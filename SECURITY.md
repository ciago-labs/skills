# Security Policy

Skills in this repository can include scripts that run on your machine. Review a skill's source code and permissions before installing it.

## Reporting a vulnerability

Please do not report security issues in public issues or pull requests.

Use GitHub's private vulnerability reporting: open the **Security** tab of this repository and choose **Report a vulnerability**.

Include:
- the affected skill and version
- steps to reproduce
- the impact you expect

We will acknowledge reports as soon as we can and keep you updated on the fix.

## Scope

In scope: scripts, parsers, and redaction logic in any skill in this repository, and the CI and marketplace configuration.

Out of scope: vulnerabilities in third-party tools a skill optionally calls (for example `psql`, `perf`, or `strace`). Report those to the upstream project.

## Supported versions

Only the latest release of each skill receives security fixes.
