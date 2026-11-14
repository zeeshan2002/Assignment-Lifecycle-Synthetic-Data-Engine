-- AMS assignment lifecycle schema (ANSI SQL, generated from src/schema.py)
-- CHECK constraints cover enums and non-negativity only. Injected anomalies are schema-valid by
-- design (e.g. a grade above the rubric maximum still loads); they are caught by the validator.

CREATE TABLE staff (
    staff_id VARCHAR(96) PRIMARY KEY,
    full_name VARCHAR(96) NOT NULL,
    email VARCHAR(128) UNIQUE NOT NULL,
    role VARCHAR(24) NOT NULL CHECK (role IN ('INSTRUCTOR', 'ACADEMIC_ADMIN', 'SUPPORT_STAFF', 'PLATFORM_ADMIN')),
    department VARCHAR(64) CHECK (department IS NULL OR department IN ('Computer Science', 'Data Science', 'Mathematics', 'Engineering', 'Business')),
    status VARCHAR(16) NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    hired_at_utc TIMESTAMP NOT NULL
);

CREATE TABLE courses (
    course_id VARCHAR(96) PRIMARY KEY,
    course_code VARCHAR(24) UNIQUE NOT NULL,
    title VARCHAR(128) NOT NULL,
    department VARCHAR(64) NOT NULL CHECK (department IN ('Computer Science', 'Data Science', 'Mathematics', 'Engineering', 'Business')),
    term VARCHAR(16) NOT NULL CHECK (term IN ('SPRING-2026', 'SUMMER-2026', 'FALL-2026')),
    instructor_id VARCHAR(96) NOT NULL,
    created_by VARCHAR(96) NOT NULL,
    created_at_utc TIMESTAMP NOT NULL,
    start_date_utc TIMESTAMP NOT NULL,
    end_date_utc TIMESTAMP NOT NULL,
    FOREIGN KEY (instructor_id) REFERENCES staff(staff_id),
    FOREIGN KEY (created_by) REFERENCES staff(staff_id)
);

CREATE TABLE course_staff (
    course_staff_id VARCHAR(96) PRIMARY KEY,
    course_id VARCHAR(96) NOT NULL,
    staff_id VARCHAR(96) NOT NULL,
    course_role VARCHAR(24) NOT NULL CHECK (course_role IN ('LEAD_INSTRUCTOR', 'GRADER')),
    effective_from_utc TIMESTAMP NOT NULL,
    effective_to_utc TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES courses(course_id),
    FOREIGN KEY (staff_id) REFERENCES staff(staff_id),
    UNIQUE (course_id, staff_id)
);

CREATE TABLE learners (
    learner_id VARCHAR(96) PRIMARY KEY,
    first_name VARCHAR(64) NOT NULL,
    last_name VARCHAR(64) NOT NULL,
    email VARCHAR(128) UNIQUE NOT NULL,
    registration_date_utc TIMESTAMP NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('ACTIVE', 'SUSPENDED', 'ALUMNI')),
    status_effective_from_utc TIMESTAMP
);

CREATE TABLE enrollments (
    enrollment_id VARCHAR(96) PRIMARY KEY,
    course_id VARCHAR(96) NOT NULL,
    learner_id VARCHAR(96) NOT NULL,
    enrolled_at_utc TIMESTAMP NOT NULL,
    effective_to_utc TIMESTAMP,
    enrollment_status VARCHAR(16) NOT NULL CHECK (enrollment_status IN ('ENROLLED', 'COMPLETED', 'DROPPED', 'AUDIT')),
    processed_by VARCHAR(96) NOT NULL,
    FOREIGN KEY (course_id) REFERENCES courses(course_id),
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id),
    FOREIGN KEY (processed_by) REFERENCES staff(staff_id),
    UNIQUE (course_id, learner_id)
);

CREATE TABLE assignments (
    assignment_id VARCHAR(96) PRIMARY KEY,
    course_id VARCHAR(96) NOT NULL,
    title VARCHAR(160) NOT NULL,
    description TEXT NOT NULL,
    created_by VARCHAR(96) NOT NULL,
    created_at_utc TIMESTAMP NOT NULL,
    published_at_utc TIMESTAMP,
    due_at_utc TIMESTAMP NOT NULL,
    due_at_local VARCHAR(19) NOT NULL,
    timezone VARCHAR(32) NOT NULL CHECK (timezone IN ('UTC', 'America/New_York', 'America/Los_Angeles', 'Europe/London', 'Asia/Kolkata')),
    utc_offset_minutes INTEGER NOT NULL,
    grace_period_minutes INTEGER NOT NULL CHECK (grace_period_minutes >= 0),
    late_penalty_per_day FLOAT NOT NULL CHECK (late_penalty_per_day >= 0),
    late_cutoff_utc TIMESTAMP NOT NULL,
    max_score FLOAT NOT NULL CHECK (max_score >= 0),
    allow_resubmission BOOLEAN NOT NULL,
    max_resubmissions INTEGER NOT NULL CHECK (max_resubmissions >= 0),
    resubmission_window_days INTEGER NOT NULL CHECK (resubmission_window_days >= 0),
    appeal_window_days INTEGER NOT NULL CHECK (appeal_window_days >= 0),
    status VARCHAR(16) NOT NULL CHECK (status IN ('DRAFT', 'PUBLISHED', 'CLOSED')),
    FOREIGN KEY (course_id) REFERENCES courses(course_id),
    FOREIGN KEY (created_by) REFERENCES staff(staff_id)
);

CREATE TABLE rubrics (
    rubric_id VARCHAR(96) PRIMARY KEY,
    assignment_id VARCHAR(96) NOT NULL,
    version_no INTEGER NOT NULL CHECK (version_no >= 1),
    title VARCHAR(200) NOT NULL,
    total_points FLOAT NOT NULL CHECK (total_points >= 0),
    effective_from_utc TIMESTAMP NOT NULL,
    effective_to_utc TIMESTAMP,
    status VARCHAR(16) NOT NULL CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
    created_by VARCHAR(96) NOT NULL,
    created_at_utc TIMESTAMP NOT NULL,
    FOREIGN KEY (assignment_id) REFERENCES assignments(assignment_id),
    FOREIGN KEY (created_by) REFERENCES staff(staff_id),
    UNIQUE (assignment_id, version_no)
);

CREATE TABLE rubric_criteria (
    criterion_id VARCHAR(96) PRIMARY KEY,
    rubric_id VARCHAR(96) NOT NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 1),
    criterion_name VARCHAR(96) NOT NULL,
    description TEXT NOT NULL,
    max_points FLOAT NOT NULL CHECK (max_points >= 0.0001),
    weight_pct FLOAT NOT NULL CHECK (weight_pct >= 0),
    FOREIGN KEY (rubric_id) REFERENCES rubrics(rubric_id),
    UNIQUE (rubric_id, sequence_no)
);

CREATE TABLE submissions (
    submission_id VARCHAR(96) PRIMARY KEY,
    assignment_id VARCHAR(96) NOT NULL,
    learner_id VARCHAR(96) NOT NULL,
    enrollment_id VARCHAR(96),
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    previous_submission_id VARCHAR(96),
    submitted_at_utc TIMESTAMP NOT NULL,
    applicable_deadline_utc TIMESTAMP NOT NULL,
    is_late BOOLEAN NOT NULL,
    late_days INTEGER NOT NULL CHECK (late_days >= 0),
    expected_file_count INTEGER NOT NULL CHECK (expected_file_count >= 1),
    file_check_status VARCHAR(16) NOT NULL CHECK (file_check_status IN ('COMPLETE', 'MISSING_FILE', 'EMPTY_FILE')),
    status VARCHAR(16) NOT NULL CHECK (status IN ('SUBMITTED', 'GRADED', 'RESUBMITTED', 'APPEALED')),
    FOREIGN KEY (assignment_id) REFERENCES assignments(assignment_id),
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id),
    FOREIGN KEY (enrollment_id) REFERENCES enrollments(enrollment_id),
    FOREIGN KEY (previous_submission_id) REFERENCES submissions(submission_id),
    UNIQUE (assignment_id, learner_id, attempt_number)
);

CREATE TABLE submission_artifacts (
    artifact_id VARCHAR(96) PRIMARY KEY,
    submission_id VARCHAR(96) NOT NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 1),
    file_name VARCHAR(128) NOT NULL,
    file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes >= 0),
    file_type VARCHAR(8) NOT NULL CHECK (file_type IN ('pdf', 'zip', 'py', 'docx')),
    storage_uri VARCHAR(255) UNIQUE NOT NULL,
    checksum_sha256 VARCHAR(64) NOT NULL,
    uploaded_at_utc TIMESTAMP NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id),
    UNIQUE (submission_id, sequence_no)
);

CREATE TABLE grades (
    grade_id VARCHAR(96) PRIMARY KEY,
    submission_id VARCHAR(96) UNIQUE NOT NULL,
    rubric_id VARCHAR(96) NOT NULL,
    grader_id VARCHAR(96) NOT NULL,
    raw_score FLOAT NOT NULL CHECK (raw_score >= 0),
    late_penalty_points FLOAT NOT NULL CHECK (late_penalty_points >= 0),
    adjustment_points FLOAT NOT NULL CHECK (adjustment_points >= 0),
    final_score FLOAT NOT NULL CHECK (final_score >= 0),
    graded_at_utc TIMESTAMP NOT NULL,
    grade_status VARCHAR(16) NOT NULL CHECK (grade_status IN ('PUBLISHED', 'REVISED')),
    current_version INTEGER NOT NULL CHECK (current_version >= 1),
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id),
    FOREIGN KEY (rubric_id) REFERENCES rubrics(rubric_id),
    FOREIGN KEY (grader_id) REFERENCES staff(staff_id)
);

CREATE TABLE appeals (
    appeal_id VARCHAR(96) PRIMARY KEY,
    submission_id VARCHAR(96) NOT NULL,
    grade_id VARCHAR(96) UNIQUE NOT NULL,
    learner_id VARCHAR(96) NOT NULL,
    reason_code VARCHAR(24) NOT NULL CHECK (reason_code IN ('GRADING_ERROR', 'RUBRIC_MISAPPLIED', 'LATE_PENALTY_ERROR', 'MISSING_FILE_DISPUTE', 'OTHER')),
    reason TEXT NOT NULL,
    filed_at_utc TIMESTAMP NOT NULL,
    intake_by VARCHAR(96) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('SUBMITTED', 'IN_REVIEW', 'UPHELD', 'REJECTED')),
    original_score FLOAT NOT NULL CHECK (original_score >= 0),
    adjusted_score FLOAT CHECK (adjusted_score IS NULL OR adjusted_score >= 0),
    reviewed_by VARCHAR(96),
    review_started_at_utc TIMESTAMP,
    decided_at_utc TIMESTAMP,
    decision_code VARCHAR(32) CHECK (decision_code IS NULL OR decision_code IN ('UPHELD_GRADING_ERROR', 'REJECTED_NO_ERROR', 'REJECTED_OUT_OF_WINDOW')),
    resolution_notes TEXT,
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id),
    FOREIGN KEY (grade_id) REFERENCES grades(grade_id),
    FOREIGN KEY (learner_id) REFERENCES learners(learner_id),
    FOREIGN KEY (intake_by) REFERENCES staff(staff_id),
    FOREIGN KEY (reviewed_by) REFERENCES staff(staff_id)
);

CREATE TABLE grade_versions (
    grade_version_id VARCHAR(96) PRIMARY KEY,
    grade_id VARCHAR(96) NOT NULL,
    version_no INTEGER NOT NULL CHECK (version_no >= 1),
    raw_score FLOAT NOT NULL CHECK (raw_score >= 0),
    late_penalty_points FLOAT NOT NULL CHECK (late_penalty_points >= 0),
    adjustment_points FLOAT NOT NULL CHECK (adjustment_points >= 0),
    final_score FLOAT NOT NULL CHECK (final_score >= 0),
    change_type VARCHAR(24) NOT NULL CHECK (change_type IN ('INITIAL', 'APPEAL_ADJUSTMENT')),
    changed_by VARCHAR(96) NOT NULL,
    changed_at_utc TIMESTAMP NOT NULL,
    appeal_id VARCHAR(96),
    FOREIGN KEY (grade_id) REFERENCES grades(grade_id),
    FOREIGN KEY (changed_by) REFERENCES staff(staff_id),
    FOREIGN KEY (appeal_id) REFERENCES appeals(appeal_id),
    UNIQUE (grade_id, version_no)
);

CREATE TABLE grade_criterion_scores (
    score_id VARCHAR(96) PRIMARY KEY,
    grade_id VARCHAR(96) NOT NULL,
    criterion_id VARCHAR(96) NOT NULL,
    awarded_points FLOAT NOT NULL CHECK (awarded_points >= 0),
    criterion_comment TEXT,
    FOREIGN KEY (grade_id) REFERENCES grades(grade_id),
    FOREIGN KEY (criterion_id) REFERENCES rubric_criteria(criterion_id),
    UNIQUE (grade_id, criterion_id)
);

CREATE TABLE feedback (
    feedback_id VARCHAR(96) PRIMARY KEY,
    submission_id VARCHAR(96) UNIQUE NOT NULL,
    instructor_id VARCHAR(96) NOT NULL,
    qualitative_comment TEXT NOT NULL,
    strengths TEXT NOT NULL,
    growth_areas TEXT NOT NULL,
    provided_at_utc TIMESTAMP NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id),
    FOREIGN KEY (instructor_id) REFERENCES staff(staff_id)
);

CREATE TABLE resubmissions (
    resubmission_id VARCHAR(96) PRIMARY KEY,
    original_submission_id VARCHAR(96) UNIQUE NOT NULL,
    new_submission_id VARCHAR(96) UNIQUE,
    requested_at_utc TIMESTAMP NOT NULL,
    request_reason TEXT NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('REQUESTED', 'APPROVED', 'DENIED', 'EXPIRED')),
    decision_reason VARCHAR(40) CHECK (decision_reason IS NULL OR decision_reason IN ('APPROVED_SCORE_BELOW_THRESHOLD', 'APPROVED_MISSING_FILE', 'DENIED_OUTSIDE_WINDOW', 'DENIED_SCORE_ABOVE_THRESHOLD')),
    decided_by VARCHAR(96),
    decided_at_utc TIMESTAMP,
    resubmission_due_utc TIMESTAMP,
    resubmitted_at_utc TIMESTAMP,
    policy_compliant BOOLEAN NOT NULL,
    FOREIGN KEY (original_submission_id) REFERENCES submissions(submission_id),
    FOREIGN KEY (new_submission_id) REFERENCES submissions(submission_id),
    FOREIGN KEY (decided_by) REFERENCES staff(staff_id)
);

CREATE TABLE audit_logs (
    audit_id VARCHAR(96) PRIMARY KEY,
    entity_name VARCHAR(24) NOT NULL CHECK (entity_name IN ('Course', 'Assignment', 'Rubric', 'Enrollment', 'Submission', 'Grade', 'Resubmission', 'Appeal')),
    entity_id VARCHAR(96) NOT NULL,
    action_type VARCHAR(32) NOT NULL CHECK (action_type IN ('COURSE_CREATE', 'ASSIGNMENT_CREATE', 'ASSIGNMENT_PUBLISH', 'ASSIGNMENT_CLOSE', 'RUBRIC_CREATE', 'RUBRIC_SUPERSEDE', 'ENROLL', 'ENROLLMENT_END', 'SUBMISSION_CREATE', 'FILE_FLAG', 'SUBMISSION_GRADED', 'SUBMISSION_SUPERSEDED', 'GRADE_PUBLISH', 'GRADE_MUTATE', 'RESUBMISSION_REQUEST', 'RESUBMISSION_DECIDE', 'RESUBMISSION_EXPIRE', 'APPEAL_FILE', 'APPEAL_INTAKE', 'APPEAL_REVIEW_START', 'APPEAL_RESOLVE', 'SUBMISSION_APPEALED', 'SUBMISSION_APPEAL_CLOSED')),
    actor_id VARCHAR(24) NOT NULL,
    actor_role VARCHAR(24) NOT NULL CHECK (actor_role IN ('LEARNER', 'INSTRUCTOR', 'ACADEMIC_ADMIN', 'SUPPORT_STAFF', 'PLATFORM_ADMIN', 'SYSTEM')),
    from_status VARCHAR(24),
    to_status VARCHAR(24),
    previous_state TEXT,
    new_state TEXT NOT NULL,
    timestamp_utc TIMESTAMP NOT NULL
);
