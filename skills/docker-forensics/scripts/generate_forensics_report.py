#!/usr/bin/env python3
"""Generate a unified Docker forensics report combining image, layer, security, network, and crash analysis."""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import analyze_image
import analyze_layers
import audit_container_security
import diagnose_crashes
import inspect_docker
import inspect_network
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from common import scrub_object_secrets, scrub_text_secrets


def build_forensics_report(
    inspect_file: Path,
    dockerfile: Optional[Path],
    dockerignore: Optional[Path],
    layers_file: Optional[Path],
    network_file: Optional[Path],
    k8s_pod_file: Optional[Path],
) -> Dict[str, Any]:
    insp_raw = json.loads(inspect_file.read_text(encoding="utf-8"))
    df_text = dockerfile.read_text(encoding="utf-8") if (dockerfile and dockerfile.exists()) else None
    di_text = dockerignore.read_text(encoding="utf-8") if (dockerignore and dockerignore.exists()) else None
    layers_raw = json.loads(layers_file.read_text(encoding="utf-8")) if (layers_file and layers_file.exists()) else []
    net_raw = json.loads(network_file.read_text(encoding="utf-8")) if (network_file and network_file.exists()) else None
    k8s_raw = json.loads(k8s_pod_file.read_text(encoding="utf-8")) if (k8s_pod_file and k8s_pod_file.exists()) else None

    c_rep = inspect_docker.inspect_container_data(insp_raw)
    img_rep = analyze_image.analyze_dockerfile(df_text, di_text) if df_text else {"findings": [], "metrics": {}, "recommendations": []}
    lyr_rep = analyze_layers.analyze_layer_history(layers_raw) if layers_raw else {"findings": [], "metrics": {}, "recommendations": []}
    sec_rep = audit_container_security.audit_security(insp_raw, df_text)
    net_rep = inspect_network.analyze_container_network(insp_raw, net_raw)
    crash_rep = diagnose_crashes.diagnose_crash(insp_raw, k8s_raw)

    all_findings = (
        c_rep["findings"]
        + img_rep["findings"]
        + lyr_rep["findings"]
        + sec_rep["findings"]
        + net_rep["findings"]
        + crash_rep["findings"]
    )
    all_recs = list(dict.fromkeys(
        c_rep["recommendations"]
        + img_rep["recommendations"]
        + lyr_rep["recommendations"]
        + sec_rep["recommendations"]
        + net_rep["recommendations"]
        + crash_rep["recommendations"]
    ))

    severities = [f.get("severity") for f in all_findings]
    status = "critical" if "critical" in severities else ("warning" if findings_exist(all_findings) else "ok")

    return scrub_object_secrets({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": all_findings,
        "metrics": {
            "container": c_rep["metrics"],
            "image": img_rep["metrics"],
            "layers": lyr_rep["metrics"],
            "security": sec_rep["metrics"],
            "network": net_rep["metrics"],
            "crashes": crash_rep["metrics"],
        },
        "warnings": [],
        "recommendations": all_recs,
        "errors": [],
    })


def findings_exist(findings: List[Dict[str, Any]]) -> bool:
    return any(f.get("severity") in ("critical", "high", "medium") for f in findings)


def render_markdown(report: Dict[str, Any]) -> str:
    cm = report["metrics"]["container"]
    lm = report["metrics"]["layers"]
    sm = report["metrics"]["security"]
    crm = report["metrics"]["crashes"]

    lines = [
        "# Container Forensics, Security & Image Optimization Report (`docker-forensics`)",
        "",
        f"- **Overall Status**: `{report['status'].upper()}`",
        f"- **Container**: `{cm.get('name')}` (`{cm.get('image')}`)",
        f"- **Exit Code / OOMKilled**: `ExitCode={crm.get('exit_code')}` (`OOMKilled={crm.get('oom_killed')}`, Restarts=`{crm.get('restart_count')}`)",
        f"- **Measured Layer History Size**: `{lm.get('measured_total_size_mib', 'N/A')} MiB` (Heuristic Reclaimable Cache: `{lm.get('heuristic_reclaimable_cache_mib', 'N/A')} MiB`)",
        f"- **Security Findings**: `{sm.get('total_security_findings', 0)}` (`{sm.get('critical_count', 0)}` critical, `{sm.get('high_count', 0)}` high; Secrets exposed in report: `0`)",
        "",
        "## 1. Diagnostic & Security Findings",
        "",
    ]

    for f in report["findings"]:
        lines.extend([
            f"### [{f.get('severity', 'info').upper()}] {f['id']}: {f['title']}",
            f"- **Category**: `{f.get('category')}` | **Classification**: `{f.get('classification')}`",
            f"- **Evidence**: `{json.dumps(f.get('evidence', {}))}`",
            f"- **Remediation**: {f.get('recommendation', '')}",
            "",
        ])

    lines.extend([
        "## 2. Prioritized Remediation Checklist",
        "",
    ])
    for rec in report["recommendations"]:
        lines.append(f"- {rec}")

    return scrub_text_secrets("\n".join(lines) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate unified Docker forensics report.")
    parser.add_argument("--inspect-file", required=True)
    parser.add_argument("--dockerfile")
    parser.add_argument("--dockerignore")
    parser.add_argument("--layers-file")
    parser.add_argument("--network-file")
    parser.add_argument("--k8s-pod-file")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    rep = build_forensics_report(
        Path(args.inspect_file),
        Path(args.dockerfile) if args.dockerfile else None,
        Path(args.dockerignore) if args.dockerignore else None,
        Path(args.layers_file) if args.layers_file else None,
        Path(args.network_file) if args.network_file else None,
        Path(args.k8s_pod_file) if args.k8s_pod_file else None,
    )
    rendered = render_markdown(rep) if args.format == "markdown" else json.dumps(rep, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
