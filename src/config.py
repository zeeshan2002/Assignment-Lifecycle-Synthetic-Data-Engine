"""
Central configuration: scale presets, business-policy constants, data cut-off.

Every business rule that the generator applies AND the validator re-checks lives here, so the
two can never drift apart.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Tuple

YEAR = 2026

# Data cut-off ("as of" instant). No event in the dataset is later than this; anything that would
# happen after it is simply not generated, so open states (pending grade, open appeal, open
# resubmission window) are real lifecycle states rather than artefacts.
SNAPSHOT_AT = datetime(2026, 11, 13, 0, 0, 0, tzinfo=timezone.utc)

# ---- Business policy -------------------------------------------------------------------------
MAX_SCORE = 100.0
LATE_PENALTY_PER_DAY = 5.0          # points per started 24h after the deadline
LATE_WINDOW_DAYS = 5                # submissions accepted until due + 5 days
RESUB_REQUEST_WINDOW_DAYS = 5       # resubmission must be requested within 5 days of grade publication
RESUB_DEADLINE_DAYS = 7             # approved resubmission is due 7 days after approval
RESUB_LATE_CUTOFF_DAYS = 2          # ... and accepted (with late penalty) until 2 days after that
RESUB_SCORE_THRESHOLD = 70.0        # resubmission is granted only below this final score (or for file problems)
APPEAL_WINDOW_DAYS = 7              # appeal must be filed within 7 days of grade publication
EMPTY_FILE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@dataclass(frozen=True)
class ScaleConfig:
    name: str
    num_courses: int
    num_learners: int
    num_assignments: int
    num_submissions: int            # TOTAL submission rows (first attempts + resubmission attempts)
    num_instructors: int
    num_admins: int
    num_support: int
    num_platform: int
    enroll_weights: Tuple[float, float, float]   # P(learner enrols in 1 / 2 / 3 courses)
    anomalies_per_type: int
    boundary_rate: float = 0.01      # share of first attempts generated exactly on a deadline boundary
    draft_rate: float = 0.02         # share of assignments still DRAFT (unpublished)
    rubric_revision_rate: float = 0.06
    file_issue_rate: float = 0.025   # missing / empty artefacts
    grading_error_rate: float = 0.06  # latent grader mistakes (drive upheld appeals)


SCALE_PRESETS: Dict[str, ScaleConfig] = {
    "starter": ScaleConfig(
        name="starter", num_courses=10, num_learners=500, num_assignments=50, num_submissions=1500,
        num_instructors=8, num_admins=3, num_support=3, num_platform=1,
        enroll_weights=(0.25, 0.45, 0.30), anomalies_per_type=2,
    ),
    "full": ScaleConfig(
        name="full", num_courses=300, num_learners=10000, num_assignments=1000, num_submissions=30000,
        num_instructors=60, num_admins=10, num_support=8, num_platform=2,
        enroll_weights=(0.80, 0.17, 0.03), anomalies_per_type=10,
    ),
}

DEFAULT_SEED = 20261022
