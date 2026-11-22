# Troubleshooting (`stack-architect`)

## 1. `scaffold_infrastructure.py` Refuses to Write to Output Directory
- **Cause**: Safety guard prevents overwriting non-empty directories.
- **Resolution**: Point `--output-dir` to a new path or pass `--force` only when intentional regeneration is desired.
