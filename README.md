# Ciago Labs — Agent Skills

**Production-focused skills for AI coding agents.**

Ciago Labs Skills is an open-source collection of modular, tested, and security-conscious engineering skills that help AI coding agents perform real-world development and infrastructure tasks more reliably.

Each skill is independently organized within this monorepo, with its own instructions, deterministic scripts, tests, references, examples, and documentation.

[Available Skills](#available-skills) · [Installation](#installation) · [Contributing](#contributing) · [Security](#security)

## Available Skills

| Skill | Description | Status |
|---|---|---|
| [pg-query-surgeon](skills/pg-query-surgeon) | Reviews PostgreSQL migrations for lock hazards, analyzes SQL and EXPLAIN ANALYZE plans, recommends indexes, and designs zero-downtime schema changes. | Available |
| [docker-forensics](skills/docker-forensics) | Read-only audit of Docker images, layer history, container security posture, bridge/DNS networking, and container crash loops (OOM, SIGSEGV, CrashLoopBackOff) for Go, Rust, Node.js, and Python workloads. | Available |
| [linux-perf-doctor](https://github.com/AnujTiwari-Student/linux-perf-doctor) | Read-only Linux performance diagnostics using /proc, /sys, PSI, and cgroup telemetry. Maintained in its own repository. | Standalone |

More engineering skills are in development and will be added to this collection.

## Installation

Replace `<skill>` with a skill name from the [catalog](#available-skills), for example `pg-query-surgeon` or `docker-forensics`. `linux-perf-doctor` is a standalone repository: follow its own README.

### Hermes Agent

```bash
hermes skills inspect ciago-labs/skills/<skill>   # preview only; the scan runs at install
hermes skills install ciago-labs/skills/<skill>
```

Hermes scans community skills before installing them and blocks CAUTION and DANGEROUS verdicts. Do not override the scanner. Each skill documents its controls in its own `SECURITY.md` (`skills/<skill>/SECURITY.md`).

### Cursor, Codex, Gemini CLI, OpenCode and other agents

```bash
npx skills add ciago-labs/skills --skill <skill>
```

This route does not run a local security scan. Review the skill's source and `SECURITY.md` before use.

### Claude Code

```
/plugin marketplace add ciago-labs/skills
```

### Manual installation

```bash
git clone https://github.com/ciago-labs/skills.git
SKILL=<skill>
cp -r "skills/skills/$SKILL" ~/.hermes/skills/    # Hermes
# or: ~/.claude/skills/ (Claude Code), ~/.agents/skills/ (Codex and others)
```

## Example prompts

- *"Use pg-query-surgeon to review this migration for lock hazards before I deploy."*
- *"Here is an EXPLAIN ANALYZE output. Why is this query slow, and what index would fix it?"*
- *"Use docker-forensics to find out why this container keeps exiting with code 137."*

## Design Principles

- **Modular:** each skill is self-contained and independently organized.
- **Verifiable:** skills include tests and deterministic supporting scripts where applicable.
- **Security-conscious:** scripts minimize permissions, avoid unnecessary network access, and protect sensitive information.
- **Transparent:** limitations, assumptions, and operational risks are documented.
- **Agent-compatible:** designed for tools that support the Agent Skills format.

## Repository Layout

```
.
├── .github/workflows/validate.yml   centralized CI for all skills
├── .claude-plugin/marketplace.json  Claude Code marketplace manifest
├── plugins/                         plugins (coming soon)
├── skills/
│   ├── pg-query-surgeon/            SKILL.md, scripts, tests, references, docs
│   └── docker-forensics/            SKILL.md, scripts, tests, references, docs
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── README.md
```

Centralized CI validates and tests every skill in this repository. Standalone projects stay independently maintained and are linked from the catalog.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. All changes must pass the repository's required validation checks.

## Security

Review a skill's source code and permissions before installing it. Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

Distributed under the MIT License. See [LICENSE](LICENSE). Check individual skill directories for any additional licensing terms.
