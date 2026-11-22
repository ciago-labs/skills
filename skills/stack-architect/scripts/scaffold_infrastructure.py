#!/usr/bin/env python3
"""Generate a runtime-matched, runnable Day-0 infrastructure scaffold driven by selected_architecture_config."""
import argparse
import json
import os
import platform
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import generate_architecture
from common import make_error_envelope, resolve_safe_child_path


def _build_runtime_files(runtime_id: str) -> Dict[str, str]:
    if runtime_id == "go":
        return {
            "go.mod": "module day0-app\n\ngo 1.23\n",
            "cmd/server/main.go": """package main

import (
\t"fmt"
\t"net/http"
\t"os"
\t"time"
)

func main() {
\tif len(os.Args) > 1 && os.Args[1] == "--healthcheck" {
\t\tclient := http.Client{Timeout: 2 * time.Second}
\t\tresp, err := client.Get("http://127.0.0.1:8080/healthz")
\t\tif err != nil || resp.StatusCode != 200 {
\t\t\tos.Exit(1)
\t\t}
\t\tos.Exit(0)
\t}
\tport := os.Getenv("APP_PORT")
\tif port == "" {
\t\tport = "8080"
\t}
\tmux := http.NewServeMux()
\tmux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
\t\tw.Header().Set("Content-Type", "application/json")
\t\tw.WriteHeader(http.StatusOK)
\t\tfmt.Fprint(w, `{"status":"ok","runtime":"go"}`)
\t})
\tmux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
\t\tw.Header().Set("Content-Type", "application/json")
\t\tw.WriteHeader(http.StatusOK)
\t\tfmt.Fprint(w, `{"status":"ready","runtime":"go"}`)
\t})
\t_ = http.ListenAndServe("0.0.0.0:"+port, mux)
}
""",
            "Dockerfile": """FROM golang:1.23-alpine AS builder
WORKDIR /src
COPY go.mod ./
COPY cmd/ ./cmd/
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/server ./cmd/server

FROM gcr.io/distroless/static-debian12:nonroot AS runtime
WORKDIR /app
COPY --from=builder /out/server /app/server
EXPOSE 8080
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \\
  CMD ["/app/server", "--healthcheck"]
ENTRYPOINT ["/app/server"]
""",
            ".github/workflows/ci.yml": """name: Day-0 Go Scaffold CI
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: "1.23"
      - name: Build and vet Go server
        run: go vet ./... && CGO_ENABLED=0 go build -o /tmp/server ./cmd/server
""",
        }

    if runtime_id == "rust":
        return {
            "Cargo.toml": """[package]
name = "day0-app"
version = "0.1.0"
edition = "2021"

[dependencies]
""",
            "src/main.rs": """use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() > 1 && args[1] == "--healthcheck" {
        match TcpStream::connect("127.0.0.1:8080") {
            Ok(mut stream) => {
                let _ = stream.write_all(b"GET /healthz HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n");
                let mut buf = String::new();
                let _ = stream.read_to_string(&mut buf);
                if buf.contains("200 OK") {
                    process::exit(0);
                }
                process::exit(1);
            }
            Err(_) => process::exit(1),
        }
    }
    let port = env::var("APP_PORT").unwrap_or_else(|_| "8080".to_string());
    let listener = TcpListener::bind(format!("0.0.0.0:{}", port)).expect("failed to bind");
    for stream in listener.incoming().flatten() {
        let mut s = stream;
        let body = "{\\"status\\":\\"ok\\",\\"runtime\\":\\"rust\\"}";
        let resp = format!(
            "HTTP/1.1 200 OK\\r\\nContent-Type: application/json\\r\\nContent-Length: {}\\r\\nConnection: close\\r\\n\\r\\n{}",
            body.len(),
            body
        );
        let _ = s.write_all(resp.as_bytes());
    }
}
""",
            "Dockerfile": """FROM rust:1.82-bookworm AS builder
WORKDIR /src
COPY Cargo.toml ./
COPY src/ ./src/
RUN cargo build --release

FROM debian:bookworm-slim AS runtime
WORKDIR /app
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -r -s /sbin/nologin appuser
COPY --from=builder /src/target/release/day0-app /usr/local/bin/app
EXPOSE 8080
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \\
  CMD ["/usr/local/bin/app", "--healthcheck"]
ENTRYPOINT ["/usr/local/bin/app"]
""",
            ".github/workflows/ci.yml": """name: Day-0 Rust Scaffold CI
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Rust server
        run: cargo check --release
""",
        }

    if runtime_id == "nodejs":
        return {
            "package.json": json.dumps({
                "name": "day0-app",
                "version": "1.0.0",
                "private": True,
                "engines": {"node": ">=22.0.0"},
                "scripts": {"start": "node src/server.js"},
                "dependencies": {}
            }, indent=2) + "\n",
            "src/server.js": """const http = require('node:http');

const port = Number(process.env.APP_PORT || 8080);
const server = http.createServer((req, res) => {
  if (req.url === '/healthz' || req.url === '/readyz' || req.url === '/') {
    const body = JSON.stringify({ status: 'ok', runtime: 'nodejs', path: req.url });
    res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) });
    res.end(body);
  } else {
    res.writeHead(404);
    res.end();
  }
});

server.listen(port, '0.0.0.0');
""",
            "Dockerfile": """FROM node:22-bookworm-slim AS builder
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev && npm cache clean --force
COPY src/ ./src/

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -r -s /sbin/nologin appuser
COPY --from=builder /app /app
EXPOSE 8080
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \\
  CMD ["node", "-e", "require('http').get({host:'127.0.0.1',port:8080,path:'/healthz'},r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"]
CMD ["node", "src/server.js"]
""",
            ".github/workflows/ci.yml": """name: Day-0 Node.js Scaffold CI
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Check JS syntax
        run: node --check src/server.js
""",
        }

    # Default: python
    return {
        "requirements.txt": "# Zero mandatory external packages for Day-0 healthcheck skeleton; add FastAPI/uvicorn here\n",
        "src/healthcheck_server.py": """#!/usr/bin/env python3
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/healthz", "/readyz", "/"):
            body = json.dumps({"status": "ok", "runtime": "python", "path": self.path}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
""",
        "Dockerfile": """FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -r -s /sbin/nologin appuser
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY src/ /app/src/
EXPOSE 8080
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \\
  CMD ["python3", "-c", "import http.client, sys; c = http.client.HTTPConnection('127.0.0.1', 8080, timeout=2); c.request('GET', '/healthz'); sys.exit(0 if c.getresponse().status == 200 else 1)"]
CMD ["python3", "/app/src/healthcheck_server.py", "--port", "8080"]
""",
        ".github/workflows/ci.yml": """name: Day-0 Python Scaffold CI
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate Python syntax
        run: python3 -m py_compile src/healthcheck_server.py
""",
    }


def _build_compose_and_env(arch_cfg: Dict[str, Any], app_mem_mb: int, db_shared_buf_mb: int) -> Dict[str, str]:
    redis_enabled = bool(arch_cfg.get("redis_enabled", False))
    cache_env_line = "      - REDIS_URL=redis://redis:6379/0\n      - CACHE_STRATEGY=redis" if redis_enabled else "      - CACHE_STRATEGY=in_process"
    redis_depends = "      redis:\n        condition: service_healthy\n" if redis_enabled else ""
    redis_service_block = """
  redis:
    image: redis:7.4-alpine
    restart: unless-stopped
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    volumes:
      - ./config/redis.conf:/usr/local/etc/redis/redis.conf:ro
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - app_net
""" if redis_enabled else ""
    redis_volume_line = "  redis_data:\n" if redis_enabled else ""

    compose_yml = f"""services:
  caddy:
    image: caddy:2.8-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./config/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on:
      app:
        condition: service_healthy
    networks:
      - app_net

  app:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file:
      - .env.example
    environment:
      - APP_PORT=8080
      - APP_RUNTIME={arch_cfg['backend_runtime']}
      - DATABASE_HOST=postgres
      - DATABASE_PORT=5432
      - DATABASE_NAME=app_db
      - DATABASE_USER=app_user
      - POSTGRES_PASSWORD_FILE=/run/secrets/pg_auth
{cache_env_line}
    deploy:
      resources:
        limits:
          memory: {app_mem_mb}M
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=64m
    depends_on:
      postgres:
        condition: service_healthy
{redis_depends}    networks:
      - app_net

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      - POSTGRES_USER=app_user
      - POSTGRES_PASSWORD_FILE=/run/secrets/pg_auth
      - POSTGRES_DB=app_db
    command: >
      postgres
      -c shared_buffers={db_shared_buf_mb}MB
      -c work_mem=16MB
      -c maintenance_work_mem=128MB
      -c random_page_cost=1.1
      -c log_min_duration_statement=250ms
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./db/init_schema.sql:/docker-entrypoint-initdb.d/001_init_schema.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user -d app_db"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - app_net
{redis_service_block}
networks:
  app_net:
    driver: bridge

volumes:
  caddy_data:
  pg_data:
{redis_volume_line}"""

    env_lines = [
        "# Template environment file - NEVER commit real production secrets to version control",
        "APP_ENV=production",
        "APP_PORT=8080",
        f"APP_RUNTIME={arch_cfg['backend_runtime']}",
        "POSTGRES_USER=app_user",
        "POSTGRES_PASSWORD_FILE=/run/secrets/pg_auth",
        "POSTGRES_DB=app_db",
        "DATABASE_HOST=postgres",
        "DATABASE_PORT=5432",
        f"CACHE_STRATEGY={arch_cfg['cache_strategy']}",
    ]
    if redis_enabled:
        env_lines.append("REDIS_URL=redis://redis:6379/0")

    out = {
        "docker-compose.yml": compose_yml,
        ".env.example": "\n".join(env_lines) + "\n",
    }
    if redis_enabled:
        out["config/redis.conf"] = """bind 0.0.0.0
port 6379
maxmemory 256mb
maxmemory-policy allkeys-lru
appendonly yes
appendfsync everysec
"""
    return out


def scaffold_project(constraints: Dict[str, Any], output_dir: Path, force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    bp = generate_architecture.build_architecture_blueprint(constraints)
    if bp["status"] == "error":
        return bp

    if not dry_run and output_dir.exists() and any(output_dir.iterdir()) and not force:
        return {
            "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": {"system": platform.system(), "release": platform.release()},
            "tool_versions": {"python": platform.python_version()},
            "findings": [],
            "metrics": {},
            "warnings": [],
            "recommendations": [],
            "errors": [f"Refusing to overwrite non-empty directory '{output_dir}' without --force."],
        }

    if not dry_run and output_dir.exists() and force:
        # Clean stale files inside output_dir when --force is explicitly passed so switching runtimes/cache leaves no stale files
        for child in list(output_dir.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    siz = bp["metrics"]["4_hardware_sizing_report"]
    stk = bp["metrics"]["6_recommended_technology_stack"]
    arch_cfg = stk["selected_architecture_config"]
    runtime_id = arch_cfg["backend_runtime"]

    app_mem_mb = siz["application_tier"]["recommended_ram_gib"] * 1024
    db_shared_buf_mb = int(siz["database_tier"]["recommended_shared_buffers_gib"] * 1024)

    files_to_write: Dict[str, str] = {
        "blueprint-manifest.json": json.dumps(arch_cfg, indent=2) + "\n",
        ".dockerignore": """.git
.github
.env
.env.*
!.env.example
__pycache__/
*.py[cod]
.venv/
venv/
node_modules/
target/
*.log
""",
        "db/init_schema.sql": """-- Day-0 PostgreSQL 16 Initial Schema & Transactional Job Queue
SET lock_timeout = '2s';
SET statement_timeout = '30s';

CREATE TABLE IF NOT EXISTS accounts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_id UUID NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS background_jobs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    queue_name TEXT NOT NULL DEFAULT 'default',
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INT NOT NULL DEFAULT 0,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_poll
    ON background_jobs (queue_name, status, run_at)
    WHERE status = 'PENDING';
""",
        "db/migrations/001_initial_migration.sql": """-- Zero-downtime migration template
SET lock_timeout = '2s';
SET statement_timeout = '30s';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_accounts_status_created
    ON accounts (status, created_at DESC);
""",
        "config/Caddyfile": """:80 {
    encode zstd gzip
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }
    reverse_proxy app:8080 {
        health_uri /healthz
        health_interval 10s
        health_timeout 3s
    }
}
""",
        "docs/ARCHITECTURE.md": generate_architecture.render_markdown(bp),
        "docs/DEPLOYMENT.md": """# Day-0 Deployment Instructions

## 1. Local & Staging Bring-Up
```bash
cp .env.example .env
# Populate POSTGRES_PASSWORD with a randomly generated secret
docker compose up -d --build
# Verify http://localhost:80/healthz returns {"status": "ok"} using your preferred HTTP client.
```

## 2. Database Migrations
Always execute migrations with explicit lock and statement timeouts:
```bash
docker compose exec -T postgres psql -U app_user -d app_db < db/migrations/001_initial_migration.sql
```
""",
        "docs/RUNBOOK.md": """# Operational Runbook

## 1. High Database Latency or Lock Waiting
- Inspect active queries: `SELECT pid, state, wait_event_type, query FROM pg_stat_activity WHERE state != 'idle';`
- Cancel stuck migration waiting on lock: `SELECT pg_cancel_backend(<pid>);`

## 2. Backup & Restore Verification (RPO 15m / RTO 30m)
- Logical snapshot: `docker compose exec -T postgres pg_dump -U app_user -Fc app_db > backup.dump`
- Restore verification: `pg_restore --list backup.dump`
""",
    }

    files_to_write.update(_build_runtime_files(runtime_id))
    files_to_write.update(_build_compose_and_env(arch_cfg, app_mem_mb, db_shared_buf_mb))

    for adr in bp["metrics"]["8_adr_documents"]:
        slug = adr["id"].lower()
        files_to_write[f"docs/adr/{slug}.md"] = (
            f"# {adr['id']}: {adr['title']}\n\n"
            f"- **Status**: {adr['status']}\n"
            f"- **Context**: {adr['context']}\n"
            f"- **Decision**: {adr['decision']}\n"
            f"- **Consequences**: {adr['consequences']}\n"
        )

    created_files: List[str] = []
    for rel, content in sorted(files_to_write.items()):
        fp = resolve_safe_child_path(output_dir, rel)
        if not dry_run:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            if rel.endswith(".py"):
                fp.chmod(fp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        created_files.append(rel)

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": [{
            "id": "SCAF-GEN-001",
            "category": "scaffolding",
            "severity": "info",
            "classification": "verified",
            "title": f"Generated {len(created_files)} runtime-matched (`{runtime_id}`, redis={arch_cfg['redis_enabled']}) Day-0 scaffold files in `{output_dir}`",
            "evidence": {
                "output_dir": str(output_dir),
                "selected_architecture_config": arch_cfg,
                "files_created": created_files,
            },
            "likely_causes": ["Automated Day-0 infrastructure scaffolding driven by selected_architecture_config"],
            "confidence": "high",
            "recommendation": "Run scripts/validate_blueprint.py to verify runtime, service, port, and secret consistency."
        }],
        "metrics": {
            "output_dir": str(output_dir),
            "dry_run": dry_run,
            "selected_architecture_config": arch_cfg,
            "file_count": len(created_files),
            "files": created_files,
        },
        "warnings": [],
        "recommendations": ["Validate scaffold with scripts/validate_blueprint.py"],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate runnable Day-0 infrastructure scaffold.")
    parser.add_argument("--input", required=True, help="Path to constraints JSON file")
    parser.add_argument("--output-dir", required=True, help="Target directory for generated scaffold")
    parser.add_argument("--force", action="store_true", help="Allow writing into an existing non-empty directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview files to be created without writing to disk")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(json.dumps(make_error_envelope(f"Constraints file not found: {in_path}")), file=sys.stderr)
        return 1

    payload = scaffold_project(json.loads(in_path.read_text(encoding="utf-8")), Path(args.output_dir), force=args.force, dry_run=args.dry_run)
    if payload["status"] == "error":
        print(json.dumps(payload), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
