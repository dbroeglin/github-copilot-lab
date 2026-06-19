# BYOK and local models

Copilot CLI supports Bring-Your-Own-Key custom providers through `COPILOT_PROVIDER_*`
environment variables. In the Pier architecture, those variables belong on the Pier agent config.

```yaml
agents:
  - name: copilot-cli
    model_name: qwen2.5-coder:7b
    env:
      COPILOT_PROVIDER_BASE_URL: http://host.docker.internal:11434/v1
      COPILOT_PROVIDER_TYPE: openai
      COPILOT_PROVIDER_MODEL_ID: qwen2.5-coder:7b
      COPILOT_PROVIDER_API_KEY: ${MY_LOCAL_PROVIDER_KEY}
    kwargs:
      reasoning_effort: low
```

The local `copilot-cli` agent runs the real Copilot CLI, so provider behavior is whatever the CLI
does with those environment variables. The harness does not implement a provider SDK path.

## Common variables

| Variable | Meaning |
| --- | --- |
| `COPILOT_PROVIDER_BASE_URL` | Provider endpoint. |
| `COPILOT_PROVIDER_TYPE` | `openai`, `azure`, or `anthropic`. |
| `COPILOT_PROVIDER_API_KEY` | Provider API key. |
| `COPILOT_PROVIDER_BEARER_TOKEN` | Bearer token alternative. |
| `COPILOT_PROVIDER_WIRE_API` | `completions` or `responses`. |
| `COPILOT_PROVIDER_MODEL_ID` | Provider model/deployment id. |
| `COPILOT_PROVIDER_WIRE_MODEL` | Wire model override. |
| `COPILOT_PROVIDER_AZURE_API_VERSION` | Azure OpenAI API version. |
| `COPILOT_PROVIDER_MAX_PROMPT_TOKENS` | Prompt limit. |
| `COPILOT_PROVIDER_MAX_OUTPUT_TOKENS` | Output limit. |

## Container networking notes

- For local services from Docker Desktop, use `host.docker.internal` rather than `localhost`.
- Ensure the Pier task environment allows network access and that the agent allowlist permits the
  provider endpoint if Pier network policy is active.
- Keep secrets in the host environment or a local untracked file; do not commit provider keys into
  job YAML.

## Metrics caveat

Copilot-native AIU/token metrics depend on what Copilot writes into `events.jsonl`. BYOK/local
providers may omit some economics fields. Success/reward still comes from the Pier verifier.
