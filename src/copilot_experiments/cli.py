"""``copilot-experiments`` command-line interface."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ._util import read_json
from .analysis import analyze_events
from .index import list_runs as index_list_runs
from .index import reindex as index_reindex
from .models import DryRunReport, Experiment
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
) -> None:
    """Discover and run experiment(s) defined under ``experiments/``.

    With ``--dry-run`` the full pipeline is exercised with the mock invoker inside a
    temporary directory, each stage is validated, and everything is deleted again --
    no run is recorded under ``results/``.
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

    for _path, experiment in experiments:
        console.print(f"[bold]Running[/bold] {experiment.name} "
                      f"({len(experiment.variants)} variant(s))")
        run_obj = run_experiment(experiment, root=root, copilot_binary=copilot_binary)
        summary = read_json(layout.run_dir(experiment.slug, run_obj.run_id) / "summary.json")
        _print_run_summary(summary)
        console.print(f"[dim]results:[/dim] {layout.run_dir(experiment.slug, run_obj.run_id)}\n")


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
        table.add_column("success")
        table.add_column("exit")
        table.add_column("duration (s)", justify="right")
        for tdir in sorted(trials_dir.iterdir()):
            meta = read_json(tdir / "meta.json")
            table.add_row(
                tdir.name,
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
        )
    console.print(table)


def _num(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


if __name__ == "__main__":
    app()

