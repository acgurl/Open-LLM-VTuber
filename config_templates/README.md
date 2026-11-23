# Configuration templates

| Template | Runtime file | Setup |
| --- | --- | --- |
| `conf.default.yaml` | `conf.yaml` | Copied on first start when missing. Use `conf.ZH.default.yaml` instead if you prefer the Chinese template. |
| `mcp_servers.default.json` | `mcp_servers.json` | Copied on first start when missing. |
| [`llm_models.default.yaml`](./llm_models.default.yaml) | `llm_models.yaml` | Top-level `models`; path: `system_config.llm_models_file`. See [LLM examples](./llm_models.example.yaml). |
| [`tts_models.default.yaml`](./tts_models.default.yaml) | `tts_models.yaml` | Top-level `tts_models`; path: `system_config.tts_models_file`. See [TTS examples](./tts_models.example.yaml). |
| [`asr_models.default.yaml`](./asr_models.default.yaml) | `asr_models.yaml` | Top-level `asr_models`; path: `system_config.asr_models_file`. See [ASR examples](./asr_models.example.yaml). |

**Copy all three model templates manually before first start.** Use the repository root for local
setup or `conf/` for Docker. Each path can be configured independently.

The minimal catalogs define `local-qwen`, `edge-default`, and `groq-whisper`, the IDs expected by
both default character templates and the tracked character preset. The defaults require a reachable
Ollama endpoint with `qwen2.5:latest`, network access for Edge TTS, and `GROQ_API_KEY` in the server
process environment (or a key configured in `asr_models.yaml`). Alternatively, reference models you
have configured for each role instead.

Add only the examples you have configured. LLM provider fields go directly on entries in `models`;
speech entries have their own `settings` mapping, with all required provider fields. Use
`settings: {}` for `pyttsx3_tts`. There is no inline speech configuration to inherit.

Runtime files can contain credentials; keep them out of Git. Do not overwrite existing catalogs
with these templates. An old combined catalog must be [split manually](../README.md#upgrading-from-a-combined-model-catalog)
without changing IDs; there is no runtime fallback. For older configurations, see
[upgrading from inline model settings](../README.md#upgrading-from-inline-model-settings).
