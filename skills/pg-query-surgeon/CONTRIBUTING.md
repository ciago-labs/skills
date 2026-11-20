# Contributing to `pg-query-surgeon`

1. Keep all analyzers deterministic and compatible with Python 3.8+ standard library.
2. Never add scripts that automatically execute DDL or mutating queries against live databases.
3. Ensure every new migration rule or query heuristic includes unit tests in `tests/test_pg_query_surgeon.py`.
