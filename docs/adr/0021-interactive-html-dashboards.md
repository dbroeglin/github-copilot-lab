# 0021. Interactive self-contained HTML result dashboards

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** copilot-experiments maintainers

## Context

The tool could render results only as Rich terminal tables (`show`, `analyze`, `inspect`) and a
plain `summary.md`. Users asked for high-quality, clean visual outputs of experiment results,
citing the [DeepSWE leaderboard](https://deepswe.datacurve.ai/) and the
[GitHub Copilot agentic-harness benchmarking report](https://github.blog/ai-and-ml/github-copilot/evaluating-performance-and-efficiency-of-the-github-copilot-agentic-harness-across-models-and-tasks/)
as the target look and feel. Those references communicate three things well: task resolution per
model, token/cost efficiency, and a resolution-vs-cost trade-off with run-to-run variance.

Constraints from our existing ADRs shaped the options:

- The filesystem is the source of truth ([0002](0002-filesystem-is-source-of-truth.md)); a
  dashboard should be a derived artifact next to `summary.json`, not new authoritative state.
- Analysis data is separate from rendering ([0006](0006-separate-analysis-data-from-rendering.md));
  charts must consume the existing summary, not re-derive metrics.
- We deliberately favored a CLI over a web app for analysis
  ([0007](0007-cli-rich-analysis-before-web-app.md)); we did not want to (re)introduce a server.
- Tests stay offline; any dependency must be exercisable without network or Docker.

Candidate approaches: (a) static PNG/SVG via Matplotlib, (b) a served web app, (c) self-contained
interactive HTML. Static images are easy to embed but not explorable and render poorly across
screens. A served app reverses ADR 0007. Self-contained HTML keeps the "just files" model while
giving crisp, interactive, shareable output.

## Decision

We will render each Pier run into a single self-contained `summary.html` dashboard built with
[Plotly](https://plotly.com/python/), added as a new `charts.py` module.

- Plotly is a **core** runtime dependency, so the `chart` command and the automatic `run`
  dashboard work with a normal install (`uvx`, `uv tool install`, `pip install`) and no extra to
  enable. The import is still guarded defensively: if Plotly is somehow unavailable, `run` skips
  the dashboard and `chart` exits with a clear `ChartError` instead of a bare `ImportError`.
- `charts.build_dashboard_html(summary)` consumes the existing `summary.json` shape and returns a
  complete HTML string; `charts.write_dashboard(job_dir)` writes `summary.html` beside the other
  derived summaries. No new source-of-truth state is introduced.
- A new `chart` CLI command produces the dashboard on demand (`--last`, `--out`, `--cdn`,
  `--open`), and `run` emits it automatically after each job.
- By default plotly.js is embedded for zero-dependency offline viewing; `--cdn` produces a small
  file that loads plotly.js from the CDN.
- To feed the charts we populated the previously stubbed variance/coverage aggregates in
  `pier_results.py` (`std_*`/`cv_*` for AIU and tokens, `mean_resolved_rate`,
  `resolved_at_k_rate`, per-task `resolved_rate`).

## Consequences

- Runs now yield a crisp, interactive, shareable dashboard with no server, preserving the
  filesystem-first, CLI-first model. It sits alongside `summary.json` / `summary.md` and is
  regenerable at any time.
- `summary.json` gained documented spread and suite-coverage fields, which also benefit `show`
  and any future consumer; `report.py` key names were corrected to match.
- We accept a large runtime dependency (Plotly bundles plotly.js). The embedded offline build is
  ~4.5 MB per file; `--cdn` is available when size matters. Offline tests stay fast by using the
  `cdn=True` path or monkeypatching the import to assert the defensive `ChartError`.
- Future chart tweaks live entirely in `charts.py` and read only the summary dict, so rendering
  stays decoupled from metric derivation per ADR 0006.
