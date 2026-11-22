# Model Context Protocol (MCP) Server Conversion Roadmap (`stack-architect`)

> **Scope Note**: This document defines the engineering blueprint for exposing `stack-architect` as a standalone Model Context Protocol (MCP) server (`stack-architect-mcp`). The current repository operates as a zero-dependency Agent Skill (`SKILL.md` + CLI scripts) with no external MCP SDK runtime requirement.

## 1. Proposed MCP Server Architecture
The MCP server wraps the existing deterministic Python core modules (`scripts/common.py`, `scripts/requirements_validator.py`, `scripts/workload_calculator.py`, `scripts/infrastructure_sizer.py`, `scripts/cost_estimator.py`, `scripts/stack_selector.py`, `scripts/generate_architecture.py`, `scripts/scaffold_infrastructure.py`, `scripts/validate_blueprint.py`) behind a thin JSON-RPC 2.0 adapter layer:
- **Core Domain Layer (Already Implemented)**: Pure Python standard-library analyzers, parsers, credential scrubbers, and `validate_against_schema()` validators in `scripts/`.
- **MCP Adapter Layer (Future `mcp_server/server.py`)**: Maps MCP `tools/list`, `tools/call`, `resources/list`, `resources/read`, and `prompts/get` requests directly to the pure Python functions in `scripts/`, avoiding subprocess spawning overhead for in-process Python modules while retaining `run_bounded_command()` for external OS utilities.

## 2. Reusable Core Functionality
All business logic in `scripts/common.py`, `scripts/requirements_validator.py`, `scripts/workload_calculator.py`, `scripts/infrastructure_sizer.py`, `scripts/cost_estimator.py`, `scripts/stack_selector.py`, `scripts/generate_architecture.py`, `scripts/scaffold_infrastructure.py`, `scripts/validate_blueprint.py` is already structured as importable, side-effect-free Python functions returning deterministic dictionaries validated against `schemas/*.schema.json`. Zero core analysis logic needs to be rewritten for MCP conversion.

## 3. Proposed MCP Tools, Input Schemas & Output Schemas

| Tool Name | Purpose | Input JSON Schema | Output JSON Schema |
| :--- | :--- | :--- | :--- |
| `validate_requirements` | Validate 18 product/operational constraints and build an explicit Assumptions Register. | `{"type":"object","required":["constraints"],"properties":{"constraints":{"type":"object"}}}` | `schemas/*.schema.json` |
| `calculate_workload_and_sizing` | Compute 1x/2x/5x RPS, Little's Law concurrency, DB IOPS, and vCPU/RAM/NVMe sizing. | `{"type":"object","required":["constraints"],"properties":{"constraints":{"type":"object"}}}` | `schemas/*.schema.json` |
| `estimate_cloud_costs` | Compare verified AWS, GCP, Azure, and Hetzner AX42 rate cards against monthly budget. | `{"type":"object","required":["constraints"],"properties":{"constraints":{"type":"object"},"custom_pricing":{"type":"array"}}}` | `schemas/*.schema.json` |
| `compile_architecture_blueprint` | Select a 13-layer technology stack with 7-point justifications, Mermaid diagram, and ADRs. | `{"type":"object","required":["constraints"],"properties":{"constraints":{"type":"object"}}}` | `schemas/*.schema.json` |
| `scaffold_day0_infrastructure` | Generate runtime-matched (Go/Rust/Node/Python) Dockerfile, Compose, SQL, and Caddy scaffold. | `{"type":"object","required":["constraints","output_dir"],"properties":{"constraints":{"type":"object"},"output_dir":{"type":"string"},"dry_run":{"type":"boolean","default":true}}}` | `schemas/*.schema.json` |

## 4. Proposed MCP Resources
- **`stack-architect://catalog/verified-pricing`**: Verified cloud and Hetzner dedicated server rate card with source URLs
- **`stack-architect://schemas/all`**: Domain JSON Schemas for requirements, sizing, pricing, architecture, and scaffolding

## 5. Reusable Workflow Prompts
- **`design-day0-system-blueprint`**: Interactive constraint gathering followed by sizing, cost comparison, and stack compilation
- **`generate-and-validate-scaffold`**: Dry-run and materialize a runtime-matched Day-0 repository scaffold

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
