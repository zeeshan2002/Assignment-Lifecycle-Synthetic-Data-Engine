"""
Assembly: selects bundles to hit the exact submission volume, assigns sequential RES-/APP- ids in
deterministic (assignment, learner) order, resolves deferred references, and builds ground truth.
"""

from typing import Dict, List, Tuple

from src.config import ScaleConfig
from src.generator.anomalies import AnomalyPlanner
from src.generator.workflow import Bundle, WorkflowGenerator
from src.id_generator import IdGenerator

LABEL_ORDER = {"ANOMALY": 0, "EXCEPTION_PATH": 1, "BOUNDARY_VALID": 2}


def select_bundles(wf: WorkflowGenerator, scale: ScaleConfig) -> List[Bundle]:
    pairs = wf.candidate_pairs()
    planner = AnomalyPlanner(wf, scale, wf.rng)
    bundles, used = planner.plan(pairs)
    count = sum(len(b.subs) for b in bundles)
    target = scale.num_submissions
    for asn, enr in pairs:
        if count >= target:
            break
        if (asn["assignment_id"], enr["learner_id"]) in used:
            continue
        b = wf.build_bundle(asn, wf.lmap[enr["learner_id"]], enr, cap=target - count)
        if b is None or not b.subs:
            continue
        bundles.append(b)
        count += len(b.subs)
    if count != target:
        raise RuntimeError(f"Scale infeasible: produced {count} submissions, target {target}. "
                           f"Increase learners/enrolments or lower the target.")
    return bundles


def assemble(bundles: List[Bundle], ids: IdGenerator) -> Tuple[Dict[str, List[dict]], List[dict]]:
    bundles = sorted(bundles, key=lambda b: (b.asn_id, b.learner_id))
    out: Dict[str, List[dict]] = {k: [] for k in
                                  ["submissions", "submission_artifacts", "grades", "appeals", "grade_versions",
                                   "grade_criterion_scores", "feedback", "resubmissions"]}
    labels: List[dict] = []
    res_no = app_no = 1
    for b in bundles:
        by_id = {s["submission_id"]: i for i, s in enumerate(b.subs)}
        for rs in b.resubs:
            rs["resubmission_id"] = ids.resubmission_id(res_no)
            res_no += 1
            if rs["resubmitted_at_utc"]:
                rs["new_submission_id"] = b.subs[by_id[rs["original_submission_id"]] + 1]["submission_id"]
        for ap in b.appeals:
            ap["appeal_id"] = ids.appeal_id(app_no)
            app_no += 1
        for v in b.versions:
            if isinstance(v["appeal_id"], dict):
                v["appeal_id"] = v["appeal_id"]["appeal_id"]
        for lb in b.labels:
            if "ref" in lb:
                row, key = lb.pop("ref")
                lb["record_id"] = row[key]
            labels.append(lb)
        out["submissions"] += b.subs
        out["submission_artifacts"] += b.arts
        out["grades"] += b.grades
        out["appeals"] += b.appeals
        out["grade_versions"] += b.versions
        out["grade_criterion_scores"] += b.scores
        out["feedback"] += b.feedback
        out["resubmissions"] += b.resubs
    labels.sort(key=lambda l: (LABEL_ORDER[l["label_class"]], l["issue_type"], l["record_id"]))
    gt = []
    for i, lb in enumerate(labels, start=1):
        gt.append({"ground_truth_id": ids.ground_truth_id(i), **lb})
    return out, gt
