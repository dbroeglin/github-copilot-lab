"""Rich rendering of a :class:`~copilot_experiments.models.SessionAnalysis`.

Kept separate from :mod:`analysis` (which produces plain data) so the same analysis can be
serialized, rendered in the terminal here, or served by a future web explorer.
"""

from __future__ import annotations

import datetime as _dt
import json

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


def _int(value: int | None) -> str:
    return "-" if value is None else f"{value:,}"


def _kchars(chars: int | None) -> str:
    if not chars:
        return "-"
    if chars < 1000:
        return str(chars)
    return f"{chars / 1000:.1f}k"


def _aiu(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 1:
        return f"{value:.3f}"
    return f"{value:,.2f}"


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
    table.add_column("dur", justify="right")
    table.add_column("ctx", justify="right")
    if not a.tools:
        table.add_row("[dim]none[/dim]", "-", "-", "-", "-")
    for tool in a.tools:
        fails = f"[red]{tool.failures}[/red]" if tool.failures else "0"
        dur = _dur(tool.total_duration_ms / 1000) if tool.total_duration_ms else "-"
        ctx = _kchars(tool.total_result_chars) if tool.total_result_chars else "-"
        table.add_row(tool.name, str(tool.calls), fails, dur, ctx)
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


def _economics_renderables(a: SessionAnalysis) -> list[Table]:
    """Cost, token-type split, context and productivity tables (omitted when no shutdown)."""
    e = a.economics
    if e.total_tokens is None and e.aiu is None:
        return []

    cost = Table(title="Cost (AIU)", title_justify="left", show_edge=False, expand=False)
    cost.add_column("token type", style="dim")
    cost.add_column("tokens", justify="right")
    cost.add_column("AIU", justify="right")
    cost.add_column("%", justify="right")
    total_aiu = e.aiu or 0.0
    by_type = e.aiu_by_type or {}
    type_tokens = {
        "input": e.input_tokens_noncached,
        "cache_read": e.cache_read_tokens,
        "cache_write": e.cache_write_tokens,
        "output": e.output_tokens,
    }
    for ttype in ("input", "cache_read", "cache_write", "output"):
        aiu = by_type.get(ttype)
        share = f"{aiu / total_aiu * 100:.0f}%" if aiu and total_aiu else "-"
        cost.add_row(ttype, _int(type_tokens.get(ttype)), _aiu(aiu), share)
    cost.add_row("[bold]total[/bold]", _int(e.total_tokens), f"[bold]{_aiu(e.aiu)}[/bold]", "")
    if e.reasoning_tokens:
        cost.add_row("[dim]reasoning[/dim]", _int(e.reasoning_tokens), "[dim](in output)[/dim]", "")

    facts = Table(title="Session economics", title_justify="left", show_edge=False, expand=False)
    facts.add_column("metric", style="dim")
    facts.add_column("value", justify="right")
    facts.add_row("requests", _int(e.n_requests))
    facts.add_row("api time", _dur(e.api_duration_ms / 1000) if e.api_duration_ms else "-")
    if e.n_requests and e.api_duration_ms:
        facts.add_row("ms / request", f"{e.api_duration_ms / e.n_requests:,.0f}")
    facts.add_row("context (cur)", _int(e.context_tokens))
    facts.add_row("context (peak)", _int(e.peak_context_tokens))
    facts.add_row("system / tools", f"{_int(e.system_tokens)} / {_int(e.tool_definitions_tokens)}")
    facts.add_row("compactions", str(e.n_compactions))
    facts.add_row("truncations", str(e.n_truncations))
    if e.files_modified is not None:
        facts.add_row("files modified", str(e.files_modified))
        facts.add_row("lines +/-", f"+{e.lines_added or 0} / -{e.lines_removed or 0}")
        if total_aiu and e.lines_added:
            facts.add_row("AIU / line added", f"{total_aiu / e.lines_added:.3f}")

    tables = [cost, facts]
    if len(e.model_metrics) > 1:
        models = Table(title="Per model", title_justify="left", show_edge=False, expand=False)
        models.add_column("model", style="dim")
        models.add_column("req", justify="right")
        models.add_column("in", justify="right")
        models.add_column("out", justify="right")
        models.add_column("AIU", justify="right")
        for m in e.model_metrics:
            models.add_row(
                m.model, str(m.requests), _int(m.input_tokens), _int(m.output_tokens), _aiu(m.aiu)
            )
        tables.append(models)
    return tables


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
    econ = _economics_renderables(analysis)
    if econ:
        console.print()
        console.print(Columns(econ, padding=(0, 4)))
    console.print()
    console.print(_timeline_table(analysis, max_turns=max_turns))
    if analysis.warnings:
        body = "\n".join(f"\u2022 {w}" for w in analysis.warnings)
        console.print(Panel(body, title="[bold]Warnings[/bold]", border_style="yellow",
                            expand=False))


# --------------------------------------------------------------------------- #
# Live (per-event) formatting for `run --verbose`
# --------------------------------------------------------------------------- #
class LiveEventFormatter:
    """Turn Copilot's ``--output-format json`` event stream into concise, ASCII-safe lines.

    Stateful, so it can correlate a tool completion back to its start (``toolCallId`` ->
    ``toolName``) and number assistant turns. Returns ``None`` for noisy/ephemeral events
    that aren't worth showing live, and falls back to the raw (trimmed) text for anything
    that isn't a JSON event object -- the user always sees *something*.

    ASCII markers (not unicode glyphs) keep output readable on Windows consoles.
    """

    def __init__(self, *, preview_len: int = 80) -> None:
        self._preview_len = preview_len
        self._tool_names: dict[str, str] = {}
        self._turn = 0

    def format(self, line: str) -> str | None:
        raw = line.strip()
        if not raw:
            return None
        try:
            ev = json.loads(raw)
        except (ValueError, TypeError):
            return raw  # not JSON -> show the raw line
        if not isinstance(ev, dict):
            return raw
        etype = str(ev.get("type", ""))
        data = ev.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        return self._format_event(etype, data)

    def _trim(self, text: object) -> str:
        if not isinstance(text, str):
            return ""
        flat = " ".join(text.split())
        if len(flat) <= self._preview_len:
            return flat
        return flat[: self._preview_len - 1] + "\u2026"

    def _format_event(self, etype: str, data: dict) -> str | None:
        if etype == "session.start":
            model = data.get("selectedModel") or "?"
            effort = data.get("reasoningEffort")
            tail = f" effort={effort}" if effort else ""
            return f"[session] start model={model}{tail}"

        if etype == "user.message":
            return f"[user] {self._trim(data.get('content'))}"

        if etype == "assistant.turn_start":
            self._turn += 1
            return f"[turn {self._turn}] start"

        if etype == "assistant.message":
            preview = self._trim(data.get("content"))
            out = data.get("outputTokens")
            suffix = f" ({out} tok)" if isinstance(out, int) else ""
            if not preview and not suffix:
                return None
            return f"[asst] {preview}{suffix}"

        if etype == "tool.execution_start":
            name = data.get("toolName") or "unknown"
            call_id = data.get("toolCallId")
            if isinstance(call_id, str):
                self._tool_names[call_id] = name
            return f"[tool] {name} start"

        if etype == "tool.execution_complete":
            call_id = data.get("toolCallId")
            name = "unknown"
            if isinstance(call_id, str):
                name = self._tool_names.get(call_id, "unknown")
            ok = data.get("success") is not False
            return f"[tool] {name} {'ok' if ok else 'FAILED'}"

        if etype == "assistant.turn_end":
            return f"[turn {self._turn}] end" if self._turn else None

        if etype == "session.warning":
            return f"[warn] {self._trim(data.get('message'))}"

        if etype in ("session.end", "session.finish", "session.complete"):
            return "[session] end"

        # Surface anything error-ish we don't explicitly model; skip the rest as noise.
        if "error" in etype or "fail" in etype:
            return f"[{etype}] {self._trim(data.get('message'))}".rstrip()
        return None
