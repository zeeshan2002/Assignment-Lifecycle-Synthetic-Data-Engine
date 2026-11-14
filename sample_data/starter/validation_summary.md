# Validation summary

* **Overall**: PASS (a run passes when every violation is a labelled anomaly and nothing unexpected is found)
* **Total checks executed**: 105812
* **Violations found**: 12 (labelled anomalies: 12, unexpected: 0)

## Stages

| Stage | Check | Status | Checks | Violations | Labelled anomalies | Unexpected |
| :-: | :--- | :--- | ---: | ---: | ---: | ---: |
| 1 | Primary keys, ID formats and ID derivation | `PASS` | 14396 | 0 | 0 | 0 |
| 2 | Foreign keys and join integrity (incl. enrolment window) | `PASS_WITH_LABELLED_ANOMALIES` | 19580 | 2 | 2 | 0 |
| 3 | Domain: required fields, enums, ranges, cross-field rules | `PASS` | 3893 | 0 | 0 | 0 |
| 4 | Chronology and data cut-off | `PASS` | 31147 | 0 | 0 | 0 |
| 5 | Arithmetic reconciliation, rubric scoring, time-zone due logic | `PASS_WITH_LABELLED_ANOMALIES` | 20549 | 4 | 4 | 0 |
| 6 | Lifecycle state machines, version history and policy rules | `PASS_WITH_LABELLED_ANOMALIES` | 14583 | 6 | 6 | 0 |
| 7 | Duplicate and contiguity checks | `PASS` | 1407 | 0 | 0 | 0 |
| 8 | Ground-truth reconciliation (precision / recall) | `PASS` | 257 | 0 | 0 | 0 |

### Violations by rule

* Stage 2: `ENROLLMENT_WINDOW` x2
* Stage 5: `GRADE_MAX` x2, `LATE_PENALTY_RULE` x2
* Stage 6: `APPEAL_AUDIT` x2, `POLICY_APPEAL_WINDOW` x2, `POLICY_RESUBMISSION` x2

## Ground-truth reconciliation (stage 8)

| Anomaly type | Labelled | Detected | TP | FP | FN | Precision | Recall |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `UNENROLLED_LEARNER_SUBMISSION` | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |
| `GRADE_EXCEEDS_MAX` | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |
| `DOUBLE_LATE_PENALTY` | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |
| `APPEAL_NO_AUDIT_LOG` | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |
| `RESUBMISSION_POLICY_VIOLATION` | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |
| `APPEAL_OUTSIDE_WINDOW_UPHELD` | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |

Label classes: {'ANOMALY': 12, 'EXCEPTION_PATH': 121, 'BOUNDARY_VALID': 5}
