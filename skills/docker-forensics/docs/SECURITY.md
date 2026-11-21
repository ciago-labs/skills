# Security & Safety Model (`docker-forensics`)

1. **Read-Only Container Inspection**: No script in `docker-forensics` stops, restarts, deletes, or modifies containers, images, volumes, or networks.
2. **Strict `Config.Env` Redaction**: Container inspection payloads frequently contain production API keys and database passwords in `Config.Env`. `inspect_docker.py` replaces all environment values with `[REDACTED_FOR_SECURITY]`.
