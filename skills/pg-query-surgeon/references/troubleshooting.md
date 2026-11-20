# Troubleshooting (`pg-query-surgeon`)

## 1. Invalid `CONCURRENTLY` Index Left Behind After Failed Build
- **Symptom**: `CREATE INDEX CONCURRENTLY` fails due to a deadlock or unique constraint violation, leaving an `INVALID` index in `pg_index` (`indisvalid = false`).
- **Resolution**: PostgreSQL ignores invalid indexes for queries, but they still incur write overhead. Drop the invalid index safely with `DROP INDEX CONCURRENTLY idx_name;` and re-create it.

## 2. `lock_timeout` Exceeded During Migration
- **Symptom**: `ERROR: canceling statement due to lock timeout`.
- **Resolution**: This is the intended safety mechanism preventing lock-queue pileups. Check `pg_stat_activity` for long-running queries on the target table and retry during low-concurrency windows.
