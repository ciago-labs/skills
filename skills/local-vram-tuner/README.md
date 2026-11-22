# local-vram-tuner

**Hardware-Aware Local LLM VRAM, KV-Cache, Context Window, and Prompt Optimization Skill**

## 1. Project Name and Positioning
`local-vram-tuner` is a deterministic [Agent Skill](https://agentskills.io/specification) built for developers running local AI coding agents via Ollama, `llama.cpp`, or vLLM on workstations, laptops, and local servers.

## 2. Problem Statement
Local coding agents frequently degrade from 40+ tokens/sec to <5 tokens/sec when the prompt context window expands and overflows free GPU VRAM into system RAM over PCIe. Developers often confuse weight quantization (`Q4_K_M`) with KV-cache quantization (`FP16` vs `Q8_0`), or feed thousands of lines of repetitive stack traces and lockfile noise into constrained context windows.

## 3. What the Skill Actually Does
`local-vram-tuner` probes host RAM and GPU VRAM (NVIDIA CUDA, AMD ROCm, Apple Silicon Unified Memory, and Linux CPU fallback), calculates exact transformer KV-cache requirements across quantizations, inspects runtime environment flags, and compacts bloated agent prompts while redacting secrets.

## 4. Key Features
- **Multi-Vendor Hardware Discovery**: Supports `nvidia-smi`, `rocm-smi`, macOS `sysctl` Unified Memory, and Linux `/proc/meminfo`.
- **Exact GQA/MHA KV-Cache Math**: Accounts for layers, KV heads, head dimension, `FP16`/`BF16`/`Q8_0`/`Q4_0` KV element sizes, concurrent sequences, and compute buffer overhead.
- **Deterministic Context Compaction Engine**: Strips duplicate log lines, truncates deep stack traces, removes lockfile checksums, and redacts credentials without modifying source files.
- **Read-Only Runtime Inspector**: Audits Ollama, `llama.cpp`, and vLLM settings without stopping or unloading active models.

## 5. Architecture Overview
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the four-component architecture (`hardware_probe.py`, `gpu_probe.py`, `kv_cache_estimator.py`, `context_analyzer.py`, `compact_context.py`, `runtime_inspector.py`, and `generate_optimization_report.py`).

## 6. Installation
Install with any Agent Skills-compatible client or CLI:
```bash
npx skills add ciago-labs/skills --skill local-vram-tuner
```
Or copy the `local-vram-tuner/` directory into your agent's configured skills folder.

## 7. Supported Agent Environments
See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## 8. Prerequisites
- Python 3.8+ (standard library only).
- Optional hardware utilities (`nvidia-smi`, `rocm-smi`, `sysctl`) are auto-detected.

## 9. Usage Examples
- *"Use `local-vram-tuner` to calculate the maximum safe context window for `qwen2.5-coder-7b` (`Q4_K_M`) on my 6 GB RTX 4060 GPU."*
- *"Compact `examples/bloated_agent_context.txt` and redact any leaked tokens before sending it to Ollama."*

## 10. Script Examples
```bash
python3 scripts/hardware_probe.py --pretty
python3 scripts/gpu_probe.py --nvidia-fixture tests/fixtures/nvidia_smi_rtx4060_6gb.csv --pretty
python3 scripts/kv_cache_estimator.py --model qwen2.5-coder-7b --weight-quant Q4_K_M --kv-quant Q8_0 --context-length 32768 --vram-budget-gb 6.0 --pretty
python3 scripts/context_analyzer.py --input-file examples/bloated_agent_context.txt --pretty
python3 scripts/compact_context.py --input-file examples/bloated_agent_context.txt --output-file examples/compacted_context.txt --pretty
python3 scripts/generate_optimization_report.py --model qwen2.5-coder-7b --weight-quant Q4_K_M --kv-quant FP16 --context-length 32768 --vram-budget-gb 6.0 --context-file examples/bloated_agent_context.txt --nvidia-fixture tests/fixtures/nvidia_smi_rtx4060_6gb.csv --format markdown --output examples/sample-optimization-report.md
```

## 11. Example Diagnostic Results
See [`examples/sample-optimization-report.md`](examples/sample-optimization-report.md) and [`examples/sample-optimization-report.json`](examples/sample-optimization-report.json).

## 12. Security and Safety Approach
- Never stops, restarts, or unloads running models.
- Never overwrites source context files in place.
- Redacts API keys and tokens automatically. See [`docs/SECURITY.md`](docs/SECURITY.md).

## 13. Limitations
- Token counts are labeled `heuristic_char_div_4_estimate` (~4 chars/token) so the tool runs with zero external tokenizer dependencies.
- Unknown custom models require explicit `--params-b`, `--layers`, and `--kv-heads` arguments rather than guessing architecture parameters.

## 14. Testing Instructions
```bash
python3 -m unittest discover -s tests -v
```

## 15. Contribution Instructions
See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## 16. Roadmap
- Add GGUF header binary reader to extract `hparams` directly from local `.gguf` files.
- Add Apple Metal bandwidth estimator for M1/M2/M3/M4 Pro/Max/Ultra chips.

## 17. License
MIT License. See [`LICENSE`](LICENSE).
