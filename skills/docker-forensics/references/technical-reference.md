# Technical Reference: Container Forensics, Exit Codes & Layer Mechanics

## 1. Linux Container Exit Codes
- **`0`**: Clean exit.
- **`1`**: Application exception, uncaught panic, or startup configuration error.
- **`126`**: Permission error (`chmod +x` missing on entrypoint script or binary).
- **`127`**: Command or shared library (`ld-linux` vs `musl`) not found inside container image.
- **`137`** (`128 + 9 = SIGKILL`): Immediate termination by kernel cgroup OOM killer (`State.OOMKilled = true`) or `docker stop` timeout expiry.
- **`139`** (`128 + 11 = SIGSEGV`): Invalid memory reference in native code or C extension.
- **`143`** (`128 + 15 = SIGTERM`): Graceful shutdown signal received from orchestrator.

## 2. OverlayFS Layer Immutability
Docker images consist of read-only OverlayFS lowerdirs. Running `apt-get install` in layer $N$ and `rm -rf /var/lib/apt/lists/*` in layer $N+1$ creates character-device whiteout files in layer $N+1$ without reducing the compressed or uncompressed byte size of layer $N$.
