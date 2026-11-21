# Architecture: `docker-forensics`

1. **`scripts/inspect_docker.py`**: Parses `docker inspect` JSON while scrubbing all `Config.Env` values.
2. **`scripts/analyze_image.py` & `scripts/analyze_layers.py`**: Evaluates multi-stage separation, layer cache ordering, `.dockerignore` coverage, and OverlayFS whiteout waste across Go, Rust, Node.js, and Python images.
3. **`scripts/audit_container_security.py`**: Audits root execution, `Privileged`, `CapAdd`, `NetworkMode: host`, sensitive bind mounts (`docker.sock`), writable rootfs, `no-new-privileges`, and Dockerfile `ENV` secret leaks.
4. **`scripts/inspect_network.py` & `scripts/diagnose_crashes.py`**: Diagnoses bridge DNS, loopback binding errors, OOMKills, and Kubernetes `CrashLoopBackOff` pods.
5. **`scripts/generate_forensics_report.py`**: Produces unified JSON and Markdown forensics reports.
