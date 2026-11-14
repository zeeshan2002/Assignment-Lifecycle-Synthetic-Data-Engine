"""
Assignment Management System (AMS) assignment-lifecycle synthetic data generator.

    python generate.py --seed 20261022 --scale starter --output-dir ./data
    python generate.py --seed 20261022 --scale full    --output-dir ./data

The same generator serves every scale; only the ScaleConfig preset changes.
"""

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Dict, Tuple

from src.config import DEFAULT_SEED, SCALE_PRESETS, SNAPSHOT_AT
from src.docs import render_data_dictionary
from src.exporters.files import export_all
from src.generator.pipeline import generate_dataset
from src.metrics import compute_metrics, render_markdown
from src.report import render_validation_json, render_validation_markdown
from src.validator.engine import Validator

GENERATOR_VERSION = "2.0.0"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_generation(seed: int, scale_name: str, out: Path, anomalies_per_type: int = None,
                   quiet: bool = False) -> Tuple[Dict, Dict, Dict]:
    if scale_name not in SCALE_PRESETS:
        raise ValueError(f"unknown scale {scale_name!r}; choose from {sorted(SCALE_PRESETS)}")
    scale = SCALE_PRESETS[scale_name]
    if anomalies_per_type is not None:
        scale = replace(scale, anomalies_per_type=anomalies_per_type)
    log = (lambda *a: None) if quiet else print
    out.mkdir(parents=True, exist_ok=True)

    log(f"[1/5] generating dataset  seed={seed} scale={scale.name}")
    tables, ground_truth = generate_dataset(seed, scale)

    log("[2/5] validating (8 stages)")
    report = Validator(tables, ground_truth).run()

    log("[3/5] exporting CSV / JSON / SQL / SQLite + isolated ground truth")
    written = export_all(out, tables, ground_truth)

    log("[4/5] metrics, validation summary, data dictionary")
    metrics = compute_metrics(tables)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "metrics.md").write_text(render_markdown(metrics), encoding="utf-8", newline="\n")
    (out / "validation_summary.json").write_text(render_validation_json(report), encoding="utf-8", newline="\n")
    (out / "validation_summary.md").write_text(render_validation_markdown(report), encoding="utf-8", newline="\n")
    (out / "data_dictionary.md").write_text(render_data_dictionary(), encoding="utf-8", newline="\n")

    log("[5/5] source manifest (row counts + SHA-256 of every file)")
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "source_manifest.json")
    counts = {k: len(v) for k, v in tables.items()}
    counts["ground_truth"] = len(ground_truth)
    manifest = {
        "generator": {"name": "AMS Assignment Lifecycle Synthetic Data Engine", "version": GENERATOR_VERSION},
        "command": f"python generate.py --seed {seed} --scale {scale.name} --output-dir ./data"
                   + (f" --anomalies-per-type {anomalies_per_type}" if anomalies_per_type is not None else ""),
        "seed": seed, "scale": scale.name, "scale_parameters": asdict(scale),
        "data_cutoff_utc": SNAPSHOT_AT.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "row_counts": counts,
        "files": {p.relative_to(out).as_posix(): {"bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files},
        "provenance": {
            "source": "Fully synthetic: deterministic PRNG (Python random.Random, SHA-256-derived sub-streams) + documented business rules",
            "external_data_used": False, "external_sources": [], "personal_data": "none (invented names, example e-mail domains)",
            "license": "Generated data is original synthetic content; no third-party licence terms apply",
            "fields_discarded": [], "transformations": [],
        },
        "environment": {"python": platform.python_version()},
        "validation": report["summary"],
    }
    (out / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    log(f"done. {len(files)} files in {out.resolve()}  (validation: {'PASS' if report['summary']['all_passed'] else 'FAIL'})")
    return tables, report, manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AMS synthetic data generator")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--scale", choices=sorted(SCALE_PRESETS), default="starter")
    ap.add_argument("--output-dir", default="./data")
    ap.add_argument("--anomalies-per-type", type=int, default=None, help="override injected anomalies per type (0 = clean baseline)")
    a = ap.parse_args(argv)
    _, report, manifest = run_generation(a.seed, a.scale, Path(a.output_dir), a.anomalies_per_type)
    for k, v in manifest["row_counts"].items():
        print(f"  {k:24s}{v:>9d}")
    return 0 if report["summary"]["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
