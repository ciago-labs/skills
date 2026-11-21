# Reproducible Benchmarks (`docker-forensics`)

## Benchmark 1: Fixture-Based Image Layer & Security Forensics Benchmark
Runs deterministically without requiring a running Docker daemon:
```bash
python3 scripts/generate_forensics_report.py \\
  --inspect-file examples/container_inspect.json \\
  --dockerfile examples/Dockerfile.bloated-python \\
  --dockerignore examples/.dockerignore.bad \\
  --layers-file examples/image_history.json \\
  --network-file examples/bridge_network.json \\
  --k8s-pod-file examples/k8s_crashloop_pod.json \\
  --pretty
```
*(Note: In environments without a running `dockerd` daemon, layer sizes reported in `examples/sample-forensics-report.json` are derived from the fixture `examples/image_history.json` (`1,370.43 MiB` measured fixture layers) and are explicitly labeled as fixture measurements rather than live `docker build` benchmarks.)*

## Recording Terminal Demonstrations
```bash
asciinema rec -i 1.5 demo-docker-forensics.cast
python3 scripts/generate_forensics_report.py --inspect-file examples/container_inspect.json --dockerfile examples/Dockerfile.bloated-python --dockerignore examples/.dockerignore.bad --layers-file examples/image_history.json --network-file examples/bridge_network.json --k8s-pod-file examples/k8s_crashloop_pod.json --format markdown
exit
```
