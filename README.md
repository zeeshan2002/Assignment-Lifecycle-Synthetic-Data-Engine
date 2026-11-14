# Assignment Management System (AMS) - Assignment Lifecycle Synthetic Data Engine

Deterministic synthetic data for the workflow **assignment publication -> submissions -> rubric-based grading -> feedback -> resubmissions -> appeals**, with labelled edge cases, a separate ground truth, an 8-stage validator, evaluation metrics and a reproducibility check. Python 3.10+, standard library only (no third-party packages).

| Quantity (full scale) | Value |
| :--- | ---: |
| Assignments / Learners / Courses | 1,000 / 10,000 / 300 |
| **Submissions (all attempts, incl. resubmissions)** | **30,000** |
| Seed | `20261022` |

> **On the 30,000 figure.** The brief asks for "30,000 submissions" and lists resubmissions as something *included* in that volume, so 30,000 is the **total** number of `submissions` rows (first attempts + resubmission attempts). Hitting the total exactly is enforced by the generator and by the tests.

## Quick start (first run, about a minute)

1. **Check Python** (3.10 or newer, nothing to install): `python --version`. On Windows, if `python` is not found, use `py` instead (for example `py generate.py ...`).
2. **Open a terminal in the project folder** (the one that contains `generate.py`), for example `cd path\to\project`.
3. **Generate a small dataset** into its own folder, so nothing existing is overwritten (`data_*` folders are git-ignored):
   ```bash
   python generate.py --scale starter --output-dir ./data_quick
   ```
   It prints five progress steps and ends with `done. 44 files ... (validation: PASS)` followed by a table of row counts (1,500 submissions at this scale).
4. **Validate it independently** from the exported CSV files:
   ```bash
   python validate.py --data-dir ./data_quick
   ```
   A healthy run says `Overall: PASS` and `unexpected: 0`. At starter scale it reports 12 violations, and all 12 are the deliberately injected, labelled anomalies (2 of each of 6 types).
5. **Run the tests** (about 45 s): `python -m unittest discover -s tests` should end with `OK`.
6. **Look at the results**, in this order:
   * `data_quick/validation_summary.md` - per-stage results and precision/recall per anomaly type
   * `data_quick/metrics.md` - late rate, score distribution, resubmission and appeal KPIs
   * `data_quick/csv/` - the input tables; `data_quick/ground_truth/` - the separate labels
   * [`data_dictionary.md`](data_dictionary.md) - every field explained

For the full 30,000-submission dataset use `--scale full --output-dir ./data` (about 35 s, about 400 MB of output). The reproducibility check (`python verify_reproducibility.py`) generates the dataset twice, so at full scale allow a few minutes; add `--scale starter` for a quick run.

**Troubleshooting**
* `python` / `py` not found -> install Python 3.10+ from python.org and tick "Add to PATH".
* `ModuleNotFoundError: No module named 'src'` -> you are not in the project folder; `cd` into the folder containing `generate.py`.
* `generate.py` exits with a non-zero code -> validation found an unexpected defect; read `validation_summary.md` (sample messages are listed per stage).
* One test is reported as skipped (`test_matches_zoneinfo_when_available`) -> your system has no time-zone database; this is harmless (`pip install tzdata` removes the skip).

## 1. Commands

```bash
# generate (starter = 50 assignments / 500 learners / 1,500 submissions; full = 1,000 / 10,000 / 30,000)
python generate.py --seed 20261022 --scale starter --output-dir ./data
python generate.py --seed 20261022 --scale full    --output-dir ./data

# optional: clean baseline without injected anomalies
python generate.py --seed 20261022 --scale starter --output-dir ./data_clean --anomalies-per-type 0

# validate an exported dataset (reads the CSVs + the separate ground truth)
python validate.py --data-dir ./data

# step 10: regenerate twice with the same seed, compare row counts and SHA-256 of every file
python verify_reproducibility.py --seed 20261022 --scale full

# tests (46, about 45 s; includes 20 seeds at starter scale)
python -m unittest discover -s tests

# regenerate data_dictionary.md from the schema
python build_docs.py
```

`generate.py` exits non-zero if validation fails. A full-scale run takes about 35 s on a laptop (generate ~10 s, validate ~8 s, the rest is exporting ~400 MB).

> **What is in the repository.** The full-scale output (`data/`, about 400 MB) is git-ignored because it is fully reproducible with the commands above (its SHA-256 values are in `source_manifest.json`). A committed **starter-scale sample** (seed 20261022, 1,500 submissions, about 24 MB) lives in [`sample_data/starter/`](sample_data/starter) with the same structure, validation summary, metrics and manifest, so the output can be inspected without running anything.

## 2. What is produced (`data/`)

```
data/
  csv/   *.csv                 18 input tables (RFC-4180, LF line endings)
  json/  *.json                the same 18 tables as JSON arrays
  sql/   schema.sql            ANSI DDL generated from src/schema.py (PK, FK, UNIQUE, enum/range CHECKs)
         seed_data.sql         batched INSERTs in FK-safe order
         ams.sqlite            loaded with PRAGMA foreign_keys=ON + foreign_key_check (joins enforced)
  ground_truth/ ground_truth.csv|json    labels - SEPARATE from every input table
  data_dictionary.md           field-level dictionary (type, required, allowed values, units, uniqueness, validation rule)
  metrics.json|md              evaluation KPIs computed from the input tables only
  validation_summary.json|md   per-stage results + per-anomaly precision/recall
  source_manifest.json         seed, command, scale parameters, row counts, SHA-256 + size of every file, provenance
```

## 3. Model

18 input tables. Full field specification: [`data_dictionary.md`](data_dictionary.md) (generated, so it cannot drift from the code).

```
Staff ---1:N--- Course ---N:M(CourseStaff)--- Staff        Course ---N:M(Enrollment)--- Learner
Course 1:N Assignment 1:N Rubric(versions) 1:N RubricCriterion
Assignment 1:N Submission(attempts) N:1 Learner          Enrollment 1:N Submission
Submission 1:N SubmissionArtifact   Submission 0..1:1 Grade   Submission 0..1:1 Feedback
Grade 1:N GradeCriterionScore N:1 RubricCriterion          Grade 1:N GradeVersion (append-only history)
Submission 0..1:1 Resubmission 0..1:1 Submission(next attempt)   Grade 0..1:1 Appeal 0..1:1 GradeVersion(v2)
AuditLog: polymorphic append-only event history for every state change
```

Actors: **learner**, **instructor** (`INS-`), **academic administrator** (`ADM-`, reviews appeals), **support staff** (`SUP-`, processes enrolments, file checks and appeal intake), **platform administrator** (`PLT-`, creates courses). Every actor id is a foreign key into `staff` (or `learners`).

### IDs (deterministic, zero-padded, immutable, identical across files)
`ASN-2026-000001`, `RUB-<assignment-id>-01`, `SUB-<assignment-id>-<learner-id>-01`, `GRD-<submission-id>`, `APP-2026-000001`; plus `CRT-`, `ART-`, `GRV-`, `SCR-`, `FDB-`, `RES-`, `AUD-`, `GT-`, `INS/ADM/SUP/PLT-`, `CRS-`, `LRN-`, `ENR-`, `CSF-`. Counter-based ids (`RES`, `APP`, `AUD`, `ENR`, ...) are gap-free, and the validator re-derives every embedded id.

## 4. Business rules (all re-checked by the validator)

* **Time zones** - deadlines are authored as local wall-clock time and converted to UTC with built-in DST rules (US, EU, fixed offset): `due_at_local`, `timezone`, `utc_offset_minutes`, `due_at_utc`. Cases across DST changes exist; the engine is cross-checked against `zoneinfo` in the tests. Grace periods (0/10/30 min) are supported.
* **Lateness** - late iff `submitted > deadline + grace`; `late_days = ceil(elapsed/24h)`. Attempt 1 uses the assignment deadline, attempts >= 2 the resubmission deadline (stored in `applicable_deadline_utc`).
* **Scoring** - `raw = sum(criterion scores)` (each <= criterion max, raw <= 100); `late_penalty = min(raw, late_days x 5)`; `final = max(0, raw - penalty + adjustment)`. A grade stores the **rubric version in force at grading time** (rubrics are versioned; ~6 % are revised after publication).
* **Missing files** - `MISSING_FILE` (no artefact rows) and `EMPTY_FILE` (0-byte artefact) are scored 0 and are always resubmission-eligible.
* **Resubmission** - allowed iff the assignment allows it, attempts < 1 + max, requested within 5 days of grade publication, and final < 70 (or a file problem). Outcomes: `APPROVED`, `DENIED` (with reason), `EXPIRED` (unused), `REQUESTED` (open at cut-off). Approved attempts are due 7 days after approval; up to 3 attempts per assignment.
* **Appeals** - file within 7 days of grade publication; decided by an academic administrator. Outcomes are driven by a hidden grader-error variable: appeals on genuinely mis-scored criteria are upheld, others rejected, late ones `REJECTED_OUT_OF_WINDOW`. An upheld appeal creates **grade version 2** and a `GRADE_MUTATE` audit event; the grade row is the current projection and **no history is lost**.
* **Learner activity** - nothing after a drop / suspension / graduation date.
* **Data cut-off** `2026-11-13T00:00:00Z` - nothing is later; pending grades (94), open appeals (18), open resubmission windows and still-`PUBLISHED` assignments are genuine states.

Outcomes are derived from rules and latent variables (learner ability and engagement, assignment and criterion difficulty, grader error) rather than independent coin flips; every derived value (late flags, penalties, totals, statuses, audit events) is computed from source records.

## 5. Edge cases and ground truth

Valid baseline records are generated first. Each anomaly is then injected by re-building the target (assignment, learner) bundle with ONE override that is applied after all baseline random draws and uses a separate RNG stream, so unrelated rows are never silently changed. Targets are chosen uniformly at random over all valid pairs (no clustering), are disjoint, and every injection is labelled. Audit ids are assigned after injection, so there is no tell-tale gap.

| Anomaly (`label_class = ANOMALY`) | How it is detected |
| :--- | :--- |
| `UNENROLLED_LEARNER_SUBMISSION` *(required)* | no effective enrolment of the learner in the course at submission time |
| `GRADE_EXCEEDS_MAX` *(required)* | raw / final / a criterion score above the rubric maximum |
| `DOUBLE_LATE_PENALTY` *(required)* | `late_penalty_points` != single deduction |
| `APPEAL_NO_AUDIT_LOG` *(required)* | upheld appeal changed the grade with no `grade_versions` v2 and no `GRADE_MUTATE` event |
| `RESUBMISSION_POLICY_VIOLATION` *(extra)* | approved resubmission on an assignment that disallows it |
| `APPEAL_OUTSIDE_WINDOW_UPHELD` *(extra)* | appeal filed after the window but upheld |

`ground_truth/` also labels **valid** cases so false positives can be measured: `EXCEPTION_PATH` (missing/empty files, denied/expired resubmissions, upheld and out-of-window appeals) and `BOUNDARY_VALID` (submissions exactly at the deadline, grace edge, +1 s, 24 h, +24 h 1 s, late cutoff). Ground truth is never part of an input table or an input column.

## 6. Validation (8 stages)

1. PK uniqueness, ID formats, gap-free counters, id <-> field derivation
2. FK existence for every relationship, polymorphic audit refs, enrolment window, grader-in-course-staff, criterion-in-rubric, chain consistency
3. Required fields, enums, ranges, cross-field rules
4. Chronology (incl. rubric effective dates, data cut-off, audit ordering)
5. Arithmetic reconciliation, time-zone due logic, lateness, artefact metadata, version formulas
6. Lifecycle state machines (audit-log replay), derived statuses, resubmission and appeal policy, version history
7. Duplicates and contiguity
8. Ground-truth reconciliation: precision/recall per anomaly type + valid labels must match the data and must not be flagged

Stages 1-7 never read the ground truth. A violation tagged with an anomaly type is "labelled"; any other violation is **unexpected** and fails the run. Current result at full scale: **2.0 M checks, 60 violations - all 60 labelled anomalies, 0 unexpected, precision = recall = 1.0 for every type**; the clean baseline (`--anomalies-per-type 0`) has 0 violations. Mutation tests deliberately corrupt a clean dataset and confirm the validator reports it; they cover the main rule families (keys, enums, scoring, time zones, lateness, enrolment, audit history, lifecycle, cut-off) but not literally every rule. The pipeline also validates clean on 20 seeds at starter scale and on 6 seeds at full scale.

## 7. Reproducibility

`verify_reproducibility.py` generates twice (same seed) and compares the SHA-256 of **all 45 files** (CSV, JSON, SQL, SQLite, ground truth, metrics, validation summary, dictionary and the manifest) plus every row count. The manifest has no wall-clock timestamp. Each (assignment, learner) bundle draws from its own SHA-256-derived RNG stream, so results do not depend on iteration order.

## 8. Provenance

Fully synthetic. No external or public data, no personal data (names are invented, e-mails use example domains), no scraping. See `source_manifest.json` -> `provenance`.

## 9. Known limitations (honest scope)

* Participation is modelled per (assignment, learner) with engagement weights; there is no calendar-level attendance or per-assignment cohort effects.
* Time zones are the five used (UTC, New York, Los Angeles, London, Kolkata) with 2026 DST rules implemented in `src/timeutil.py`, not the full tz database.
* The hidden latent variables (ability, engagement, grader error) are intentionally **not** exported; they would leak labels.

## 10. AI usage and prompt history

This project was built with the help of an AI coding assistant (Claude Code). The tool used and every prompt submitted are documented in [`prompt_history/`](prompt_history): [`README.md`](prompt_history/README.md) and [`prompt_history.md`](prompt_history/prompt_history.md).

## 11. Layout

```
generate.py  validate.py  verify_reproducibility.py  build_docs.py
src/ config.py  schema.py  timeutil.py  id_generator.py  docs.py  metrics.py  report.py
     generator/ master_data.py assignments.py workflow.py anomalies.py assemble.py events.py pipeline.py prng.py
     validator/ engine.py      exporters/ files.py
tests/ test_timeutil.py  test_pipeline.py  test_validation.py
```
