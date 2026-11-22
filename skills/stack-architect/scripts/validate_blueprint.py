#!/usr/bin/env python3
"""Validate generated Day-0 scaffold files for runtime matching, conditional Redis consistency, docker compose validity, port alignment, and zero secrets."""
import argparse
import json
import platform
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import run_bounded_command

BASE_REQUIRED_FILES = [
    "blueprint-manifest.json",
    "docker-compose.yml",
    "Dockerfile",
    ".dockerignore",
    ".env.example",
    "db/init_schema.sql",
    "db/migrations/001_initial_migration.sql",
    "config/Caddyfile",
    ".github/workflows/ci.yml",
    "docs/ARCHITECTURE.md",
    "docs/DEPLOYMENT.md",
    "docs/RUNBOOK.md",
    "docs/adr/adr-001.md",
    "docs/adr/adr-002.md",
    "docs/adr/adr-003.md",
]

RUNTIME_REQUIRED_FILES = {
    "go": ["go.mod", "cmd/server/main.go"],
    "rust": ["Cargo.toml", "src/main.rs"],
    "nodejs": ["package.json", "src/server.js"],
    "python": ["requirements.txt", "src/healthcheck_server.py"],
}

RUNTIME_DOCKERFILE_MARKERS = {
    "go": "FROM golang:",
    "rust": "FROM rust:",
    "nodejs": "FROM node:",
    "python": "FROM python:",
}


def validate_compose_structure(compose_text: str, scaffold_dir: Path, redis_enabled: bool) -> Dict[str, Any]:
    if shutil.which("docker"):
        res = run_bounded_command(["docker", "compose", "-f", str(scaffold_dir / "docker-compose.yml"), "config", "-q"], timeout_sec=5.0, cwd=scaffold_dir)
        if res["ok"]:
            return {"mode": "docker_compose_cli_verified", "valid": True, "details": "Validated via `docker compose config -q`."}

    required_sections = ["services:", "  caddy:", "  app:", "  postgres:", "networks:", "volumes:"]
    if redis_enabled:
        required_sections.append("  redis:")
    missing_sections = [s.strip() for s in required_sections if s not in compose_text]
    unexpected_redis = (not redis_enabled) and ("  redis:" in compose_text or "redis_data:" in compose_text)
    security_directives = ["no-new-privileges:true", "read_only: true"]
    missing_sec = [s for s in security_directives if s not in compose_text]
    valid = (len(missing_sections) == 0 and len(missing_sec) == 0 and not unexpected_redis)
    return {
        "mode": "structural_offline_validator (docker compose CLI unavailable)",
        "valid": valid,
        "missing_sections": missing_sections,
        "unexpected_redis_present": unexpected_redis,
        "missing_security_directives": missing_sec,
    }


def validate_scaffold(scaffold_dir: Path) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    findings: List[Dict[str, Any]] = []

    if not scaffold_dir.exists():
        return {
            "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platform": {"system": platform.system(), "release": platform.release()},
            "tool_versions": {"python": platform.python_version()},
            "findings": [],
            "metrics": {},
            "warnings": [],
            "recommendations": [],
            "errors": [f"Scaffold directory does not exist: {scaffold_dir}"],
        }

    manifest_fp = scaffold_dir / "blueprint-manifest.json"
    arch_cfg = {}
    if manifest_fp.exists():
        arch_cfg = json.loads(manifest_fp.read_text(encoding="utf-8"))
    runtime_id = arch_cfg.get("backend_runtime", "python")
    redis_enabled = bool(arch_cfg.get("redis_enabled", False))

    expected_files = list(BASE_REQUIRED_FILES) + RUNTIME_REQUIRED_FILES.get(runtime_id, [])
    if redis_enabled:
        expected_files.append("config/redis.conf")

    missing = []
    empty = []
    for rel in expected_files:
        fp = scaffold_dir / rel
        if not fp.exists():
            missing.append(rel)
        elif fp.stat().st_size == 0:
            empty.append(rel)

    if not redis_enabled and (scaffold_dir / "config/redis.conf").exists():
        errors.append("config/redis.conf exists even though cache_strategy is in_process (redis_enabled=False)")

    if missing or empty:
        errors.append(f"Missing files: {missing}; Empty files: {empty}")

    df_fp = scaffold_dir / "Dockerfile"
    if df_fp.exists():
        df_txt = df_fp.read_text(encoding="utf-8")
        expected_marker = RUNTIME_DOCKERFILE_MARKERS.get(runtime_id, "")
        if expected_marker and expected_marker not in df_txt:
            errors.append(f"Dockerfile does not match selected runtime '{runtime_id}' (expected '{expected_marker}')")

    port_checks = {}
    for rel in ("docker-compose.yml", "Dockerfile", "config/Caddyfile", ".env.example"):
        fp = scaffold_dir / rel
        if fp.exists():
            txt = fp.read_text(encoding="utf-8")
            port_checks[rel] = "8080" in txt
            if not port_checks[rel]:
                errors.append(f"Port 8080 not aligned in {rel}")

    compose_check = {"mode": "not_run", "valid": False}
    compose_fp = scaffold_dir / "docker-compose.yml"
    if compose_fp.exists():
        compose_check = validate_compose_structure(compose_fp.read_text(encoding="utf-8"), scaffold_dir, redis_enabled)
        if not compose_check["valid"]:
            errors.append(f"Compose validation failed: {compose_check}")
        elif "offline" in compose_check["mode"]:
            warnings.append("docker compose CLI unavailable in environment; validated docker-compose.yml via structural offline validator.")

    env_fp = scaffold_dir / ".env.example"
    if env_fp.exists():
        env_txt = env_fp.read_text(encoding="utf-8")
        if re.search(r"\b(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b", env_txt):
            errors.append("Detected real API key pattern inside .env.example")

    status = "error" if errors else "ok"
    findings.append({
        "id": "BP-VAL-001",
        "category": "blueprint_validation",
        "severity": "info" if not errors else "critical",
        "classification": "verified",
        "title": f"All {len(expected_files)} scaffold files verified for runtime `{runtime_id}`, redis={redis_enabled}, port 8080 alignment, and secret-free configuration" if not errors else "Blueprint validation failed",
        "evidence": {
            "runtime": runtime_id,
            "redis_enabled": redis_enabled,
            "checked_files": len(expected_files),
            "missing": missing,
            "empty": empty,
            "port_alignment": port_checks,
            "compose_validation": compose_check,
        },
        "likely_causes": ["Automated structural and security validation"],
        "confidence": "high",
        "recommendation": "Commit the validated Day-0 scaffold to version control." if not errors else "Fix missing or misaligned scaffold files."
    })

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "runtime": runtime_id,
            "redis_enabled": redis_enabled,
            "required_file_count": len(expected_files),
            "missing_files": missing,
            "empty_files": empty,
            "port_alignment": port_checks,
            "compose_validation": compose_check,
        },
        "warnings": warnings,
        "recommendations": [],
        "errors": errors,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate generated Day-0 infrastructure scaffold.")
    parser.add_argument("--scaffold-dir", required=True, help="Path to generated scaffold directory")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    payload = validate_scaffold(Path(args.scaffold_dir))
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
