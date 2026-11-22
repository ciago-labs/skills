# Troubleshooting (`local-vram-tuner`)

## 1. Sudden Drop from 45 tok/s to 4 tok/s During Long Coding Sessions
- **Cause**: Context grew past the KV-cache budget or `num_ctx` triggered partial CPU layer offloading over PCIe.
- **Resolution**: Compact prompt context with `scripts/compact_context.py` and enable `Q8_0` KV-cache quantization.
