# Diagnostic Workflows (`pg-query-surgeon`)

## Workflow 1: Pre-Merge CI Migration Audit
1. Run `python3 scripts/check_migration_safety.py --sql-file <migration.sql> --pg-version 16 --pretty`.
2. Fail CI or request engineering review whenever `risk_classification` is `HIGH` or `CRITICAL`.
3. Apply the expand-and-contract steps emitted by `scripts/generate_migration_report.py`.

## Workflow 2: Slow Query & EXPLAIN Plan Triage
1. Capture `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on staging or a read replica for `SELECT` queries (never run `EXPLAIN ANALYZE` on mutating statements without explicit precautions).
2. Run `python3 scripts/analyze_explain.py --explain-file plan.json --pretty`.
3. Run `python3 scripts/index_advisor.py --sql-file query.sql --explain-file plan.json --pretty`.
