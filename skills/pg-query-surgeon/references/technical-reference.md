# Technical Reference: PostgreSQL Locks, EXPLAIN Nodes & Supplementary MySQL/Redis Notes

## 1. PostgreSQL Lock Modes and DDL Matrix
| DDL Statement | Lock Mode Acquired | Blocks Reads (`SELECT`)? | Blocks Writes (`DML`)? | Safe Online Alternative |
| :--- | :--- | :--- | :--- | :--- |
| `CREATE INDEX` | `SHARE` | No | **Yes** | `CREATE INDEX CONCURRENTLY` (`SHARE UPDATE EXCLUSIVE`) |
| `DROP INDEX` | `ACCESS EXCLUSIVE` | **Yes** | **Yes** | `DROP INDEX CONCURRENTLY` |
| `ALTER TABLE ... ADD COLUMN ... DEFAULT <const>` (PG 11+) | `ACCESS EXCLUSIVE` (instant metadata) | Brief | Brief | Pair with `SET lock_timeout = '2s'` |
| `ALTER TABLE ... ALTER COLUMN TYPE` | `ACCESS EXCLUSIVE` (full table rewrite) | **Yes** | **Yes** | Expand-and-contract dual-column pattern |
| `ALTER TABLE ... SET NOT NULL` | `ACCESS EXCLUSIVE` (full table scan) | **Yes** | **Yes** | `ADD CONSTRAINT ... CHECK (col IS NOT NULL) NOT VALID` + `VALIDATE CONSTRAINT` |
| `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY` | `SHARE ROW EXCLUSIVE` | No | **Yes** | Append `NOT VALID`, then `VALIDATE CONSTRAINT` |

## 2. Supplementary MySQL 8.0+ Online DDL Guidance
- In MySQL 8.0+, explicitly specify `ALGORITHM=INSTANT` (for metadata-only column additions) or `ALGORITHM=INPLACE, LOCK=NONE` to prevent table-copying locks.
- Unlike PostgreSQL, MySQL does not support transactional DDL (`ALTER TABLE` causes an implicit commit).

## 3. Supplementary Redis Operational Safety Guidance
- Never execute `KEYS *`, `FLUSHALL`, or unpaginated `SMEMBERS`/`HGETALL` on collections with >10,000 elements; use `SCAN`, `SSCAN`, and `HSCAN` with bounded `COUNT`.
