# Examples — fixtures only, never deploy

All files in this directory are **intentionally imperfect fixtures** for
offline testing of the `docker-forensics` scripts. They are not deployment
configurations, not a real container, and not a recommendation.

- `container_inspect.json` — a deliberately misconfigured container used
  by the walkthrough in `SKILL.md`: root user, no memory/PIDs limit,
  writable rootfs, missing `no-new-privileges`, OOM-killed (`ExitCode 137`),
  unhealthy healthcheck, loopback bind (`127.0.0.1`) with port 8080
  published on `0.0.0.0`, and an unmapped `9090/tcp`.
  It is **not** privileged, has no extra Linux capabilities, and mounts
  no host socket. Those three host-escape risks are covered separately,
  in a test fixture only — see below.
- `Dockerfile.bloated-python`, `dockerignore.bad`, `image_history.json`,
  `bridge_network.json`, `k8s_crashloop_pod.json` — similarly bad-by-design
  fixtures for the image, layer, network and crash analysers.
- `sample-forensics-report.md` / `.json` — the report the scripts produce
  from the fixtures above. Regenerate it after changing a fixture.

## Where the privileged / docker.sock case lives

`tests/fixtures/container_privileged_docker_sock.json` is the only file
that contains `Privileged: true`, `CAP_SYS_ADMIN` / `NET_ADMIN`, and a
writable `/var/run/docker.sock` mount. It exists so the security auditor
test can prove those three findings (`SEC-PRIV-001`, `SEC-CAP-001`,
`SEC-MOUNT-001`) are still detected. It is a test fixture, never an
example to copy, and it must never be used as a run specification.

If a scanner flags a file in this directory, check this note first:
the flagged values are the point of the fixture — the auditor is
supposed to find them.
