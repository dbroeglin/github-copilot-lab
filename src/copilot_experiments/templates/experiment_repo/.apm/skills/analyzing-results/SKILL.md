---
name: analyzing-results
description: >-
  Use when analyzing GitHub Copilot experiment results: comparing variants,
  measuring success rates and cost-effectiveness, and inspecting session logs to
  identify failures. Covers the results/ filesystem layout and the SQLite index.
---

# Analyzing results

## Filesystem layout
```
results/<experiment-slug>/<run-id>/
  run.json            # full run manifest (variants + trials)
  summary.json        # aggregated per-variant metrics
  summary.md          # human-readable report
  variants/<variant>/trials/<NNN>/
    meta.json         # session id, exit code, duration, success
    metrics.json      # parsed metrics (turns, tool calls/failures, tokens)
    events.jsonl      # copied Copilot session events (the source of truth)
    workspace.diff    # what Copilot changed
    verify.json       # verification command result
```

## CLI
```bash
copilot-experiments list                 # runs + success rates
copilot-experiments show --last          # per-variant comparison table
copilot-experiments inspect <run-id>     # list variants
copilot-experiments inspect <run-id> --variant <slug>            # list trials
copilot-experiments inspect <run-id> --variant <slug> --trial 1  # events + metrics
copilot-experiments reindex              # rebuild results/index.db
```

## SQLite (results/index.db)
Tables: `experiments`, `runs`, `variants`, `trials`. Useful queries:
```sql
-- success rate by model across all runs
SELECT model, AVG(success) AS success_rate, COUNT(*) AS n
FROM trials WHERE success IS NOT NULL GROUP BY model ORDER BY success_rate DESC;

-- average tool failures by variant for one run
SELECT variant_slug, AVG(n_tool_failures) FROM trials
WHERE run_id = '<run-id>' GROUP BY variant_slug;
```

## Diagnosing failures
- Open `verify.json` for the failing command output.
- Read `workspace.diff` to see what (if anything) Copilot changed.
- Scan `events.jsonl` for `tool.execution_complete` with `success: false` and for
  `session.warning` events.
