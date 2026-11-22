#!/usr/bin/env python3
"""Shared streaming bounded subprocess execution, process-group lifecycle manager, credential/PEM scrubber, and JSON Schema validator."""
import json
import os
import platform
import re
import selectors
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

MAX_SUBPROCESS_OUTPUT_BYTES = 65536
DEFAULT_SUBPROCESS_TIMEOUT_SEC = 5.0
ALLOWED_EXECUTABLES = frozenset({"nvidia-smi", "rocm-smi", "sysctl", "system_profiler"})
_CHILD_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TERM")


def build_child_env(source_env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Build a minimal child-process environment from a fixed allowlist of variable names."""
    out: Dict[str, str] = {}
    for key in _CHILD_ENV_ALLOWLIST:
        val = source_env.get(key) if source_env is not None else os.environ.get(key)
        if val is not None:
            out[key] = val
    return out

FORBIDDEN_MUTATING_SUBCOMMANDS = {
    "stop", "kill", "rm", "rmi", "prune", "build", "push", "restart", "pause", "unpause", "update"
}


def _enable_child_subreaper() -> None:
    """On Linux, mark the current process as a child subreaper (PR_SET_CHILD_SUBREAPER=36) so reparented descendants can be reaped directly."""
    if platform.system() != "Linux":
        return
    try:
        import ctypes
        libc = ctypes.CDLL(None)
        libc.prctl(36, 1, 0, 0, 0)
    except Exception:
        pass


def _reap_process_group(pgid: int) -> None:
    """Reap any terminated child or reparented descendant processes belonging to process group `pgid`."""
    if pgid is None or pgid <= 0:
        return
    while True:
        try:
            wpid, _ = os.waitpid(-pgid, os.WNOHANG)
            if wpid <= 0:
                break
        except ChildProcessError:
            break
        except Exception:
            break


def _linux_proc_has_live_member_in_pgid(pgid: int) -> Optional[bool]:
    """
    On Linux with /proc mounted, inspect whether any process in process group `pgid`
    is in a non-zombie/non-dead state (i.e. state not in {'Z', 'X'}).
    Returns True if a live member is found, False if only zombies or no members exist,
    or None if /proc cannot be inspected.
    """
    proc_root = Path("/proc")
    if platform.system() != "Linux" or not proc_root.exists():
        return None
    try:
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            stat_path = entry / "stat"
            try:
                raw = stat_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rparen = raw.rfind(")")
            if rparen == -1:
                continue
            fields = raw[rparen + 2 :].split()
            # fields[0] is state, fields[2] is pgrp
            if len(fields) >= 3:
                try:
                    entry_pgrp = int(fields[2])
                except ValueError:
                    continue
                if entry_pgrp == pgid and fields[0] not in ("Z", "X"):
                    return True
        return False
    except Exception:
        return None


def is_pid_alive(pid: int) -> bool:
    """Return True if `pid` is currently running and not a terminated zombie process."""
    if pid is None or pid <= 0:
        return False
    try:
        os.waitpid(pid, os.WNOHANG)
    except Exception:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False

    if platform.system() == "Linux":
        stat_path = Path(f"/proc/{pid}/stat")
        try:
            if stat_path.exists():
                raw = stat_path.read_text(encoding="utf-8", errors="replace")
                rparen = raw.rfind(")")
                if rparen != -1:
                    fields = raw[rparen + 2 :].split()
                    if fields and fields[0] in ("Z", "X"):
                        return False
        except Exception:
            pass
    return True


def _is_process_group_alive(pgid: int) -> bool:
    """Return True if at least one non-zombie process in process group `pgid` is still alive."""
    if pgid is None or pgid <= 0:
        return False
    _reap_process_group(pgid)
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False

    proc_check = _linux_proc_has_live_member_in_pgid(pgid)
    if proc_check is not None:
        if not proc_check:
            _reap_process_group(pgid)
        return proc_check
    return True


def _terminate_process_safely(proc: subprocess.Popen, grace_period_sec: float = 0.25) -> Dict[str, bool]:
    """
    Terminate the direct child and its entire process group (`pgid = proc.pid`).
    Do NOT return early when the direct child exits if any descendant process in
    the process group remains alive (e.g., ignoring SIGTERM); wait up to
    `grace_period_sec` for the entire process group to exit, then escalate to
    SIGKILL on the process group and reap all reparented descendants.
    """
    meta = {"sigterm_sent": False, "sigkill_escalated": False}
    pgid = proc.pid
    try:
        proc.poll()
    except Exception:
        pass
    _reap_process_group(pgid)

    if proc.returncode is not None and not _is_process_group_alive(pgid):
        return meta

    # Step 1: Send SIGTERM to the entire process group
    try:
        os.killpg(pgid, signal.SIGTERM)
        meta["sigterm_sent"] = True
    except ProcessLookupError:
        pass
    except Exception:
        pass

    if not meta["sigterm_sent"] and proc.poll() is None:
        try:
            proc.terminate()
            meta["sigterm_sent"] = True
        except Exception:
            pass

    # Step 2: Poll during grace_period_sec until BOTH direct child and all descendants in pgid exit
    deadline = time.monotonic() + max(0.05, grace_period_sec)
    while time.monotonic() < deadline:
        try:
            proc.poll()
        except Exception:
            pass
        if proc.returncode is not None and not _is_process_group_alive(pgid):
            return meta
        time.sleep(0.02)

    # Step 3: Escalate to SIGKILL on the entire process group if direct child or any descendant survived
    try:
        os.killpg(pgid, signal.SIGKILL)
        meta["sigkill_escalated"] = True
    except ProcessLookupError:
        pass
    except Exception:
        pass

    if proc.poll() is None:
        try:
            proc.kill()
            meta["sigkill_escalated"] = True
        except Exception:
            pass

    try:
        proc.wait(timeout=1.0)
    except Exception:
        pass

    # Reap any killed descendants in pgid
    kill_deadline = time.monotonic() + 0.5
    while time.monotonic() < kill_deadline:
        if not _is_process_group_alive(pgid):
            break
        time.sleep(0.02)
    return meta


def run_bounded_command(
    cmd: List[str],
    timeout_sec: float = DEFAULT_SUBPROCESS_TIMEOUT_SEC,
    max_bytes: int = MAX_SUBPROCESS_OUTPUT_BYTES,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    forbidden_subcommands: Optional[set] = None,
    terminate_on_limit: bool = True,
    grace_period_sec: float = 0.25,
    ready_file: Optional[Path] = None,
    startup_timeout_sec: float = 10.0,
    allowed_executables: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Execute an external command using streaming non-blocking I/O capture.
    Enforces true memory-bounded stdout and stderr capture, drains buffered
    output before closing pipes, terminates the entire process group (with
    SIGTERM -> SIGKILL escalation) when output limits or timeouts are exceeded,
    and blocks privilege escalation and unsafe argument types.
    """
    if (
        not isinstance(cmd, list)
        or not cmd
        or not all(isinstance(x, str) and x != "" and "\x00" not in x for x in cmd)
    ):
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "Unsafe or invalid command argument array",
            "truncated": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "terminated_reason": "invalid_arguments",
            "child_pid": None,
        }

    base_bin = os.path.basename(cmd[0])
    eff_allowlist = allowed_executables if allowed_executables is not None else ALLOWED_EXECUTABLES
    if base_bin not in eff_allowlist:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Refused non-allowlisted executable: {base_bin}",
            "truncated": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "terminated_reason": "blocked_executable",
            "child_pid": None,
        }

    if forbidden_subcommands and len(cmd) > 1 and cmd[1] in forbidden_subcommands:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Refused mutating {base_bin} subcommand: {cmd[1]}",
            "truncated": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "terminated_reason": "blocked_mutating_command",
            "child_pid": None,
        }

    if max_bytes <= 0 or timeout_sec <= 0:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "max_bytes and timeout_sec must be positive",
            "truncated": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "terminated_reason": "invalid_limits",
            "child_pid": None,
        }

    resolved_exe = cmd[0] if os.path.isabs(cmd[0]) else shutil.which(cmd[0])
    if not resolved_exe or not os.path.exists(resolved_exe):
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": f"Executable not found: {cmd[0]}",
            "truncated": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "terminated_reason": "executable_not_found",
            "child_pid": None,
        }

    safe_cmd = [resolved_exe] + cmd[1:]
    safe_env = env if env is not None else build_child_env()

    try:
        _enable_child_subreaper()
        proc = subprocess.Popen(
            safe_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=safe_env,
            shell=False,
            start_new_session=True,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": f"Executable not found: {cmd[0]}",
            "truncated": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "terminated_reason": "executable_not_found",
            "child_pid": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc)[:max_bytes],
            "truncated": False,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": False,
            "terminated_reason": "spawn_error",
            "child_pid": None,
        }

    child_pid = proc.pid
    sel = selectors.DefaultSelector()
    stdout_chunks: List[bytes] = []
    stderr_chunks: List[bytes] = []
    stdout_bytes = 0
    stderr_bytes = 0
    stdout_truncated = False
    stderr_truncated = False
    timed_out = False
    terminated_reason: Optional[str] = None

    assert proc.stdout is not None and proc.stderr is not None
    os.set_blocking(proc.stdout.fileno(), False)
    os.set_blocking(proc.stderr.fileno(), False)
    sel.register(proc.stdout, selectors.EVENT_READ, data="stdout")
    sel.register(proc.stderr, selectors.EVENT_READ, data="stderr")

    start_monotonic = time.monotonic()
    startup_Phase = ready_file is not None
    ready_path = Path(ready_file) if ready_file is not None else None
    read_chunk_size = min(4096, max(512, max_bytes))

    def _consume_chunk(stream_name: str, chunk: bytes) -> None:
        nonlocal stdout_bytes, stderr_bytes, stdout_truncated, stderr_truncated
        if stream_name == "stdout":
            space = max_bytes - stdout_bytes
            if space > 0:
                kept = chunk[:space]
                stdout_chunks.append(kept)
                stdout_bytes += len(kept)
            if len(chunk) > space:
                stdout_truncated = True
        else:
            space = max_bytes - stderr_bytes
            if space > 0:
                kept = chunk[:space]
                stderr_chunks.append(kept)
                stderr_bytes += len(kept)
            if len(chunk) > space:
                stderr_truncated = True

    def _drain_ready_pipes(max_iterations: int = 16) -> None:
        """Non-blockingly drain any bytes already buffered in stdout/stderr pipes up to max_bytes."""
        for _ in range(max_iterations):
            if not sel.get_map():
                break
            try:
                ready = sel.select(timeout=0.0)
            except (InterruptedError, BlockingIOError):
                continue
            except Exception:
                break
            if not ready:
                break
            made_progress = False
            for key, _ in ready:
                try:
                    chunk = os.read(key.fd, read_chunk_size)
                except (InterruptedError, BlockingIOError):
                    continue
                except Exception:
                    chunk = b""
                if not chunk:
                    try:
                        sel.unregister(key.fileobj)
                    except Exception:
                        pass
                    continue
                made_progress = True
                _consume_chunk(key.data, chunk)
            if not made_progress:
                break

    try:
        while sel.get_map():
            now = time.monotonic()
            if startup_Phase and ready_path is not None:
                if ready_path.exists():
                    try:
                        if ready_path.stat().st_size > 0:
                            startup_Phase = False
                            start_monotonic = now
                    except Exception:
                        pass
                if startup_Phase:
                    elapsed = now - start_monotonic
                    remaining = max(timeout_sec, startup_timeout_sec) - elapsed
                else:
                    elapsed = 0.0
                    remaining = timeout_sec
            else:
                elapsed = now - start_monotonic
                remaining = timeout_sec - elapsed

            if remaining <= 0:
                _drain_ready_pipes()
                timed_out = True
                terminated_reason = "timeout"
                _terminate_process_safely(proc, grace_period_sec=grace_period_sec)
                _drain_ready_pipes()
                break

            try:
                events = sel.select(timeout=min(0.05, remaining))
            except (InterruptedError, BlockingIOError):
                continue

            if not events:
                if proc.poll() is not None and not _is_process_group_alive(child_pid):
                    _drain_ready_pipes()
                    break
                continue

            for key, _ in events:
                stream_name = key.data
                fd = key.fd
                try:
                    chunk = os.read(fd, read_chunk_size)
                except (InterruptedError, BlockingIOError):
                    continue
                except Exception:
                    chunk = b""

                if not chunk:
                    try:
                        sel.unregister(key.fileobj)
                    except Exception:
                        pass
                    continue

                _consume_chunk(stream_name, chunk)

                if (stdout_truncated or stderr_truncated) and terminate_on_limit:
                    terminated_reason = "output_limit_exceeded"
                    _terminate_process_safely(proc, grace_period_sec=grace_period_sec)
                    break

            if terminated_reason is not None:
                break
    finally:
        try:
            _drain_ready_pipes(max_iterations=4)
        except Exception:
            pass
        try:
            sel.close()
        except Exception:
            pass
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.stderr.close()
        except Exception:
            pass
        _terminate_process_safely(proc, grace_period_sec=grace_period_sec)

    rc = proc.returncode if proc.returncode is not None else -9
    truncated = stdout_truncated or stderr_truncated or timed_out
    stdout_str = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_str = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    if timed_out and "timed out" not in stderr_str.lower():
        suffix = f"\n[Command timed out after {timeout_sec}s]"
        stderr_str = (stderr_str + suffix)[:max_bytes]

    return {
        "ok": (not timed_out and (rc == 0 or terminated_reason == "output_limit_exceeded")),
        "returncode": rc,
        "stdout": stdout_str,
        "stderr": stderr_str,
        "truncated": truncated,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "timed_out": timed_out,
        "terminated_reason": terminated_reason,
        "child_pid": child_pid,
    }


# Complete, mismatched, and fail-closed unclosed PEM private-key regexes
PEM_COMPLETE_BLOCK_RE = re.compile(
    r"-{3,5}BEGIN (?P<label>[A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*)-{3,5}"
    r"[\s\S]*?"
    r"-{3,5}END (?P=label)-{3,5}"
)

PEM_MISMATCHED_BLOCK_RE = re.compile(
    r"-{3,5}BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-{3,5}"
    r"[\s\S]*?"
    r"-{3,5}END [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-{3,5}"
)

# Fail-closed strategy: after all closed blocks (matched or mismatched) are redacted,
# any remaining opening PEM header is an unclosed/truncated block and
# must be redacted through the end of the text so short/malformed lines (e.g. AQID, AQ)
# can never leak.
PEM_UNCLOSED_BLOCK_RE = re.compile(
    r"-{3,5}BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-{3,5}[\s\S]*$"
)

PEM_HEADER_OR_FOOTER_LINE_RE = re.compile(
    r"-{3,5}BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-{3,5}|-{3,5}END [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-{3,5}"
)

# Matches a double-quoted string (with escaped quotes & spaces), a single-quoted string
# (with escaped quotes & spaces), or an unquoted non-whitespace token.
_QUOTED_OR_TOKEN_SECRET_VAL = r'(?:"(?:\\.|[^"\\\r\n])*"|\'(?:\\.|[^\'\\\r\n])*\'|[^\'"\s;,\r\n]+)'

COMPREHENSIVE_SECRET_PATTERNS = [
    # 1. Connection URLs (PostgreSQL, MySQL, MongoDB, Redis, AMQP)
    (re.compile(r'((?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis(?:s)?|amqp(?:s)?)://[^:\s/]*:)(?:"[^"]*"|\'[^\']*\'|[^@\s]+)(@)', re.IGNORECASE), r"\1[REDACTED_URL_PASSWORD]\2"),
    # 2. Authorization headers (Bearer, Basic, Token, Digest, ApiKey) — quoted header or quoted/unquoted token
    (re.compile(r"(\bAuthorization\s*[:=]\s*['\"](?:Bearer|Basic|Token|Digest|ApiKey)\s+)([^'\"\r\n]+)(['\"])", re.IGNORECASE), r"\1[REDACTED_AUTH_HEADER]\3"),
    (re.compile(r"(\bAuthorization\s*[:=]\s*(?:Bearer|Basic|Token|Digest|ApiKey)\s+)" + _QUOTED_OR_TOKEN_SECRET_VAL, re.IGNORECASE), r"\1[REDACTED_AUTH_HEADER]"),
    # 3. Standalone Bearer tokens
    (re.compile(r'(\bBearer\s+)(?:"(?:\\.|[^"\\\r\n])*"|\'(?:\\.|[^\'\\\r\n])*\'|[A-Za-z0-9\-\._~\+/]{16,}=*)', re.IGNORECASE), r"\1[REDACTED_BEARER_TOKEN]"),
    # 4. AWS Access Key ID & Secret Access Key
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY_ID]"),
    (re.compile(r"((?:AWS_SECRET_ACCESS_KEY|aws_secret_access_key)(?:['\"])?\s*[=:]\s*)" + _QUOTED_OR_TOKEN_SECRET_VAL), r"\1[REDACTED_AWS_SECRET_KEY]"),
    # 5. GitHub tokens (classic & fine-grained PATs)
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,})\b"), "[REDACTED_GITHUB_TOKEN]"),
    # 6. OpenAI / Anthropic / Stripe / Google / Slack / SendGrid API keys
    (re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{12,}\b"), "[REDACTED_STRIPE_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "[REDACTED_GCP_API_KEY]"),
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b"), "[REDACTED_SENDGRID_KEY]"),
    # 7. GCP JSON private_key escaped newline fields (closed or unclosed)
    (re.compile(r'("private_key"\s*:\s*")-{3,5}BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-{3,5}.*?(")', re.DOTALL), r'\1[REDACTED_PRIVATE_KEY]\2'),
    # 8. Docker registry auth base64 & docker login -p / --password (supports quoted multiword secrets)
    (re.compile(r'("auth"\s*:\s*")([A-Za-z0-9+/=]{12,})(")'), r'\1[REDACTED_DOCKER_AUTH]\3'),
    (re.compile(r"(\bdocker\s+login\b[^\r\n]*?(?:-p|--password)(?:\s*=\s*|\s+))" + _QUOTED_OR_TOKEN_SECRET_VAL, re.IGNORECASE), r"\1[REDACTED_DOCKER_PASSWORD]"),
    # 9. Redis requirepass & Azure AccountKey (supports quoted multiword secrets)
    (re.compile(r"(\brequirepass\s+)" + _QUOTED_OR_TOKEN_SECRET_VAL, re.IGNORECASE), r"\1[REDACTED_REDIS_PASSWORD]"),
    (re.compile(r"(AccountKey\s*=\s*)" + _QUOTED_OR_TOKEN_SECRET_VAL, re.IGNORECASE), r"\1[REDACTED_AZURE_ACCOUNT_KEY]"),
    # 10. Generic password/secret/token/key assignments (ENV, CLI flags, YAML/JSON/INI; supports quoted multiword secrets)
    (
        re.compile(
            r"(\b(?:[A-Z0-9_]*?(?:PASSWORD|PASSWD|PWD|SECRET|PRIVATE_KEY|API_KEY|ACCESS_KEY|AUTH_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|SESSION_TOKEN|BEARER_TOKEN|ID_TOKEN|SECRET_TOKEN|CLIENT_SECRET|WEBHOOK_SECRET|ENCRYPTION_KEY|SIGNING_KEY|MASTER_KEY)[A-Z0-9_]*|(?:[A-Z0-9_]+_)?TOKEN)(?:['\"])?\s*[=:]\s*)"
            + _QUOTED_OR_TOKEN_SECRET_VAL,
            re.IGNORECASE,
        ),
        r"\1[REDACTED_SECRET]",
    ),
    (
        re.compile(
            r"((?:--password|--passwd|--token|--api-key|--apikey|--access-token|--auth-token|--secret|--client-secret)(?:\s*=\s*|\s+))"
            + _QUOTED_OR_TOKEN_SECRET_VAL,
            re.IGNORECASE,
        ),
        r"\1[REDACTED_SECRET]",
    ),
]

_CLI_SECRET_FLAG_RE = re.compile(
    r"^(?:--password|--passwd|--token|--api-key|--apikey|--access-token|--auth-token|--secret|--client-secret|-p)$",
    re.IGNORECASE,
)


def redact_pem_private_keys(text: str) -> Tuple[str, int]:
    """Redact complete, mismatched, unclosed/truncated, and orphan-footer PEM private-key blocks."""
    count = 0
    out = text

    def _repl(match: re.Match) -> str:
        nonlocal count
        count += 1
        return "[REDACTED_PRIVATE_KEY]"

    out = PEM_COMPLETE_BLOCK_RE.sub(_repl, out)
    out = PEM_MISMATCHED_BLOCK_RE.sub(_repl, out)
    out = PEM_UNCLOSED_BLOCK_RE.sub(_repl, out)
    if PEM_HEADER_OR_FOOTER_LINE_RE.search(out):
        out = PEM_HEADER_OR_FOOTER_LINE_RE.sub(_repl, out)
    return out, count


def scrub_text_secrets(text: str) -> str:
    if not text:
        return text
    out, _ = redact_pem_private_keys(text)
    for rx, repl in COMPREHENSIVE_SECRET_PATTERNS:
        out = rx.sub(repl, out)
    return out


def scrub_object_secrets(obj: Any) -> Any:
    """Recursively scrub secrets from dicts, lists (including split CLI flag + value pairs), and strings."""
    if isinstance(obj, str):
        return scrub_text_secrets(obj)
    if isinstance(obj, list):
        sanitized_list: List[Any] = []
        skip_next = False
        for idx, item in enumerate(obj):
            if skip_next:
                skip_next = False
                sanitized_list.append("[REDACTED_SECRET]")
                continue
            if isinstance(item, str) and _CLI_SECRET_FLAG_RE.match(item.strip()) and idx + 1 < len(obj) and isinstance(obj[idx + 1], str):
                sanitized_list.append(item)
                skip_next = True
            else:
                sanitized_list.append(scrub_object_secrets(item))
        return sanitized_list
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            if isinstance(v, str) and re.search(
                r"(?:PASSWORD|PASSWD|SECRET|PRIVATE_KEY|API_KEY|ACCESS_KEY|TOKEN|AUTH)",
                str(k),
                re.IGNORECASE,
            ) and v not in ("[REDACTED_FOR_SECURITY]", "[REDACTED_SECRET]", "[REDACTED_PRIVATE_KEY]") and not str(k).lower().endswith(("_count", "_detected", "_present", "_type", "_keys", "_status", "_estimation_method")):
                sanitized[k] = "[REDACTED_SECRET]"
            else:
                sanitized[k] = scrub_object_secrets(v)
        return sanitized
    return obj


def redact_secrets(text: str) -> str:
    return scrub_text_secrets(text)

def make_error_envelope(msg: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "tool_versions": {"python": platform.python_version()},
        "findings": [],
        "metrics": {},
        "warnings": [],
        "recommendations": [],
        "errors": [scrub_text_secrets(msg)],
    }

def validate_against_schema(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """Deterministic recursive JSON Schema validator supporting type, required, enum, minLength, items, properties."""
    errors: List[str] = []
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(instance, dict):
            return [f"{path}: expected object, got {type(instance).__name__}"]
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property '{req}'")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errors.extend(validate_against_schema(v, props[k], f"{path}.{k}"))
    elif expected_type == "array":
        if not isinstance(instance, list):
            return [f"{path}: expected array, got {type(instance).__name__}"]
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(instance):
                errors.extend(validate_against_schema(item, item_schema, f"{path}[{idx}]"))
    elif expected_type == "string":
        if not isinstance(instance, str):
            return [f"{path}: expected string, got {type(instance).__name__}"]
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: string length {len(instance)} < minLength {schema['minLength']}")
    elif expected_type == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            return [f"{path}: expected integer, got {type(instance).__name__}"]
    elif expected_type == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            return [f"{path}: expected number, got {type(instance).__name__}"]
    elif expected_type == "boolean":
        if not isinstance(instance, bool):
            return [f"{path}: expected boolean, got {type(instance).__name__}"]

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in enum {schema['enum']}")
    return errors
