# Architecture: `local-vram-tuner`

1. **Hardware & Accelerator Probes (`hardware_probe.py`, `gpu_probe.py`)**: Detects Linux `/proc/meminfo`, macOS Unified Memory (`sysctl`), NVIDIA GPUs (`nvidia-smi`), and AMD GPUs (`rocm-smi`).
2. **Deterministic KV-Cache Calculator (`kv_cache_estimator.py`)**: Computes exact weight, KV-cache, and compute buffer memory across `FP16`, `BF16`, `Q8_0`, and `Q4_0` KV formats.
3. **Context Analyzer & Compactor (`context_analyzer.py`, `compact_context.py`)**: Removes ANSI escapes, deduplicates log storms, truncates repetitive stack frames, strips lockfile checksums, and redacts credentials without touching original files.
4. **Runtime Inspector & Report Generator (`runtime_inspector.py`, `generate_optimization_report.py`)**: Synthesizes hardware telemetry and KV math into actionable runtime flags.
