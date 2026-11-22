#!/usr/bin/env python3
"""Probe host CPU architecture, physical RAM, available RAM, and Apple Silicon unified memory + Metal support."""
import argparse
import json
import os
import platform
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope, run_bounded_command


def probe_linux_meminfo(proc_root: Path = Path("/proc")) -> Dict[str, int]:
    mf = proc_root / "meminfo"
    out: Dict[str, int] = {}
    if not mf.exists():
        return out
    for line in mf.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        k, rest = line.split(":", 1)
        parts = rest.strip().split()
        if parts and parts[0].isdigit():
            out[k.strip()] = int(parts[0]) * 1024
    return out


def parse_macos_system_profiler(profiler_text: str) -> Dict[str, Any]:
    """Parse macOS system_profiler SPHardwareDataType SPDisplaysDataType output."""
    info: Dict[str, Any] = {}
    chip_m = re.search(r"Chip:\s*(.+)$", profiler_text, re.MULTILINE)
    if chip_m:
        info["chip_model"] = chip_m.group(1).strip()
    mem_m = re.search(r"Memory:\s*(\d+)\s*GB", profiler_text, re.MULTILINE | re.IGNORECASE)
    if mem_m:
        info["unified_mem_total_bytes"] = int(mem_m.group(1)) * (1024**3)
    metal_m = re.search(r"Metal(?:\s+Support|\s+Family)?:\s*(.+)$", profiler_text, re.MULTILINE | re.IGNORECASE)
    if metal_m:
        info["metal_family"] = metal_m.group(1).strip()
        info["metal_available"] = "metal" in info["metal_family"].lower() or "supported" in info["metal_family"].lower()
    gpu_cores_m = re.search(r"Total Number of Cores:\s*(\d+)", profiler_text, re.MULTILINE)
    if gpu_cores_m:
        info[" cores_reported"] = int(gpu_cores_m.group(1))
    return info


def probe_macos_live() -> Dict[str, Any]:
    if platform.system() != "Darwin":
        return {}
    info: Dict[str, Any] = {}
    if shutil.which("sysctl"):
        mem = run_bounded_command(["sysctl", "-n", "hw.memsize"], timeout_sec=2.0)
        if mem["ok"] and mem["stdout"].strip().isdigit():
            info["unified_mem_total_bytes"] = int(mem["stdout"].strip())
        brand = run_bounded_command(["sysctl", "-n", "machdep.cpu.brand_string"], timeout_sec=2.0)
        if brand["ok"] and brand["stdout"].strip():
            info["cpu_brand"] = brand["stdout"].strip()
    if shutil.which("system_profiler"):
        sp = run_bounded_command(["system_profiler", "SPHardwareDataType", "SPDisplaysDataType"], timeout_sec=4.0)
        if sp["ok"]:
            info.update(parse_macos_system_profiler(sp["stdout"]))
    return info


def probe_hardware(proc_root: Path = Path("/proc"), macos_profiler_fixture: Optional[Path] = None) -> Dict[str, Any]:
    sys_name = platform.system()
    machine = platform.machine()
    cpu_count = os.cpu_count() or 1
    mem = probe_linux_meminfo(proc_root)

    if macos_profiler_fixture and macos_profiler_fixture.exists():
        mac_info = parse_macos_system_profiler(macos_profiler_fixture.read_text(encoding="utf-8", errors="replace"))
        sys_name = "Darwin"
        machine = "arm64"
    else:
        mac_info = probe_macos_live()

    total_ram = mac_info.get("unified_mem_total_bytes") or mem.get("MemTotal") or 0
    avail_ram = mem.get("MemAvailable") or mem.get("MemFree") or int(total_ram * 0.75)
    if macos_profiler_fixture and mac_info.get("unified_mem_total_bytes"):
        avail_ram = int(mac_info["unified_mem_total_bytes"] * 0.75)

    is_apple_silicon = (sys_name == "Darwin" and machine in ("arm64", "aarch64")) or bool(mac_info.get("chip_model", "").startswith("Apple M"))

    findings = [{
        "id": "HW-HOST-001",
        "category": "hardware",
        "severity": "info",
        "classification": "measured",
        "title": f"Detected {sys_name} ({machine}) with {cpu_count} logical CPUs and {round(total_ram / (1024**3), 2)} GiB memory",
        "evidence": {
            "measurement_source": "macos_system_profiler_fixture" if macos_profiler_fixture else ("proc_meminfo" if mem else "sysctl"),
            "system": sys_name,
            "architecture": machine,
            "logical_cpus": cpu_count,
            "ram_total_gib": round(total_ram / (1024**3), 2),
            "ram_available_gib": round(avail_ram / (1024**3), 2),
            "apple_silicon_unified_memory": is_apple_silicon,
            "chip_model": mac_info.get("chip_model"),
            "metal_available": mac_info.get("metal_available", False),
            "metal_family": mac_info.get("metal_family"),
        },
        "likely_causes": ["Host OS hardware inventory"],
        "confidence": "high",
        "recommendation": "Run scripts/gpu_probe.py to check discrete NVIDIA/AMD GPU VRAM availability."
    }]

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": sys_name, "release": platform.release(), "machine": machine},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "measurement_classification": "measured_hardware_consumption",
            "cpu": {
                "logical_cores": cpu_count,
                "architecture": machine,
                "brand": mac_info.get("chip_model") or mac_info.get("cpu_brand"),
            },
            "memory": {
                "total_bytes": total_ram,
                "available_bytes": avail_ram,
                "total_gib": round(total_ram / (1024**3), 2),
                "available_gib": round(avail_ram / (1024**3), 2),
                "swap_total_bytes": mem.get("SwapTotal", 0),
                "swap_free_bytes": mem.get("SwapFree", 0),
                "unified_memory": is_apple_silicon,
                "metal_available": mac_info.get("metal_available", False),
                "metal_family": mac_info.get("metal_family"),
            },
        },
        "warnings": [] if total_ram > 0 else ["Could not read /proc/meminfo or macOS sysctl hw.memsize"],
        "recommendations": ["Keep at least 1.5 GiB of host RAM free for OS and coding agent processes when sizing local LLM models."],
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe host CPU, memory, and Apple Silicon Metal resources.")
    parser.add_argument("--proc-root", default="/proc", help="Path to /proc filesystem")
    parser.add_argument("--macos-profiler-fixture", help="Optional path to system_profiler fixture for testing")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p_root = Path(args.proc_root)
    if not p_root.exists() and not args.macos_profiler_fixture:
        print(json.dumps(make_error_envelope(f"Proc root does not exist: {p_root}")), file=sys.stderr)
        return 1

    payload = probe_hardware(
        p_root,
        Path(args.macos_profiler_fixture) if args.macos_profiler_fixture else None,
    )
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
