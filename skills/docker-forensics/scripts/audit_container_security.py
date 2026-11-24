#!/usr/bin/env python3
"""Audit Docker container and Dockerfile security controls without exposing environment secrets."""
import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from common import make_error_envelope, scrub_object_secrets, scrub_text_secrets


DANGEROUS_CAPS = {"ALL", "CAP_SYS_ADMIN", "SYS_ADMIN", "CAP_NET_ADMIN", "NET_ADMIN", "CAP_SYS_PTRACE", "SYS_PTRACE", "CAP_DAC_READ_SEARCH"}
SENSITIVE_MOUNTS = {"/", "/etc", "/proc", "/sys", "/var/run/docker.sock", "/run/docker.sock", "/root"}


def audit_security(inspect_data: Optional[Dict[str, Any]], dockerfile_text: Optional[str] = None) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    recommendations: List[str] = []

    if inspect_data:
        c = inspect_data[0] if isinstance(inspect_data, list) else inspect_data
        cfg = c.get("Config", {})
        hcfg = c.get("HostConfig", {})
        mounts = c.get("Mounts", [])

        user = str(cfg.get("User", "")).strip()
        if user in ("", "0", "root", "0:0"):
            findings.append({
                "id": "SEC-ROOT-001",
                "category": "privilege",
                "severity": "high",
                "classification": "verified",
                "title": "Container runs as root (UID 0)",
                "evidence": {"user": user or "root (default)"},
                "likely_causes": ["No non-root USER specified in Dockerfile or container securityContext"],
                "confidence": "high",
                "recommendation": "Run container as a non-root UID (e.g., `--user 10001:10001`)."
            })

        if hcfg.get("Privileged") is True:
            findings.append({
                "id": "SEC-PRIV-001",
                "category": "privilege",
                "severity": "critical",
                "classification": "verified",
                "title": "Container is running in `--privileged` mode (disables seccomp, AppArmor, and device isolation)",
                "evidence": {"privileged": True},
                "likely_causes": ["Container launched with --privileged flag"],
                "confidence": "high",
                "recommendation": "Remove `--privileged` and grant only minimal required Linux capabilities."
            })

        cap_add = set(hcfg.get("CapAdd") or [])
        bad_caps = sorted(cap_add.intersection(DANGEROUS_CAPS))
        if bad_caps:
            findings.append({
                "id": "SEC-CAP-001",
                "category": "capabilities",
                "severity": "high",
                "classification": "verified",
                "title": f"Excessive Linux capabilities granted: {', '.join(bad_caps)}",
                "evidence": {"cap_add": bad_caps},
                "likely_causes": ["Overly permissive CapAdd configuration"],
                "confidence": "high",
                "recommendation": "Drop all capabilities (`--cap-drop=ALL`) and add back only strictly necessary capabilities."
            })

        if hcfg.get("NetworkMode") == "host":
            findings.append({
                "id": "SEC-NET-001",
                "category": "network_isolation",
                "severity": "high",
                "classification": "verified",
                "title": "Container uses host network namespace (`NetworkMode: host`)",
                "evidence": {"network_mode": "host"},
                "likely_causes": ["Launched with --network=host, exposing host loopback and all host interfaces"],
                "confidence": "high",
                "recommendation": "Isolate container on a user-defined bridge network and publish only required ports."
            })

        for m in mounts:
            src = str(m.get("Source", "")).rstrip("/") or "/"
            if src in SENSITIVE_MOUNTS or src.endswith("docker.sock"):
                findings.append({
                    "id": "SEC-MOUNT-001",
                    "category": "host_mount",
                    "severity": "critical" if "docker.sock" in src or src in ("/", "/etc") else "high",
                    "classification": "verified",
                    "title": f"Sensitive host path mounted into container: `{src}` -> `{m.get('Destination')}`",
                    "evidence": {"source": src, "destination": m.get("Destination"), "rw": m.get("RW")},
                    "likely_causes": ["Mounting Docker socket or sensitive host root directories allows trivial host root escape"],
                    "confidence": "high",
                    "recommendation": "Remove host `/var/run/docker.sock` or `/etc` mounts, or proxy read-only API calls via a hardened socket proxy."
                })

        if not hcfg.get("ReadonlyRootfs"):
            findings.append({
                "id": "SEC-ROFS-001",
                "category": "filesystem",
                "severity": "medium",
                "classification": "verified",
                "title": "Container root filesystem is writable (`ReadonlyRootfs: false`)",
                "evidence": {"readonly_rootfs": False},
                "likely_causes": ["Default Docker rootfs allows runtime binary tampering"],
                "confidence": "high",
                "recommendation": "Enable `--read-only` root filesystem and mount `/tmp` via `--tmpfs /tmp:rw,noexec,nosuid`."
            })

        sec_opts = hcfg.get("SecurityOpt") or []
        if not any("no-new-privileges" in str(opt) for opt in sec_opts):
            findings.append({
                "id": "SEC-NNP-001",
                "category": "privilege_escalation",
                "severity": "medium",
                "classification": "verified",
                "title": "Missing `no-new-privileges:true` in SecurityOpt",
                "evidence": {"security_opt": sec_opts},
                "likely_causes": ["Binaries with the SUID/SGID bit set inside the container can escalate privileges without no-new-privileges"],
                "confidence": "high",
                "recommendation": "Pass `--security-opt=no-new-privileges:true`."
            })

        if int(hcfg.get("Memory", 0) or 0) == 0 or int(hcfg.get("PidsLimit", 0) or 0) in (0, -1):
            findings.append({
                "id": "SEC-LIMITS-001",
                "category": "resource_limits",
                "severity": "medium",
                "classification": "verified",
                "title": "Missing cgroup memory or PIDs limit (`Memory=0` or `PidsLimit=unlimited`)",
                "evidence": {"memory_limit": hcfg.get("Memory", 0), "pids_limit": hcfg.get("PidsLimit", 0)},
                "likely_causes": ["Container can exhaust host RAM or fork-bomb the node"],
                "confidence": "high",
                "recommendation": "Set explicit `--memory` and `--pids-limit` bounds on every container."
            })

    if dockerfile_text:
        if re.search(r"\bcurl\b.*\|\s*(?:ba)?sh\b", dockerfile_text, re.IGNORECASE):
            findings.append({
                "id": "SEC-DF-CURLPIPE",
                "category": "supply_chain",
                "severity": "high",
                "classification": "verified",
                "title": "Dockerfile pipes remote downloaded script directly into a shell without SHA-256 verification",
                "evidence": {"pattern": "remote_script_piped_to_shell"},
                "likely_causes": ["Unverified remote script execution during image build"],
                "confidence": "high",
                "recommendation": "Download release artifacts to a file, verify `sha256sum --check`, and then execute."
            })
        if re.search(r"^\s*(?:ENV|ARG)\s+[A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|PRIVATE_KEY|API_KEY|ACCESS_KEY)[A-Z0-9_]*\s*(?:=|\s+\S+)", dockerfile_text, re.IGNORECASE | re.MULTILINE):
            findings.append({
                "id": "SEC-DF-ENVSECRET",
                "category": "secret_baked_in_image",
                "severity": "critical",
                "classification": "verified",
                "title": "Dockerfile bakes secret/password key into image metadata via `ENV`",
                "evidence": {"secret_value_printed": False, "detected_in": "Dockerfile ENV"},
                "likely_causes": ["Secrets placed in ENV or ARG persist permanently in `docker inspect` and image layer history"],
                "confidence": "high",
                "recommendation": "Inject secrets at runtime via secret mounts (`RUN --mount=type=secret`) or orchestrator secret stores."
            })

    severities = [f["severity"] for f in findings]
    status = "critical" if "critical" in severities else ("warning" if findings else "ok")
    for f in findings:
        if f["recommendation"] not in recommendations:
            recommendations.append(f["recommendation"])

    return scrub_object_secrets({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "total_security_findings": len(findings),
            "critical_count": severities.count("critical"),
            "high_count": severities.count("high"),
            "medium_count": severities.count("medium"),
            "secrets_exposed_in_report": 0,
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    })


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit container and Dockerfile security posture.")
    parser.add_argument("--inspect-file", help="Path to container inspect JSON file")
    parser.add_argument("--dockerfile", help="Optional path to Dockerfile")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    if not args.inspect_file and not args.dockerfile:
        print(json.dumps(make_error_envelope("Supply --inspect-file and/or --dockerfile")), file=sys.stderr)
        return 2

    insp = None
    if args.inspect_file:
        p = Path(args.inspect_file)
        if not p.exists():
            print(json.dumps(make_error_envelope(f"Inspect file not found: {p}")), file=sys.stderr)
            return 1
        insp = json.loads(p.read_text(encoding="utf-8"))

    df_text = None
    if args.dockerfile:
        df = Path(args.dockerfile)
        if not df.exists():
            print(json.dumps(make_error_envelope(f"Dockerfile not found: {df}")), file=sys.stderr)
            return 1
        df_text = df.read_text(encoding="utf-8", errors="replace")

    payload = audit_security(insp, df_text)
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
