"""
Standalone validation harness. Reads the exported CSV files (and the separate ground truth) and runs
the 8 validation stages.

    python validate.py --data-dir ./data
"""

import argparse
import sys
from pathlib import Path

from src.exporters.files import load_csv_tables
from src.report import render_validation_json, render_validation_markdown
from src.validator.engine import Validator


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate an exported AMS dataset")
    ap.add_argument("--data-dir", default="./data")
    ap.add_argument("--no-write", action="store_true", help="do not rewrite validation_summary.{md,json}")
    a = ap.parse_args(argv)
    d = Path(a.data_dir)
    tables, gt = load_csv_tables(d)
    rep = Validator(tables, gt).run()
    print(render_validation_markdown(rep))
    if not a.no_write:
        (d / "validation_summary.md").write_text(render_validation_markdown(rep), encoding="utf-8", newline="\n")
        (d / "validation_summary.json").write_text(render_validation_json(rep), encoding="utf-8", newline="\n")
    return 0 if rep["summary"]["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
