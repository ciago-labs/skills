# Architecture: `pg-query-surgeon`

`pg-query-surgeon` is structured into five modular, offline-capable Python analyzers:
1. **`scripts/check_migration_safety.py`**: Regex and token-based DDL parser that classifies lock severity, detects `CONCURRENTLY` inside transaction blocks, checks PostgreSQL version-specific table rewrite rules, and redacts credentials.
2. **`scripts/analyze_sql.py`**: Detects non-SARGable functions, leading-wildcard `LIKE`, deep `OFFSET` pagination, `NOT IN (SELECT ...)` traps, and repeated N+1 query fingerprints.
3. **`scripts/analyze_explain.py`**: Recursive AST walker for PostgreSQL `EXPLAIN (FORMAT JSON)` trees, measuring buffer cache hit ratios, disk sort spills, sequential scan filter selectivity, and cardinality misestimates.
4. **`scripts/inspect_schema.py` & `scripts/index_advisor.py`**: Identifies missing primary keys, unindexed foreign keys, 4-byte integer exhaustion risks, and synthesizes Equality-Sort-Range composite index DDL.
5. **`scripts/generate_migration_report.py`**: Unifies all four engines into a structured JSON or Markdown report with verification and rollback commands.
