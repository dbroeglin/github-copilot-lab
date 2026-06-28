---
name: analyzing-results
description: >-
  Use when analyzing GitHub Copilot experiment results: comparing variants,
  measuring success rates and cost-effectiveness, and inspecting session logs to
  identify failures. Covers Pier jobs and the derived SQLite index.
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
copilot-experiments show --last          # per-variant comparison table
copilot-experiments inspect <job-name>   # latest run for that Pier job
copilot-experiments inspect <job-name>/<run-id>  # exact run selector from list
copilot-experiments analyze --last       # render native Copilot events
copilot-experiments reindex              # rebuild results/index.db
```

## SQLite (results/index.db)
Tables include legacy `experiments`, `runs`, `variants`, `tasks`, `trials` plus Pier
`pier_jobs` and `pier_trials`. Useful queries:
```sql
SELECT model, AVG(success) AS success_rate, COUNT(*) AS n
FROM pier_trials WHERE success IS NOT NULL GROUP BY model ORDER BY success_rate DESC;
```

## Diagnosing failures
- Open the trial's `verifier/` directory for test output.
- Read collected `artifacts/` to see what the task exported.
- Scan `agent/copilot-session/**/events.jsonl` for `tool.execution_complete` failures and
  `session.warning` events.
