# Reproducible Benchmarks (`local-vram-tuner`)

## Benchmark 1: KV-Cache Quantization Comparison on 6.0 GiB VRAM Budget (`qwen2.5-coder-7b`)
```bash
# FP16 KV cache at 32k context (exceeds 6.0 GiB budget: 4.25 GiB weights + 1.75 GiB KV + 0.50 GiB overhead = 6.50 GiB)
python3 scripts/kv_cache_estimator.py --model qwen2.5-coder-7b --weight-quant Q4_K_M --kv-quant FP16 --context-length 32768 --vram-budget-gb 6.0 --pretty

# Q8_0 KV cache at 32k context (fits within 6.0 GiB budget: 4.25 GiB weights + 0.93 GiB KV + 0.50 GiB overhead = 5.68 GiB)
python3 scripts/kv_cache_estimator.py --model qwen2.5-coder-7b --weight-quant Q4_K_M --kv-quant Q8_0 --context-length 32768 --vram-budget-gb 6.0 --pretty
```

## Benchmark 2: Context Compaction & Credential Redaction Benchmark
```bash
python3 scripts/compact_context.py --input-file examples/bloated_agent_context.txt --output-file examples/compacted_context.txt --pretty
```

## Recording Terminal Demonstrations
```bash
asciinema rec -i 1.5 demo-local-vram-tuner.cast
python3 scripts/generate_optimization_report.py --model qwen2.5-coder-7b --weight-quant Q4_K_M --kv-quant FP16 --context-length 32768 --vram-budget-gb 6.0 --context-file examples/bloated_agent_context.txt --nvidia-fixture tests/fixtures/nvidia_smi_rtx4060_6gb.csv --format markdown
exit
```
