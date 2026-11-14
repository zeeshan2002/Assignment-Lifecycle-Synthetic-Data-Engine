"""End-to-end pipeline tests at starter scale: volume, determinism, cleanliness, anomaly detection, isolation."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import SCALE_PRESETS
from src.generator.pipeline import generate_dataset
from src.schema import ANOMALY_TYPES, GROUND_TRUTH_TABLE, TABLES
from src.validator.engine import Validator

SEED = 20261022
STARTER = SCALE_PRESETS["starter"]
CLEAN = replace(STARTER, anomalies_per_type=0)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.T, cls.gt = generate_dataset(SEED, STARTER)
        cls.Tc, cls.gtc = generate_dataset(SEED, CLEAN)

    def test_volumes_hit_targets_exactly(self):
        self.assertEqual(len(self.T["assignments"]), STARTER.num_assignments)
        self.assertEqual(len(self.T["learners"]), STARTER.num_learners)
        self.assertEqual(len(self.T["submissions"]), STARTER.num_submissions)   # total, incl. resubmission attempts
        self.assertEqual(len(self.Tc["submissions"]), STARTER.num_submissions)

    def test_every_table_has_unique_pk_and_all_columns(self):
        for t in TABLES:
            rows = self.T[t.name]
            self.assertTrue(rows, t.name)
            self.assertEqual(len({r[t.pk] for r in rows}), len(rows), t.name)
            self.assertEqual(set(rows[0]), set(t.col_names), t.name)

    def test_deterministic_for_same_seed(self):
        T2, gt2 = generate_dataset(SEED, STARTER)
        self.assertEqual(T2, self.T)
        self.assertEqual(gt2, self.gt)

    def test_many_seeds_validate_clean_and_with_exact_anomaly_detection(self):
        # regression: a rare resubmission/appeal ordering bug only showed up for some seeds
        for seed in range(1, 21):
            for scale in (CLEAN, STARTER):
                T, gt = generate_dataset(seed, scale)
                rep = Validator(T, gt).run()
                self.assertEqual(len(T["submissions"]), scale.num_submissions, seed)
                self.assertTrue(rep["summary"]["all_passed"], (seed, scale.anomalies_per_type,
                                                              [s["sample_unexpected"] for s in rep["stages"]]))
                if scale is CLEAN:
                    self.assertEqual(rep["summary"]["total_violations"], 0, seed)

    def test_different_seed_changes_data(self):
        T2, _ = generate_dataset(SEED + 1, STARTER)
        self.assertNotEqual(T2["submissions"], self.T["submissions"])

    def test_clean_baseline_has_zero_violations(self):
        rep = Validator(self.Tc, self.gtc).run()
        self.assertEqual(rep["summary"]["total_violations"], 0, [s["sample_unexpected"] for s in rep["stages"]])
        self.assertTrue(all(g["label_class"] != "ANOMALY" for g in self.gtc))

    def test_injected_anomalies_exactly_detected(self):
        rep = Validator(self.T, self.gt).run()
        self.assertTrue(rep["summary"]["all_passed"], [s["sample_unexpected"] for s in rep["stages"]])
        self.assertEqual(rep["summary"]["unexpected_violations"], 0)
        per = rep["ground_truth"]["per_type"]
        for t in ANOMALY_TYPES:
            self.assertEqual(per[t]["labelled"], STARTER.anomalies_per_type, t)
            self.assertEqual((per[t]["precision"], per[t]["recall"]), (1.0, 1.0), t)

    def test_required_edge_cases_present_and_labelled(self):
        issues = {g["issue_type"] for g in self.gt if g["label_class"] == "ANOMALY"}
        for required in ("UNENROLLED_LEARNER_SUBMISSION", "GRADE_EXCEEDS_MAX", "DOUBLE_LATE_PENALTY", "APPEAL_NO_AUDIT_LOG"):
            self.assertIn(required, issues)

    def test_ground_truth_not_leaked_into_inputs(self):
        gt_cols = {"ground_truth_id", "label_class", "issue_type", "expected_value", "actual_value", "expected_decision"}
        self.assertTrue(gt_cols <= set(GROUND_TRUTH_TABLE.col_names))
        for t in TABLES:
            self.assertFalse(gt_cols & set(t.col_names), t.name)
        # no anomaly label text in any input string field
        for t in TABLES:
            for r in self.T[t.name][:200]:
                for v in r.values():
                    if isinstance(v, str):
                        self.assertNotIn("ANOMALY", v)
                        self.assertNotIn("INJECTED", v.upper())
        gt_ids = {g["ground_truth_id"] for g in self.gt}
        self.assertEqual(len(gt_ids), len(self.gt))

    def test_anomalies_are_spread_not_clustered(self):
        a = sorted(g["record_id"] for g in self.gt if g["issue_type"] == "GRADE_EXCEEDS_MAX")
        asn_ids = {x.split("-LRN-")[0] for x in a}
        self.assertEqual(len(asn_ids), len(a))      # distinct assignments

    def test_audit_ids_sequential_and_time_ordered(self):
        logs = self.T["audit_logs"]
        self.assertEqual([int(r["audit_id"].rsplit("-", 1)[1]) for r in logs], list(range(1, len(logs) + 1)))
        ts = [r["timestamp_utc"] for r in logs]
        self.assertEqual(ts, sorted(ts))

    def test_history_is_retained(self):
        revised = [g for g in self.Tc["grades"] if g["grade_status"] == "REVISED"]
        self.assertTrue(revised)
        versions = {}
        for v in self.Tc["grade_versions"]:
            versions.setdefault(v["grade_id"], []).append(v["version_no"])
        for g in revised:
            self.assertEqual(sorted(versions[g["grade_id"]]), [1, 2])
        mutate = {a["entity_id"] for a in self.Tc["audit_logs"] if a["action_type"] == "GRADE_MUTATE"}
        self.assertEqual(mutate, {g["grade_id"] for g in revised})

    def test_coverage_of_failure_and_exception_paths(self):
        kinds = {g["issue_type"] for g in self.gt if g["label_class"] != "ANOMALY"}
        for k in ("MISSING_FILE", "EMPTY_FILE", "RESUBMISSION_EXPIRED", "RESUBMISSION_DENIED_OUTSIDE_WINDOW"):
            self.assertIn(k, kinds)
        self.assertTrue(any(k.startswith("BOUNDARY_") for k in kinds))
        self.assertTrue(any(s["attempt_number"] == 2 for s in self.T["submissions"]))
        self.assertTrue(any(s["is_late"] for s in self.T["submissions"]))


if __name__ == "__main__":
    unittest.main()
