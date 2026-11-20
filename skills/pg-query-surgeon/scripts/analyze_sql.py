#!/usr/bin/env python3
"""Static SQL query performance and N+1 pattern analyzer for PostgreSQL."""
import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import make_error_envelope, redact_secrets, split_sql_statements


def analyze_queries(sql_text: str) -> Dict[str, Any]:
    safe_sql = redact_secrets(sql_text)
    statements = split_sql_statements(safe_sql)
    findings: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    warnings: List[str] = []

    normalized_fingerprints: Dict[str, int] = {}

    for idx, stmt in enumerate(statements, start=1):
        norm = " ".join(stmt.split())
        upper = norm.upper()

        # Fingerprint for N+1 detection (replace literals with ?)
        fp = re.sub(r"'[^']*'", "?", upper)
        fp = re.sub(r"\b\d+\b", "?", fp)
        normalized_fingerprints[fp] = normalized_fingerprints.get(fp, 0) + 1

        # 1. Leading wildcard LIKE / ILIKE
        if re.search(r"\bI?LIKE\s+'%[^']+'", norm, re.IGNORECASE):
            findings.append({
                "id": f"SQL-LIKE-{idx:03d}",
                "category": "index_prevented",
                "severity": "high",
                "classification": "verified",
                "statement_index": idx,
                "statement": norm[:200],
                "title": "Leading wildcard LIKE/ILIKE ('%pattern') prevents standard B-Tree index usage",
                "evidence": {"pattern": "LIKE '%...'"},
                "likely_causes": ["B-Tree indexes are left-anchored and cannot seek on a leading wildcard"],
                "confidence": "high",
                "recommendation": "Enable pg_trgm extension and create a GIN trigram index: `CREATE INDEX CONCURRENTLY idx_trgm ON table USING gin (col gin_trgm_ops);`"
            })

        # 2. Function wrapping column in WHERE predicate
        func_match = re.search(r"\bWHERE\b.*\b(LOWER|UPPER|DATE|DATE_TRUNC|COALESCE|CAST)\s*\(\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\)\s*=", norm, re.IGNORECASE)
        if func_match:
            fn_name, col_name = func_match.group(1), func_match.group(2)
            findings.append({
                "id": f"SQL-FUNC-{idx:03d}",
                "category": "sargability",
                "severity": "high",
                "classification": "verified",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Non-SARGable function call `{fn_name}({col_name})` in WHERE clause forces sequential scan unless expression index exists",
                "evidence": {"function": fn_name, "column": col_name},
                "likely_causes": ["Applying a function to a column prevents plain column B-Tree index lookups"],
                "confidence": "high",
                "recommendation": f"Rewrite predicate as a range filter (for dates) or create an expression index on `({fn_name}({col_name}))`."
            })

        # 3. Large OFFSET pagination
        offset_match = re.search(r"\bOFFSET\s+(\d+)\b", upper)
        if offset_match and int(offset_match.group(1)) >= 1000:
            offset_val = int(offset_match.group(1))
            findings.append({
                "id": f"SQL-OFFSET-{idx:03d}",
                "category": "pagination",
                "severity": "medium",
                "classification": "verified",
                "statement_index": idx,
                "statement": norm[:200],
                "title": f"Deep OFFSET pagination (OFFSET {offset_val}) scans and discards {offset_val} rows on every query",
                "evidence": {"offset": offset_val},
                "likely_causes": ["PostgreSQL must materialize and skip all preceding rows to satisfy OFFSET"],
                "confidence": "high",
                "recommendation": "Replace OFFSET pagination with keyset (seek) pagination: `WHERE (created_at, id) < ($1, $2) ORDER BY created_at DESC, id DESC LIMIT N`."
            })

        # 4. SELECT * without LIMIT on joined or unfiltered table
        if re.search(r"^\s*SELECT\s+\*\s+FROM\b", upper) and "LIMIT" not in upper:
            findings.append({
                "id": f"SQL-STAR-{idx:03d}",
                "category": "projection",
                "severity": "medium",
                "classification": "heuristic",
                "statement_index": idx,
                "statement": norm[:200],
                "title": "Unbounded SELECT * fetches wide rows (including TOAST columns) and prevents Index-Only Scans",
                "evidence": {"select_star": True, "has_limit": False},
                "likely_causes": ["Fetching all columns forces heap page fetches even when filter columns are covered by an index"],
                "confidence": "medium",
                "recommendation": "Project only required columns to enable Index-Only Scans and reduce network/TOAST I/O."
            })

        # 5. NOT IN (SELECT ...) nullable trap
        if re.search(r"\bNOT\s+IN\s*\(\s*SELECT\b", upper):
            findings.append({
                "id": f"SQL-NOTIN-{idx:03d}",
                "category": "join_efficiency",
                "severity": "high",
                "classification": "verified",
                "statement_index": idx,
                "statement": norm[:200],
                "title": "NOT IN (SELECT ...) uses hashed/materialized subplan and returns 0 rows if any NULL exists in subquery",
                "evidence": {"construct": "NOT IN (SELECT ...)"},
                "likely_causes": ["SQL three-valued logic forces expensive NULL semantics checks in PostgreSQL"],
                "confidence": "high",
                "recommendation": "Rewrite `NOT IN (SELECT ...)` as `NOT EXISTS (SELECT 1 FROM ... WHERE ...)` for anti-join optimization and safe NULL semantics."
            })

    # Check N+1 query patterns in batch trace
    for fp, count in normalized_fingerprints.items():
        if count >= 3 and fp.startswith("SELECT"):
            findings.append({
                "id": "SQL-NPLUS1-001",
                "category": "n_plus_one",
                "severity": "high",
                "classification": "verified",
                "statement_index": 0,
                "statement": fp[:200],
                "title": f"N+1 query pattern detected: identical query shape repeated {count} times in workload trace",
                "evidence": {"fingerprint": fp[:200], "execution_count": count},
                "likely_causes": ["Application loop issuing per-entity SELECT queries instead of batched IN/ANY($1) or JOIN fetch"],
                "confidence": "high",
                "recommendation": "Batch lookups using `WHERE id = ANY($1::bigint[])` or eager-load via JOIN."
            })

    status = "warning" if findings else "ok"
    if not findings:
        findings.append({
            "id": "SQL-OK-001",
            "category": "sql_analysis",
            "severity": "info",
            "classification": "verified",
            "statement_index": 0,
            "statement": "(all queries)",
            "title": "No static SQL anti-patterns detected",
            "evidence": {"query_count": len(statements)},
            "likely_causes": ["Queries use indexed predicates and bounded projections"],
            "confidence": "high",
            "recommendation": "Verify runtime execution plans with scripts/analyze_explain.py."
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
            "query_count": len(statements),
            "unique_query_shapes": len(normalized_fingerprints),
            "anti_pattern_count": len([f for f in findings if f["severity"] != "info"]),
        },
        "warnings": warnings,
        "recommendations": recommendations,
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze PostgreSQL queries for performance anti-patterns.")
    parser.add_argument("--sql-file", required=True, help="Path to SQL file or query trace")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.sql_file)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"SQL file not found: {p}")), file=sys.stderr)
        return 1

    payload = analyze_queries(p.read_text(encoding="utf-8", errors="replace"))
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
