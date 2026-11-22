# Reproducible Benchmarks (`stack-architect`)

## Benchmark 1: Low-Budget B2B SaaS ($120/mo, 150 RPS) vs High-Scale Fintech ($1,500/mo, 1,200 RPS)
```bash
# Scenario A: 2-person SaaS team ($120/mo budget, 150 avg RPS / 450 peak RPS)
python3 scripts/generate_architecture.py --input examples/saas_constraints.json --pretty

# Scenario B: 12-person Fintech team ($1,500/mo budget, 1,200 avg RPS / 6,000 peak RPS, 99.99% SLA)
python3 scripts/generate_architecture.py --input examples/high_scale_constraints.json --pretty
```

## Recording Terminal Demonstrations
```bash
asciinema rec -i 1.5 demo-stack-architect.cast
python3 scripts/generate_architecture.py --input examples/saas_constraints.json --format markdown
exit
```
