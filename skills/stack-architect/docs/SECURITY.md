# Security & Safety Model (`stack-architect`)

1. **Zero Overwrite by Default**: `scaffold_infrastructure.py` refuses to write into existing non-empty directories unless `--force` is passed.
2. **Zero Hardcoded Credentials**: Generated `.env.example` and `docker-compose.yml` use placeholder tokens (`REPLACE_WITH_VAULT_OR_DOPPLER_SECRET`), verified automatically by `validate_blueprint.py`.
3. **Hardened Container Defaults**: Generated `Dockerfile` and `docker-compose.yml` enforce non-root execution (`UID 10001`), `read_only: true` root filesystem, and `no-new-privileges:true`.
