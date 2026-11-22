#!/usr/bin/env python3
"""Deterministic CPU, RAM, storage, and database capacity sizing engine with headroom and scaling thresholds."""
import argparse
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from requirements_validator import validate_requirements
from workload_calculator import calculate_workload


def size_infrastructure(constraints: Dict[str, Any]) -> Dict[str, Any]:
    val = validate_requirements(constraints)
    if val["status"] == "error":
        return val
    c = val["metrics"]["normalized_constraints"]
    wkl = calculate_workload(constraints)["metrics"]["baseline_1x"]

    peak_rps = wkl["peak_rps"]
    init_storage_gb = float(c["data_storage_gb"])
    monthly_growth_gb = float(c["monthly_data_growth_gb"])
    sla = float(c["availability_sla_pct"])

    # App tier sizing: ~250 RPS per vCPU for compiled/fast runtime with 40% headroom
    raw_app_vcpus = (peak_rps / 250.0) * 1.4
    app_vcpus = max(2, int(2 ** math.ceil(math.log2(max(2.0, raw_app_vcpus)))))
    app_ram_gib = max(4, app_vcpus * 2)

    # DB tier sizing: working set ~20% of 12-month dataset + connection memory
    year1_dataset_gb = init_storage_gb + (12.0 * monthly_growth_gb)
    # Account for 1.35x B-Tree index + WAL + dead-tuple headroom
    year1_provisioned_storage_gb = math.ceil(year1_dataset_gb * 1.35)
    working_set_gib = max(2.0, year1_dataset_gb * 0.20)
    # PostgreSQL shared_buffers is ~25-40% of DB RAM; total DB RAM = max(4, next power of 2 above working_set * 1.5)
    db_ram_gib = max(4, int(2 ** math.ceil(math.log2(max(4.0, working_set_gib * 1.5)))))
    db_vcpus = max(2, db_ram_gib // 4)

    ha_replicas = 2 if sla >= 99.95 else 1

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": [{
            "id": "SIZE-COMP-001",
            "category": "capacity_sizing",
            "severity": "info",
            "classification": "verified",
            "title": f"Sized application tier at {app_vcpus} vCPU / {app_ram_gib} GiB RAM and database tier at {db_vcpus} vCPU / {db_ram_gib} GiB RAM with {year1_provisioned_storage_gb} GB Year-1 NVMe storage",
            "evidence": {
                "app_vcpus": app_vcpus,
                "app_ram_gib": app_ram_gib,
                "db_vcpus": db_vcpus,
                "db_ram_gib": db_ram_gib,
                "year1_storage_gb": year1_provisioned_storage_gb,
            },
            "likely_causes": ["Deterministic working-set and headroom capacity formulas"],
            "confidence": "high",
            "recommendation": "Monitor CPU steal/utilization and PostgreSQL buffer cache hit ratio (>99% target) before vertical scaling."
        }],
        "metrics": {
            "capacity_disclaimer": "Theoretical deterministic engineering estimate; validate under load testing before production commitment.",
            "application_tier": {
                "recommended_vcpus": app_vcpus,
                "recommended_ram_gib": app_ram_gib,
                "ha_instances": ha_replicas,
                "headroom_pct": 40.0,
            },
            "database_tier": {
                "recommended_vcpus": db_vcpus,
                "recommended_ram_gib": db_ram_gib,
                "estimated_working_set_gib": round(working_set_gib, 2),
                "recommended_shared_buffers_gib": round(db_ram_gib * 0.25, 2),
                "initial_dataset_gb": init_storage_gb,
                "year1_dataset_gb": year1_dataset_gb,
                "year1_provisioned_nvme_gb": year1_provisioned_storage_gb,
                "standby_replicas": 1 if sla >= 99.95 else 0,
            },
            "scaling_thresholds": {
                "add_read_replica_or_cache_at_rps": round(peak_rps * 2.5, 0),
                "split_worker_node_at_cpu_pct": 70.0,
                "partition_tables_at_dataset_gb": 250,
            },
        },
        "warnings": ["Capacity numbers are engineering estimates, not guaranteed SLA benchmarks."],
        "recommendations": ["Configure automated daily backups + WAL archiving to object storage to satisfy RPO/RTO constraints."],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Size compute, memory, and database capacity.")
    parser.add_argument("--input", required=True, help="Path to constraints JSON file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.input)
    if not p.exists():
        print(json.dumps({"status": "error", "errors": [f"File not found: {p}"]}), file=sys.stderr)
        return 1

    payload = size_infrastructure(json.loads(p.read_text(encoding="utf-8")))
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
