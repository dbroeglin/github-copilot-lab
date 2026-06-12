# sandbox/

Scratch area for running experiments **locally, only to test the library and CLI**.

Anything under `sandbox/` is gitignored (except this README and `.gitkeep`), so it is
safe to generate throwaway experiment repos and runs here.

```bash
# scaffold a throwaway experiment repo and dry-run it (no Copilot credits used)
uv run copilot-experiments init sandbox/demo
cd sandbox/demo
uv run copilot-experiments run --dry-run
uv run copilot-experiments show --last
```
