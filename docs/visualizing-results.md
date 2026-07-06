# Visualizing results

`copilot-experiments` renders each Pier run into a single, self-contained
`summary.html` dashboard inspired by the [DeepSWE leaderboard](https://deepswe.datacurve.ai/)
and the [GitHub Copilot agentic-harness benchmarking report](https://github.blog/ai-and-ml/github-copilot/evaluating-performance-and-efficiency-of-the-github-copilot-agentic-harness-across-models-and-tasks/).
The dashboard is built with [Plotly](https://plotly.com/python/): the charts are interactive
(hover, zoom, legend toggles) yet the file opens straight from disk with no server.

## Producing a dashboard

```bash
# Chart the most recent run and open it in a browser.
uv run copilot-experiments chart --last --open

# Chart a specific run by selector (from `list`).
uv run copilot-experiments chart <job-name>
uv run copilot-experiments chart <job-name>/<run-id>

# Write it somewhere else, or use the CDN build (see below).
uv run copilot-experiments chart --last --out report.html
uv run copilot-experiments chart --last --cdn
```

`run` also emits `summary.html` automatically after each Pier job, so a freshly finished
experiment already has a shareable dashboard next to its `summary.json`.

Plotly ships as a core dependency, so `chart` and the automatic `run` dashboard work out of the
box with a normal install (`uv sync`, `uvx copilot-experiments`, `uv tool install`, or `pip
install copilot-experiments`) -- there is no extra to enable.

## What the dashboard shows

The page is derived entirely from `summary.json` (see
[Results format](results-format.md)), so it stays in sync with `show` and `inspect`:

- **Header + KPI cards** - job identity, status, and headline numbers (agents, tasks, trials,
  overall success rate, total AIU).
- **Leaderboard** - agents ranked by success rate, then by cost, with per-agent color that is
  reused across every chart.
- **Task resolution** - success rate per agent; grouped by task when the run has more than one
  task. Higher is better.
- **Resolution vs. cost** - success rate (y) against average cost per task (x) with ±1σ cost
  error bars. "Up and to the left" (high success, low cost) is best.
- **Cost efficiency** - average cost per task per agent with ±1σ spread. Lower is better.
- **Per-task success** - an agent × task heatmap, shown only when the run has more than one task.

Cost prefers AIU (`avg_aiu` / `std_aiu`) and falls back to token counts
(`avg_total_tokens` / `std_total_tokens`) when no AIU is available, matching the aggregate fields
documented in [Results format](results-format.md#variance-and-suite-coverage-aggregates).

## Offline vs. CDN builds

By default the dashboard **embeds** the full plotly.js bundle (~4.5 MB) so it renders with zero
network access - ideal for archiving a run or emailing it to a colleague. Pass `--cdn` to instead
reference plotly.js from `https://cdn.plot.ly/`, producing a small file (tens of KB) that needs an
internet connection to render.

| Build | Flag | File size | Needs network to view |
| --- | --- | --- | --- |
| Offline (default) | *(none)* | ~4.5 MB | No |
| CDN | `--cdn` | ~40 KB | Yes |

## Programmatic use

The dashboard builder is a small public API:

```python
from copilot_experiments.charts import build_dashboard_html, write_dashboard, plotly_available
from copilot_experiments.pier_results import build_pier_summary

summary = build_pier_summary(job_dir)
html = build_dashboard_html(summary, cdn=True)     # returns a complete HTML string
write_dashboard(job_dir, summary=summary)          # writes <job_dir>/summary.html
```

`build_dashboard_html` and `write_dashboard` raise `charts.ChartError` (with an install hint) when
Plotly is unavailable; guard optional call sites with `plotly_available()`.
