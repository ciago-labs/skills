# Model Context Protocol (MCP) Server Conversion Roadmap (`local-vram-tuner`)

> **Scope Note**: This document defines the engineering blueprint for exposing `local-vram-tuner` as a standalone Model Context Protocol (MCP) server (`local-vram-tuner-mcp`). The current repository operates as a zero-dependency Agent Skill (`SKILL.md` + CLI scripts) with no external MCP SDK runtime requirement.

## 1. Proposed MCP Server Architecture
The MCP server wraps the existing deterministic Python core modules (`scripts/common.py`, `scripts/hardware_probe.py`, `scripts/gpu_probe.py`, `scripts/kv_cache_estimator.py`, `scripts/context_analyzer.py`, `scripts/compact_context.py`, `scripts/runtime_inspector.py`) behind a thin JSON-RPC 2.0 adapter layer:
- **Core Domain Layer (Already Implemented)**: Pure Python standard-library analyzers, parsers, credential scrubbers, and `validate_against_schema()` validators in `scripts/`.
- **MCP Adapter Layer (Future `mcp_server/server.py`)**: Maps MCP `tools/list`, `tools/call`, `resources/list`, `resources/read`, and `prompts/get` requests directly to the pure Python functions in `scripts/`, avoiding subprocess spawning overhead for in-process Python modules while retaining `run_bounded_command()` for external OS utilities.

## 2. Reusable Core Functionality
All business logic in `scripts/common.py`, `scripts/hardware_probe.py`, `scripts/gpu_probe.py`, `scripts/kv_cache_estimator.py`, `scripts/context_analyzer.py`, `scripts/compact_context.py`, `scripts/runtime_inspector.py` is already structured as importable, side-effect-free Python functions returning deterministic dictionaries validated against `schemas/*.schema.json`. Zero core analysis logic needs to be rewritten for MCP conversion.

## 3. Proposed MCP Tools, Input Schemas & Output Schemas

| Tool Name | Purpose | Input JSON Schema | Output JSON Schema |
| :--- | :--- | :--- | :--- |
| `probe_hardware_and_gpus` | Detect CPU, system RAM, Apple Silicon Unified Memory/Metal, NVIDIA CUDA, and AMD ROCm VRAM. | `{"type":"object","properties":{"proc_root":{"type":"string","default":"/proc"}}}` | `schemas/*.schema.json` |
| `estimate_kv_cache_vram` | Calculate exact model weight and block-quantized KV-cache VRAM budget and safe context window. | `{"type":"object","required":["model"],"properties":{"model":{"type":"string"},"weight_quant":{"type":"string","default":"Q4_K_M"},"kv_quant":{"type":"string","default":"Q8_0"},"context_length":{"type":"integer","default":32768},"batch_seqs":{"type":"integer","default":1},"vram_budget_gb":{"type":"number"}}}` | `schemas/*.schema.json` |
| `analyze_prompt_context` | Scan prompt context for duplicate logs, stack traces, build artifacts, large JSON, and secrets. | `{"type":"object","required":["text"],"properties":{"text":{"type":"string"}}}` | `schemas/*.schema.json` |
| `compact_prompt_context` | Deterministically compact bloated context and redact PEM private keys and API credentials. | `{"type":"object","required":["text"],"properties":{"text":{"type":"string"},"max_stack_frames":{"type":"integer","default":4}}}` | `schemas/*.schema.json` |

## 4. Proposed MCP Resources
- **`vram-tuner://presets/models`**: Verified architectural presets for Qwen2.5-Coder and Llama-3.1
- **`vram-tuner://references/kv-math`**: GGML block quantization (Q8_0, Q4_0) and PagedAttention equations

## 5. Reusable Workflow Prompts
- **`rightsize-local-coding-model`**: Match local GPU VRAM to optimal model quantization, num_ctx, and KV cache dtype
- **`sanitize-and-compact-context`**: Audit and shrink an oversized coding agent prompt before local LLM prefill

## 6. Permission Boundaries & Security Requirements
- **Read-Only Default Execution**: All diagnostic tools execute in read-only mode. Any opt-in active profiler or file-scaffolding tool requires explicit boolean confirmation parameters (`enable_active_profiling=true` or `dry_run=false`) and path-traversal validation (`resolve_safe_child_path`).
- **Mandatory Output Sanitization**: Every MCP tool response passes through the centralized credential redaction pipeline (`redact_credentials` / `scrub_text_secrets`) before serialization over JSON-RPC.
- **True Streaming Subprocess Limits**: All external binary invocations enforce `run_bounded_command()` with streaming byte caps (`64 KiB` default), `shell=False`, process-group termination on limit/timeout violation, and hard blocks on privilege-escalation wrappers and mutating subcommands.

## 7. Transport Plan: `stdio` and Streamable HTTP
1. **`stdio` Transport (Local IDE & CLI Agents)**:
   - Entrypoint: `python3 -m mcp_server --transport stdio`
   - Communicates over newline-delimited JSON-RPC 2.0 on `stdin`/`stdout`, logging diagnostic errors exclusively to `stderr`.
2. **Streamable HTTP Transport (Remote / Containerized Agent Gateways)**:
   - Entrypoint: `python3 -m mcp_server --transport streamable-http --host 127.0.0.1 --port 8765`
   - Implements the MCP `/mcp` single-endpoint POST/GET SSE streamable HTTP specification with request body size limits (`<= 1 MiB`) and per-request execution timeouts.

## 8. Authentication and Access-Control Requirements
- **`stdio` Mode**: Inherits local OS user UID/GID and Linux capability bounding set; never escalates privileges.
- **Streamable HTTP Mode**: Binds to `127.0.0.1` by default. When exposed across a network, requires `Authorization: Bearer <token>` validated via constant-time comparison (`hmac.compare_digest`), mTLS client certificate verification, and origin header validation to prevent DNS rebinding.

## 9. Testing Strategy
- **Contract Tests**: Validate every MCP tool's input and output payload against `schemas/*.schema.json`.
- **Transport Tests**: Verify JSON-RPC 2.0 framing, error codes (`-32602` Invalid Params, `-32603` Internal Error), timeout cancellation, and secret redaction over both `stdio` pipes and HTTP loopback requests.

## 10. Future Implementation Milestones
- **Phase 1 (Completed)**: Deterministic Python core modules, streaming bounded subprocess runner, credential redaction, and formal JSON Schemas.
- **Phase 2**: Add lightweight zero-dependency JSON-RPC 2.0 `stdio` dispatcher (`scripts/mcp_stdio_bridge.py`).
- **Phase 3**: Add Streamable HTTP transport with Bearer token authentication and rate limiting.
