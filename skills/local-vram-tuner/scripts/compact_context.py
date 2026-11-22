#!/usr/bin/env python3
"""Deterministic prompt context compaction (logs, stack traces, lockfiles, build artifacts, large JSON) and credential redaction engine."""
import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from common import make_error_envelope
from context_analyzer import SECRET_REGEXES, estimate_tokens, is_build_artifact_line, is_large_json_line


def redact_credentials(text: str) -> Tuple[str, int]:
    """Redact complete/malformed PEM private-key blocks and common secret tokens."""
    from common import COMPREHENSIVE_SECRET_PATTERNS, redact_pem_private_keys

    out, pem_count = redact_pem_private_keys(text)
    redacted_count = pem_count
    for name, rx in SECRET_REGEXES:
        if name == "private_key_block":
            continue
        matches = rx.findall(out)
        if matches:
            redacted_count += len(matches)
            out = rx.sub(f"[REDACTED_{name.upper()}]", out)
    for rx, repl in COMPREHENSIVE_SECRET_PATTERNS:
        out, n_subs = rx.subn(repl, out)
        redacted_count += n_subs
    return out, redacted_count


def summarize_large_json_line(line: str) -> str:
    stripped = line.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            keys = list(parsed.keys())[:6]
            return f'{{"_compacted_json_object": true, "total_keys": {len(parsed)}, "sample_keys": {json.dumps(keys)}}}'
        elif isinstance(parsed, list):
            return f'[{{"_compacted_json_array": true, "length": {len(parsed)}}}]'
    except Exception:
        pass
    return stripped[:160] + " ... [truncated]"


def compact_text(
    raw_text: str,
    max_stack_frames: int = 4,
    dedup_logs: bool = True,
    strip_lockfile_noise: bool = True,
    prune_build_artifacts: bool = True,
    compact_large_json: bool = True,
    json_threshold_chars: int = 240,
) -> Tuple[str, Dict[str, Any]]:
    clean_text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", raw_text)
    clean_text, redacted_count = redact_credentials(clean_text)

    lines = clean_text.splitlines()
    out_lines: List[str] = []
    seen_log_lines: Dict[str, int] = {}
    stack_frame_run = 0
    omitted_stack_frames = 0
    total_omitted_stack_frames = 0
    omitted_lockfile_lines = 0
    omitted_duplicate_lines = 0
    omitted_build_artifact_lines = 0
    compacted_json_blobs = 0

    for line in lines:
        stripped = line.strip()

        if strip_lockfile_noise and re.search(
            r"^(?:\"integrity\":\s*\"sha512-|\"resolved\":\s*\"https://registry\.npmjs\.org/|checksum\s*=\s*\"[0-9a-f]{64}\")",
            stripped,
        ):
            omitted_lockfile_lines += 1
            continue

        if prune_build_artifacts and is_build_artifact_line(stripped):
            omitted_build_artifact_lines += 1
            continue

        if compact_large_json and is_large_json_line(stripped, threshold_chars=json_threshold_chars):
            out_lines.append(summarize_large_json_line(stripped))
            compacted_json_blobs += 1
            continue

        is_frame = bool(re.match(r"^(?:at\s+[\w\.$]+\(|File\s+\".*\", line \d+)", stripped))
        if is_frame:
            stack_frame_run += 1
            if stack_frame_run > max_stack_frames:
                omitted_stack_frames += 1
                total_omitted_stack_frames += 1
                continue
        else:
            if omitted_stack_frames > 0:
                out_lines.append(f"  ... [{omitted_stack_frames} repetitive stack frames elided by local-vram-tuner] ...")
                omitted_stack_frames = 0
            stack_frame_run = 0

        if dedup_logs and len(stripped) > 24:
            norm_log = re.sub(r"^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\s*", "", stripped)
            seen_log_lines[norm_log] = seen_log_lines.get(norm_log, 0) + 1
            if seen_log_lines[norm_log] > 2:
                omitted_duplicate_lines += 1
                continue

        out_lines.append(line)

    if omitted_stack_frames > 0:
        out_lines.append(f"  ... [{omitted_stack_frames} repetitive stack frames elided by local-vram-tuner] ...")

    compacted = "\n".join(out_lines) + ("\n" if raw_text.endswith("\n") else "")
    before_tokens = estimate_tokens(raw_text)
    after_tokens = estimate_tokens(compacted)
    saved_tokens = max(0, before_tokens - after_tokens)
    reduction_pct = round((saved_tokens * 100.0 / max(1, before_tokens)), 2)

    stats = {
        "before_characters": len(raw_text),
        "after_characters": len(compacted),
        "before_tokens_estimate": before_tokens,
        "after_tokens_estimate": after_tokens,
        "tokens_saved_estimate": saved_tokens,
        "reduction_pct_estimate": reduction_pct,
        "token_estimation_method": "heuristic_char_div_4_estimate",
        "omitted_duplicate_lines": omitted_duplicate_lines,
        "omitted_stack_frames": total_omitted_stack_frames,
        "omitted_lockfile_lines": omitted_lockfile_lines,
        "omitted_build_artifact_lines": omitted_build_artifact_lines,
        "compacted_large_json_blobs": compacted_json_blobs,
        "redacted_credentials_count": redacted_count,
    }
    return compacted, stats


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compact bloated prompt context and redact secrets without modifying input files.")
    parser.add_argument("--input-file", required=True, help="Path to source context file (read-only)")
    parser.add_argument("--output-file", help="Path to write compacted context file (must differ from --input-file)")
    parser.add_argument("--max-stack-frames", type=int, default=4, help="Maximum consecutive stack frames to retain")
    parser.add_argument("--json-threshold-chars", type=int, default=240, help="Character threshold for compacting single-line JSON blobs")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON report")
    args = parser.parse_args(argv)

    in_path = Path(args.input_file).resolve()
    if not in_path.exists():
        print(json.dumps(make_error_envelope(f"Input file not found: {in_path}")), file=sys.stderr)
        return 1

    if args.output_file:
        out_path = Path(args.output_file).resolve()
        if out_path == in_path:
            print(json.dumps(make_error_envelope("Safety refusal: --output-file must not overwrite --input-file in place.")), file=sys.stderr)
            return 2
    else:
        out_path = None

    raw = in_path.read_text(encoding="utf-8", errors="replace")
    compacted, stats = compact_text(raw, max_stack_frames=args.max_stack_frames, json_threshold_chars=args.json_threshold_chars)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(compacted, encoding="utf-8")

    payload = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release()},
        "tool_versions": {"python": platform.python_version()},
        "findings": [{
            "id": "CTX-COMPACT-001",
            "category": "context_compaction",
            "severity": "info",
            "classification": "measured",
            "title": f"Compacted context by ~{stats['reduction_pct_estimate']}% ({stats['before_tokens_estimate']} -> {stats['after_tokens_estimate']} estimated tokens) and redacted {stats['redacted_credentials_count']} secret(s)",
            "evidence": stats,
            "likely_causes": ["Deterministic deduplication, stack trace pruning, lockfile/build-artifact removal, large JSON summarization, and secret scrubbing"],
            "confidence": "high",
            "recommendation": "Feed compacted output into local coding agent to reduce prefill time and KV-cache usage."
        }],
        "metrics": stats,
        "warnings": [],
        "recommendations": ["Use compacted context file to minimize KV-cache memory pressure."],
        "errors": [],
    }
    print(json.dumps(payload, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
