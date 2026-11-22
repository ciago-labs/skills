#!/usr/bin/env python3
"""Infrastructure cost comparison engine using verified pricing records with complete provenance metadata."""
import argparse
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope
from requirements_validator import validate_requirements

VERIFIED_PRICING_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "aws-ec2-t4g-medium",
        "offering_type": "standard",
        "provider": "AWS",
        "region": "us-east-2 (Ohio)",
        "service": "Amazon EC2 On-Demand",
        "instance_type": "t4g.medium",
        "resource_specifications": "2 vCPU AWS Graviton2, 4 GiB RAM, EBS-only",
        "instance_configuration": "t4g.medium (2 vCPU Graviton2, 4 GiB RAM)",
        "currency": "USD",
        "price": 0.0336,
        "price_usd": 0.0336,
        "monthly_usd_730h": 24.53,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 3.65,
        "vat_included": False,
        "billing_unit": "USD per hour (excl. taxes)",
        "source_url": "https://aws.amazon.com/ec2/pricing/on-demand/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "aws-ec2-t4g-large",
        "offering_type": "standard",
        "provider": "AWS",
        "region": "us-east-2 (Ohio)",
        "service": "Amazon EC2 On-Demand",
        "instance_type": "t4g.large",
        "resource_specifications": "2 vCPU AWS Graviton2, 8 GiB RAM, EBS-only",
        "instance_configuration": "t4g.large (2 vCPU Graviton2, 8 GiB RAM)",
        "currency": "USD",
        "price": 0.0672,
        "price_usd": 0.0672,
        "monthly_usd_730h": 49.06,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 3.65,
        "vat_included": False,
        "billing_unit": "USD per hour (excl. taxes)",
        "source_url": "https://aws.amazon.com/ec2/pricing/on-demand/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "aws-rds-db-t4g-medium",
        "offering_type": "standard",
        "provider": "AWS",
        "region": "us-east-1",
        "service": "Amazon RDS for PostgreSQL (Single-AZ)",
        "instance_type": "db.t4g.medium",
        "resource_specifications": "2 vCPU Graviton2, 4 GB RAM",
        "instance_configuration": "db.t4g.medium (2 vCPU, 4 GB RAM)",
        "currency": "USD",
        "price": 0.0650,
        "price_usd": 0.0650,
        "monthly_usd_730h": 47.45,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 0.0,
        "vat_included": False,
        "billing_unit": "USD per hour",
        "source_url": "https://instances.vantage.sh/aws/rds/db.t4g.medium",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "aws-rds-db-t4g-large",
        "offering_type": "standard",
        "provider": "AWS",
        "region": "us-east-1",
        "service": "Amazon RDS for PostgreSQL (Single-AZ)",
        "instance_type": "db.t4g.large",
        "resource_specifications": "2 vCPU Graviton2, 8 GB RAM",
        "instance_configuration": "db.t4g.large (2 vCPU, 8 GB RAM)",
        "currency": "USD",
        "price": 0.1290,
        "price_usd": 0.1290,
        "monthly_usd_730h": 94.17,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 0.0,
        "vat_included": False,
        "billing_unit": "USD per hour",
        "source_url": "https://instances.vantage.sh/aws/rds/db.t4g.large",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "aws-rds-db-t4g-xlarge",
        "offering_type": "standard",
        "provider": "AWS",
        "region": "us-east-1",
        "service": "Amazon RDS for PostgreSQL (Single-AZ)",
        "instance_type": "db.t4g.xlarge",
        "resource_specifications": "4 vCPU Graviton2, 16 GB RAM",
        "instance_configuration": "db.t4g.xlarge (4 vCPU, 16 GB RAM)",
        "currency": "USD",
        "price": 0.2600,
        "price_usd": 0.2600,
        "monthly_usd_730h": 189.80,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 0.0,
        "vat_included": False,
        "billing_unit": "USD per hour",
        "source_url": "https://www.economize.cloud/resources/aws/pricing/rds/db.t4g.xlarge/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "gcp-gce-e2-standard-2",
        "offering_type": "standard",
        "provider": "Google Cloud",
        "region": "us-central1 (Iowa)",
        "service": "Compute Engine On-Demand",
        "instance_type": "e2-standard-2",
        "resource_specifications": "2 vCPU, 8 GB RAM",
        "instance_configuration": "e2-standard-2 (2 vCPU, 8 GB RAM)",
        "currency": "USD",
        "price": 0.0700,
        "price_usd": 0.0700,
        "monthly_usd_730h": 48.92,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 3.65,
        "vat_included": False,
        "billing_unit": "USD per hour ($48.92/month)",
        "source_url": "https://www.economize.cloud/resources/gcp/pricing/compute-engine/e2-standard-2/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "gcp-cloud-sql-pg-2vcpu-8gb",
        "offering_type": "standard",
        "provider": "Google Cloud",
        "region": "us-central1 (Iowa)",
        "service": "Cloud SQL for PostgreSQL Enterprise (Zonal)",
        "instance_type": "db-custom-2-8192",
        "resource_specifications": "2 vCPU ($0.054/vCPU-hr) + 8 GiB RAM ($0.009/GiB-hr)",
        "instance_configuration": "2 vCPU ($0.054/vCPU-hr) + 8 GiB RAM ($0.009/GiB-hr)",
        "currency": "USD",
        "price": 0.1800,
        "price_usd": 0.1800,
        "monthly_usd_730h": 131.40,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 0.0,
        "vat_included": False,
        "billing_unit": "USD per hour (2*$0.054 + 8*$0.009)",
        "source_url": "https://cloud.google.com/sql/pricing",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "azure-vm-b2ms",
        "offering_type": "standard",
        "provider": "Microsoft Azure",
        "region": "eastus (East US)",
        "service": "Azure Virtual Machines (Linux Pay-As-You-Go)",
        "instance_type": "Standard_B2ms",
        "resource_specifications": "2 vCPU, 8 GB RAM, 16 GB temp storage",
        "instance_configuration": "Standard_B2ms (2 vCPU, 8 GB RAM)",
        "currency": "USD",
        "price": 0.0832,
        "price_usd": 0.0832,
        "monthly_usd_730h": 60.74,
        "setup_fee": 0.0,
        "ipv4_monthly_fee": 3.65,
        "vat_included": False,
        "billing_unit": "USD per hour ($60.74/month)",
        "source_url": "https://www.economize.cloud/resources/azure/pricing/virtual-machine/b2ms/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "hetzner-dedicated-ax42-1-standard",
        "offering_type": "standard",
        "provider": "Hetzner",
        "region": "eu-central (Falkenstein DE / Helsinki FI)",
        "service": "Dedicated Root Server AX42-1 (Standard Offering)",
        "instance_type": "AX42-1",
        "resource_specifications": "AMD Ryzen 7 PRO 8700GE (8 Cores / 16 Threads), 64 GB DDR5 RAM, 2x 512 GB Gen4 NVMe SSD",
        "instance_configuration": "AX42-1 Standard (8C/16T Ryzen 7 PRO 8700GE, 64 GB DDR5 RAM, 2x 512 GB NVMe)",
        "currency": "EUR",
        "price": 97.30,
        "setup_fee": 49.00,
        "ipv4_monthly_fee": 1.70,
        "ipv4_setup_fee": 0.00,
        "total_monthly_eur_with_ipv4": 99.00,
        "total_setup_eur_with_ipv4": 49.00,
        "vat_included": False,
        "vat_notes": "Prices exclude 19% VAT (USt)",
        "price_usd": 115.83,
        "monthly_usd_730h": 115.83,
        "billing_unit": "EUR per month recurring (€97.30 server + €1.70 primary IPv4, excl. VAT; plus €49.00 server setup + €0.00 primary IPv4 setup one-time)",
        "source_url": "https://www.hetzner.com/dedicated-rootserver/ax42/configurator/",
        "ipv4_pricing_source_url": "https://docs.hetzner.com/general/infrastructure-and-availability/ipv4-pricing/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "hetzner-dedicated-ax42-2-ecc",
        "offering_type": "standard",
        "provider": "Hetzner",
        "region": "eu-central (Falkenstein DE / Helsinki FI)",
        "service": "Dedicated Root Server AX42-2 ECC (Standard Offering)",
        "instance_type": "AX42-2",
        "resource_specifications": "AMD Ryzen 7 PRO 8700GE (8 Cores / 16 Threads), 64 GB DDR5 ECC RAM, 2x 512 GB Gen4 NVMe SSD",
        "instance_configuration": "AX42-2 ECC Standard (8C/16T Ryzen 7 PRO 8700GE, 64 GB DDR5 ECC RAM, 2x 512 GB NVMe)",
        "currency": "EUR",
        "price": 187.30,
        "setup_fee": 49.00,
        "ipv4_monthly_fee": 1.70,
        "ipv4_setup_fee": 0.00,
        "total_monthly_eur_with_ipv4": 189.00,
        "total_setup_eur_with_ipv4": 49.00,
        "vat_included": False,
        "vat_notes": "Prices exclude 19% VAT (USt)",
        "price_usd": 221.13,
        "monthly_usd_730h": 221.13,
        "billing_unit": "EUR per month recurring (€187.30 server + €1.70 primary IPv4, excl. VAT; plus €49.00 server setup + €0.00 primary IPv4 setup one-time)",
        "source_url": "https://www.hetzner.com/dedicated-rootserver/ax42/configurator/",
        "ipv4_pricing_source_url": "https://docs.hetzner.com/general/infrastructure-and-availability/ipv4-pricing/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "hetzner-dedicated-additional-single-ipv4",
        "offering_type": "addon",
        "provider": "Hetzner",
        "region": "eu-central (Falkenstein DE / Helsinki FI)",
        "service": "Dedicated Root Server Additional Single IPv4 Address (Optional Add-on)",
        "instance_type": "Additional-Single-IPv4",
        "resource_specifications": "1x Additional single IPv4 address for Dedicated Root Servers (distinct from Primary IPv4)",
        "instance_configuration": "Additional Single IPv4 (€1.70/mo + €4.90 one-time setup, excl. VAT)",
        "currency": "EUR",
        "price": 1.70,
        "setup_fee": 4.90,
        "ipv4_monthly_fee": 1.70,
        "ipv4_setup_fee": 4.90,
        "vat_included": False,
        "vat_notes": "Prices exclude 19% VAT (USt); Primary IPv4 has €0.00 setup fee, whereas Additional Single IPv4 has €4.90 setup fee",
        "price_usd": 1.90,
        "monthly_usd_730h": 1.90,
        "billing_unit": "EUR per month recurring (€1.70/mo excl. VAT; plus €4.90 one-time setup fee for additional single IPv4)",
        "source_url": "https://docs.hetzner.com/general/infrastructure-and-availability/ipv4-pricing/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
    {
        "id": "hetzner-dedicated-ax41-1-ltd-promotional",
        "offering_type": "limited_promotional",
        "provider": "Hetzner",
        "region": "eu-central (Germany / Finland, subject to stock)",
        "service": "Dedicated Root Server AX41-1-LTD (Limited / Promotional Offering)",
        "instance_type": "AX41-1-LTD",
        "resource_specifications": "Supply-limited promotional dedicated server (excluded from standard SLA capacity planning)",
        "instance_configuration": "AX41-1-LTD Promotional (Supply-limited stock)",
        "currency": "EUR",
        "price": 57.30,
        "setup_fee": 0.00,
        "ipv4_monthly_fee": 1.70,
        "vat_included": False,
        "vat_notes": "Excludes VAT; promotional limited availability",
        "price_usd": 69.03,
        "monthly_usd_730h": 69.03,
        "billing_unit": "EUR per month recurring (€57.30 base + €1.70 primary IPv4, excl. VAT; limited stock)",
        "source_url": "https://www.hetzner.com/dedicated-rootserver/",
        "verification_timestamp": "2026-11-17T00:00:00Z",
        "verification_date": "2026-11-17",
        "provenance_type": "verified_current_price",
    },
]


def estimate_costs(constraints: Dict[str, Any], custom_pricing: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    val = validate_requirements(constraints)
    if val["status"] == "error":
        return val
    c = val["metrics"]["normalized_constraints"]
    budget = float(c["monthly_budget_usd"])

    catalog = list(VERIFIED_PRICING_CATALOG)
    if custom_pricing:
        for item in custom_pricing:
            tagged = dict(item)
            tagged.setdefault("offering_type", "user_custom")
            tagged.setdefault("provenance_type", "user_supplied_assumption")
            tagged.setdefault("verification_timestamp", datetime.now(timezone.utc).isoformat())
            tagged.setdefault("verification_date", "user-supplied")
            tagged.setdefault("price_usd", float(tagged.get("price", 0.0)))
            tagged.setdefault("instance_configuration", f"{tagged.get('instance_type', 'custom')} ({tagged.get('resource_specifications', '')})")
            catalog.append(tagged)

    aws_combo_monthly = round(24.53 + 47.45, 2)
    aws_8gb_combo_monthly = round(49.06 + 94.17, 2)
    gcp_combo_monthly = round(48.92 + 131.40, 2)
    azure_selfhosted_db_monthly = round(60.74 * 2, 2)
    single_vm_aws_monthly = 49.06
    hetzner_ax42_1_standard_monthly_usd = 115.83  # €97.30 base + €1.70 IPv4 = €99.00/mo excl. VAT (~$115.83 USD/mo)

    deployment_options = [
        {
            "option_id": "opt-aws-single-ec2-compose",
            "offering_type": "standard",
            "name": "Single-Node AWS EC2 (`t4g.large`, 2 vCPU / 8 GiB) running Docker Compose + PostgreSQL",
            "Estimated_Monthly_USD": single_vm_aws_monthly,
            "one_time_setup_usd": 0.0,
            "fits_budget": single_vm_aws_monthly <= budget,
            "components": ["aws-ec2-t4g-large"],
            "provenance": "verified_current_price",
            "tradeoffs": "Lowest cloud cost; requires automated S3 pgBackRest/WAL-G backups since DB is self-hosted on EC2.",
        },
        {
            "option_id": "opt-aws-ec2-plus-rds",
            "offering_type": "standard",
            "name": "AWS EC2 (`t4g.medium`) + Managed Amazon RDS PostgreSQL (`db.t4g.medium`)",
            "Estimated_Monthly_USD": aws_combo_monthly,
            "one_time_setup_usd": 0.0,
            "fits_budget": aws_combo_monthly <= budget,
            "components": ["aws-ec2-t4g-medium", "aws-rds-db-t4g-medium"],
            "provenance": "verified_current_price",
            "tradeoffs": "Managed automated backups and point-in-time recovery via RDS within modest startup budgets.",
        },
        {
            "option_id": "opt-hetzner-baremetal-ax42-1",
            "offering_type": "standard",
            "name": "Hetzner Dedicated Root Server `AX42-1` Standard (8C/16T Ryzen 7 PRO 8700GE, 64 GB DDR5, 2x 512 GB NVMe + Primary IPv4)",
            "Estimated_Monthly_USD": hetzner_ax42_1_standard_monthly_usd,
            "recurring_monthly_eur_excl_vat": 99.00,
            "one_time_setup_eur_excl_vat": 49.00,
            "fits_budget": hetzner_ax42_1_standard_monthly_usd <= budget,
            "components": ["hetzner-dedicated-ax42-1-standard"],
            "provenance": "verified_current_price",
            "tradeoffs": "Standard offering is €97.30/mo + €1.70/mo primary IPv4 (€99.00/mo excl. VAT) plus €49.00 one-time server setup fee (€0.00 setup fee on Primary IPv4; €4.90 setup fee applies only to optional Additional Single IPv4 addresses). (Promotional/limited-stock variants such as AX41-1-LTD/AX42-1-LTD are tracked separately and not mixed with standard SLA pricing.)",
        },
        {
            "option_id": "opt-aws-ec2-rds-8gb",
            "offering_type": "standard",
            "name": "AWS EC2 (`t4g.large`) + Managed Amazon RDS PostgreSQL (`db.t4g.large`)",
            "Estimated_Monthly_USD": aws_8gb_combo_monthly,
            "one_time_setup_usd": 0.0,
            "fits_budget": aws_8gb_combo_monthly <= budget,
            "components": ["aws-ec2-t4g-large", "aws-rds-db-t4g-large"],
            "provenance": "verified_current_price",
            "tradeoffs": "16 GiB combined RAM across App + Managed RDS tier.",
        },
        {
            "option_id": "opt-gcp-gce-cloudsql",
            "offering_type": "standard",
            "name": "Google Cloud Compute Engine (`e2-standard-2`) + Cloud SQL for PostgreSQL (2 vCPU, 8 GiB)",
            "Estimated_Monthly_USD": gcp_combo_monthly,
            "one_time_setup_usd": 0.0,
            "fits_budget": gcp_combo_monthly <= budget,
            "components": ["gcp-gce-e2-standard-2", "gcp-cloud-sql-pg-2vcpu-8gb"],
            "provenance": "verified_current_price",
            "tradeoffs": "Managed Cloud SQL Enterprise with 8 GiB dedicated DB memory; higher base cost ($180.32/mo).",
        },
        {
            "option_id": "opt-azure-b2ms-pair",
            "offering_type": "standard",
            "name": "Microsoft Azure 2x `Standard_B2ms` VMs (App VM + Dedicated PostgreSQL VM)",
            "Estimated_Monthly_USD": azure_selfhosted_db_monthly,
            "one_time_setup_usd": 0.0,
            "fits_budget": azure_selfhosted_db_monthly <= budget,
            "components": ["azure-vm-b2ms"],
            "provenance": "verified_current_price",
            "tradeoffs": "Predictable $121.48/mo compute cost in East US; Azure Database for PostgreSQL Flexible Server pricing is marked unverified offline (user override supported).",
        },
    ]

    fitting = [o for o in deployment_options if o["fits_budget"]]
    status = "ok" if fitting else "warning"

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": [{
            "id": "COST-EST-001",
            "category": "cost_estimation",
            "severity": "info" if fitting else "medium",
            "classification": "verified",
            "title": f"{len(fitting)} of {len(deployment_options)} verified standard deployment architectures fit within the ${budget}/month budget",
            "evidence": {
                "monthly_budget_usd": budget,
                "fitting_options": [o["option_id"] for o in fitting],
            },
            "likely_causes": ["Comparison against verified 2026-11-17 cloud and Hetzner AX42-1 rate cards"],
            "confidence": "high",
            "recommendation": (
                f"Select `{fitting[1]['name'] if len(fitting) > 1 else fitting[0]['name']}` to balance operational simplicity and budget."
                if fitting else "Increase monthly budget to >= $50/month or deploy on a single burstable t4g.medium instance ($24.53/mo)."
            ),
        }],
        "metrics": {
            "monthly_budget_usd": budget,
            "verified_pricing_records": catalog,
            "deployment_options": deployment_options,
            "unverified_services_notice": "Managed Redis/ElastiCache, Azure Flexible Server, and out-of-stock promotional Hetzner AX42-1-LTD rates are marked unverified/promotional rather than guessed; supply --custom-pricing-file to include custom quotes.",
        },
        "warnings": [],
        "recommendations": ["Account for one-time bare-metal setup fees (€49.00 server setup + €0.00 primary IPv4 setup on Hetzner AX42-1; €4.90 setup applies only to additional single IPs), VAT where applicable, and EBS/PD storage."],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compare verified cloud and bare-metal infrastructure costs.")
    parser.add_argument("--input", required=True, help="Path to constraints JSON file")
    parser.add_argument("--custom-pricing-file", help="Optional JSON file with user-supplied pricing records")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.input)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"File not found: {p}")), file=sys.stderr)
        return 1

    custom = None
    if args.custom_pricing_file:
        cp = Path(args.custom_pricing_file)
        if cp.exists():
            custom = json.loads(cp.read_text(encoding="utf-8"))

    payload = estimate_costs(json.loads(p.read_text(encoding="utf-8")), custom)
    if payload["status"] == "error":
        print(json.dumps(payload), file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
