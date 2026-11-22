# Local LLM Hardware & KV-Cache Optimization Report (`local-vram-tuner`)

- **Status**: `WARNING`
- **Acceleration Backend**: `cuda` (GPUs detected: `1`, Free VRAM: `5.6 GiB`)
- **System RAM Available**: `6.92 GiB` / `7.76 GiB`

## 1. Model Weight & KV-Cache Memory Breakdown

- **Model**: `qwen2.5-coder-7b` (`Q4_K_M` weights, `FP16` KV cache)
- **Model Weights**: `4.263 GiB`
- **KV-Cache Allocation**: `1.75 GiB` (`56.0 KiB/token/seq`)
- **Runtime Overhead**: `0.5 GiB`
- **Total Estimated Memory**: `6.513 GiB` vs Budget `6.0 GiB` (Fits in VRAM: `False`)
- **Max Recommended Safe Context Window**: `23040 tokens`

## 2. Prompt Context Compaction Summary

- **Estimated Tokens (Before -> After)**: `1347` -> `222` (`-83.52%`, method: `heuristic_char_div_4_estimate`)
- **Credentials Redacted**: `0`
- **Noise Removed**: `13` duplicate log lines, `8` stack frames, `20` lockfile lines

## 3. Recommended Runtime Adjustments

- Keep at least 1.5 GiB of host RAM free for OS and coding agent processes when sizing local LLM models.
- Target model weights + KV cache within 5.04 GiB to avoid PCIe CPU layer offloading.
- Reduce num_ctx to <= 23040 tokens, set KV cache quantization to Q8_0/Q4_0 (OLLAMA_KV_CACHE_TYPE=q8_0), or set parallel sequences to 1.
- Export OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0 for constrained VRAM hosts.
- For llama.cpp server, pass `--flash-attn -ctk q8_0 -ctv q8_0 -np 1` to minimize KV-cache overhead.
- For vLLM on constrained GPUs, tune `--max-model-len`, `--gpu-memory-utilization 0.90`, and `--kv-cache-dtype fp8` where supported.
