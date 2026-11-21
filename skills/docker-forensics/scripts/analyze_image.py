#!/usr/bin/env python3
"""Analyze Dockerfiles and .dockerignore across Go, Rust, Node.js, and Python for image bloat, distroless/scratch suitability, and build efficiency."""
import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import scrub_object_secrets, scrub_text_secrets, make_error_envelope


def analyze_dockerfile(dockerfile_text: str, dockerignore_text: Optional[str] = None) -> Dict[str, Any]:
    lines = [l.strip() for l in dockerfile_text.splitlines() if l.strip() and not l.strip().startswith("#")]
    from_lines = [l for l in lines if l.upper().startswith("FROM ")]
    run_lines = [l for l in lines if l.upper().startswith("RUN ")]
    copy_lines = [l for l in lines if l.upper().startswith(("COPY ", "ADD "))]
    user_lines = [l for l in lines if l.upper().startswith("USER ")]

    is_multistage = len(from_lines) >= 2
    final_from = from_lines[-1].split()[1] if from_lines else "unknown"

    joined = "\n".join(lines)
    ecosystem = "generic"
    if re.search(r"\b(?:go\s+build|golang:)", joined, re.IGNORECASE):
        ecosystem = "go"
    elif re.search(r"\b(?:cargo\s+build|rust:)", joined, re.IGNORECASE):
        ecosystem = "rust"
    elif re.search(r"\b(?:npm\s+install|npm\s+ci|pnpm|yarn|node:)", joined, re.IGNORECASE):
        ecosystem = "nodejs"
    elif re.search(r"\b(?:pip\s+install|poetry|uv\s+pip|python:)", joined, re.IGNORECASE):
        ecosystem = "python"

    # Evaluate distroless / scratch suitability per language ecosystem
    cgo_disabled = "CGO_ENABLED=0" in joined
    rust_musl = "unknown-linux-musl" in joined
    if ecosystem == "go":
        recommended_runtime_base = (
            "gcr.io/distroless/static-debian12:nonroot or scratch (CGO_ENABLED=0 static binary)"
            if cgo_disabled else
            "gcr.io/distroless/base-debian12:nonroot (or set CGO_ENABLED=0 to enable static distroless/scratch)"
        )
    elif ecosystem == "rust":
        recommended_runtime_base = (
            "gcr.io/distroless/static-debian12:nonroot or scratch (musl static binary)"
            if rust_musl else
            "gcr.io/distroless/cc-debian12:nonroot or debian:bookworm-slim (links libgcc_s/glibc)"
        )
    elif ecosystem == "nodejs":
        recommended_runtime_base = "node:22-bookworm-slim or gcr.io/distroless/nodejs22-debian12:nonroot (scratch is unsuitable for Node.js V8 runtime)"
    elif ecosystem == "python":
        recommended_runtime_base = "python:3.11-slim-bookworm (scratch is unsuitable for CPython interpreter and manylinux C extensions)"
    else:
        recommended_runtime_base = "debian:bookworm-slim or gcr.io/distroless/base-debian12:nonroot"

    findings: List[Dict[str, Any]] = []
    recommendations: List[str] = []

    if not is_multistage and any(b in final_from.lower() for b in ("golang", "rust", "python:3", "node:", "ubuntu", "debian")) and "slim" not in final_from.lower() and "alpine" not in final_from.lower():
        findings.append({
            "id": "IMG-STAGE-001",
            "category": "multi_stage",
            "severity": "high",
            "classification": "verified",
            "title": f"Single-stage build using full SDK/OS base image `{final_from}` ships compilers and build toolchains to production",
            "evidence": {
                "from_stages": len(from_lines),
                "final_base_image": final_from,
                "ecosystem": ecosystem,
                "recommended_runtime_base": recommended_runtime_base,
            },
            "likely_causes": ["No multi-stage separation between build environment and runtime image"],
            "confidence": "high",
            "recommendation": f"Use a multi-stage build and copy only runtime artifacts into `{recommended_runtime_base}`."
        })

    # Detect dynamic Go/Rust binary copied into scratch/alpine without static linking
    if ecosystem == "go" and not cgo_disabled and any(x in final_from.lower() for x in ("scratch", "alpine", "distroless/static")):
        findings.append({
            "id": "IMG-ABI-GO-001",
            "category": "abi_mismatch",
            "severity": "high",
            "classification": "verified",
            "title": f"Go build without `CGO_ENABLED=0` targeting minimal image `{final_from}` risks ExitCode 127 missing dynamic linker failure",
            "evidence": {"cgo_disabled": False, "final_base_image": final_from},
            "likely_causes": ["Default go build links host glibc when net/os/user packages or CGO are used"],
            "confidence": "high",
            "recommendation": "Set `CGO_ENABLED=0 GOOS=linux go build -ldflags='-s -w'` before copying into `scratch` or `distroless/static`."
        })

    if ecosystem == "rust" and not rust_musl and "scratch" in final_from.lower():
        findings.append({
            "id": "IMG-ABI-RUST-001",
            "category": "abi_mismatch",
            "severity": "high",
            "classification": "verified",
            "title": "Rust binary compiled without musl static target copied into `scratch` will fail at startup due to missing `libc.so.6` / `libgcc_s.so.1`",
            "evidence": {"rust_musl": False, "final_base_image": final_from},
            "likely_causes": ["Standard cargo build --release dynamically links glibc and libgcc_s"],
            "confidence": "high",
            "recommendation": "Use `gcr.io/distroless/cc-debian12:nonroot` or compile with `--target x86_64-unknown-linux-musl`."
        })

    for idx, rline in enumerate(run_lines, start=1):
        if "apt-get install" in rline and ("rm -rf /var/lib/apt/lists" not in rline):
            findings.append({
                "id": f"IMG-CACHE-APT-{idx}",
                "category": "layer_bloat",
                "severity": "medium",
                "classification": "verified",
                "title": "apt-get install without cleaning `/var/lib/apt/lists/*` in the same RUN instruction",
                "evidence": {"run_instruction": rline[:160]},
                "likely_causes": ["Apt package lists remain permanently committed in the lower overlayfs layer"],
                "confidence": "high",
                "recommendation": "Chain `&& rm -rf /var/lib/apt/lists/*` inside the exact same `RUN apt-get update && apt-get install -y --no-install-recommends ...` command."
            })
        if "pip install" in rline and "--no-cache-dir" not in rline and "mount=type=cache" not in rline:
            findings.append({
                "id": f"IMG-CACHE-PIP-{idx}",
                "category": "layer_bloat",
                "severity": "medium",
                "classification": "verified",
                "title": "pip install executed without `--no-cache-dir` or BuildKit cache mount",
                "evidence": {"run_instruction": rline[:160]},
                "likely_causes": ["pip stores downloaded wheel archives in ~/.cache/pip inside the image layer"],
                "confidence": "high",
                "recommendation": "Pass `pip install --no-cache-dir` or set `ENV PIP_NO_CACHE_DIR=1`."
            })
        if re.search(r"\bnpm\s+install\b", rline) and "--omit=dev" not in rline and "--production" not in rline and not is_multistage:
            findings.append({
                "id": f"IMG-DEVDEPS-NPM-{idx}",
                "category": "dev_dependencies",
                "severity": "medium",
                "classification": "verified",
                "title": "`npm install` in single-stage image installs devDependencies into production image",
                "evidence": {"run_instruction": rline[:160]},
                "likely_causes": ["Running unfiltered npm install instead of npm ci --omit=dev"],
                "confidence": "high",
                "recommendation": "Use `npm ci --omit=dev && npm cache clean --force` in the production stage."
            })

    copy_all_idx = None
    dep_install_idx = None
    for idx, l in enumerate(lines):
        if re.match(r"^COPY\s+\.\s+", l, re.IGNORECASE) and copy_all_idx is None:
            copy_all_idx = idx
        if re.search(r"\b(?:pip\s+install|npm\s+ci|npm\s+install|go\s+mod\s+download|cargo\s+build)\b", l) and dep_install_idx is None:
            dep_install_idx = idx
    if copy_all_idx is not None and dep_install_idx is not None and copy_all_idx < dep_install_idx:
        findings.append({
            "id": "IMG-CACHETRAP-001",
            "category": "build_cache",
            "severity": "medium",
            "classification": "verified",
            "title": "`COPY . .` appears before dependency installation, invalidating dependency layer cache on every code edit",
            "evidence": {"copy_all_line_index": copy_all_idx, "dep_install_line_index": dep_install_idx},
            "likely_causes": ["Copying full source tree before lockfiles/manifests"],
            "confidence": "high",
            "recommendation": "Copy only `package*.json` / `requirements.txt` / `go.mod` / `Cargo.toml` first, install dependencies, and then `COPY . .`."
        })

    if dockerignore_text is not None:
        ignored = {l.strip().rstrip("/") for l in dockerignore_text.splitlines() if l.strip() and not l.strip().startswith("#")}
        missing_ignores = [item for item in (".git", ".env", "node_modules", "__pycache__", ".venv") if item not in ignored]
        if missing_ignores:
            findings.append({
                "id": "IMG-IGNORE-001",
                "category": "dockerignore",
                "severity": "high" if ".env" in missing_ignores or ".git" in missing_ignores else "medium",
                "classification": "verified",
                "title": f"`.dockerignore` is missing critical exclusions: {', '.join(missing_ignores)}",
                "evidence": {"missing_entries": missing_ignores},
                "likely_causes": ["Incomplete .dockerignore risks leaking .env secrets or .git history into COPY . . layers"],
                "confidence": "high",
                "recommendation": "Add `.git`, `.env*`, `node_modules`, `.venv`, `__pycache__`, and `target/` to `.dockerignore`."
            })

    if not user_lines or user_lines[-1].split()[1] in ("root", "0"):
        findings.append({
            "id": "IMG-USER-001",
            "category": "security",
            "severity": "medium",
            "classification": "verified",
            "title": "Dockerfile does not switch to a non-root USER in the final stage",
            "evidence": {"user_instructions": user_lines},
            "likely_causes": ["Container processes run as UID 0 by default unless USER is specified"],
            "confidence": "high",
            "recommendation": "Create an unprivileged user (`RUN useradd -u 10001 -r -s /sbin/nologin appuser`) and set `USER 10001`."
        })

    status = "warning" if findings else "ok"
    for f in findings:
        if f["recommendation"] not in recommendations:
            recommendations.append(f["recommendation"])

    return scrub_object_secrets({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "size_estimation_policy": "theoretical_recommendations_only_no_fabricated_byte_reductions",
            "ecosystem": ecosystem,
            "is_multistage": is_multistage,
            "stage_count": len(from_lines),
            "final_base_image": final_from,
            "recommended_runtime_base": recommended_runtime_base,
            "run_instruction_count": len(run_lines),
            "copy_instruction_count": len(copy_lines),
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    })


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze Dockerfile and .dockerignore for bloat and anti-patterns.")
    parser.add_argument("--dockerfile", required=True, help="Path to Dockerfile")
    parser.add_argument("--dockerignore", help="Optional path to .dockerignore")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    df = Path(args.dockerfile)
    if not df.exists():
        print(json.dumps(make_error_envelope(f"Dockerfile not found: {df}")), file=sys.stderr)
        return 1

    di_text = None
    if args.dockerignore:
        di = Path(args.dockerignore)
        if di.exists():
            di_text = di.read_text(encoding="utf-8", errors="replace")

    payload = analyze_dockerfile(df.read_text(encoding="utf-8", errors="replace"), di_text)
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
