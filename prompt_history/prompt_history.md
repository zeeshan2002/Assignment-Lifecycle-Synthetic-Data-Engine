# Assessment --- Development Prompt History

This document records the prompts used during the development of the
Assignment Management System. The prompts are organized in the order of
the project work, from planning and architecture through implementation,
validation, and final verification.

## Prompt 1 --- Project Planning

Analyze the assignment management requirements and break them into
manageable development tasks. Identify entities, relationships, business
rules, edge cases and deliverables. Suggest a practical implementation
plan.

## Prompt 2 --- Database Design

Review the database structure for all required entities. Define primary
keys, foreign keys, relationships, constraints and lifecycle states.
Identify missing relationships and potential data consistency issues.

## Prompt 3 --- Project Setup and Architecture

Set up the Python project with separate modules for generators, business
logic, validation and exporters. Use Python's built-in `csv`, `random`,
`json`, `hashlib` and `sqlite3` modules without unnecessary external
dependencies. Keep the code modular and configuration-driven.

## Prompt 4 --- Master Data Generation

Implement master data generation for courses, learners, assignments and
rubrics. Use deterministic IDs and seed `20261022`. Use Python lists and
built-in random choices for synthetic values. Ensure all relationships
and rubric maximum scores are valid.

## Prompt 5 --- Reproducible Random Generation

Implement a reusable PRNG wrapper in `src/generator/prng.py`. Give each
learner and assignment its own repeatable random stream so that
generated records remain deterministic and independent of generation
order. Verify that the same seed produces identical results.

## Prompt 6 --- Enrollment and Submissions

Implement enrollment and submission generation. Generate realistic
timestamps, attempts and artifact metadata. Ensure submissions belong to
enrolled learners and published assignments. Include on-time, late and
missing-file scenarios. Use the existing CSV generation approach.

## Prompt 7 --- Grading and Feedback

Implement rubric-based grading, criterion scores, feedback and late
penalties using plain Python calculations. Validate score limits and
ensure final grades reconcile with rubric scores. Preserve previous
grade versions.

## Prompt 8 --- Resubmission and Appeals

Implement resubmission policies and appeal workflows. Preserve
submission and grade history. Support appeal approval and rejection, and
ensure approved appeals create new grade versions with corresponding
audit records.

## Prompt 9 --- Audit and Lifecycle Verification

Verify lifecycle transitions for assignments, submissions, grades and
appeals. Ensure invalid transitions are rejected and important state
changes are recorded in `AuditLog` without overwriting historical
records.

## Prompt 10 --- Anomaly Testing

Introduce and test four labelled anomalies: unenrolled learner
submission, grade exceeding rubric maximum, duplicate late penalty and
appeal without audit history. Store expected results separately in
`ground_truth.csv`/`ground_truth.json` and verify detection
independently.

## Prompt 11 --- Data Validation and Exports

Validate primary keys, foreign keys, duplicate records, dates, score
calculations, penalties and lifecycle consistency. Export data using
Python's built-in `csv` and `json` modules. Generate `schema.sql` and
`seed_data.sql` as plain SQL files. Use `sqlite3` to build `ams.sqlite`,
enable foreign keys and verify database joins.

## Prompt 12 --- Reproducibility and Final Review

Run the generator twice with seed `20261022`. Compare record counts and
SHA-256 checksums. Verify all assessment requirements, fix validation
failures, and update `README.md` with architecture, dependencies,
execution commands, data dictionary, source manifest and final test
results.

------------------------------------------------------------------------

## Implementation Notes

The prompts reflect the project's intended implementation choices:

-   **CSV input/output:** Python's built-in `csv` module.
-   **Synthetic values:** Short predefined lists and Python's built-in
    `random` module.
-   **Deterministic generation:** A custom PRNG wrapper in
    `src/generator/prng.py`, with independent repeatable random streams
    for learners and assignments.
-   **Database export and verification:** Python's built-in `sqlite3`
    module, used to create `sql/ams.sqlite`, enable foreign-key
    enforcement and verify joins.
-   **SQL scripts:** `schema.sql` and `seed_data.sql` are generated as
    plain-text SQL files.
-   **Calculations:** Plain Python logic; Pandas and Faker are not used.

This is a prompt-history record, not a claim that every implementation
step was completed exactly as requested. The final code, tests and
generated outputs should be used as the evidence of what was actually
implemented.
