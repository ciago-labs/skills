# stack-architect (`ship-blueprint`)

**Constraint-Driven Technology Stack Compiler, Infrastructure Sizing Engine, and Runnable Day-0 Product Scaffolder**

## 1. Project Name and Positioning
`stack-architect` (also positioned as `ship-blueprint`) is a production-oriented [Agent Skill](https://agentskills.io/specification) that turns product requirements, traffic targets, and budget constraints into deterministic capacity numbers, verified cloud/bare-metal cost comparisons, justified 13-layer stack decisions, and a runnable Day-0 project scaffold.

## 2. Problem Statement
Most system-design prompts and architecture assistants default to recommending Kubernetes, Kafka, microservices, and multi-database topologies regardless of whether the user is a 2-person startup with a $120/month budget or a 50-engineer enterprise.

## 3. What the Skill Actually Does
`stack-architect` ingests 18 operational constraints, builds an explicit Assumptions Register for any unknown inputs, computes workload throughput and hardware sizing with 1x/2x/5x sensitivity analysis, compares verified cloud and bare-metal pricing, selects a right-sized 13-layer technology stack with 7-point justifications, and scaffolds a runnable 16-file Day-0 repository (`docker-compose.yml`, `Dockerfile`, PostgreSQL schema/migrations, `Caddyfile`, `redis.conf`, healthcheck server, CI workflow, Mermaid diagram, ADRs, and runbooks).

## 4. Key Features
- **18-Constraint Questionnaire & Assumptions Register**: Never silently guesses requirements; records every default assumption explicitly.
- **Deterministic Sizing Engine**: Calculates Little's Law concurrency, DB IOPS, network egress, and vCPU/RAM/NVMe capacity with 40% burst headroom.
- **Verified Cloud & Bare-Metal Cost Comparator**: Includes verified pricing records (`2026-11-17`) with source URLs across AWS (`EC2 t4g` + `RDS db.t4g`), Google Cloud (`e2-standard-2` + `Cloud SQL`), Azure (`Standard_B2ms`), and Hetzner Dedicated (`AX42`).
- **Simplicity-First 13-Layer Stack Compiler**: Evaluates every major choice across 7 dimensions (Why selected, Alternatives, Why rejected, Complexity, Cost, Scaling limits, Migration path).
- **Runnable Day-0 Scaffolder & Validator**: Generates internally consistent, non-root, read-only container and database files without overwriting existing repositories.

## 5. Architecture Overview
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 6. Installation
Install with any Agent Skills-compatible client or CLI:
```bash
npx skills add ciago-labs/skills --skill stack-architect
```
Or copy the `stack-architect/` directory into your agent's configured skills folder.

## 7. Supported Agent Environments
See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## 8. Prerequisites
- Python 3.8+ (standard library only).

## 9. Usage Examples
- *"Use `stack-architect` with `examples/saas_constraints.json` to size our infrastructure, compare AWS vs Hetzner vs GCP costs, and scaffold our Day-0 repository."*

## 10. Script Examples
```bash
python3 scripts/requirements_validator.py --input examples/saas_constraints.json --pretty
python3 scripts/workload_calculator.py --input examples/saas_constraints.json --pretty
python3 scripts/infrastructure_sizer.py --input examples/saas_constraints.json --pretty
python3 scripts/cost_estimator.py --input examples/saas_constraints.json --pretty
python3 scripts/stack_selector.py --input examples/saas_constraints.json --pretty
python3 scripts/generate_architecture.py --input examples/saas_constraints.json --format markdown --output examples/sample-blueprint.md
python3 scripts/scaffold_infrastructure.py --input examples/saas_constraints.json --output-dir /tmp/day0-scaffold --force --pretty
python3 scripts/validate_blueprint.py --scaffold-dir /tmp/day0-scaffold --pretty
```

## 11. Example Diagnostic Results
See [`examples/sample-blueprint.md`](examples/sample-blueprint.md), [`examples/sample-blueprint.json`](examples/sample-blueprint.json). Generate the Day-0 scaffold with the commands above.

## 12. Security and Safety Approach
- Refuses to overwrite existing non-empty directories without `--force`.
- Generates placeholder-only `.env.example` files and validates zero hardcoded secrets.
- Enforces non-root UID `10001`, `read_only: true`, and `no-new-privileges:true` in generated container configs. See [`docs/SECURITY.md`](docs/SECURITY.md).

## 13. Limitations
- Sizing formulas represent engineering capacity estimates and must be validated with load tests (`k6` / `vegeta`) against actual application code.

## 14. Testing Instructions
```bash
python3 -m unittest discover -s tests -v
```

## 15. Contribution Instructions
See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## 16. Roadmap
- Add Terraform / OpenTofu single-node and RDS module generators.
- Add multi-region active-passive RPO/RTO latency calculator.

## 17. License
MIT License. See [`LICENSE`](LICENSE).
