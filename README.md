# Ciago Labs — Agent Skills

**Production-focused skills for AI coding agents.**

Ciago Labs Skills is an open-source collection of modular, tested, and security-conscious engineering skills that help AI coding agents perform real-world development and infrastructure tasks more reliably.

Each skill is independently organized within this monorepo, with its own instructions, deterministic scripts, tests, references, examples, and documentation.

[Available Skills](#available-skills) · [Installation](#installation) · [Contributing](#contributing) · [Security](#security)

## Available Skills

| Skill | Description | Status |
|---|---|---|
| [pg-query-surgeon](skills/pg-query-surgeon) | Reviews PostgreSQL migrations for lock hazards, analyzes SQL and EXPLAIN ANALYZE plans, recommends indexes, and designs zero-downtime schema changes. | Available |
| [linux-perf-doctor](https://github.com/AnujTiwari-Student/linux-perf-doctor) | Read-only Linux performance diagnostics using /proc, /sys, PSI, and cgroup telemetry. Maintained in its own repository. | Standalone |

More engineering skills are in development and will be added to this collection.

## Installation

### Install an individual skill

```bash
npx skills add ciago-labs/skills --skill pg-query-surgeon
```

### Install through the Claude Code marketplace

```
/plugin marketplace add ciago-labs/skills
```

### Manual installation

```bash
git clone https://github.com/ciago-labs/skills.git
mkdir -p ~/.claude/skills
cp -r skills/skills/pg-query-surgeon ~/.claude/skills/
```

For OpenAI Codex, use `~/.agents/skills/` as the destination.

## Example prompts

- *"Use pg-query-surgeon to review this migration for lock hazards before I deploy."*
- *"Here is an EXPLAIN ANALYZE output. Why is this query slow, and what index would fix it?"*

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
│   └── pg-query-surgeon/            SKILL.md, scripts, tests, references, docs
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
