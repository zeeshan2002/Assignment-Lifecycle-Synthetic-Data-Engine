"""Mutation tests: corrupt a clean dataset in one specific way and assert the validator reports it."""

import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import SCALE_PRESETS
from src.generator.pipeline import generate_dataset
from src.validator.engine import Validator

CLEAN, _ = generate_dataset(20261022, replace(SCALE_PRESETS["starter"], anomalies_per_type=0))


def rules_after(mutator):
    T = copy.deepcopy(CLEAN)
    mutator(T)
    v = Validator(T, None)
    v.run()
    return {x["rule"] for x in v.violations}, v


def first(T, table, pred=lambda r: True):
    return next(r for r in T[table] if pred(r))


class MutationTests(unittest.TestCase):
    def test_baseline_clean(self):
        v = Validator(copy.deepcopy(CLEAN), None)
        v.run()
        self.assertEqual(v.violations, [])

    def test_duplicate_primary_key(self):
        def m(T): T["learners"].append(dict(T["learners"][0]))
        self.assertIn("PK_UNIQUE", rules_after(m)[0])

    def test_orphan_foreign_key(self):
        def m(T): first(T, "submissions")["assignment_id"] = "ASN-2026-999999"
        self.assertIn("FK_EXISTS", rules_after(m)[0])

    def test_bad_enum(self):
        def m(T): first(T, "submissions")["status"] = "WEIRD"
        self.assertIn("ENUM", rules_after(m)[0])

    def test_raw_score_not_sum_of_criteria(self):
        def m(T):
            g = first(T, "grades", lambda r: r["raw_score"] > 10)
            g["raw_score"] = round(g["raw_score"] - 3, 2)
        self.assertIn("RAW_EQ_SUM", rules_after(m)[0])

    def test_final_formula(self):
        def m(T): first(T, "grades")["final_score"] = 1.0
        self.assertIn("FINAL_FORMULA", rules_after(m)[0])

    def test_grade_over_max_is_tagged(self):
        def m(T):
            g = first(T, "grades", lambda r: r["raw_score"] > 40)
            sc = next(s for s in T["grade_criterion_scores"] if s["grade_id"] == g["grade_id"])
            sc["awarded_points"] += 100
        rules, v = rules_after(m)
        self.assertTrue(any(x["anomaly"] == "GRADE_EXCEEDS_MAX" for x in v.violations))

    def test_double_penalty_is_tagged(self):
        def m(T):
            s = first(T, "submissions", lambda r: r["late_days"] > 0 and r["status"] != "SUBMITTED")
            g = next(g for g in T["grades"] if g["submission_id"] == s["submission_id"])
            g["late_penalty_points"] = round(g["late_penalty_points"] * 2 + 1, 2)
        _, v = rules_after(m)
        self.assertTrue(any(x["anomaly"] == "DOUBLE_LATE_PENALTY" for x in v.violations))

    def test_timezone_tampering(self):
        def m(T):
            a = first(T, "assignments", lambda r: r["timezone"] == "America/New_York")
            a["utc_offset_minutes"] = 0
        self.assertIn("TZ_OFFSET", rules_after(m)[0])

    def test_due_time_not_matching_local(self):
        def m(T): first(T, "assignments")["due_at_local"] = "2026-01-01T00:00:00"
        self.assertIn("TZ_DUE_LOCAL_TO_UTC", rules_after(m)[0])

    def test_lateness_flag(self):
        def m(T):
            s = first(T, "submissions", lambda r: not r["is_late"])
            s["is_late"], s["late_days"] = True, 2
        self.assertIn("LATE_DERIVATION", rules_after(m)[0])

    def test_unenrolled_submission_is_tagged(self):
        def m(T):
            s = first(T, "submissions")
            s["enrollment_id"] = None
        _, v = rules_after(m)
        self.assertTrue(any(x["anomaly"] == "UNENROLLED_LEARNER_SUBMISSION" for x in v.violations))

    def test_submission_before_enrolment(self):
        def m(T):
            s = first(T, "submissions", lambda r: r["attempt_number"] == 1)
            e = next(e for e in T["enrollments"] if e["enrollment_id"] == s["enrollment_id"])
            e["enrolled_at_utc"] = "2030-01-01T00:00:00Z"
        self.assertIn("ENROLLMENT_WINDOW", rules_after(m)[0])

    def test_missing_audit_history_for_grade_change(self):
        def m(T):
            ap = first(T, "appeals", lambda r: r["status"] == "UPHELD")
            T["audit_logs"][:] = [a for a in T["audit_logs"] if not (a["action_type"] == "GRADE_MUTATE" and a["entity_id"] == ap["grade_id"])]
        _, v = rules_after(m)
        self.assertTrue(any(x["anomaly"] == "APPEAL_NO_AUDIT_LOG" for x in v.violations))

    def test_grade_overwritten_without_version(self):
        def m(T):
            g = first(T, "grades", lambda r: r["grade_status"] == "PUBLISHED")
            g["raw_score"] = round(g["raw_score"] + 1, 2)
            g["final_score"] = round(g["final_score"] + 1, 2)
        self.assertTrue({"GRADE_EQ_LATEST_VERSION", "RAW_EQ_SUM"} & rules_after(m)[0])

    def test_illegal_lifecycle_transition(self):
        def m(T):
            a = first(T, "audit_logs", lambda r: r["action_type"] == "SUBMISSION_GRADED")
            a["from_status"] = "APPEALED"
        self.assertIn("AUDIT_TRANSITIONS", rules_after(m)[0])

    def test_resubmission_after_window_approved_is_tagged(self):
        def m(T):
            r = first(T, "resubmissions", lambda r: r["status"] == "APPROVED")
            r["requested_at_utc"] = "2026-12-31T00:00:00Z"
        rules, v = rules_after(m)
        self.assertTrue({"POLICY_RESUBMISSION", "CUTOFF", "CHRON_RESUBMISSION"} & rules)

    def test_rubric_sum(self):
        def m(T): first(T, "rubric_criteria")["max_points"] += 5
        self.assertIn("RUBRIC_SUM", rules_after(m)[0])

    def test_artifact_checksum_for_empty_file(self):
        def m(T):
            a = first(T, "submission_artifacts")
            a["file_size_bytes"] = 0
        self.assertTrue({"ARTIFACT_META", "FILE_STATUS"} & rules_after(m)[0])

    def test_duplicate_attempt(self):
        def m(T):
            s = copy.deepcopy(first(T, "submissions"))
            s["submission_id"] = s["submission_id"] + "X"
            T["submissions"].append(s)
        self.assertTrue({"DUP_ATTEMPT", "ID_FORMAT"} & rules_after(m)[0])

    def test_event_after_cutoff(self):
        def m(T): first(T, "submissions")["submitted_at_utc"] = "2027-05-01T00:00:00Z"
        self.assertIn("CUTOFF", rules_after(m)[0])

    def test_audit_gap_detected(self):
        def m(T): del T["audit_logs"][5]
        self.assertIn("ID_SEQUENTIAL", rules_after(m)[0])


if __name__ == "__main__":
    unittest.main()
