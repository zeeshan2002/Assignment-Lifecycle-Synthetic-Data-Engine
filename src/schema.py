"""
Single source of truth for the relational model.

The SQL DDL, the data dictionary, CSV/JSON typing and the validator's generic checks
(required / enum / pattern / range / foreign key) are all derived from the definitions below.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any

# ---- enumerations ----------------------------------------------------------------------------
STAFF_ROLES = ("INSTRUCTOR", "ACADEMIC_ADMIN", "SUPPORT_STAFF", "PLATFORM_ADMIN")
STAFF_STATUS = ("ACTIVE", "INACTIVE")
TERMS = ("SPRING-2026", "SUMMER-2026", "FALL-2026")
DEPARTMENTS = ("Computer Science", "Data Science", "Mathematics", "Engineering", "Business")
COURSE_ROLES = ("LEAD_INSTRUCTOR", "GRADER")
LEARNER_STATUS = ("ACTIVE", "SUSPENDED", "ALUMNI")
ENROLLMENT_STATUS = ("ENROLLED", "COMPLETED", "DROPPED", "AUDIT")
TIMEZONES = tuple(["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Asia/Kolkata"])
ASSIGNMENT_STATUS = ("DRAFT", "PUBLISHED", "CLOSED")
RUBRIC_STATUS = ("ACTIVE", "SUPERSEDED")
FILE_CHECK_STATUS = ("COMPLETE", "MISSING_FILE", "EMPTY_FILE")
FILE_TYPES = ("pdf", "zip", "py", "docx")
SUBMISSION_STATUS = ("SUBMITTED", "GRADED", "RESUBMITTED", "APPEALED")
GRADE_STATUS = ("PUBLISHED", "REVISED")
GRADE_CHANGE_TYPES = ("INITIAL", "APPEAL_ADJUSTMENT")
RESUB_STATUS = ("REQUESTED", "APPROVED", "DENIED", "EXPIRED")
RESUB_DECISIONS = ("APPROVED_SCORE_BELOW_THRESHOLD", "APPROVED_MISSING_FILE",
                   "DENIED_OUTSIDE_WINDOW", "DENIED_SCORE_ABOVE_THRESHOLD")
APPEAL_STATUS = ("SUBMITTED", "IN_REVIEW", "UPHELD", "REJECTED")
APPEAL_REASONS = ("GRADING_ERROR", "RUBRIC_MISAPPLIED", "LATE_PENALTY_ERROR", "MISSING_FILE_DISPUTE", "OTHER")
APPEAL_DECISIONS = ("UPHELD_GRADING_ERROR", "REJECTED_NO_ERROR", "REJECTED_OUT_OF_WINDOW")
ACTOR_ROLES = ("LEARNER", "INSTRUCTOR", "ACADEMIC_ADMIN", "SUPPORT_STAFF", "PLATFORM_ADMIN", "SYSTEM")
AUDIT_ENTITIES = ("Course", "Assignment", "Rubric", "Enrollment", "Submission", "Grade", "Resubmission", "Appeal")
AUDIT_ACTIONS = (
    "COURSE_CREATE", "ASSIGNMENT_CREATE", "ASSIGNMENT_PUBLISH", "ASSIGNMENT_CLOSE",
    "RUBRIC_CREATE", "RUBRIC_SUPERSEDE", "ENROLL", "ENROLLMENT_END",
    "SUBMISSION_CREATE", "FILE_FLAG", "SUBMISSION_GRADED", "SUBMISSION_SUPERSEDED",
    "GRADE_PUBLISH", "GRADE_MUTATE",
    "RESUBMISSION_REQUEST", "RESUBMISSION_DECIDE", "RESUBMISSION_EXPIRE",
    "APPEAL_FILE", "APPEAL_INTAKE", "APPEAL_REVIEW_START", "APPEAL_RESOLVE",
    "SUBMISSION_APPEALED", "SUBMISSION_APPEAL_CLOSED",
)
LABEL_CLASSES = ("ANOMALY", "EXCEPTION_PATH", "BOUNDARY_VALID")
ANOMALY_TYPES = (
    "UNENROLLED_LEARNER_SUBMISSION", "GRADE_EXCEEDS_MAX", "DOUBLE_LATE_PENALTY", "APPEAL_NO_AUDIT_LOG",
    "RESUBMISSION_POLICY_VIOLATION", "APPEAL_OUTSIDE_WINDOW_UPHELD",
)

# ---- ID / format patterns --------------------------------------------------------------------
_SUB = r"SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}"
PAT = {
    "staff": r"^(INS|ADM|SUP|PLT)-\d{6}$",
    "course": r"^CRS-\d{4}-\d{4}$",
    "csf": r"^CSF-\d{6}$",
    "learner": r"^LRN-\d{6}$",
    "enr": r"^ENR-\d{6}$",
    "asn": r"^ASN-\d{4}-\d{6}$",
    "rub": r"^RUB-ASN-\d{4}-\d{6}-\d{2}$",
    "crt": r"^CRT-RUB-ASN-\d{4}-\d{6}-\d{2}-\d{2}$",
    "sub": rf"^{_SUB}$",
    "art": rf"^ART-{_SUB}-\d{{2}}$",
    "grd": rf"^GRD-{_SUB}$",
    "grv": rf"^GRV-GRD-{_SUB}-\d{{2}}$",
    "scr": rf"^SCR-GRD-{_SUB}-\d{{2}}$",
    "fdb": rf"^FDB-{_SUB}$",
    "res": r"^RES-\d{4}-\d{6}$",
    "app": r"^APP-\d{4}-\d{6}$",
    "aud": r"^AUD-\d{4}-\d{6}$",
    "gt": r"^GT-\d{4}-\d{6}$",
    "ts": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
    "ts_local": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$",
    "email": r"^[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}$",
    "sha256": r"^[0-9a-f]{64}$",
}


@dataclass
class Col:
    name: str
    typ: str                       # id | str | text | int | float | bool | ts
    req: bool = True
    enum: Optional[Tuple[str, ...]] = None
    unit: str = ""
    unique: bool = False
    pattern: Optional[str] = None  # key into PAT (or raw regex)
    fk: Optional[str] = None       # "table.column"
    lo: Optional[float] = None
    hi: Optional[float] = None
    rule: str = ""
    desc: str = ""
    n: Optional[int] = None        # VARCHAR length for 'str'


@dataclass
class Table:
    name: str
    entity: str
    desc: str
    pk: str
    cols: List[Col]
    unique_keys: List[Tuple[str, ...]] = field(default_factory=list)
    cardinality: str = ""

    def col(self, name: str) -> Col:
        return next(c for c in self.cols if c.name == name)

    @property
    def col_names(self) -> List[str]:
        return [c.name for c in self.cols]


def C(name, typ, req=True, **kw) -> Col:
    return Col(name, typ, req, **kw)


def ID(name, pat, req=True, fk=None, unique=False, desc="", rule=""):
    return Col(name, "id", req, pattern=pat, fk=fk, unique=unique, desc=desc, rule=rule)


def TS(name, req=True, desc="", rule=""):
    return Col(name, "ts", req, pattern="ts", unit="ISO-8601 UTC", desc=desc, rule=rule)


TABLES: List[Table] = [
    Table("staff", "Staff", "Instructors, academic administrators, support staff and platform administrators.", "staff_id", [
        ID("staff_id", "staff", unique=True, desc="Role-prefixed id: INS/ADM/SUP/PLT."),
        C("full_name", "str", n=96), C("email", "str", unique=True, pattern="email", n=128),
        C("role", "str", enum=STAFF_ROLES, n=24, desc="Actor role."),
        C("department", "str", req=False, enum=DEPARTMENTS, n=64, desc="Instructors only."),
        C("status", "str", enum=STAFF_STATUS, n=16, rule="INACTIVE staff are never referenced by any record."),
        TS("hired_at_utc"),
    ], cardinality="1:N with Course (lead instructor), Grade (grader), Appeal (reviewer/intake); N:M with Course via course_staff"),

    Table("courses", "Course", "Course offering in one academic term.", "course_id", [
        ID("course_id", "course", unique=True),
        C("course_code", "str", n=24, unique=True), C("title", "str", n=128),
        C("department", "str", enum=DEPARTMENTS, n=64), C("term", "str", enum=TERMS, n=16),
        ID("instructor_id", "staff", fk="staff.staff_id", desc="Lead instructor."),
        ID("created_by", "staff", fk="staff.staff_id", desc="Platform administrator who created the course."),
        TS("created_at_utc"), TS("start_date_utc"), TS("end_date_utc"),
    ], cardinality="1:N Assignment, 1:N Enrollment, N:M Staff (course_staff)"),

    Table("course_staff", "CourseStaff", "Bridge: staff authorised to grade a course (N:M Course-Staff) with effective dates.", "course_staff_id", [
        ID("course_staff_id", "csf", unique=True),
        ID("course_id", "course", fk="courses.course_id"), ID("staff_id", "staff", fk="staff.staff_id"),
        C("course_role", "str", enum=COURSE_ROLES, n=24),
        TS("effective_from_utc"), TS("effective_to_utc", req=False, desc="NULL = open-ended."),
    ], unique_keys=[("course_id", "staff_id")], cardinality="N:M bridge"),

    Table("learners", "Learner", "Student registered with the institution.", "learner_id", [
        ID("learner_id", "learner", unique=True),
        C("first_name", "str", n=64), C("last_name", "str", n=64),
        C("email", "str", unique=True, pattern="email", n=128),
        TS("registration_date_utc", rule="<= every enrollment of the learner."),
        C("status", "str", enum=LEARNER_STATUS, n=16),
        TS("status_effective_from_utc", req=False, rule="Required iff status != ACTIVE; no submission after this instant."),
    ], cardinality="1:N Enrollment, 1:N Submission"),

    Table("enrollments", "Enrollment", "Bridge: learner enrolled in a course (N:M Learner-Course), with effective dates and status.", "enrollment_id", [
        ID("enrollment_id", "enr", unique=True),
        ID("course_id", "course", fk="courses.course_id"), ID("learner_id", "learner", fk="learners.learner_id"),
        TS("enrolled_at_utc", desc="Effective-from of the enrolment."),
        TS("effective_to_utc", req=False, desc="Effective-to (drop / completion instant); NULL while open."),
        C("enrollment_status", "str", enum=ENROLLMENT_STATUS, n=16),
        ID("processed_by", "staff", fk="staff.staff_id", desc="Support staff who processed the enrolment."),
    ], unique_keys=[("course_id", "learner_id")], cardinality="N:M bridge"),

    Table("assignments", "Assignment", "Published (or draft) coursework with deadline and policy parameters.", "assignment_id", [
        ID("assignment_id", "asn", unique=True),
        ID("course_id", "course", fk="courses.course_id"),
        C("title", "str", n=160), C("description", "text"),
        ID("created_by", "staff", fk="staff.staff_id"), TS("created_at_utc"),
        TS("published_at_utc", req=False, desc="NULL while DRAFT."),
        TS("due_at_utc", rule="== due_at_local converted with `timezone` rules."),
        C("due_at_local", "str", pattern="ts_local", unit="ISO-8601 local wall-clock", n=19),
        C("timezone", "str", enum=TIMEZONES, n=32),
        C("utc_offset_minutes", "int", unit="minutes", rule="Offset in force at due_at_utc (DST aware)."),
        C("grace_period_minutes", "int", unit="minutes", lo=0, hi=120, rule="Submission is late only if later than due + grace."),
        C("late_penalty_per_day", "float", unit="points/day", lo=0),
        TS("late_cutoff_utc", rule="== due_at_utc + 5 days; later submissions are not accepted."),
        C("max_score", "float", unit="points", lo=0),
        C("allow_resubmission", "bool"),
        C("max_resubmissions", "int", unit="count", lo=0, hi=2, rule="0 iff allow_resubmission is false."),
        C("resubmission_window_days", "int", unit="days", lo=0), C("appeal_window_days", "int", unit="days", lo=0),
        C("status", "str", enum=ASSIGNMENT_STATUS, n=16,
          rule="DRAFT iff published_at_utc is NULL; CLOSED iff late_cutoff_utc <= data cut-off."),
    ], cardinality="1:N Rubric (versions), 1:N Submission"),

    Table("rubrics", "Rubric", "Versioned scoring guide of an assignment; exactly one version is effective at any instant.", "rubric_id", [
        ID("rubric_id", "rub", unique=True),
        ID("assignment_id", "asn", fk="assignments.assignment_id"),
        C("version_no", "int", lo=1), C("title", "str", n=200),
        C("total_points", "float", unit="points", lo=0, rule="== SUM(criteria.max_points)."),
        TS("effective_from_utc"), TS("effective_to_utc", req=False, desc="Set when superseded by the next version."),
        C("status", "str", enum=RUBRIC_STATUS, n=16),
        ID("created_by", "staff", fk="staff.staff_id"), TS("created_at_utc"),
    ], unique_keys=[("assignment_id", "version_no")], cardinality="N:1 Assignment, 1:N RubricCriterion, 1:N Grade"),

    Table("rubric_criteria", "RubricCriterion", "One scored dimension of a rubric.", "criterion_id", [
        ID("criterion_id", "crt", unique=True), ID("rubric_id", "rub", fk="rubrics.rubric_id"),
        C("sequence_no", "int", lo=1), C("criterion_name", "str", n=96), C("description", "text"),
        C("max_points", "float", unit="points", lo=0.0001),
        C("weight_pct", "float", unit="%", lo=0, hi=100, rule="Weights of a rubric sum to 100."),
    ], unique_keys=[("rubric_id", "sequence_no")], cardinality="N:1 Rubric, 1:N GradeCriterionScore"),

    Table("submissions", "Submission", "One attempt by a learner at an assignment (attempt 1 = first submission).", "submission_id", [
        ID("submission_id", "sub", unique=True, rule="== SUB-<assignment_id>-<learner_id>-<attempt:02d>."),
        ID("assignment_id", "asn", fk="assignments.assignment_id"), ID("learner_id", "learner", fk="learners.learner_id"),
        ID("enrollment_id", "enr", req=False, fk="enrollments.enrollment_id", desc="Enrolment under which the work was submitted."),
        C("attempt_number", "int", lo=1, hi=3),
        ID("previous_submission_id", "sub", req=False, fk="submissions.submission_id", desc="Prior attempt (NULL for attempt 1)."),
        TS("submitted_at_utc"),
        TS("applicable_deadline_utc", desc="Assignment due date (attempt 1) or resubmission due date (attempt >= 2)."),
        C("is_late", "bool", rule="submitted_at_utc > applicable_deadline_utc + grace."),
        C("late_days", "int", unit="days", lo=0, rule="CEIL((submitted - deadline)/24h) if late else 0."),
        C("expected_file_count", "int", lo=1, hi=2),
        C("file_check_status", "str", enum=FILE_CHECK_STATUS, n=16,
          rule="MISSING_FILE: no artefact rows; EMPTY_FILE: an artefact of 0 bytes; COMPLETE otherwise."),
        C("status", "str", enum=SUBMISSION_STATUS, n=16),
    ], unique_keys=[("assignment_id", "learner_id", "attempt_number")],
        cardinality="N:1 Assignment, N:1 Learner, 1:N SubmissionArtifact, 0..1:1 Grade, 0..1:1 Feedback"),

    Table("submission_artifacts", "SubmissionArtifact", "File metadata attached to a submission.", "artifact_id", [
        ID("artifact_id", "art", unique=True), ID("submission_id", "sub", fk="submissions.submission_id"),
        C("sequence_no", "int", lo=1), C("file_name", "str", n=128),
        C("file_size_bytes", "int", unit="bytes", lo=0, rule="0 only for EMPTY_FILE submissions."),
        C("file_type", "str", enum=FILE_TYPES, n=8),
        C("storage_uri", "str", unique=True, n=255),
        C("checksum_sha256", "str", pattern="sha256", n=64, rule="SHA-256 of the empty string iff size is 0."),
        TS("uploaded_at_utc", rule="<= submission.submitted_at_utc."),
    ], unique_keys=[("submission_id", "sequence_no")], cardinality="N:1 Submission"),

    Table("grades", "Grade", "Current grade of a submission; every change is retained in grade_versions.", "grade_id", [
        ID("grade_id", "grd", unique=True, rule="== GRD-<submission_id>."),
        ID("submission_id", "sub", unique=True, fk="submissions.submission_id"),
        ID("rubric_id", "rub", fk="rubrics.rubric_id", desc="Rubric version effective at graded_at_utc."),
        ID("grader_id", "staff", fk="staff.staff_id", desc="Must be course staff (course_staff)."),
        C("raw_score", "float", unit="points", lo=0, rule="== SUM(grade_criterion_scores.awarded_points); must be <= rubric total."),
        C("late_penalty_points", "float", unit="points", lo=0, rule="== MIN(raw, late_days x late_penalty_per_day)."),
        C("adjustment_points", "float", unit="points", lo=0, rule="Appeal adjustment; 0 unless REVISED."),
        C("final_score", "float", unit="points", lo=0, rule="== MAX(0, raw - late_penalty + adjustment)."),
        TS("graded_at_utc"), C("grade_status", "str", enum=GRADE_STATUS, n=16, rule="REVISED iff current_version > 1."),
        C("current_version", "int", lo=1),
    ], cardinality="1:1 Submission, 1:N GradeVersion, 1:N GradeCriterionScore, 0..1:1 Appeal"),

    Table("appeals", "Appeal", "Formal learner appeal against a grade, reviewed by an academic administrator.", "appeal_id", [
        ID("appeal_id", "app", unique=True),
        ID("submission_id", "sub", fk="submissions.submission_id"),
        ID("grade_id", "grd", unique=True, fk="grades.grade_id", desc="At most one appeal per grade."),
        ID("learner_id", "learner", fk="learners.learner_id"),
        C("reason_code", "str", enum=APPEAL_REASONS, n=24), C("reason", "text"),
        TS("filed_at_utc"), ID("intake_by", "staff", fk="staff.staff_id", desc="Support staff who registered the appeal."),
        C("status", "str", enum=APPEAL_STATUS, n=16),
        C("original_score", "float", unit="points", lo=0, rule="== grade final_score before the appeal."),
        C("adjusted_score", "float", req=False, unit="points", lo=0, rule="NULL while open; == original for REJECTED."),
        ID("reviewed_by", "staff", req=False, fk="staff.staff_id", desc="Academic administrator."),
        TS("review_started_at_utc", req=False), TS("decided_at_utc", req=False),
        C("decision_code", "str", req=False, enum=APPEAL_DECISIONS, n=32),
        C("resolution_notes", "text", req=False),
    ], cardinality="N:1 Grade (max 1 per grade), N:1 Submission, N:1 Learner, 0..N GradeVersion"),

    Table("grade_versions", "GradeVersion", "Append-only history of every grade state (version 1 = initial grading).", "grade_version_id", [
        ID("grade_version_id", "grv", unique=True), ID("grade_id", "grd", fk="grades.grade_id"),
        C("version_no", "int", lo=1), C("raw_score", "float", unit="points", lo=0),
        C("late_penalty_points", "float", unit="points", lo=0), C("adjustment_points", "float", unit="points", lo=0),
        C("final_score", "float", unit="points", lo=0),
        C("change_type", "str", enum=GRADE_CHANGE_TYPES, n=24),
        ID("changed_by", "staff", fk="staff.staff_id"), TS("changed_at_utc"),
        ID("appeal_id", "app", req=False, fk="appeals.appeal_id", desc="Set for APPEAL_ADJUSTMENT versions."),
    ], unique_keys=[("grade_id", "version_no")], cardinality="N:1 Grade, 0..1:1 Appeal"),

    Table("grade_criterion_scores", "GradeCriterionScore", "Rubric-based score for one criterion of a grade.", "score_id", [
        ID("score_id", "scr", unique=True), ID("grade_id", "grd", fk="grades.grade_id"),
        ID("criterion_id", "crt", fk="rubric_criteria.criterion_id", desc="Must belong to the grade's rubric."),
        C("awarded_points", "float", unit="points", lo=0, rule="<= criterion.max_points."),
        C("criterion_comment", "text", req=False),
    ], unique_keys=[("grade_id", "criterion_id")], cardinality="N:1 Grade, N:1 RubricCriterion"),

    Table("feedback", "Feedback", "Qualitative instructor feedback attached to a graded submission.", "feedback_id", [
        ID("feedback_id", "fdb", unique=True), ID("submission_id", "sub", unique=True, fk="submissions.submission_id"),
        ID("instructor_id", "staff", fk="staff.staff_id"),
        C("qualitative_comment", "text"), C("strengths", "text"), C("growth_areas", "text"),
        TS("provided_at_utc", rule="== grade.graded_at_utc."),
    ], cardinality="1:1 Submission"),

    Table("resubmissions", "Resubmission", "Request for another attempt, its decision and outcome (links attempt n to n+1).", "resubmission_id", [
        ID("resubmission_id", "res", unique=True),
        ID("original_submission_id", "sub", unique=True, fk="submissions.submission_id"),
        ID("new_submission_id", "sub", req=False, unique=True, fk="submissions.submission_id", desc="NULL if denied, expired or still open."),
        TS("requested_at_utc"), C("request_reason", "text"),
        C("status", "str", enum=RESUB_STATUS, n=16),
        C("decision_reason", "str", req=False, enum=RESUB_DECISIONS, n=40),
        ID("decided_by", "staff", req=False, fk="staff.staff_id"), TS("decided_at_utc", req=False),
        TS("resubmission_due_utc", req=False, desc="Set when approved."), TS("resubmitted_at_utc", req=False),
        C("policy_compliant", "bool", desc="Request satisfied the resubmission policy at decision time."),
    ], cardinality="1:1 original Submission, 0..1:1 new Submission"),

    Table("audit_logs", "AuditLog", "Append-only event history of every lifecycle state change.", "audit_id", [
        ID("audit_id", "aud", unique=True, rule="Sequential in (timestamp, event order)."),
        C("entity_name", "str", enum=AUDIT_ENTITIES, n=24), C("entity_id", "str", n=96, desc="PK of the entity (polymorphic)."),
        C("action_type", "str", enum=AUDIT_ACTIONS, n=32),
        C("actor_id", "str", n=24, desc="Learner id, staff id, or SYSTEM."),
        C("actor_role", "str", enum=ACTOR_ROLES, n=24),
        C("from_status", "str", req=False, n=24), C("to_status", "str", req=False, n=24),
        C("previous_state", "text", req=False, desc="JSON before the change."), C("new_state", "text", desc="JSON after the change."),
        TS("timestamp_utc"),
    ], cardinality="Polymorphic N:1 to the audited entity"),
]

TABLE_BY_NAME: Dict[str, Table] = {t.name: t for t in TABLES}

# Kept out of the input data on purpose: lives in its own folder / file.
GROUND_TRUTH_TABLE = Table("ground_truth", "GroundTruth",
    "Labels for injected anomalies, valid exception paths and valid boundary cases. NEVER an input feature.",
    "ground_truth_id", [
        ID("ground_truth_id", "gt", unique=True),
        C("label_class", "str", enum=LABEL_CLASSES, n=16),
        C("issue_type", "str", n=64, desc="Anomaly type (ANOMALY) or exception/boundary kind."),
        C("entity_name", "str", n=24),
        C("record_id", "str", n=96, desc="PK of the labelled record (heterogeneous: any table)."),
        C("field_name", "str", n=48), C("expected_value", "text"), C("actual_value", "text"),
        C("expected_decision", "text", desc="What a correct system should decide for this record."),
        C("description", "text"),
    ], cardinality="Separate artefact")

# ---- (de)serialisation -----------------------------------------------------------------------

def _cast(col: Col, raw: str) -> Any:
    if raw == "" or raw is None:
        return None
    if col.typ == "int":
        return int(raw)
    if col.typ == "float":
        return float(raw)
    if col.typ == "bool":
        return raw.strip().lower() == "true"
    return raw


def cast_row(table: Table, row: Dict[str, str]) -> Dict[str, Any]:
    return {c.name: _cast(c, row.get(c.name)) for c in table.cols}


def csv_value(col: Col, v: Any) -> str:
    if v is None:
        return ""
    if col.typ == "bool":
        return "true" if v else "false"
    if col.typ == "float":
        return f"{v:.2f}"
    return str(v)


# ---- SQL DDL ---------------------------------------------------------------------------------
_SQL_TYPE = {"id": "VARCHAR(96)", "text": "TEXT", "int": "INTEGER", "float": "FLOAT", "bool": "BOOLEAN", "ts": "TIMESTAMP"}


def sql_type(c: Col) -> str:
    return f"VARCHAR({c.n or 128})" if c.typ == "str" else _SQL_TYPE[c.typ]


def ddl(tables: List[Table] = None) -> str:
    out = ["-- AMS assignment lifecycle schema (ANSI SQL, generated from src/schema.py)",
           "-- CHECK constraints cover enums and non-negativity only. Injected anomalies are schema-valid by",
           "-- design (e.g. a grade above the rubric maximum still loads); they are caught by the validator.", ""]
    for t in (tables or TABLES):
        lines = []
        for c in t.cols:
            parts = [c.name, sql_type(c)]
            if c.name == t.pk:
                parts.append("PRIMARY KEY")
            elif c.unique:
                parts.append("UNIQUE")
            if c.req and c.name != t.pk:
                parts.append("NOT NULL")
            if c.enum:
                vals = ", ".join(f"'{e}'" for e in c.enum)
                parts.append(f"CHECK ({c.name} IN ({vals}))" if c.req else f"CHECK ({c.name} IS NULL OR {c.name} IN ({vals}))")
            if c.lo is not None and c.typ in ("int", "float"):
                parts.append(f"CHECK ({c.name} IS NULL OR {c.name} >= {c.lo})" if not c.req else f"CHECK ({c.name} >= {c.lo})")
            lines.append("    " + " ".join(parts))
        for c in t.cols:
            if c.fk:
                ft, fc = c.fk.split(".")
                lines.append(f"    FOREIGN KEY ({c.name}) REFERENCES {ft}({fc})")
        for uk in t.unique_keys:
            lines.append(f"    UNIQUE ({', '.join(uk)})")
        out.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(lines) + "\n);\n")
    return "\n".join(out)
