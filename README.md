# Agent Skills

Open-source skills for AI coding agents (Claude Code, OpenAI Codex, Gemini CLI, OpenCode and other tools that support the [Agent Skills](https://agentskills.io/specification) format).

Each skill is a self-contained folder with a `SKILL.md`, deterministic scripts, tests, and references.

## Skills

| Skill | What it does |
|---|---|
| [pg-query-surgeon](skills/pg-query-surgeon) | Finds lock hazards in PostgreSQL migrations, optimizes slow SQL and EXPLAIN ANALYZE plans, recommends indexes, and designs zero-downtime schema changes. |
| [linux-perf-doctor](https://github.com/AnujTiwari-Student/linux-perf-doctor) | Read-only Linux performance diagnostics using /proc, /sys, PSI and cgroup telemetry. Lives in its own repo. |

More skills, MCP servers, and plugins are on the way.

## Install

### Option 1: `npx skills`

```bash
npx skills add ciago-labs/skills --skill pg-query-surgeon
```

### Option 2: Claude Code plugin marketplace

```
/plugin marketplace add ciago-labs/skills
```

### Option 3: Manual

```bash
git clone https://github.com/ciago-labs/skills.git
mkdir -p ~/.claude/skills
cp -r skills/skills/pg-query-surgeon ~/.claude/skills/
```

For OpenAI Codex, copy to `~/.agents/skills/` instead.

## Example prompts

- *"Use pg-query-surgeon to review this migration for lock hazards before I deploy."*
- *"Here is an EXPLAIN ANALYZE output. Why is this query slow, and what index would fix it?"*

## Repository layout

```
skills/            one folder per skill (SKILL.md + scripts, tests, references)
plugins/           plugins (coming soon)
.claude-plugin/    marketplace manifest
.github/workflows/ CI: frontmatter validation and tests
```

## Contributing

Issues and pull requests are welcome. Each skill folder has its own `CONTRIBUTING.md` with code style and test requirements. CI must pass before merging.

## Security

Skills can run scripts, so review any skill before installing it. Report vulnerabilities as described in each skill's `SECURITY.md`.

## License

MIT. See [LICENSE](LICENSE). Individual skills may carry their own license file.
