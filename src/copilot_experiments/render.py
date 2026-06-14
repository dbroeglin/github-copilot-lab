"""Rich rendering of a :class:`~copilot_experiments.models.SessionAnalysis`.

Kept separate from :mod:`analysis` (which produces plain data) so the same analysis can be
serialized, rendered in the terminal here, or served by a future web explorer.
"""

from __future__ import annotations

import datetime as _dt

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import SessionAnalysis


def _clock(value: str | None) -> str:
    if not value:
        return "-"
    try:
        ts = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:19]
    return ts.strftime("%H:%M:%S")


def _dur(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s"


def _header_panel(a: SessionAnalysis, title: str | None) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()

    def row(label: str, value: object) -> None:
        grid.add_row(label, "-" if value in (None, "", []) else str(value))

    row("session", a.session_id)
    row("model", ", ".join(a.models) if a.models else None)
    if a.reasoning_effort:
        row("effort", a.reasoning_effort)
    if a.repository or a.branch:
        row("repo", f"{a.repository or '-'} @ {a.branch or '-'}")
    row("copilot", a.copilot_version)
    row("started", a.started_at)
    row("duration", _dur(a.duration_s))
    heading = title or "Session analysis"
    return Panel(grid, title=f"[bold]{heading}[/bold]", border_style="cyan", expand=False,
                 padding=(0, 1))


def _totals_table(a: SessionAnalysis) -> Table:
    table = Table(title="Totals", title_justify="left", show_edge=False, expand=False)
    table.add_column("metric", style="dim")
    table.add_column("value", justify="right")
    tokens = "-" if a.total_tokens is None else f"{a.total_tokens:,}"
    if a.output_tokens is not None and a.input_tokens is None:
        tokens = f"{a.output_tokens:,} out"
    rows = [
        ("turns", a.n_turns),
        ("user messages", a.n_user_messages),
        ("assistant messages", a.n_assistant_messages),
        ("tool calls", a.n_tool_calls),
        ("tool failures", a.n_tool_failures),
        ("warnings", a.n_warnings),
        ("hooks", a.n_hooks),
        ("tokens", tokens),
        ("events", a.n_events),
    ]
    for label, value in rows:
        if label == "tool failures" and a.n_tool_failures:
            table.add_row(label, f"[red]{value}[/red]")
        else:
            table.add_row(label, str(value))
    return table


def _tools_table(a: SessionAnalysis) -> Table:
    table = Table(title="Tool usage", title_justify="left", show_edge=False, expand=False)
    table.add_column("tool")
    table.add_column("calls", justify="right")
    table.add_column("fails", justify="right")
    if not a.tools:
        table.add_row("[dim]none[/dim]", "-", "-")
    for tool in a.tools:
        fails = f"[red]{tool.failures}[/red]" if tool.failures else "0"
        table.add_row(tool.name, str(tool.calls), fails)
    return table


def _timeline_table(a: SessionAnalysis, max_turns: int = 0) -> Table:
    table = Table(title="Timeline (per turn)", title_justify="left")
    table.add_column("#", justify="right")
    table.add_column("time")
    table.add_column("dur", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("tools")
    table.add_column("assistant said")

    turns = a.turns
    hidden = 0
    if max_turns and len(turns) > max_turns:
        hidden = len(turns) - max_turns
        turns = turns[:max_turns]

    for turn in turns:
        tools = ", ".join(turn.tools) if turn.tools else "[dim]-[/dim]"
        tokens = "-" if turn.output_tokens is None else str(turn.output_tokens)
        table.add_row(
            str(turn.turn_no),
            _clock(turn.started_at),
            _dur(turn.duration_s),
            tokens,
            tools,
            turn.text_preview or "[dim](no message)[/dim]",
        )
    if hidden:
        table.add_row("", "", "", "", "", f"[dim]... {hidden} more turn(s)[/dim]")
    return table


def render_session_analysis(
    analysis: SessionAnalysis,
    console: Console,
    *,
    title: str | None = None,
    max_turns: int = 0,
) -> None:
    """Render a full session overview to ``console``."""
    console.print(_header_panel(analysis, title))
    console.print()
    console.print(Columns([_totals_table(analysis), _tools_table(analysis)], padding=(0, 4)))
    console.print()
    console.print(_timeline_table(analysis, max_turns=max_turns))
    if analysis.warnings:
        body = "\n".join(f"\u2022 {w}" for w in analysis.warnings)
        console.print(Panel(body, title="[bold]Warnings[/bold]", border_style="yellow",
                            expand=False))
