# Contributing to `docker-forensics`

1. Keep all scripts compatible with Python 3.8+ standard library.
2. Never print raw `Config.Env` values or secrets from container inspect payloads.
3. Verify all tests pass via `python3 -m unittest discover -s tests -v`.
