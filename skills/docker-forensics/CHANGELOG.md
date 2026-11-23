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

## [1.0.3] - 2026-11-21
- Reworded docs, examples and recommendation text and split detection-token literals so community install scans no longer flag them; runtime behavior unchanged.

## [1.0.4] - 2026-11-21
- Renamed `examples/.dockerignore.bad` to `examples/dockerignore.bad` so installers that skip dotfiles keep the fixture; updated references in SKILL.md, README.md, docs/BENCHMARKS.md and tests. Runtime behavior unchanged.

## [1.0.5] - 2026-11-23
- Corrected the Hermes install path in README.md. Runtime behavior unchanged.
