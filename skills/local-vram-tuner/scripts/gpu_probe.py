#!/usr/bin/env python3
"""Probe NVIDIA CUDA GPUs (nvidia-smi), AMD ROCm GPUs (rocm-smi), Apple Metal, or CPU fallback."""
import argparse
import csv
import io
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope, run_bounded_command


def parse_nvidia_smi_csv(csv_text: str) -> List[Dict[str, Any]]:
    gpus: List[Dict[str, Any]] = []
    reader = csv.reader(io.StringIO(csv_text.strip()))
    for idx, row in enumerate(reader):
        if len(row) < 5:
            continue
        try:
            name = row[0].strip()
            total_mib = float(row[1].strip())
            used_mib = float(row[2].strip())
            free_mib = float(row[3].strip())
            driver = row[4].strip()
            gpus.append({
                "index": idx,
                "vendor": "NVIDIA",
                "name": name,
                "total_vram_mib": total_mib,
                "used_vram_mib": used_mib,
                "free_vram_mib": free_mib,
                "total_vram_gib": round(total_mib / 1024.0, 2),
                "used_vram_gib": round(used_mib / 1024.0, 2),
                "free_vram_gib": round(free_mib / 1024.0, 2),
                "driver_version": driver,
            })
        except ValueError:
            continue
    return gpus


def parse_rocm_smi_json(raw_json: str) -> List[Dict[str, Any]]:
    data = json.loads(raw_json)
    gpus: List[Dict[str, Any]] = []
    for idx, (card_key, card_val) in enumerate(data.items()):
        if not isinstance(card_val, dict):
            continue
        total_b = int(card_val.get("VRAM Total Memory (B)", 0) or 0)
        used_b = int(card_val.get("VRAM Total Used Memory (B)", 0) or 0)
        free_b = max(0, total_b - used_b)
        gpus.append({
            "index": idx,
            "vendor": "AMD",
            "name": card_val.get("Card series", card_key),
            "total_vram_mib": round(total_b / (1024**2), 2),
            "used_vram_mib": round(used_b / (1024**2), 2),
            "free_vram_mib": round(free_b / (1024**2), 2),
            "total_vram_gib": round(total_b / (1024**3), 2),
            "used_vram_gib": round(used_b / (1024**3), 2),
            "free_vram_gib": round(free_b / (1024**3), 2),
            "driver_version": card_val.get("Driver version", "rocm"),
        })
    return gpus


def probe_gpus(nvidia_fixture: Optional[Path] = None, rocm_fixture: Optional[Path] = None) -> Dict[str, Any]:
    gpus: List[Dict[str, Any]] = []
    warnings: List[str] = []
    backend = "cpu_fallback"

    if nvidia_fixture and nvidia_fixture.exists():
        gpus = parse_nvidia_smi_csv(nvidia_fixture.read_text(encoding="utf-8"))
        if gpus:
            backend = "cuda"
    elif rocm_fixture and rocm_fixture.exists():
        gpus = parse_rocm_smi_json(rocm_fixture.read_text(encoding="utf-8"))
        if gpus:
            backend = "rocm"
    else:
        if shutil.which("nvidia-smi"):
            res = run_bounded_command(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,driver_version", "--format=csv,noheader,nounits"],
                timeout_sec=4.0,
            )
            if res["ok"] and res["stdout"].strip():
                gpus = parse_nvidia_smi_csv(res["stdout"])
                if gpus:
                    backend = "cuda"
            elif res["stderr"]:
                warnings.append(f"nvidia-smi invocation failed: {res['stderr']}")

        if not gpus and shutil.which("rocm-smi"):
            res = run_bounded_command(["rocm-smi", "--showmeminfo", "vram", "--json"], timeout_sec=4.0)
            if res["ok"] and res["stdout"].strip():
                gpus = parse_rocm_smi_json(res["stdout"])
                if gpus:
                    backend = "rocm"
            elif res["stderr"]:
                warnings.append(f"rocm-smi invocation failed: {res['stderr']}")

        if not gpus and platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64"):
            backend = "metal_unified"

    if not gpus and backend == "cpu_fallback":
        warnings.append("No NVIDIA (nvidia-smi) or AMD (rocm-smi) discrete GPU detected; using CPU/RAM fallback.")

    total_vram_gib = round(sum(g["total_vram_gib"] for g in gpus), 2)
    used_vram_gib = round(sum(g.get("used_vram_gib", 0.0) for g in gpus), 2)
    free_vram_gib = round(sum(g["free_vram_gib"] for g in gpus), 2)

    findings = [{
        "id": "GPU-PROBE-001",
        "category": "gpu_hardware",
        "severity": "info" if gpus or backend == "metal_unified" else "low",
        "classification": "measured",
        "title": (
            f"Detected {len(gpus)} {backend.upper()} GPU(s) ({total_vram_gib} GiB total VRAM, {free_vram_gib} GiB free)"
            if gpus else f"Running in {backend} mode (no discrete GPU detected)"
        ),
        "evidence": {"backend": backend, "gpu_count": len(gpus), "gpus": gpus},
        "likely_causes": ["Hardware accelerator discovery"],
        "confidence": "high",
        "recommendation": (
            f"Target model weights + KV cache within {round(free_vram_gib * 0.9, 2)} GiB to avoid PCIe CPU layer offloading."
            if gpus else "Use quantized 1.5B-7B GGUF models with llama.cpp CPU inference or supply --vram-budget-gb manually."
        ),
    }]

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "tool_versions": {
            "python": platform.python_version(),
            "nvidia_smi": shutil.which("nvidia-smi") is not None,
            "rocm_smi": shutil.which("rocm-smi") is not None,
        },
        "findings": findings,
        "metrics": {
            "measurement_classification": "measured_hardware_consumption",
            "acceleration_backend": backend,
            "gpu_count": len(gpus),
            "total_vram_gib": total_vram_gib,
            "used_vram_gib": used_vram_gib,
            "free_vram_gib": free_vram_gib,
            "gpus": gpus,
        },
        "warnings": warnings,
        "recommendations": [findings[0]["recommendation"]],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe GPU accelerators and VRAM availability.")
    parser.add_argument("--nvidia-fixture", help="Optional path to nvidia-smi CSV fixture for testing")
    parser.add_argument("--rocm-fixture", help="Optional path to rocm-smi JSON fixture for testing")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    try:
        payload = probe_gpus(
            Path(args.nvidia_fixture) if args.nvidia_fixture else None,
            Path(args.rocm_fixture) if args.rocm_fixture else None,
        )
    except Exception as exc:
        print(json.dumps(make_error_envelope(f"GPU probe failed: {exc}")), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
