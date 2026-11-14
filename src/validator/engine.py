"""
Eight-stage validation engine.

Stages 1-7 never read the ground truth. Every violation is tagged with the anomaly type it
corresponds to (if any); a violation with no tag is an UNEXPECTED defect and fails the run.
Stage 8 then compares the tagged detections to the separate ground-truth file (precision/recall per
anomaly type) and verifies the valid exception-path / boundary labels.
"""

import re
from collections import Counter, defaultdict
from datetime import timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from src.config import (SNAPSHOT_AT, LATE_WINDOW_DAYS, RESUB_DEADLINE_DAYS, RESUB_LATE_CUTOFF_DAYS,
                        RESUB_SCORE_THRESHOLD)
from src.schema import (ANOMALY_TYPES, GROUND_TRUTH_TABLE, PAT, TABLE_BY_NAME, TABLES, Table)
from src.timeutil import local_to_utc, parse as _parse, parse_local, utc_offset_minutes

parse = lru_cache(maxsize=None)(_parse)

STAGE_NAMES = {
    1: "Primary keys, ID formats and ID derivation",
    2: "Foreign keys and join integrity (incl. enrolment window)",
    3: "Domain: required fields, enums, ranges, cross-field rules",
    4: "Chronology and data cut-off",
    5: "Arithmetic reconciliation, rubric scoring, time-zone due logic",
    6: "Lifecycle state machines, version history and policy rules",
    7: "Duplicate and contiguity checks",
    8: "Ground-truth reconciliation (precision / recall)",
}

TRANSITIONS = {
    "Assignment": {(None, "DRAFT"), ("DRAFT", "PUBLISHED"), ("PUBLISHED", "CLOSED")},
    "Rubric": {(None, "ACTIVE"), ("ACTIVE", "SUPERSEDED")},
    "Enrollment": {(None, "ENROLLED"), (None, "AUDIT"), ("ENROLLED", "DROPPED"), ("ENROLLED", "COMPLETED")},
    "Submission": {(None, "SUBMITTED"), ("SUBMITTED", "SUBMITTED"), ("SUBMITTED", "GRADED"), ("GRADED", "RESUBMITTED"),
                   ("GRADED", "APPEALED"), ("APPEALED", "GRADED")},
    "Grade": {(None, "PUBLISHED"), ("PUBLISHED", "REVISED")},
    "Resubmission": {(None, "REQUESTED"), ("REQUESTED", "APPROVED"), ("REQUESTED", "DENIED"), ("APPROVED", "EXPIRED")},
    "Appeal": {(None, "SUBMITTED"), ("SUBMITTED", "SUBMITTED"), ("SUBMITTED", "IN_REVIEW"), ("IN_REVIEW", "UPHELD"),
               ("IN_REVIEW", "REJECTED")},
}
ENTITY_TABLE = {"Course": "courses", "Assignment": "assignments", "Rubric": "rubrics", "Enrollment": "enrollments",
                "Submission": "submissions", "Grade": "grades", "Resubmission": "resubmissions", "Appeal": "appeals"}
STATUS_COL = {"Assignment": "status", "Rubric": "status", "Enrollment": "enrollment_status", "Submission": "status",
              "Resubmission": "status", "Appeal": "status"}
TS_EVENT_COLS = {  # timestamps that are real events and so cannot be after the data cut-off
    "courses": ["created_at_utc"], "learners": ["registration_date_utc", "status_effective_from_utc"],
    "enrollments": ["enrolled_at_utc", "effective_to_utc"], "assignments": ["created_at_utc", "published_at_utc"],
    "rubrics": ["created_at_utc"], "submissions": ["submitted_at_utc"], "submission_artifacts": ["uploaded_at_utc"],
    "grades": ["graded_at_utc"], "grade_versions": ["changed_at_utc"], "feedback": ["provided_at_utc"],
    "resubmissions": ["requested_at_utc", "decided_at_utc", "resubmitted_at_utc"],
    "appeals": ["filed_at_utc", "review_started_at_utc", "decided_at_utc"], "audit_logs": ["timestamp_utc"],
}


class Validator:
    def __init__(self, T: Dict[str, List[dict]], ground_truth: Optional[List[dict]] = None):
        self.T, self.gt = T, ground_truth
        self.checks: Dict[int, int] = Counter()
        self.violations: List[dict] = []
        self.stage = 0
        # indexes
        self.by = {t.name: {r[t.pk]: r for r in T[t.name]} for t in TABLES}
        self.sub, self.asn, self.grade = self.by["submissions"], self.by["assignments"], self.by["grades"]
        self.grade_by_sub = {g["submission_id"]: g for g in T["grades"]}
        self.versions = defaultdict(list)
        for v in T["grade_versions"]:
            self.versions[v["grade_id"]].append(v)
        self.crit_by_rub = defaultdict(list)
        for c in T["rubric_criteria"]:
            self.crit_by_rub[c["rubric_id"]].append(c)
        self.scores_by_grade = defaultdict(list)
        for s in T["grade_criterion_scores"]:
            self.scores_by_grade[s["grade_id"]].append(s)
        self.arts_by_sub = defaultdict(list)
        for a in T["submission_artifacts"]:
            self.arts_by_sub[a["submission_id"]].append(a)
        self.appeal_by_grade = {a["grade_id"]: a for a in T["appeals"]}
        self.resub_by_orig = {r["original_submission_id"]: r for r in T["resubmissions"]}
        self.resub_by_new = {r["new_submission_id"]: r for r in T["resubmissions"] if r["new_submission_id"]}
        self.next_sub = {s["previous_submission_id"]: s for s in T["submissions"] if s["previous_submission_id"]}
        self.enr_by_pair = {(e["course_id"], e["learner_id"]): e for e in T["enrollments"]}
        self.rub_by_asn = defaultdict(list)
        for r in T["rubrics"]:
            self.rub_by_asn[r["assignment_id"]].append(r)
        self.cstaff = defaultdict(dict)
        for cs in T["course_staff"]:
            self.cstaff[cs["course_id"]][cs["staff_id"]] = cs
        self.audit_by_entity = defaultdict(list)
        for a in T["audit_logs"]:
            self.audit_by_entity[(a["entity_name"], a["entity_id"])].append(a)

    # ---- helpers ----
    def chk(self, ok: bool, rule: str, table: str, rid: Any, msg: str, anomaly: Optional[str] = None) -> bool:
        self.checks[self.stage] += 1
        if not ok:
            self.violations.append({"stage": self.stage, "rule": rule, "table": table, "record_id": rid,
                                    "message": msg, "anomaly": anomaly})
        return ok

    def late_calc(self, sub: dict, deadline, grace_min: int) -> Tuple[bool, int]:
        el = (parse(sub["submitted_at_utc"]) - deadline).total_seconds()
        if el > grace_min * 60:
            import math
            return True, int(math.ceil(el / 86400.0))
        return False, 0

    # ---- driver ----
    def run(self) -> Dict[str, Any]:
        fns = [self.s1_keys, self.s2_foreign_keys, self.s3_domain, self.s4_chronology, self.s5_arithmetic,
               self.s6_lifecycle, self.s7_duplicates]
        for i, fn in enumerate(fns, start=1):
            self.stage = i
            try:
                fn()
            except (KeyError, TypeError, ValueError, AttributeError, StopIteration) as exc:
                # Corrupt data (typically an orphan key reported by stage 2) can make a later rule unevaluable.
                # Report it as an unexpected violation instead of crashing the whole run.
                self.chk(False, "STAGE_ABORTED", "*", "*", f"stage {i} aborted on corrupt data: {type(exc).__name__}: {exc}")
        self.stage = 8
        gt_report = self.s8_ground_truth() if self.gt is not None else {"skipped": True}
        return self.report(gt_report)

    # ================= stage 1 =================
    def s1_keys(self):
        seq_tables = {"courses", "course_staff", "learners", "enrollments", "assignments", "resubmissions", "appeals", "audit_logs"}
        for t in TABLES:
            rows = self.T[t.name]
            ids = [r[t.pk] for r in rows]
            self.chk(len(ids) == len(set(ids)), "PK_UNIQUE", t.name, "*", f"duplicate primary key in {t.name}")
            for c in t.cols:
                if c.typ == "id" and c.pattern:
                    rx = re.compile(PAT.get(c.pattern, c.pattern))
                    bad = [r[t.pk] for r in rows if r[c.name] is not None and not rx.match(r[c.name])]
                    self.chk(not bad, "ID_FORMAT", t.name, c.name, f"{len(bad)} malformed ids in {t.name}.{c.name} e.g. {bad[:2]}")
            if t.name in seq_tables:
                nums = sorted(int(i.rsplit("-", 1)[1]) for i in ids)
                self.chk(nums == list(range(1, len(nums) + 1)), "ID_SEQUENTIAL", t.name, "*", f"{t.pk} not gap-free / zero-based")
        for s in self.T["submissions"]:
            self.chk(s["submission_id"] == f"SUB-{s['assignment_id']}-{s['learner_id']}-{s['attempt_number']:02d}",
                     "ID_DERIVATION", "submissions", s["submission_id"], "submission_id does not embed its assignment/learner/attempt")
        for a in self.T["submission_artifacts"]:
            self.chk(a["artifact_id"] == f"ART-{a['submission_id']}-{a['sequence_no']:02d}", "ID_DERIVATION",
                     "submission_artifacts", a["artifact_id"], "artifact_id mismatch")
        for g in self.T["grades"]:
            self.chk(g["grade_id"] == "GRD-" + g["submission_id"], "ID_DERIVATION", "grades", g["grade_id"], "grade_id != GRD-<submission_id>")
        for f in self.T["feedback"]:
            self.chk(f["feedback_id"] == "FDB-" + f["submission_id"], "ID_DERIVATION", "feedback", f["feedback_id"], "feedback_id mismatch")
        for r in self.T["rubrics"]:
            self.chk(r["rubric_id"] == f"RUB-{r['assignment_id']}-{r['version_no']:02d}", "ID_DERIVATION", "rubrics", r["rubric_id"], "rubric_id mismatch")
        for c in self.T["rubric_criteria"]:
            self.chk(c["criterion_id"] == f"CRT-{c['rubric_id']}-{c['sequence_no']:02d}", "ID_DERIVATION", "rubric_criteria", c["criterion_id"], "criterion_id mismatch")
        for v in self.T["grade_versions"]:
            self.chk(v["grade_version_id"] == f"GRV-{v['grade_id']}-{v['version_no']:02d}", "ID_DERIVATION", "grade_versions", v["grade_version_id"], "grade_version_id mismatch")
        for s in self.T["grade_criterion_scores"]:
            self.chk(s["score_id"].startswith(f"SCR-{s['grade_id']}-"), "ID_DERIVATION", "grade_criterion_scores", s["score_id"], "score_id mismatch")

    # ================= stage 2 =================
    def s2_foreign_keys(self):
        pk_sets = {t.name: set(self.by[t.name]) for t in TABLES}
        referenced_staff = set()
        for t in TABLES:
            for c in t.cols:
                if not c.fk:
                    continue
                ft, fc = c.fk.split(".")
                bad = []
                for r in self.T[t.name]:
                    v = r[c.name]
                    if v is None:
                        continue
                    if ft == "staff":
                        referenced_staff.add(v)
                    if v not in pk_sets[ft]:
                        bad.append(r[t.pk])
                self.chk(not bad, "FK_EXISTS", t.name, c.name, f"{len(bad)} orphan {t.name}.{c.name} -> {ft} e.g. {bad[:2]}")
        for a in self.T["audit_logs"]:
            tbl = ENTITY_TABLE[a["entity_name"]]
            self.chk(a["entity_id"] in pk_sets[tbl], "FK_AUDIT_ENTITY", "audit_logs", a["audit_id"], f"audit entity {a['entity_id']} missing in {tbl}")
        for sid in referenced_staff:
            self.chk(self.by["staff"][sid]["status"] == "ACTIVE", "STAFF_ACTIVE", "staff", sid, "inactive staff referenced")
        # semantic joins
        for s in self.T["submissions"]:
            a = self.asn.get(s["assignment_id"])
            if a is None:
                continue                      # orphan already reported by FK_EXISTS
            e = self.by["enrollments"].get(s["enrollment_id"]) if s["enrollment_id"] else None
            ok = bool(e) and e["course_id"] == a["course_id"] and e["learner_id"] == s["learner_id"] \
                and e["enrollment_status"] != "AUDIT" and parse(e["enrolled_at_utc"]) <= parse(s["submitted_at_utc"])
            if ok and e["enrollment_status"] == "DROPPED":
                ok = parse(s["submitted_at_utc"]) <= parse(e["effective_to_utc"])
            ok = ok and self.enr_by_pair.get((a["course_id"], s["learner_id"])) is e
            self.chk(ok, "ENROLLMENT_WINDOW", "submissions", s["submission_id"],
                     f"learner {s['learner_id']} not validly enrolled in {a['course_id']} at submission time",
                     "UNENROLLED_LEARNER_SUBMISSION")
            if s["previous_submission_id"]:
                p = self.sub.get(s["previous_submission_id"])
                self.chk(bool(p) and p["assignment_id"] == s["assignment_id"] and p["learner_id"] == s["learner_id"]
                         and p["attempt_number"] == s["attempt_number"] - 1, "FK_PREVIOUS_ATTEMPT", "submissions",
                         s["submission_id"], "previous_submission_id is not the preceding attempt")
        for g in self.T["grades"]:
            s = self.sub.get(g["submission_id"])
            a = self.asn.get(s["assignment_id"]) if s else None
            rub = self.by["rubrics"].get(g["rubric_id"])
            if a is None or rub is None:
                continue
            self.chk(g["grader_id"] in self.cstaff[a["course_id"]], "FK_GRADER_IN_COURSE", "grades", g["grade_id"], "grader is not course staff")
            self.chk(rub["assignment_id"] == a["assignment_id"], "FK_RUBRIC_ASSIGNMENT", "grades", g["grade_id"], "rubric belongs to another assignment")
        for sc in self.T["grade_criterion_scores"]:
            g, crit = self.grade.get(sc["grade_id"]), self.by["rubric_criteria"].get(sc["criterion_id"])
            if g is None or crit is None:
                continue
            self.chk(crit["rubric_id"] == g["rubric_id"], "FK_CRITERION_RUBRIC",
                     "grade_criterion_scores", sc["score_id"], "criterion not in the grade's rubric")
        for ap in self.T["appeals"]:
            g = self.grade.get(ap["grade_id"])
            s = self.sub.get(ap["submission_id"])
            if g is None or s is None:
                continue
            self.chk(g["submission_id"] == ap["submission_id"] and s["learner_id"] == ap["learner_id"], "FK_APPEAL_CONSISTENT",
                     "appeals", ap["appeal_id"], "appeal grade/submission/learner disagree")
        for r in self.T["resubmissions"]:
            o = self.sub.get(r["original_submission_id"])
            n = self.sub.get(r["new_submission_id"]) if r["new_submission_id"] else None
            if o is None or (r["new_submission_id"] and n is None):
                continue
            if r["new_submission_id"]:
                self.chk(n["previous_submission_id"] == o["submission_id"] and n["attempt_number"] == o["attempt_number"] + 1,
                         "FK_RESUB_CHAIN", "resubmissions", r["resubmission_id"], "resubmission does not link consecutive attempts")
        for f in self.T["feedback"]:
            g = self.grade_by_sub.get(f["submission_id"])
            self.chk(g is not None and g["grader_id"] == f["instructor_id"], "FK_FEEDBACK_GRADER", "feedback", f["feedback_id"], "feedback without matching grade / grader")

    # ================= stage 3 =================
    def s3_domain(self):
        rx = {}
        for t in TABLES:
            rows = self.T[t.name]
            for c in t.cols:
                vals = [(r[t.pk], r[c.name]) for r in rows]
                if c.req:
                    bad = [i for i, v in vals if v is None]
                    self.chk(not bad, "REQUIRED", t.name, c.name, f"{len(bad)} null values in required {t.name}.{c.name}")
                if c.enum:
                    bad = [i for i, v in vals if v is not None and v not in c.enum]
                    self.chk(not bad, "ENUM", t.name, c.name, f"{len(bad)} values outside enum in {t.name}.{c.name}")
                if c.pattern and c.typ != "id":
                    key = PAT.get(c.pattern, c.pattern)
                    rxc = rx.setdefault(key, re.compile(key))
                    bad = [i for i, v in vals if v is not None and not rxc.match(v)]
                    self.chk(not bad, "FORMAT", t.name, c.name, f"{len(bad)} malformed values in {t.name}.{c.name}")
                if c.lo is not None:
                    bad = [i for i, v in vals if v is not None and v < c.lo]
                    self.chk(not bad, "RANGE_MIN", t.name, c.name, f"{len(bad)} values below {c.lo} in {t.name}.{c.name}")
                if c.hi is not None:
                    bad = [i for i, v in vals if v is not None and v > c.hi]
                    self.chk(not bad, "RANGE_MAX", t.name, c.name, f"{len(bad)} values above {c.hi} in {t.name}.{c.name}")
        for a in self.T["assignments"]:
            i = a["assignment_id"]
            self.chk((a["max_resubmissions"] == 0) == (not a["allow_resubmission"]), "XFIELD_RESUB_FLAG", "assignments", i, "max_resubmissions vs allow_resubmission")
            self.chk((a["status"] == "DRAFT") == (a["published_at_utc"] is None), "XFIELD_DRAFT", "assignments", i, "DRAFT iff unpublished")
            if a["status"] != "DRAFT":
                closed = parse(a["late_cutoff_utc"]) <= SNAPSHOT_AT
                self.chk((a["status"] == "CLOSED") == closed, "XFIELD_CLOSED", "assignments", i, "status CLOSED iff late cutoff has passed")
        for l in self.T["learners"]:
            self.chk((l["status"] != "ACTIVE") == (l["status_effective_from_utc"] is not None), "XFIELD_LEARNER_STATUS", "learners", l["learner_id"], "status_effective_from iff not ACTIVE")
        months = {"SPRING-2026": (1, 2), "SUMMER-2026": (5, 6), "FALL-2026": (9, 10)}
        for c in self.T["courses"]:
            self.chk(parse(c["start_date_utc"]).month in months[c["term"]], "XFIELD_TERM_DATES", "courses", c["course_id"], "term does not match start date")
        for g in self.T["grades"]:
            self.chk((g["grade_status"] == "REVISED") == (g["current_version"] > 1), "XFIELD_GRADE_STATUS", "grades", g["grade_id"], "REVISED iff current_version > 1")
        for s in self.T["submissions"]:
            self.chk(s["attempt_number"] == 1 or s["previous_submission_id"] is not None, "XFIELD_ATTEMPT", "submissions", s["submission_id"], "attempt > 1 needs previous_submission_id")

    # ================= stage 4 =================
    def s4_chronology(self):
        P = parse
        for tname, cols in TS_EVENT_COLS.items():
            for r in self.T[tname]:
                for c in cols:
                    v = r[c]
                    if v is not None:
                        self.chk(P(v) <= SNAPSHOT_AT, "CUTOFF", tname, r[TABLE_BY_NAME[tname].pk], f"{c} after data cut-off")
        for c in self.T["courses"]:
            self.chk(P(c["created_at_utc"]) <= P(c["start_date_utc"]) < P(c["end_date_utc"]), "CHRON_COURSE", "courses", c["course_id"], "created <= start < end")
        for e in self.T["enrollments"]:
            l = self.by["learners"][e["learner_id"]]
            ok = P(l["registration_date_utc"]) <= P(e["enrolled_at_utc"]) and (e["effective_to_utc"] is None or P(e["enrolled_at_utc"]) < P(e["effective_to_utc"]))
            self.chk(ok, "CHRON_ENROLLMENT", "enrollments", e["enrollment_id"], "registration <= enrolled < effective_to")
        for a in self.T["assignments"]:
            c = self.by["courses"][a["course_id"]]
            pub = P(a["published_at_utc"]) if a["published_at_utc"] else None
            ok = P(c["created_at_utc"]) <= P(a["created_at_utc"]) and (pub is None or (P(a["created_at_utc"]) <= pub < P(a["due_at_utc"]))) \
                and P(a["due_at_utc"]) < P(a["late_cutoff_utc"])
            self.chk(ok, "CHRON_ASSIGNMENT", "assignments", a["assignment_id"], "course created <= created <= published < due < cutoff")
        for aid, rs in self.rub_by_asn.items():
            rs = sorted(rs, key=lambda r: r["version_no"])
            a = self.asn[aid]
            self.chk(P(rs[0]["effective_from_utc"]) >= P(a["created_at_utc"]), "CHRON_RUBRIC", "rubrics", rs[0]["rubric_id"], "rubric effective before assignment exists")
            for i, r in enumerate(rs):
                last = i == len(rs) - 1
                ok = (r["effective_to_utc"] is None) == last and (last or P(r["effective_to_utc"]) == P(rs[i + 1]["effective_from_utc"])) \
                    and (r["effective_to_utc"] is None or P(r["effective_to_utc"]) > P(r["effective_from_utc"]))
                self.chk(ok, "CHRON_RUBRIC_VERSIONS", "rubrics", r["rubric_id"], "rubric version effective-dates are not contiguous")
                self.chk(r["status"] == ("ACTIVE" if last else "SUPERSEDED"), "RUBRIC_STATUS", "rubrics", r["rubric_id"], "only the latest rubric version is ACTIVE")
        for s in self.T["submissions"]:
            a = self.asn[s["assignment_id"]]
            l = self.by["learners"][s["learner_id"]]
            t = P(s["submitted_at_utc"])
            ok = a["published_at_utc"] is not None and t >= P(a["published_at_utc"]) and t >= P(l["registration_date_utc"])
            if l["status_effective_from_utc"]:
                ok = ok and t < P(l["status_effective_from_utc"])
            self.chk(ok, "CHRON_SUBMISSION", "submissions", s["submission_id"], "submission before publication/registration or after suspension")
            if s["attempt_number"] == 1:
                self.chk(t <= P(a["late_cutoff_utc"]), "CHRON_LATE_CUTOFF", "submissions", s["submission_id"], "submission after the late cutoff")
        for ar in self.T["submission_artifacts"]:
            self.chk(P(ar["uploaded_at_utc"]) <= P(self.sub[ar["submission_id"]]["submitted_at_utc"]), "CHRON_ARTIFACT", "submission_artifacts", ar["artifact_id"], "uploaded after submission")
        for g in self.T["grades"]:
            s = self.sub[g["submission_id"]]
            gt = P(g["graded_at_utc"])
            rub = self.by["rubrics"][g["rubric_id"]]
            eff_ok = P(rub["effective_from_utc"]) <= gt and (rub["effective_to_utc"] is None or gt < P(rub["effective_to_utc"]))
            self.chk(gt >= P(s["submitted_at_utc"]), "CHRON_GRADE", "grades", g["grade_id"], "graded before submission")
            self.chk(eff_ok, "RUBRIC_EFFECTIVE_AT_GRADING", "grades", g["grade_id"], "grade used a rubric version not in force at grading time")
        for f in self.T["feedback"]:
            g = self.grade_by_sub.get(f["submission_id"])
            self.chk(g is not None and P(f["provided_at_utc"]) == P(g["graded_at_utc"]), "CHRON_FEEDBACK", "feedback", f["feedback_id"], "feedback time != grade time")
        for gid, vs in self.versions.items():
            vs = sorted(vs, key=lambda v: v["version_no"])
            self.chk(all(P(vs[i]["changed_at_utc"]) <= P(vs[i + 1]["changed_at_utc"]) for i in range(len(vs) - 1)), "CHRON_VERSIONS", "grade_versions", gid, "version timestamps not ascending")
        for r in self.T["resubmissions"]:
            o_g = self.grade_by_sub.get(r["original_submission_id"])
            ok = o_g is not None and P(r["requested_at_utc"]) >= P(o_g["graded_at_utc"])
            if r["decided_at_utc"]:
                ok = ok and P(r["decided_at_utc"]) >= P(r["requested_at_utc"])
            if r["resubmission_due_utc"]:
                ok = ok and P(r["resubmission_due_utc"]) > P(r["decided_at_utc"])
            if r["resubmitted_at_utc"]:
                ok = ok and P(r["resubmitted_at_utc"]) >= P(r["decided_at_utc"])
            self.chk(ok, "CHRON_RESUBMISSION", "resubmissions", r["resubmission_id"], "resubmission timestamps out of order")
        for ap in self.T["appeals"]:
            g = self.grade[ap["grade_id"]]
            ok = P(ap["filed_at_utc"]) >= P(g["graded_at_utc"])
            if ap["review_started_at_utc"]:
                ok = ok and P(ap["review_started_at_utc"]) >= P(ap["filed_at_utc"])
            if ap["decided_at_utc"]:
                ok = ok and P(ap["decided_at_utc"]) >= P(ap["review_started_at_utc"])
            self.chk(ok, "CHRON_APPEAL", "appeals", ap["appeal_id"], "appeal timestamps out of order")
        logs = self.T["audit_logs"]
        self.chk(all((logs[i]["timestamp_utc"], logs[i]["audit_id"]) <= (logs[i + 1]["timestamp_utc"], logs[i + 1]["audit_id"]) for i in range(len(logs) - 1)),
                 "CHRON_AUDIT_ORDER", "audit_logs", "*", "audit log is not ordered by timestamp")

    # ================= stage 5 =================
    def s5_arithmetic(self):
        P = parse
        for a in self.T["assignments"]:
            i, tz = a["assignment_id"], a["timezone"]
            due = P(a["due_at_utc"])
            self.chk(local_to_utc(tz, parse_local(a["due_at_local"])) == due, "TZ_DUE_LOCAL_TO_UTC", "assignments", i, "due_at_local does not convert to due_at_utc")
            self.chk(utc_offset_minutes(tz, due) == a["utc_offset_minutes"], "TZ_OFFSET", "assignments", i, "utc_offset_minutes wrong for the due date (DST)")
            self.chk(P(a["late_cutoff_utc"]) == due + timedelta(days=LATE_WINDOW_DAYS), "LATE_CUTOFF_RULE", "assignments", i, "late cutoff != due + 5 days")
        for r in self.T["rubrics"]:
            cs = self.crit_by_rub[r["rubric_id"]]
            self.chk(abs(sum(c["max_points"] for c in cs) - r["total_points"]) < 0.005, "RUBRIC_SUM", "rubrics", r["rubric_id"], "criteria max_points != total_points")
            self.chk(abs(sum(c["weight_pct"] for c in cs) - 100.0) < 0.005, "RUBRIC_WEIGHTS", "rubrics", r["rubric_id"], "criteria weights != 100")
            self.chk(abs(r["total_points"] - self.asn[r["assignment_id"]]["max_score"]) < 0.005, "RUBRIC_MAX", "rubrics", r["rubric_id"], "rubric total != assignment max_score")
        for s in self.T["submissions"]:
            a = self.asn[s["assignment_id"]]
            sid = s["submission_id"]
            if s["attempt_number"] == 1:
                deadline = P(a["due_at_utc"])
            else:
                rs = self.resub_by_new.get(sid)
                deadline = P(rs["resubmission_due_utc"]) if rs else None
            self.chk(deadline is not None and P(s["applicable_deadline_utc"]) == deadline, "DEADLINE_RULE", "submissions", sid, "applicable_deadline_utc is not the assignment/resubmission deadline")
            if deadline is not None:
                late, days = self.late_calc(s, P(s["applicable_deadline_utc"]), a["grace_period_minutes"])
                self.chk(late == s["is_late"] and days == s["late_days"], "LATE_DERIVATION", "submissions", sid, f"is_late/late_days != derived ({late},{days})")
            arts = self.arts_by_sub.get(sid, [])
            st = s["file_check_status"]
            exp = 0 if st == "MISSING_FILE" else s["expected_file_count"]
            ok = len(arts) == exp
            if st == "EMPTY_FILE":
                ok = ok and sum(1 for x in arts if x["file_size_bytes"] == 0) == 1
            elif st == "COMPLETE":
                ok = ok and all(x["file_size_bytes"] > 0 for x in arts)
            self.chk(ok, "FILE_STATUS", "submissions", sid, "file_check_status inconsistent with artifacts")
            for x in arts:
                self.chk((x["checksum_sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") == (x["file_size_bytes"] == 0)
                         and x["file_name"].endswith("." + x["file_type"]) and x["storage_uri"].startswith(f"s3://ams-artifacts/{s['assignment_id']}/{sid}/"),
                         "ARTIFACT_META", "submission_artifacts", x["artifact_id"], "artifact checksum/extension/uri inconsistent")
        for g in self.T["grades"]:
            gid = g["grade_id"]
            s = self.sub[g["submission_id"]]
            a = self.asn[s["assignment_id"]]
            rub = self.by["rubrics"][g["rubric_id"]]
            crits = self.crit_by_rub[g["rubric_id"]]
            scs = self.scores_by_grade.get(gid, [])
            cmap = {c["criterion_id"]: c for c in crits}
            self.chk({x["criterion_id"] for x in scs} == set(cmap) and len(scs) == len(crits), "SCORES_COVER_RUBRIC", "grades", gid, "criterion scores do not cover the rubric exactly once")
            self.chk(abs(sum(x["awarded_points"] for x in scs) - g["raw_score"]) < 0.015, "RAW_EQ_SUM", "grades", gid, "raw_score != sum of criterion scores")
            over = g["raw_score"] > rub["total_points"] + 0.005 or g["final_score"] > a["max_score"] + 0.005 \
                or any(x["awarded_points"] > cmap[x["criterion_id"]]["max_points"] + 0.005 for x in scs if x["criterion_id"] in cmap)
            self.chk(not over, "GRADE_MAX", "grades", gid, f"raw {g['raw_score']} / final {g['final_score']} exceeds rubric maximum", "GRADE_EXCEEDS_MAX")
            exp_pen = round(min(g["raw_score"], s["late_days"] * a["late_penalty_per_day"]), 2) if s["late_days"] > 0 else 0.0
            self.chk(abs(g["late_penalty_points"] - exp_pen) < 0.005, "LATE_PENALTY_RULE", "grades", gid,
                     f"late penalty {g['late_penalty_points']} != single deduction {exp_pen}", "DOUBLE_LATE_PENALTY")
            self.chk(abs(g["final_score"] - round(max(0.0, g["raw_score"] - g["late_penalty_points"] + g["adjustment_points"]), 2)) < 0.005,
                     "FINAL_FORMULA", "grades", gid, "final != max(0, raw - penalty + adjustment)")
            self.chk(all(x["awarded_points"] >= 0 for x in scs), "SCORE_NONNEG", "grades", gid, "negative criterion score")
            self.chk((g["grade_status"] == "REVISED") == (g["adjustment_points"] > 0), "ADJUSTMENT_FLAG", "grades", gid, "adjustment_points > 0 iff REVISED")
            vs = self.versions.get(gid, [])
            ap = self.appeal_by_grade.get(gid)
            if vs:
                top = max(vs, key=lambda v: v["version_no"])
                # an upheld appeal whose version-2 row is missing is reported once, by rule APPEAL_AUDIT (stage 6)
                missing_v2 = ap is not None and ap["status"] == "UPHELD" and top["version_no"] < g["current_version"]
                if not missing_v2:
                    same = top["version_no"] == g["current_version"] and all(
                        abs(top[k] - g[k]) < 0.005 for k in ("raw_score", "late_penalty_points", "adjustment_points", "final_score"))
                    self.chk(same, "GRADE_EQ_LATEST_VERSION", "grades", gid, "grade row != latest grade_version")
            else:
                self.chk(False, "GRADE_HAS_VERSION", "grades", gid, "grade has no version history")
        for v in self.T["grade_versions"]:
            self.chk(abs(v["final_score"] - round(max(0.0, v["raw_score"] - v["late_penalty_points"] + v["adjustment_points"]), 2)) < 0.005,
                     "VERSION_FORMULA", "grade_versions", v["grade_version_id"], "version final != formula")
        for ap in self.T["appeals"]:
            g = self.grade[ap["grade_id"]]
            vs = sorted(self.versions.get(ap["grade_id"], []), key=lambda v: v["version_no"])
            if vs:
                self.chk(abs(ap["original_score"] - vs[0]["final_score"]) < 0.005, "APPEAL_ORIGINAL", "appeals", ap["appeal_id"], "original_score != version-1 final")
            if ap["status"] == "UPHELD":
                self.chk(ap["adjusted_score"] is not None and abs(ap["adjusted_score"] - g["final_score"]) < 0.005 and ap["adjusted_score"] > ap["original_score"] - 0.005,
                         "APPEAL_ADJUSTED", "appeals", ap["appeal_id"], "upheld adjusted_score != grade.final_score / not an increase")
            elif ap["status"] == "REJECTED":
                self.chk(ap["adjusted_score"] is not None and abs(ap["adjusted_score"] - ap["original_score"]) < 0.005 and abs(g["final_score"] - ap["original_score"]) < 0.005,
                         "APPEAL_REJECTED_UNCHANGED", "appeals", ap["appeal_id"], "rejected appeal changed the grade")

    # ================= stage 6 =================
    def s6_lifecycle(self):
        P = parse
        # 6a. replay the audit log per entity against the state machines
        for (ent, eid), evs in self.audit_by_entity.items():
            if ent not in TRANSITIONS:
                continue
            prev, ok_chain = None, True
            for e in evs:
                ok_chain &= (e["from_status"] == prev) and ((e["from_status"], e["to_status"]) in TRANSITIONS[ent])
                prev = e["to_status"]
            self.chk(ok_chain, "AUDIT_TRANSITIONS", ent, eid, "audit history is not a legal state-machine path")
            if ent in STATUS_COL:
                row = self.by[ENTITY_TABLE[ent]].get(eid)
                if row is not None:
                    self.chk(prev == row[STATUS_COL[ent]], "AUDIT_FINAL_STATE", ent, eid, f"audit ends in {prev} but record is {row[STATUS_COL[ent]]}")
        for ent, col in STATUS_COL.items():
            for r in self.T[ENTITY_TABLE[ent]]:
                self.chk((ent, r[TABLE_BY_NAME[ENTITY_TABLE[ent]].pk]) in self.audit_by_entity, "AUDIT_PRESENT", ent,
                         r[TABLE_BY_NAME[ENTITY_TABLE[ent]].pk], "entity has no audit history")
        # 6b. derived submission / enrollment status
        open_appeal_subs = {a["submission_id"] for a in self.T["appeals"] if a["status"] in ("SUBMITTED", "IN_REVIEW")}
        for s in self.T["submissions"]:
            sid = s["submission_id"]
            if sid in self.next_sub:
                exp = "RESUBMITTED"
            elif sid not in self.grade_by_sub:
                exp = "SUBMITTED"
            elif sid in open_appeal_subs:
                exp = "APPEALED"
            else:
                exp = "GRADED"
            self.chk(s["status"] == exp, "SUBMISSION_STATUS", "submissions", sid, f"status {s['status']} != derived {exp}")
        for e in self.T["enrollments"]:
            c = self.by["courses"][e["course_id"]]
            ended = P(c["end_date_utc"]) <= SNAPSHOT_AT
            exp = e["enrollment_status"]
            if exp in ("ENROLLED", "COMPLETED"):
                ok = (exp == "COMPLETED") == ended and ((exp == "COMPLETED") == (e["effective_to_utc"] is not None))
            elif exp == "DROPPED":
                ok = e["effective_to_utc"] is not None
            else:
                ok = e["effective_to_utc"] is None
            self.chk(ok, "ENROLLMENT_STATUS", "enrollments", e["enrollment_id"], "enrollment status vs course end / effective_to")
        # 6c. resubmission lifecycle + policy
        for r in self.T["resubmissions"]:
            rid, st = r["resubmission_id"], r["status"]
            o = self.sub[r["original_submission_id"]]
            a = self.asn[o["assignment_id"]]
            og = self.grade_by_sub.get(o["submission_id"])
            shape = True
            if st == "REQUESTED":
                shape = r["decided_at_utc"] is None and r["new_submission_id"] is None and r["decision_reason"] is None
            elif st == "DENIED":
                shape = r["new_submission_id"] is None and (r["decision_reason"] or "").startswith("DENIED") and r["resubmission_due_utc"] is None
            elif st == "APPROVED":
                shape = (r["decision_reason"] or "").startswith("APPROVED") and r["resubmission_due_utc"] is not None
                if r["new_submission_id"]:
                    n = self.sub[r["new_submission_id"]]
                    shape = shape and r["resubmitted_at_utc"] == n["submitted_at_utc"] and n["applicable_deadline_utc"] == r["resubmission_due_utc"]
                else:
                    shape = shape and P(r["resubmission_due_utc"]) + timedelta(days=RESUB_LATE_CUTOFF_DAYS) > SNAPSHOT_AT
            elif st == "EXPIRED":
                shape = r["new_submission_id"] is None and r["resubmission_due_utc"] is not None and \
                    P(r["resubmission_due_utc"]) + timedelta(days=RESUB_LATE_CUTOFF_DAYS) <= SNAPSHOT_AT
            self.chk(shape, "RESUB_LIFECYCLE", "resubmissions", rid, f"resubmission fields inconsistent with status {st}")
            if og is None:
                continue
            in_window = (P(r["requested_at_utc"]) - P(og["graded_at_utc"])).total_seconds() <= a["resubmission_window_days"] * 86400
            # eligibility is judged on the grade as it stood when the request was decided (a later appeal may change it)
            at = P(r["decided_at_utc"]) if r["decided_at_utc"] else P(r["requested_at_utc"])
            final_then = og["final_score"]
            for v in sorted(self.versions.get(og["grade_id"], []), key=lambda v: v["version_no"]):
                if P(v["changed_at_utc"]) <= at:
                    final_then = v["final_score"]
            score_ok = o["file_check_status"] != "COMPLETE" or final_then < RESUB_SCORE_THRESHOLD
            reason = r["decision_reason"] or ""
            if reason.startswith("APPROVED"):
                limit_ok = o["attempt_number"] < 1 + a["max_resubmissions"]
                self.chk(a["allow_resubmission"] and limit_ok and in_window and score_ok, "POLICY_RESUBMISSION", "resubmissions", rid,
                         "approved resubmission violates policy (disabled / limit / window / score)", "RESUBMISSION_POLICY_VIOLATION")
            elif reason == "DENIED_OUTSIDE_WINDOW":
                self.chk(not in_window, "RESUB_DENIAL_RULE", "resubmissions", rid, "denied for window but request was in window")
            elif reason == "DENIED_SCORE_ABOVE_THRESHOLD":
                self.chk(in_window and not score_ok, "RESUB_DENIAL_RULE", "resubmissions", rid, "denied for score but score was eligible / out of window")
        # 6d. appeal lifecycle, policy and audit trail
        mutate_events = defaultdict(list)
        for e in self.T["audit_logs"]:
            if e["action_type"] == "GRADE_MUTATE":
                mutate_events[e["entity_id"]].append(e)
        for ap in self.T["appeals"]:
            aid, st = ap["appeal_id"], ap["status"]
            g = self.grade[ap["grade_id"]]
            a = self.asn[self.sub[ap["submission_id"]]["assignment_id"]]
            shape = True
            if st == "SUBMITTED":
                shape = ap["review_started_at_utc"] is None and ap["decided_at_utc"] is None and ap["decision_code"] is None
            elif st == "IN_REVIEW":
                shape = ap["review_started_at_utc"] is not None and ap["decided_at_utc"] is None and ap["reviewed_by"] is not None
            else:
                shape = ap["decided_at_utc"] is not None and ap["decision_code"] is not None and ap["adjusted_score"] is not None
            self.chk(shape, "APPEAL_LIFECYCLE", "appeals", aid, f"appeal fields inconsistent with status {st}")
            if st in ("SUBMITTED", "IN_REVIEW"):
                self.chk(g["grade_status"] == "PUBLISHED", "APPEAL_OPEN_GRADE", "appeals", aid, "open appeal but grade already revised")
                continue
            in_window = (P(ap["filed_at_utc"]) - P(g["graded_at_utc"])).total_seconds() <= a["appeal_window_days"] * 86400
            code = ap["decision_code"]
            if st == "UPHELD":
                vs = self.versions.get(ap["grade_id"], [])
                has_v2 = any(v["version_no"] == 2 and v["appeal_id"] == aid for v in vs)
                has_evt = any(e["new_state"].find(f'"appeal_id":"{aid}"') >= 0 for e in mutate_events.get(ap["grade_id"], []))
                self.chk(has_v2 and has_evt, "APPEAL_AUDIT", "appeals", aid,
                         "upheld appeal changed the grade without grade_versions / GRADE_MUTATE audit history", "APPEAL_NO_AUDIT_LOG")
                self.chk(in_window, "POLICY_APPEAL_WINDOW", "appeals", aid, "appeal filed outside the window was upheld", "APPEAL_OUTSIDE_WINDOW_UPHELD")
                self.chk(code == "UPHELD_GRADING_ERROR", "APPEAL_DECISION_CODE", "appeals", aid, "upheld with wrong decision code")
            else:
                self.chk((code == "REJECTED_OUT_OF_WINDOW") == (not in_window), "APPEAL_DECISION_CODE", "appeals", aid, "rejection reason vs window")
        for g in self.T["grades"]:
            if g["grade_status"] == "REVISED":
                ap = self.appeal_by_grade.get(g["grade_id"])
                self.chk(ap is not None and ap["status"] == "UPHELD", "REVISED_NEEDS_APPEAL", "grades", g["grade_id"], "REVISED grade without an upheld appeal")
        for gid, vs in self.versions.items():
            nums = sorted(v["version_no"] for v in vs)
            ap = self.appeal_by_grade.get(gid)
            if ap is not None and ap["status"] == "UPHELD" and len(nums) < self.grade[gid]["current_version"]:
                continue                           # reported once by rule APPEAL_AUDIT
            self.chk(nums == list(range(1, len(nums) + 1)) and len(nums) == self.grade[gid]["current_version"], "VERSION_CONTIGUOUS", "grade_versions", gid, "version numbers not contiguous")

    # ================= stage 7 =================
    def s7_duplicates(self):
        def dup(rows, keyfn, rule, table, label):
            seen, bad = set(), []
            for r in rows:
                k = keyfn(r)
                if k in seen:
                    bad.append(k)
                seen.add(k)
            self.chk(not bad, rule, table, "*", f"{len(bad)} duplicate {label}, e.g. {bad[:2]}")
        dup(self.T["submissions"], lambda r: (r["assignment_id"], r["learner_id"], r["attempt_number"]), "DUP_ATTEMPT", "submissions", "(assignment, learner, attempt)")
        dup(self.T["enrollments"], lambda r: (r["course_id"], r["learner_id"]), "DUP_ENROLLMENT", "enrollments", "(course, learner)")
        dup(self.T["grades"], lambda r: r["submission_id"], "DUP_GRADE", "grades", "grades per submission")
        dup(self.T["feedback"], lambda r: r["submission_id"], "DUP_FEEDBACK", "feedback", "feedback per submission")
        dup(self.T["appeals"], lambda r: r["grade_id"], "DUP_APPEAL", "appeals", "appeals per grade")
        dup(self.T["resubmissions"], lambda r: r["original_submission_id"], "DUP_RESUB", "resubmissions", "resubmissions per attempt")
        dup(self.T["grade_criterion_scores"], lambda r: (r["grade_id"], r["criterion_id"]), "DUP_SCORE", "grade_criterion_scores", "(grade, criterion)")
        dup(self.T["learners"], lambda r: r["email"], "DUP_EMAIL", "learners", "learner emails")
        dup(self.T["staff"], lambda r: r["email"], "DUP_EMAIL", "staff", "staff emails")
        dup(self.T["submission_artifacts"], lambda r: r["storage_uri"], "DUP_URI", "submission_artifacts", "storage URIs")
        dup(self.T["audit_logs"], lambda r: (r["entity_name"], r["entity_id"], r["action_type"], r["timestamp_utc"]), "DUP_AUDIT", "audit_logs", "audit events")
        attempts = defaultdict(list)
        for s in self.T["submissions"]:
            attempts[(s["assignment_id"], s["learner_id"])].append(s["attempt_number"])
        for k, v in attempts.items():
            self.chk(sorted(v) == list(range(1, len(v) + 1)), "ATTEMPT_CONTIGUOUS", "submissions", k, "attempt numbers are not contiguous from 1")

    # ================= stage 8 =================
    def s8_ground_truth(self) -> Dict[str, Any]:
        gt = self.gt
        anomalies = [g for g in gt if g["label_class"] == "ANOMALY"]
        expected = {(g["issue_type"], g["record_id"]) for g in anomalies}
        detected = {(v["anomaly"], v["record_id"]) for v in self.violations if v["anomaly"]}
        per_type = {}
        for t in ANOMALY_TYPES:
            e = {x for x in expected if x[0] == t}
            d = {x for x in detected if x[0] == t}
            tp = len(e & d)
            per_type[t] = {"labelled": len(e), "detected": len(d), "true_positive": tp,
                           "false_positive": len(d - e), "false_negative": len(e - d),
                           "precision": round(tp / len(d), 4) if d else (1.0 if not e else 0.0),
                           "recall": round(tp / len(e), 4) if e else 1.0}
        fp, fn = detected - expected, expected - detected
        self.chk(not fp and not fn, "GT_PRECISION_RECALL", "ground_truth", "*", f"false positives {sorted(fp)[:3]} / false negatives {sorted(fn)[:3]}")
        # valid labels (exception paths / boundary cases) must (a) match the data and (b) not be flagged
        # only UNTAGGED violations count here: a valid case may legitimately share a record with a labelled anomaly
        flagged_ids = {v["record_id"] for v in self.violations if not v["anomaly"]}
        table_for = {"Submission": "submissions", "Grade": "grades", "Appeal": "appeals", "Resubmission": "resubmissions"}
        bad_valid = 0
        for g in gt:
            if g["label_class"] == "ANOMALY":
                if g["issue_type"] in ("GRADE_EXCEEDS_MAX", "DOUBLE_LATE_PENALTY"):
                    row = self.grade.get(g["record_id"])
                    ok = row is not None and f"{row[g['field_name']]:.2f}" == g["actual_value"]
                    self.chk(ok, "GT_ACTUAL_VALUE", "ground_truth", g["ground_truth_id"], "labelled actual_value differs from the data")
                continue
            row = self.by[table_for[g["entity_name"]]].get(g["record_id"])
            ok = row is not None and str(row[g["field_name"]]) == g["expected_value"]
            if not self.chk(ok, "GT_VALID_LABEL", "ground_truth", g["ground_truth_id"], f"valid-case label does not match data ({g['issue_type']})"):
                bad_valid += 1
            self.chk(g["record_id"] not in flagged_ids, "GT_NO_FALSE_ALARM", "ground_truth", g["ground_truth_id"], f"valid case {g['record_id']} was flagged by a rule")
        return {"per_type": per_type, "labelled_anomalies": len(expected), "detected_anomalies": len(detected),
                "label_counts": dict(Counter(g["label_class"] for g in gt))}

    # ---- report ----
    def report(self, gt_report) -> Dict[str, Any]:
        stages = []
        unexpected_total = 0
        for n in range(1, 9):
            vs = [v for v in self.violations if v["stage"] == n]
            labelled = [v for v in vs if v["anomaly"]]
            unexpected = [v for v in vs if not v["anomaly"]]
            unexpected_total += len(unexpected)
            status = "FAIL" if unexpected else ("PASS_WITH_LABELLED_ANOMALIES" if labelled else "PASS")
            by_rule = Counter(v["rule"] for v in vs)
            stages.append({"stage": n, "name": STAGE_NAMES[n], "status": status, "checks": self.checks[n],
                           "violations": len(vs), "labelled_anomaly_violations": len(labelled),
                           "unexpected_violations": len(unexpected), "violations_by_rule": dict(by_rule),
                           "sample_unexpected": [f"{v['rule']} {v['record_id']}: {v['message']}" for v in unexpected[:5]]})
        return {"summary": {"all_passed": unexpected_total == 0, "total_checks": sum(self.checks.values()),
                            "total_violations": len(self.violations),
                            "labelled_anomaly_violations": sum(1 for v in self.violations if v["anomaly"]),
                            "unexpected_violations": unexpected_total},
                "stages": stages, "ground_truth": gt_report}
