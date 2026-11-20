# Security & Safety Model (`pg-query-surgeon`)

1. **Zero Automatic SQL Execution**: No script in `pg-query-surgeon` connects to or executes queries against a database by default. All analysis operates on SQL files and captured `EXPLAIN` plans.
2. **Protection Against `EXPLAIN ANALYZE` Side Effects**: Documentation and workflows explicitly warn that `EXPLAIN ANALYZE` executes the query and must never be run automatically on mutating statements (`INSERT`, `UPDATE`, `DELETE`, `DDL`).
3. **Automatic Credential Redaction**: `check_migration_safety.py` and `analyze_sql.py` automatically scrub `postgresql://user:password@host` URI credentials and `password=...` tokens before emitting findings or reports.
