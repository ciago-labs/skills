#!/usr/bin/env python3
"""Read-only inspector for local LLM inference runtimes (Ollama, llama.cpp, vLLM) supporting runtime-reported snapshot fixtures."""
import argparse
import json
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope


def inspect_runtimes(ollama_ps_fixture: Optional[Path] = None) -> Dict[str, Any]:
    runtimes = {
        "ollama": {"binary_path": shutil.which("ollama"), "installed": shutil.which("ollama") is not None},
        "llama_server": {
            "binary_path": shutil.which("llama-server") or shutil.which("llama-cli"),
            "installed": bool(shutil.which("llama-server") or shutil.which("llama-cli")),
        },
        "vllm": {"binary_path": shutil.which("vllm"), "installed": shutil.which("vllm") is not None},
    }

    env_flags: Dict[str, Optional[str]] = {}
    for key in ("OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS"):
        env_flags[key] = os.environ.get(key)

    runtime_reported_models: List[Dict[str, Any]] = []
    if ollama_ps_fixture and ollama_ps_fixture.exists():
        raw = json.loads(ollama_ps_fixture.read_text(encoding="utf-8"))
        for m in raw.get("models", []):
            size_b = int(m.get("size", 0) or 0)
            size_vram_b = int(m.get("size_vram", 0) or 0)
            offload_ratio = round((size_vram_b * 100.0 / max(1, size_b)), 2)
            runtime_reported_models.append({
                "name": m.get("name"),
                "runtime_reported_total_bytes": size_b,
                "runtime_reported_vram_bytes": size_vram_b,
                "runtime_reported_cpu_offload_bytes": max(0, size_b - size_vram_b),
                "gpu_offload_pct": offload_ratio,
            })

    findings = []
    recommendations = []
    status = "ok"

    for rm in runtime_reported_models:
        if rm["gpu_offload_pct"] < 100.0:
            status = "warning"
            findings.append({
                "id": "RT-PARTIAL-OFFLOAD",
                "category": "cpu_offload_bottleneck",
                "severity": "high",
                "classification": "measured",
                "title": f"Runtime-reported partial CPU offload detected for `{rm['name']}` ({rm['gpu_offload_pct']}% in VRAM, {round(rm['runtime_reported_cpu_offload_bytes'] / (1024**2), 1)} MiB spilled to CPU RAM)",
                "evidence": rm,
                "likely_causes": ["Model weights + KV cache exceeded free GPU VRAM, forcing split-layer execution across PCIe"],
                "confidence": "high",
                "recommendation": "Enable Q8_0 KV cache quantization (`OLLAMA_KV_CACHE_TYPE=q8_0`) or lower context length (`num_ctx`) so 100% of layers reside in VRAM."
            })

    if env_flags["OLLAMA_KV_CACHE_TYPE"] not in ("q8_0", "q4_0"):
        findings.append({
            "id": "RT-OLLAMA-KV",
            "category": "runtime_config",
            "severity": "info",
            "classification": "verified",
            "title": "OLLAMA_KV_CACHE_TYPE is not set to q8_0/q4_0 (defaults to f16 KV cache)",
            "evidence": env_flags,
            "likely_causes": ["Default Ollama configuration uses 16-bit KV cache"],
            "confidence": "high",
            "recommendation": "Set `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` to cut KV-cache VRAM by ~47%."
        })
        recommendations.append("Export OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0 for constrained VRAM hosts.")

    recommendations.append("For llama.cpp server, pass `--flash-attn -ctk q8_0 -ctv q8_0 -np 1` to minimize KV-cache overhead.")
    recommendations.append("For vLLM on constrained GPUs, tune `--max-model-len`, `--gpu-memory-utilization 0.90`, and `--kv-cache-dtype fp8` where supported.")

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "inspection_scope": "runtime_reported_snapshot" if runtime_reported_models else "static_env_and_binary_check",
            "runtimes": runtimes,
            "environment_variables": env_flags,
            "runtime_reported_models": runtime_reported_models,
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect local LLM runtimes (read-only).")
    parser.add_argument("--ollama-ps-fixture", help="Optional path to Ollama /api/ps JSON snapshot")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    try:
        payload = inspect_runtimes(Path(args.ollama_ps_fixture) if args.ollama_ps_fixture else None)
    except Exception as exc:
        print(json.dumps(make_error_envelope(str(exc))), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
