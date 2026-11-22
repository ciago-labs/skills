#!/usr/bin/env python3
"""Analyze prompt or context files for token bloat, repeated stack traces, lockfiles, build artifacts, large JSON objects, and secrets."""
import argparse
import json
import platform
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope, scrub_object_secrets


SECRET_REGEXES = [
    ("openai_or_api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+/]+=*", re.IGNORECASE)),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-----|-----END [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-----")),
]


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def is_build_artifact_line(line: str) -> bool:
    stripped = line.strip()
    if re.search(r"^(?:dist/|build/|\.next/|target/release/|target/debug/|out/|coverage/|node_modules/)", stripped):
        return True
    if "sourceMappingURL=data:application/json;base64," in stripped:
        return True
    # Minified JS/CSS bundle line: > 300 chars and < 2% whitespace
    if len(stripped) > 300 and (stripped.count(" ") / max(1, len(stripped))) < 0.02:
        return True
    return False


def is_large_json_line(line: str, threshold_chars: int = 240) -> bool:
    stripped = line.strip()
    if len(stripped) >= threshold_chars and ((stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]"))):
        try:
            json.loads(stripped)
            return True
        except Exception:
            return False
    return False


def analyze_context_text(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    total_chars = len(text)
    est_tokens = estimate_tokens(text)

    line_counts = Counter(l.strip() for l in lines if len(l.strip()) > 20)
    duplicate_lines = sum(cnt - 1 for _, cnt in line_counts.items() if cnt > 1)
    duplicate_chars = sum(len(line) * (cnt - 1) for line, cnt in line_counts.items() if cnt > 1)

    stack_trace_lines = sum(1 for l in lines if re.search(r"^\s*(?:at\s+[\w\.$]+\(|File\s+\".*\", line \d+|Traceback \(most recent call last\))", l))
    lockfile_lines = sum(1 for l in lines if re.search(r"^\s*(?:\"integrity\":\s*\"sha512-|\"resolved\":\s*\"https://registry\.npmjs\.org/|checksum\s*=\s*\"[0-9a-f]{64}\")", l))
    build_artifact_lines = sum(1 for l in lines if is_build_artifact_line(l))
    large_json_lines = sum(1 for l in lines if is_large_json_line(l))
    ansi_escapes = len(re.findall(r"\x1b\[[0-9;]*[a-zA-Z]", text))

    detected_secrets: List[Dict[str, Any]] = []
    for name, rx in SECRET_REGEXES:
        matches = rx.findall(text)
        if matches:
            detected_secrets.append({"type": name, "count": len(matches)})

    findings = []
    recommendations = []
    status = "ok"

    if detected_secrets:
        status = "warning"
        findings.append({
            "id": "CTX-SEC-001",
            "category": "secret_exposure",
            "severity": "high",
            "classification": "verified",
            "title": f"Detected {sum(s['count'] for s in detected_secrets)} potential credential/secret token(s) in prompt context",
            "evidence": {"secret_types": detected_secrets},
            "likely_causes": ["Raw `.env`, CLI command history, or HTTP headers pasted into agent context"],
            "confidence": "high",
            "recommendation": "Run scripts/compact_context.py to automatically redact credentials before sending context to an LLM."
        })

    bloat_chars = duplicate_chars + (lockfile_lines * 60) + (build_artifact_lines * 150) + (large_json_lines * 250)
    bloat_pct = round(min(99.0, (bloat_chars * 100.0 / max(1, total_chars))), 2)
    if duplicate_lines >= 5 or lockfile_lines >= 5 or stack_trace_lines >= 15 or build_artifact_lines >= 1 or large_json_lines >= 1:
        if status == "ok":
            status = "warning"
        findings.append({
            "id": "CTX-BLOAT-001",
            "category": "context_bloat",
            "severity": "medium",
            "classification": "measured",
            "title": (
                f"Detected compactable noise ({duplicate_lines} duplicate lines, {lockfile_lines} lockfile lines, "
                f"{stack_trace_lines} stack-trace frames, {build_artifact_lines} build-artifact lines, {large_json_lines} large JSON blobs)"
            ),
            "evidence": {
                "duplicate_lines": duplicate_lines,
                "lockfile_lines": lockfile_lines,
                "stack_trace_lines": stack_trace_lines,
                "build_artifact_lines": build_artifact_lines,
                "large_json_lines": large_json_lines,
                "ansi_escape_sequences": ansi_escapes,
                "estimated_bloat_pct": bloat_pct,
            },
            "likely_causes": ["Repeated test runner output, lockfile dumps, minified build bundles, or large raw JSON payloads"],
            "confidence": "high",
            "recommendation": "Compact context with scripts/compact_context.py to reduce prompt evaluation latency and KV-cache footprint."
        })

    if not findings:
        findings.append({
            "id": "CTX-OK-001",
            "category": "context_analysis",
            "severity": "info",
            "classification": "measured",
            "title": "Prompt context is clean with minimal duplication and zero detected credentials",
            "evidence": {"estimated_tokens": est_tokens, "total_lines": len(lines)},
            "likely_causes": ["Well-scoped context payload"],
            "confidence": "high",
            "recommendation": "No context compaction required."
        })

    for f in findings:
        recommendations.append(f["recommendation"])

    return scrub_object_secrets({
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": findings,
        "metrics": {
            "total_characters": total_chars,
            "total_lines": len(lines),
            "estimated_tokens": est_tokens,
            "token_estimation_method": "heuristic_char_div_4_estimate",
            "noise_breakdown": {
                "duplicate_long_lines": duplicate_lines,
                "lockfile_noise_lines": lockfile_lines,
                "stack_trace_lines": stack_trace_lines,
                "build_artifact_lines": build_artifact_lines,
                "large_json_lines": large_json_lines,
                "ansi_escape_sequences": ansi_escapes,
            },
            "secrets_detected": detected_secrets,
        },
        "warnings": [],
        "recommendations": recommendations,
        "errors": [],
    })


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze prompt context for bloat and secrets.")
    parser.add_argument("--input-file", required=True, help="Path to context text file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    p = Path(args.input_file)
    if not p.exists():
        print(json.dumps(make_error_envelope(f"Input file not found: {p}")), file=sys.stderr)
        return 1

    payload = analyze_context_text(p.read_text(encoding="utf-8", errors="replace"))
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
