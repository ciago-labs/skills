#!/usr/bin/env python3
"""PostgreSQL EXPLAIN and EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON/TEXT) execution plan analyzer."""
import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope


def walk_plan_nodes(node: Dict[str, Any], acc: List[Dict[str, Any]]) -> None:
    acc.append(node)
    for child in node.get("Plans", []) or []:
        if isinstance(child, dict):
            walk_plan_nodes(child, acc)


def parse_text_explain_to_synthetic_json(text_plan: str) -> Dict[str, Any]:
    """Convert standard PostgreSQL text EXPLAIN / EXPLAIN ANALYZE output into a normalized Plan structure."""
    lines = [l for l in text_plan.splitlines() if l.strip()]
    if not lines:
        raise ValueError("Empty EXPLAIN text")
    nodes: List[Dict[str, Any]] = []
    exec_time_ms = 0.0
    plan_time_ms = 0.0
    shared_hit = 0
    shared_read = 0
    temp_written = 0

    node_rx = re.compile(
        r"(Seq Scan|Index Scan|Index Only Scan|Bitmap Heap Scan|Nested Loop|Hash Join|Merge Join|Sort|Hash|Aggregate)"
        r"(?:\s+using\s+([a-zA-Z0-9_]+))?"
        r"(?:\s+on\s+([a-zA-Z0-9_\.]+))?"
        r".*?\(cost=([0-9\.]+)\.\.([0-9\.]+)\s+rows=(\d+)\s+width=(\d+)\)"
        r"(?:\s+\(actual time=([0-9\.]+)\.\.([0-9\.]+)\s+rows=(\d+)\s+loops=(\d+)\))?"
    )

    current_node: Optional[Dict[str, Any]] = None
    for line in lines:
        m = node_rx.search(line)
        if m:
            current_node = {
                "Node Type": m.group(1),
                "Index Name": m.group(2),
                "Relation Name": m.group(3) or "unknown_relation",
                "Startup Cost": float(m.group(4)),
                "Total Cost": float(m.group(5)),
                "Plan Rows": int(m.group(6)),
                "Plan Width": int(m.group(7)),
                "Actual Startup Time": float(m.group(8)) if m.group(8) else None,
                "Actual Total Time": float(m.group(9)) if m.group(9) else None,
                "Actual Rows": int(m.group(10)) if m.group(10) else None,
                "Actual Loops": int(m.group(11)) if m.group(11) else 1,
            }
            nodes.append(current_node)
            continue

        if current_node is not None:
            filt_m = re.search(r"Filter:\s*(.+)$", line)
            if filt_m:
                current_node["Filter"] = filt_m.group(1).strip()
            rem_m = re.search(r"Rows Removed by Filter:\s*(\d+)", line)
            if rem_m:
                current_node["Rows Removed by Filter"] = int(rem_m.group(1))
            sort_m = re.search(r"Sort Method:\s*([\w\s\-]+?)\s+(Memory|Disk):\s*(\d+)kB", line, re.IGNORECASE)
            if sort_m:
                current_node["Sort Method"] = sort_m.group(1).strip()
                current_node["Sort Space Type"] = "Disk" if sort_m.group(2).lower() == "disk" else "Memory"
                current_node["Sort Space Used"] = int(sort_m.group(3))
            hash_m = re.search(r"Batches:\s*(\d+)\s+Memory Usage:\s*(\d+)kB", line)
            if hash_m:
                current_node["Hash Batches"] = int(hash_m.group(1))
                current_node["Peak Memory Usage"] = int(hash_m.group(2))

        buf_m = re.search(r"Buffers:\s*shared(?: hit=(\d+))?(?: read=(\d+))?(?:,\s*temp written=(\d+))?", line)
        if buf_m:
            shared_hit += int(buf_m.group(1) or 0)
            shared_read += int(buf_m.group(2) or 0)
            temp_written += int(buf_m.group(3) or 0)

        pt_m = re.search(r"Planning Time:\s*([0-9\.]+)\s*ms", line)
        if pt_m:
            plan_time_ms = float(pt_m.group(1))
        et_m = re.search(r"Execution Time:\s*([0-9\.]+)\s*ms", line)
        if et_m:
            exec_time_ms = float(et_m.group(1))

    if not nodes:
        raise ValueError("Could not parse any PostgreSQL EXPLAIN plan nodes from input")

    root_plan = nodes[0]
    root_plan["Shared Hit Blocks"] = shared_hit
    root_plan["Shared Read Blocks"] = shared_read
    root_plan["Temp Written Blocks"] = temp_written
    if len(nodes) > 1:
        root_plan["Plans"] = nodes[1:]

    return {"Plan": root_plan, "Planning Time": plan_time_ms, "Execution Time": exec_time_ms}


def analyze_explain_json(raw_data: Any) -> Dict[str, Any]:
    if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict):
        root = raw_data[0]
    elif isinstance(raw_data, dict):
        root = raw_data
    else:
        raise ValueError("EXPLAIN JSON must be a JSON object or non-empty list containing a Plan object")

    plan = root.get("Plan")
    if not isinstance(plan, dict):
        raise ValueError("Missing top-level 'Plan' key in EXPLAIN JSON")

    nodes: List[Dict[str, Any]] = []
    walk_plan_nodes(plan, nodes)

    findings: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    total_shared_read_blocks = 0
    total_shared_hit_blocks = 0
    total_temp_written_blocks = 0

    for idx, n in enumerate(nodes, start=1):
        node_type = n.get("Node Type", "Unknown")
        rel = n.get("Relation Name") or n.get("Alias") or "unknown_relation"
        est_rows = n.get("Plan Rows", 0)
        act_rows = n.get("Actual Rows")
        loops = n.get("Actual Loops", 1) or 1
        rows_removed = n.get("Rows Removed by Filter", 0)
        filter_cond = n.get("Filter")
        shared_hit = n.get("Shared Hit Blocks", 0)
        shared_read = n.get("Shared Read Blocks", 0)
        temp_written = n.get("Temp Written Blocks", 0)

        total_shared_hit_blocks += shared_hit
        total_shared_read_blocks += shared_read
        total_temp_written_blocks += temp_written

        if node_type == "Seq Scan" and ((act_rows is not None and act_rows + rows_removed >= 5000) or est_rows >= 10000):
            selectivity = round((act_rows / max(1, act_rows + rows_removed)) * 100.0, 2) if act_rows is not None else None
            findings.append({
                "id": f"PLAN-SEQ-{idx:03d}",
                "category": "sequential_scan",
                "severity": "high" if (rows_removed >= 25000 or est_rows >= 50000) else "medium",
                "classification": "verified",
                "node_type": node_type,
                "relation": rel,
                "title": f"Large Sequential Scan on `{rel}` (rows_removed={rows_removed}, actual_rows={act_rows}, est_rows={est_rows})",
                "evidence": {
                    "relation": rel,
                    "filter": filter_cond,
                    "actual_rows": act_rows,
                    "rows_removed_by_filter": rows_removed,
                    "selectivity_pct": selectivity,
                    "shared_read_blocks": shared_read,
                },
                "likely_causes": [f"Missing B-Tree or partial index on `{rel}` for filter `{filter_cond}`"],
                "confidence": "high",
                "recommendation": f"Create a targeted index on `{rel}` covering columns in `{filter_cond}` using CREATE INDEX CONCURRENTLY."
            })

        if act_rows is not None and est_rows > 0:
            ratio = max(act_rows / est_rows, est_rows / max(1, act_rows))
            if ratio >= 10.0 and abs(act_rows - est_rows) >= 1000:
                findings.append({
                    "id": f"PLAN-EST-{idx:03d}",
                    "category": "cardinality_misestimate",
                    "severity": "medium",
                    "classification": "verified",
                    "node_type": node_type,
                    "relation": rel,
                    "title": f"Row estimation mismatch ({ratio:.1f}x) on `{node_type}` ({rel}): estimated {est_rows} vs actual {act_rows}",
                    "evidence": {"estimated_rows": est_rows, "actual_rows": act_rows, "ratio": round(ratio, 2)},
                    "likely_causes": ["Stale table statistics in pg_statistic or correlated multi-column predicates without extended statistics"],
                    "confidence": "high",
                    "recommendation": f"Run `ANALYZE {rel};` and consider `CREATE STATISTICS` for correlated columns on `{rel}`."
                })

        sort_space_type = n.get("Sort Space Type")
        hash_batches = n.get("Hash Batches", 1) or 1
        if sort_space_type == "Disk" or temp_written > 0 or hash_batches > 1:
            findings.append({
                "id": f"PLAN-SPILL-{idx:03d}",
                "category": "memory_spill",
                "severity": "high",
                "classification": "verified",
                "node_type": node_type,
                "relation": rel,
                "title": f"`{node_type}` spilled to disk (Sort Space Type={sort_space_type}, Temp Written Blocks={temp_written}, Hash Batches={hash_batches})",
                "evidence": {
                    "sort_method": n.get("Sort Method"),
                    "sort_space_type": sort_space_type,
                    "sort_space_used_kb": n.get("Sort Space Used"),
                    "temp_written_blocks": temp_written,
                    "hash_batches": hash_batches,
                },
                "likely_causes": ["Operation memory exceeded session work_mem setting"],
                "confidence": "high",
                "recommendation": "Provide an index matching the ORDER BY clause to eliminate the sort, or raise session `work_mem` for heavy reporting/hash-join queries."
            })

        if (node_type == "Nested Loop" and loops >= 500) or (act_rows is not None and loops >= 200 and (n.get("Actual Total Time") or 0) >= 50.0):
            findings.append({
                "id": f"PLAN-NL-{idx:03d}",
                "category": "join_amplification",
                "severity": "high",
                "classification": "verified",
                "node_type": node_type,
                "relation": rel,
                "title": f"Expensive Nested Loop join or inner scan executed across {loops} loops",
                "evidence": {"actual_loops": loops, "actual_total_time_ms": n.get("Actual Total Time")},
                "likely_causes": ["Planner underestimated outer row count and chose Nested Loop instead of Hash Join, or inner join key lacks an index"],
                "confidence": "high",
                "recommendation": "Verify inner join column is indexed and refresh statistics with `ANALYZE` so the planner selects a Hash Join when appropriate."
            })

    total_blocks = total_shared_hit_blocks + total_shared_read_blocks
    cache_hit_pct = round((total_shared_hit_blocks * 100.0 / total_blocks), 2) if total_blocks > 0 else 100.0
    exec_time_ms = root.get("Execution Time") or plan.get("Actual Total Time") or 0.0
    plan_time_ms = root.get("Planning Time") or 0.0

    status = "ok"
    if any(f["severity"] == "high" for f in findings):
        status = "warning" if exec_time_ms < 1000.0 else "critical"
    elif findings:
        status = "warning"
    else:
        findings.append({
            "id": "PLAN-OK-001",
            "category": "execution_plan",
            "severity": "info",
            "classification": "verified",
            "node_type": plan.get("Node Type", "Root"),
            "relation": "root",
            "title": "Execution plan uses efficient access paths with no spills or large sequential scans",
            "evidence": {"execution_time_ms": exec_time_ms, "buffer_cache_hit_pct": cache_hit_pct},
            "likely_causes": ["Appropriate indexing and fresh planner statistics"],
            "confidence": "high",
            "recommendation": "No execution plan changes needed."
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
            "planning_time_ms": plan_time_ms,
            "execution_time_ms": exec_time_ms,
            "total_cost": plan.get("Total Cost"),
            "node_count": len(nodes),
            "shared_hit_blocks": total_shared_hit_blocks,
            "shared_read_blocks": total_shared_read_blocks,
            "temp_written_blocks": total_temp_written_blocks,
            "buffer_cache_hit_pct": cache_hit_pct,
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    }


def analyze_explain_content(content: str) -> Dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return analyze_explain_json(json.loads(stripped))
    return analyze_explain_json(parse_text_explain_to_synthetic_json(stripped))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze PostgreSQL EXPLAIN JSON or text output.")
    parser.add_argument("--explain-file", required=True, help="Path to EXPLAIN JSON or text file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.explain_file)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"EXPLAIN file not found: {p}")), file=sys.stderr)
        return 1

    try:
        payload = analyze_explain_content(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        print(json.dumps(make_error_envelope(f"Invalid EXPLAIN input: {exc}")), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
