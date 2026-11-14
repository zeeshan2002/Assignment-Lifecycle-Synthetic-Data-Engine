# AMS Data Dictionary

_Generated from `src/schema.py` - do not edit by hand. Regenerate with `python build_docs.py`._

## 1. Conventions

* **Timestamps**: ISO-8601 UTC `YYYY-MM-DDTHH:MM:SSZ`. `due_at_local` is local wall-clock without offset (offset in `utc_offset_minutes`).
* **Points**: 2-decimal numbers. **Booleans**: `true`/`false` in CSV. **NULL**: empty CSV cell / JSON `null` / SQL `NULL`.
* **Data cut-off**: `2026-11-13T00:00:00Z`. Nothing in the dataset is later than this instant.
* **IDs** are deterministic, immutable and zero-padded; child ids embed the parent id (`GRD-<submission-id>`, ...).
* **Ground truth** lives in its own folder (`ground_truth/`) and is never part of the input tables.

## 2. Relationships and cardinality

| Parent | Child | Cardinality | Optionality | Notes |
| :--- | :--- | :--- | :--- | :--- |
| Staff | Course | 1:N | mandatory | lead instructor (courses.instructor_id) |
| Course | Staff | N:M | via CourseStaff | who may grade the course, with effective dates |
| Course | Learner | N:M | via Enrollment | bridge with effective_from (enrolled_at) / effective_to and status |
| Course | Assignment | 1:N | mandatory |  |
| Assignment | Rubric | 1:N | mandatory (>=1) | rubric versions; exactly one effective at any instant; ids RUB-<asn>-01, -02 |
| Rubric | RubricCriterion | 1:N | mandatory (>=1) | criteria sum to rubric total (100) |
| Assignment | Submission | 1:N | optional | one row per attempt |
| Learner | Submission | 1:N | optional | learner must hold an effective enrolment in the assignment's course |
| Enrollment | Submission | 1:N | optional | submissions.enrollment_id (NULL only for the injected unenrolled anomaly) |
| Submission | Submission | 1:0..1 | optional | previous_submission_id links attempt n to n-1 |
| Submission | SubmissionArtifact | 1:N | optional | 0 rows for MISSING_FILE submissions |
| Submission | Grade | 1:0..1 | optional | absent while grading is pending |
| Rubric | Grade | 1:N | mandatory | grade records the rubric version used |
| Grade | GradeCriterionScore | 1:N | mandatory | exactly one row per criterion of the grade's rubric |
| RubricCriterion | GradeCriterionScore | 1:N | mandatory |  |
| Grade | GradeVersion | 1:N | mandatory (>=1) | append-only history; version 1 = initial grading |
| Submission | Feedback | 1:0..1 | optional | present iff graded |
| Submission | Resubmission | 1:0..1 | optional | request for the next attempt (original_submission_id) |
| Resubmission | Submission | 1:0..1 | optional | new_submission_id (NULL if denied / expired / open) |
| Grade | Appeal | 1:0..1 | optional | at most one appeal per grade |
| Appeal | GradeVersion | 1:0..1 | optional | upheld appeal creates version 2 (APPEAL_ADJUSTMENT) |
| Any audited entity | AuditLog | 1:N | optional | polymorphic (entity_name, entity_id) |

## 3. ID conventions

| Entity | Format | Example |
| :--- | :--- | :--- |
| Assignment | `ASN-YYYY-NNNNNN` | `ASN-2026-000001` |
| Rubric | `RUB-<assignment-id>-VV` | `RUB-ASN-2026-000001-01` |
| RubricCriterion | `CRT-<rubric-id>-NN` | `CRT-RUB-ASN-2026-000001-01-01` |
| Submission | `SUB-<assignment-id>-<learner-id>-AA` | `SUB-ASN-2026-000001-LRN-000042-01` |
| Artifact | `ART-<submission-id>-NN` | |
| Grade | `GRD-<submission-id>` | `GRD-SUB-ASN-2026-000001-LRN-000042-01` |
| GradeVersion | `GRV-<grade-id>-VV` | |
| Feedback | `FDB-<submission-id>` | |
| Appeal | `APP-YYYY-NNNNNN` | `APP-2026-000001` |
| Resubmission | `RES-YYYY-NNNNNN` | |
| Staff | `INS|ADM|SUP|PLT-NNNNNN` | `INS-000007` |
| Course | `CRS-YYYY-NNNN` | |
| Learner | `LRN-NNNNNN` | |
| Enrollment | `ENR-NNNNNN` | |
| AuditLog | `AUD-YYYY-NNNNNN` (sequential in time order) | |
| GroundTruth | `GT-YYYY-NNNNNN` | |

## 4. Lifecycle state machines

* **Assignment**: (none) -> DRAFT -> PUBLISHED -> CLOSED   (CLOSED automatically at late_cutoff_utc)
* **Rubric**: (none) -> ACTIVE -> SUPERSEDED   (a new version supersedes the previous one; its effective_from = old effective_to)
* **Enrollment**: (none) -> ENROLLED | AUDIT ;  ENROLLED -> DROPPED | COMPLETED
* **Submission**: (none) -> SUBMITTED -> GRADED ; GRADED -> RESUBMITTED (superseded by next attempt) ; GRADED -> APPEALED -> GRADED (open appeal) ; SUBMITTED -> SUBMITTED (file check flag)
* **Grade**: (none) -> PUBLISHED -> REVISED   (REVISED only through an upheld appeal; each state is a grade_versions row)
* **Resubmission**: (none) -> REQUESTED -> APPROVED | DENIED ; APPROVED -> EXPIRED (never used by its deadline)
* **Appeal**: (none) -> SUBMITTED -> IN_REVIEW -> UPHELD | REJECTED

## 5. Business rules and derived values

* **Time zone**: Deadlines are authored as local wall-clock (`due_at_local`) and converted with DST rules (US, EU, fixed offset) to `due_at_utc`; `utc_offset_minutes` records the offset in force.
* **Lateness**: `is_late` iff submitted_at > applicable_deadline + grace; `late_days = CEIL(elapsed/24h)`. Attempt 1 is measured against the assignment due date; attempt >= 2 against the resubmission due date.
* **Acceptance**: Attempt 1 accepted until due + 5 days; resubmissions until due + 2 days.
* **Late penalty**: `late_penalty_points = MIN(raw, late_days x 5.0)` - a single deduction.
* **Raw score**: `raw_score = SUM(criterion awarded_points)`; each criterion <= its max; raw <= rubric total (100).
* **Final score**: `final_score = MAX(0, raw - late_penalty + adjustment)`; adjustment is non-zero only after an upheld appeal.
* **Rubric version**: A grade uses the rubric version effective at `graded_at_utc` (recorded in grades.rubric_id).
* **Missing files**: MISSING_FILE (no artefact) and EMPTY_FILE (0-byte artefact) submissions are scored 0 and are always resubmission-eligible.
* **Resubmission**: Allowed iff the assignment allows it, attempts < 1 + max_resubmissions, requested within 5 days of grade publication, and final score < 70 (or a file problem). Approved attempts are due 7 days after approval. Denials carry a decision_reason.
* **Appeal**: File within 7 days of grade publication; decided by an academic administrator. UPHELD (a genuine scoring error was confirmed) creates grade version 2 plus a GRADE_MUTATE audit event; late appeals are REJECTED_OUT_OF_WINDOW.
* **Learner activity**: No submission, resubmission request or attempt after a DROPPED enrolment date or after a SUSPENDED/ALUMNI effective date.
* **Data cut-off**: No event is later than 2026-11-13T00:00:00Z; later steps are simply not yet generated (open appeals, pending grades, open resubmission windows).
* **History**: Nothing is overwritten silently: grades are versioned, every state change is an audit event, rubrics are versioned.

## 6. Table specifications

### 1. Staff (`staff`)

Instructors, academic administrators, support staff and platform administrators.

* **Primary key**: `staff_id`
* **Cardinality**: 1:N with Course (lead instructor), Grade (grader), Appeal (reviewer/intake); N:M with Course via course_staff

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `staff_id` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | PRIMARY KEY | Role-prefixed id: INS/ADM/SUP/PLT. |
| `full_name` | VARCHAR(96) | required | - | - | - | - |
| `email` | VARCHAR(128) | required | `^[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}$` | - | UNIQUE | - |
| `role` | VARCHAR(24) | required | `INSTRUCTOR`, `ACADEMIC_ADMIN`, `SUPPORT_STAFF`, `PLATFORM_ADMIN` | - | - | Actor role. |
| `department` | VARCHAR(64) | optional | `Computer Science`, `Data Science`, `Mathematics`, `Engineering`, `Business` | - | - | Instructors only. |
| `status` | VARCHAR(16) | required | `ACTIVE`, `INACTIVE` | - | - | INACTIVE staff are never referenced by any record. |
| `hired_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |

### 2. Course (`courses`)

Course offering in one academic term.

* **Primary key**: `course_id`
* **Cardinality**: 1:N Assignment, 1:N Enrollment, N:M Staff (course_staff)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `course_id` | VARCHAR(96) | required | `^CRS-\d{4}-\d{4}$` | - | PRIMARY KEY | - |
| `course_code` | VARCHAR(24) | required | - | - | UNIQUE | - |
| `title` | VARCHAR(128) | required | - | - | - | - |
| `department` | VARCHAR(64) | required | `Computer Science`, `Data Science`, `Mathematics`, `Engineering`, `Business` | - | - | - |
| `term` | VARCHAR(16) | required | `SPRING-2026`, `SUMMER-2026`, `FALL-2026` | - | - | - |
| `instructor_id` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | Lead instructor. |
| `created_by` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | Platform administrator who created the course. |
| `created_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `start_date_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `end_date_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |

### 3. CourseStaff (`course_staff`)

Bridge: staff authorised to grade a course (N:M Course-Staff) with effective dates.

* **Primary key**: `course_staff_id`
* **Cardinality**: N:M bridge
* **Composite unique keys**: (course_id, staff_id)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `course_staff_id` | VARCHAR(96) | required | `^CSF-\d{6}$` | - | PRIMARY KEY | - |
| `course_id` | VARCHAR(96) | required | `^CRS-\d{4}-\d{4}$` | - | FOREIGN KEY -> courses.course_id | - |
| `staff_id` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | - |
| `course_role` | VARCHAR(24) | required | `LEAD_INSTRUCTOR`, `GRADER` | - | - | - |
| `effective_from_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `effective_to_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | NULL = open-ended. |

### 4. Learner (`learners`)

Student registered with the institution.

* **Primary key**: `learner_id`
* **Cardinality**: 1:N Enrollment, 1:N Submission

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `learner_id` | VARCHAR(96) | required | `^LRN-\d{6}$` | - | PRIMARY KEY | - |
| `first_name` | VARCHAR(64) | required | - | - | - | - |
| `last_name` | VARCHAR(64) | required | - | - | - | - |
| `email` | VARCHAR(128) | required | `^[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}$` | - | UNIQUE | - |
| `registration_date_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | <= every enrollment of the learner. |
| `status` | VARCHAR(16) | required | `ACTIVE`, `SUSPENDED`, `ALUMNI` | - | - | - |
| `status_effective_from_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | Required iff status != ACTIVE; no submission after this instant. |

### 5. Enrollment (`enrollments`)

Bridge: learner enrolled in a course (N:M Learner-Course), with effective dates and status.

* **Primary key**: `enrollment_id`
* **Cardinality**: N:M bridge
* **Composite unique keys**: (course_id, learner_id)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `enrollment_id` | VARCHAR(96) | required | `^ENR-\d{6}$` | - | PRIMARY KEY | - |
| `course_id` | VARCHAR(96) | required | `^CRS-\d{4}-\d{4}$` | - | FOREIGN KEY -> courses.course_id | - |
| `learner_id` | VARCHAR(96) | required | `^LRN-\d{6}$` | - | FOREIGN KEY -> learners.learner_id | - |
| `enrolled_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | Effective-from of the enrolment. |
| `effective_to_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | Effective-to (drop / completion instant); NULL while open. |
| `enrollment_status` | VARCHAR(16) | required | `ENROLLED`, `COMPLETED`, `DROPPED`, `AUDIT` | - | - | - |
| `processed_by` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | Support staff who processed the enrolment. |

### 6. Assignment (`assignments`)

Published (or draft) coursework with deadline and policy parameters.

* **Primary key**: `assignment_id`
* **Cardinality**: 1:N Rubric (versions), 1:N Submission

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `assignment_id` | VARCHAR(96) | required | `^ASN-\d{4}-\d{6}$` | - | PRIMARY KEY | - |
| `course_id` | VARCHAR(96) | required | `^CRS-\d{4}-\d{4}$` | - | FOREIGN KEY -> courses.course_id | - |
| `title` | VARCHAR(160) | required | - | - | - | - |
| `description` | TEXT | required | - | - | - | - |
| `created_by` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | - |
| `created_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `published_at_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | NULL while DRAFT. |
| `due_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | == due_at_local converted with `timezone` rules. |
| `due_at_local` | VARCHAR(19) | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$` | ISO-8601 local wall-clock | - | - |
| `timezone` | VARCHAR(32) | required | `UTC`, `America/New_York`, `America/Los_Angeles`, `Europe/London`, `Asia/Kolkata` | - | - | - |
| `utc_offset_minutes` | INTEGER | required | - | minutes | - | Offset in force at due_at_utc (DST aware). |
| `grace_period_minutes` | INTEGER | required |  range [0, 120] | minutes | - | Submission is late only if later than due + grace. |
| `late_penalty_per_day` | DECIMAL(2dp) | required |  range [0, ] | points/day | - | - |
| `late_cutoff_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | == due_at_utc + 5 days; later submissions are not accepted. |
| `max_score` | DECIMAL(2dp) | required |  range [0, ] | points | - | - |
| `allow_resubmission` | BOOLEAN | required | - | - | - | - |
| `max_resubmissions` | INTEGER | required |  range [0, 2] | count | - | 0 iff allow_resubmission is false. |
| `resubmission_window_days` | INTEGER | required |  range [0, ] | days | - | - |
| `appeal_window_days` | INTEGER | required |  range [0, ] | days | - | - |
| `status` | VARCHAR(16) | required | `DRAFT`, `PUBLISHED`, `CLOSED` | - | - | DRAFT iff published_at_utc is NULL; CLOSED iff late_cutoff_utc <= data cut-off. |

### 7. Rubric (`rubrics`)

Versioned scoring guide of an assignment; exactly one version is effective at any instant.

* **Primary key**: `rubric_id`
* **Cardinality**: N:1 Assignment, 1:N RubricCriterion, 1:N Grade
* **Composite unique keys**: (assignment_id, version_no)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `rubric_id` | VARCHAR(96) | required | `^RUB-ASN-\d{4}-\d{6}-\d{2}$` | - | PRIMARY KEY | - |
| `assignment_id` | VARCHAR(96) | required | `^ASN-\d{4}-\d{6}$` | - | FOREIGN KEY -> assignments.assignment_id | - |
| `version_no` | INTEGER | required |  range [1, ] | - | - | - |
| `title` | VARCHAR(200) | required | - | - | - | - |
| `total_points` | DECIMAL(2dp) | required |  range [0, ] | points | - | == SUM(criteria.max_points). |
| `effective_from_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `effective_to_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | Set when superseded by the next version. |
| `status` | VARCHAR(16) | required | `ACTIVE`, `SUPERSEDED` | - | - | - |
| `created_by` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | - |
| `created_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |

### 8. RubricCriterion (`rubric_criteria`)

One scored dimension of a rubric.

* **Primary key**: `criterion_id`
* **Cardinality**: N:1 Rubric, 1:N GradeCriterionScore
* **Composite unique keys**: (rubric_id, sequence_no)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `criterion_id` | VARCHAR(96) | required | `^CRT-RUB-ASN-\d{4}-\d{6}-\d{2}-\d{2}$` | - | PRIMARY KEY | - |
| `rubric_id` | VARCHAR(96) | required | `^RUB-ASN-\d{4}-\d{6}-\d{2}$` | - | FOREIGN KEY -> rubrics.rubric_id | - |
| `sequence_no` | INTEGER | required |  range [1, ] | - | - | - |
| `criterion_name` | VARCHAR(96) | required | - | - | - | - |
| `description` | TEXT | required | - | - | - | - |
| `max_points` | DECIMAL(2dp) | required |  range [0.0001, ] | points | - | - |
| `weight_pct` | DECIMAL(2dp) | required |  range [0, 100] | % | - | Weights of a rubric sum to 100. |

### 9. Submission (`submissions`)

One attempt by a learner at an assignment (attempt 1 = first submission).

* **Primary key**: `submission_id`
* **Cardinality**: N:1 Assignment, N:1 Learner, 1:N SubmissionArtifact, 0..1:1 Grade, 0..1:1 Feedback
* **Composite unique keys**: (assignment_id, learner_id, attempt_number)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `submission_id` | VARCHAR(96) | required | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | PRIMARY KEY | == SUB-<assignment_id>-<learner_id>-<attempt:02d>. |
| `assignment_id` | VARCHAR(96) | required | `^ASN-\d{4}-\d{6}$` | - | FOREIGN KEY -> assignments.assignment_id | - |
| `learner_id` | VARCHAR(96) | required | `^LRN-\d{6}$` | - | FOREIGN KEY -> learners.learner_id | - |
| `enrollment_id` | VARCHAR(96) | optional | `^ENR-\d{6}$` | - | FOREIGN KEY -> enrollments.enrollment_id | Enrolment under which the work was submitted. |
| `attempt_number` | INTEGER | required |  range [1, 3] | - | - | - |
| `previous_submission_id` | VARCHAR(96) | optional | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | FOREIGN KEY -> submissions.submission_id | Prior attempt (NULL for attempt 1). |
| `submitted_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `applicable_deadline_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | Assignment due date (attempt 1) or resubmission due date (attempt >= 2). |
| `is_late` | BOOLEAN | required | - | - | - | submitted_at_utc > applicable_deadline_utc + grace. |
| `late_days` | INTEGER | required |  range [0, ] | days | - | CEIL((submitted - deadline)/24h) if late else 0. |
| `expected_file_count` | INTEGER | required |  range [1, 2] | - | - | - |
| `file_check_status` | VARCHAR(16) | required | `COMPLETE`, `MISSING_FILE`, `EMPTY_FILE` | - | - | MISSING_FILE: no artefact rows; EMPTY_FILE: an artefact of 0 bytes; COMPLETE otherwise. |
| `status` | VARCHAR(16) | required | `SUBMITTED`, `GRADED`, `RESUBMITTED`, `APPEALED` | - | - | - |

### 10. SubmissionArtifact (`submission_artifacts`)

File metadata attached to a submission.

* **Primary key**: `artifact_id`
* **Cardinality**: N:1 Submission
* **Composite unique keys**: (submission_id, sequence_no)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `artifact_id` | VARCHAR(96) | required | `^ART-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}-\d{2}$` | - | PRIMARY KEY | - |
| `submission_id` | VARCHAR(96) | required | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | FOREIGN KEY -> submissions.submission_id | - |
| `sequence_no` | INTEGER | required |  range [1, ] | - | - | - |
| `file_name` | VARCHAR(128) | required | - | - | - | - |
| `file_size_bytes` | INTEGER | required |  range [0, ] | bytes | - | 0 only for EMPTY_FILE submissions. |
| `file_type` | VARCHAR(8) | required | `pdf`, `zip`, `py`, `docx` | - | - | - |
| `storage_uri` | VARCHAR(255) | required | - | - | UNIQUE | - |
| `checksum_sha256` | VARCHAR(64) | required | `^[0-9a-f]{64}$` | - | - | SHA-256 of the empty string iff size is 0. |
| `uploaded_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | <= submission.submitted_at_utc. |

### 11. Grade (`grades`)

Current grade of a submission; every change is retained in grade_versions.

* **Primary key**: `grade_id`
* **Cardinality**: 1:1 Submission, 1:N GradeVersion, 1:N GradeCriterionScore, 0..1:1 Appeal

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `grade_id` | VARCHAR(96) | required | `^GRD-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | PRIMARY KEY | == GRD-<submission_id>. |
| `submission_id` | VARCHAR(96) | required | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | UNIQUE | - |
| `rubric_id` | VARCHAR(96) | required | `^RUB-ASN-\d{4}-\d{6}-\d{2}$` | - | FOREIGN KEY -> rubrics.rubric_id | Rubric version effective at graded_at_utc. |
| `grader_id` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | Must be course staff (course_staff). |
| `raw_score` | DECIMAL(2dp) | required |  range [0, ] | points | - | == SUM(grade_criterion_scores.awarded_points); must be <= rubric total. |
| `late_penalty_points` | DECIMAL(2dp) | required |  range [0, ] | points | - | == MIN(raw, late_days x late_penalty_per_day). |
| `adjustment_points` | DECIMAL(2dp) | required |  range [0, ] | points | - | Appeal adjustment; 0 unless REVISED. |
| `final_score` | DECIMAL(2dp) | required |  range [0, ] | points | - | == MAX(0, raw - late_penalty + adjustment). |
| `graded_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `grade_status` | VARCHAR(16) | required | `PUBLISHED`, `REVISED` | - | - | REVISED iff current_version > 1. |
| `current_version` | INTEGER | required |  range [1, ] | - | - | - |

### 12. Appeal (`appeals`)

Formal learner appeal against a grade, reviewed by an academic administrator.

* **Primary key**: `appeal_id`
* **Cardinality**: N:1 Grade (max 1 per grade), N:1 Submission, N:1 Learner, 0..N GradeVersion

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `appeal_id` | VARCHAR(96) | required | `^APP-\d{4}-\d{6}$` | - | PRIMARY KEY | - |
| `submission_id` | VARCHAR(96) | required | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | FOREIGN KEY -> submissions.submission_id | - |
| `grade_id` | VARCHAR(96) | required | `^GRD-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | UNIQUE | At most one appeal per grade. |
| `learner_id` | VARCHAR(96) | required | `^LRN-\d{6}$` | - | FOREIGN KEY -> learners.learner_id | - |
| `reason_code` | VARCHAR(24) | required | `GRADING_ERROR`, `RUBRIC_MISAPPLIED`, `LATE_PENALTY_ERROR`, `MISSING_FILE_DISPUTE`, `OTHER` | - | - | - |
| `reason` | TEXT | required | - | - | - | - |
| `filed_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `intake_by` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | Support staff who registered the appeal. |
| `status` | VARCHAR(16) | required | `SUBMITTED`, `IN_REVIEW`, `UPHELD`, `REJECTED` | - | - | - |
| `original_score` | DECIMAL(2dp) | required |  range [0, ] | points | - | == grade final_score before the appeal. |
| `adjusted_score` | DECIMAL(2dp) | optional |  range [0, ] | points | - | NULL while open; == original for REJECTED. |
| `reviewed_by` | VARCHAR(96) | optional | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | Academic administrator. |
| `review_started_at_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `decided_at_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `decision_code` | VARCHAR(32) | optional | `UPHELD_GRADING_ERROR`, `REJECTED_NO_ERROR`, `REJECTED_OUT_OF_WINDOW` | - | - | - |
| `resolution_notes` | TEXT | optional | - | - | - | - |

### 13. GradeVersion (`grade_versions`)

Append-only history of every grade state (version 1 = initial grading).

* **Primary key**: `grade_version_id`
* **Cardinality**: N:1 Grade, 0..1:1 Appeal
* **Composite unique keys**: (grade_id, version_no)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `grade_version_id` | VARCHAR(96) | required | `^GRV-GRD-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}-\d{2}$` | - | PRIMARY KEY | - |
| `grade_id` | VARCHAR(96) | required | `^GRD-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | FOREIGN KEY -> grades.grade_id | - |
| `version_no` | INTEGER | required |  range [1, ] | - | - | - |
| `raw_score` | DECIMAL(2dp) | required |  range [0, ] | points | - | - |
| `late_penalty_points` | DECIMAL(2dp) | required |  range [0, ] | points | - | - |
| `adjustment_points` | DECIMAL(2dp) | required |  range [0, ] | points | - | - |
| `final_score` | DECIMAL(2dp) | required |  range [0, ] | points | - | - |
| `change_type` | VARCHAR(24) | required | `INITIAL`, `APPEAL_ADJUSTMENT` | - | - | - |
| `changed_by` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | - |
| `changed_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `appeal_id` | VARCHAR(96) | optional | `^APP-\d{4}-\d{6}$` | - | FOREIGN KEY -> appeals.appeal_id | Set for APPEAL_ADJUSTMENT versions. |

### 14. GradeCriterionScore (`grade_criterion_scores`)

Rubric-based score for one criterion of a grade.

* **Primary key**: `score_id`
* **Cardinality**: N:1 Grade, N:1 RubricCriterion
* **Composite unique keys**: (grade_id, criterion_id)

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `score_id` | VARCHAR(96) | required | `^SCR-GRD-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}-\d{2}$` | - | PRIMARY KEY | - |
| `grade_id` | VARCHAR(96) | required | `^GRD-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | FOREIGN KEY -> grades.grade_id | - |
| `criterion_id` | VARCHAR(96) | required | `^CRT-RUB-ASN-\d{4}-\d{6}-\d{2}-\d{2}$` | - | FOREIGN KEY -> rubric_criteria.criterion_id | Must belong to the grade's rubric. |
| `awarded_points` | DECIMAL(2dp) | required |  range [0, ] | points | - | <= criterion.max_points. |
| `criterion_comment` | TEXT | optional | - | - | - | - |

### 15. Feedback (`feedback`)

Qualitative instructor feedback attached to a graded submission.

* **Primary key**: `feedback_id`
* **Cardinality**: 1:1 Submission

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `feedback_id` | VARCHAR(96) | required | `^FDB-SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | PRIMARY KEY | - |
| `submission_id` | VARCHAR(96) | required | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | UNIQUE | - |
| `instructor_id` | VARCHAR(96) | required | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | - |
| `qualitative_comment` | TEXT | required | - | - | - | - |
| `strengths` | TEXT | required | - | - | - | - |
| `growth_areas` | TEXT | required | - | - | - | - |
| `provided_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | == grade.graded_at_utc. |

### 16. Resubmission (`resubmissions`)

Request for another attempt, its decision and outcome (links attempt n to n+1).

* **Primary key**: `resubmission_id`
* **Cardinality**: 1:1 original Submission, 0..1:1 new Submission

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `resubmission_id` | VARCHAR(96) | required | `^RES-\d{4}-\d{6}$` | - | PRIMARY KEY | - |
| `original_submission_id` | VARCHAR(96) | required | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | UNIQUE | - |
| `new_submission_id` | VARCHAR(96) | optional | `^SUB-ASN-\d{4}-\d{6}-LRN-\d{6}-\d{2}$` | - | UNIQUE | NULL if denied, expired or still open. |
| `requested_at_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `request_reason` | TEXT | required | - | - | - | - |
| `status` | VARCHAR(16) | required | `REQUESTED`, `APPROVED`, `DENIED`, `EXPIRED` | - | - | - |
| `decision_reason` | VARCHAR(40) | optional | `APPROVED_SCORE_BELOW_THRESHOLD`, `APPROVED_MISSING_FILE`, `DENIED_OUTSIDE_WINDOW`, `DENIED_SCORE_ABOVE_THRESHOLD` | - | - | - |
| `decided_by` | VARCHAR(96) | optional | `^(INS|ADM|SUP|PLT)-\d{6}$` | - | FOREIGN KEY -> staff.staff_id | - |
| `decided_at_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `resubmission_due_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | Set when approved. |
| `resubmitted_at_utc` | TIMESTAMP | optional | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |
| `policy_compliant` | BOOLEAN | required | - | - | - | Request satisfied the resubmission policy at decision time. |

### 17. AuditLog (`audit_logs`)

Append-only event history of every lifecycle state change.

* **Primary key**: `audit_id`
* **Cardinality**: Polymorphic N:1 to the audited entity

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `audit_id` | VARCHAR(96) | required | `^AUD-\d{4}-\d{6}$` | - | PRIMARY KEY | Sequential in (timestamp, event order). |
| `entity_name` | VARCHAR(24) | required | `Course`, `Assignment`, `Rubric`, `Enrollment`, `Submission`, `Grade`, `Resubmission`, `Appeal` | - | - | - |
| `entity_id` | VARCHAR(96) | required | - | - | - | PK of the entity (polymorphic). |
| `action_type` | VARCHAR(32) | required | `COURSE_CREATE`, `ASSIGNMENT_CREATE`, `ASSIGNMENT_PUBLISH`, `ASSIGNMENT_CLOSE`, `RUBRIC_CREATE`, `RUBRIC_SUPERSEDE`, `ENROLL`, `ENROLLMENT_END`, `SUBMISSION_CREATE`, `FILE_FLAG`, `SUBMISSION_GRADED`, `SUBMISSION_SUPERSEDED`, `GRADE_PUBLISH`, `GRADE_MUTATE`, `RESUBMISSION_REQUEST`, `RESUBMISSION_DECIDE`, `RESUBMISSION_EXPIRE`, `APPEAL_FILE`, `APPEAL_INTAKE`, `APPEAL_REVIEW_START`, `APPEAL_RESOLVE`, `SUBMISSION_APPEALED`, `SUBMISSION_APPEAL_CLOSED` | - | - | - |
| `actor_id` | VARCHAR(24) | required | - | - | - | Learner id, staff id, or SYSTEM. |
| `actor_role` | VARCHAR(24) | required | `LEARNER`, `INSTRUCTOR`, `ACADEMIC_ADMIN`, `SUPPORT_STAFF`, `PLATFORM_ADMIN`, `SYSTEM` | - | - | - |
| `from_status` | VARCHAR(24) | optional | - | - | - | - |
| `to_status` | VARCHAR(24) | optional | - | - | - | - |
| `previous_state` | TEXT | optional | - | - | - | JSON before the change. |
| `new_state` | TEXT | required | - | - | - | JSON after the change. |
| `timestamp_utc` | TIMESTAMP | required | `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` | ISO-8601 UTC | - | - |

## 7. Ground truth (separate artefact)

Injected anomaly types (`label_class = ANOMALY`):

* `UNENROLLED_LEARNER_SUBMISSION` - Submission from a learner with no effective enrolment in the course (required).
* `GRADE_EXCEEDS_MAX` - A criterion score and raw_score above the rubric maximum (required).
* `DOUBLE_LATE_PENALTY` - Late penalty deducted twice (required).
* `APPEAL_NO_AUDIT_LOG` - Upheld appeal changed the grade with no grade_versions row and no GRADE_MUTATE audit event (required).
* `RESUBMISSION_POLICY_VIOLATION` - Resubmission approved although the assignment disallows it (extra).
* `APPEAL_OUTSIDE_WINDOW_UPHELD` - Appeal filed after the appeal window but upheld (extra).

Other label classes: `EXCEPTION_PATH` (valid but unusual outcomes such as missing files, denied/expired resubmissions, out-of-window appeals) and `BOUNDARY_VALID` (valid deadline-boundary submissions). These exist to measure false positives.

### 18. GroundTruth (`ground_truth`)

Labels for injected anomalies, valid exception paths and valid boundary cases. NEVER an input feature.

* **Primary key**: `ground_truth_id`
* **Cardinality**: Separate artefact

| Field | Type | Req/Opt | Allowed values / format | Units | Uniqueness / FK | Validation rule / notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ground_truth_id` | VARCHAR(96) | required | `^GT-\d{4}-\d{6}$` | - | PRIMARY KEY | - |
| `label_class` | VARCHAR(16) | required | `ANOMALY`, `EXCEPTION_PATH`, `BOUNDARY_VALID` | - | - | - |
| `issue_type` | VARCHAR(64) | required | - | - | - | Anomaly type (ANOMALY) or exception/boundary kind. |
| `entity_name` | VARCHAR(24) | required | - | - | - | - |
| `record_id` | VARCHAR(96) | required | - | - | - | PK of the labelled record (heterogeneous: any table). |
| `field_name` | VARCHAR(48) | required | - | - | - | - |
| `expected_value` | TEXT | required | - | - | - | - |
| `actual_value` | TEXT | required | - | - | - | - |
| `expected_decision` | TEXT | required | - | - | - | What a correct system should decide for this record. |
| `description` | TEXT | required | - | - | - | - |
