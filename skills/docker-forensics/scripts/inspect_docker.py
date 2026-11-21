#!/usr/bin/env python3
"""Read-only Docker container configuration inspector with automatic environment secret redaction."""
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

from common import scrub_object_secrets, scrub_text_secrets, make_error_envelope, run_bounded_command


def sanitize_env_list(env_list: List[str]) -> List[Dict[str, str]]:
    sanitized = []
    for item in env_list or []:
        if "=" in item:
            k, _ = item.split("=", 1)
            sanitized.append({"name": k, "value": "[REDACTED_FOR_SECURITY]"})
        else:
            sanitized.append({"name": item, "value": "[REDACTED_FOR_SECURITY]"})
    return sanitized


def inspect_container_data(raw_data: Any) -> Dict[str, Any]:
    if isinstance(raw_data, list) and raw_data:
        c = raw_data[0]
    elif isinstance(raw_data, dict):
        c = raw_data
    else:
        raise ValueError("Container inspect payload must be a JSON object or non-empty list")

    state = c.get("State", {})
    config = c.get("Config", {})
    host_cfg = c.get("HostConfig", {})
    mounts = c.get("Mounts", [])

    env_sanitized = sanitize_env_list(config.get("Env", []))
    restart_policy = host_cfg.get("RestartPolicy", {})
    health = state.get("Health", {})

    findings = []
    recommendations = []
    status = "ok"

    if not config.get("Healthcheck") and not health:
        status = "warning"
        findings.append({
            "id": "DKR-CFG-001",
            "category": "configuration",
            "severity": "medium",
            "classification": "verified",
            "title": "Container has no HEALTHCHECK configured",
            "evidence": {"container_name": c.get("Name"), "healthcheck_present": False},
            "likely_causes": ["Dockerfile and container run spec omit HEALTHCHECK instruction"],
            "confidence": "high",
            "recommendation": "Configure a lightweight HTTP or TCP HEALTHCHECK so orchestrators can detect hung event loops."
        })

    if restart_policy.get("Name") in ("", "no", None):
        findings.append({
            "id": "DKR-CFG-002",
            "category": "resilience",
            "severity": "low",
            "classification": "verified",
            "title": "Container restart policy is set to 'no'",
            "evidence": {"restart_policy": restart_policy},
            "likely_causes": ["Container launched without --restart unless-stopped or on-failure"],
            "confidence": "high",
            "recommendation": "Use `--restart on-failure:5` or `unless-stopped` for long-running services."
        })

    for f in findings:
        recommendations.append(f["recommendation"])

    return scrub_object_secrets({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version(), "docker_cli": shutil.which("docker") is not None},
        "findings": findings,
        "metrics": {
            "id": str(c.get("Id", ""))[:12],
            "name": c.get("Name", "").lstrip("/"),
            "image": config.get("Image"),
            "user": config.get("User") or "root (default)",
            "state": {
                "status": state.get("Status"),
                "running": state.get("Running"),
                "oom_killed": state.get("OOMKilled"),
                "exit_code": state.get("ExitCode"),
                "restart_count": c.get("RestartCount", 0),
                "health_status": health.get("Status") if health else "none",
            },
            "resources": {
                "memory_limit_bytes": host_cfg.get("Memory", 0),
                "nano_cpus": host_cfg.get("NanoCpus", 0),
                "pids_limit": host_cfg.get("PidsLimit", 0),
            },
            "mounts": [
                {"source": m.get("Source"), "destination": m.get("Destination"), "rw": m.get("RW"), "type": m.get("Type")}
                for m in mounts
            ],
            "exposed_ports": list((config.get("ExposedPorts") or {}).keys()),
            "environment_variable_keys": env_sanitized,
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    })


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Docker container configuration safely (secrets redacted).")
    parser.add_argument("--inspect-file", help="Path to docker inspect JSON file")
    parser.add_argument("--container", help="Live container name/ID (requires docker daemon)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    if args.inspect_file:
        p = Path(args.inspect_file)
        if not p.exists():
            print(json.dumps(make_error_envelope(f"Inspect file not found: {p}")), file=sys.stderr)
            return 1
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(json.dumps(make_error_envelope(f"Invalid JSON: {exc}")), file=sys.stderr)
            return 2
    elif args.container:
        res = run_bounded_command(["docker", "inspect", args.container], timeout_sec=5.0)
        if not res["ok"]:
            print(json.dumps(make_error_envelope(res["stderr"] or "docker inspect failed")), file=sys.stderr)
            return 1
        raw = json.loads(res["stdout"])
    else:
        print(json.dumps(make_error_envelope("Provide --inspect-file or --container")), file=sys.stderr)
        return 2

    payload = inspect_container_data(raw)
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
