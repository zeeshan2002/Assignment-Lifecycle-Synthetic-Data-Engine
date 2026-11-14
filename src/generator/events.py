"""
Audit-log (event history) derivation.

Every state change is emitted as an append-only event DERIVED from the final records, so the event
history can never disagree with the data it describes. Ids are assigned after a stable sort on
(timestamp, emission order), which keeps them sequential and gap-free.
"""

import json
import zlib
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List

from src.config import RESUB_LATE_CUTOFF_DAYS, SNAPSHOT_AT
from src.id_generator import IdGenerator
from src.timeutil import fmt, parse

SYSTEM = "SYSTEM"


def _js(d: dict) -> str:
    return json.dumps(d, separators=(",", ":"), sort_keys=True)


def build_audit_log(T: Dict[str, List[dict]], ids: IdGenerator) -> List[dict]:
    ev = []

    def add(ts, entity, eid, action, actor, role, frm, to, prev, new):
        ev.append((ts, len(ev), {
            "entity_name": entity, "entity_id": eid, "action_type": action, "actor_id": actor, "actor_role": role,
            "from_status": frm, "to_status": to, "previous_state": _js(prev) if prev is not None else None,
            "new_state": _js(new), "timestamp_utc": ts,
        }))

    support = [s["staff_id"] for s in T["staff"] if s["role"] == "SUPPORT_STAFF" and s["status"] == "ACTIVE"]
    sub_by_id = {s["submission_id"]: s for s in T["submissions"]}
    sub_next = {}
    for s in T["submissions"]:
        if s["previous_submission_id"]:
            sub_next[s["previous_submission_id"]] = s
    grade_by_sub = {g["submission_id"]: g for g in T["grades"]}
    versions = defaultdict(list)
    for v in T["grade_versions"]:
        versions[v["grade_id"]].append(v)
    appeal_by_sub = {a["submission_id"]: a for a in T["appeals"]}

    for c in T["courses"]:
        add(c["created_at_utc"], "Course", c["course_id"], "COURSE_CREATE", c["created_by"], "PLATFORM_ADMIN",
            None, "CREATED", None, {"term": c["term"], "instructor_id": c["instructor_id"]})
    for a in T["assignments"]:
        i = a["assignment_id"]
        add(a["created_at_utc"], "Assignment", i, "ASSIGNMENT_CREATE", a["created_by"], "INSTRUCTOR", None, "DRAFT", None,
            {"status": "DRAFT", "due_at_utc": a["due_at_utc"]})
        if a["published_at_utc"]:
            add(a["published_at_utc"], "Assignment", i, "ASSIGNMENT_PUBLISH", a["created_by"], "INSTRUCTOR", "DRAFT",
                "PUBLISHED", {"status": "DRAFT"}, {"status": "PUBLISHED", "due_at_utc": a["due_at_utc"]})
        if a["status"] == "CLOSED":
            add(a["late_cutoff_utc"], "Assignment", i, "ASSIGNMENT_CLOSE", SYSTEM, "SYSTEM", "PUBLISHED", "CLOSED",
                {"status": "PUBLISHED"}, {"status": "CLOSED"})
    for r in T["rubrics"]:
        add(r["created_at_utc"], "Rubric", r["rubric_id"], "RUBRIC_CREATE", r["created_by"], "INSTRUCTOR", None, "ACTIVE",
            None, {"status": "ACTIVE", "version_no": r["version_no"]})
        if r["status"] == "SUPERSEDED":
            add(r["effective_to_utc"], "Rubric", r["rubric_id"], "RUBRIC_SUPERSEDE", r["created_by"], "INSTRUCTOR",
                "ACTIVE", "SUPERSEDED", {"status": "ACTIVE"}, {"status": "SUPERSEDED"})
    for e in T["enrollments"]:
        first = "AUDIT" if e["enrollment_status"] == "AUDIT" else "ENROLLED"
        add(e["enrolled_at_utc"], "Enrollment", e["enrollment_id"], "ENROLL", e["processed_by"], "SUPPORT_STAFF", None, first,
            None, {"status": first})
        if e["enrollment_status"] in ("DROPPED", "COMPLETED"):
            dropped = e["enrollment_status"] == "DROPPED"
            add(e["effective_to_utc"], "Enrollment", e["enrollment_id"], "ENROLLMENT_END",
                e["learner_id"] if dropped else SYSTEM, "LEARNER" if dropped else "SYSTEM", "ENROLLED",
                e["enrollment_status"], {"status": "ENROLLED"}, {"status": e["enrollment_status"]})

    for s in T["submissions"]:
        sid, lid = s["submission_id"], s["learner_id"]
        add(s["submitted_at_utc"], "Submission", sid, "SUBMISSION_CREATE", lid, "LEARNER", None, "SUBMITTED", None,
            {"status": "SUBMITTED", "attempt": s["attempt_number"], "late_days": s["late_days"]})
        flag_at = parse(s["submitted_at_utc"]) + timedelta(seconds=60)
        if s["file_check_status"] != "COMPLETE" and flag_at <= SNAPSHOT_AT:
            ts = fmt(flag_at)
            add(ts, "Submission", sid, "FILE_FLAG", support[zlib.crc32(sid.encode()) % len(support)], "SUPPORT_STAFF",
                "SUBMITTED", "SUBMITTED", {"file_check": "PENDING"}, {"file_check": s["file_check_status"]})
        g = grade_by_sub.get(sid)
        if g:
            v1 = next(v for v in versions[g["grade_id"]] if v["version_no"] == 1)
            add(g["graded_at_utc"], "Grade", g["grade_id"], "GRADE_PUBLISH", g["grader_id"], "INSTRUCTOR", None, "PUBLISHED",
                None, {"version": 1, "raw_score": v1["raw_score"], "late_penalty_points": v1["late_penalty_points"],
                       "adjustment_points": 0.0, "final_score": v1["final_score"]})
            add(g["graded_at_utc"], "Submission", sid, "SUBMISSION_GRADED", g["grader_id"], "INSTRUCTOR", "SUBMITTED",
                "GRADED", {"status": "SUBMITTED"}, {"status": "GRADED"})
        nxt = sub_next.get(sid)
        if nxt:
            add(nxt["submitted_at_utc"], "Submission", sid, "SUBMISSION_SUPERSEDED", SYSTEM, "SYSTEM", "GRADED",
                "RESUBMITTED", {"status": "GRADED"}, {"status": "RESUBMITTED", "superseded_by": nxt["submission_id"]})
        ap = appeal_by_sub.get(sid)
        if ap and g:
            aid = ap["appeal_id"]
            add(ap["filed_at_utc"], "Appeal", aid, "APPEAL_FILE", lid, "LEARNER", None, "SUBMITTED", None,
                {"status": "SUBMITTED", "reason_code": ap["reason_code"]})
            add(ap["filed_at_utc"], "Submission", sid, "SUBMISSION_APPEALED", lid, "LEARNER", "GRADED", "APPEALED",
                {"status": "GRADED"}, {"status": "APPEALED", "appeal_id": aid})
            intake_at = parse(ap["filed_at_utc"]) + timedelta(minutes=30)
            if intake_at <= SNAPSHOT_AT:
                add(fmt(intake_at), "Appeal", aid, "APPEAL_INTAKE", ap["intake_by"], "SUPPORT_STAFF", "SUBMITTED",
                    "SUBMITTED", {"status": "SUBMITTED"}, {"status": "SUBMITTED", "intake": True})
            if ap["review_started_at_utc"]:
                add(ap["review_started_at_utc"], "Appeal", aid, "APPEAL_REVIEW_START", ap["reviewed_by"], "ACADEMIC_ADMIN",
                    "SUBMITTED", "IN_REVIEW", {"status": "SUBMITTED"}, {"status": "IN_REVIEW"})
            if ap["decided_at_utc"]:
                add(ap["decided_at_utc"], "Appeal", aid, "APPEAL_RESOLVE", ap["reviewed_by"], "ACADEMIC_ADMIN", "IN_REVIEW",
                    ap["status"], {"status": "IN_REVIEW"},
                    {"status": ap["status"], "decision_code": ap["decision_code"], "adjusted_score": ap["adjusted_score"]})
                add(ap["decided_at_utc"], "Submission", sid, "SUBMISSION_APPEAL_CLOSED", ap["reviewed_by"], "ACADEMIC_ADMIN",
                    "APPEALED", "GRADED", {"status": "APPEALED"}, {"status": "GRADED"})
                v2 = next((v for v in versions[g["grade_id"]] if v["version_no"] == 2), None)
                if v2:
                    v1 = next(v for v in versions[g["grade_id"]] if v["version_no"] == 1)
                    add(v2["changed_at_utc"], "Grade", g["grade_id"], "GRADE_MUTATE", v2["changed_by"], "ACADEMIC_ADMIN",
                        "PUBLISHED", "REVISED",
                        {"version": 1, "final_score": v1["final_score"], "adjustment_points": 0.0},
                        {"version": 2, "final_score": v2["final_score"], "adjustment_points": v2["adjustment_points"],
                         "appeal_id": aid})
    for rs in T["resubmissions"]:
        rid = rs["resubmission_id"]
        learner = sub_by_id[rs["original_submission_id"]]["learner_id"]
        add(rs["requested_at_utc"], "Resubmission", rid, "RESUBMISSION_REQUEST", learner, "LEARNER", None, "REQUESTED", None,
            {"status": "REQUESTED"})
        if rs["decided_at_utc"]:
            decided_to = "DENIED" if rs["status"] == "DENIED" else "APPROVED"
            add(rs["decided_at_utc"], "Resubmission", rid, "RESUBMISSION_DECIDE", rs["decided_by"], "INSTRUCTOR",
                "REQUESTED", decided_to, {"status": "REQUESTED"},
                {"status": decided_to, "decision_reason": rs["decision_reason"]})
        if rs["status"] == "EXPIRED":
            ts = fmt(parse(rs["resubmission_due_utc"]) + timedelta(days=RESUB_LATE_CUTOFF_DAYS))
            add(ts, "Resubmission", rid, "RESUBMISSION_EXPIRE", SYSTEM, "SYSTEM", "APPROVED", "EXPIRED",
                {"status": "APPROVED"}, {"status": "EXPIRED"})

    ev.sort(key=lambda x: (x[0], x[1]))
    rows = []
    for n, (_, _, row) in enumerate(ev, start=1):
        rows.append({"audit_id": ids.audit_id(n), **row})
    return rows
