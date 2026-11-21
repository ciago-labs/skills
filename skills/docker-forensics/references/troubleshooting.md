# Troubleshooting (`docker-forensics`)

## 1. Go or Rust Binary Fails with `exec user process caused: no such file or directory` (ExitCode 127)
- **Cause**: The binary was compiled on a glibc host (`Ubuntu`/`Debian`) with dynamic linking enabled (`CGO_ENABLED=1`) and copied into an `alpine` (musl) or `scratch` runtime stage.
- **Resolution**: Compile with `CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w"` or use `gcr.io/distroless/base-debian12:nonroot`.
