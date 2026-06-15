# BYOK and local models

Copilot CLI supports **Bring-Your-Own-Key (BYOK)** custom model providers via
`COPILOT_PROVIDER_*` environment variables. This works with any OpenAI-compatible endpoint
(Ollama, vLLM, LM Studio, Foundry Local), Azure OpenAI, or Anthropic. In
`copilot-experiments`, a BYOK provider is expressed as a `ProviderConfig` on a `Variant` — a
variant is simply *flags + environment*.

## `ProviderConfig`

```python
from copilot_experiments import ProviderConfig, Variant

ollama = ProviderConfig(
    base_url="http://localhost:11434/v1",
    type="openai",                 # openai | azure | anthropic
    model_id="qwen2.5-coder:7b",   # the provider's model name
    # api_key="...",               # if your endpoint requires one
)

variant = Variant(name="local-qwen", model="qwen2.5-coder:7b", provider=ollama)
```

### Fields → environment variables

| `ProviderConfig` field | Environment variable |
| --- | --- |
| `base_url` | `COPILOT_PROVIDER_BASE_URL` |
| `type` | `COPILOT_PROVIDER_TYPE` |
| `api_key` | `COPILOT_PROVIDER_API_KEY` |
| `bearer_token` | `COPILOT_PROVIDER_BEARER_TOKEN` |
| `wire_api` | `COPILOT_PROVIDER_WIRE_API` (`completions` / `responses`) |
| `model_id` | `COPILOT_PROVIDER_MODEL_ID` |
| `wire_model` | `COPILOT_PROVIDER_WIRE_MODEL` |
| `azure_api_version` | `COPILOT_PROVIDER_AZURE_API_VERSION` |
| `max_prompt_tokens` | `COPILOT_PROVIDER_MAX_PROMPT_TOKENS` |
| `max_output_tokens` | `COPILOT_PROVIDER_MAX_OUTPUT_TOKENS` |

`api_key` and `bearer_token` are **redacted** in stored artifacts (`variant.json`, the index).
As a safety net, secret-looking `Variant.env` values (keys containing `token`, `key`, `secret`,
`password`, `bearer`, `credential`, `authorization`) are redacted there too.

## Examples

### Ollama (local)

```python
ProviderConfig(base_url="http://localhost:11434/v1", type="openai", model_id="llama3.1:8b")
```

```bash
ollama serve            # in another terminal
ollama pull llama3.1:8b
```

### vLLM (local / self-hosted)

```python
ProviderConfig(
    base_url="http://localhost:8000/v1",
    type="openai",
    model_id="Qwen/Qwen2.5-Coder-7B-Instruct",
    api_key="EMPTY",     # vLLM accepts any non-empty key by default
)
```

### Azure OpenAI

```python
ProviderConfig(
    base_url="https://<resource>.openai.azure.com/openai/deployments/<deployment>",
    type="azure",
    azure_api_version="2024-08-01-preview",
    api_key="...",       # prefer reading from the environment, see below
)
```

### Anthropic

```python
ProviderConfig(base_url="https://api.anthropic.com", type="anthropic", api_key="...")
```

## Keeping secrets out of source

Do **not** hard-code keys in experiment files. Read them from the environment instead:

```python
import os
from copilot_experiments import ProviderConfig

provider = ProviderConfig(
    base_url=os.environ["MY_LLM_BASE_URL"],
    type="openai",
    api_key=os.environ.get("MY_LLM_API_KEY"),
    model_id="qwen2.5-coder:7b",
)
```

Stored artifacts redact secrets regardless, but reading from the environment avoids ever putting
them in the repository.

## Comparing hosted vs. local in one experiment

Put hosted and BYOK variants side by side; the runner executes them under identical tasks and
trials so results are directly comparable:

```python
variants = [
    Variant(name="opus", model="claude-opus-4.7", reasoning_effort="medium", trials=5),
    Variant(name="gpt-5", model="gpt-5.2", trials=5),
    Variant(name="local-qwen", model="qwen2.5-coder:7b", provider=ollama, trials=5),
]
```

## Notes

- A real run (hosted or BYOK) requires a working `copilot` CLI; dry-runs never contact a provider.
- Token-usage metrics depend on what the provider/CLI emit into `events.jsonl`; they may be
  `null` for some endpoints (see [results-format](results-format.md)).
- Local models are slower and may need a higher per-trial timeout and more `trials` to compare
  fairly against hosted frontier models.
