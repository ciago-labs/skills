#!/usr/bin/env python3
"""Constraint-driven 13-layer technology stack compiler with structured architecture configuration object."""
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


def determine_primary_runtime(exp: str, rps: float) -> str:
    """Select primary backend runtime ('go', 'rust', 'nodejs', or 'python') from team experience and workload."""
    tokens = [t.strip() for t in exp.lower().replace(",", "_").replace(" ", "_").split("_") if t.strip()]
    for tok in tokens:
        if tok in ("go", "golang"):
            return "go"
        if tok in ("rust", "cargo", "axum", "tokio"):
            return "rust"
        if tok in ("node", "nodejs", "typescript", "ts", "javascript", "js", "bun", "fastify"):
            return "nodejs"
        if tok in ("python", "py", "fastapi", "django", "flask"):
            return "python"
    if "rust" in exp.lower():
        return "rust"
    if "python" in exp.lower():
        return "python"
    if "node" in exp.lower() or "typescript" in exp.lower():
        return "nodejs"
    return "go"


RUNTIME_PROFILES = {
    "go": {
        "runtime_label": "Go 1.23 (compiled static binary)",
        "backend_framework": "Go net/http + chi router + sqlc",
        "healthcheck_cmd": ["/app/server", "--healthcheck"],
        "entrypoint": ["/app/server"],
    },
    "rust": {
        "runtime_label": "Rust 1.82 (compiled release binary)",
        "backend_framework": "Axum + Tokio + SQLx",
        "healthcheck_cmd": ["/usr/local/bin/app", "--healthcheck"],
        "entrypoint": ["/usr/local/bin/app"],
    },
    "nodejs": {
        "runtime_label": "Node.js 22 LTS (TypeScript / ES2023)",
        "backend_framework": "Fastify / Hono + Drizzle ORM",
        "healthcheck_cmd": ["node", "-e", "require('http').get({host:'127.0.0.1',port:8080,path:'/healthz'},r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"],
        "entrypoint": ["node", "src/server.js"],
    },
    "python": {
        "runtime_label": "Python 3.12 (slim container runtime)",
        "backend_framework": "FastAPI / Uvicorn + SQLAlchemy 2.0",
        "healthcheck_cmd": ["python3", "-c", "import http.client, sys; c = http.client.HTTPConnection('127.0.0.1', 8080, timeout=2); c.request('GET', '/healthz'); sys.exit(0 if c.getresponse().status == 200 else 1)"],
        "entrypoint": ["python3", "/app/src/healthcheck_server.py"],
    },
}


def select_stack(constraints: Dict[str, Any]) -> Dict[str, Any]:
    val = validate_requirements(constraints)
    if val["status"] == "error":
        return val
    c = val["metrics"]["normalized_constraints"]

    rps = float(c["expected_rps"])
    budget = float(c["monthly_budget_usd"])
    team_size = int(c["team_size"])
    exp = str(c["team_experience"]).lower()

    runtime_id = determine_primary_runtime(exp, rps)
    profile = RUNTIME_PROFILES[runtime_id]
    runtime_choice = profile["runtime_label"]
    backend_choice = profile["backend_framework"]
    need_dedicated_redis = rps >= 300 or budget >= 250.0 or "redis" in exp

    selected_architecture_config = {
        "backend_runtime": runtime_id,
        "runtime_label": runtime_choice,
        "backend_framework": backend_choice,
        "frontend_framework": "React 19 + TanStack Start / Vite + Tailwind CSS",
        "database": "postgresql-16",
        "cache_strategy": "redis" if need_dedicated_redis else "in_process",
        "redis_enabled": need_dedicated_redis,
        "queue_strategy": "postgres_skip_locked",
        "authentication": "stateless_jwt_httponly_cookie",
        "object_storage": "s3_compatible",
        "reverse_proxy": "caddy-2",
        "deployment": "docker_compose",
        "healthcheck_strategy": {
            "endpoint": "/healthz",
            "port": 8080,
            "probe_command": profile["healthcheck_cmd"],
            "entrypoint": profile["entrypoint"],
        },
    }

    stack_decisions: Dict[str, Dict[str, Any]] = {
        "runtime": {
            "choice": runtime_choice,
            "why_selected": f"Directly matches team experience (`{c['team_experience']}`) while delivering predictable p95 latency on 2-4 vCPU nodes.",
            "alternatives_considered": [p["runtime_label"] for k, p in RUNTIME_PROFILES.items() if k != runtime_id],
            "why_rejected": "Alternative runtimes do not align as closely with the stated primary team skillset and operational preferences.",
            "operational_complexity": "Low (single container runtime with deterministic health check).",
            "cost_implications": "Fits comfortably within 2-4 GiB RAM tiers.",
            "scaling_limitations": "Single node saturates when CPU exceeds 70-80% under peak serialization load.",
            "migration_path": "Add horizontal stateless container replicas behind Caddy/ALB.",
        },
        "backend_framework": {
            "choice": backend_choice,
            "why_selected": "Provides type-safe request validation and low middleware overhead to keep p95 latency below target.",
            "alternatives_considered": ["Distributed gRPC Microservices", "GraphQL Federation Mesh"],
            "why_rejected": "Microservices and GraphQL Federation introduce distributed tracing, network serialization, and deployment coordination overhead unsuitable for Day-0 scale.",
            "operational_complexity": "Low (modular monolith deployment unit).",
            "cost_implications": "Zero additional sidecar or service-mesh memory overhead.",
            "scaling_limitations": "Shared deployment artifact requires disciplined module boundaries as team grows past 15 engineers.",
            "migration_path": "Extract only the highest-throughput domain module into an independent worker service if independent scaling becomes necessary.",
        },
        "frontend_framework": {
            "choice": "React 19 + TanStack Start / Vite + Tailwind CSS",
            "why_selected": "Provides type-safe full-stack routing, SSR/streaming where needed, and static asset caching via CDN.",
            "alternatives_considered": ["Multi-repo Micro-Frontends", "Native Mobile Apps on Day 0"],
            "why_rejected": "Micro-frontends multiply CI/CD and bundle complexity with zero benefit for a focused product team.",
            "operational_complexity": "Low.",
            "cost_implications": "Static assets are served from CDN / Caddy with near-zero compute cost.",
            "scaling_limitations": "SSR routes consume server CPU under heavy un-cached bot traffic.",
            "migration_path": "Place CDN edge caching headers (`Cache-Control: s-maxage`) in front of public SSR pages.",
        },
        "database": {
            "choice": "PostgreSQL 16 (Primary OLTP + JSONB + Full-Text Search)",
            "why_selected": "Handles relational integrity, JSONB document flexibility, and ACID transactions in a single battle-tested engine.",
            "alternatives_considered": ["MongoDB + Elasticsearch + MySQL polyglot persistence", "CockroachDB / Spanner"],
            "why_rejected": "Running 3 separate data stores triples operational maintenance and exceeds the monthly budget; distributed SQL adds network-hop latency unnecessary below 5,000 write RPS.",
            "operational_complexity": "Low-to-Medium (managed RDS/Cloud SQL or automated pgBackRest container).",
            "cost_implications": "Consolidates relational, document, and search workloads into a single database tier.",
            "scaling_limitations": "Single primary node write throughput saturates around 3,000-8,000 write IOPS.",
            "migration_path": "Add PgBouncer connection pooling, then introduce 1 read replica, then partition time-series tables > 250 GB.",
        },
        "cache": {
            "choice": "Redis 7 (Read-through cache & rate limiting)" if need_dedicated_redis else "In-Process LRU Cache + PostgreSQL UNLOGGED tables",
            "why_selected": (
                "High RPS / dedicated cache requirement benefits from sub-millisecond shared Redis caching and sliding-window rate limiting."
                if need_dedicated_redis else
                "At <= 300 RPS and tight budget without explicit Redis requirement, in-memory process caching + PostgreSQL UNLOGGED tables eliminate an extra container and network hop."
            ),
            "alternatives_considered": ["Memcached cluster", "Managed AWS ElastiCache Multi-AZ ($100+/mo)"],
            "why_rejected": "Managed multi-node cache clusters consume disproportionate budget at Day-0 scale.",
            "operational_complexity": "Low.",
            "cost_implications": "$0 additional cloud bill when co-located or using in-process cache.",
            "scaling_limitations": "In-process cache is not shared across multiple stateless app nodes.",
            "migration_path": "Switch cache_strategy to 'redis' when scaling to >= 2 stateless app nodes.",
        },
        "queue": {
            "choice": "PostgreSQL transactional job queue (`FOR UPDATE SKIP LOCKED`)",
            "why_selected": "Guarantees atomic job enqueueing inside the same ACID database transaction as business writes without dual-write bugs.",
            "alternatives_considered": ["Apache Kafka", "RabbitMQ Cluster", "AWS SQS + EventBridge"],
            "why_rejected": "Kafka requires ZooKeeper/KRaft brokers and multiple gigabytes of RAM; RabbitMQ adds another stateful cluster to monitor and back up.",
            "operational_complexity": "Very Low (uses existing PostgreSQL backups and monitoring).",
            "cost_implications": "$0 extra infrastructure cost.",
            "scaling_limitations": "Table bloat and lock contention appear above ~2,000 jobs/second.",
            "migration_path": "Migrate high-volume fire-and-forget telemetry streams to Redis Streams or NATS JetStream if throughput exceeds 2,000 jobs/sec.",
        },
        "authentication": {
            "choice": "Stateless EdDSA/ES256 JWT + HttpOnly Secure Session Cookies (or Clerk/Auth.js)",
            "why_selected": "Prevents XSS token theft via `HttpOnly; Secure; SameSite=Lax` cookies while keeping verification fast.",
            "alternatives_considered": ["Custom OAuth2 Identity Server microservice", "Enterprise SAML appliance on Day 0"],
            "why_rejected": "Maintaining a separate identity microservice doubles deployment surface area.",
            "operational_complexity": "Low.",
            "cost_implications": "$0 self-hosted session table in PostgreSQL.",
            "scaling_limitations": "Database-backed session revocation checks add 1 PK lookup if not cached for 60s.",
            "migration_path": "Cache active session revocations for 60 seconds in memory or Redis.",
        },
        "object_storage": {
            "choice": "S3-Compatible Object Storage (Cloudflare R2 / AWS S3)",
            "why_selected": "Offloads user uploads and database WAL backups from local block storage with 11 nines durability.",
            "alternatives_considered": ["Storing binary blobs in PostgreSQL BYTEA", "Local container filesystem volumes"],
            "why_rejected": "Storing blobs in PostgreSQL bloats shared_buffers and slows backups; local disks break horizontal scaling.",
            "operational_complexity": "Low (presigned PUT/GET URLs).",
            "cost_implications": "~$0.015-$0.023 per GB-month ($0 egress on Cloudflare R2).",
            "scaling_limitations": "Virtually unlimited object storage scaling.",
            "migration_path": "Use standard AWS S3 SDK v3 so endpoints can switch via environment variables.",
        },
        "api_architecture": {
            "choice": "REST / JSON HTTP/2 API with OpenAPI 3.1 schema validation",
            "why_selected": "Universal client compatibility, straightforward HTTP caching, and human-readable debugging.",
            "alternatives_considered": ["gRPC-only external API", "GraphQL with deeply nested dynamic resolvers"],
            "why_rejected": "GraphQL requires complex query-depth and N+1 DataLoader defenses on Day 0.",
            "operational_complexity": "Low.",
            "cost_implications": "Standard CDN and reverse-proxy compression works out of the box.",
            "scaling_limitations": "JSON payload verbosity on large batch responses.",
            "migration_path": "Enable Zstandard/Gzip compression in Caddy and add internal gRPC only for high-frequency internal streams.",
        },
        "observability": {
            "choice": "Structured JSON logs + Prometheus `/metrics` endpoint + OpenTelemetry traces",
            "why_selected": "Vendor-neutral telemetry compatible with Grafana Cloud free tier, VictoriaMetrics, or self-hosted Prometheus.",
            "alternatives_considered": ["Enterprise APM agents costing $50-$150/host/month", "Unstructured plain-text printf logs"],
            "why_rejected": "Commercial per-host APM agents can exceed the entire compute budget on Day 0.",
            "operational_complexity": "Low.",
            "cost_implications": "$0 using open-source collectors or free tier metrics.",
            "scaling_limitations": "High-cardinality labels can bloat time-series memory.",
            "migration_path": "Sample traces at 10% in production while keeping 100% sampling on errors and slow (>500ms) requests.",
        },
        "deployment": {
            "choice": "Docker Compose on Single/Pair Linux Nodes (or AWS EC2 + RDS)",
            "why_selected": f"Matches team size ({team_size}) and maintenance capacity without Kubernetes control-plane tax.",
            "alternatives_considered": ["Managed Kubernetes (EKS/GKE/AKS)", "HashiCorp Nomad + Consul + Vault cluster"],
            "why_rejected": "EKS/GKE control planes cost ~$73/month before a single worker node is launched and require continuous cluster upgrade maintenance.",
            "operational_complexity": "Low (immutable container images deployed via atomic Compose pull/up).",
            "cost_implications": "Saves $73+/month in control plane fees and 1-2 vCPUs of kube-system daemonset overhead.",
            "scaling_limitations": "Single-node vertical scaling tops out at 64-128 vCPUs.",
            "migration_path": "Since services are packaged as standard OCI containers, transition to ECS/Cloud Run or Kubernetes only when node count exceeds 5-8 hosts.",
        },
        "reverse_proxy": {
            "choice": "Caddy 2 (Automatic HTTPS, HTTP/2, HTTP/3, Zstd compression)",
            "why_selected": "Automates Let's Encrypt/ZeroSSL TLS certificate provisioning and renewal with a 15-line Caddyfile.",
            "alternatives_considered": ["Envoy Proxy mesh", "Manual Nginx + Certbot cron scripts"],
            "why_rejected": "Envoy configuration verbosity is overkill for edge routing; manual Certbot cron jobs frequently fail silently after 90 days.",
            "operational_complexity": "Very Low.",
            "cost_implications": "$0.",
            "scaling_limitations": "Single edge proxy handles >15,000 RPS on 2 vCPUs.",
            "migration_path": "Place Cloudflare or AWS ALB in front of Caddy instances for multi-node active-active routing.",
        },
        "ci_cd": {
            "choice": "GitHub Actions (Lint, Unit Tests, Migration Safety Check, Multi-Stage OCI Build)",
            "why_selected": "Zero self-hosted runner maintenance and native integration with pull-request status checks.",
            "alternatives_considered": ["Self-hosted Jenkins server", "Complex ArgoCD GitOps cluster"],
            "why_rejected": "Self-hosted Jenkins requires patching and dedicated RAM.",
            "operational_complexity": "Low.",
            "cost_implications": "Free tier includes 2,000 CI minutes/month.",
            "scaling_limitations": "Hosted runner build cache eviction above 10 GB.",
            "migration_path": "Add GitHub Actions layer caching (`type=gha`) or Depot/Namespace fast builders as build volume grows.",
        },
    }

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": [{
            "id": "STK-COMP-001",
            "category": "stack_selection",
            "severity": "info",
            "classification": "verified",
            "title": f"Compiled cohesive 13-layer stack anchored on {runtime_choice}, PostgreSQL 16, and {'Redis 7 + ' if need_dedicated_redis else 'in-process cache + '}Caddy/Docker Compose",
            "evidence": selected_architecture_config,
            "likely_causes": ["Constraint-driven architecture selection favoring operational simplicity"],
            "confidence": "high",
            "recommendation": "Use scripts/scaffold_infrastructure.py to materialize the runtime-matched Day-0 configuration files."
        }],
        "metrics": {
            "architecture_pattern": "Modular Monolith with Transactional Postgres Job Queue",
            "selected_architecture_config": selected_architecture_config,
            "stack_decisions": stack_decisions,
        },
        "warnings": [],
        "recommendations": ["Review the generated ADR documents to record trade-offs in version control."],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Select cohesive 13-layer technology stack from constraints.")
    parser.add_argument("--input", required=True, help="Path to constraints JSON file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.input)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"File not found: {p}")), file=sys.stderr)
        return 1

    payload = select_stack(json.loads(p.read_text(encoding="utf-8")))
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
