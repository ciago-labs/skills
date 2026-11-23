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
| [local-vram-tuner](skills/local-vram-tuner) | Diagnoses local LLM inference bottlenecks on Ollama, llama.cpp, and vLLM: probes NVIDIA, AMD, Apple Silicon, and CPU memory, calculates KV-cache VRAM budgets and safe context windows across FP16, Q8_0, and Q4_0, and compacts bloated agent prompts while redacting secrets. | Available |
| [stack-architect](skills/stack-architect) | Turns product constraints into a sized and costed infrastructure blueprint: workload math, AWS vs Hetzner vs GCP cost comparison, runtime and stack selection, and a validated Day-0 scaffold (Compose, Dockerfile, Caddy, PostgreSQL schema, ADRs, runbook). | Available |
| [linux-perf-doctor](https://github.com/AnujTiwari-Student/linux-perf-doctor) | Read-only Linux performance diagnostics using /proc, /sys, PSI, and cgroup telemetry. Maintained in its own repository. | Standalone |

More engineering skills are in development and will be added to this collection.

## Installation

Replace `<skill>` with a skill name from the [catalog](#available-skills), for example `pg-query-surgeon` or `docker-forensics`. `linux-perf-doctor` is a standalone repository: follow its own README.

### Hermes Agent

```bash
hermes skills inspect ciago-labs/skills/skills/<skill>   # preview only; the scan runs at install
hermes skills install ciago-labs/skills/skills/<skill>
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
git clone https://github.com/ciago-labs/skills.git && cd skills
SKILL=<skill>
cp -r "skills/$SKILL" ~/.hermes/skills/    # Hermes
# or: ~/.claude/skills/ (Claude Code), ~/.agents/skills/ (Codex and others)
```

Manual copying runs no security scan. Review the skill's source and `SECURITY.md` first.

## Example prompts

- *"Use pg-query-surgeon to review this migration for lock hazards before I deploy."*
- *"Here is an EXPLAIN ANALYZE output. Why is this query slow, and what index would fix it?"*
- *"Use docker-forensics to find out why this container keeps exiting with code 137."*
- *"Use local-vram-tuner to calculate the maximum safe context window for qwen2.5-coder-7b (Q4_K_M) on my 6 GB RTX 4060."*
- *"Use stack-architect to size infrastructure for my SaaS constraints, compare AWS vs Hetzner vs GCP costs, and scaffold the Day-0 repository."*

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
│   ├── docker-forensics/            SKILL.md, scripts, tests, references, docs
│   ├── local-vram-tuner/            SKILL.md, scripts, tests, references, docs
│   └── stack-architect/             SKILL.md, scripts, tests, references, docs
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
