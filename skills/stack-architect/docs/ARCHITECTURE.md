# Architecture: `stack-architect` (`ship-blueprint`)

1. **`scripts/requirements_validator.py`**: Validates 18 product/operational constraints and generates an explicit Assumptions Register.
2. **`scripts/workload_calculator.py` & `scripts/infrastructure_sizer.py`**: Computes 1x/2x/5x RPS, Little's Law concurrency, DB IOPS, egress bandwidth, and vCPU/RAM/NVMe allocations.
3. **`scripts/cost_estimator.py`**: Compares verified AWS, GCP, Azure, and Hetzner AX42 rate cards against the monthly budget.
4. **`scripts/stack_selector.py` & `scripts/generate_architecture.py`**: Compiles a 13-layer stack with 7-point justifications, Mermaid diagram, and ADRs.
5. **`scripts/scaffold_infrastructure.py` & `scripts/validate_blueprint.py`**: Materializes and validates a runnable 16-file Day-0 project scaffold.
