# PostgreSQL Migration Safety & Query Optimization Report (`pg-query-surgeon`)

- **Overall Risk Status**: `CRITICAL`
- **Target PostgreSQL Version**: `PostgreSQL 16`
- **Migration Risk Classification**: `CRITICAL` (Score: `100/100`)
- **Plan Execution Time**: `395.2 ms` (Buffer Cache Hit Rate: `4.09%`)

## 1. Verified Findings vs Heuristic Recommendations

### [HIGH] MIG-IDX-002: CREATE INDEX without CONCURRENTLY acquires a SHARE lock that blocks all INSERT, UPDATE, and DELETE operations
- **Classification**: `verified` | **Category**: `locking`
- **Evidence**: `{"concurrently": false, "in_transaction": true, "lock_mode": "SHARE"}`
- **Recommendation**: Rewrite as CREATE INDEX CONCURRENTLY outside of a transaction block (uses SHARE UPDATE EXCLUSIVE lock).

### [CRITICAL] MIG-TXN-003: CREATE/DROP/REINDEX INDEX CONCURRENTLY inside a BEGIN...COMMIT transaction block will fail at runtime
- **Classification**: `verified` | **Category**: `transaction_hazard`
- **Evidence**: `{"has_begin": true, "has_concurrently": true}`
- **Recommendation**: Split concurrent index operations into standalone non-transactional migration files.

### [CRITICAL] MIG-REWRITE-004: ALTER COLUMN TYPE acquires ACCESS EXCLUSIVE lock and triggers a full heap and index rewrite
- **Classification**: `verified` | **Category**: `table_rewrite`
- **Evidence**: `{"operation": "ALTER COLUMN TYPE", "pg_version": 16}`
- **Recommendation**: Use expand-and-contract: add a new column, dual-write via trigger or application, backfill in small batches, and swap.

### [HIGH] MIG-ADDCOL-005: ADD COLUMN with volatile DEFAULT causes table rewrite or blocking index build
- **Classification**: `verified` | **Category**: `table_rewrite`
- **Evidence**: `{"pg_version": 16, "volatile_default": true, "inline_pk_unique": false}`
- **Recommendation**: Add the column as nullable without a default, backfill in batched UPDATEs, create unique index CONCURRENTLY, and set DEFAULT.

### [HIGH] MIG-NOTNULL-006: ALTER COLUMN `shipping_address` SET NOT NULL performs a full sequential scan under ACCESS EXCLUSIVE lock
- **Classification**: `verified` | **Category**: `locking`
- **Evidence**: `{"column": "shipping_address", "pg_version": 16, "backed_by_validated_check": false}`
- **Recommendation**: Add `CHECK (shipping_address IS NOT NULL) NOT VALID`, run `VALIDATE CONSTRAINT` (`SHARE UPDATE EXCLUSIVE`), and then run `SET NOT NULL` on PostgreSQL 12+.

### [HIGH] MIG-FK-007: Adding FOREIGN KEY or CHECK constraint without NOT VALID validates all existing rows under heavy lock
- **Classification**: `verified` | **Category**: `locking`
- **Evidence**: `{"not_valid_present": false}`
- **Recommendation**: Append NOT VALID to ADD CONSTRAINT, then execute ALTER TABLE ... VALIDATE CONSTRAINT (`SHARE UPDATE EXCLUSIVE`) in a separate transaction.

### [HIGH] MIG-DESTRUCT-008: Destructive schema operation (DROP/TRUNCATE) detected; breaks running application instances referencing the column/table
- **Classification**: `verified` | **Category**: `destructive_change`
- **Evidence**: `{"destructive": true}`
- **Recommendation**: Deploy application code removing all references to the column first, verify zero queries reference it, and drop in a subsequent release.

### [MEDIUM] MIG-TIMEOUT-001: Missing SET lock_timeout before DDL statements risks catastrophic lock-queue convoying
- **Classification**: `verified` | **Category**: `lock_queue_hazard`
- **Evidence**: `{"has_lock_timeout": false, "has_statement_timeout": false}`
- **Recommendation**: Prepend `SET lock_timeout = '2s'; SET statement_timeout = '30s';` with retry backoff logic.

### [HIGH] SQL-FUNC-001: Non-SARGable function call `LOWER(customer_email)` in WHERE clause forces sequential scan unless expression index exists
- **Classification**: `verified` | **Category**: `sargability`
- **Evidence**: `{"function": "LOWER", "column": "customer_email"}`
- **Recommendation**: Rewrite predicate as a range filter (for dates) or create an expression index on `(LOWER(customer_email))`.

### [MEDIUM] SQL-OFFSET-001: Deep OFFSET pagination (OFFSET 5000) scans and discards 5000 rows on every query
- **Classification**: `verified` | **Category**: `pagination`
- **Evidence**: `{"offset": 5000}`
- **Recommendation**: Replace OFFSET pagination with keyset (seek) pagination: `WHERE (created_at, id) < ($1, $2) ORDER BY created_at DESC, id DESC LIMIT N`.

### [MEDIUM] SQL-STAR-001: Unbounded SELECT * fetches wide rows (including TOAST columns) and prevents Index-Only Scans
- **Classification**: `heuristic` | **Category**: `projection`
- **Evidence**: `{"select_star": true, "has_limit": false}`
- **Recommendation**: Project only required columns to enable Index-Only Scans and reduce network/TOAST I/O.

### [HIGH] SQL-LIKE-002: Leading wildcard LIKE/ILIKE ('%pattern') prevents standard B-Tree index usage
- **Classification**: `verified` | **Category**: `index_prevented`
- **Evidence**: `{"pattern": "LIKE '%...'"}`
- **Recommendation**: Enable pg_trgm extension and create a GIN trigram index: `CREATE INDEX CONCURRENTLY idx_trgm ON table USING gin (col gin_trgm_ops);`

### [HIGH] SQL-NOTIN-003: NOT IN (SELECT ...) uses hashed/materialized subplan and returns 0 rows if any NULL exists in subquery
- **Classification**: `verified` | **Category**: `join_efficiency`
- **Evidence**: `{"construct": "NOT IN (SELECT ...)"}`
- **Recommendation**: Rewrite `NOT IN (SELECT ...)` as `NOT EXISTS (SELECT 1 FROM ... WHERE ...)` for anti-join optimization and safe NULL semantics.

### [HIGH] SQL-NPLUS1-001: N+1 query pattern detected: identical query shape repeated 4 times in workload trace
- **Classification**: `verified` | **Category**: `n_plus_one`
- **Evidence**: `{"fingerprint": "SELECT ID, STATUS FROM ORDERS WHERE CUSTOMER_ID = ?", "execution_count": 4}`
- **Recommendation**: Batch lookups using `WHERE id = ANY($1::bigint[])` or eager-load via JOIN.

### [MEDIUM] PLAN-EST-001: Row estimation mismatch (59.2x) on `Sort` (unknown_relation): estimated 250 vs actual 14800
- **Classification**: `verified` | **Category**: `cardinality_misestimate`
- **Evidence**: `{"estimated_rows": 250, "actual_rows": 14800, "ratio": 59.2}`
- **Recommendation**: Run `ANALYZE unknown_relation;` and consider `CREATE STATISTICS` for correlated columns on `unknown_relation`.

### [HIGH] PLAN-SPILL-001: `Sort` spilled to disk (Sort Space Type=Disk, Temp Written Blocks=2048, Hash Batches=1)
- **Classification**: `verified` | **Category**: `memory_spill`
- **Evidence**: `{"sort_method": "external merge", "sort_space_type": "Disk", "sort_space_used_kb": 16384, "temp_written_blocks": 2048, "hash_batches": 1}`
- **Recommendation**: Provide an index matching the ORDER BY clause to eliminate the sort, or raise session `work_mem` for heavy reporting/hash-join queries.

### [HIGH] PLAN-SEQ-002: Large Sequential Scan on `orders` (rows_removed=485200, actual_rows=14800, est_rows=250)
- **Classification**: `verified` | **Category**: `sequential_scan`
- **Evidence**: `{"relation": "orders", "filter": "((status = 'PAID'::text) AND (customer_id = 42))", "actual_rows": 14800, "rows_removed_by_filter": 485200, "selectivity_pct": 2.96, "shared_read_blocks": 9850}`
- **Recommendation**: Create a targeted index on `orders` covering columns in `((status = 'PAID'::text) AND (customer_id = 42))` using CREATE INDEX CONCURRENTLY.

### [MEDIUM] PLAN-EST-002: Row estimation mismatch (59.2x) on `Seq Scan` (orders): estimated 250 vs actual 14800
- **Classification**: `verified` | **Category**: `cardinality_misestimate`
- **Evidence**: `{"estimated_rows": 250, "actual_rows": 14800, "ratio": 59.2}`
- **Recommendation**: Run `ANALYZE orders;` and consider `CREATE STATISTICS` for correlated columns on `orders`.

### [MEDIUM] SCH-INT4-MERCHANTS-ID: 32-bit integer identifier `merchants.id` (SERIAL) risks 2.14B sequence exhaustion in high-growth tables
- **Classification**: `heuristic` | **Category**: `type_safety`
- **Evidence**: `{"table": "merchants", "column": "id", "type": "SERIAL"}`
- **Recommendation**: Prefer `BIGINT` (`BIGSERIAL` or `GENERATED ALWAYS AS IDENTITY`) for primary and foreign key columns.

### [HIGH] SCH-FKIDX-ORDERS-MERCHANT_ID: Unindexed foreign key `orders.merchant_id` causes sequential scans on parent DELETE/UPDATE and join queries
- **Classification**: `verified` | **Category**: `missing_fk_index`
- **Evidence**: `{"table": "orders", "foreign_key_column": "merchant_id"}`
- **Recommendation**: Run `CREATE INDEX CONCURRENTLY idx_orders_merchant_id ON orders (merchant_id);`

### [MEDIUM] SCH-INT4-ORDERS-ID: 32-bit integer identifier `orders.id` (INT) risks 2.14B sequence exhaustion in high-growth tables
- **Classification**: `heuristic` | **Category**: `type_safety`
- **Evidence**: `{"table": "orders", "column": "id", "type": "INT"}`
- **Recommendation**: Prefer `BIGINT` (`BIGSERIAL` or `GENERATED ALWAYS AS IDENTITY`) for primary and foreign key columns.

### [MEDIUM] SCH-INT4-ORDERS-MERCHANT_ID: 32-bit integer identifier `orders.merchant_id` (INT) risks 2.14B sequence exhaustion in high-growth tables
- **Classification**: `heuristic` | **Category**: `type_safety`
- **Evidence**: `{"table": "orders", "column": "merchant_id", "type": "INT"}`
- **Recommendation**: Prefer `BIGINT` (`BIGSERIAL` or `GENERATED ALWAYS AS IDENTITY`) for primary and foreign key columns.

### [HIGH] SCH-PK-AUDIT_EVENTS: Table `audit_events` has no PRIMARY KEY (breaks logical replication and bloat remediation tools like pg_repack)
- **Classification**: `verified` | **Category**: `schema_integrity`
- **Evidence**: `{"table": "audit_events", "has_pk": false}`
- **Recommendation**: Add a BIGINT GENERATED ALWAYS AS IDENTITY or UUIDv7 primary key to `audit_events`.

## 2. Proposed Index & SQL Optimizations

- **Table `orders`**: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_status_created_at ON orders (status, created_at);` (Follows Equality -> Sort -> Range column ordering rule to maximize B-Tree selectivity and avoid in-memory/disk sorting.)
- **Table `orders`**: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id ON orders (customer_id);` (Follows Equality -> Sort -> Range column ordering rule to maximize B-Tree selectivity and avoid in-memory/disk sorting.)
- **Table `orders`**: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id ON orders (customer_id);` (Follows Equality -> Sort -> Range column ordering rule to maximize B-Tree selectivity and avoid in-memory/disk sorting.)
- **Table `orders`**: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id ON orders (customer_id);` (Follows Equality -> Sort -> Range column ordering rule to maximize B-Tree selectivity and avoid in-memory/disk sorting.)
- **Table `orders`**: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id ON orders (customer_id);` (Follows Equality -> Sort -> Range column ordering rule to maximize B-Tree selectivity and avoid in-memory/disk sorting.)

## 3. Step-by-Step Zero-Downtime Migration & Rollback Strategy

1. **Pre-Flight Lock Guard**: Configure `SET lock_timeout = '2s'; SET statement_timeout = '30s';` in the migration session.
2. **Expand Phase**: Add new nullable columns or create indexes using `CREATE INDEX CONCURRENTLY` outside transaction blocks.
3. **Backfill Phase**: Backfill historical data in batches of 1,000-5,000 rows with `pg_sleep(0.05)` between batches to avoid Replication lag and VACUUM starvation.
4. **Constraint Validation Phase**: Add constraints as `NOT VALID`, then execute `ALTER TABLE ... VALIDATE CONSTRAINT` (`SHARE UPDATE EXCLUSIVE` lock).
5. **Verification & Rollback**: To roll back a concurrent or invalid index without blocking traffic, execute `DROP INDEX CONCURRENTLY IF EXISTS <index_name>;`. To roll back a `NOT VALID` constraint, execute `ALTER TABLE <table_name> DROP CONSTRAINT IF EXISTS <constraint_name>;`.
