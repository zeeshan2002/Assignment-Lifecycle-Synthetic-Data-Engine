"""
Deterministic, zero-padded, immutable identifiers.

Required conventions (from the assignment brief):
    Assignment   ASN-2026-000001
    Rubric       RUB-<assignment-id>-01
    Submission   SUB-<assignment-id>-<learner-id>-01
    Grade        GRD-<submission-id>
    Appeal       APP-2026-000001
Derived/extra conventions follow the same pattern (child id embeds the parent id).
"""


class IdGenerator:
    def __init__(self, year: int = 2026):
        self.year = year

    # master data
    def staff_id(self, prefix: str, i: int) -> str: return f"{prefix}-{i:06d}"
    def course_id(self, i: int) -> str: return f"CRS-{self.year}-{i:04d}"
    def course_staff_id(self, i: int) -> str: return f"CSF-{i:06d}"
    def learner_id(self, i: int) -> str: return f"LRN-{i:06d}"
    def enrollment_id(self, i: int) -> str: return f"ENR-{i:06d}"
    def assignment_id(self, i: int) -> str: return f"ASN-{self.year}-{i:06d}"
    def rubric_id(self, assignment_id: str, version: int = 1) -> str: return f"RUB-{assignment_id}-{version:02d}"
    def criterion_id(self, rubric_id: str, seq: int) -> str: return f"CRT-{rubric_id}-{seq:02d}"

    # transactions
    def submission_id(self, assignment_id: str, learner_id: str, attempt: int = 1) -> str:
        return f"SUB-{assignment_id}-{learner_id}-{attempt:02d}"
    def artifact_id(self, submission_id: str, seq: int) -> str: return f"ART-{submission_id}-{seq:02d}"
    def grade_id(self, submission_id: str) -> str: return f"GRD-{submission_id}"
    def grade_version_id(self, grade_id: str, version: int) -> str: return f"GRV-{grade_id}-{version:02d}"
    def criterion_score_id(self, grade_id: str, seq: int) -> str: return f"SCR-{grade_id}-{seq:02d}"
    def feedback_id(self, submission_id: str) -> str: return f"FDB-{submission_id}"
    def resubmission_id(self, i: int) -> str: return f"RES-{self.year}-{i:06d}"
    def appeal_id(self, i: int) -> str: return f"APP-{self.year}-{i:06d}"
    def audit_id(self, i: int) -> str: return f"AUD-{self.year}-{i:06d}"
    def ground_truth_id(self, i: int) -> str: return f"GT-{self.year}-{i:06d}"
