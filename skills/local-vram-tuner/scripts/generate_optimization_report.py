#!/usr/bin/env python3
"""Generate a unified hardware, KV-cache, and prompt compaction optimization report."""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import compact_context
import gpu_probe
import hardware_probe
import kv_cache_estimator
import runtime_inspector
from common import make_error_envelope, scrub_object_secrets, scrub_text_secrets


def build_report(
    model: str,
    weight_quant: str,
    kv_quant: str,
    context_length: int,
    batch_seqs: int,
    vram_budget_gb: Optional[float],
    context_file: Optional[Path],
    nvidia_fixture: Optional[Path] = None,
) -> Dict[str, Any]:
    hw = hardware_probe.probe_hardware()
    gpu = gpu_probe.probe_gpus(nvidia_fixture=nvidia_fixture)
    rt = runtime_inspector.inspect_runtimes()

    effective_budget = vram_budget_gb
    if effective_budget is None:
        if gpu["metrics"]["free_vram_gib"] > 0:
            effective_budget = gpu["metrics"]["free_vram_gib"]
        else:
            effective_budget = round(hw["metrics"]["memory"]["available_gib"] * 0.75, 2)

    if model not in kv_cache_estimator.MODEL_PRESETS:
        return make_error_envelope(f"Unknown model preset '{model}'. Supported presets: {list(kv_cache_estimator.MODEL_PRESETS)}")
    preset = kv_cache_estimator.MODEL_PRESETS[model]
    kv = kv_cache_estimator.calculate_vram_budget(
        params_b=preset["params_b"],
        num_layers=preset["num_layers"],
        num_kv_heads=preset["num_kv_heads"],
        head_dim=preset["head_dim"],
        weight_quant=weight_quant,
        kv_quant=kv_quant,
        context_length=context_length,
        batch_seqs=batch_seqs,
        vram_budget_gb=effective_budget,
        model_name=model,
    )

    ctx_stats = None
    if context_file and context_file.exists():
        _, ctx_stats = compact_context.compact_text(context_file.read_text(encoding="utf-8", errors="replace"))

    findings = hw["findings"] + gpu["findings"] + kv["findings"] + rt["findings"]
    recommendations = list(dict.fromkeys(hw["recommendations"] + gpu["recommendations"] + kv["recommendations"] + rt["recommendations"]))

    return scrub_object_secrets({
        "status": kv["status"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": hw["platform"],
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "hardware": hw["metrics"],
            "gpu": gpu["metrics"],
            "kv_cache": kv["metrics"],
            "runtime": rt["metrics"],
            "context_compaction": ctx_stats,
        },
        "warnings": hw["warnings"] + gpu["warnings"],
        "recommendations": recommendations,
        "errors": [],
    })


def render_markdown(report: Dict[str, Any]) -> str:
    hw_m = report["metrics"]["hardware"]
    gpu_m = report["metrics"]["gpu"]
    kv_m = report["metrics"]["kv_cache"]["memory_breakdown"]
    ctx_m = report["metrics"].get("context_compaction")

    lines = [
        "# Local LLM Hardware & KV-Cache Optimization Report (`local-vram-tuner`)",
        "",
        f"- **Status**: `{report['status'].upper()}`",
        f"- **Acceleration Backend**: `{gpu_m['acceleration_backend']}` (GPUs detected: `{gpu_m['gpu_count']}`, Free VRAM: `{gpu_m['free_vram_gib']} GiB`)",
        f"- **System RAM Available**: `{hw_m['memory']['available_gib']} GiB` / `{hw_m['memory']['total_gib']} GiB`",
        "",
        "## 1. Model Weight & KV-Cache Memory Breakdown",
        "",
        f"- **Model**: `{report['metrics']['kv_cache']['model']}` (`{report['metrics']['kv_cache']['quantization']['weight_quant']}` weights, `{report['metrics']['kv_cache']['quantization']['kv_quant']}` KV cache)",
        f"- **Model Weights**: `{kv_m['model_weights_gib']} GiB`",
        f"- **KV-Cache Allocation**: `{kv_m['kv_cache_gib']} GiB` (`{kv_m['kv_kib_per_token_per_seq']} KiB/token/seq`)",
        f"- **Runtime Overhead**: `{kv_m['runtime_overhead_gib']} GiB`",
        f"- **Total Estimated Memory**: `{kv_m['total_estimated_gib']} GiB` vs Budget `{kv_m['vram_budget_gib']} GiB` (Fits in VRAM: `{kv_m['fits_in_vram']}`)",
        f"- **Max Recommended Safe Context Window**: `{kv_m['max_recommended_context']} tokens`",
        "",
    ]

    if ctx_m:
        lines.extend([
            "## 2. Prompt Context Compaction Summary",
            "",
            f"- **Estimated Tokens (Before -> After)**: `{ctx_m['before_tokens_estimate']}` -> `{ctx_m['after_tokens_estimate']}` (`-{ctx_m['reduction_pct_estimate']}%`, method: `{ctx_m['token_estimation_method']}`)",
            f"- **Credentials Redacted**: `{ctx_m['redacted_credentials_count']}`",
            f"- **Noise Removed**: `{ctx_m['omitted_duplicate_lines']}` duplicate log lines, `{ctx_m['omitted_stack_frames']}` stack frames, `{ctx_m['omitted_lockfile_lines']}` lockfile lines",
            "",
        ])

    lines.extend([
        "## 3. Recommended Runtime Adjustments",
        "",
    ])
    for rec in report["recommendations"]:
        lines.append(f"- {rec}")

    return scrub_text_secrets("\n".join(lines) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate unified local LLM VRAM and context optimization report.")
    parser.add_argument("--model", default="qwen2.5-coder-7b")
    parser.add_argument("--weight-quant", default="Q4_K_M")
    parser.add_argument("--kv-quant", default="FP16")
    parser.add_argument("--context-length", type=int, default=32768)
    parser.add_argument("--batch-seqs", type=int, default=1)
    parser.add_argument("--vram-budget-gb", type=float)
    parser.add_argument("--context-file", help="Optional path to prompt context file")
    parser.add_argument("--nvidia-fixture", help="Optional path to nvidia-smi CSV fixture")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", help="Optional output file path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    rep = build_report(
        model=args.model,
        weight_quant=args.weight_quant,
        kv_quant=args.kv_quant,
        context_length=args.context_length,
        batch_seqs=args.batch_seqs,
        vram_budget_gb=args.vram_budget_gb,
        context_file=Path(args.context_file) if args.context_file else None,
        nvidia_fixture=Path(args.nvidia_fixture) if args.nvidia_fixture else None,
    )
    if rep.get("status") == "error":
        print(json.dumps(rep), file=sys.stderr)
        return 2
    rendered = render_markdown(rep) if args.format == "markdown" else json.dumps(rep, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
