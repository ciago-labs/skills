# Model Context Protocol (MCP) Server Conversion Roadmap (`docker-forensics`)

> **Scope Note**: This document defines the engineering blueprint for exposing `docker-forensics` as a standalone Model Context Protocol (MCP) server (`docker-forensics-mcp`). The current repository operates as a zero-dependency Agent Skill (`SKILL.md` + CLI scripts) with no external MCP SDK runtime requirement.

## 1. Proposed MCP Server Architecture
The MCP server wraps the existing deterministic Python core modules (`scripts/common.py`, `scripts/inspect_docker.py`, `scripts/analyze_image.py`, `scripts/analyze_layers.py`, `scripts/audit_container_security.py`, `scripts/inspect_network.py`, `scripts/diagnose_crashes.py`) behind a thin JSON-RPC 2.0 adapter layer:
- **Core Domain Layer (Already Implemented)**: Pure Python standard-library analyzers, parsers, credential scrubbers, and `validate_against_schema()` validators in `scripts/`.
- **MCP Adapter Layer (Future `mcp_server/server.py`)**: Maps MCP `tools/list`, `tools/call`, `resources/list`, `resources/read`, and `prompts/get` requests directly to the pure Python functions in `scripts/`, avoiding subprocess spawning overhead for in-process Python modules while retaining `run_bounded_command()` for external OS utilities.

## 2. Reusable Core Functionality
All business logic in `scripts/common.py`, `scripts/inspect_docker.py`, `scripts/analyze_image.py`, `scripts/analyze_layers.py`, `scripts/audit_container_security.py`, `scripts/inspect_network.py`, `scripts/diagnose_crashes.py` is already structured as importable, side-effect-free Python functions returning deterministic dictionaries validated against `schemas/*.schema.json`. Zero core analysis logic needs to be rewritten for MCP conversion.

## 3. Proposed MCP Tools, Input Schemas & Output Schemas

| Tool Name | Purpose | Input JSON Schema | Output JSON Schema |
| :--- | :--- | :--- | :--- |
| `inspect_container_safe` | Inspect container configuration with mandatory Config.Env and credential redaction. | `{"type":"object","required":["inspect_json"],"properties":{"inspect_json":{"type":"object"}}}` | `schemas/*.schema.json` |
| `analyze_dockerfile_and_layers` | Audit Dockerfile and layer history across Go, Rust, Node.js, and Python for bloat and ABI issues. | `{"type":"object","required":["dockerfile_text"],"properties":{"dockerfile_text":{"type":"string"},"dockerignore_text":{"type":"string"},"layers":{"type":"array"}}}` | `schemas/*.schema.json` |
| `audit_container_security` | Audit root execution, Privileged mode, CapAdd, docker.sock mounts, and baked-in secrets. | `{"type":"object","properties":{"inspect_json":{"type":"object"},"dockerfile_text":{"type":"string"}}}` | `schemas/*.schema.json` |
| `diagnose_container_crash` | Distinguish confirmed OOMKilled, ExitCode 137 SIGKILL, ExitCode 139 SIGSEGV, restart loops, and K8s CrashLoopBackOff. | `{"type":"object","required":["inspect_json"],"properties":{"inspect_json":{"type":"object"},"k8s_pod_json":{"type":"object"}}}` | `schemas/*.schema.json` |
| `inspect_container_network` | Diagnose default bridge DNS limitations, unmapped ports, and 127.0.0.1 loopback binding traps. | `{"type":"object","required":["inspect_json"],"properties":{"inspect_json":{"type":"object"},"network_json":{"type":"object"}}}` | `schemas/*.schema.json` |

## 4. Proposed MCP Resources
- **`docker-forensics://references/exit-codes`**: Linux container signal and exit code forensics matrix
- **`docker-forensics://schemas/diagnostic-output`**: JSON Schema for container forensics reports

## 5. Reusable Workflow Prompts
- **`triage-container-crashloop`**: Correlate container exit codes, OOMKilled state, healthchecks, and K8s pod status
- **`harden-and-slim-dockerfile`**: Multi-stage and non-root security remediation workflow

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
