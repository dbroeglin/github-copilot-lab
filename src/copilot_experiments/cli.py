"""``copilot-experiments`` command-line interface."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ._util import read_json
from .analysis import analyze_events
from .auth import AuthError, preflight_github_token
from .index import list_runs as index_list_runs
from .index import reindex as index_reindex
from .models import DryRunReport, Experiment, ExperimentRun
from .render import render_session_analysis
from .runner import dry_run_experiment, run_experiment
from .scaffold import ScaffoldError, init_experiment_repo
from .sessionlog import load_events
from .storage import Layout

app = typer.Typer(
    add_completion=False,
    help="Build and analyze GitHub Copilot research experiments.",
    no_args_is_help=True,
)
console = Console()
err = Console(stderr=True)


# --------------------------------------------------------------------------- #
# Experiment discovery
# --------------------------------------------------------------------------- #
def _load_experiments(experiments_dir: Path) -> list[tuple[Path, Experiment]]:
    """Import every ``*.py`` under ``experiments/`` and collect Experiment objects.

    A module contributes experiments via a module-level ``experiment`` (single),
    ``experiments`` (iterable), a ``get_experiments()`` function, or any
    module-level :class:`Experiment` instances.
    """
    found: list[tuple[Path, Experiment]] = []
    if not experiments_dir.is_dir():
        return found

    root = experiments_dir.parent.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    for path in sorted(experiments_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = _import_path(path)
        candidates: list[object] = []
        if hasattr(module, "get_experiments"):
            candidates.extend(list(module.get_experiments()))
        if hasattr(module, "experiments"):
            candidates.extend(list(module.experiments))
        if hasattr(module, "experiment"):
            candidates.append(module.experiment)
        if not candidates:
            candidates = [v for v in vars(module).values() if isinstance(v, Experiment)]
        seen: set[int] = set()
        for obj in candidates:
            if isinstance(obj, Experiment) and id(obj) not in seen:
                seen.add(id(obj))
                found.append((path, obj))
    return found


def _import_path(path: Path):
    name = f"copilot_experiments_user_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Cannot import experiment module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def init(
    directory: Path = typer.Argument(..., help="Directory for the new experiment repository."),
    name: str | None = typer.Option(None, "--name", help="Project name (defaults to dir name)."),
    force: bool = typer.Option(
        False, "--force", help="Scaffold even if the directory is not empty."
    ),
) -> None:
    """Scaffold a new, standalone experiment repository."""
    try:
        created = init_experiment_repo(directory, project_name=name, force=force)
    except ScaffoldError as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]Created {len(created)} files in[/green] {directory}")
    console.print("\nNext steps:")
    console.print(f"  cd {directory}")
    console.print("  uv sync")
    console.print("  uv run copilot-experiments run --dry-run")


@app.command()
def run(
    name: str | None = typer.Argument(None, help="Only run the experiment with this name/slug."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate the whole pipeline in a throwaway dir and persist nothing.",
    ),
    copilot_binary: str = typer.Option("copilot", "--copilot", help="Path to the copilot binary."),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Stream per-trial progress and live Copilot output as the run proceeds.",
    ),
) -> None:
    """Discover and run experiment(s) defined under ``experiments/``.

    With ``--dry-run`` the full pipeline is exercised with the mock invoker inside a
    temporary directory, each stage is validated, and everything is deleted again --
    no run is recorded under ``results/``.

    Pass ``--verbose`` to stream per-trial progress (workspace provisioning, the
    Copilot invocation, session-log/metrics, and verification) plus Copilot's own
    output live as the run proceeds.
    """
    root = Path(root or Path.cwd())
    layout = Layout(root)
    experiments = _load_experiments(layout.experiments_dir)
    if not experiments:
        err.print(f"[yellow]No experiments found in[/yellow] {layout.experiments_dir}")
        raise typer.Exit(1)

    if name:
        experiments = [(p, e) for p, e in experiments if name in (e.name, e.slug)]
        if not experiments:
            err.print(f"[red]No experiment matched[/red] {name!r}")
            raise typer.Exit(1)

    if dry_run:
        all_ok = True
        for _path, experiment in experiments:
            console.print(
                f"[bold]Dry-run[/bold] {experiment.name} "
                f"({len(experiment.variants)} variant(s)) [dim]— validating plumbing[/dim]"
            )
            report = dry_run_experiment(experiment, root=root)
            _print_dry_run_report(report)
            all_ok = all_ok and report.ok
        raise typer.Exit(0 if all_ok else 1)

    # Preflight authentication ONCE so a missing token aborts immediately instead of
    # failing every trial after provisioning. The token is injected into each trial's
    # environment; it is never logged (only its source) or persisted.
    try:
        auth = preflight_github_token()
    except AuthError as exc:
        err.print(f"[red]Authentication error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[dim]auth:[/dim] using GitHub token from {auth.source}")

    any_failures = False
    for _path, experiment in experiments:
        console.print(f"[bold]Running[/bold] {experiment.name} "
                      f"({len(experiment.variants)} variant(s))")
        progress = _make_progress() if verbose else None
        copilot_stream = _make_copilot_stream() if verbose else None
        run_obj = run_experiment(
            experiment,
            root=root,
            copilot_binary=copilot_binary,
            github_token=auth.token,
            progress=progress,
            copilot_stream=copilot_stream,
        )
        summary = read_json(layout.run_dir(experiment.slug, run_obj.run_id) / "summary.json")
        _print_run_summary(summary)
        _warn_failed_trials(layout, experiment, run_obj)
        if run_obj.status != "completed":
            any_failures = True
        console.print(f"[dim]results:[/dim] {layout.run_dir(experiment.slug, run_obj.run_id)}\n")

    # A distinct exit code (2) lets scripts tell harness/infra trouble apart from a
    # clean run (0) and usage errors like "no experiments found" (1).
    if any_failures:
        raise typer.Exit(2)


@app.command(name="list")
def list_cmd(
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """List experiments and past runs."""
    root = Path(root or Path.cwd())
    layout = Layout(root)
    experiments = _load_experiments(layout.experiments_dir)
    if experiments:
        table = Table(title="Experiments", show_edge=False)
        table.add_column("name")
        table.add_column("slug")
        table.add_column("variants", justify="right")
        for _path, exp in experiments:
            table.add_row(exp.name, exp.slug, str(len(exp.variants)))
        console.print(table)

    runs = index_list_runs(layout)
    if not runs:
        console.print("[dim]No runs yet.[/dim]")
        return
    table = Table(title="Runs")
    table.add_column("run id")
    table.add_column("experiment")
    table.add_column("started")
    table.add_column("trials", justify="right")
    table.add_column("success", justify="right")
    for r in runs:
        sr = r.get("success_rate")
        table.add_row(
            r["run_id"],
            r["experiment_slug"],
            (r.get("started_at") or "")[:19],
            str(r.get("n_trials") or 0),
            "-" if sr is None else f"{sr * 100:.0f}%",
        )
    console.print(table)


@app.command()
def show(
    run_id: str | None = typer.Argument(None, help="Run id or unique prefix."),
    last: bool = typer.Option(False, "--last", help="Show the most recent run."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Print a run summary and per-variant comparison."""
    root = Path(root or Path.cwd())
    layout = Layout(root)
    run_dir = layout.latest_run() if last else (layout.find_run(run_id) if run_id else None)
    if run_dir is None:
        err.print("[red]Run not found.[/red] Pass a run id or --last.")
        raise typer.Exit(1)
    _print_run_summary(read_json(run_dir / "summary.json"))
    console.print(f"\n[dim]{run_dir / 'summary.md'}[/dim]")


@app.command()
def inspect(
    run_id: str | None = typer.Argument(None, help="Run id or unique prefix."),
    variant: str | None = typer.Option(None, "--variant", help="Variant slug."),
    trial: int | None = typer.Option(None, "--trial", help="Trial number."),
    events: int = typer.Option(20, "--events", help="Number of session events to show."),
    last: bool = typer.Option(False, "--last", help="Inspect the most recent run."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Drill into a run's variants, trials, and session events."""
    root = Path(root or Path.cwd())
    layout = Layout(root)
    run_dir = layout.latest_run() if last else (layout.find_run(run_id) if run_id else None)
    if run_dir is None:
        err.print("[red]Run not found.[/red] Pass a run id or --last.")
        raise typer.Exit(1)

    variants_dir = run_dir / "variants"
    if variant is None:
        table = Table(title=f"Variants in {run_dir.name}")
        table.add_column("variant")
        table.add_column("trials", justify="right")
        for vdir in sorted(variants_dir.iterdir()):
            trials = sorted((vdir / "trials").glob("*")) if (vdir / "trials").is_dir() else []
            table.add_row(vdir.name, str(len(trials)))
        console.print(table)
        return

    trials_dir = variants_dir / variant / "trials"
    if trial is None:
        table = Table(title=f"Trials in {variant}")
        table.add_column("trial")
        table.add_column("status")
        table.add_column("success")
        table.add_column("exit")
        table.add_column("duration (s)", justify="right")
        for tdir in sorted(trials_dir.iterdir()):
            meta = read_json(tdir / "meta.json")
            table.add_row(
                tdir.name,
                str(meta.get("status", "-")),
                str(meta.get("success")),
                str(meta.get("exit_code")),
                f"{meta.get('duration_s', 0):.2f}",
            )
        console.print(table)
        return

    tdir = trials_dir / f"{trial:03d}"
    if not tdir.is_dir():
        err.print(f"[red]Trial not found:[/red] {tdir}")
        raise typer.Exit(1)
    console.print(f"[bold]meta[/bold]: {read_json(tdir / 'meta.json')}")
    meta = read_json(tdir / "meta.json")
    if meta.get("status") and meta["status"] != "ok":
        artifact = meta.get("error_artifact") or "stdout.txt"
        console.print(
            f"[yellow]status[/yellow]: {meta['status']} — {meta.get('error') or ''}\n"
            f"  -> {tdir / artifact}"
        )
    console.print(f"[bold]metrics[/bold]: {read_json(tdir / 'metrics.json')}")
    if (tdir / "verify.json").exists():
        verify = read_json(tdir / "verify.json")
        console.print(
            f"[bold]verify[/bold]: exit={verify['exit_code']} success={verify['success']}"
        )
    evs = load_events(tdir / "events.jsonl")
    console.print(f"\n[bold]events[/bold] (showing up to {events} of {len(evs)}):")
    for ev in evs[:events]:
        console.print(f"  {ev.get('timestamp', '')[:23]:23}  {ev.get('type')}")


@app.command()
def analyze(
    run_id: str | None = typer.Argument(None, help="Run id or unique prefix."),
    variant: str | None = typer.Option(None, "--variant", help="Variant slug (default: first)."),
    trial: int | None = typer.Option(None, "--trial", help="Trial number (default: first)."),
    file: Path | None = typer.Option(
        None, "--file", help="Analyze an events.jsonl file directly (ignores run/variant/trial)."
    ),
    last: bool = typer.Option(False, "--last", help="Analyze the most recent run."),
    max_turns: int = typer.Option(0, "--max-turns", help="Limit timeline rows (0 = all)."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Analyze a captured session log and render a rich overview of what happened."""
    if file is not None:
        events = load_events(file)
        if not events:
            err.print(f"[red]No events found in[/red] {file}")
            raise typer.Exit(1)
        render_session_analysis(analyze_events(events), console, title=file.name,
                                max_turns=max_turns)
        return

    root = Path(root or Path.cwd())
    layout = Layout(root)
    run_dir = layout.latest_run() if last else (layout.find_run(run_id) if run_id else None)
    if run_dir is None:
        err.print("[red]Run not found.[/red] Pass a run id, --last, or --file.")
        raise typer.Exit(1)

    events_path, label = _resolve_trial_events(run_dir, variant, trial)
    if events_path is None:
        err.print(f"[red]No trial session log found in[/red] {run_dir}")
        raise typer.Exit(1)

    render_session_analysis(
        analyze_events(load_events(events_path)), console, title=label, max_turns=max_turns
    )


@app.command()
def reindex(
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Rebuild ``results/index.db`` by scanning the filesystem."""
    root = Path(root or Path.cwd())
    layout = Layout(root)
    count = index_reindex(layout)
    console.print(f"[green]Reindexed {count} run(s)[/green] -> {layout.index_db}")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _resolve_trial_events(
    run_dir: Path, variant: str | None, trial: int | None
) -> tuple[Path | None, str]:
    """Locate a trial's ``events.jsonl``, defaulting to the first variant/trial."""
    variants_dir = run_dir / "variants"
    if variant is not None:
        vdir = variants_dir / variant
    else:
        subdirs = sorted(p for p in variants_dir.iterdir() if p.is_dir()) \
            if variants_dir.is_dir() else []
        if not subdirs:
            return None, run_dir.name
        vdir = subdirs[0]

    trials_dir = vdir / "trials"
    if trial is not None:
        tdir = trials_dir / f"{trial:03d}"
    else:
        subdirs = sorted(p for p in trials_dir.iterdir() if p.is_dir()) \
            if trials_dir.is_dir() else []
        if not subdirs:
            return None, f"{run_dir.name} · {vdir.name}"
        tdir = subdirs[0]

    label = f"{run_dir.name} · {vdir.name}/{tdir.name}"
    events_path = tdir / "events.jsonl"
    return (events_path if events_path.exists() else None), label


def _print_dry_run_report(report: DryRunReport) -> None:
    table = Table(title=f"Dry-run · {report.experiment}", show_lines=False)
    table.add_column("", justify="center", width=3)
    table.add_column("check")
    table.add_column("detail", style="dim")
    for c in report.checks:
        mark = "[green]✓[/green]" if c.ok else "[red]✗[/red]"
        table.add_row(mark, c.name, c.detail)
    console.print(table)
    tail = "[dim]— nothing persisted (temp dir removed)[/dim]\n"
    if report.ok:
        console.print(f"[green]plumbing OK[/green] {tail}")
    else:
        console.print(f"[red]plumbing FAILED[/red] {tail}")


def _make_progress() -> Callable[[str], None]:
    """Return a progress sink for ``run --verbose``.

    Each line is printed dimmed. ``markup=False`` keeps Copilot's raw output and the
    ``[variant/NNN]`` phase tags from being interpreted as Rich markup.
    """

    def _emit(msg: str) -> None:
        console.print(msg, style="dim", markup=False, highlight=False)

    return _emit


def _make_copilot_stream() -> Callable[[str], None]:
    """Return a live Copilot-output sink for ``run --verbose``.

    Copilot's ``--output-format json`` stream is a firehose of JSON events; a stateful
    :class:`~copilot_experiments.render.LiveEventFormatter` condenses each into a short,
    ASCII-tagged line (turns, messages, tool calls). Unparseable lines fall back to raw
    text; pure-noise events are dropped. Output is indented under the phase messages.
    """
    from .render import LiveEventFormatter

    formatter = LiveEventFormatter()

    def _emit(line: str) -> None:
        rendered = formatter.format(line)
        if rendered is not None:
            console.print(f"    {rendered}", style="dim", markup=False, highlight=False)

    return _emit


def _warn_failed_trials(layout: Layout, experiment: Experiment, run: ExperimentRun) -> None:
    """Loudly flag trials that did not run cleanly, with a pointer to diagnose.

    The summary table still renders a row for a Copilot invocation that errored out
    immediately (e.g. bad auth or a bad working directory) -- just with zero turns.
    That makes a broken run look deceptively clean. We surface harness/infra failures
    explicitly, classify them (harness vs copilot), and point at the exact artifact to
    inspect (its ``stdout.txt``).
    """
    problems: list[str] = []
    for vr in run.variants:
        for trial in vr.trials:
            if not trial.failed:
                continue
            trial_dir = layout.trial_dir(
                experiment.slug, run.run_id, vr.variant.slug, trial.trial_no
            )
            label = (
                "harness failure" if trial.status == "harness_error" else "copilot did not run"
            )
            detail = trial.error or trial.status
            artifact = trial.error_artifact or "stdout.txt"
            problems.append(
                f"  {vr.variant.slug}/{trial.trial_no:03d}: {label} — {detail}\n"
                f"      -> {trial_dir / artifact}"
            )
    if not problems:
        return
    err.print(
        f"[yellow]Warning:[/yellow] run status [bold]{run.status}[/bold] — "
        f"{len(problems)} trial(s) failed in the harness (not the experiment). "
        "Inspect the captured output:"
    )
    for line in problems:
        err.print(f"[yellow]{line}[/yellow]")


def _print_run_summary(summary: dict) -> None:
    sr = summary.get("overall_success_rate")
    title = (
        f"{summary['experiment']}  ·  {summary['run_id']}  ·  "
        f"{summary['n_trials']} trial(s)  ·  "
        f"success {'-' if sr is None else f'{sr * 100:.0f}%'}"
    )
    table = Table(title=title)
    table.add_column("variant")
    table.add_column("model")
    table.add_column("effort")
    table.add_column("byok")
    table.add_column("trials", justify="right")
    table.add_column("success", justify="right")
    table.add_column("avg dur", justify="right")
    table.add_column("turns", justify="right")
    table.add_column("tool calls", justify="right")
    table.add_column("tool fails", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("AIU", justify="right")
    table.add_column("AIU/solve", justify="right")
    for v in summary["variants"]:
        vsr = v.get("success_rate")
        table.add_row(
            v["name"],
            v.get("model") or "-",
            v.get("reasoning_effort") or "-",
            "yes" if v.get("byok") else "no",
            str(v["n_trials"]),
            "-" if vsr is None else f"{vsr * 100:.0f}%",
            _num(v.get("avg_duration_s")),
            _num(v.get("avg_turns")),
            _num(v.get("avg_tool_calls")),
            _num(v.get("avg_tool_failures")),
            _num(v.get("avg_total_tokens")),
            _aiu(v.get("avg_aiu")),
            _aiu(v.get("aiu_per_solve")),
        )
    total_aiu = summary.get("total_aiu")
    if total_aiu is not None:
        console.print(table)
        console.print(f"[dim]total cost:[/dim] {_aiu(total_aiu)} AIU")
        return
    console.print(table)


def _aiu(value: object) -> str:
    if value is None:
        return "-"
    val = float(value)
    return f"{val:.3f}" if val < 1 else f"{val:,.2f}"


def _num(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


if __name__ == "__main__":
    app()

