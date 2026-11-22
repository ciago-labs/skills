# Diagnostic Workflows (`local-vram-tuner`)

## Workflow 1: Tuning a 6 GB VRAM Laptop GPU for 16k-32k Coding Context
1. Run `python3 scripts/gpu_probe.py --pretty` to verify free VRAM after display server overhead.
2. Run `python3 scripts/kv_cache_estimator.py --model qwen2.5-coder-7b --weight-quant Q4_K_M --kv-quant Q8_0 --context-length 16384 --vram-budget-gb 5.6 --pretty`.
3. Configure `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, and `OLLAMA_NUM_PARALLEL=1`.
