# Model Context Protocol (MCP) Server Conversion Roadmap (`pg-query-surgeon`)

> **Scope Note**: This document defines the engineering blueprint for exposing `pg-query-surgeon` as a standalone Model Context Protocol (MCP) server (`pg-query-surgeon-mcp`). The current repository operates as a zero-dependency Agent Skill (`SKILL.md` + CLI scripts) with no external MCP SDK runtime requirement.

## 1. Proposed MCP Server Architecture
The MCP server wraps the existing deterministic Python core modules (`scripts/common.py`, `scripts/check_migration_safety.py`, `scripts/analyze_sql.py`, `scripts/analyze_explain.py`, `scripts/inspect_schema.py`, `scripts/index_advisor.py`) behind a thin JSON-RPC 2.0 adapter layer:
- **Core Domain Layer (Already Implemented)**: Pure Python standard-library analyzers, parsers, credential scrubbers, and `validate_against_schema()` validators in `scripts/`.
- **MCP Adapter Layer (Future `mcp_server/server.py`)**: Maps MCP `tools/list`, `tools/call`, `resources/list`, `resources/read`, and `prompts/get` requests directly to the pure Python functions in `scripts/`, avoiding subprocess spawning overhead for in-process Python modules while retaining `run_bounded_command()` for external OS utilities.

## 2. Reusable Core Functionality
All business logic in `scripts/common.py`, `scripts/check_migration_safety.py`, `scripts/analyze_sql.py`, `scripts/analyze_explain.py`, `scripts/inspect_schema.py`, `scripts/index_advisor.py` is already structured as importable, side-effect-free Python functions returning deterministic dictionaries validated against `schemas/*.schema.json`. Zero core analysis logic needs to be rewritten for MCP conversion.

## 3. Proposed MCP Tools, Input Schemas & Output Schemas

| Tool Name | Purpose | Input JSON Schema | Output JSON Schema |
| :--- | :--- | :--- | :--- |
| `check_migration_safety` | Statement-order and transaction-aware PostgreSQL DDL lock and rewrite analyzer. | `{"type":"object","required":["sql_text"],"properties":{"sql_text":{"type":"string"},"pg_version":{"type":"integer","default":16}}}` | `schemas/*.schema.json` |
| `analyze_sql_queries` | Detect non-SARGable predicates, leading-wildcard LIKE, deep OFFSET, and N+1 query patterns. | `{"type":"object","required":["sql_text"],"properties":{"sql_text":{"type":"string"}}}` | `schemas/*.schema.json` |
| `analyze_explain_plan` | Analyze PostgreSQL EXPLAIN (FORMAT JSON or TEXT) plans for seq scans, misestimates, and disk spills. | `{"type":"object","required":["explain_input"],"properties":{"explain_input":{"type":"string"}}}` | `schemas/*.schema.json` |
| `inspect_schema_and_catalog` | Audit DDL schema and optional pg_stat_user_tables / pg_index snapshot for missing PKs, unindexed FKs, and bloat. | `{"type":"object","required":["schema_sql"],"properties":{"schema_sql":{"type":"string"},"catalog_snapshot":{"type":"object"}}}` | `schemas/*.schema.json` |
| `recommend_indexes` | Synthesize Equality-Sort-Range composite CREATE INDEX CONCURRENTLY statements. | `{"type":"object","required":["sql_text"],"properties":{"sql_text":{"type":"string"}}}` | `schemas/*.schema.json` |

## 4. Proposed MCP Resources
- **`pg-surgeon://references/lock-matrix`**: PostgreSQL DDL lock conflict and online alternative matrix
- **`pg-surgeon://schemas/diagnostic-output`**: JSON Schema for migration and query analysis outputs

## 5. Reusable Workflow Prompts
- **`review-migration-pr`**: Pre-merge zero-downtime migration review and expand-and-contract rewrite
- **`optimize-slow-query-plan`**: Step-by-step EXPLAIN ANALYZE bottleneck diagnosis and index recommendation

## 6. Permission Boundaries & Security Requirements
- **Read-Only Default Execution**: All diagnostic tools execute in read-only mode. Any opt-in active profiler or file-scaffolding tool requires explicit boolean confirmation parameters (`enable_active_profiling=true` or `dry_run=false`) and path-traversal validation (`resolve_safe_child_path`).
- **Mandatory Output Sanitization**: Every MCP tool response passes through the centralized credential redaction pipeline (`redact_credentials` / `scrub_text_secrets`) before serialization over JSON-RPC.
- **True Streaming Subprocess Limits**: All external binary invocations enforce `run_bounded_command()` with streaming byte caps (`64 KiB` default), `shell=False`, process-group termination on limit/timeout violation, a strict executable allowlist, and refusal of mutating subcommands.

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
