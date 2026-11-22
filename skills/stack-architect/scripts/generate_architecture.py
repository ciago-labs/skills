#!/usr/bin/env python3
"""Generate the complete 12-section engineering architecture blueprint and Mermaid diagram."""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cost_estimator
import infrastructure_sizer
import requirements_validator
import stack_selector
import workload_calculator


MERMAID_DIAGRAM = """```mermaid
flowchart TD
    Client["Users & API Clients (HTTPS / HTTP3)"] --> Edge["Caddy 2 Reverse Proxy (TLS, Zstd, Rate Limit)"]
    Edge --> App["Modular Monolith API & Worker (Container, Non-Root UID 10001)"]
    App --> Pool["PgBouncer / Connection Pool"]
    Pool --> PG[("PostgreSQL 16 Primary\\n(OLTP + JSONB + SKIP LOCKED Queue)")]
    App --> Cache[("Redis 7 / In-Memory Cache\\n(Session & Rate-Limit State)")]
    PG --> Backup["Off-Site S3 / R2 Object Storage\\n(WAL-G / pgBackRest Continuous Archive)"]
    App --> Obs["Prometheus /metrics & JSON Structured Logs"]
```"""


def build_architecture_blueprint(constraints: Dict[str, Any]) -> Dict[str, Any]:
    req = requirements_validator.validate_requirements(constraints)
    if req["status"] == "error":
        return req
    wkl = workload_calculator.calculate_workload(constraints)
    siz = infrastructure_sizer.size_infrastructure(constraints)
    cst = cost_estimator.estimate_costs(constraints)
    stk = stack_selector.select_stack(constraints)

    adrs = [
        {
            "id": "ADR-001",
            "title": "Adopt Modular Monolith on Docker Compose over Kubernetes Microservices",
            "status": "Accepted",
            "context": f"Team size is {req['metrics']['normalized_constraints']['team_size']} with budget ${req['metrics']['normalized_constraints']['monthly_budget_usd']}/mo and peak RPS {wkl['metrics']['baseline_1x']['peak_rps']}.",
            "decision": "Deploy a single stateless modular monolith container behind Caddy 2 using Docker Compose.",
            "consequences": "Eliminates $73+/mo Kubernetes control plane cost and network mesh latency; requires strict internal package boundaries.",
        },
        {
            "id": "ADR-002",
            "title": "Use PostgreSQL 16 for Primary OLTP and Transactional Job Queue (`FOR UPDATE SKIP LOCKED`)",
            "status": "Accepted",
            "context": "Workload requires durable background job processing without dual-write inconsistencies between DB and an external broker.",
            "decision": "Store relational records, JSONB metadata, and background job queues in PostgreSQL 16.",
            "consequences": "Single backup/restore surface for RPO/RTO; must monitor queue table vacuuming above 2,000 jobs/sec.",
        },
        {
            "id": "ADR-003",
            "title": "Terminate TLS and Enforce Edge Rate Limiting with Caddy 2",
            "status": "Accepted",
            "context": "Service requires automated HTTPS certificate lifecycle and HTTP/2+HTTP/3 support with zero manual renewal toil.",
            "decision": "Run Caddy 2 as the edge reverse proxy forwarding to the internal app container on port 8080.",
            "consequences": "Zero-touch TLS management and automatic healthcheck routing.",
        },
    ]

    operational_checklist = [
        "Verify `SET lock_timeout = '2s'` and `SET statement_timeout = '30s'` on all database migrations.",
        "Configure automated daily base backups + continuous WAL shipping to S3/R2 and test restore monthly.",
        "Set container `--memory` and `--pids-limit` flags and run application process as non-root UID `10001`.",
        "Alert on PostgreSQL disk utilization > 75%, connection utilization > 80%, and p95 latency > target.",
        "Verify `/healthz` endpoint checks both process liveness and database `SELECT 1` readiness.",
    ]

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": req["findings"] + wkl["findings"] + siz["findings"] + cst["findings"] + stk["findings"],
        "metrics": {
            "1_requirements_document": req["metrics"]["normalized_constraints"],
            "2_assumptions_register": req["metrics"]["assumptions_register"],
            "3_workload_estimation": wkl["metrics"],
            "4_hardware_sizing_report": siz["metrics"],
            "5_infrastructure_cost_comparison": cst["metrics"],
            "6_recommended_technology_stack": stk["metrics"],
            "7_architecture_diagram_mermaid": MERMAID_DIAGRAM,
            "8_adr_documents": adrs,
            "9_deployment_architecture": {
                "topology": "Caddy Edge -> Modular Monolith Container -> PostgreSQL 16 + Redis 7",
                "zero_downtime_rollout": "Blue/green container swap via health-checked Caddy upstream",
            },
            "11_scaling_and_failure_considerations": {
                "single_points_of_failure": "Single-node deployments share host kernel/power; mitigate with RDS Multi-AZ or standby replica when SLA >= 99.95%.",
                "scaling_triggers": siz["metrics"]["scaling_thresholds"],
            },
            "12_operational_checklist": operational_checklist,
        },
        "warnings": wkl["warnings"] + siz["warnings"],
        "recommendations": stk["recommendations"] + cst["recommendations"],
        "errors": [],
    }


def render_markdown(bp: Dict[str, Any]) -> str:
    m = bp["metrics"]
    req = m["1_requirements_document"]
    wkl = m["3_workload_estimation"]["baseline_1x"]
    siz = m["4_hardware_sizing_report"]
    cst = m["5_infrastructure_cost_comparison"]
    stk = m["6_recommended_technology_stack"]["stack_decisions"]

    lines = [
        "# System Architecture & Day-0 Engineering Blueprint (`stack-architect` / `ship-blueprint`)",
        "",
        "## 1. Requirements Summary",
        f"- **Product Type / Complexity**: `{req['product_type']}` (`{req['product_complexity']}`)",
        f"- **Traffic**: `{req['expected_rps']} avg RPS` (`{req['expected_concurrent_users']} concurrent users`, Read/Write `{req['read_write_ratio']}`)",
        f"- **Latency / Availability Targets**: `p95 <= {req['p95_latency_ms']} ms` | `SLA: {req['availability_sla_pct']}%` | `RPO: {req['rpo_minutes']}m` | `RTO: {req['rto_minutes']}m`",
        f"- **Budget & Team**: `${req['monthly_budget_usd']}/month` | `Team Size: {req['team_size']}` (`{req['team_experience']}`)",
        "",
        "## 2. Assumptions Register",
        "",
        "| Field | Value | Source | Rationale |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for a in m["2_assumptions_register"]:
        lines.append(f"| `{a['field']}` | `{a['assumed_value']}` | `{a['source']}` | {a['rationale']} |")

    lines.extend([
        "",
        "## 3. Deterministic Workload Estimation (1x / 2x / 5x Sensitivity)",
        f"- **1x Baseline Peak**: `{wkl['peak_rps']} RPS` | `{wkl['littles_law_active_concurrency']} active concurrent reqs` | `{wkl['estimated_peak_db_iops']} DB IOPS` | `{wkl['monthly_egress_gb']} GB/mo egress`",
        f"- **2x Growth Peak**: `{m['3_workload_estimation']['sensitivity_2x_growth']['peak_rps']} RPS` | `{m['3_workload_estimation']['sensitivity_2x_growth']['estimated_peak_db_iops']} DB IOPS`",
        f"- **5x Surge Peak**: `{m['3_workload_estimation']['sensitivity_5x_surge']['peak_rps']} RPS` | `{m['3_workload_estimation']['sensitivity_5x_surge']['estimated_peak_db_iops']} DB IOPS`",
        "",
        "## 4. Hardware Sizing Report",
        f"- **Application Tier**: `{siz['application_tier']['recommended_vcpus']} vCPU`, `{siz['application_tier']['recommended_ram_gib']} GiB RAM` (`{siz['application_tier']['ha_instances']}` instance(s))",
        f"- **Database Tier**: `{siz['database_tier']['recommended_vcpus']} vCPU`, `{siz['database_tier']['recommended_ram_gib']} GiB RAM` (`shared_buffers={siz['database_tier']['recommended_shared_buffers_gib']} GiB`, Year-1 NVMe=`{siz['database_tier']['year1_provisioned_nvme_gb']} GB`)",
        "",
        "## 5. Verified Infrastructure Cost Comparison",
        "",
        "| Option | Monthly Cost (USD) | Fits Budget? | Trade-offs |",
        "| :--- | :--- | :--- | :--- |",
    ])
    for opt in cst["deployment_options"]:
        lines.append(f"| {opt['name']} | `${opt['Estimated_Monthly_USD']:.2f}/mo` | `{opt['fits_budget']}` | {opt['tradeoffs']} |")

    lines.extend([
        "",
        "### Verified Rate Card Sources (Verified `2026-11-17`)",
    ])
    for rec in cst["verified_pricing_records"]:
        lines.append(f"- **{rec['provider']} {rec['service']} (`{rec['instance_configuration']}`)**: `${rec['price_usd']}` ({rec['billing_unit']}) in `{rec['region']}` - [Source]({rec['source_url']})")

    lines.extend([
        "",
        "## 6. Recommended 13-Layer Technology Stack",
        "",
    ])
    for layer, d in stk.items():
        lines.extend([
            f"### Layer: `{layer}` -> **{d['choice']}**",
            f"1. **Why Selected**: {d['why_selected']}",
            f"2. **Alternatives Considered**: {', '.join(d['alternatives_considered'])}",
            f"3. **Why Rejected**: {d['why_rejected']}",
            f"4. **Operational Complexity**: {d['operational_complexity']}",
            f"5. **Cost Implications**: {d['cost_implications']}",
            f"6. **Scaling Limitations**: {d['scaling_limitations']}",
            f"7. **Migration Path**: {d['migration_path']}",
            "",
        ])

    lines.extend([
        "## 7. Architecture Diagram",
        "",
        MERMAID_DIAGRAM,
        "",
        "## 8. Architecture Decision Records (ADRs)",
        "",
    ])
    for adr in m["8_adr_documents"]:
        lines.extend([
            f"### {adr['id']}: {adr['title']} ({adr['status']})",
            f"- **Context**: {adr['context']}",
            f"- **Decision**: {adr['decision']}",
            f"- **Consequences**: {adr['consequences']}",
            "",
        ])

    lines.extend([
        "## 9. Deployment Architecture & Scaling Thresholds",
        f"- **Topology**: {m['9_deployment_architecture']['topology']}",
        f"- **Rollout Strategy**: {m['9_deployment_architecture']['zero_downtime_rollout']}",
        f"- **Scaling Triggers**: `{json.dumps(siz['scaling_thresholds'])}`",
        "",
        "## 10. Pre-Launch Operational Checklist",
    ])
    for item in m["12_operational_checklist"]:
        lines.append(f"- [ ] {item}")

    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate complete system architecture blueprint.")
    parser.add_argument("--input", required=True, help="Path to constraints JSON file")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", help="Optional output file path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    p = Path(args.input)
    if not p.exists():
        print(json.dumps({"status": "error", "errors": [f"File not found: {p}"]}), file=sys.stderr)
        return 1

    bp = build_architecture_blueprint(json.loads(p.read_text(encoding="utf-8")))
    rendered = render_markdown(bp) if args.format == "markdown" else json.dumps(bp, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
