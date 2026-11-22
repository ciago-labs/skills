# Technical Reference: Transformer KV-Cache Mathematics & Quantization

## 1. Exact KV-Cache Memory Formula
For a decoder-only transformer using Multi-Head Attention (MHA) or Grouped-Query Attention (GQA), the KV-cache memory in bytes is:

$$\\text{KV Bytes} = 2 \\times L \\times H_{kv} \\times D_h \\times B_{elem} \\times C \\times S$$

Where:
- $2$: Key and Value tensors
- $L$: Number of transformer layers (`num_hidden_layers`)
- $H_{kv}$: Number of Key/Value heads (`num_key_value_heads`)
- $D_h$: Head dimension (`hidden_size / num_attention_heads`, typically `128`)
- $B_{elem}$: Bytes per KV element (`2.0` for `FP16`/`BF16`, `1.0625` for `Q8_0`, `0.5625` for `Q4_0`)
- $C$: Context length in tokens
- $S$: Number of concurrent sequences (`OLLAMA_NUM_PARALLEL` or `--parallel`)

## 2. Why GQA Models Scale Better than MHA on Constrained VRAM
A 7B model with 28 layers and GQA ($H_{kv}=4, D_h=128$) consumes only `56 KiB/token` in `FP16` (`1.75 GiB` at 32k context) and `29.75 KiB/token` in `Q8_0` (`0.93 GiB` at 32k context).
