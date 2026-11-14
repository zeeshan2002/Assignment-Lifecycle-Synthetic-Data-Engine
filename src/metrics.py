"""
Evaluation metrics computed ONLY from the input tables (never from ground truth), so they are the
measurable outputs of the workflow: timeliness, grading, resubmission, appeal and data-quality KPIs.
"""

import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List

from src.timeutil import parse


def _pct(n: float, d: float) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def _q(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


def compute_metrics(T: Dict[str, List[dict]]) -> Dict[str, Any]:
    subs, grades = T["submissions"], T["grades"]
    sub_by = {s["submission_id"]: s for s in subs}
    first = [s for s in subs if s["attempt_number"] == 1]
    gmap = {g["submission_id"]: g for g in grades}
    m: Dict[str, Any] = {}

    m["volume"] = {t: len(rows) for t, rows in T.items()}

    # --- participation ---
    asn_by = {a["assignment_id"]: a for a in T["assignments"]}
    enr_by_course = defaultdict(list)
    for e in T["enrollments"]:
        if e["enrollment_status"] != "AUDIT":
            enr_by_course[e["course_id"]].append(e)
    expected_pairs = sum(len(enr_by_course[a["course_id"]]) for a in T["assignments"] if a["status"] != "DRAFT")
    m["participation"] = {
        "published_assignments": sum(1 for a in T["assignments"] if a["status"] != "DRAFT"),
        "draft_assignments": sum(1 for a in T["assignments"] if a["status"] == "DRAFT"),
        "enrolled_learner_assignment_pairs": expected_pairs,
        "first_attempt_submissions": len(first),
        "submission_rate_pct": _pct(len(first), expected_pairs),
        "learners_with_no_submission": len({l["learner_id"] for l in T["learners"]} - {s["learner_id"] for s in subs}),
    }

    # --- timeliness ---
    late = [s for s in first if s["is_late"]]
    m["timeliness"] = {
        "first_attempt_late_rate_pct": _pct(len(late), len(first)),
        "mean_late_days_of_late": round(statistics.mean(s["late_days"] for s in late), 2) if late else 0,
        "late_days_distribution": dict(sorted(Counter(s["late_days"] for s in late).items())),
        "assignments_by_timezone": dict(Counter(a["timezone"] for a in T["assignments"])),
        "assignments_with_grace_period_pct": _pct(sum(1 for a in T["assignments"] if a["grace_period_minutes"] > 0), len(T["assignments"])),
    }

    # --- file problems ---
    m["files"] = {
        "file_issue_rate_pct": _pct(sum(1 for s in subs if s["file_check_status"] != "COMPLETE"), len(subs)),
        "by_status": dict(Counter(s["file_check_status"] for s in subs)),
        "artifacts_per_submission_mean": round(len(T["submission_artifacts"]) / len(subs), 2),
    }

    # --- grading ---
    finals1 = [gmap[s["submission_id"]]["final_score"] for s in first if s["submission_id"] in gmap]
    bands = Counter()
    for x in finals1:
        bands["<50" if x < 50 else "50-59" if x < 60 else "60-69" if x < 70 else "70-79" if x < 80 else "80-89" if x < 90 else "90-100" if x <= 100 else ">100"] += 1
    turn = [(parse(g["graded_at_utc"]) - parse(sub_by[g["submission_id"]]["submitted_at_utc"])).total_seconds() / 3600 for g in grades]
    crit_by = {c["criterion_id"]: c for c in T["rubric_criteria"]}
    attain = defaultdict(list)
    for sc in T["grade_criterion_scores"]:
        c = crit_by[sc["criterion_id"]]
        attain[c["criterion_name"]].append(sc["awarded_points"] / c["max_points"])
    m["grading"] = {
        "graded_submissions": len(grades), "pending_grading": len(subs) - len(grades),
        "first_attempt_final_mean": round(statistics.mean(finals1), 2), "first_attempt_final_median": round(statistics.median(finals1), 2),
        "first_attempt_final_stdev": round(statistics.pstdev(finals1), 2), "score_bands_first_attempt": dict(bands),
        "mean_late_penalty_points_when_late": round(statistics.mean([g["late_penalty_points"] for g in grades if g["late_penalty_points"] > 0] or [0]), 2),
        "grading_turnaround_hours": {"median": _q(turn, 0.5), "p90": _q(turn, 0.9)},
        "rubric_attainment_pct_by_criterion": {k: round(100 * statistics.mean(v), 1) for k, v in sorted(attain.items())},
        "rubrics_revised_after_publication": sum(1 for r in T["rubrics"] if r["version_no"] > 1),
        "grades_revised_on_appeal": sum(1 for g in grades if g["grade_status"] == "REVISED"),
    }

    # --- resubmission ---
    rs = T["resubmissions"]
    attempts = Counter(s["attempt_number"] for s in subs)
    uplift = []
    for r in rs:
        if r["new_submission_id"]:
            a, b = gmap.get(r["original_submission_id"]), gmap.get(r["new_submission_id"])
            if a and b:
                uplift.append(b["raw_score"] - a["raw_score"])
    m["resubmission"] = {
        "requests": len(rs), "by_status": dict(Counter(r["status"] for r in rs)),
        "decision_reasons": dict(Counter(r["decision_reason"] for r in rs if r["decision_reason"])),
        "approval_rate_pct": _pct(sum(1 for r in rs if r["status"] in ("APPROVED", "EXPIRED")), sum(1 for r in rs if r["decided_at_utc"])),
        "attempts_distribution": dict(sorted(attempts.items())),
        "resubmission_attempts_pct_of_submissions": _pct(sum(v for k, v in attempts.items() if k > 1), len(subs)),
        "mean_raw_score_uplift": round(statistics.mean(uplift), 2) if uplift else 0,
    }

    # --- appeals ---
    ap = T["appeals"]
    decided = [a for a in ap if a["decided_at_utc"]]
    dur = [(parse(a["decided_at_utc"]) - parse(a["filed_at_utc"])).total_seconds() / 86400 for a in decided]
    adj = [a["adjusted_score"] - a["original_score"] for a in ap if a["status"] == "UPHELD"]
    m["appeals"] = {
        "appeals": len(ap), "appeal_rate_pct_of_grades": _pct(len(ap), len(grades)),
        "by_status": dict(Counter(a["status"] for a in ap)), "by_reason": dict(Counter(a["reason_code"] for a in ap)),
        "by_decision": dict(Counter(a["decision_code"] for a in ap if a["decision_code"])),
        "uphold_rate_pct_of_decided": _pct(sum(1 for a in decided if a["status"] == "UPHELD"), len(decided)),
        "mean_points_gained_when_upheld": round(statistics.mean(adj), 2) if adj else 0,
        "decision_time_days": {"median": _q(dur, 0.5), "p90": _q(dur, 0.9)},
        "open_appeals_at_cutoff": sum(1 for a in ap if a["status"] in ("SUBMITTED", "IN_REVIEW")),
    }

    # --- enrolment / population ---
    m["population"] = {
        "enrollment_status": dict(Counter(e["enrollment_status"] for e in T["enrollments"])),
        "learner_status": dict(Counter(l["status"] for l in T["learners"])),
        "courses_by_term": dict(Counter(c["term"] for c in T["courses"])),
        "submission_status": dict(Counter(s["status"] for s in subs)),
        "assignment_status": dict(Counter(a["status"] for a in T["assignments"])),
        "audit_events_by_action": dict(Counter(a["action_type"] for a in T["audit_logs"])),
    }
    return m


def render_markdown(m: Dict[str, Any]) -> str:
    out = ["# Evaluation metrics (computed from input tables only)", ""]
    for section, body in m.items():
        out += [f"## {section}", "", "| metric | value |", "| :--- | :--- |"]
        for k, v in body.items():
            out.append(f"| {k} | {v} |")
        out.append("")
    return "\n".join(out)
