"""
Step 10 - reproducibility check.

Generates the dataset twice with the same seed into two temporary directories and compares the row
counts and the SHA-256 of EVERY output file (CSV, JSON, SQL, SQLite, ground truth, metrics,
validation summary, data dictionary and the source manifest itself).

    python verify_reproducibility.py --seed 20261022 --scale full
"""

import argparse
import sys
import tempfile
from pathlib import Path

from generate import run_generation, sha256_file
from src.config import DEFAULT_SEED, SCALE_PRESETS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify bit-exact reproducibility")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--scale", choices=sorted(SCALE_PRESETS), default="full")
    a = ap.parse_args(argv)
    print(f"Reproducibility check: seed={a.seed} scale={a.scale}")
    with tempfile.TemporaryDirectory(prefix="ams_repro_") as tmp:
        da, db = Path(tmp) / "run_A", Path(tmp) / "run_B"
        _, _, ma = run_generation(a.seed, a.scale, da, quiet=True)
        _, _, mb = run_generation(a.seed, a.scale, db, quiet=True)
        files_a = sorted(p.relative_to(da).as_posix() for p in da.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(db).as_posix() for p in db.rglob("*") if p.is_file())
        problems = []
        if files_a != files_b:
            problems.append(f"file lists differ: {set(files_a) ^ set(files_b)}")
        if ma["row_counts"] != mb["row_counts"]:
            problems.append("row counts differ between runs")
        print(f"\n{'file':<44}{'rows/bytes':>14}  {'sha256 (A)':<20} match")
        print("-" * 92)
        for rel in files_a:
            ha, hb = sha256_file(da / rel), sha256_file(db / rel)
            ok = ha == hb
            if not ok:
                problems.append(f"checksum mismatch: {rel}")
            print(f"{rel:<44}{(da / rel).stat().st_size:>14,}  {ha[:16]}...  {'OK' if ok else 'MISMATCH'}")
        print("\nrow counts (run A == run B):")
        for k, v in ma["row_counts"].items():
            print(f"  {k:24s}{v:>9d}  {'OK' if v == mb['row_counts'][k] else 'MISMATCH'}")
    if problems:
        print("\nFAILED:\n  " + "\n  ".join(problems))
        return 1
    print(f"\nSUCCESS: {len(files_a)} files and all row counts are identical across two runs with seed {a.seed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
