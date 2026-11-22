#!/usr/bin/env python3
"""Validate 18 product and operational constraints and build an explicit Assumptions Register."""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REQUIRED_FIELDS_DEFAULTS: Dict[str, Tuple[Any, str]] = {
    "product_type": ("b2b_saas_api", "Assumed B2B SaaS web & API workload"),
    "product_complexity": ("medium", "Assumed medium domain complexity (CRUD + background jobs + webhooks)"),
    "expected_concurrent_users": (500, "Assumed 500 concurrent active users during business peak"),
    "expected_rps": (120, "Assumed 120 average requests/second (~10.3M requests/day)"),
    "read_write_ratio": ("80:20", "Assumed 80% read / 20% write OLTP ratio"),
    "api_traffic_pattern": ("diurnal_burst_3x", "Assumed 3x peak-to-average diurnal traffic ratio"),
    "data_storage_gb": (50, "Assumed 50 GB initial relational dataset"),
    "monthly_data_growth_gb": (10, "Assumed 10 GB/month dataset growth"),
    "p95_latency_ms": (150, "Assumed 150ms p95 HTTP API response latency target"),
    "availability_sla_pct": (99.9, "Assumed 99.9% uptime target (~43.8m/month error budget)"),
    "monthly_budget_usd": (150.0, "Assumed $150/month initial infrastructure budget"),
    "deployment_region": ("us-east-1", "Assumed US East primary deployment region"),
    "team_size": (2, "Assumed 2-person founding/product engineering team"),
    "team_experience": ("fullstack_typescript_go_postgres", "Assumed strong TypeScript/Go/PostgreSQL familiarity with limited dedicated SRE staff"),
    "maintenance_capacity": ("low_ops_overhead", "Assumed < 4 hours/week infrastructure maintenance capacity"),
    "compliance_requirements": (["soc2_ready_audit_logs"], "Assumed baseline encryption + audit log retention without HIPAA/PCI-DSS L1"),
    "rpo_minutes": (15, "Assumed 15-minute Recovery Point Objective via continuous WAL archiving"),
    "rto_minutes": (30, "Assumed 30-minute Recovery Time Objective via automated backup restore or standby promotion"),
}


def parse_rw_ratio(ratio_str: str) -> Tuple[float, float]:
    try:
        parts = str(ratio_str).split(":")
        r = float(parts[0])
        w = float(parts[1])
        total = max(1.0, r + w)
        return round(r / total, 2), round(w / total, 2)
    except Exception:
        return 0.8, 0.2


def validate_requirements(raw: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    assumptions_register: List[Dict[str, Any]] = []
    missing_questions: List[str] = []

    for field, (default_val, rationale) in REQUIRED_FIELDS_DEFAULTS.items():
        val = raw.get(field)
        if val is None or val == "" or val == "unknown":
            normalized[field] = default_val
            assumptions_register.append({
                "field": field,
                "assumed_value": default_val,
                "source": "default_assumption",
                "rationale": rationale,
            })
            missing_questions.append(f"What is your target `{field}`? (Defaulted to `{default_val}`: {rationale})")
        else:
            normalized[field] = val
            assumptions_register.append({
                "field": field,
                "assumed_value": val,
                "source": "user_provided",
                "rationale": "Explicitly provided in constraints specification.",
            })

    read_frac, write_frac = parse_rw_ratio(str(normalized["read_write_ratio"]))
    normalized["read_fraction"] = read_frac
    normalized["write_fraction"] = write_frac

    # Validate numeric bounds
    errors = []
    if float(normalized["expected_rps"]) <= 0:
        errors.append("expected_rps must be > 0")
    if float(normalized["monthly_budget_usd"]) <= 0:
        errors.append("monthly_budget_usd must be > 0")
    if int(normalized["team_size"]) <= 0:
        errors.append("team_size must be >= 1")

    if errors:
        return {
            "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": {"system": platform.system(), "release": platform.release()},
            "tool_versions": {"python": platform.python_version()},
            "findings": [],
            "metrics": {},
            "warnings": [],
            "recommendations": [],
            "errors": errors,
        }

    assumed_count = sum(1 for a in assumptions_register if a["source"] == "default_assumption")
    findings = [{
        "id": "REQ-VAL-001",
        "category": "requirements_validation",
        "severity": "info" if assumed_count == 0 else "low",
        "classification": "verified",
        "title": f"Validated 18 architecture constraints ({18 - assumed_count} user-provided, {assumed_count} explicit assumptions)",
        "evidence": {
            "user_provided_count": 18 - assumed_count,
            "assumed_count": assumed_count,
            "monthly_budget_usd": normalized["monthly_budget_usd"],
            "expected_rps": normalized["expected_rps"],
        },
        "likely_causes": ["Constraint ingestion and normalization"],
        "confidence": "high",
        "recommendation": "Review the Assumptions Register before finalizing production procurement."
    }]

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "normalized_constraints": normalized,
            "assumptions_register": assumptions_register,
            "clarification_questionnaire": missing_questions,
        },
        "warnings": [],
        "recommendations": ["Confirm any defaulted fields in clarification_questionnaire with stakeholders."],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate product and operational architecture constraints.")
    parser.add_argument("--input", required=True, help="Path to constraints JSON file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.input)
    if not p.exists():
        print(json.dumps({"status": "error", "errors": [f"Constraints file not found: {p}"]}), file=sys.stderr)
        return 1

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "error", "errors": [f"Malformed JSON: {exc}"]}), file=sys.stderr)
        return 2

    payload = validate_requirements(raw)
    if payload["status"] == "error":
        print(json.dumps(payload), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
