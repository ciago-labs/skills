# Diagnostic Workflows (`docker-forensics`)

## Workflow 1: Container Restart Loop / CrashLoopBackOff Triage
1. Capture `docker inspect <container> > inspect.json`.
2. Run `python3 scripts/diagnose_crashes.py --inspect-file inspect.json --pretty`.
3. Check whether `OOMKilled` is `true` (ExitCode 137) or if healthcheck probes are failing due to loopback binding (`scripts/inspect_network.py`).

## Workflow 2: Pre-Production Image & Security Audit
1. Run `python3 scripts/analyze_image.py --dockerfile Dockerfile --dockerignore .dockerignore --pretty`.
2. Run `python3 scripts/audit_container_security.py --inspect-file inspect.json --dockerfile Dockerfile --pretty`.
