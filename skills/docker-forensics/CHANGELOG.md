# Changelog

## [1.0.0] - 2026-11-17
### Added
- Initial release of `docker-forensics` with container config inspector, Dockerfile/layer analyzer, security auditor, network debugger, crash/OOM/Kubernetes analyzer, and forensics report generator.

## [1.0.1] - 2026-11-20
- Enforced strict executable allowlist (`docker` only) and explicit read-only Docker subcommand allowlist (blocking `exec`, `run`, `stop`, `rm`, `prune`, `push`, etc.).
- Added minimal allowlisted child environment (`build_child_env`) and detached child stdin (`DEVNULL`).
- Replaced literal remote-shell pipe evidence string with `remote_script_piped_to_shell` while preserving detection.

## [1.0.2] - 2026-11-21
- Removed nested `.github/` workflow for monorepo placement at `skills/docker-forensics/`.
- Added Handling External Content, Credential Security, and honest scope sections to `SKILL.md`.
- Replaced static fake credentials in examples/fixtures with runtime-assembled test fixtures (zero literal secrets or PEM headers on disk).
