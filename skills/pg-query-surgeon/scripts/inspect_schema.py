#!/usr/bin/env python3
"""Inspect PostgreSQL DDL schema files and pg_catalog / pg_stat_user_tables / pg_stat_activity snapshots."""
import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope, redact_secrets, run_readonly_psql_query


def inspect_catalog_snapshot(catalog: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    recs: List[str] = []

    for tbl in catalog.get("pg_stat_user_tables", []):
        relname = tbl.get("relname", "unknown")
        n_live = int(tbl.get("n_live_tup", 0) or 0)
        n_dead = int(tbl.get("n_dead_tup", 0) or 0)
        seq_scan = int(tbl.get("seq_scan", 0) or 0)
        idx_scan = int(tbl.get("idx_scan", 0) or 0)
        dead_ratio = round((n_dead * 100.0 / max(1, n_live + n_dead)), 2)

        if n_dead >= 50000 and dead_ratio >= 20.0:
            findings.append({
                "id": f"CAT-BLOAT-{relname.upper()}",
                "category": "autovacuum_bloat",
                "severity": "high",
                "classification": "verified",
                "table": relname,
                "title": f"Table `{relname}` has {dead_ratio}% dead tuples ({n_dead} dead vs {n_live} live in pg_stat_user_tables)",
                "evidence": tbl,
                "likely_causes": ["Autovacuum scale factor (default 0.2) is too high for large hot tables or long-running transactions are holding back xmin"],
                "confidence": "high",
                "recommendation": f"Tune table-level autovacuum: `ALTER TABLE {relname} SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_vacuum_cost_limit = 1000);`"
            })
            recs.append(f"Lower autovacuum_vacuum_scale_factor on bloated table `{relname}`.")

        if seq_scan >= 1000 and n_live >= 50000 and seq_scan > idx_scan * 2:
            findings.append({
                "id": f"CAT-SEQ-{relname.upper()}",
                "category": "catalog_seq_scan",
                "severity": "medium",
                "classification": "verified",
                "table": relname,
                "title": f"High sequential scan count on `{relname}` (seq_scan={seq_scan} vs idx_scan={idx_scan})",
                "evidence": tbl,
                "likely_causes": ["Missing indexes on frequent filter predicates"],
                "confidence": "high",
                "recommendation": f"Inspect top queries against `{relname}` in pg_stat_statements and add targeted indexes."
            })

    for idx in catalog.get("pg_index", []):
        if idx.get("indisvalid") is False:
            idx_name = idx.get("indexrelname", "unknown_idx")
            findings.append({
                "id": f"CAT-INVIDX-{idx_name.upper()}",
                "category": "invalid_index",
                "severity": "high",
                "classification": "verified",
                "table": idx.get("tablename", "unknown"),
                "title": f"Invalid index `{idx_name}` (`indisvalid=false`) left behind by failed CREATE INDEX CONCURRENTLY",
                "evidence": idx,
                "likely_causes": ["Previous concurrent index build failed due to deadlock, unique violation, or canceled session"],
                "confidence": "high",
                "recommendation": f"Drop and rebuild safely: `DROP INDEX CONCURRENTLY {idx_name};`"
            })
            recs.append(f"Drop invalid index `{idx_name}` using DROP INDEX CONCURRENTLY.")

    for act in catalog.get("pg_stat_activity", []):
        state = act.get("state")
        wait_event_type = act.get("wait_event_type")
        duration_sec = float(act.get("duration_seconds", 0) or 0)
        if state == "idle in transaction" and duration_sec >= 60.0:
            findings.append({
                "id": f"CAT-IDLETX-{act.get('pid', 0)}",
                "category": "transaction_pinning",
                "severity": "high",
                "classification": "verified",
                "table": "(session)",
                "title": f"Session PID {act.get('pid')} stuck `idle in transaction` for {duration_sec}s (blocks VACUUM and DDL locks)",
                "evidence": {"pid": act.get("pid"), "state": state, "duration_seconds": duration_sec},
                "likely_causes": ["Application opened BEGIN transaction and waited on external HTTP call or leaked connection"],
                "confidence": "high",
                "recommendation": "Set `idle_in_transaction_session_timeout = '60s'` in postgresql.conf or role configuration."
            })
        elif wait_event_type == "Lock" and duration_sec >= 5.0:
            findings.append({
                "id": f"CAT-LOCKWAIT-{act.get('pid', 0)}",
                "category": "lock_contention",
                "severity": "high",
                "classification": "verified",
                "table": "(session)",
                "title": f"Session PID {act.get('pid')} blocked on Lock wait for {duration_sec}s",
                "evidence": {"pid": act.get("pid"), "wait_event_type": wait_event_type, "duration_seconds": duration_sec},
                "likely_causes": ["Concurrent DDL without lock_timeout or unindexed foreign key row lock contention"],
                "confidence": "high",
                "recommendation": "Check blocking_pids(pid) and terminate or cancel the blocker."
            })

    return findings, recs


def inspect_schema_sql(schema_sql: str, catalog_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tables: Dict[str, Dict[str, Any]] = {}
    indexes: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    recommendations: List[str] = []

    for match in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_\.]+)\s*\((.*?)\)\s*;", schema_sql, re.IGNORECASE | re.DOTALL):
        tname = match.group(1).split(".")[-1].lower()
        body = match.group(2)
        has_pk = "PRIMARY KEY" in body.upper()
        fks: List[str] = []
        cols: List[Tuple[str, str]] = []

        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            fk_inline = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s+([a-zA-Z0-9_\(\)]+).*\bREFERENCES\b", line, re.IGNORECASE)
            if fk_inline:
                fks.append(fk_inline.group(1).lower())
            fk_table = re.search(r"FOREIGN\s+KEY\s*\(\s*([a-zA-Z0-9_,\s]+)\s*\)\s*REFERENCES", line, re.IGNORECASE)
            if fk_table:
                first_col = fk_table.group(1).split(",")[0].strip().lower()
                fks.append(first_col)
            col_m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s+([a-zA-Z0-9_]+)", line)
            if col_m and col_m.group(1).upper() not in ("CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK"):
                cols.append((col_m.group(1).lower(), col_m.group(2).upper()))

        tables[tname] = {"has_pk": has_pk, "foreign_keys": list(dict.fromkeys(fks)), "columns": cols}

    indexed_leading_cols: Dict[str, Set[str]] = {t: set() for t in tables}
    for m in re.finditer(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s+ON\s+([a-zA-Z0-9_\.]+)(?:\s+USING\s+[a-zA-Z0-9_]+)?\s*\(\s*([a-zA-Z0-9_,\s]+)\s*\)", schema_sql, re.IGNORECASE):
        idx_name = m.group(1)
        tname = m.group(2).split(".")[-1].lower()
        col_list = [c.strip().split()[0].lower() for c in m.group(3).split(",")]
        indexes.append({"name": idx_name, "table": tname, "columns": col_list})
        if tname not in indexed_leading_cols:
            indexed_leading_cols[tname] = set()
        if col_list:
            indexed_leading_cols[tname].add(col_list[0])

    for tname, tinfo in tables.items():
        if not tinfo["has_pk"]:
            findings.append({
                "id": f"SCH-PK-{tname.upper()}",
                "category": "schema_integrity",
                "severity": "high",
                "classification": "verified",
                "table": tname,
                "title": f"Table `{tname}` has no PRIMARY KEY (breaks logical replication and bloat remediation tools like pg_repack)",
                "evidence": {"table": tname, "has_pk": False},
                "likely_causes": ["Table created without an explicit PRIMARY KEY constraint"],
                "confidence": "high",
                "recommendation": f"Add a BIGINT GENERATED ALWAYS AS IDENTITY or UUIDv7 primary key to `{tname}`."
            })

        for fk_col in tinfo["foreign_keys"]:
            if fk_col not in indexed_leading_cols.get(tname, set()):
                findings.append({
                    "id": f"SCH-FKIDX-{tname.upper()}-{fk_col.upper()}",
                    "category": "missing_fk_index",
                    "severity": "high",
                    "classification": "verified",
                    "table": tname,
                    "title": f"Unindexed foreign key `{tname}.{fk_col}` causes sequential scans on parent DELETE/UPDATE and join queries",
                    "evidence": {"table": tname, "foreign_key_column": fk_col},
                    "likely_causes": ["PostgreSQL automatically indexes PRIMARY KEY and UNIQUE constraints, but never automatically indexes FOREIGN KEY columns"],
                    "confidence": "high",
                    "recommendation": f"Run `CREATE INDEX CONCURRENTLY idx_{tname}_{fk_col} ON {tname} ({fk_col});`"
                })

        for cname, ctype in tinfo["columns"]:
            if (cname == "id" or cname.endswith("_id")) and ctype in ("INT", "INTEGER", "SERIAL"):
                findings.append({
                    "id": f"SCH-INT4-{tname.upper()}-{cname.upper()}",
                    "category": "type_safety",
                    "severity": "medium",
                    "classification": "heuristic",
                    "table": tname,
                    "title": f"32-bit integer identifier `{tname}.{cname}` ({ctype}) risks 2.14B sequence exhaustion in high-growth tables",
                    "evidence": {"table": tname, "column": cname, "type": ctype},
                    "likely_causes": ["Using 4-byte integer/serial instead of 8-byte BIGINT"],
                    "confidence": "medium",
                    "recommendation": "Prefer `BIGINT` (`BIGSERIAL` or `GENERATED ALWAYS AS IDENTITY`) for primary and foreign key columns."
                })

    if catalog_snapshot:
        cat_findings, cat_recs = inspect_catalog_snapshot(catalog_snapshot)
        findings.extend(cat_findings)
        recommendations.extend(cat_recs)

    status = "warning" if findings else "ok"
    if not findings:
        findings.append({
            "id": "SCH-OK-001",
            "category": "schema",
            "severity": "info",
            "classification": "verified",
            "table": "(all)",
            "title": "All inspected tables have primary keys and indexed foreign keys",
            "evidence": {"table_count": len(tables), "index_count": len(indexes)},
            "likely_causes": ["Well-structured relational schema"],
            "confidence": "high",
            "recommendation": "No immediate schema structural changes required."
        })

    for f in findings:
        if f["recommendation"] not in recommendations:
            recommendations.append(f["recommendation"])

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "table_count": len(tables),
            "index_count": len(indexes),
            "tables": tables,
            "indexes": indexes,
            "catalog_inspected": catalog_snapshot is not None,
        },
        "warnings": [],
        "recommendations": list(dict.fromkeys(recommendations)),
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect PostgreSQL DDL schema file and optional catalog snapshot.")
    parser.add_argument("--schema-file", required=True, help="Path to SQL schema file")
    parser.add_argument("--catalog-file", help="Optional path to pg_catalog / pg_stat snapshot JSON file")
    parser.add_argument("--live-dsn", help="Optional PostgreSQL connection string for read-only catalog query")
    parser.add_argument("--allow-live-readonly", action="store_true", help="Explicit consent flag required when --live-dsn is supplied")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    if args.live_dsn and not args.allow_live_readonly:
        print(json.dumps(make_error_envelope("Live database connection requires explicit --allow-live-readonly flag.")), file=sys.stderr)
        return 2

    p = Path(args.schema_file)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"Schema file not found: {p}")), file=sys.stderr)
        return 1

    cat_data = None
    if args.catalog_file:
        cp = Path(args.catalog_file)
        if not cp.exists():
            print(json.dumps(make_error_envelope(f"Catalog file not found: {cp}")), file=sys.stderr)
            return 1
        cat_data = json.loads(cp.read_text(encoding="utf-8"))

    payload = inspect_schema_sql(p.read_text(encoding="utf-8", errors="replace"), cat_data)
    if args.live_dsn:
        res = run_readonly_psql_query(args.live_dsn, "SELECT relname, n_live_tup, n_dead_tup, seq_scan, idx_scan FROM pg_stat_user_tables LIMIT 50;")
        if not res["ok"]:
            payload["warnings"].append(f"Live read-only psql check failed safely: {res['error']}")

    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
