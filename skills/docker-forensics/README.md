# docker-forensics

**Container Image Optimization, Security Auditing, Network Diagnostics, and Crash Investigation Agent Skill**

## 1. Project Name and Positioning
`docker-forensics` is a production-ready [Agent Skill](https://agentskills.io/specification) for diagnosing container crashes, auditing Docker security posture, debugging container networking, and optimizing Dockerfiles across Go, Rust, Node.js, and Python workloads.

## 2. Problem Statement
Containerized applications frequently ship with gigabyte-sized build toolchains, uncleaned OverlayFS package caches, root execution, mounted `/var/run/docker.sock` sockets, loopback port-binding bugs, and opaque `ExitCode 137` / `CrashLoopBackOff` failures.

## 3. What the Skill Actually Does
`docker-forensics` provides seven deterministic Python scripts that inspect container state, analyze Dockerfiles and layer histories, audit container security without leaking environment secrets, debug bridge/DNS networking, and diagnose container exit codes and Kubernetes crash loops.

## 4. Key Features
- **Multi-Language Image & Layer Optimizer**: Detects missing multi-stage builds, `COPY . .` cache invalidation traps, uncleaned `apt`/`pip`/`npm` caches, separate `RUN rm` whiteout layers, and incomplete `.dockerignore` files.
- **Zero-Trust Container Security Auditor**: Flags UID 0 execution, `Privileged: true`, dangerous capabilities (`CAP_SYS_ADMIN`), `NetworkMode: host`, `/var/run/docker.sock` bind mounts, writable rootfs, and baked-in `ENV` secrets while redacting all `Config.Env` values.
- **Network & Crash Forensics**: Diagnoses default bridge DNS limitations, `127.0.0.1` vs `0.0.0.0` binding failures, `OOMKilled` (`ExitCode 137`), `SIGSEGV` (`139`), healthcheck failures, and Kubernetes `CrashLoopBackOff`.

## 5. Architecture Overview
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 6. Installation

Hermes Agent:

```bash
hermes skills install ciago-labs/skills/docker-forensics
```

Cursor, Codex, Gemini CLI, OpenCode and other agents:

```bash
npx skills add ciago-labs/skills --skill docker-forensics
```

The npx route runs no local security scan: review the source before use. For Claude Code and manual installation, see the [repository README](https://github.com/ciago-labs/skills#installation). See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md) for per-agent paths.

## 7. Supported Agent Environments
See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## 8. Prerequisites
- Python 3.8+ (standard library only).
- Works offline against JSON/Dockerfile fixtures or online with `docker` and optional `kubectl` CLIs.

## 9. Usage Examples
- *"Run `docker-forensics` on our `Dockerfile` and `container_inspect.json` to find why the container is OOM-killing and failing healthchecks."*
- *"Audit our container configuration for privilege escalation risks without printing any environment secrets."*

## 10. Script Examples
```bash
python3 scripts/inspect_docker.py --inspect-file examples/container_inspect.json --pretty
python3 scripts/analyze_image.py --dockerfile examples/Dockerfile.bloated-python --dockerignore examples/dockerignore.bad --pretty
python3 scripts/analyze_layers.py --layers-file examples/image_history.json --pretty
python3 scripts/audit_container_security.py --inspect-file examples/container_inspect.json --dockerfile examples/Dockerfile.bloated-python --pretty
python3 scripts/inspect_network.py --inspect-file examples/container_inspect.json --network-file examples/bridge_network.json --pretty
python3 scripts/diagnose_crashes.py --inspect-file examples/container_inspect.json --k8s-pod-file examples/k8s_crashloop_pod.json --pretty
python3 scripts/generate_forensics_report.py --inspect-file examples/container_inspect.json --dockerfile examples/Dockerfile.bloated-python --dockerignore examples/dockerignore.bad --layers-file examples/image_history.json --network-file examples/bridge_network.json --k8s-pod-file examples/k8s_crashloop_pod.json --format markdown --output examples/sample-forensics-report.md
```

## 11. Example Diagnostic Results
See [`examples/sample-forensics-report.md`](examples/sample-forensics-report.md) and [`examples/sample-forensics-report.json`](examples/sample-forensics-report.json).

## 12. Security and Safety Approach
- Never stops, removes, or modifies containers, images, or networks.
- Strips all `Config.Env` secret values before emitting reports. See [`docs/SECURITY.md`](docs/SECURITY.md).

## 13. Limitations
- Live container inspection requires access to the Docker CLI/socket; when unavailable, pass captured `docker inspect` and `docker history` JSON files.

## 14. Testing Instructions
```bash
python3 -m unittest discover -s tests -v
```

## 15. Contribution Instructions
See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## 16. Roadmap
- Add OCI image tarball `manifest.json` direct layer inspector.
- Add Docker Compose multi-service network topology graph validator.

## 17. License
MIT License. See [`LICENSE`](LICENSE).
