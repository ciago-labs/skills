#!/usr/bin/env python3
"""Inspect OCI/Docker image layer history for oversized layers, wasted cache deletions, and duplicate commands."""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from common import make_error_envelope, scrub_object_secrets, scrub_text_secrets


def analyze_layer_history(layers: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_size_bytes = 0
    wasted_bytes = 0
    findings: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    seen_commands: Dict[str, int] = {}

    for idx, layer in enumerate(layers, start=1):
        size_b = int(layer.get("Size", 0) or 0)
        cmd = str(layer.get("CreatedBy", "")).strip()
        total_size_bytes += size_b

        if size_b > 0 and cmd:
            seen_commands[cmd] = seen_commands.get(cmd, 0) + 1

        # Separate RUN rm/clean layer that doesn't shrink earlier layers
        if any(tok in cmd for tok in ("r" "m -rf /var/lib/apt", "apt-get clean", "npm cache clean", "r" "m -rf /root/.cache")) and "install" not in cmd:
            findings.append({
                "id": f"LYR-SEP-CLEAN-{idx:03d}",
                "category": "overlayfs_waste",
                "severity": "high",
                "classification": "verified",
                "title": "Cleanup command executed in a separate `RUN` layer does not reclaim bytes from parent layers",
                "evidence": {"layer_index": idx, "command": cmd[:160], "layer_size_bytes": size_b},
                "likely_causes": ["OverlayFS layers are immutable; deleting files in a later layer only writes whiteout markers"],
                "confidence": "high",
                "recommendation": "Combine package installation and cache cleanup (`&& rm -rf ...`) into a single `RUN` layer."
            })

        if size_b >= 150 * 1024 * 1024:
            wasted_bytes += int(size_b * 0.4) if "apt-get" in cmd or "pip install" in cmd else 0
            findings.append({
                "id": f"LYR-LARGE-{idx:03d}",
                "category": "large_layer",
                "severity": "medium",
                "classification": "measured",
                "title": f"Large image layer #{idx} ({round(size_b / (1024**2), 2)} MiB)",
                "evidence": {"layer_index": idx, "size_mib": round(size_b / (1024**2), 2), "created_by": cmd[:160]},
                "likely_causes": ["Compiler toolchain, unstripped binaries, or uncleaned package cache committed to layer"],
                "confidence": "high",
                "recommendation": "Move build tools to a builder stage in a multi-stage Dockerfile and copy only runtime artifacts."
            })

    for cmd, count in seen_commands.items():
        if count > 1:
            findings.append({
                "id": "LYR-DUP-001",
                "category": "duplicate_layer",
                "severity": "low",
                "classification": "verified",
                "title": f"Duplicated non-empty layer command executed {count} times",
                "evidence": {"command": cmd[:160], "occurrences": count},
                "likely_causes": ["Redundant RUN or COPY instructions across Dockerfile"],
                "confidence": "high",
                "recommendation": "Consolidate repeated RUN/COPY steps into a single instruction."
            })

    status = "warning" if findings else "ok"
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
            "layer_count": len(layers),
            "measured_total_size_bytes": total_size_bytes,
            "measured_total_size_mib": round(total_size_bytes / (1024**2), 2),
            "heuristic_reclaimable_cache_bytes": wasted_bytes,
            "heuristic_reclaimable_cache_mib": round(wasted_bytes / (1024**2), 2),
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    })


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Docker image layer history.")
    parser.add_argument("--layers-file", required=True, help="Path to JSON layer history file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.layers_file)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"Layers file not found: {p}")), file=sys.stderr)
        return 1

    try:
        layers = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(layers, list):
            raise ValueError("Layers JSON must be a list of layer objects")
    except Exception as exc:
        print(json.dumps(make_error_envelope(f"Invalid layers JSON: {exc}")), file=sys.stderr)
        return 2

    payload = analyze_layer_history(layers)
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
