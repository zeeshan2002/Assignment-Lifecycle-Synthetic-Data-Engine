"""Renders the validation summary (markdown + JSON) deterministically (no timestamps)."""

import json
from typing import Any, Dict


def render_validation_markdown(rep: Dict[str, Any]) -> str:
    s = rep["summary"]
    out = ["# Validation summary", "",
           f"* **Overall**: {'PASS' if s['all_passed'] else 'FAIL'} (a run passes when every violation is a labelled anomaly and nothing unexpected is found)",
           f"* **Total checks executed**: {s['total_checks']}",
           f"* **Violations found**: {s['total_violations']} (labelled anomalies: {s['labelled_anomaly_violations']}, unexpected: {s['unexpected_violations']})", "",
           "## Stages", "", "| Stage | Check | Status | Checks | Violations | Labelled anomalies | Unexpected |",
           "| :-: | :--- | :--- | ---: | ---: | ---: | ---: |"]
    for st in rep["stages"]:
        out.append(f"| {st['stage']} | {st['name']} | `{st['status']}` | {st['checks']} | {st['violations']} | "
                   f"{st['labelled_anomaly_violations']} | {st['unexpected_violations']} |")
    out += ["", "### Violations by rule", ""]
    for st in rep["stages"]:
        if st["violations_by_rule"]:
            out.append(f"* Stage {st['stage']}: " + ", ".join(f"`{k}` x{v}" for k, v in sorted(st["violations_by_rule"].items())))
    gt = rep.get("ground_truth", {})
    if "per_type" in gt:
        out += ["", "## Ground-truth reconciliation (stage 8)", "",
                "| Anomaly type | Labelled | Detected | TP | FP | FN | Precision | Recall |", "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for k, v in gt["per_type"].items():
            out.append(f"| `{k}` | {v['labelled']} | {v['detected']} | {v['true_positive']} | {v['false_positive']} | "
                       f"{v['false_negative']} | {v['precision']} | {v['recall']} |")
        out += ["", f"Label classes: {gt['label_counts']}"]
    return "\n".join(out) + "\n"


def render_validation_json(rep: Dict[str, Any]) -> str:
    return json.dumps(rep, indent=2, sort_keys=False) + "\n"
