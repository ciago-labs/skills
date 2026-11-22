# Security & Safety Model (`local-vram-tuner`)

1. **Read-Only Runtime Inspection**: Never terminates, restarts, or unloads running LLM servers.
2. **Non-Destructive Context Compaction**: `scripts/compact_context.py` enforces that `--output-file` is distinct from `--input-file`.
3. **Credential Redaction**: Automatically scrubs OpenAI keys (`sk-...`), GitHub tokens (`ghp_...`), AWS keys (`AKIA...`), bearer tokens, Private Keys, and `SECRET/PASSWORD` assignments before writing compacted outputs.
