# Changelog

## [1.0.0] - 2026-11-17
### Added
- Initial release of `pg-query-surgeon` with migration lock analyzer, SQL anti-pattern and N+1 detector, `EXPLAIN (FORMAT JSON)` plan analyzer, schema inspector, composite index advisor, and zero-downtime migration report generator.

## [1.0.1] - 2026-11-20
- Replaced executable blocklist with a strict executable allowlist (`psql` only) and `shutil.which` path resolution.
- Replaced full environment iteration with explicit named-variable allowlist reads in `build_child_env()`.
- Detached child stdin (`DEVNULL`), centralized test CLI execution through `run_bounded_command()`, and updated security documentation.
