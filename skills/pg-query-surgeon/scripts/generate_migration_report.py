#!/usr/bin/env python3
"""Generate a unified PostgreSQL migration safety, query performance, and execution plan report."""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import analyze_explain
import analyze_sql
import check_migration_safety
import index_advisor
import inspect_schema


def generate_full_report(
    migration_file: Optional[Path],
    query_file: Optional[Path],
    explain_file: Optional[Path],
    schema_file: Optional[Path],
    pg_version: int = 16,
) -> Dict[str, Any]:
    sections: Dict[str, Any] = {}
    all_findings: List[Dict[str, Any]] = []
    all_recommendations: List[str] = []

    if migration_file and migration_file.exists():
        mig = check_migration_safety.analyze_migration_sql(
            migration_file.read_text(encoding="utf-8", errors="replace"), pg_version=pg_version
        )
        sections["migration_safety"] = mig
        all_findings.extend(mig.get("findings", []))
        all_recommendations.extend(mig.get("recommendations", []))

    if query_file and query_file.exists():
        qtext = query_file.read_text(encoding="utf-8", errors="replace")
        sql_rep = analyze_sql.analyze_queries(qtext)
        idx_recs = index_advisor.recommend_indexes_from_sql(qtext)
        sections["query_analysis"] = sql_rep
        sections["index_advisor"] = idx_recs
        all_findings.extend(sql_rep.get("findings", []))
        all_recommendations.extend(sql_rep.get("recommendations", []))
        for r in idx_recs:
            if r["recommended_ddl"] not in all_recommendations:
                all_recommendations.append(r["recommended_ddl"])

    if explain_file and explain_file.exists():
        exp_rep = analyze_explain.analyze_explain_content(explain_file.read_text(encoding="utf-8", errors="replace"))
        sections["explain_analysis"] = exp_rep
        all_findings.extend(exp_rep.get("findings", []))
        all_recommendations.extend(exp_rep.get("recommendations", []))

    if schema_file and schema_file.exists():
        sch_rep = inspect_schema.inspect_schema_sql(schema_file.read_text(encoding="utf-8", errors="replace"))
        sections["schema_inspection"] = sch_rep
        all_findings.extend(sch_rep.get("findings", []))
        all_recommendations.extend(sch_rep.get("recommendations", []))

    severities = [f.get("severity") for f in all_findings]
    if "critical" in severities:
        status = "critical"
    elif "high" in severities or "medium" in severities:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version(), "target_pg_version": str(pg_version)},
        "findings": all_findings,
        "metrics": sections,
        "warnings": [],
        "recommendations": list(dict.fromkeys(all_recommendations)),
        "errors": [],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    mig = report["metrics"].get("migration_safety", {}).get("metrics", {})
    exp = report["metrics"].get("explain_analysis", {}).get("metrics", {})
    idx_recs = report["metrics"].get("index_advisor", [])

    lines = [
        "# PostgreSQL Migration Safety & Query Optimization Report (`pg-query-surgeon`)",
        "",
        f"- **Overall Risk Status**: `{report['status'].upper()}`",
        f"- **Target PostgreSQL Version**: `PostgreSQL {report['tool_versions'].get('target_pg_version', '16')}`",
        f"- **Migration Risk Classification**: `{mig.get('risk_classification', 'N/A')}` (Score: `{mig.get('risk_score', 'N/A')}/100`)",
        f"- **Plan Execution Time**: `{exp.get('execution_time_ms', 'N/A')} ms` (Buffer Cache Hit Rate: `{exp.get('buffer_cache_hit_pct', 'N/A')}%`)",
        "",
        "## 1. Verified Findings vs Heuristic Recommendations",
        "",
    ]

    for f in report["findings"]:
        lines.extend([
            f"### [{f.get('severity', 'info').upper()}] {f['id']}: {f['title']}",
            f"- **Classification**: `{f.get('classification', 'verified')}` | **Category**: `{f.get('category')}`",
            f"- **Evidence**: `{json.dumps(f.get('evidence', {}))}`",
            f"- **Recommendation**: {f.get('recommendation', '')}",
            "",
        ])

    lines.extend([
        "## 2. Proposed Index & SQL Optimizations",
        "",
    ])
    if idx_recs:
        for r in idx_recs:
            lines.append(f"- **Table `{r['table']}`**: `{r['recommended_ddl']}` ({r['rationale']})")
    else:
        lines.append("- No composite index additions generated.")

    lines.extend([
        "",
        "## 3. Step-by-Step Zero-Downtime Migration & Rollback Strategy",
        "",
        "1. **Pre-Flight Lock Guard**: Configure `SET lock_timeout = '2s'; SET statement_timeout = '30s';` in the migration session.",
        "2. **Expand Phase**: Add new nullable columns or create indexes using `CREATE INDEX CONCURRENTLY` outside transaction blocks.",
        "3. **Backfill Phase**: Backfill historical data in batches of 1,000-5,000 rows with `pg_sleep(0.05)` between batches to avoid Replication lag and VACUUM starvation.",
        "4. **Constraint Validation Phase**: Add constraints as `NOT VALID`, then execute `ALTER TABLE ... VALIDATE CONSTRAINT` (`SHARE UPDATE EXCLUSIVE` lock).",
        "5. **Verification & Rollback**: To roll back a concurrent or invalid index without blocking traffic, execute `DROP INDEX CONCURRENTLY IF EXISTS <index_name>;`. To roll back a `NOT VALID` constraint, execute `ALTER TABLE <table_name> DROP CONSTRAINT IF EXISTS <constraint_name>;`.",
    ])
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate unified PostgreSQL migration and query report.")
    parser.add_argument("--migration-file", help="Path to SQL migration file")
    parser.add_argument("--query-file", help="Path to SQL query file")
    parser.add_argument("--explain-file", help="Path to EXPLAIN JSON file")
    parser.add_argument("--schema-file", help="Path to schema SQL file")
    parser.add_argument("--pg-version", type=int, default=16, help="Target PostgreSQL version")
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="Output format")
    parser.add_argument("--output", help="Optional output file path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    rep = generate_full_report(
        Path(args.migration_file) if args.migration_file else None,
        Path(args.query_file) if args.query_file else None,
        Path(args.explain_file) if args.explain_file else None,
        Path(args.schema_file) if args.schema_file else None,
        pg_version=args.pg_version,
    )
    rendered = render_markdown(rep) if args.format == "markdown" else json.dumps(rep, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
