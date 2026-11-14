"""CSV / JSON / SQL / SQLite exporters and the CSV loader. All output is byte-deterministic."""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from src.schema import GROUND_TRUTH_TABLE, TABLES, Table, cast_row, csv_value, ddl


def _json_value(col, v: Any) -> Any:
    if v is not None and col.typ == "float":
        return round(v, 2)
    return v


def write_csv(path: Path, table: Table, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(table.col_names)
        for r in rows:
            w.writerow([csv_value(c, r[c.name]) for c in table.cols])


def write_json(path: Path, table: Table, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("[\n")
        for i, r in enumerate(rows):
            obj = {c.name: _json_value(c, r[c.name]) for c in table.cols}
            f.write(("," if i else "") + json.dumps(obj, ensure_ascii=False, separators=(", ", ": ")) + "\n")
        f.write("]\n")


def _sql_literal(col, v: Any) -> str:
    if v is None:
        return "NULL"
    if col.typ == "bool":
        return "TRUE" if v else "FALSE"
    if col.typ == "float":
        return f"{v:.2f}"
    if col.typ == "int":
        return str(int(v))
    return "'" + str(v).replace("'", "''") + "'"


def write_sql_seed(path: Path, tables: Dict[str, List[dict]], batch: int = 500) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("-- Seed data (generated). Load after schema.sql. Tables are in foreign-key-safe order.\nBEGIN;\n")
        for t in TABLES:
            rows = tables[t.name]
            cols = ", ".join(t.col_names)
            for i in range(0, len(rows), batch):
                chunk = rows[i:i + batch]
                vals = ",\n".join("(" + ", ".join(_sql_literal(c, r[c.name]) for c in t.cols) + ")" for r in chunk)
                f.write(f"INSERT INTO {t.name} ({cols}) VALUES\n{vals};\n")
        f.write("COMMIT;\n")


def write_sqlite(path: Path, schema_sql: str, tables: Dict[str, List[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode = OFF")
    con.execute("PRAGMA synchronous = OFF")
    con.execute("PRAGMA foreign_keys = ON")           # joins are enforced while loading
    con.executescript(schema_sql)
    for t in TABLES:
        cols = ", ".join(t.col_names)
        ph = ", ".join("?" for _ in t.cols)
        data = [[(int(r[c.name]) if (c.typ == "bool" and r[c.name] is not None) else r[c.name]) for c in t.cols]
                for r in tables[t.name]]
        con.executemany(f"INSERT INTO {t.name} ({cols}) VALUES ({ph})", data)
    con.commit()
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    con.close()
    if bad:
        raise RuntimeError(f"SQLite foreign_key_check failed: {bad[:5]}")


def export_all(out: Path, tables: Dict[str, List[dict]], ground_truth: List[dict]) -> List[Path]:
    written: List[Path] = []
    for t in TABLES:
        p = out / "csv" / f"{t.name}.csv"
        write_csv(p, t, tables[t.name]); written.append(p)
        p = out / "json" / f"{t.name}.json"
        write_json(p, t, tables[t.name]); written.append(p)
    schema_sql = ddl()
    (out / "sql").mkdir(parents=True, exist_ok=True)
    (out / "sql" / "schema.sql").write_text(schema_sql, encoding="utf-8", newline="\n")
    write_sql_seed(out / "sql" / "seed_data.sql", tables)
    write_sqlite(out / "sql" / "ams.sqlite", schema_sql, tables)
    written += [out / "sql" / "schema.sql", out / "sql" / "seed_data.sql", out / "sql" / "ams.sqlite"]
    # ground truth is isolated in its own folder, never inside csv/ json/ sql/
    p = out / "ground_truth" / "ground_truth.csv"
    write_csv(p, GROUND_TRUTH_TABLE, ground_truth); written.append(p)
    p = out / "ground_truth" / "ground_truth.json"
    write_json(p, GROUND_TRUTH_TABLE, ground_truth); written.append(p)
    return written


def load_csv_tables(data_dir: Path) -> (Dict[str, List[dict]], List[dict]):
    tables = {}
    for t in TABLES:
        with open(data_dir / "csv" / f"{t.name}.csv", encoding="utf-8", newline="") as f:
            tables[t.name] = [cast_row(t, row) for row in csv.DictReader(f)]
    with open(data_dir / "ground_truth" / "ground_truth.csv", encoding="utf-8", newline="") as f:
        gt = [cast_row(GROUND_TRUTH_TABLE, row) for row in csv.DictReader(f)]
    return tables, gt
