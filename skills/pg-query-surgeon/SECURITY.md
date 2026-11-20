# Security Policy

## Supported Versions
| Version | Supported |
| :--- | :--- |
| 1.0.x | Yes |

## Reporting a Vulnerability
Report credential-redaction bypasses or SQL parser vulnerabilities via private GitHub Security Advisories. See `docs/SECURITY.md` for details.

## Security Controls Summary

- **Strict Executable Allowlist** (`scripts/common.py`): External process invocation is restricted to an explicit executable allowlist (`psql` only), resolved by basename and absolute path. All non-allowlisted executables and privilege-escalation wrappers are refused before process creation.
- **Bounded Command Execution** (`scripts/common.py`): Optional, user-requested read-only catalog inspection runs through a single isolated runner with argument arrays (`shell=False`), detached standard input, strict execution timeouts, streaming stdout/stderr byte limits, and process-group cleanup.
- **Minimal Child Environment** (`scripts/common.py`): Child-process environments are built from an explicit allowlist of named locale, path, and PostgreSQL client variables so unrelated host credentials and API tokens are never inherited.
