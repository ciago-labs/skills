#!/usr/bin/env python3
"""Deterministic LLM weight and KV-cache VRAM calculator with GGML block quantization structure and runtime cache layout."""
import argparse
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope

MODEL_PRESETS: Dict[str, Dict[str, Any]] = {
    "qwen2.5-coder-7b": {
        "params_b": 7.61,
        "num_layers": 28,
        "num_q_heads": 28,
        "num_kv_heads": 4,
        "head_dim": 128,
        "max_position_embeddings": 131072,
        "architecture": "Qwen2 (GQA 28Q/4KV)",
    },
    "qwen2.5-coder-14b": {
        "params_b": 14.7,
        "num_layers": 48,
        "num_q_heads": 40,
        "num_kv_heads": 8,
        "head_dim": 128,
        "max_position_embeddings": 131072,
        "architecture": "Qwen2 (GQA 40Q/8KV)",
    },
    "qwen2.5-coder-32b": {
        "params_b": 32.5,
        "num_layers": 64,
        "num_q_heads": 40,
        "num_kv_heads": 8,
        "head_dim": 128,
        "max_position_embeddings": 131072,
        "architecture": "Qwen2 (GQA 40Q/8KV)",
    },
    "llama-3.1-8b": {
        "params_b": 8.03,
        "num_layers": 32,
        "num_q_heads": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "max_position_embeddings": 131072,
        "architecture": "Llama-3.1 (GQA 32Q/8KV)",
    },
    "deepseek-coder-v2-lite-16b": {
        "params_b": 15.7,
        "num_layers": 27,
        "num_q_heads": 16,
        "num_kv_heads": 16,
        "head_dim": 128,
        "max_position_embeddings": 163840,
        "architecture": "DeepSeek-V2-Lite (MoE)",
    },
    "starcoder2-3b-mqa": {
        "params_b": 3.0,
        "num_layers": 30,
        "num_q_heads": 24,
        "num_kv_heads": 2,
        "head_dim": 128,
        "max_position_embeddings": 16384,
        "architecture": "StarCoder2 (GQA 24Q/2KV)",
    },
}

WEIGHT_BYTES_PER_PARAM: Dict[str, float] = {
    "FP16": 2.0,
    "BF16": 2.0,
    "Q8_0": 1.0625,
    "Q6_K": 0.8203,
    "Q5_K_M": 0.7109,
    "Q4_K_M": 0.6015,
    "Q4_0": 0.5625,
}

# Explicit block structure for KV-cache quantization formats (GGML / vLLM)
KV_QUANT_SPEC: Dict[str, Dict[str, Any]] = {
    "FP16": {
        "block_size": 1,
        "data_bytes_per_block": 2,
        "scale_metadata_bytes_per_block": 0,
        "total_bytes_per_block": 2,
        "effective_bytes_per_element": 2.0,
        "description": "IEEE 754 16-bit float (no block scale overhead)",
    },
    "BF16": {
        "block_size": 1,
        "data_bytes_per_block": 2,
        "scale_metadata_bytes_per_block": 0,
        "total_bytes_per_block": 2,
        "effective_bytes_per_element": 2.0,
        "description": "Brain Floating Point 16-bit (no block scale overhead)",
    },
    "Q8_0": {
        "block_size": 32,
        "data_bytes_per_block": 32,
        "scale_metadata_bytes_per_block": 2,
        "total_bytes_per_block": 34,
        "effective_bytes_per_element": 34.0 / 32.0,
        "description": "GGML block_q8_0: 32 int8 values (32 B) + 1 FP16 scale factor d (2 B) = 34 B per 32 elements",
    },
    "Q4_0": {
        "block_size": 32,
        "data_bytes_per_block": 16,
        "scale_metadata_bytes_per_block": 2,
        "total_bytes_per_block": 18,
        "effective_bytes_per_element": 18.0 / 32.0,
        "description": "GGML block_q4_0: 32 4-bit nibbles (16 B) + 1 FP16 scale factor d (2 B) = 18 B per 32 elements",
    },
}

RUNTIME_CACHE_LAYOUTS: Dict[str, Dict[str, Any]] = {
    "contiguous_ggml": {
        "page_block_tokens": 1,
        "fragmentation_overhead_factor": 1.00,
        "description": "llama.cpp / Ollama contiguous KV ring buffer",
    },
    "paged_attention_vllm": {
        "page_block_tokens": 16,
        "fragmentation_overhead_factor": 1.04,
        "description": "vLLM PagedAttention (16-token blocks + page table & ~4% block fragmentation overhead)",
    },
}


def compute_kv_bytes_per_token_per_seq(
    num_layers: int,
    num_kv_heads: int,
    head_dim: int,
    kv_quant: str,
) -> Dict[str, Any]:
    spec = KV_QUANT_SPEC[kv_quant]
    block_size = spec["block_size"]
    elements_per_head = head_dim
    blocks_per_head = math.ceil(elements_per_head / block_size)
    padded_elements_per_head = blocks_per_head * block_size

    data_bytes_per_token = 2 * num_layers * num_kv_heads * blocks_per_head * spec["data_bytes_per_block"]
    metadata_bytes_per_token = 2 * num_layers * num_kv_heads * blocks_per_head * spec["scale_metadata_bytes_per_block"]
    total_bytes_per_token = data_bytes_per_token + metadata_bytes_per_token

    return {
        "kv_quant": kv_quant,
        "block_size": block_size,
        "blocks_per_head": blocks_per_head,
        "padded_head_dim": padded_elements_per_head,
        "raw_quant_data_bytes_per_token": data_bytes_per_token,
        "block_scale_metadata_bytes_per_token": metadata_bytes_per_token,
        "total_kv_bytes_per_token_per_seq": total_bytes_per_token,
        "effective_bytes_per_element": spec["effective_bytes_per_element"],
    }


def calculate_vram_budget(
    params_b: float,
    num_layers: int,
    num_kv_heads: int,
    head_dim: int,
    weight_quant: str,
    kv_quant: str,
    context_length: int,
    batch_seqs: int = 1,
    runtime_overhead_mib: float = 512.0,
    vram_budget_gb: Optional[float] = None,
    model_name: str = "custom",
    cache_layout: str = "contiguous_ggml",
    num_q_heads: Optional[int] = None,
) -> Dict[str, Any]:
    if weight_quant not in WEIGHT_BYTES_PER_PARAM:
        raise ValueError(f"Unsupported weight quantization '{weight_quant}'. Supported: {list(WEIGHT_BYTES_PER_PARAM)}")
    if kv_quant not in KV_QUANT_SPEC:
        raise ValueError(f"Unsupported KV-cache quantization '{kv_quant}'. Supported: {list(KV_QUANT_SPEC)}")
    if cache_layout not in RUNTIME_CACHE_LAYOUTS:
        raise ValueError(f"Unsupported cache layout '{cache_layout}'. Supported: {list(RUNTIME_CACHE_LAYOUTS)}")
    if context_length <= 0 or batch_seqs <= 0 or num_layers <= 0 or num_kv_heads <= 0 or head_dim <= 0 or params_b <= 0:
        raise ValueError("All architectural and context dimensions must be positive numbers")

    w_bpp = WEIGHT_BYTES_PER_PARAM[weight_quant]
    weight_bytes = int(params_b * 1_000_000_000 * w_bpp)

    kv_token_info = compute_kv_bytes_per_token_per_seq(num_layers, num_kv_heads, head_dim, kv_quant)
    kv_bytes_per_token_per_seq = kv_token_info["total_kv_bytes_per_token_per_seq"]

    layout_spec = RUNTIME_CACHE_LAYOUTS[cache_layout]
    page_tokens = layout_spec["page_block_tokens"]
    aligned_context = math.ceil(context_length / page_tokens) * page_tokens
    raw_kv_total_bytes = int(kv_bytes_per_token_per_seq * aligned_context * batch_seqs)
    kv_total_bytes = int(raw_kv_total_bytes * layout_spec["fragmentation_overhead_factor"])
    kv_metadata_total_bytes = int(kv_token_info["block_scale_metadata_bytes_per_token"] * aligned_context * batch_seqs)

    overhead_bytes = int(runtime_overhead_mib * 1024 * 1024)
    total_bytes = weight_bytes + kv_total_bytes + overhead_bytes

    total_gib = round(total_bytes / (1024**3), 3)
    weight_gib = round(weight_bytes / (1024**3), 3)
    kv_gib = round(kv_total_bytes / (1024**3), 3)
    overhead_gib = round(overhead_bytes / (1024**3), 3)

    q_heads = num_q_heads or num_kv_heads
    if num_kv_heads == 1:
        attention_type = "MQA (Multi-Query Attention)"
    elif num_kv_heads < q_heads:
        attention_type = f"GQA (Grouped-Query Attention {q_heads}Q:{num_kv_heads}KV, {round(q_heads / num_kv_heads, 1)}x KV reduction)"
    else:
        attention_type = "MHA (Multi-Head Attention)"

    max_recommended_context = None
    fits_in_vram = True
    status = "ok"
    findings = []
    recommendations = []

    if vram_budget_gb is not None:
        budget_bytes = int(vram_budget_gb * (1024**3))
        avail_for_kv = budget_bytes - weight_bytes - overhead_bytes
        if avail_for_kv <= 0:
            max_recommended_context = 0
            fits_in_vram = False
            status = "critical"
            findings.append({
                "id": "VRAM-WEIGHT-OOM",
                "category": "vram_exhaustion",
                "severity": "critical",
                "classification": "theoretical_estimate",
                "title": f"Model weights ({weight_gib} GiB) + runtime overhead ({overhead_gib} GiB) exceed VRAM budget ({vram_budget_gb} GiB) before any KV cache allocation",
                "evidence": {
                    "weight_gib": weight_gib,
                    "overhead_gib": overhead_gib,
                    "vram_budget_gib": vram_budget_gb,
                },
                "likely_causes": ["Model parameter count or weight quantization precision exceeds hardware VRAM"],
                "confidence": "high",
                "recommendation": "Switch to a smaller parameter model or lower weight quantization (e.g., Q4_K_M), or offload a subset of layers to system RAM."
            })
        else:
            effective_per_token = kv_bytes_per_token_per_seq * batch_seqs * layout_spec["fragmentation_overhead_factor"]
            raw_max_ctx = int(avail_for_kv // effective_per_token)
            max_recommended_context = (raw_max_ctx // 512) * 512
            if total_bytes > budget_bytes:
                fits_in_vram = False
                status = "warning"
                findings.append({
                    "id": "VRAM-KV-OVERFLOW",
                    "category": "kv_cache_overflow",
                    "severity": "high",
                    "classification": "theoretical_estimate",
                    "title": f"Total estimated memory ({total_gib} GiB) exceeds {vram_budget_gb} GiB VRAM budget at context={context_length} (KV cache consumes {kv_gib} GiB)",
                    "evidence": {
                        "total_gib": total_gib,
                        "vram_budget_gib": vram_budget_gb,
                        "kv_cache_gib": kv_gib,
                        "kv_block_metadata_mib": round(kv_metadata_total_bytes / (1024**2), 2),
                        "max_safe_context_tokens": max_recommended_context,
                    },
                    "likely_causes": [
                        f"Context window ({context_length}) x parallel sequences ({batch_seqs}) overflows free VRAM after loading {weight_gib} GiB weights"
                    ],
                    "confidence": "high",
                    "recommendation": (
                        f"Reduce num_ctx to <= {max_recommended_context} tokens, set KV cache quantization to Q8_0/Q4_0 (OLLAMA_KV_CACHE_TYPE=q8_0), or set parallel sequences to 1."
                    ),
                })

    if not findings:
        findings.append({
            "id": "VRAM-FIT-OK",
            "category": "vram_sizing",
            "severity": "info",
            "classification": "theoretical_estimate",
            "title": f"Model '{model_name}' ({weight_quant} weights, {kv_quant} KV) requires {total_gib} GiB total ({weight_gib} GiB weights + {kv_gib} GiB KV cache)",
            "evidence": {
                "weight_gib": weight_gib,
                "kv_cache_gib": kv_gib,
                "kv_block_metadata_mib": round(kv_metadata_total_bytes / (1024**2), 2),
                "overhead_gib": overhead_gib,
                "total_gib": total_gib,
                "max_safe_context_tokens": max_recommended_context,
            },
            "likely_causes": ["Deterministic KV-cache and block-quantization calculation"],
            "confidence": "high",
            "recommendation": "Configuration fits cleanly within target memory envelope."
        })

    for f in findings:
        recommendations.append(f["recommendation"])

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "value_provenance": "theoretical_estimate",
            "model": model_name,
            "architecture": {
                "params_b": params_b,
                "num_layers": num_layers,
                "num_q_heads": q_heads,
                "num_kv_heads": num_kv_heads,
                "head_dim": head_dim,
                "attention_mechanism": attention_type,
            },
            "quantization": {
                "weight_quant": weight_quant,
                "weight_bytes_per_param": w_bpp,
                "kv_quant": kv_quant,
                "kv_block_spec": KV_QUANT_SPEC[kv_quant],
                "kv_bytes_per_element": KV_QUANT_SPEC[kv_quant]["effective_bytes_per_element"],
            },
            "workload": {
                "context_length": context_length,
                "aligned_context_length": aligned_context,
                "concurrent_sequences": batch_seqs,
                "cache_layout": cache_layout,
                "runtime_overhead_mib": runtime_overhead_mib,
            },
            "memory_breakdown": {
                "model_weights_bytes": weight_bytes,
                "model_weights_gib": weight_gib,
                "kv_cache_bytes": kv_total_bytes,
                "kv_cache_raw_data_bytes": int(kv_token_info["raw_quant_data_bytes_per_token"] * aligned_context * batch_seqs),
                "kv_cache_block_scale_metadata_bytes": kv_metadata_total_bytes,
                "kv_cache_gib": kv_gib,
                "kv_kib_per_token_per_seq": round(kv_bytes_per_token_per_seq / 1024.0, 2),
                "runtime_overhead_gib": overhead_gib,
                "total_estimated_bytes": total_bytes,
                "total_estimated_gib": total_gib,
                "vram_budget_gib": vram_budget_gb,
                "fits_in_vram": fits_in_vram,
                "max_recommended_context": max_recommended_context,
            },
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic KV-cache and model VRAM estimator.")
    parser.add_argument("--model", default="qwen2.5-coder-7b", help=f"Preset name ({', '.join(MODEL_PRESETS)}) or 'custom'")
    parser.add_argument("--params-b", type=float, help="Model parameters in billions (required if --model is custom)")
    parser.add_argument("--layers", type=int, help="Number of transformer layers")
    parser.add_argument("--q-heads", type=int, help="Number of Query attention heads")
    parser.add_argument("--kv-heads", type=int, help="Number of Key/Value attention heads")
    parser.add_argument("--head-dim", type=int, default=128, help="Attention head dimension (default: 128)")
    parser.add_argument("--weight-quant", default="Q4_K_M", choices=list(WEIGHT_BYTES_PER_PARAM.keys()))
    parser.add_argument("--kv-quant", default="FP16", choices=list(KV_QUANT_SPEC.keys()))
    parser.add_argument("--cache-layout", default="contiguous_ggml", choices=list(RUNTIME_CACHE_LAYOUTS.keys()))
    parser.add_argument("--context-length", type=int, default=32768, help="Target context window in tokens")
    parser.add_argument("--batch-seqs", type=int, default=1, help="Concurrent parallel sequences")
    parser.add_argument("--overhead-mib", type=float, default=512.0, help="Compute buffer / CUDA context overhead in MiB")
    parser.add_argument("--vram-budget-gb", type=float, help="Available GPU VRAM budget in GiB")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    if args.model in MODEL_PRESETS:
        preset = MODEL_PRESETS[args.model]
        params_b = args.params_b or preset["params_b"]
        layers = args.layers or preset["num_layers"]
        q_heads = args.q_heads or preset.get("num_q_heads", preset["num_kv_heads"])
        kv_heads = args.kv_heads or preset["num_kv_heads"]
        head_dim = args.head_dim or preset["head_dim"]
    else:
        if not (args.params_b and args.layers and args.kv_heads):
            print(json.dumps(make_error_envelope(
                f"Unknown model preset '{args.model}'. Supply --params-b, --layers, and --kv-heads explicitly instead of guessing architecture."
            )), file=sys.stderr)
            return 2
        params_b = args.params_b
        layers = args.layers
        q_heads = args.q_heads or args.kv_heads
        kv_heads = args.kv_heads
        head_dim = args.head_dim

    try:
        payload = calculate_vram_budget(
            params_b=params_b,
            num_layers=layers,
            num_kv_heads=kv_heads,
            head_dim=head_dim,
            weight_quant=args.weight_quant,
            kv_quant=args.kv_quant,
            context_length=args.context_length,
            batch_seqs=args.batch_seqs,
            runtime_overhead_mib=args.overhead_mib,
            vram_budget_gb=args.vram_budget_gb,
            model_name=args.model,
            cache_layout=args.cache_layout,
            num_q_heads=q_heads,
        )
    except ValueError as exc:
        print(json.dumps(make_error_envelope(str(exc))), file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
