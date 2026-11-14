"""
Assignments, versioned Rubrics and RubricCriteria.

Deadlines are authored as LOCAL wall-clock times and converted to UTC with DST rules, so the data
contains real DST-boundary cases. Some rubrics are revised after publication (version 02); a grade
always uses the rubric version in force at its grading instant.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from src.config import (ScaleConfig, SNAPSHOT_AT, MAX_SCORE, LATE_PENALTY_PER_DAY, LATE_WINDOW_DAYS,
                        RESUB_REQUEST_WINDOW_DAYS, APPEAL_WINDOW_DAYS)
from src.generator.prng import SeededRNG
from src.id_generator import IdGenerator
from src.timeutil import fmt, fmt_local, local_to_utc, parse, utc_offset_minutes, utc_to_local

TITLES = [
    "Problem Set: Fundamental Concepts", "Lab: Algorithmic Verification", "Project Milestone: Core Architecture",
    "Problem Set: Advanced Structures", "Lab: Database & State Transitions", "Practical Project",
    "Problem Set: Concurrency & Async Workflows", "Project Milestone: Service Integration",
    "Lab: End-to-End Validation", "Capstone Submission",
]

# (name, description, max_points) -- every template sums to 100
RUBRIC_TEMPLATES = [
    [("Problem Solving & Core Logic", "Accurate solution and logic.", 35.0),
     ("Code Quality & Architecture", "Clean, modular structure.", 25.0),
     ("Testing & Verification", "Unit tests and edge cases.", 20.0),
     ("Documentation & Traceability", "Readme, schema and annotations.", 20.0)],
    [("Functional Implementation", "Meets all business requirements.", 50.0),
     ("Validation & Error Handling", "Handles exceptions and boundaries.", 30.0),
     ("Technical Reporting", "Clear design rationale and outcomes.", 20.0)],
    [("Algorithm Implementation", "Correct and efficient algorithm.", 30.0),
     ("Data Integrity & Validation", "Type checks, keys and invariants.", 25.0),
     ("Performance & Scaling", "Efficient at volume.", 15.0),
     ("Test Coverage & Harness", "Automated pass/fail tests.", 15.0),
     ("Documentation & Readme", "Instructions and schema notes.", 15.0)],
    [("Analysis & Approach", "Soundness of the chosen approach.", 40.0),
     ("Implementation", "Working, readable implementation.", 20.0),
     ("Evaluation", "Quality of experiments / metrics.", 20.0),
     ("Presentation", "Clarity of the write-up.", 20.0)],
]
LOCAL_DUE_TIMES = [(23, 59), (17, 0), (12, 0), (9, 0)]
LOCAL_DUE_WEIGHTS = (0.60, 0.20, 0.10, 0.10)


class AssignmentGenerator:
    def __init__(self, rng: SeededRNG, ids: IdGenerator, scale: ScaleConfig):
        self.rng, self.ids, self.scale = rng, ids, scale

    def generate(self, courses: List[dict], course_tz: Dict[str, str]) -> Tuple[List[dict], List[dict], List[dict]]:
        assignments, rubrics, criteria = [], [], []
        total = self.scale.num_assignments
        per, rem = divmod(total, len(courses))
        asn_no = 1
        for ci, course in enumerate(courses):
            n = per + (1 if ci < rem else 0)
            cstart = parse(course["start_date_utc"])
            tz = course_tz[course["course_id"]]
            for k in range(1, n + 1):
                aid = self.ids.assignment_id(asn_no)
                asn_no += 1
                r = self.rng.spawn("assignment", aid)
                title = f"{course['course_code']}: {r.choice(TITLES)} (Part {k})"
                # publication: 09:00 local, one assignment per week
                pub_day = (cstart + timedelta(days=(k - 1) * 7 + r.randint(1, 3))).replace(hour=0, minute=0, second=0)
                pub_local = datetime(pub_day.year, pub_day.month, pub_day.day, 9, 0, 0)
                published = local_to_utc(tz, pub_local)
                created = published - timedelta(days=r.randint(1, 5), hours=r.randint(0, 6))
                # deadline: local wall-clock 7-12 days later
                hh, mm = r.choices(LOCAL_DUE_TIMES, weights=LOCAL_DUE_WEIGHTS, k=1)[0]
                due_local = datetime(pub_day.year, pub_day.month, pub_day.day, hh, mm, 0) + timedelta(days=r.randint(7, 12))
                due = local_to_utc(tz, due_local)
                cutoff = due + timedelta(days=LATE_WINDOW_DAYS)
                grace = r.choices([0, 10, 30], weights=(0.70, 0.15, 0.15), k=1)[0]
                allow = r.random() < 0.85
                max_resub = r.choice([1, 2]) if allow else 0
                is_draft = r.random() < self.scale.draft_rate
                if is_draft:
                    status = "DRAFT"
                elif cutoff <= SNAPSHOT_AT:
                    status = "CLOSED"
                else:
                    status = "PUBLISHED"
                assert published <= SNAPSHOT_AT or is_draft
                assignments.append({
                    "assignment_id": aid, "course_id": course["course_id"], "title": title,
                    "description": f"Implement the required modules and test cases for {title}. "
                                   f"Submit source artefacts and an evaluation report.",
                    "created_by": course["instructor_id"], "created_at_utc": fmt(created),
                    "published_at_utc": None if is_draft else fmt(published),
                    "due_at_utc": fmt(due), "due_at_local": fmt_local(due_local), "timezone": tz,
                    "utc_offset_minutes": utc_offset_minutes(tz, due),
                    "grace_period_minutes": grace, "late_penalty_per_day": LATE_PENALTY_PER_DAY,
                    "late_cutoff_utc": fmt(cutoff), "max_score": MAX_SCORE,
                    "allow_resubmission": allow, "max_resubmissions": max_resub,
                    "resubmission_window_days": RESUB_REQUEST_WINDOW_DAYS, "appeal_window_days": APPEAL_WINDOW_DAYS,
                    "status": status,
                })
                # ---- rubric version 1 (and optional revision 2) ----
                tmpl_idx = r.randint(0, len(RUBRIC_TEMPLATES) - 1)
                revised = (not is_draft) and r.random() < self.scale.rubric_revision_rate
                v1_from = created
                v2_from = published + timedelta(hours=r.randint(12, 72)) if revised else None
                versions = [(1, tmpl_idx, v1_from, v2_from, "SUPERSEDED" if revised else "ACTIVE", created)]
                if revised:
                    t2 = (tmpl_idx + 1 + r.randint(0, len(RUBRIC_TEMPLATES) - 2)) % len(RUBRIC_TEMPLATES)
                    versions.append((2, t2, v2_from, None, "ACTIVE", v2_from))
                for vno, tidx, eff_from, eff_to, rstatus, created_at in versions:
                    rid = self.ids.rubric_id(aid, vno)
                    rubrics.append({
                        "rubric_id": rid, "assignment_id": aid, "version_no": vno, "title": f"Rubric v{vno}: {title}",
                        "total_points": 100.0, "effective_from_utc": fmt(eff_from),
                        "effective_to_utc": fmt(eff_to) if eff_to else None, "status": rstatus,
                        "created_by": course["instructor_id"], "created_at_utc": fmt(created_at),
                    })
                    for seq, (cname, cdesc, mx) in enumerate(RUBRIC_TEMPLATES[tidx], start=1):
                        criteria.append({
                            "criterion_id": self.ids.criterion_id(rid, seq), "rubric_id": rid, "sequence_no": seq,
                            "criterion_name": cname, "description": cdesc, "max_points": mx, "weight_pct": mx,
                        })
        return assignments, rubrics, criteria
