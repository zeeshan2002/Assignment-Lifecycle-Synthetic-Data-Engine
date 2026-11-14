"""
Anomaly planner.

Valid baseline bundles are generated first by the same code path as every other bundle. Each target
bundle is then RE-BUILT with a single named override (see WorkflowGenerator.build_bundle). Because
overrides are applied after all baseline random draws and use a separate RNG stream, only the
targeted values change, so unrelated rows are never silently corrupted. Targets are chosen uniformly at random over
all valid pairs (no positional clustering), are mutually disjoint, and every injection is
labelled in ground truth.

Injected scenarios (required): UNENROLLED_LEARNER_SUBMISSION, GRADE_EXCEEDS_MAX, DOUBLE_LATE_PENALTY,
APPEAL_NO_AUDIT_LOG. Extra scenarios: RESUBMISSION_POLICY_VIOLATION, APPEAL_OUTSIDE_WINDOW_UPHELD.
"""

from typing import Callable, List, Set, Tuple

from src.config import ScaleConfig
from src.generator.prng import SeededRNG
from src.generator.workflow import Bundle, WorkflowGenerator

# (override name, override dict, predicate on assignment, post-condition on the built bundle)
# Score-changing anomalies avoid bundles with resubmission decisions: those decisions were taken on the
# clean score, and mixing the two would create a second, unlabelled inconsistency.
PLANS = [
    ("over_max", {"over_max": True}, lambda a: True, lambda b: not b.resubs),
    ("double_penalty", {"double_penalty": True}, lambda a: True, lambda b: not b.resubs),
    ("no_audit", {"no_audit": True}, lambda a: True, lambda b: True),
    ("force_resub", {"force_resub": True}, lambda a: not a["allow_resubmission"], lambda b: len(b.subs) == 2),
    ("late_appeal", {"late_appeal": True}, lambda a: True, lambda b: True),
]


class AnomalyPlanner:
    def __init__(self, wf: WorkflowGenerator, scale: ScaleConfig, rng: SeededRNG):
        self.wf, self.scale, self.rng = wf, scale, rng

    def plan(self, pairs: List[Tuple[dict, dict]]) -> Tuple[List[Bundle], Set[Tuple[str, str]]]:
        k = self.scale.anomalies_per_type
        bundles: List[Bundle] = []
        used: Set[Tuple[str, str]] = set()
        if k <= 0:
            return bundles, used
        pr = self.rng.spawn("anomaly-plan")
        # 1) unenrolled-learner submissions (brand-new pairs, not in the enrolment bridge)
        bundles += self._unenrolled(pr, k, used)
        # 2) overrides applied to randomly chosen valid pairs
        for name, ov, pred, post in PLANS:
            order = list(range(len(pairs)))
            pr.spawn("order", name).shuffle(order)
            got = 0
            for idx in order:
                if got >= k:
                    break
                asn, enr = pairs[idx]
                key = (asn["assignment_id"], enr["learner_id"])
                if key in used or not pred(asn):
                    continue
                b = self.wf.build_bundle(asn, self.wf.lmap[enr["learner_id"]], enr, ov=ov)
                if b is not None and name in b.applied and post(b):
                    used.add(key)
                    bundles.append(b)
                    got += 1
            if got < k:
                raise RuntimeError(f"Could not place {k} '{name}' anomalies (placed {got}); scale too small.")
        return bundles, used

    def _unenrolled(self, pr: SeededRNG, k: int, used: Set[Tuple[str, str]]) -> List[Bundle]:
        wf = self.wf
        enrolled = {(e["course_id"], e["learner_id"]) for e in wf.enrollments}
        assignments = [a for a in wf.amap.values() if a["status"] != "DRAFT"]
        learners = [l for l in wf.lmap.values() if l["status"] == "ACTIVE"]
        out: List[Bundle] = []
        i = 0
        trials = 0
        while len(out) < k and trials < 5000:
            trials += 1
            ur = pr.spawn("unenrolled", trials)
            a, L = ur.choice(assignments), ur.choice(learners)
            key = (a["assignment_id"], L["learner_id"])
            pub = wf.t[a["assignment_id"]]["pub"]
            from src.timeutil import parse
            if (a["course_id"], L["learner_id"]) in enrolled or key in used or parse(L["registration_date_utc"]) > pub:
                continue
            b = wf.build_bundle(a, L, None, ov={"unenrolled": True})
            if b is not None and "unenrolled" in b.applied:
                used.add(key)
                out.append(b)
        if len(out) < k:
            raise RuntimeError("Could not place unenrolled-learner anomalies.")
        return out
