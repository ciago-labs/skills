# Contributing

Thanks for helping improve Ciago Labs Agent Skills.

## Ground rules

- One skill per folder under `skills/`. The folder name must match the `name` in its `SKILL.md` frontmatter.
- Every skill needs a specific `description` that says what it does and when to use it.
- Scripts must be deterministic and read-only by default. Anything that modifies a system or contacts the network must be opt-in and documented.
- Never commit secrets, credentials, personal paths, or real connection strings.
- Add or update tests for any behavior you change.

## Local checks

Run these before opening a pull request:

```bash
# run one skill's tests
cd skills/<skill-name>
python3 -m unittest discover -s tests -v

# compile all scripts
python3 -m compileall -q skills
```

CI runs the same checks on Python 3.8, 3.11, and 3.12, plus frontmatter, JSON, and shell-syntax validation.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep each PR focused on one skill or one change.
3. Describe what changed and why, and how you tested it.
4. All required checks must pass before merging.

## Adding a new skill

1. Create `skills/<skill-name>/` with a `SKILL.md`. Add `scripts/`, `tests/`, `references/`, and `examples/` as needed.
2. Add the skill path to `.claude-plugin/marketplace.json`.
3. Add a row to the skill table in the root `README.md`.
4. Include a `CHANGELOG.md` inside the skill folder.

## Reporting bugs and requesting features

Open a GitHub issue. For security problems, do not open a public issue. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the MIT License.
