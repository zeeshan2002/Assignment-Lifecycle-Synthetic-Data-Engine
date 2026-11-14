"""Renders data_dictionary.md from src/schema.py (single source of truth) plus the rule catalogue."""

from src import config as C
from src.schema import ANOMALY_TYPES, GROUND_TRUTH_TABLE, PAT, TABLES, Col, Table

RELATIONSHIPS = [
    ("Staff", "Course", "1:N", "mandatory", "lead instructor (courses.instructor_id)"),
    ("Course", "Staff", "N:M", "via CourseStaff", "who may grade the course, with effective dates"),
    ("Course", "Learner", "N:M", "via Enrollment", "bridge with effective_from (enrolled_at) / effective_to and status"),
    ("Course", "Assignment", "1:N", "mandatory", ""),
    ("Assignment", "Rubric", "1:N", "mandatory (>=1)", "rubric versions; exactly one effective at any instant; ids RUB-<asn>-01, -02"),
    ("Rubric", "RubricCriterion", "1:N", "mandatory (>=1)", "criteria sum to rubric total (100)"),
    ("Assignment", "Submission", "1:N", "optional", "one row per attempt"),
    ("Learner", "Submission", "1:N", "optional", "learner must hold an effective enrolment in the assignment's course"),
    ("Enrollment", "Submission", "1:N", "optional", "submissions.enrollment_id (NULL only for the injected unenrolled anomaly)"),
    ("Submission", "Submission", "1:0..1", "optional", "previous_submission_id links attempt n to n-1"),
    ("Submission", "SubmissionArtifact", "1:N", "optional", "0 rows for MISSING_FILE submissions"),
    ("Submission", "Grade", "1:0..1", "optional", "absent while grading is pending"),
    ("Rubric", "Grade", "1:N", "mandatory", "grade records the rubric version used"),
    ("Grade", "GradeCriterionScore", "1:N", "mandatory", "exactly one row per criterion of the grade's rubric"),
    ("RubricCriterion", "GradeCriterionScore", "1:N", "mandatory", ""),
    ("Grade", "GradeVersion", "1:N", "mandatory (>=1)", "append-only history; version 1 = initial grading"),
    ("Submission", "Feedback", "1:0..1", "optional", "present iff graded"),
    ("Submission", "Resubmission", "1:0..1", "optional", "request for the next attempt (original_submission_id)"),
    ("Resubmission", "Submission", "1:0..1", "optional", "new_submission_id (NULL if denied / expired / open)"),
    ("Grade", "Appeal", "1:0..1", "optional", "at most one appeal per grade"),
    ("Appeal", "GradeVersion", "1:0..1", "optional", "upheld appeal creates version 2 (APPEAL_ADJUSTMENT)"),
    ("Any audited entity", "AuditLog", "1:N", "optional", "polymorphic (entity_name, entity_id)"),
]

LIFECYCLES = {
    "Assignment": "(none) -> DRAFT -> PUBLISHED -> CLOSED   (CLOSED automatically at late_cutoff_utc)",
    "Rubric": "(none) -> ACTIVE -> SUPERSEDED   (a new version supersedes the previous one; its effective_from = old effective_to)",
    "Enrollment": "(none) -> ENROLLED | AUDIT ;  ENROLLED -> DROPPED | COMPLETED",
    "Submission": "(none) -> SUBMITTED -> GRADED ; GRADED -> RESUBMITTED (superseded by next attempt) ; "
                  "GRADED -> APPEALED -> GRADED (open appeal) ; SUBMITTED -> SUBMITTED (file check flag)",
    "Grade": "(none) -> PUBLISHED -> REVISED   (REVISED only through an upheld appeal; each state is a grade_versions row)",
    "Resubmission": "(none) -> REQUESTED -> APPROVED | DENIED ; APPROVED -> EXPIRED (never used by its deadline)",
    "Appeal": "(none) -> SUBMITTED -> IN_REVIEW -> UPHELD | REJECTED",
}

RULES = [
    ("Time zone", "Deadlines are authored as local wall-clock (`due_at_local`) and converted with DST rules "
                  "(US, EU, fixed offset) to `due_at_utc`; `utc_offset_minutes` records the offset in force."),
    ("Lateness", f"`is_late` iff submitted_at > applicable_deadline + grace; `late_days = CEIL(elapsed/24h)`. "
                 f"Attempt 1 is measured against the assignment due date; attempt >= 2 against the resubmission due date."),
    ("Acceptance", f"Attempt 1 accepted until due + {C.LATE_WINDOW_DAYS} days; resubmissions until due + {C.RESUB_LATE_CUTOFF_DAYS} days."),
    ("Late penalty", f"`late_penalty_points = MIN(raw, late_days x {C.LATE_PENALTY_PER_DAY})` - a single deduction."),
    ("Raw score", "`raw_score = SUM(criterion awarded_points)`; each criterion <= its max; raw <= rubric total (100)."),
    ("Final score", "`final_score = MAX(0, raw - late_penalty + adjustment)`; adjustment is non-zero only after an upheld appeal."),
    ("Rubric version", "A grade uses the rubric version effective at `graded_at_utc` (recorded in grades.rubric_id)."),
    ("Missing files", "MISSING_FILE (no artefact) and EMPTY_FILE (0-byte artefact) submissions are scored 0 and are always resubmission-eligible."),
    ("Resubmission", f"Allowed iff the assignment allows it, attempts < 1 + max_resubmissions, requested within "
                     f"{C.RESUB_REQUEST_WINDOW_DAYS} days of grade publication, and final score < {C.RESUB_SCORE_THRESHOLD:g} (or a file problem). "
                     f"Approved attempts are due {C.RESUB_DEADLINE_DAYS} days after approval. Denials carry a decision_reason."),
    ("Appeal", f"File within {C.APPEAL_WINDOW_DAYS} days of grade publication; decided by an academic administrator. "
               "UPHELD (a genuine scoring error was confirmed) creates grade version 2 plus a GRADE_MUTATE audit event; "
               "late appeals are REJECTED_OUT_OF_WINDOW."),
    ("Learner activity", "No submission, resubmission request or attempt after a DROPPED enrolment date or after a SUSPENDED/ALUMNI effective date."),
    ("Data cut-off", f"No event is later than {C.SNAPSHOT_AT:%Y-%m-%dT%H:%M:%SZ}; later steps are simply not yet generated (open appeals, pending grades, open resubmission windows)."),
    ("History", "Nothing is overwritten silently: grades are versioned, every state change is an audit event, rubrics are versioned."),
]

ANOMALY_DOC = {
    "UNENROLLED_LEARNER_SUBMISSION": "Submission from a learner with no effective enrolment in the course (required).",
    "GRADE_EXCEEDS_MAX": "A criterion score and raw_score above the rubric maximum (required).",
    "DOUBLE_LATE_PENALTY": "Late penalty deducted twice (required).",
    "APPEAL_NO_AUDIT_LOG": "Upheld appeal changed the grade with no grade_versions row and no GRADE_MUTATE audit event (required).",
    "RESUBMISSION_POLICY_VIOLATION": "Resubmission approved although the assignment disallows it (extra).",
    "APPEAL_OUTSIDE_WINDOW_UPHELD": "Appeal filed after the appeal window but upheld (extra).",
}


def _col_row(c: Col) -> str:
    typ = {"id": "VARCHAR(96)", "str": f"VARCHAR({c.n or 128})", "text": "TEXT", "int": "INTEGER", "float": "DECIMAL(2dp)",
           "bool": "BOOLEAN", "ts": "TIMESTAMP"}[c.typ]
    allowed = ", ".join(f"`{e}`" for e in c.enum) if c.enum else (f"`{PAT.get(c.pattern, c.pattern)}`" if c.pattern else "")
    if c.lo is not None or c.hi is not None:
        allowed += f" range [{'' if c.lo is None else c.lo}, {'' if c.hi is None else c.hi}]"
    uniq = "PRIMARY KEY" if False else ("UNIQUE" if c.unique else ("FOREIGN KEY -> " + c.fk if c.fk else "-"))
    rule = "; ".join(x for x in (c.rule, c.desc) if x) or "-"
    return f"| `{c.name}` | {typ} | {'required' if c.req else 'optional'} | {allowed or '-'} | {c.unit or '-'} | {uniq} | {rule} |"


def _table_md(i: int, t: Table) -> str:
    out = [f"### {i}. {t.entity} (`{t.name}`)", "", t.desc, "", f"* **Primary key**: `{t.pk}`",
           f"* **Cardinality**: {t.cardinality}"]
    if t.unique_keys:
        out.append("* **Composite unique keys**: " + ", ".join("(" + ", ".join(k) + ")" for k in t.unique_keys))
    out += ["", "| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for c in t.cols:
        row = _col_row(c)
        if c.name == t.pk:
            row = row.replace("| UNIQUE |", "| PRIMARY KEY |")
        out.append(row)
    return "\n".join(out) + "\n"


def render_data_dictionary() -> str:
    out = ["# AMS Data Dictionary", "",
           "_Generated from `src/schema.py` - do not edit by hand. Regenerate with `python build_docs.py`._", "",
           "## 1. Conventions", "",
           "* **Timestamps**: ISO-8601 UTC `YYYY-MM-DDTHH:MM:SSZ`. `due_at_local` is local wall-clock without offset (offset in `utc_offset_minutes`).",
           "* **Points**: 2-decimal numbers. **Booleans**: `true`/`false` in CSV. **NULL**: empty CSV cell / JSON `null` / SQL `NULL`.",
           f"* **Data cut-off**: `{C.SNAPSHOT_AT:%Y-%m-%dT%H:%M:%SZ}`. Nothing in the dataset is later than this instant.",
           "* **IDs** are deterministic, immutable and zero-padded; child ids embed the parent id (`GRD-<submission-id>`, ...).",
           "* **Ground truth** lives in its own folder (`ground_truth/`) and is never part of the input tables.", "",
           "## 2. Relationships and cardinality", "",
           "| Parent | Child | Cardinality | Optionality | Notes |", "| :--- | :--- | :--- | :--- | :--- |"]
    out += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in RELATIONSHIPS]
    out += ["", "## 3. ID conventions", "", "| Entity | Format | Example |", "| :--- | :--- | :--- |",
            "| Assignment | `ASN-YYYY-NNNNNN` | `ASN-2026-000001` |", "| Rubric | `RUB-<assignment-id>-VV` | `RUB-ASN-2026-000001-01` |",
            "| RubricCriterion | `CRT-<rubric-id>-NN` | `CRT-RUB-ASN-2026-000001-01-01` |",
            "| Submission | `SUB-<assignment-id>-<learner-id>-AA` | `SUB-ASN-2026-000001-LRN-000042-01` |",
            "| Artifact | `ART-<submission-id>-NN` | |", "| Grade | `GRD-<submission-id>` | `GRD-SUB-ASN-2026-000001-LRN-000042-01` |",
            "| GradeVersion | `GRV-<grade-id>-VV` | |", "| Feedback | `FDB-<submission-id>` | |",
            "| Appeal | `APP-YYYY-NNNNNN` | `APP-2026-000001` |", "| Resubmission | `RES-YYYY-NNNNNN` | |",
            "| Staff | `INS|ADM|SUP|PLT-NNNNNN` | `INS-000007` |", "| Course | `CRS-YYYY-NNNN` | |", "| Learner | `LRN-NNNNNN` | |",
            "| Enrollment | `ENR-NNNNNN` | |", "| AuditLog | `AUD-YYYY-NNNNNN` (sequential in time order) | |",
            "| GroundTruth | `GT-YYYY-NNNNNN` | |", "",
            "## 4. Lifecycle state machines", ""]
    out += [f"* **{k}**: {v}" for k, v in LIFECYCLES.items()]
    out += ["", "## 5. Business rules and derived values", ""]
    out += [f"* **{k}**: {v}" for k, v in RULES]
    out += ["", "## 6. Table specifications", ""]
    for i, t in enumerate(TABLES, start=1):
        out.append(_table_md(i, t))
    out += ["## 7. Ground truth (separate artefact)", "",
            "Injected anomaly types (`label_class = ANOMALY`):", ""]
    out += [f"* `{k}` - {ANOMALY_DOC[k]}" for k in ANOMALY_TYPES]
    out += ["", "Other label classes: `EXCEPTION_PATH` (valid but unusual outcomes such as missing files, denied/expired "
                "resubmissions, out-of-window appeals) and `BOUNDARY_VALID` (valid deadline-boundary submissions). "
                "These exist to measure false positives.", "",
            _table_md(len(TABLES) + 1, GROUND_TRUTH_TABLE)]
    return "\n".join(out)
