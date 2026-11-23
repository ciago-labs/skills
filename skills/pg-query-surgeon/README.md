# pg-query-surgeon

**PostgreSQL Query Optimization, Migration Safety, and Execution Plan Analyzer Agent Skill**

## 1. Project Name and Positioning
`pg-query-surgeon` is a production-ready [Agent Skill](https://agentskills.io/specification) that prevents outage-inducing PostgreSQL schema migrations and diagnoses slow SQL queries and `EXPLAIN ANALYZE` execution plans before they hit production.

## 2. Problem Statement
Most database outages during deployments are caused by migrations that acquire `ACCESS EXCLUSIVE` or `SHARE` locks on high-traffic tables without a `lock_timeout`, triggering lock-queue convoys that stall all application reads and writes. Similarly, slow query regressions stem from non-SARGable predicates, unindexed foreign keys, deep `OFFSET` pagination, and disk sort spills that are easily caught by deterministic analysis.

## 3. What the Skill Actually Does
`pg-query-surgeon` provides six standalone Python tools that audit SQL migrations for locking and rewrite hazards, inspect DDL schemas for structural defects, detect query anti-patterns and N+1 loops, parse `EXPLAIN (FORMAT JSON)` execution trees, recommend Equality-Sort-Range composite indexes, and produce step-by-step zero-downtime migration runbooks.

## 4. Key Features
- **Migration Lock & Rewrite Hazard Detector**: Catches non-concurrent `CREATE INDEX`, `CONCURRENTLY` inside transaction blocks, `ALTER COLUMN TYPE` table rewrites, volatile `ADD COLUMN ... DEFAULT`, unvalidated `SET NOT NULL` scans, unguarded `ADD CONSTRAINT FOREIGN KEY`, and missing `lock_timeout`.
- **PostgreSQL Version-Aware Rules**: Accounts for metadata-only `ADD COLUMN ... DEFAULT` in PostgreSQL 11+ and `CHECK ... NOT VALID` optimizations in PostgreSQL 12+.
- **Execution Plan Analyzer (`EXPLAIN FORMAT JSON`)**: Identifies high-filter sequential scans, cardinality misestimates (`>=10x`), external disk sort spills (`Sort Space Type: Disk`), and high-loop nested joins.
- **Schema & Foreign Key Inspector**: Flags tables missing a `PRIMARY KEY`, unindexed `FOREIGN KEY` columns, and 32-bit `INT`/`SERIAL` key exhaustion risks.
- **Automatic Credential Redaction**: Strips database passwords and connection URIs before emitting JSON or Markdown reports.

## 5. Architecture Overview
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the modular five-analyzer pipeline (`check_migration_safety.py`, `analyze_sql.py`, `analyze_explain.py`, `inspect_schema.py`, `index_advisor.py`, and `generate_migration_report.py`).

## 6. Installation
```bash
# Hermes Agent
hermes skills install ciago-labs/skills/skills/pg-query-surgeon

# Cursor, Codex, Gemini CLI, OpenCode and other agents (no local security scan: review the source first)
npx skills add ciago-labs/skills --skill pg-query-surgeon

# Manual copy, run from the root of a clone of the repository
cp -r skills/pg-query-surgeon ~/.claude/skills/pg-query-surgeon   # Claude Code
cp -r skills/pg-query-surgeon ~/.agents/skills/pg-query-surgeon   # Codex and others
```

## 7. Supported Agent Environments
See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md) for compatibility status across Claude Code, OpenAI Codex, Gemini CLI, Google Antigravity, OpenCode, and Hermes Agent.

## 8. Prerequisites
- Python 3.8+ (standard library only; zero external dependencies required for offline analysis).
- Optional: `psql` client when the user explicitly runs read-only catalog queries against a live database.

## 9. Usage Examples
- *"Run `pg-query-surgeon` on `db/migrations/20261117_alter_orders.sql` and rewrite it as a zero-downtime expand-and-contract migration."*
- *"Analyze `examples/slow_explain_plan.json` with `pg-query-surgeon` and recommend the exact `CREATE INDEX CONCURRENTLY` statement."*

## 10. Script Examples
```bash
python3 scripts/check_migration_safety.py --sql-file examples/unsafe_migration.sql --pg-version 16 --pretty
python3 scripts/analyze_sql.py --sql-file examples/slow_queries.sql --pretty
python3 scripts/analyze_explain.py --explain-file examples/slow_explain_plan.json --pretty
python3 scripts/inspect_schema.py --schema-file examples/schema.sql --pretty
python3 scripts/index_advisor.py --sql-file examples/slow_queries.sql --explain-file examples/slow_explain_plan.json --pretty
python3 scripts/generate_migration_report.py --migration-file examples/unsafe_migration.sql --query-file examples/slow_queries.sql --explain-file examples/slow_explain_plan.json --schema-file examples/schema.sql --format markdown --output examples/sample-migration-report.md
```

## 11. Example Diagnostic Results
See [`examples/sample-migration-report.md`](examples/sample-migration-report.md) and [`examples/sample-migration-report.json`](examples/sample-migration-report.json).

## 12. Security and Safety Approach
- Never executes arbitrary SQL or runs migrations automatically.
- Redacts connection strings and passwords automatically.
- Explicitly guards against running `EXPLAIN ANALYZE` on mutating statements. See [`docs/SECURITY.md`](docs/SECURITY.md).

## 13. Limitations
- Uses deterministic regex/token parsing rather than embedding the full C `libpg_query` grammar, so deeply nested CTEs or procedural PL/pgSQL blocks are analyzed heuristically.
- MySQL and Redis support is scoped to architectural reference guidance in `references/technical-reference.md`.

## 14. Testing Instructions
```bash
python3 -m unittest discover -s tests -v
```

## 15. Contribution Instructions
See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## 16. Roadmap
- Add optional `pg_stat_statements` JSON dump ingestion.
- Add partitioning key advisor for time-series tables exceeding 100 GB.

## 17. License
MIT License. See [`LICENSE`](LICENSE).
