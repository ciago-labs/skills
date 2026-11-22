# Contributing to `local-vram-tuner`

1. Keep all scripts compatible with Python 3.8+ standard library.
2. Only add model presets to `MODEL_PRESETS` using verified `config.json` architectural parameters (`num_hidden_layers`, `num_key_value_heads`, `head_dim`).
3. Ensure unit tests pass via `python3 -m unittest discover -s tests -v`.
