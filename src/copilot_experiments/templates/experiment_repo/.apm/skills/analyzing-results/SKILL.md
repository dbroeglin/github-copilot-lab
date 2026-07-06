---
name: analyzing-results
description: >-
  Use when analyzing GitHub Copilot experiment results: comparing agents,
  measuring success rates and cost-effectiveness, and inspecting session logs to
  identify failures. Covers Pier jobs and derived summaries.
---

# Analyzing results

## Filesystem layout
```
jobs/<job-name>/<run-id>/
  config.json         # resolved Pier job config
  result.json         # Pier job result
  copilot-experiments-run.json
  summary.json        # derived copilot-experiments summary
  summary.md          # human-readable report
  summary.html        # interactive Plotly dashboard (chart / run)
  <trial-name>/
    result.json       # Pier trial result
    agent/
      trajectory.json
      copilot-cli.jsonl
      copilot-session/**/events.jsonl
    verifier/
    artifacts/
```
Native Copilot session events remain the source of truth for Copilot-specific turns, tools,
tokens, and AIU economics.

## CLI
```bash
copilot-experiments list                 # runs + success rates
copilot-experiments show --last          # per-agent comparison table
copilot-experiments chart --last --open  # interactive summary.html dashboard
copilot-experiments inspect <job-name>   # latest run for that Pier job
copilot-experiments inspect <job-name>/<run-id>  # exact run selector from list
copilot-experiments analyze <job-name>/<run-id> --agent <agent> --trial <n>
```

## Diagnosing failures
- Open the trial's `verifier/` directory for test output.
- Read collected `artifacts/` to see what the task exported.
- Scan `agent/copilot-session/**/events.jsonl` for `tool.execution_complete` failures and
  `session.warning` events.
