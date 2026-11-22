# Architecture Workflows (`stack-architect`)

## Workflow 1: Green-Field Product Architecture & Day-0 Scaffolding
1. Populate or validate constraints with `scripts/requirements_validator.py`.
2. Review the Assumptions Register with the user for any `"unknown"` inputs.
3. Run `scripts/generate_architecture.py` to produce the 12-section blueprint.
4. Run `scripts/scaffold_infrastructure.py` and `scripts/validate_blueprint.py` to generate the runnable project directory.
