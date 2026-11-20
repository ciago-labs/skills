# Reproducible Benchmarks (`pg-query-surgeon`)

## Benchmark 1: Controlled SQLite / Relational Index Selectivity & Migration Hazard Verification
Because a live PostgreSQL server daemon is not required for the offline test suite, `pg-query-surgeon` provides two reproducible benchmarks:

### A. Fixture-Based PostgreSQL `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` Benchmark
Evaluates a 500,000-row `orders` table plan (`examples/slow_explain_plan.json`) where a `Seq Scan` removes `485,200` rows (`2.96%` selectivity) and spills `16,384 KB` (`2,048` blocks) to disk during an external merge sort:
```bash
python3 scripts/analyze_explain.py --explain-file examples/slow_explain_plan.json --pretty
python3 scripts/index_advisor.py --sql-file examples/slow_queries.sql --explain-file examples/slow_explain_plan.json --pretty
```

### B. Controlled Local Relational Index Benchmark (Python `sqlite3` B-Tree Verification)
To measure the real execution-plan change from a full table scan (`SCAN orders`) to a composite B-Tree index lookup (`SEARCH orders USING INDEX idx_orders_customer_id_status_created_at`) on 50,000 synthetic rows:
```bash
python3 - <<'PY'
import sqlite3, time
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INT, status TEXT, created_at TEXT, total_cents INT)")
rows = [(i, i % 500, "PAID" if i % 2 == 0 else "PENDING", f"2026-01-{(i%28)+1:02d}", 1999) for i in range(1, 50001)]
conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", rows)
plan_before = conn.execute("EXPLAIN QUERY PLAN SELECT id, total_cents FROM orders WHERE customer_id = 42 AND status = 'PAID' ORDER BY created_at DESC").fetchall()
t0 = time.perf_counter()
for _ in range(100):
    conn.execute("SELECT id, total_cents FROM orders WHERE customer_id = 42 AND status = 'PAID' ORDER BY created_at DESC").fetchall()
ms_before = (time.perf_counter() - t0) * 1000
conn.execute("CREATE INDEX idx_orders_cust_status_created ON orders (customer_id, status, created_at DESC)")
plan_after = conn.execute("EXPLAIN QUERY PLAN SELECT id, total_cents FROM orders WHERE customer_id = 42 AND status = 'PAID' ORDER BY created_at DESC").fetchall()
t0 = time.perf_counter()
for _ in range(100):
    conn.execute("SELECT id, total_cents FROM orders WHERE customer_id = 42 AND status = 'PAID' ORDER BY created_at DESC").fetchall()
ms_after = (time.perf_counter() - t0) * 1000
print({"plan_before": plan_before, "100_queries_ms_before": round(ms_before, 2), "plan_after": plan_after, "100_queries_ms_after": round(ms_after, 2)})
PY
```

## Recording Terminal Demonstrations
```bash
asciinema rec -i 1.5 demo-pg-query-surgeon.cast
python3 scripts/generate_migration_report.py --migration-file examples/unsafe_migration.sql --query-file examples/slow_queries.sql --explain-file examples/slow_explain_plan.json --schema-file examples/schema.sql --format markdown
exit
```
