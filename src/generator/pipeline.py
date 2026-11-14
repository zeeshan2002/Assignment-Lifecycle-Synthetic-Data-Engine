"""In-memory generation pipeline (no I/O): master data -> assignments -> transactions -> audit log."""

from typing import Dict, List, Tuple

from src.config import ScaleConfig
from src.generator.assemble import assemble, select_bundles
from src.generator.assignments import AssignmentGenerator
from src.generator.events import build_audit_log
from src.generator.master_data import MasterDataGenerator
from src.generator.prng import SeededRNG
from src.generator.workflow import WorkflowGenerator
from src.id_generator import IdGenerator
from src.schema import TABLES


def generate_dataset(seed: int, scale: ScaleConfig, year: int = 2026) -> Tuple[Dict[str, List[dict]], List[dict]]:
    rng = SeededRNG(seed)
    ids = IdGenerator(year)

    # 1) master data first
    md = MasterDataGenerator(rng, ids, scale)
    staff = md.generate_staff()
    courses, course_staff = md.generate_courses(staff)
    learners, enrollments = md.generate_learners_and_enrollments(courses, staff)

    # 2) assignments, versioned rubrics, criteria
    assignments, rubrics, criteria = AssignmentGenerator(rng, ids, scale).generate(courses, md.course_tz)

    T: Dict[str, List[dict]] = {
        "staff": staff, "courses": courses, "course_staff": course_staff, "learners": learners,
        "enrollments": enrollments, "assignments": assignments, "rubrics": rubrics, "rubric_criteria": criteria,
    }

    # 3) dependent transactions (bundles), anomaly injection, exact volume
    wf = WorkflowGenerator(rng, ids, scale, T)
    bundles = select_bundles(wf, scale)
    tx, ground_truth = assemble(bundles, ids)
    T.update(tx)

    # 4) event history derived from the final records
    T["audit_logs"] = build_audit_log(T, ids)

    ordered = {t.name: T[t.name] for t in TABLES}
    return ordered, ground_truth
