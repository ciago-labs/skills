# Changelog

## [1.0.0] - 2026-11-17
### Added
- Initial release of `local-vram-tuner` with hardware/GPU probes, GQA/MHA KV-cache estimator, deterministic prompt context compactor with secret redaction, runtime inspector, and optimization report generator.

## [1.0.1] - 2026-11-20
- Replaced executable blocklist with a strict hardware-probe allowlist (`nvidia-smi`, `rocm-smi`, `sysctl`, `system_profiler`).
- Centralized `OLLAMA_*` environment variable reads through explicit allowlist helper `read_allowlisted_env()`.
- Detached child stdin (`DEVNULL`) and routed test CLI invocations through `run_bounded_command()`.

## [1.0.2] - 2026-11-21
- Removed nested `.github/` workflow for monorepo compatibility and replaced static PEM/secret fixtures with runtime-assembled test inputs.
- Sanitized example context files and regenerated sample optimization reports with zero literal credentials on disk.
- Added **Scope & Safety Boundaries**, **Handling External Content**, and **Credential Security** sections to `SKILL.md` and updated `README.md` to agent-neutral installation.
- Verified full `unittest` suite passes on a fresh extract after `chmod -x` on every file.
- Fixed the secret scrubber redacting the `token_estimation_method` field in reports; added a regression test.
- Inlined allowlisted environment reads (no key-taking helper) in `common.py` and `runtime_inspector.py`.
- Replaced host and port literals in example logs with a neutral hostname and corrected the sample reports.
- Reworded the privilege-escalation line in `docs/MCP-ROADMAP.md`.

## [1.0.3] - 2026-11-22
- Fixed the optimization report mislabeling GQA models as MHA: the report path now passes the preset query-head count to the estimator (qwen2.5-coder-7b reports 28Q:4KV GQA). KV memory numbers were never affected.
- Corrected the committed sample optimization report.
- Added a regression test covering every model preset.
