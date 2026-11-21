# Container Forensics, Security & Image Optimization Report (`docker-forensics`)

- **Overall Status**: `CRITICAL`
- **Container**: `payment-processor-api` (`payment-processor:v1.2.0`)
- **Exit Code / OOMKilled**: `ExitCode=137` (`OOMKilled=True`, Restarts=`7`)
- **Measured Layer History Size**: `1370.43 MiB` (Heuristic Reclaimable Cache: `162.12 MiB`)
- **Security Findings**: `7` (`2` critical, `2` high; Secrets exposed in report: `0`)

## 1. Diagnostic & Security Findings

### [LOW] DKR-CFG-002: Container restart policy is set to 'no'
- **Category**: `resilience` | **Classification**: `verified`
- **Evidence**: `{"restart_policy": {"Name": "no", "MaximumRetryCount": 0}}`
- **Remediation**: Use `--restart on-failure:5` or `unless-stopped` for long-running services.

### [HIGH] IMG-STAGE-001: Single-stage build using full SDK/OS base image `python:3.11` ships compilers and build toolchains to production
- **Category**: `multi_stage` | **Classification**: `verified`
- **Evidence**: `{"from_stages": 1, "final_base_image": "python:3.11", "ecosystem": "python", "recommended_runtime_base": "python:3.11-slim-bookworm (scratch is unsuitable for CPython interpreter and manylinux C extensions)"}`
- **Remediation**: Use a multi-stage build and copy only runtime artifacts into `python:3.11-slim-bookworm (scratch is unsuitable for CPython interpreter and manylinux C extensions)`.

### [MEDIUM] IMG-CACHE-APT-1: apt-get install without cleaning `/var/lib/apt/lists/*` in the same RUN instruction
- **Category**: `layer_bloat` | **Classification**: `verified`
- **Evidence**: `{"run_instruction": "RUN apt-get update && apt-get install -y build-essential git"}`
- **Remediation**: Chain `&& rm -rf /var/lib/apt/lists/*` inside the exact same `RUN apt-get update && apt-get install -y --no-install-recommends ...` command.

### [MEDIUM] IMG-CACHE-PIP-3: pip install executed without `--no-cache-dir` or BuildKit cache mount
- **Category**: `layer_bloat` | **Classification**: `verified`
- **Evidence**: `{"run_instruction": "RUN pip install -r requirements.txt"}`
- **Remediation**: Pass `pip install --no-cache-dir` or set `ENV PIP_NO_CACHE_DIR=1`.

### [MEDIUM] IMG-CACHETRAP-001: `COPY . .` appears before dependency installation, invalidating dependency layer cache on every code edit
- **Category**: `build_cache` | **Classification**: `verified`
- **Evidence**: `{"copy_all_line_index": 2, "dep_install_line_index": 5}`
- **Remediation**: Copy only `package*.json` / `requirements.txt` / `go.mod` / `Cargo.toml` first, install dependencies, and then `COPY . .`.

### [HIGH] IMG-IGNORE-001: `.dockerignore` is missing critical exclusions: .git, .env, node_modules, __pycache__, .venv
- **Category**: `dockerignore` | **Classification**: `verified`
- **Evidence**: `{"missing_entries": [".git", ".env", "node_modules", "__pycache__", ".venv"]}`
- **Remediation**: Add `.git`, `.env*`, `node_modules`, `.venv`, `__pycache__`, and `target/` to `.dockerignore`.

### [MEDIUM] IMG-USER-001: Dockerfile does not switch to a non-root USER in the final stage
- **Category**: `security` | **Classification**: `verified`
- **Evidence**: `{"user_instructions": []}`
- **Remediation**: Create an unprivileged user (`RUN useradd -u 10001 -r -s /sbin/nologin appuser`) and set `USER 10001`.

### [MEDIUM] LYR-LARGE-001: Large image layer #1 (965.12 MiB)
- **Category**: `large_layer` | **Classification**: `measured`
- **Evidence**: `{"layer_index": 1, "size_mib": 965.12, "created_by": "FROM python:3.11"}`
- **Remediation**: Move build tools to a builder stage in a multi-stage Dockerfile and copy only runtime artifacts.

### [MEDIUM] LYR-LARGE-002: Large image layer #2 (233.65 MiB)
- **Category**: `large_layer` | **Classification**: `measured`
- **Evidence**: `{"layer_index": 2, "size_mib": 233.65, "created_by": "/bin/sh -c apt-get update && apt-get install -y build-essential git"}`
- **Remediation**: Move build tools to a builder stage in a multi-stage Dockerfile and copy only runtime artifacts.

### [HIGH] LYR-SEP-CLEAN-003: Cleanup command executed in a separate `RUN` layer does not reclaim bytes from parent layers
- **Category**: `overlayfs_waste` | **Classification**: `verified`
- **Evidence**: `{"layer_index": 3, "command": "/bin/sh -c rm -rf /var/lib/apt/lists/*", "layer_size_bytes": 0}`
- **Remediation**: Combine package installation and cache cleanup (`&& rm -rf ...`) into a single `RUN` layer.

### [MEDIUM] LYR-LARGE-004: Large image layer #4 (171.66 MiB)
- **Category**: `large_layer` | **Classification**: `measured`
- **Evidence**: `{"layer_index": 4, "size_mib": 171.66, "created_by": "/bin/sh -c pip install -r requirements.txt"}`
- **Remediation**: Move build tools to a builder stage in a multi-stage Dockerfile and copy only runtime artifacts.

### [HIGH] SEC-ROOT-001: Container runs as root (UID 0)
- **Category**: `privilege` | **Classification**: `verified`
- **Evidence**: `{"user": "root (default)"}`
- **Remediation**: Run container as a non-root UID (e.g., `--user 10001:10001`).

### [CRITICAL] SEC-PRIV-001: Container is running in `--privileged` mode (disables seccomp, AppArmor, and device isolation)
- **Category**: `privilege` | **Classification**: `verified`
- **Evidence**: `{"privileged": true}`
- **Remediation**: Remove `--privileged` and grant only minimal required Linux capabilities.

### [HIGH] SEC-CAP-001: Excessive Linux capabilities granted: CAP_SYS_ADMIN, NET_ADMIN
- **Category**: `capabilities` | **Classification**: `verified`
- **Evidence**: `{"cap_add": ["CAP_SYS_ADMIN", "NET_ADMIN"]}`
- **Remediation**: Drop all capabilities (`--cap-drop=ALL`) and add back only strictly necessary capabilities.

### [CRITICAL] SEC-MOUNT-001: Sensitive host path mounted into container: `/var/run/docker.sock` -> `/var/run/docker.sock`
- **Category**: `host_mount` | **Classification**: `verified`
- **Evidence**: `{"source": "/var/run/docker.sock", "destination": "/var/run/docker.sock", "rw": true}`
- **Remediation**: Remove host `/var/run/docker.sock` or `/etc` mounts, or proxy read-only API calls via a hardened socket proxy.

### [MEDIUM] SEC-ROFS-001: Container root filesystem is writable (`ReadonlyRootfs: false`)
- **Category**: `filesystem` | **Classification**: `verified`
- **Evidence**: `{"readonly_rootfs": false}`
- **Remediation**: Enable `--read-only` root filesystem and mount `/tmp` via `--tmpfs /tmp:rw,noexec,nosuid`.

### [MEDIUM] SEC-NNP-001: Missing `no-new-privileges:true` in SecurityOpt
- **Category**: `privilege_escalation` | **Classification**: `verified`
- **Evidence**: `{"security_opt": []}`
- **Remediation**: Pass `--security-opt=no-new-privileges:true`.

### [MEDIUM] SEC-LIMITS-001: Missing cgroup memory or PIDs limit (`Memory=0` or `PidsLimit=unlimited`)
- **Category**: `resource_limits` | **Classification**: `verified`
- **Evidence**: `{"memory_limit": 0, "pids_limit": 0}`
- **Remediation**: Set explicit `--memory` and `--pids-limit` bounds on every container.

### [HIGH] NET-DEFAULT-BRIDGE: Container is attached only to the default `bridge` network, where Docker embedded DNS (`127.0.0.11`) service discovery is disabled
- **Category**: `dns_resolution` | **Classification**: `verified`
- **Evidence**: `{"attached_networks": ["bridge"]}`
- **Remediation**: Create and attach a user-defined bridge network (`docker network create app-net`) to enable automatic DNS name resolution via 127.0.0.11.

### [MEDIUM] NET-PORT-UNMAPPED: Exposed container port(s) `9090/tcp` have no host port publishing (`-p`)
- **Category**: `port_mapping` | **Classification**: `verified`
- **Evidence**: `{"unmapped_ports": ["9090/tcp"], "ports_map": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}], "9090/tcp": null}}`
- **Remediation**: Publish the port explicitly (e.g., `-p 127.0.0.1:8080:8080`) or route via an internal reverse proxy on the same bridge network.

### [HIGH] NET-LOOPBACK-BIND: Application command binds to `127.0.0.1`/`localhost` inside container, breaking Docker NAT port forwarding
- **Category**: `connection_refused` | **Classification**: `verified`
- **Evidence**: `{"command": "python3 app.py --host 127.0.0.1 --port 8080", "published_ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}], "9090/tcp": null}}`
- **Remediation**: Bind the application server inside the container to `0.0.0.0` (e.g., `--host 0.0.0.0`).

### [CRITICAL] CRASH-OOM-CONFIRMED: Confirmed kernel cgroup OOM kill (`State.OOMKilled=true`, `ExitCode=137`)
- **Category**: `confirmed_oom_kill` | **Classification**: `verified`
- **Evidence**: `{"exit_code": 137, "oom_killed": true, "memory_limit_bytes": 0, "restart_count": 7}`
- **Remediation**: Increase container memory limit or configure runtime heap bounds (`GOMEMLIMIT`, `--max-old-space-size`, `-XX:MaxRAMPercentage=80.0`) to 80-85% of the container limit.

### [HIGH] CRASH-RESTART-LOOP: Container is in a restart loop (`RestartCount=7`)
- **Category**: `restart_loop` | **Classification**: `verified`
- **Evidence**: `{"restart_count": 7, "last_exit_code": 137, "status": "exited"}`
- **Remediation**: Inspect logs from the previous run and fix the root cause reflected by `ExitCode` before increasing restart retries.

### [HIGH] CRASH-HEALTH-001: Container healthcheck is UNHEALTHY (failing streak=5)
- **Category**: `healthcheck_failure` | **Classification**: `verified`
- **Evidence**: `{"failing_streak": 5, "last_exit_code": 1, "last_output": "HTTP probe failed to connect to localhost port 8080: Connection refused"}`
- **Remediation**: Verify the healthcheck binary exists inside the container image and that `--start-period` is long enough for initialization.

### [CRITICAL] CRASH-K8S-CLBO: Kubernetes waiting condition `CrashLoopBackOff` on container `payment-processor` (kubelet backoff state; underlying container last terminated with exitCode=137, reason=OOMKilled)
- **Category**: `kubernetes_waiting_condition` | **Classification**: `verified`
- **Evidence**: `{"is_docker_exit_code": false, "kubernetes_waiting_reason": "CrashLoopBackOff", "container": "payment-processor", "restart_count": 7, "last_terminated_reason": "OOMKilled", "last_exit_code": 137}`
- **Remediation**: Inspect previous pod logs (`kubectl logs <pod> --previous`) and remediate the underlying termination cause (`lastState.terminated`).

## 2. Prioritized Remediation Checklist

- Use `--restart on-failure:5` or `unless-stopped` for long-running services.
- Use a multi-stage build and copy only runtime artifacts into `python:3.11-slim-bookworm (scratch is unsuitable for CPython interpreter and manylinux C extensions)`.
- Chain `&& rm -rf /var/lib/apt/lists/*` inside the exact same `RUN apt-get update && apt-get install -y --no-install-recommends ...` command.
- Pass `pip install --no-cache-dir` or set `ENV PIP_NO_CACHE_DIR=1`.
- Copy only `package*.json` / `requirements.txt` / `go.mod` / `Cargo.toml` first, install dependencies, and then `COPY . .`.
- Add `.git`, `.env*`, `node_modules`, `.venv`, `__pycache__`, and `target/` to `.dockerignore`.
- Create an unprivileged user (`RUN useradd -u 10001 -r -s /sbin/nologin appuser`) and set `USER 10001`.
- Move build tools to a builder stage in a multi-stage Dockerfile and copy only runtime artifacts.
- Combine package installation and cache cleanup (`&& rm -rf ...`) into a single `RUN` layer.
- Run container as a non-root UID (e.g., `--user 10001:10001`).
- Remove `--privileged` and grant only minimal required Linux capabilities.
- Drop all capabilities (`--cap-drop=ALL`) and add back only strictly necessary capabilities.
- Remove host `/var/run/docker.sock` or `/etc` mounts, or proxy read-only API calls via a hardened socket proxy.
- Enable `--read-only` root filesystem and mount `/tmp` via `--tmpfs /tmp:rw,noexec,nosuid`.
- Pass `--security-opt=no-new-privileges:true`.
- Set explicit `--memory` and `--pids-limit` bounds on every container.
- Create and attach a user-defined bridge network (`docker network create app-net`) to enable automatic DNS name resolution via 127.0.0.11.
- Publish the port explicitly (e.g., `-p 127.0.0.1:8080:8080`) or route via an internal reverse proxy on the same bridge network.
- Bind the application server inside the container to `0.0.0.0` (e.g., `--host 0.0.0.0`).
- Increase container memory limit or configure runtime heap bounds (`GOMEMLIMIT`, `--max-old-space-size`, `-XX:MaxRAMPercentage=80.0`) to 80-85% of the container limit.
- Inspect logs from the previous run and fix the root cause reflected by `ExitCode` before increasing restart retries.
- Verify the healthcheck binary exists inside the container image and that `--start-period` is long enough for initialization.
- Inspect previous pod logs (`kubectl logs <pod> --previous`) and remediate the underlying termination cause (`lastState.terminated`).
