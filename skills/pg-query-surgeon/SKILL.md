---
name: pg-query-surgeon
description: Analyze PostgreSQL schema migrations for lock hazards and optimize slow SQL queries and EXPLAIN ANALYZE execution plans. Use when reviewing SQL migrations, diagnosing slow PostgreSQL queries, interpreting EXPLAIN plans, recommending composite or partial indexes, or designing zero-downtime expand-and-contract schema changes.
license: MIT
compatibility: Python 3.8+ standard library for offline SQL, DDL, and EXPLAIN JSON/text analysis. Optional live read-only inspection via psql when explicitly requested by the user.
metadata:
  version: "1.0.2"
  category: database-engineering
---

# pg-query-surgeon

PostgreSQL query optimization, migration safety, and execution plan analyzer with scoped supplementary guidance for MySQL and Redis.

## When to Use

- Audit SQL migration files (`ALTER TABLE`, `CREATE INDEX`, `DROP COLUMN`, `ADD CONSTRAINT`) for `ACCESS EXCLUSIVE` table locks, table rewrites, and transaction-wrapping errors before deployment.
- Analyze slow SQL queries for anti-patterns (leading wildcard `LIKE '%foo'`, functions on indexed columns, `SELECT *`, unbounded `OFFSET`, missing join predicates, and N+1 loops).
- Parse PostgreSQL `EXPLAIN (FORMAT JSON)` or text execution plans to detect sequential scans on large tables, row-estimation mispredictions, external disk sorts, hash batch spills, and nested loop amplification.
- Generate composite, covering (`INCLUDE`), or partial (`WHERE`) index recommendations with `CREATE INDEX CONCURRENTLY` syntax.
- Produce zero-downtime expand-and-contract migration runbooks with explicit `lock_timeout`, `statement_timeout`, batch backfill, and rollback steps.

## Safety and Operating Principles

1. **Offline-First Analysis**: Default all SQL, DDL, and `EXPLAIN` plan inspections to static/fixture analysis without connecting to a database.
2. **Never Execute Arbitrary or Mutating SQL**: `EXPLAIN ANALYZE` executes the underlying query. Never run `EXPLAIN ANALYZE` automatically against `INSERT`, `UPDATE`, `DELETE`, `DDL`, or volatile functions, and never assume `BEGIN ... ROLLBACK` makes arbitrary SQL safe on production systems (due to lock acquisition, sequence advancement, and side effects).
3. **Never Run Migrations Against Production**: This skill audits and generates migration plans; it never applies schema migrations automatically.
4. **Strict Credential Redaction**: All connection strings (`postgresql://user:pass@host/db`), passwords, and bearer tokens are scrubbed before any report or JSON output is emitted.
5. **PostgreSQL Version Awareness**: Account for PostgreSQL version differences (for example, `ALTER TABLE ... ADD COLUMN ... DEFAULT <non-volatile>` is metadata-only in PostgreSQL 11+, whereas `ADD COLUMN ... PRIMARY KEY` or `ALTER COLUMN TYPE` still rewrites the table).

## Diagnostic & Optimization Workflow

### Step 1: Audit SQL Migrations for Lock and Rewrite Hazards

```bash
python3 scripts/check_migration_safety.py --sql-file examples/unsafe_migration.sql --pg-version 16 --pretty
```

### Step 2: Analyze SQL Queries for Performance Anti-Patterns and N+1 Risks

```bash
python3 scripts/analyze_sql.py --sql-file examples/slow_queries.sql --pretty
```

### Step 3: Analyze PostgreSQL Execution Plans (`EXPLAIN` JSON or Text)

```bash
python3 scripts/analyze_explain.py --explain-file examples/slow_explain_plan.json --pretty
```

### Step 4: Inspect Schema Definitions and Recommend Targeted Indexes

```bash
python3 scripts/inspect_schema.py --schema-file examples/schema.sql --pretty
python3 scripts/index_advisor.py --sql-file examples/slow_queries.sql --explain-file examples/slow_explain_plan.json --pretty
```

### Step 5: Generate Unified Migration & Query Optimization Report

```bash
python3 scripts/generate_migration_report.py \\
  --migration-file examples/unsafe_migration.sql \\
  --query-file examples/slow_queries.sql \\
  --explain-file examples/slow_explain_plan.json \\
  --schema-file examples/schema.sql \\
  --format markdown \\
  --output migration_report.md
```

## Scoped Supplementary Guidance (MySQL and Redis)

- **MySQL 8.0+**: Use `ALGORITHM=INSTANT` or `ALGORITHM=INPLACE, LOCK=NONE` where supported (`references/technical-reference.md`). Do not use PostgreSQL-specific `CONCURRENTLY` syntax on MySQL.
- **Redis**: Avoid `KEYS *`, unbounded `SMEMBERS`, or large Lua scripts blocking the single-threaded event loop; use `SCAN` and pipelining. Note that `pg-query-surgeon` scripts target PostgreSQL SQL/EXPLAIN directly and provide reference guidance for MySQL/Redis in `references/technical-reference.md`.

## Gotchas

- `CREATE INDEX CONCURRENTLY` cannot run inside a `BEGIN ... COMMIT` transaction block. Many migration frameworks wrap files in transactions by default; always disable transactional wrapping for concurrent index migrations.
- Adding a `NOT NULL` constraint to an existing column requires a full table scan unless backed by a `CHECK (col IS NOT NULL) NOT VALID` constraint that is subsequently validated via `VALIDATE CONSTRAINT` (`SHARE UPDATE EXCLUSIVE` lock).
