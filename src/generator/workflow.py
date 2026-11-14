"""
Transaction workflow: submissions -> artefacts -> rubric grading -> feedback -> resubmission policy
-> appeals, simulated per (assignment, learner) "bundle".

Design rules
* Every outcome is derived from documented rules + latent variables (learner ability / engagement,
  assignment difficulty, hidden grader error, policy windows), not from independent coin flips.
* Totals, penalties, lateness and statuses are computed from source records.
* Each bundle uses its own RNG stream (SeededRNG.spawn), so anomaly overrides, which are applied
  AFTER all random draws, change only the targeted values and never shift unrelated rows.
* Events after the data cut-off (SNAPSHOT_AT) are not generated, so open states are genuine.
"""

import hashlib
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.config import (ScaleConfig, SNAPSHOT_AT, LATE_WINDOW_DAYS, RESUB_DEADLINE_DAYS, RESUB_LATE_CUTOFF_DAYS,
                        RESUB_SCORE_THRESHOLD, EMPTY_FILE_SHA256)
from src.generator.prng import SeededRNG, clip
from src.id_generator import IdGenerator
from src.timeutil import fmt, parse

FILE_SIZE_RANGE = {"pdf": (80e3, 4e6), "zip": (3e5, 40e6), "py": (2e3, 2e5), "docx": (5e4, 3e6)}
APPEAL_REASON_TEXT = {
    "GRADING_ERROR": "One or more criteria appear to be under-scored relative to the submitted work.",
    "RUBRIC_MISAPPLIED": "The rubric descriptors were not applied consistently to my submission.",
    "LATE_PENALTY_ERROR": "I believe the late penalty was calculated against the wrong deadline.",
    "MISSING_FILE_DISPUTE": "My files were uploaded but the grader recorded no gradable artefact.",
    "OTHER": "Requesting a second review of the overall grade.",
}
RESUB_REASON_TEXT = {
    "file": "Required artefact was missing or empty in the original attempt.",
    "score": "Requesting another attempt to address the rubric feedback and improve the score.",
}


def lateness(submitted: datetime, deadline: datetime, grace_s: int) -> Tuple[bool, int]:
    """Late iff submitted later than deadline + grace; late_days = ceil(elapsed since deadline / 24h)."""
    elapsed = (submitted - deadline).total_seconds()
    if elapsed > grace_s:
        return True, int(math.ceil(elapsed / 86400.0))
    return False, 0


def boundary_kinds(grace_s: int) -> List[Tuple[str, int]]:
    kinds = [("AT_DEADLINE", 0), ("JUST_PAST_DEADLINE_OR_GRACE", grace_s + 1), ("EXACTLY_24H_AFTER_DEADLINE", 86400),
             ("JUST_PAST_24H", 86401), ("AT_LATE_CUTOFF", LATE_WINDOW_DAYS * 86400)]
    if grace_s > 0:
        kinds.append(("AT_GRACE_EDGE", grace_s))
    return kinds


class Bundle:
    """Everything produced for one (assignment, learner) pair."""
    def __init__(self, asn_id: str, learner_id: str):
        self.asn_id, self.learner_id = asn_id, learner_id
        self.subs: List[dict] = []
        self.arts: List[dict] = []
        self.grades: List[dict] = []
        self.versions: List[dict] = []
        self.scores: List[dict] = []
        self.feedback: List[dict] = []
        self.resubs: List[dict] = []
        self.appeals: List[dict] = []
        self.labels: List[dict] = []
        self.applied: Dict[str, dict] = {}
        self._latent: Dict[str, tuple] = {}      # grade_id -> hidden grader mistake (never exported)


class WorkflowGenerator:
    def __init__(self, rng: SeededRNG, ids: IdGenerator, scale: ScaleConfig, tables: Dict[str, List[dict]]):
        self.rng, self.ids, self.scale = rng, ids, scale
        self.cmap = {c["course_id"]: c for c in tables["courses"]}
        self.amap = {a["assignment_id"]: a for a in tables["assignments"]}
        self.lmap = {l["learner_id"]: l for l in tables["learners"]}
        self.enrollments = tables["enrollments"]
        self.enr_by_course = defaultdict(list)
        for e in self.enrollments:
            self.enr_by_course[e["course_id"]].append(e)
        self.t = {}
        for a in tables["assignments"]:
            self.t[a["assignment_id"]] = {
                "pub": parse(a["published_at_utc"]) if a["published_at_utc"] else None,
                "due": parse(a["due_at_utc"]), "cutoff": parse(a["late_cutoff_utc"]),
                "grace": a["grace_period_minutes"] * 60,
            }
        self.rub_by_asn = defaultdict(list)
        for r in sorted(tables["rubrics"], key=lambda x: (x["assignment_id"], x["version_no"])):
            self.rub_by_asn[r["assignment_id"]].append((r, parse(r["effective_from_utc"])))
        self.crit_by_rub = defaultdict(list)
        for c in sorted(tables["rubric_criteria"], key=lambda x: (x["rubric_id"], x["sequence_no"])):
            self.crit_by_rub[c["rubric_id"]].append(c)
        self.course_staff = defaultdict(list)
        for cs in tables["course_staff"]:
            self.course_staff[cs["course_id"]].append(cs)
        staff = tables["staff"]
        self.support = [s["staff_id"] for s in staff if s["role"] == "SUPPORT_STAFF" and s["status"] == "ACTIVE"]
        self.admins = [s["staff_id"] for s in staff if s["role"] == "ACADEMIC_ADMIN" and s["status"] == "ACTIVE"]
        self._lat: Dict[str, Tuple[float, float]] = {}
        self._diff: Dict[str, float] = {}
        self._hard: Dict[str, float] = {}

    # ---- latent variables (never exported) ----
    def latent(self, lid: str) -> Tuple[float, float]:
        if lid not in self._lat:
            r = self.rng.spawn("latent", lid)
            self._lat[lid] = (clip(r.gauss(0.79, 0.11), 0.35, 0.97), clip(r.betavariate(2.6, 1.4), 0.08, 1.0))
        return self._lat[lid]

    def criterion_hardness(self, name: str) -> float:
        """Stable per-criterion difficulty (e.g. 'Testing' is consistently harder than 'Documentation')."""
        if name not in self._hard:
            self._hard[name] = self.rng.spawn("criterion-hardness", name).gauss(0.0, 0.05)
        return self._hard[name]

    def difficulty(self, aid: str) -> float:
        if aid not in self._diff:
            self._diff[aid] = self.rng.spawn("difficulty", aid).gauss(0.0, 0.04)
        return self._diff[aid]

    def rubric_at(self, aid: str, when: datetime) -> dict:
        chosen = self.rub_by_asn[aid][0][0]
        for r, eff_from in self.rub_by_asn[aid]:
            if eff_from <= when:
                chosen = r
        return chosen

    # ---- candidate (assignment, enrolment) pairs ----
    def candidate_pairs(self) -> List[Tuple[dict, dict]]:
        """Valid pairs ordered by a deterministic weighted-random priority (engaged learners first)."""
        keyed = []
        sel = self.rng.spawn("select")
        for aid, a in self.amap.items():
            t = self.t[aid]
            if a["status"] == "DRAFT":
                continue
            for e in self.enr_by_course[a["course_id"]]:
                if e["enrollment_status"] == "AUDIT":
                    continue
                L = self.lmap[e["learner_id"]]
                start = max(t["pub"], parse(e["enrolled_at_utc"]) + timedelta(hours=2))
                limit = t["due"]
                if e["enrollment_status"] == "DROPPED":
                    limit = min(limit, parse(e["effective_to_utc"]))
                if L["status_effective_from_utc"]:
                    limit = min(limit, parse(L["status_effective_from_utc"]))
                if start + timedelta(hours=1) >= limit:
                    continue
                w = self.latent(L["learner_id"])[1] ** 1.5
                keyed.append((sel.random() ** (1.0 / w), aid, e["learner_id"], a, e))
        keyed.sort(key=lambda k: (-k[0], k[1], k[2]))
        return [(k[3], k[4]) for k in keyed]

    # ---- bundle construction ----
    def build_bundle(self, asn: dict, learner: dict, enr: Optional[dict], cap: int = 10 ** 9,
                     ov: Optional[dict] = None) -> Optional[Bundle]:
        ov = ov or {}
        aid, lid = asn["assignment_id"], learner["learner_id"]
        b = Bundle(aid, lid)
        r = self.rng.spawn("bundle", aid, lid)
        ar = self.rng.spawn("anomaly", aid, lid)           # separate stream: anomalies never shift baseline draws
        t = self.t[aid]
        course = self.cmap[asn["course_id"]]
        cstaff = self.course_staff[course["course_id"]]
        lead = course["instructor_id"]
        graders = [s["staff_id"] for s in cstaff if s["course_role"] == "GRADER"] or [lead]
        theta, eng = self.latent(lid)
        delta = self.difficulty(aid)
        mx, rate, grace = asn["max_score"], asn["late_penalty_per_day"], t["grace"]
        window_s = asn["appeal_window_days"] * 86400
        if ov.get("unenrolled"):
            cap = 1

        # ---- attempt-1 timing ----
        if enr:
            start = max(t["pub"], parse(enr["enrolled_at_utc"]) + timedelta(hours=2))
            limit = t["due"]
            if enr["enrollment_status"] == "DROPPED":
                limit = min(limit, parse(enr["effective_to_utc"]))
        else:
            start, limit = t["pub"] + timedelta(days=1), t["due"]
        if learner["status_effective_from_utc"]:
            limit = min(limit, parse(learner["status_effective_from_utc"]))
        curtailed = limit < t["due"]
        # after a drop / suspension / graduation the learner can no longer submit anything for this course
        block_at = None
        if enr and enr["enrollment_status"] == "DROPPED":
            block_at = parse(enr["effective_to_utc"])
        if learner["status_effective_from_utc"]:
            eff = parse(learner["status_effective_from_utc"])
            block_at = eff if block_at is None else min(block_at, eff)
        p_late = clip(0.07 + 0.55 * (0.9 - theta), 0.02, 0.45)
        roll_late, u_on, exp_s = r.random(), r.betavariate(2.5, 1.0), r.expovariate(1.0 / (30 * 3600))
        roll_boundary, roll_kind = r.random(), r.random()
        fr, fk, nf = r.random(), r.random(), r.random()
        boundary = None
        if not curtailed and not ov.get("unenrolled") and roll_boundary < self.scale.boundary_rate:
            kinds = boundary_kinds(grace)
            boundary = kinds[int(roll_kind * len(kinds)) % len(kinds)]
        if boundary and block_at is not None and t["due"] + timedelta(seconds=boundary[1]) >= block_at:
            boundary = None
        late_dt = t["due"] + timedelta(seconds=min(grace + 60 + int(exp_s), LATE_WINDOW_DAYS * 86400))
        if boundary:
            sub_dt = t["due"] + timedelta(seconds=boundary[1])
        elif not curtailed and roll_late < p_late and (block_at is None or late_dt < block_at):
            sub_dt = late_dt
        else:
            sub_dt = start + timedelta(seconds=int((limit - start).total_seconds() * u_on))
        if sub_dt > SNAPSHOT_AT:
            return None                                    # learner has not submitted yet at the cut-off
        expected_files = 1 if nf < 0.55 else 2
        file_status = "COMPLETE"
        if fr < self.scale.file_issue_rate:
            file_status = "MISSING_FILE" if fk < 0.6 else "EMPTY_FILE"

        # ---- attempt chain ----
        attempt, prev_sub, prev_pts, prev_rubric, prev_final = 1, None, None, None, None
        deadline, boost = t["due"], 0.0
        resub_due = None
        chain_open = False
        while True:
            sub = self._make_submission(b, asn, lid, enr, attempt, prev_sub, sub_dt, deadline, grace,
                                        expected_files, file_status, r, t)
            if ov.get("unenrolled"):
                b.applied["unenrolled"] = {}
                b.labels.append({
                    "label_class": "ANOMALY", "issue_type": "UNENROLLED_LEARNER_SUBMISSION", "entity_name": "Submission",
                    "record_id": sub["submission_id"], "field_name": "enrollment_id",
                    "expected_value": f"active enrolment of {lid} in {asn['course_id']}", "actual_value": "NO_ENROLLMENT",
                    "expected_decision": "REJECT_SUBMISSION",
                    "description": f"Submission by learner {lid}, who is not enrolled in course {asn['course_id']}.",
                })
            if attempt == 1 and boundary:
                exp_late = sub_dt - t["due"]
                el = exp_late.total_seconds()
                late_exp, days_exp = (True, int(math.ceil(el / 86400.0))) if el > grace else (False, 0)
                b.labels.append({
                    "label_class": "BOUNDARY_VALID", "issue_type": f"BOUNDARY_{boundary[0]}", "entity_name": "Submission",
                    "record_id": sub["submission_id"], "field_name": "late_days", "expected_value": str(days_exp),
                    "actual_value": str(sub["late_days"]),
                    "expected_decision": "ACCEPTED_LATE_PENALTY_%d_DAYS" % days_exp if late_exp else "ACCEPTED_ON_TIME",
                    "description": f"Submission exactly {boundary[1]}s after the deadline (grace {grace}s): valid boundary case.",
                })
            if file_status != "COMPLETE" and attempt == 1:
                b.labels.append({
                    "label_class": "EXCEPTION_PATH", "issue_type": file_status, "entity_name": "Submission",
                    "record_id": sub["submission_id"], "field_name": "file_check_status", "expected_value": file_status,
                    "actual_value": sub["file_check_status"], "expected_decision": "GRADE_ZERO_AND_ELIGIBLE_FOR_RESUBMISSION",
                    "description": "Submission without a gradable artefact: scored 0, resubmission-eligible.",
                })
            info = self._grade_attempt(b, sub, asn, course, lead, graders, theta, delta, boost, prev_pts, prev_rubric,
                                       prev_final, r, ar, ov, attempt, file_status)
            if info is None:
                break                                      # grading falls after the cut-off -> stays SUBMITTED
            prev_sub = sub
            prev_pts, prev_rubric, prev_final = info["pts"], info["rubric_id"], info["grade"]["final_score"]

            # ---- resubmission policy ----
            forced = bool(ov.get("force_resub")) and attempt == 1 and not asn["allow_resubmission"]
            max_attempts = 1 + (asn["max_resubmissions"] if asn["allow_resubmission"] else (1 if forced else 0))
            q, d_roll = r.random(), r.random()
            d_a, d_b, dec_h = r.uniform(0.5, 5.0), r.uniform(5.2, 9.0), r.uniform(4.0, 48.0)
            act_roll, pos, late_roll, late_h = r.random(), r.betavariate(2.0, 1.3), r.random(), r.uniform(1.0, 48.0)
            nfr = r.random()
            if len(b.subs) >= cap or attempt >= max_attempts or ov.get("unenrolled"):
                break
            clean_final = info["clean_final"]
            has_file_issue = sub["file_check_status"] != "COMPLETE"
            below = clean_final < RESUB_SCORE_THRESHOLD
            p_req = 0.80 if has_file_issue else ((0.12 + 0.40 * eng) if below else 0.03)
            if not forced and q >= p_req:
                break
            delay_days = d_a if (d_roll < 0.85 or forced) else d_b
            requested = info["graded_at"] + timedelta(days=delay_days)
            if requested > SNAPSHOT_AT or (block_at is not None and requested >= block_at):
                break
            decided = requested + timedelta(hours=dec_h)
            within = (requested - info["graded_at"]).total_seconds() <= asn["resubmission_window_days"] * 86400
            row = {"resubmission_id": None, "original_submission_id": sub["submission_id"], "new_submission_id": None,
                   "requested_at_utc": fmt(requested),
                   "request_reason": RESUB_REASON_TEXT["file" if has_file_issue else "score"],
                   "status": "REQUESTED", "decision_reason": None, "decided_by": None, "decided_at_utc": None,
                   "resubmission_due_utc": None, "resubmitted_at_utc": None, "policy_compliant": True}
            b.resubs.append(row)
            if forced:
                approved, reason, compliant = True, ("APPROVED_MISSING_FILE" if has_file_issue else "APPROVED_SCORE_BELOW_THRESHOLD"), True
            elif not within:
                approved, reason, compliant = False, "DENIED_OUTSIDE_WINDOW", False
            elif not (has_file_issue or below):
                approved, reason, compliant = False, "DENIED_SCORE_ABOVE_THRESHOLD", False
            else:
                approved, reason, compliant = True, ("APPROVED_MISSING_FILE" if has_file_issue else "APPROVED_SCORE_BELOW_THRESHOLD"), True
            if decided > SNAPSHOT_AT:
                chain_open = True
                row["policy_compliant"] = compliant
                break
            row.update({"status": "APPROVED" if approved else "DENIED", "decision_reason": reason, "decided_by": lead,
                        "decided_at_utc": fmt(decided), "policy_compliant": compliant})
            if not approved:
                b.labels.append({
                    "label_class": "EXCEPTION_PATH", "issue_type": "RESUBMISSION_" + reason, "entity_name": "Resubmission",
                    "ref": (row, "resubmission_id"), "field_name": "status", "expected_value": "DENIED",
                    "actual_value": "DENIED", "expected_decision": "DENY_RESUBMISSION",
                    "description": "Resubmission request correctly denied by policy (%s)." % reason,
                })
                break
            due = decided + timedelta(days=RESUB_DEADLINE_DAYS)
            row["resubmission_due_utc"] = fmt(due)
            acts = act_roll < (0.60 + 0.35 * eng) or forced
            new_dt = (decided + timedelta(seconds=int((due - decided).total_seconds() * pos))) if (late_roll < 0.85 or forced) \
                else due + timedelta(hours=late_h)
            if block_at is not None and new_dt >= block_at:
                acts = False                                   # learner left before the attempt could be made
            if not acts or new_dt > SNAPSHOT_AT:
                if due + timedelta(days=RESUB_LATE_CUTOFF_DAYS) <= SNAPSHOT_AT and not acts:
                    row["status"] = "EXPIRED"
                    b.labels.append({
                        "label_class": "EXCEPTION_PATH", "issue_type": "RESUBMISSION_EXPIRED", "entity_name": "Resubmission",
                        "ref": (row, "resubmission_id"), "field_name": "status", "expected_value": "EXPIRED",
                        "actual_value": "EXPIRED", "expected_decision": "EXPIRE_UNUSED_APPROVAL",
                        "description": "Approved resubmission never used before the deadline: expired.",
                    })
                else:
                    chain_open = True                      # window still open at the data cut-off
                break
            attempt += 1
            sub_dt, deadline, boost = new_dt, due, 0.10
            row["resubmitted_at_utc"] = fmt(new_dt)
            file_status = "COMPLETE" if nfr >= self.scale.file_issue_rate / 2 else "MISSING_FILE"
            if forced:
                b.applied["force_resub"] = {"original": sub["submission_id"]}
                b.labels.append({
                    "label_class": "ANOMALY", "issue_type": "RESUBMISSION_POLICY_VIOLATION", "entity_name": "Resubmission",
                    "ref": (row, "resubmission_id"), "field_name": "status",
                    "expected_value": "no resubmission (assignment.allow_resubmission = false)",
                    "actual_value": "APPROVED with attempt 2 created", "expected_decision": "DENY_RESUBMISSION",
                    "description": f"Resubmission approved although assignment {aid} does not allow resubmission.",
                })

        # ---- appeal on the last grade of the chain ----
        if not chain_open and not ov.get("unenrolled"):
            # an appeal on the last grade can only follow the last resubmission decision: otherwise a grade
            # changed by the appeal would contradict the eligibility on which that decision was taken
            floor = parse(b.resubs[-1]["decided_at_utc"]) if b.resubs and b.resubs[-1]["decided_at_utc"] else None
            self._appeal(b, asn, lead, r, ar, ov, window_s, floor)
        self._finalize_statuses(b)
        return b

    # ---- pieces ----
    def _make_submission(self, b, asn, lid, enr, attempt, prev_sub, sub_dt, deadline, grace, expected_files,
                         file_status, r, t) -> dict:
        aid = asn["assignment_id"]
        sid = self.ids.submission_id(aid, lid, attempt)
        is_late, late_days = lateness(sub_dt, deadline, grace)
        sub = {
            "submission_id": sid, "assignment_id": aid, "learner_id": lid,
            "enrollment_id": enr["enrollment_id"] if enr else None, "attempt_number": attempt,
            "previous_submission_id": prev_sub["submission_id"] if prev_sub else None,
            "submitted_at_utc": fmt(sub_dt), "applicable_deadline_utc": fmt(deadline),
            "is_late": is_late, "late_days": late_days, "expected_file_count": expected_files,
            "file_check_status": file_status, "status": "SUBMITTED",
        }
        b.subs.append(sub)
        n_art = 0 if file_status == "MISSING_FILE" else expected_files
        for seq in range(1, n_art + 1):
            ext = r.choice(["pdf", "zip", "py", "docx"])
            lo, hi = FILE_SIZE_RANGE[ext]
            size = int(math.exp(r.uniform(math.log(lo), math.log(hi))))
            empty = file_status == "EMPTY_FILE" and seq == 1
            if empty:
                size = 0
            fname = f"{'revised' if attempt > 1 else 'solution'}_{seq}_{lid}.{ext}"
            sha = EMPTY_FILE_SHA256 if empty else hashlib.sha256(f"{sid}|{seq}|{size}".encode()).hexdigest()
            upload = sub_dt - timedelta(seconds=r.randint(10, 600))
            if t["pub"] and upload < t["pub"]:
                upload = t["pub"]
            b.arts.append({
                "artifact_id": self.ids.artifact_id(sid, seq), "submission_id": sid, "sequence_no": seq,
                "file_name": fname, "file_size_bytes": size, "file_type": ext,
                "storage_uri": f"s3://ams-artifacts/{aid}/{sid}/{fname}", "checksum_sha256": sha,
                "uploaded_at_utc": fmt(min(upload, sub_dt)),
            })
        return sub

    def _grade_attempt(self, b, sub, asn, course, lead, graders, theta, delta, boost, prev_pts, prev_rubric,
                       prev_final, r, ar, ov, attempt, file_status) -> Optional[dict]:
        aid = asn["assignment_id"]
        sub_dt = parse(sub["submitted_at_utc"])
        turnaround_h = clip(r.lognormvariate(math.log(72.0), 0.55), 12.0, 240.0)
        grader_roll, grader_pick = r.random(), r.choice(graders)
        err_roll, err_idx, err_cut = r.random(), r.random(), r.uniform(0.15, 0.40)
        graded_at = sub_dt + timedelta(seconds=int(turnaround_h * 3600))
        rubric = self.rubric_at(aid, graded_at)
        crits = self.crit_by_rub[rubric["rubric_id"]]
        noise = [r.gauss(0.0, 0.07) for _ in crits]
        hard = [self.criterion_hardness(c["criterion_name"]) + r.gauss(0.0, 0.02) for c in crits]
        if graded_at > SNAPSHOT_AT:
            return None
        grader = lead if grader_roll < 0.70 else grader_pick
        mx, rate = asn["max_score"], asn["late_penalty_per_day"]
        use_prev = prev_pts is not None and prev_rubric == rubric["rubric_id"]
        pts, true_pts = [], []
        for i, c in enumerate(crits):
            cm = c["max_points"]
            if file_status != "COMPLETE":
                p = 0.0
            else:
                frac = clip(theta - delta - hard[i] + boost + noise[i], 0.0, 1.0)
                p = min(cm, round(frac * cm * 2.0) / 2.0)
                if use_prev:
                    p = max(p, prev_pts[i])
            pts.append(p)
        # latent grader mistake: one criterion under-scored; it is what justified appeals later reveal
        latent = None
        if file_status == "COMPLETE" and err_roll < self.scale.grading_error_rate:
            idx = min(int(err_idx * len(crits)), len(crits) - 1)
            cut = min(round(err_cut * crits[idx]["max_points"] * 2.0) / 2.0, pts[idx])
            if cut >= 0.5:
                latent = (idx, cut)
        awarded = list(pts)
        if latent:
            awarded[latent[0]] = pts[latent[0]] - latent[1]
        clean_raw = round(sum(awarded), 2)
        clean_single = round(min(clean_raw, sub["late_days"] * rate), 2) if sub["late_days"] > 0 else 0.0
        clean_final = round(max(0.0, clean_raw - clean_single), 2)

        # ---- anomaly overrides (post-hoc; no baseline RNG consumed) ----
        out_pts, penalty = list(awarded), clean_single
        if ov.get("over_max") and attempt == 1 and file_status == "COMPLETE":
            extra = (mx - clean_raw) + round(ar.uniform(2.0, 10.0) * 2.0) / 2.0
            out_pts[0] = round(out_pts[0] + extra, 2)
            b.applied["over_max"] = {"clean_raw": clean_raw}
        raw = round(sum(out_pts), 2)
        if ov.get("double_penalty") and attempt == 1 and sub["late_days"] > 0 and raw > clean_single:
            doubled = round(min(raw, 2.0 * clean_single), 2)
            if doubled != clean_single:
                penalty = doubled
                b.applied["double_penalty"] = {"expected": clean_single, "actual": doubled, "late_days": sub["late_days"]}
        elif "over_max" in b.applied:
            penalty = round(min(raw, sub["late_days"] * rate), 2) if sub["late_days"] > 0 else 0.0
        final = round(max(0.0, raw - penalty), 2)

        sid = sub["submission_id"]
        gid = self.ids.grade_id(sid)
        grade = {
            "grade_id": gid, "submission_id": sid, "rubric_id": rubric["rubric_id"], "grader_id": grader,
            "raw_score": raw, "late_penalty_points": penalty, "adjustment_points": 0.0, "final_score": final,
            "graded_at_utc": fmt(graded_at), "grade_status": "PUBLISHED", "current_version": 1,
        }
        b.grades.append(grade)
        if latent:
            b._latent[gid] = latent
        b.versions.append({
            "grade_version_id": self.ids.grade_version_id(gid, 1), "grade_id": gid, "version_no": 1, "raw_score": raw,
            "late_penalty_points": penalty, "adjustment_points": 0.0, "final_score": final, "change_type": "INITIAL",
            "changed_by": grader, "changed_at_utc": fmt(graded_at), "appeal_id": None,
        })
        for i, c in enumerate(crits):
            b.scores.append({
                "score_id": self.ids.criterion_score_id(gid, i + 1), "grade_id": gid, "criterion_id": c["criterion_id"],
                "awarded_points": out_pts[i],
                "criterion_comment": f"Awarded {out_pts[i]:.1f}/{c['max_points']:.1f} for {c['criterion_name']}.",
            })
        comment, strengths, growth = make_feedback(out_pts, crits, final, mx, penalty, sub["late_days"], file_status,
                                                   prev_final if attempt > 1 else None)
        b.feedback.append({
            "feedback_id": self.ids.feedback_id(sid), "submission_id": sid, "instructor_id": grader,
            "qualitative_comment": comment, "strengths": strengths, "growth_areas": growth,
            "provided_at_utc": fmt(graded_at),
        })
        if attempt == 1 and "over_max" in b.applied:
            b.labels.append({
                "label_class": "ANOMALY", "issue_type": "GRADE_EXCEEDS_MAX", "entity_name": "Grade", "record_id": gid,
                "field_name": "raw_score", "expected_value": f"<= {mx:.2f} (clean value {clean_raw:.2f})",
                "actual_value": f"{raw:.2f}", "expected_decision": "REJECT_GRADE_AND_RESCORE",
                "description": f"Grade {gid} raw_score {raw:.2f} exceeds the rubric maximum of {mx:.2f}.",
            })
        if attempt == 1 and "double_penalty" in b.applied:
            a = b.applied["double_penalty"]
            b.labels.append({
                "label_class": "ANOMALY", "issue_type": "DOUBLE_LATE_PENALTY", "entity_name": "Grade", "record_id": gid,
                "field_name": "late_penalty_points", "expected_value": f"{a['expected']:.2f}", "actual_value": f"{a['actual']:.2f}",
                "expected_decision": "CORRECT_PENALTY_TO_SINGLE_DEDUCTION",
                "description": f"Late penalty applied twice for {a['late_days']} late day(s).",
            })
        return {"grade": grade, "pts": awarded, "rubric_id": rubric["rubric_id"], "clean_final": clean_final,
                "graded_at": graded_at, "latent": latent, "crits": crits}

    def _appeal(self, b, asn, lead, r, ar, ov, window_s, floor=None):
        info_grade = b.grades[-1] if b.grades else None
        last = b.subs[-1]
        # always draw (stable stream)
        ap_roll, out_roll = r.random(), r.random()
        d_in, d_out = r.uniform(0.2, asn["appeal_window_days"] - 0.1), r.uniform(asn["appeal_window_days"] + 0.1, asn["appeal_window_days"] + 5.0)
        reason_pick, rv_h, dc_h = r.random(), r.uniform(4.0, 72.0), r.uniform(24.0, 144.0)
        admin, intake = r.choice(self.admins), r.choice(self.support)
        if info_grade is None or info_grade["submission_id"] != last["submission_id"]:
            return
        g = info_grade
        graded_at = parse(g["graded_at_utc"])
        latent = self._latent_for(b, g)
        file_issue = last["file_check_status"] != "COMPLETE"
        if latent:
            p = 0.30
        elif file_issue:
            p = 0.15
        elif g["late_penalty_points"] > 0:
            p = 0.06
        elif g["final_score"] < 60:
            p = 0.07
        else:
            p = 0.012
        forced = bool(ov.get("late_appeal"))
        if forced:
            filed = graded_at + timedelta(days=asn["appeal_window_days"] + 0.5 + ar.uniform(0.0, 4.0))
        elif ap_roll < p:
            filed = graded_at + timedelta(days=d_out if out_roll < 0.10 else d_in)
        else:
            return
        if floor is not None and filed < floor + timedelta(hours=1):
            filed = floor + timedelta(hours=1)
        if filed > SNAPSHOT_AT:
            return
        # reason code (rule-driven)
        if latent:
            code = "GRADING_ERROR" if reason_pick < 0.55 else "RUBRIC_MISAPPLIED"
        elif file_issue:
            code = "MISSING_FILE_DISPUTE"
        elif g["late_penalty_points"] > 0:
            code = "LATE_PENALTY_ERROR" if reason_pick < 0.6 else "GRADING_ERROR"
        else:
            code = ["GRADING_ERROR", "RUBRIC_MISAPPLIED", "OTHER"][int(reason_pick * 3) % 3]
        review_start = filed + timedelta(hours=rv_h)
        decided = review_start + timedelta(hours=dc_h)
        out_of_window = (filed - graded_at).total_seconds() > window_s
        before = g["final_score"]
        appeal = {"appeal_id": None, "submission_id": last["submission_id"], "grade_id": g["grade_id"],
                  "learner_id": last["learner_id"], "reason_code": code, "reason": APPEAL_REASON_TEXT[code],
                  "filed_at_utc": fmt(filed), "intake_by": intake, "status": "SUBMITTED", "original_score": before,
                  "adjusted_score": None, "reviewed_by": None, "review_started_at_utc": None, "decided_at_utc": None,
                  "decision_code": None, "resolution_notes": None}
        b.appeals.append(appeal)
        if review_start > SNAPSHOT_AT:
            if forced:
                b.appeals.pop()
            return
        appeal.update({"status": "IN_REVIEW", "reviewed_by": admin, "review_started_at_utc": fmt(review_start)})
        if decided > SNAPSHOT_AT:
            if forced:
                b.appeals.pop()
            return
        base = round(g["raw_score"] - g["late_penalty_points"], 2)
        adj = 0.0
        if out_of_window and not forced:
            decision = "REJECTED_OUT_OF_WINDOW"
        elif forced:
            adj = min(round(ar.uniform(3.0, 12.0) * 2.0) / 2.0, max(0.0, asn["max_score"] - base))
            decision = "UPHELD_GRADING_ERROR" if adj > 0 else "REJECTED_NO_ERROR"
        elif latent:
            adj = min(latent[1], max(0.0, asn["max_score"] - base))
            decision = "UPHELD_GRADING_ERROR" if adj > 0 else "REJECTED_NO_ERROR"
        else:
            decision = "REJECTED_NO_ERROR"
        upheld = decision == "UPHELD_GRADING_ERROR"
        if forced and not upheld:
            b.appeals.pop()
            return
        after = round(max(0.0, base + adj), 2) if upheld else before
        notes = {
            "UPHELD_GRADING_ERROR": f"Appeal upheld: a scoring error was confirmed on re-review; grade adjusted by +{adj:.1f} points.",
            "REJECTED_NO_ERROR": "Appeal rejected: re-review found the rubric was applied correctly.",
            "REJECTED_OUT_OF_WINDOW": f"Appeal rejected: filed after the {asn['appeal_window_days']}-day appeal window.",
        }[decision]
        appeal.update({"status": "UPHELD" if upheld else "REJECTED", "adjusted_score": after,
                       "decided_at_utc": fmt(decided), "decision_code": decision, "resolution_notes": notes})
        if upheld:
            g.update({"adjustment_points": adj, "final_score": after, "grade_status": "REVISED", "current_version": 2})
            skip_history = bool(ov.get("no_audit")) and not forced
            if not skip_history:
                b.versions.append({
                    "grade_version_id": self.ids.grade_version_id(g["grade_id"], 2), "grade_id": g["grade_id"],
                    "version_no": 2, "raw_score": g["raw_score"], "late_penalty_points": g["late_penalty_points"],
                    "adjustment_points": adj, "final_score": after, "change_type": "APPEAL_ADJUSTMENT",
                    "changed_by": admin, "changed_at_utc": fmt(decided), "appeal_id": appeal,   # resolved at commit
                })
            if skip_history:
                b.applied["no_audit"] = {"appeal": appeal}
                b.labels.append({
                    "label_class": "ANOMALY", "issue_type": "APPEAL_NO_AUDIT_LOG", "entity_name": "Appeal",
                    "ref": (appeal, "appeal_id"), "field_name": "grade_versions/audit_logs",
                    "expected_value": "grade_versions v2 + GRADE_MUTATE audit event present",
                    "actual_value": "MISSING_HISTORY", "expected_decision": "FLAG_UNAUDITED_GRADE_CHANGE",
                    "description": f"Appeal upheld and grade {g['grade_id']} changed to {after:.2f} with no audit/version history.",
                })
            elif forced:
                b.applied["late_appeal"] = {"appeal": appeal}
                b.labels.append({
                    "label_class": "ANOMALY", "issue_type": "APPEAL_OUTSIDE_WINDOW_UPHELD", "entity_name": "Appeal",
                    "ref": (appeal, "appeal_id"), "field_name": "decision_code", "expected_value": "REJECTED_OUT_OF_WINDOW",
                    "actual_value": "UPHELD_GRADING_ERROR", "expected_decision": "REJECT_LATE_APPEAL",
                    "description": f"Appeal filed {(filed - graded_at).total_seconds() / 86400:.1f} days after grading "
                                   f"(window {asn['appeal_window_days']} days) but upheld.",
                })
            else:
                b.labels.append({
                    "label_class": "EXCEPTION_PATH", "issue_type": "APPEAL_UPHELD_GRADE_REVISED", "entity_name": "Appeal",
                    "ref": (appeal, "appeal_id"), "field_name": "decision_code", "expected_value": "UPHELD_GRADING_ERROR",
                    "actual_value": "UPHELD_GRADING_ERROR", "expected_decision": "REVISE_GRADE_WITH_AUDIT_TRAIL",
                    "description": "Appeal upheld; grade revised with full version + audit history.",
                })
        elif decision == "REJECTED_OUT_OF_WINDOW":
            b.labels.append({
                "label_class": "EXCEPTION_PATH", "issue_type": "APPEAL_REJECTED_OUT_OF_WINDOW", "entity_name": "Appeal",
                "ref": (appeal, "appeal_id"), "field_name": "decision_code", "expected_value": "REJECTED_OUT_OF_WINDOW",
                "actual_value": "REJECTED_OUT_OF_WINDOW", "expected_decision": "REJECT_LATE_APPEAL",
                "description": "Appeal filed after the window and correctly rejected.",
            })

    @staticmethod
    def _latent_for(b: Bundle, g: dict):
        """Hidden grader mistake attached to the grade (None when the grade is correct)."""
        return b._latent.get(g["grade_id"])

    @staticmethod
    def _finalize_statuses(b: Bundle) -> None:
        open_appeal = any(a["status"] in ("SUBMITTED", "IN_REVIEW") for a in b.appeals)
        graded = {g["submission_id"] for g in b.grades}
        for i, s in enumerate(b.subs):
            if i < len(b.subs) - 1:
                s["status"] = "RESUBMITTED"
            elif s["submission_id"] not in graded:
                s["status"] = "SUBMITTED"
            else:
                s["status"] = "APPEALED" if open_appeal else "GRADED"
        for rs in b.resubs:
            rs.pop("_new_attempt", None)


# ---- feedback text (derived from the scored data) ----------------------------------------------
def make_feedback(pts, crits, final, mx, penalty, late_days, file_status, prev_final):
    if file_status != "COMPLETE":
        return ("No gradable artefact was received, so no rubric criterion could be scored.",
                "None identified: nothing to assess.",
                "Upload the complete deliverable; a resubmission may be requested within the policy window.")
    pct = final / mx * 100.0
    tier = ("Outstanding work meeting the rubric almost completely." if pct >= 88 else
            "Solid work; most criteria are met." if pct >= 72 else
            "Acceptable, but several criteria need work." if pct >= 58 else
            "Substantial gaps against the rubric; remediation advised.")
    ratios = [p / c["max_points"] for p, c in zip(pts, crits)]
    hi, lo = max(range(len(ratios)), key=lambda i: ratios[i]), min(range(len(ratios)), key=lambda i: ratios[i])
    comment = tier
    if penalty > 0:
        comment += f" A late penalty of {penalty:.1f} points was applied ({late_days} day(s) late)."
    if prev_final is not None:
        comment += f" Improved from {prev_final:.1f} on the previous attempt."
    return (comment,
            f"Strongest criterion: {crits[hi]['criterion_name']} ({pts[hi]:.1f}/{crits[hi]['max_points']:.1f}).",
            f"Weakest criterion: {crits[lo]['criterion_name']} ({pts[lo]:.1f}/{crits[lo]['max_points']:.1f}).")
