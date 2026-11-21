#!/usr/bin/env python3
"""Diagnose Docker bridge networking, DNS resolution, port mappings, and loopback binding mismatches."""
import argparse
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from common import make_error_envelope, scrub_object_secrets, scrub_text_secrets


def analyze_container_network(inspect_data: Any, network_data: Optional[Any] = None) -> Dict[str, Any]:
    c = inspect_data[0] if isinstance(inspect_data, list) else inspect_data
    cfg = c.get("Config", {})
    hcfg = c.get("HostConfig", {})
    net = c.get("NetworkSettings", {})
    networks = net.get("Networks", {})
    ports = net.get("Ports") or {}
    exposed = cfg.get("ExposedPorts") or {}

    findings: List[Dict[str, Any]] = []
    recommendations: List[str] = []

    # 1. Default bridge network disables automatic service-name DNS resolution
    if "bridge" in networks and len(networks) == 1:
        findings.append({
            "id": "NET-DEFAULT-BRIDGE",
            "category": "dns_resolution",
            "severity": "high",
            "classification": "verified",
            "title": "Container is attached only to the default `bridge` network, where Docker embedded DNS (`127.0.0.11`) service discovery is disabled",
            "evidence": {"attached_networks": list(networks.keys())},
            "likely_causes": ["Containers on the default docker0 bridge cannot resolve peer containers by container name"],
            "confidence": "high",
            "recommendation": "Create and attach a user-defined bridge network (`docker network create app-net`) to enable automatic DNS name resolution via 127.0.0.11."
        })

    # 2. Exposed ports that have no host port binding
    unmapped_ports = [p for p, bindings in ports.items() if bindings is None]
    if unmapped_ports:
        findings.append({
            "id": "NET-PORT-UNMAPPED",
            "category": "port_mapping",
            "severity": "medium",
            "classification": "verified",
            "title": f"Exposed container port(s) `{', '.join(unmapped_ports)}` have no host port publishing (`-p`)",
            "evidence": {"unmapped_ports": unmapped_ports, "ports_map": ports},
            "likely_causes": ["EXPOSE in Dockerfile only documents the port; it does not publish the port to the host without -p / ports: in Compose"],
            "confidence": "high",
            "recommendation": "Publish the port explicitly (e.g., `-p 127.0.0.1:8080:8080`) or route via an internal reverse proxy on the same bridge network."
        })

    # 3. Check if command/args bind to 127.0.0.1 inside container while ports are published
    cmd_str = " ".join((cfg.get("Entrypoint") or []) + (cfg.get("Cmd") or []))
    if ("127.0.0.1" in cmd_str or "localhost" in cmd_str) and ports:
        findings.append({
            "id": "NET-LOOPBACK-BIND",
            "category": "connection_refused",
            "severity": "high",
            "classification": "verified",
            "title": "Application command binds to `127.0.0.1`/`localhost` inside container, breaking Docker NAT port forwarding",
            "evidence": {"command": cmd_str[:160], "published_ports": ports},
            "likely_causes": ["Traffic forwarded via Docker bridge veth pair arrives on eth0, not container lo (127.0.0.1)"],
            "confidence": "high",
            "recommendation": "Bind the application server inside the container to `0.0.0.0` (e.g., `--host 0.0.0.0`)."
        })

    # 4. Inspect network fixture if provided
    net_summary = {}
    if network_data:
        nobj = network_data[0] if isinstance(network_data, list) else network_data
        net_summary = {
            "name": nobj.get("Name"),
            "driver": nobj.get("Driver"),
            "internal": nobj.get("Internal", False),
            "ipam_config": nobj.get("IPAM", {}).get("Config", []),
        }
        if nobj.get("Internal") is True:
            findings.append({
                "id": "NET-INTERNAL-ONLY",
                "category": "egress_blocked",
                "severity": "info",
                "classification": "verified",
                "title": f"Network `{nobj.get('Name')}` is marked `Internal: true` (outbound internet egress is blocked by design)",
                "evidence": net_summary,
                "likely_causes": ["Network created with --internal flag"],
                "confidence": "high",
                "recommendation": "Attach an external bridge network if the container needs outbound HTTPS/DNS access."
            })

    status = "warning" if any(f["severity"] in ("high", "medium") for f in findings) else "ok"
    for f in findings:
        if f["recommendation"] not in recommendations:
            recommendations.append(f["recommendation"])

    return scrub_object_secrets({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {
            "python": platform.python_version(),
            "ss_available": shutil.which("ss") is not None,
            "ip_available": shutil.which("ip") is not None,
        },
        "findings": findings,
        "metrics": {
            "networks": list(networks.keys()),
            "published_ports": ports,
            "exposed_ports": list(exposed.keys()),
            "network_inspect": net_summary,
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    })


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Docker container networking.")
    parser.add_argument("--inspect-file", required=True, help="Path to container inspect JSON file")
    parser.add_argument("--network-file", help="Optional path to docker network inspect JSON file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.inspect_file)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"Inspect file not found: {p}")), file=sys.stderr)
        return 1

    insp = json.loads(p.read_text(encoding="utf-8"))
    net_data = None
    if args.network_file:
        np = Path(args.network_file)
        if np.exists():
            net_data = json.loads(np.read_text(encoding="utf-8"))

    payload = analyze_container_network(insp, net_data)
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
