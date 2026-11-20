# Security Policy

## Supported Versions
| Version | Supported |
| :--- | :--- |
| 1.0.x | Yes |

## Reporting a Vulnerability
Report credential-redaction bypasses or SQL parser vulnerabilities via private GitHub Security Advisories. See `docs/SECURITY.md` for details.

## Notes for installer security scanners

Some agent installers (for example Hermes Agent) scan community skills and may report a CAUTION verdict for this one. The findings and what they refer to:

- **`sudo`, `su`, `pkexec`, `doas`** (`scripts/common.py`, `tests/`): a blocklist. The read-only command runner refuses to execute these binaries, and a test checks that it does. They are not invoked by the skill.
- **`subprocess`** (`scripts/common.py`, `tests/`): used by the bounded command runner for optional, user-requested read-only inspection through `psql`, with a timeout and an output limit, and by tests that exercise timeouts and process cleanup.
- **`os.environ`** (`scripts/common.py`, `tests/test_child_env.py`): read to build an allowlisted environment for the `psql` child process, so unrelated variables such as cloud credentials and API tokens are not passed to it. A test verifies this.

Review the source before installing, as with any skill that runs scripts.
