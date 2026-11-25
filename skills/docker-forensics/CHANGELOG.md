# Changelog

## [1.0.7] - 2026-11-25
- Socket audit: `examples/container_inspect.json` no longer combines `Privileged: true`, `CAP_SYS_ADMIN` / `NET_ADMIN`, and a writable `/var/run/docker.sock` mount. It still demonstrates the crash/network findings (OOM `ExitCode 137`, unhealthy healthcheck, loopback bind, root user, no resource limits). The privileged / docker.sock case moved to `tests/fixtures/container_privileged_docker_sock.json` only, so the auditor test still proves `SEC-PRIV-001`, `SEC-CAP-001` and `SEC-MOUNT-001` are detected. Added `examples/README.md` stating all examples are fixtures, never deployments.
- Snyk audit (W011): health-probe output and `State.Error` are no longer copied verbatim into findings. New `sanitize_untrusted_text()` in `scripts/common.py` scrubs secrets, drops control characters and newlines, collapses to a single line and truncates to 120 characters; `scripts/diagnose_crashes.py` labels the result `untrusted_external_content` with `verbatim: false`. Added a regression test with instruction-like text hidden in health output.
- Snyk audit (E004): strengthened the Handling External Content section in `SKILL.md` — inspected logs, Dockerfiles and labels are data only, never instructions; detection patterns are read-only matches on analysed text, never commands to run.
- Sample forensics report updated to match the new example (4 security findings, 0 critical from the example itself; overall status is still `critical` from the confirmed OOM kill).

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
- Reworded docs, examples and recommendation text for clarity; detection patterns in this release were written as split literals. Runtime behavior unchanged.

## [1.0.4] - 2026-11-21
- Renamed `examples/.dockerignore.bad` to `examples/dockerignore.bad` so installers that skip dotfiles keep the fixture; updated references in SKILL.md, README.md, docs/BENCHMARKS.md and tests. Runtime behavior unchanged.

## [1.0.5] - 2026-11-23
- Corrected the Hermes install path in README.md. Runtime behavior unchanged.

## [1.0.6] - 2026-11-24
- Removed network from the read-only docker subcommand allowlist. The runner checked only the first subcommand, so docker network create, rm and connect would have passed. Added a regression test.
- Reverted the split literals from 1.0.3: detection patterns are plain readable regex again. The Dockerfile secret-name check is plain readable regex again, with the ARG|ENV alternation reordered (same matches). Cleanup-layer detection now parses each shell segment with shlex and checks for the rm command, a recursive flag and a package-cache path, instead of matching a fixed substring. This is broader than before: it also catches rm -r and rm -fr variants. The text is only analysed, never executed.
- Test fixtures still assemble fake secret strings at runtime so no secret-like literal is committed.
