# Changelog

## [1.0.0] - 2026-11-17
### Added
- Initial release of `stack-architect` (`ship-blueprint`) with 18-constraint validator, workload calculator, hardware sizer, verified cloud/bare-metal cost estimator, 13-layer stack selector, 12-section blueprint generator, Day-0 scaffolder, and blueprint validator.

## [1.0.1] - 2026-11-20
- Replaced executable blocklist with a strict executable allowlist (`docker` only for optional Compose syntax validation).
- Added minimal allowlisted child environment (`build_child_env`) and detached child stdin (`DEVNULL`).
- Updated security documentation and regression tests.

## [1.0.2] - 2026-11-21
- Removed nested `.github/` workflows from the skill root and pre-generated example scaffold for monorepo compatibility (runtime scaffold generation still emits `.github/workflows/ci.yml` into target project directories).
- Updated generated Compose and `.env.example` templates to use file-based `POSTGRES_PASSWORD_FILE` secret references and updated Python scaffold healthcheck/server templates to use `argparse` and `http.client` with zero `os.environ` or `curl` references.
- Added **Scope & Safety Boundaries**, **Handling External Content**, and **Credential Security** sections to `SKILL.md` and updated `README.md` to agent-neutral installation.
- Verified full `unittest` suite passes on a fresh extract after `chmod -x` on every file.
- Inlined allowlisted environment reads in `common.py` (no key-taking helper).
- Removed the committed example scaffold, which could not pass validation without dotfiles and a nested workflow; README now generates it on demand.
- Reworded the privilege-escalation line in `docs/MCP-ROADMAP.md`.
