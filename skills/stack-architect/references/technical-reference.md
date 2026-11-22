# Technical Reference: Capacity Sizing Formulas & Verified Pricing Methodology

## 1. Little's Law & Compute Headroom
- **Active Concurrency ($L$)**: $L = \\lambda_{\\text{peak}} \\times W$, where $\\lambda_{\\text{peak}}$ is peak requests/sec and $W$ is average request residency time ($\\approx 0.5 \\times \\text{p95 latency}$).
- **Application CPU Sizing**: $\\text{vCPUs} = \\text{next\\_pow2}(\\frac{\\lambda_{\\text{peak}}}{250} \\times 1.40)$ to preserve a 40% burst headroom margin.
- **Database Storage & Working Set**: $\\text{Year-1 Storage} = (\\text{Initial GB} + 12 \\times \\text{Monthly Growth GB}) \\times 1.35$ (accounting for B-Tree indexes, WAL segments, and MVCC dead-tuple headroom).

## 2. Verified Cloud & Bare-Metal Rate Cards (`2026-11-17`)
All pricing records in `scripts/cost_estimator.py` link directly to official AWS, Google Cloud, Hetzner, and cloud rate-card aggregators verified on `2026-11-17`.
