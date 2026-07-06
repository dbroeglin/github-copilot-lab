"""Self-contained interactive HTML dashboards for Pier run summaries.

Renders a Pier ``summary`` (the dict produced by
:func:`copilot_experiments.pier_results.build_pier_summary`) into a single,
shareable ``summary.html`` file. The look and feel is inspired by the DeepSWE
leaderboard and the GitHub Copilot agentic-harness benchmarking report: a clean
header, KPI cards, a ranked leaderboard, and a small set of interactive
[Plotly](https://plotly.com/python/) charts.

Plotly is a required runtime dependency. The import is still guarded, so if it
is somehow unavailable (e.g. a broken or partial install) the public helpers
raise :class:`ChartError` with a clear message instead of a bare ``ImportError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._util import write_text

try:  # required dependency, guarded defensively against a broken install
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.offline import get_plotlyjs, get_plotlyjs_version

    _PLOTLY_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via monkeypatch
    go = None  # type: ignore[assignment]
    pio = None  # type: ignore[assignment]
    get_plotlyjs = None  # type: ignore[assignment]
    get_plotlyjs_version = None  # type: ignore[assignment]
    _PLOTLY_IMPORT_ERROR = exc


class ChartError(RuntimeError):
    """Raised when a dashboard cannot be produced (e.g. Plotly not installed)."""


_INSTALL_HINT = (
    "Plotly is required to render HTML dashboards but could not be imported. "
    "Reinstall copilot-experiments to restore it (for example `uv sync` or "
    "`pip install --force-reinstall copilot-experiments`)."
)

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

_FONT_FAMILY = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, '
    'sans-serif, "Apple Color Emoji", "Segoe UI Emoji"'
)
_INK = "#1f2328"
_MUTED = "#656d76"
_GRID = "#eaeef2"
_ZERO = "#d0d7de"

# Stable, readable qualitative palette (assigned by leaderboard rank).
_PALETTE = [
    "#0969da",  # blue
    "#1a7f37",  # green
    "#8250df",  # purple
    "#bc4c00",  # orange
    "#bf3989",  # pink
    "#1b7c83",  # teal
    "#9a6700",  # amber
    "#cf222e",  # red
    "#57606a",  # gray
    "#6639ba",  # indigo
]

_PLOT_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_dashboard_html(
    summary: dict[str, Any], *, title: str | None = None, cdn: bool = False
) -> str:
    """Render ``summary`` into a complete, self-contained HTML document.

    Parameters
    ----------
    summary:
        A Pier run summary (see :func:`pier_results.build_pier_summary`).
    title:
        Optional page/document title. Defaults to the job name.
    cdn:
        When ``True`` load plotly.js from the public CDN instead of embedding
        the ~4.5 MB bundle, producing a tiny file that needs network access to
        render.
    """

    _ensure_plotly()
    agents = list(summary.get("agents") or [])
    ranked = _rank_agents(agents)
    colors = {agent["name"]: _PALETTE[i % len(_PALETTE)] for i, agent in enumerate(ranked)}
    n_tasks = int(summary.get("n_tasks") or 0)

    charts_html: list[str] = []

    resolution = _chart_task_resolution(ranked, colors, n_tasks)
    if resolution is not None:
        charts_html.append(
            _chart_card(
                "Task resolution",
                "Success rate per agent"
                + (" across tasks" if n_tasks > 1 else "")
                + ". Higher is better.",
                resolution,
            )
        )

    scatter = _chart_resolution_vs_cost(ranked, colors)
    if scatter is not None:
        charts_html.append(
            _chart_card(
                "Resolution vs. cost",
                "Success rate against average cost per task, with \u00b11\u03c3 cost "
                "spread across trials. Up and to the left is better.",
                scatter,
            )
        )

    cost = _chart_cost_efficiency(ranked, colors)
    if cost is not None:
        charts_html.append(
            _chart_card(
                "Cost efficiency",
                "Average cost per task per agent, with \u00b11\u03c3 spread across "
                "trials. Lower is better.",
                cost,
            )
        )

    if n_tasks > 1:
        heatmap = _chart_task_heatmap(ranked)
        if heatmap is not None:
            charts_html.append(
                _chart_card(
                    "Per-task success",
                    "Success rate for every agent \u00d7 task cell.",
                    heatmap,
                )
            )

    body = "\n".join(
        [
            _header_html(summary),
            _kpi_cards_html(summary),
            _leaderboard_html(ranked, colors),
            '<div class="charts">' + "\n".join(charts_html) + "</div>"
            if charts_html
            else _empty_charts_html(),
            _footer_html(),
        ]
    )

    head_js = _plotly_head(cdn)
    doc_title = title or f"{summary.get('job') or 'Experiment'} \u2014 results"
    return _PAGE_SHELL.format(title=_esc(doc_title), css=_CSS, head_js=head_js, body=body)


def write_dashboard(
    job_dir: Path,
    *,
    summary: dict[str, Any] | None = None,
    out_path: Path | None = None,
    title: str | None = None,
    cdn: bool = False,
) -> Path:
    """Build and write a ``summary.html`` dashboard for a Pier job directory.

    Pass ``summary`` to reuse an already-built summary; otherwise it is rebuilt
    from ``job_dir``. Returns the path written. Raises :class:`ChartError` when
    Plotly is missing.
    """

    _ensure_plotly()
    job_dir = Path(job_dir)
    if summary is None:
        from .pier_results import build_pier_summary

        summary = build_pier_summary(job_dir)
    html = build_dashboard_html(summary, title=title, cdn=cdn)
    out = Path(out_path) if out_path is not None else job_dir / "summary.html"
    write_text(out, html)
    return out


def plotly_available() -> bool:
    """Return ``True`` when the Plotly dependency can be imported."""

    return _PLOTLY_IMPORT_ERROR is None


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _chart_task_resolution(
    agents: list[dict[str, Any]],
    colors: dict[str, str],
    n_tasks: int,
) -> str | None:
    if not agents:
        return None
    fig = go.Figure()
    if n_tasks > 1:
        # One colored series per agent; grouped by task along the x-axis.
        task_order = _task_order(agents)
        for agent in agents:
            by_task = {task["task"]: task for task in agent.get("tasks") or []}
            ys = [_pct_value(by_task.get(slug, {}).get("success_rate")) for slug in task_order]
            fig.add_bar(
                name=_esc(agent["name"]),
                x=[label for _, label in task_order.items()],
                y=ys,
                marker_color=colors[agent["name"]],
                hovertemplate="%{fullData.name}<br>%{x}: %{y:.0f}%<extra></extra>",
            )
        fig.update_layout(barmode="group", legend_title_text="Agent")
    else:
        names = [agent["name"] for agent in agents]
        fig.add_bar(
            x=names,
            y=[_pct_value(agent.get("success_rate")) for agent in agents],
            marker_color=[colors[name] for name in names],
            hovertemplate="%{x}<br>%{y:.0f}%<extra></extra>",
            showlegend=False,
        )
    fig.update_yaxes(title_text="Success rate", ticksuffix="%", range=[0, 100])
    _apply_theme(fig)
    return _fragment(fig, "chart-resolution", height=430)


def _chart_resolution_vs_cost(agents: list[dict[str, Any]], colors: dict[str, str]) -> str | None:
    metric, points = _cost_points(agents)
    if not points:
        return None
    fig = go.Figure()
    for agent in points:
        label = _esc(agent["name"])
        cost = agent["_cost"]
        std = agent.get("_cost_std")
        color = colors[agent["name"]]
        # Agent names are identified through the legend rather than printed on
        # each point: Plotly has no collision avoidance for scatter text, so long
        # names over closely spaced points would overlap. The legend wraps cleanly.
        fig.add_trace(
            go.Scatter(
                x=[cost],
                y=[_pct_value(agent.get("success_rate"))],
                mode="markers",
                name=label,
                marker={
                    "size": 15,
                    "color": color,
                    "line": {"width": 1.5, "color": "#ffffff"},
                    "opacity": 0.95,
                },
                error_x=(
                    {
                        "type": "data",
                        "array": [std],
                        "thickness": 1.4,
                        "width": 6,
                        "color": color,
                    }
                    if std
                    else None
                ),
                hovertemplate=(
                    f"{label}<br>Success: %{{y:.0f}}%<br>{metric['label']}: "
                    f"%{{x:{metric['fmt']}}}{metric['suffix']}<extra></extra>"
                ),
                showlegend=True,
            )
        )
    fig.update_xaxes(title_text=metric["axis"], range=list(_cost_axis_bounds(points)))
    fig.update_yaxes(title_text="Success rate", ticksuffix="%", range=[-5, 106])
    _apply_theme(fig)
    return _fragment(fig, "chart-scatter", height=460)


def _chart_cost_efficiency(agents: list[dict[str, Any]], colors: dict[str, str]) -> str | None:
    metric, points = _cost_points(agents)
    if not points:
        return None
    names = [agent["name"] for agent in points]
    fig = go.Figure(
        go.Bar(
            x=names,
            y=[agent["_cost"] for agent in points],
            marker_color=[colors[name] for name in names],
            error_y={
                "type": "data",
                "array": [agent.get("_cost_std") or 0 for agent in points],
                "thickness": 1.4,
                "width": 6,
                "color": _MUTED,
            },
            hovertemplate=f"%{{x}}<br>%{{y:{metric['fmt']}}}{metric['suffix']}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_yaxes(title_text=metric["axis"], rangemode="tozero")
    _apply_theme(fig)
    return _fragment(fig, "chart-cost", height=430)


def _chart_task_heatmap(agents: list[dict[str, Any]]) -> str | None:
    task_order = _task_order(agents)
    if not task_order:
        return None
    x_labels = list(task_order.values())
    y_labels = [agent["name"] for agent in agents]
    z: list[list[float | None]] = []
    text: list[list[str]] = []
    for agent in agents:
        by_task = {task["task"]: task for task in agent.get("tasks") or []}
        row_z: list[float | None] = []
        row_t: list[str] = []
        for slug in task_order:
            rate = by_task.get(slug, {}).get("success_rate")
            row_z.append(None if rate is None else round(rate * 100, 1))
            row_t.append("\u2014" if rate is None else f"{rate * 100:.0f}%")
        z.append(row_z)
        text.append(row_t)
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=x_labels,
            y=y_labels,
            text=text,
            texttemplate="%{text}",
            textfont={"size": 12},
            zmin=0,
            zmax=100,
            colorscale=[[0, "#fbeaec"], [0.5, "#ffe8b3"], [1.0, "#c3e6cd"]],
            colorbar={"title": {"text": "%"}, "ticksuffix": "%", "thickness": 12},
            hovertemplate="%{y}<br>%{x}: %{z:.0f}%<extra></extra>",
            xgap=3,
            ygap=3,
        )
    )
    fig.update_yaxes(autorange="reversed")
    _apply_theme(fig)
    height = max(320, 120 + 46 * len(y_labels))
    return _fragment(fig, "chart-heatmap", height=height)


# ---------------------------------------------------------------------------
# HTML pieces
# ---------------------------------------------------------------------------


def _header_html(summary: dict[str, Any]) -> str:
    chips = []
    run_id = summary.get("run_id")
    if run_id:
        chips.append(f'<span class="chip mono">{_esc(str(run_id))}</span>')
    status = summary.get("status")
    if status:
        chips.append(f'<span class="chip status-{_esc(str(status))}">{_esc(str(status))}</span>')
    started = (summary.get("started_at") or "")[:19].replace("T", " ")
    if started:
        chips.append(f'<span class="chip">started {_esc(started)}</span>')
    finished = (summary.get("finished_at") or "")[:19].replace("T", " ")
    if finished:
        chips.append(f'<span class="chip">finished {_esc(finished)}</span>')
    selector = summary.get("pier_job_id")
    subtitle = f'<div class="subtitle mono">{_esc(str(selector))}</div>' if selector else ""
    return (
        '<header class="header">'
        f'<div class="eyebrow">Experiment results</div>'
        f"<h1>{_esc(str(summary.get('job') or 'Experiment'))}</h1>"
        f"{subtitle}"
        f'<div class="chips">{"".join(chips)}</div>'
        "</header>"
    )


def _kpi_cards_html(summary: dict[str, Any]) -> str:
    cards = [
        ("Overall success", _pct(summary.get("overall_success_rate")), "resolved trials"),
        ("Total cost", _aiu(summary.get("total_aiu")), "AIU"),
        ("Agents", _int(summary.get("n_agents")), "compared"),
        ("Tasks", _int(summary.get("n_tasks")), "in suite"),
        ("Trials", _int(summary.get("n_trials")), "executed"),
    ]
    failed = int(summary.get("n_failed_trials") or 0)
    if failed:
        cards.append(("Harness failures", str(failed), "did not run cleanly"))
    items = "".join(
        f'<div class="kpi{" kpi-warn" if label == "Harness failures" else ""}">'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-label">{_esc(label)}</div>'
        f'<div class="kpi-note">{_esc(note)}</div>'
        "</div>"
        for label, value, note in cards
    )
    return f'<section class="kpis">{items}</section>'


def _leaderboard_html(agents: list[dict[str, Any]], colors: dict[str, str]) -> str:
    if not agents:
        return ""
    rows = []
    for rank, agent in enumerate(agents, start=1):
        name = agent["name"]
        rows.append(
            "<tr>"
            f'<td class="rank">{rank}</td>'
            f'<td><span class="dot" style="background:{colors[name]}"></span>'
            f'<span class="agent-name">{_esc(name)}</span></td>'
            f'<td class="mono muted">{_esc(str(agent.get("model") or "\u2014"))}</td>'
            f'<td class="muted">{_esc(str(agent.get("reasoning_effort") or "\u2014"))}</td>'
            f'<td class="num strong">{_pct(agent.get("success_rate"))}</td>'
            f'<td class="num">{_pct(agent.get("resolved_at_k_rate"))}</td>'
            f'<td class="num">{_aiu(agent.get("avg_aiu"))}</td>'
            f'<td class="num">{_aiu(agent.get("aiu_per_solve"))}</td>'
            f'<td class="num muted">{_int(agent.get("avg_total_tokens"))}</td>'
            f'<td class="num muted">{_int(agent.get("n_trials"))}</td>'
            "</tr>"
        )
    return (
        '<section class="panel">'
        '<div class="panel-head"><h2>Leaderboard</h2>'
        '<div class="panel-sub">Ranked by success rate, then cost.</div></div>'
        '<div class="table-wrap"><table class="board">'
        "<thead><tr>"
        '<th class="rank">#</th><th>Agent</th><th>Model</th><th>Effort</th>'
        '<th class="num">Success</th><th class="num">Resolved@k</th>'
        '<th class="num">Avg AIU</th><th class="num">AIU / solve</th>'
        '<th class="num">Avg tokens</th><th class="num">Trials</th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div></section>"
    )


def _chart_card(title: str, subtitle: str, fragment: str) -> str:
    return (
        '<section class="panel chart-panel">'
        f'<div class="panel-head"><h2>{_esc(title)}</h2>'
        f'<div class="panel-sub">{subtitle}</div></div>'
        f'<div class="chart-body">{fragment}</div>'
        "</section>"
    )


def _empty_charts_html() -> str:
    return (
        '<section class="panel"><div class="panel-head"><h2>Charts</h2>'
        '<div class="panel-sub">No agent metrics were available to plot.</div>'
        "</div></section>"
    )


def _footer_html() -> str:
    return (
        '<footer class="footer">Generated by '
        '<span class="mono">copilot-experiments</span>. Charts are interactive \u2014 '
        "hover for details, drag to zoom, double-click to reset.</footer>"
    )


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _rank_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(agent: dict[str, Any]) -> tuple[Any, ...]:
        success = agent.get("success_rate")
        cost = agent.get("avg_aiu")
        if cost is None:
            cost = agent.get("avg_total_tokens")
        return (
            0 if success is not None else 1,
            -(success or 0.0),
            0 if cost is not None else 1,
            cost if cost is not None else 0.0,
            str(agent.get("name") or ""),
        )

    return sorted(agents, key=key)


def _cost_points(agents: list[dict[str, Any]]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Attach a cost value/std to each agent, preferring AIU then tokens."""

    use_aiu = any(agent.get("avg_aiu") is not None for agent in agents)
    metric = (
        {"label": "Avg AIU", "axis": "Average cost per task (AIU)", "fmt": ".3f", "suffix": ""}
        if use_aiu
        else {"label": "Avg tokens", "axis": "Average tokens per task", "fmt": ",.0f", "suffix": ""}
    )
    points = []
    for agent in agents:
        cost = agent.get("avg_aiu") if use_aiu else agent.get("avg_total_tokens")
        if cost is None:
            continue
        std = agent.get("std_aiu") if use_aiu else agent.get("std_total_tokens")
        points.append({**agent, "_cost": cost, "_cost_std": std})
    return metric, points


def _cost_axis_bounds(points: list[dict[str, Any]]) -> tuple[float, float]:
    """Padded x-range for the cost scatter so markers and error bars clear the edges."""

    lo = min(p["_cost"] - (p.get("_cost_std") or 0) for p in points)
    hi = max(p["_cost"] + (p.get("_cost_std") or 0) for p in points)
    span = hi - lo
    pad = span * 0.1 if span > 0 else (abs(hi) or 1.0) * 0.4
    low = lo - pad
    if lo >= 0:  # keep a cost axis from dipping below zero
        low = max(0.0, low)
    return low, hi + pad


def _task_order(agents: list[dict[str, Any]]) -> dict[str, str]:
    """Ordered mapping of task slug -> display label across all agents."""

    order: dict[str, str] = {}
    for agent in agents:
        for task in agent.get("tasks") or []:
            slug = task.get("task")
            if slug and slug not in order:
                order[slug] = str(task.get("name") or slug)
    return order


def _pct_value(rate: float | None) -> float | None:
    return None if rate is None else round(rate * 100, 1)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _ensure_plotly() -> None:
    if _PLOTLY_IMPORT_ERROR is not None:
        raise ChartError(_INSTALL_HINT) from _PLOTLY_IMPORT_ERROR


def _apply_theme(fig: Any) -> None:
    fig.update_layout(
        template="plotly_white",
        font={"family": _FONT_FAMILY, "size": 13, "color": _INK},
        margin={"l": 64, "r": 24, "t": 16, "b": 56},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=_PALETTE,
        hoverlabel={"font": {"family": _FONT_FAMILY, "size": 12}},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 12},
        },
        bargap=0.28,
        bargroupgap=0.12,
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        linecolor=_ZERO,
        ticks="outside",
        tickcolor=_ZERO,
        tickfont={"color": _MUTED},
        title_font={"size": 12, "color": _MUTED},
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=_GRID,
        zeroline=True,
        zerolinecolor=_ZERO,
        linecolor="rgba(0,0,0,0)",
        tickfont={"color": _MUTED},
        title_font={"size": 12, "color": _MUTED},
        automargin=True,
    )


def _plotly_head(cdn: bool) -> str:
    """Return the ``<head>`` snippet that makes plotly.js available."""

    if cdn:
        src = f"https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js"
        return f'<script src="{src}" charset="utf-8"></script>'
    return f"<script>{get_plotlyjs()}</script>"


def _fragment(fig: Any, div_id: str, *, height: int) -> str:
    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        div_id=div_id,
        default_width="100%",
        default_height=f"{height}px",
        config=_PLOT_CONFIG,
    )


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pct(value: float | None) -> str:
    return "\u2014" if value is None else f"{value * 100:.0f}%"


def _aiu(value: float | None) -> str:
    if value is None:
        return "\u2014"
    value = float(value)
    return f"{value:.3f}" if value < 1 else f"{value:,.2f}"


def _int(value: float | None) -> str:
    if value is None:
        return "\u2014"
    return f"{float(value):,.0f}"


# ---------------------------------------------------------------------------
# Page shell
# ---------------------------------------------------------------------------

_CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#f6f8fa;color:#1f2328;line-height:1.5;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.mono{font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace}
.muted{color:#656d76}
.wrap{max-width:1120px;margin:0 auto;padding:36px 24px 72px}
.header{margin-bottom:24px}
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#8250df}
h1{margin:6px 0 4px;font-size:30px;line-height:1.2;letter-spacing:-.01em}
.subtitle{color:#656d76;font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;
  background:#fff;border:1px solid #d0d7de;font-size:12px;color:#424a53}
.chip.status-completed{background:#dafbe1;border-color:#aceebb;color:#1a7f37}
.chip.status-failed,.chip.status-error{background:#ffebe9;border-color:#ffcecb;color:#cf222e}
.chip.status-running,.chip.status-partial{background:#fff8c5;border-color:#eac54f;color:#7d4e00}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:22px}
.kpi{background:#fff;border:1px solid #d0d7de;border-radius:12px;padding:16px 18px;
  box-shadow:0 1px 2px rgba(31,35,40,.06)}
.kpi-value{font-size:26px;font-weight:650;letter-spacing:-.01em;line-height:1.1}
.kpi-label{margin-top:4px;font-size:13px;font-weight:600;color:#424a53}
.kpi-note{font-size:12px;color:#8b949e}
.kpi-warn{border-color:#eac54f;background:#fffbdd}
.kpi-warn .kpi-value{color:#7d4e00}
.panel{background:#fff;border:1px solid #d0d7de;border-radius:14px;margin-bottom:22px;
  box-shadow:0 1px 2px rgba(31,35,40,.06);overflow:hidden}
.panel-head{padding:18px 20px 0}
.panel-head h2{margin:0;font-size:16px;letter-spacing:-.005em}
.panel-sub{margin-top:3px;color:#656d76;font-size:13px}
.chart-body{padding:8px 12px 14px}
.table-wrap{overflow-x:auto;padding:12px 8px 8px}
table.board{width:100%;border-collapse:collapse;font-size:13px}
table.board th,table.board td{padding:10px 12px;text-align:left;white-space:nowrap}
table.board thead th{font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:#656d76;border-bottom:1px solid #d0d7de}
table.board tbody tr{border-bottom:1px solid #eaeef2}
table.board tbody tr:last-child{border-bottom:0}
table.board tbody tr:hover{background:#f6f8fa}
table.board td.num,table.board th.num{text-align:right;font-variant-numeric:tabular-nums}
table.board td.rank,table.board th.rank{text-align:center;color:#8b949e;width:34px}
table.board td.strong{font-weight:650}
.agent-name{font-weight:600}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;vertical-align:middle}
.charts{display:block}
.footer{color:#8b949e;font-size:12px;text-align:center;margin-top:8px}
@media (max-width:640px){h1{font-size:24px}.wrap{padding:24px 16px 56px}}
"""

_PAGE_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
{head_js}
</head>
<body>
<main class="wrap">
{body}
</main>
</body>
</html>
"""
