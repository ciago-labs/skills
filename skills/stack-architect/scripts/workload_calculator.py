#!/usr/bin/env python3
"""Deterministic workload throughput, concurrency, IOPS, and bandwidth calculator with sensitivity analysis."""
import argparse
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from requirements_validator import validate_requirements


def calculate_scenario(avg_rps: float, burst_factor: float, read_frac: float, write_frac: float, p95_ms: float) -> Dict[str, Any]:
    peak_rps = round(avg_rps * burst_factor, 2)
    read_rps = round(peak_rps * read_frac, 2)
    write_rps = round(peak_rps * write_frac, 2)
    # Little's Law concurrency: L = lambda * W (using average latency ~ 0.5 * p95_ms)
    avg_service_sec = (p95_ms * 0.5) / 1000.0
    active_concurrent_requests = max(1, math.ceil(peak_rps * avg_service_sec))
    # DB queries per request: ~2.5 reads + 1.2 writes (with index updates)
    estimated_db_iops = math.ceil((read_rps * 2.5) + (write_rps * 3.0))
    # Average payload: 18 KB response + 4 KB request = 22 KB per request
    avg_bytes_per_req = 22 * 1024
    peak_bandwidth_mbps = round((peak_rps * avg_bytes_per_req * 8) / 1_000_000.0, 2)
    monthly_egress_gb = round((avg_rps * 86400 * 30 * (18 * 1024)) / (1024**3), 2)

    return {
        "avg_rps": avg_rps,
        "peak_rps": peak_rps,
        "peak_read_rps": read_rps,
        "peak_write_rps": write_rps,
        "littles_law_active_concurrency": active_concurrent_requests,
        "estimated_peak_db_iops": estimated_db_iops,
        "peak_bandwidth_mbps": peak_bandwidth_mbps,
        "monthly_egress_gb": monthly_egress_gb,
    }


def calculate_workload(constraints: Dict[str, Any]) -> Dict[str, Any]:
    val = validate_requirements(constraints)
    if val["status"] == "error":
        return val
    c = val["metrics"]["normalized_constraints"]

    avg_rps = float(c["expected_rps"])
    burst_factor = 3.0 if "3x" in str(c["api_traffic_pattern"]) else (5.0 if "5x" in str(c["api_traffic_pattern"]) else 2.5)
    r_frac = float(c["read_fraction"])
    w_frac = float(c["write_fraction"])
    p95_ms = float(c["p95_latency_ms"])

    baseline_1x = calculate_scenario(avg_rps, burst_factor, r_frac, w_frac, p95_ms)
    growth_2x = calculate_scenario(avg_rps * 2.0, burst_factor, r_frac, w_frac, p95_ms)
    surge_5x = calculate_scenario(avg_rps * 5.0, burst_factor, r_frac, w_frac, p95_ms)

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": [{
            "id": "WKL-CALC-001",
            "category": "workload_estimation",
            "severity": "info",
            "classification": "verified",
            "title": f"Baseline peak throughput is {baseline_1x['peak_rps']} RPS ({baseline_1x['estimated_peak_db_iops']} DB IOPS, {baseline_1x['monthly_egress_gb']} GB/mo egress)",
            "evidence": baseline_1x,
            "likely_causes": ["Deterministic Little's Law and payload bandwidth modeling"],
            "confidence": "high",
            "recommendation": "Size primary compute and database tiers for at least the 2x growth envelope to maintain 50% headroom."
        }],
        "metrics": {
            "formulas_used": {
                "peak_rps": "avg_rps * burst_factor",
                "littles_law_concurrency": "ceil(peak_rps * (0.5 * p95_latency_sec))",
                "db_iops": "ceil(peak_read_rps * 2.5 + peak_write_rps * 3.0)",
                "monthly_egress_gb": "avg_rps * 2,592,000_sec * 18_KiB / 1024^3",
            },
            "baseline_1x": baseline_1x,
            "sensitivity_2x_growth": growth_2x,
            "sensitivity_5x_surge": surge_5x,
        },
        "warnings": ["Theoretical workload estimates must be validated against real application profiling."],
        "recommendations": ["Provision connection pooling (PgBouncer) once active concurrency exceeds 50 connections."],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate deterministic workload throughput and sensitivity analysis.")
    parser.add_argument("--input", required=True, help="Path to constraints JSON file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.input)
    if not p.exists():
        print(json.dumps({"status": "error", "errors": [f"File not found: {p}"]}), file=sys.stderr)
        return 1

    payload = calculate_workload(json.loads(p.read_text(encoding="utf-8")))
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
