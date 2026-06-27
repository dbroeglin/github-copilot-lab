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
from .analysis import analyze_events, analyze_trajectory
from .auth import AuthError, preflight_github_token
from .deepswe import DeepSweImportError, write_deepswe_job_config
from .index import list_runs as index_list_runs
from .index import reindex as index_reindex
from .models import DryRunReport, Experiment, ExperimentRun
from .pier_backend import (
    PierBackendPreflightError,
    discover_pier_job_configs,
    inject_copilot_token,
    preflight_pier_backend,
    prepare_pier_job_for_run,
    run_pier_job,
)
from .pier_results import (
    describe_missing_pier_analysis_source,
    iter_pier_trial_summaries,
    resolve_pier_trial_analysis_source,
    write_pier_summary,
)
from .render import render_session_analysis
from .runner import dry_run_experiment, run_experiment
from .scaffold import ScaffoldError, init_experiment_repo
from .sessionlog import load_events
from .storage import Layout


def _force_utf8_streams() -> None:
    """Make stdout/stderr UTF-8 so Rich glyphs (e.g. ``✓``) don't crash.

    On Windows the console and redirected pipes default to a legacy code page
    (cp1252), which raises ``UnicodeEncodeError`` on non-Latin-1 characters.
    ``errors="replace"`` is a belt-and-braces fallback for any remaining
    unencodable glyph.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


_force_utf8_streams()

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


@app.command("deepswe-import")
def deepswe_import(
    source: Path = typer.Argument(
        ...,
        help="DeepSWE checkout root, tasks directory, or single task directory.",
    ),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
    job_name: str = typer.Option(
        "deepswe-copilot",
        "--job-name",
        "--name",
        help="Pier job name and default output filename.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Job config path. Relative paths are resolved from --root.",
    ),
    model: str = typer.Option("gpt-5-mini", "--model", help="Copilot model for the agent."),
    effort: str | None = typer.Option(
        "medium",
        "--effort",
        help="Copilot reasoning effort. Pass an empty string to omit.",
    ),
    mode: str | None = typer.Option(None, "--mode", help="Optional Copilot CLI mode."),
    context_tier: str | None = typer.Option(
        None,
        "--context-tier",
        help="Optional Copilot context tier.",
    ),
    environment: str | None = typer.Option(
        None,
        "--environment",
        help="Optional Pier backend type, e.g. docker or modal.",
    ),
    n_attempts: int = typer.Option(1, "--n-attempts", help="Attempts per agent/task cell."),
    n_concurrent_trials: int = typer.Option(
        1,
        "--n-concurrent-trials",
        help="Maximum Pier trial concurrency.",
    ),
    task_names: list[str] = typer.Option(
        [],
        "--task",
        help="Task name or glob to include. Repeat for multiple filters.",
    ),
    n_tasks: int | None = typer.Option(
        None,
        "--n-tasks",
        help="Maximum number of tasks to include from the DeepSWE corpus.",
    ),
    sample_seed: int | None = typer.Option(
        None,
        "--sample-seed",
        help="Deterministic Pier sampling seed used with dataset tasks.",
    ),
    jobs_dir: str = typer.Option("jobs", "--jobs-dir", help="Pier jobs directory."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing output file."),
) -> None:
    """Generate a Pier job config for a cloned DeepSWE task corpus."""

    root = Path(root or Path.cwd())
    try:
        result = write_deepswe_job_config(
            source,
            root=root,
            output=output,
            overwrite=force,
            job_name=job_name,
            jobs_dir=jobs_dir,
            model=model,
            reasoning_effort=(effort or None),
            mode=mode,
            context_tier=context_tier,
            environment=environment,
            n_attempts=n_attempts,
            n_concurrent_trials=n_concurrent_trials,
            task_names=task_names or None,
            n_tasks=n_tasks,
            sample_seed=sample_seed,
        )
    except DeepSweImportError as exc:
        err.print(f"[red]DeepSWE import error:[/red] {exc}")
        raise typer.Exit(1) from exc

    display_path = (
        result.path.relative_to(root.resolve())
        if result.path.is_relative_to(root.resolve())
        else result.path
    )
    task_label = "task" if result.source.task_count == 1 else "tasks"
    source_label = "single task" if result.source.kind == "task" else "task corpus"
    console.print(f"[green]Wrote[/green] {display_path}")
    console.print(
        f"[dim]source:[/dim] {result.source.path} "
        f"({source_label}, {result.source.task_count} {task_label})"
    )
    console.print("[dim]validate:[/dim] uv run copilot-experiments run --dry-run")


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
        help="Enable debug-level Pier output. Legacy experiments also stream Copilot output.",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help=(
            "Resume an existing Pier job directory instead of creating a fresh rerun when the "
            "configured job name already exists."
        ),
    ),
) -> None:
    """Discover and run experiment(s) defined under ``experiments/``.

    With ``--dry-run`` the full pipeline is exercised with the mock invoker inside a
    temporary directory, each stage is validated, and everything is deleted again --
    no run is recorded under ``results/``.

    Pier configs create a fresh job directory on rerun when the configured job name
    already exists. Pass ``--resume`` to opt into Pier's native resume behavior, which
    skips trials that already completed for the same resolved config.
    """
    root = Path(root or Path.cwd())
    layout = Layout(root)
    pier_specs = discover_pier_job_configs(root, name=name)
    if pier_specs:
        if dry_run:
            table = Table(title="Pier job configs", show_edge=False)
            table.add_column("job")
            table.add_column("config")
            table.add_column("tasks", justify="right")
            table.add_column("agents", justify="right")
            for spec in pier_specs:
                table.add_row(
                    spec.name,
                    str(spec.path.relative_to(root)),
                    str(len(spec.config.tasks) + len(spec.config.datasets)),
                    str(len(spec.config.agents)),
                )
            console.print(table)
            console.print("[green]Pier config validation OK[/green] [dim]— no job was run[/dim]")
            raise typer.Exit(0)

        try:
            for spec in pier_specs:
                preflight_pier_backend(spec.config)
        except PierBackendPreflightError as exc:
            err.print(f"[red]Pier backend preflight failed:[/red] {exc}")
            raise typer.Exit(1) from exc

        try:
            auth = preflight_github_token()
        except AuthError as exc:
            err.print(f"[red]Authentication error:[/red] {exc}")
            raise typer.Exit(1) from exc
        console.print(f"[dim]auth:[/dim] using GitHub token from {auth.source}")

        any_failures = False
        for spec in pier_specs:
            prepared = prepare_pier_job_for_run(spec.config, resume=resume)
            if verbose:
                prepared.config.debug = True
            inject_copilot_token(prepared.config, auth.token)
            console.print(f"[bold]Running Pier job[/bold] {prepared.run_name}")
            if prepared.renamed:
                console.print(
                    f"[dim]existing job[/dim] {prepared.requested_name} "
                    f"[dim]found; writing fresh rerun to[/dim] {prepared.run_name} "
                    "[dim](use --resume to reuse the existing job)[/dim]"
                )
            try:
                run_result = run_pier_job(prepared.config)
            except Exception as exc:
                err.print(f"[red]Pier job failed:[/red] {type(exc).__name__}: {exc}")
                any_failures = True
                continue
            summary = write_pier_summary(run_result.job_dir)
            _print_run_summary(summary)
            _warn_failed_pier_trials(run_result.job_dir)
            if summary.get("status") != "completed":
                any_failures = True
            console.print(f"[dim]results:[/dim] {run_result.job_dir}\n")

        if any_failures:
            raise typer.Exit(2)
        raise typer.Exit(0)

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
        console.print(
            f"[bold]Running[/bold] {experiment.name} ({len(experiment.variants)} variant(s))"
        )
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
    pier_specs = discover_pier_job_configs(root)
    if pier_specs:
        table = Table(title="Pier job configs", show_edge=False)
        table.add_column("job")
        table.add_column("config")
        table.add_column("tasks", justify="right")
        table.add_column("agents", justify="right")
        for spec in pier_specs:
            table.add_row(
                spec.name,
                str(spec.path.relative_to(root)),
                str(len(spec.config.tasks) + len(spec.config.datasets)),
                str(len(spec.config.agents)),
            )
        console.print(table)

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
    else:
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

    pier_jobs = layout.iter_pier_jobs()
    if not pier_jobs:
        return
    table = Table(title="Runs")
    table.add_column("pier job")
    table.add_column("started")
    table.add_column("trials", justify="right")
    table.add_column("status")
    for job_dir in pier_jobs:
        summary = write_pier_summary(job_dir)
        table.add_row(
            job_dir.name,
            (summary.get("started_at") or "")[:19],
            str(summary.get("n_trials") or 0),
            str(summary.get("status") or "-"),
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
    pier_job = _resolve_pier_job(layout, last=last, run_id=run_id)
    run_dir = (
        None
        if last and pier_job is not None
        else (layout.latest_run() if last else (layout.find_run(run_id) if run_id else None))
    )
    if run_dir is None:
        if pier_job is not None:
            summary = write_pier_summary(pier_job)
            _print_run_summary(summary)
            console.print(f"\n[dim]{pier_job / 'summary.md'}[/dim]")
            return
    if run_dir is None:
        err.print("[red]Run not found.[/red] Pass a run id or --last.")
        raise typer.Exit(1)
    _print_run_summary(read_json(run_dir / "summary.json"))
    console.print(f"\n[dim]{run_dir / 'summary.md'}[/dim]")


@app.command()
def inspect(
    run_id: str | None = typer.Argument(None, help="Run id or unique prefix."),
    variant: str | None = typer.Option(None, "--variant", help="Variant slug."),
    task: str | None = typer.Option(None, "--task", help="Task slug."),
    trial: int | None = typer.Option(None, "--trial", help="Trial number."),
    events: int = typer.Option(20, "--events", help="Number of session events to show."),
    last: bool = typer.Option(False, "--last", help="Inspect the most recent run."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Drill into a run's variants, tasks, trials, and session events."""
    root = Path(root or Path.cwd())
    layout = Layout(root)
    pier_job = _resolve_pier_job(layout, last=last, run_id=run_id)
    run_dir = (
        None
        if last and pier_job is not None
        else (layout.latest_run() if last else (layout.find_run(run_id) if run_id else None))
    )
    if run_dir is None:
        if pier_job is not None:
            _inspect_pier_job(pier_job)
            return
    if run_dir is None:
        err.print("[red]Run not found.[/red] Pass a run id or --last.")
        raise typer.Exit(1)

    variants_dir = run_dir / "variants"
    if variant is None:
        table = Table(title=f"Variants in {run_dir.name}")
        table.add_column("variant")
        table.add_column("tasks", justify="right")
        table.add_column("trials", justify="right")
        for vdir in sorted(variants_dir.iterdir()):
            tasks = sorted((vdir / "tasks").glob("*")) if (vdir / "tasks").is_dir() else []
            n_trials = sum(
                len(sorted((tk / "trials").glob("*"))) if (tk / "trials").is_dir() else 0
                for tk in tasks
            )
            table.add_row(vdir.name, str(len(tasks)), str(n_trials))
        console.print(table)
        return

    tasks_dir = variants_dir / variant / "tasks"
    if task is None:
        table = Table(title=f"Tasks in {variant}")
        table.add_column("task")
        table.add_column("trials", justify="right")
        for tkdir in sorted(tasks_dir.iterdir()) if tasks_dir.is_dir() else []:
            trials = sorted((tkdir / "trials").glob("*")) if (tkdir / "trials").is_dir() else []
            table.add_row(tkdir.name, str(len(trials)))
        console.print(table)
        return

    trials_dir = tasks_dir / task / "trials"
    if trial is None:
        table = Table(title=f"Trials in {variant}/{task}")
        table.add_column("trial")
        table.add_column("status")
        table.add_column("success")
        table.add_column("exit")
        table.add_column("duration (s)", justify="right")
        for tdir in sorted(trials_dir.iterdir()) if trials_dir.is_dir() else []:
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
    task: str | None = typer.Option(None, "--task", help="Task slug (default: first)."),
    trial: int | None = typer.Option(None, "--trial", help="Trial number (default: first)."),
    file: Path | None = typer.Option(
        None, "--file", help="Analyze an events.jsonl file directly (ignores run/variant/trial)."
    ),
    otel_file: Path | None = typer.Option(
        None, "--otel-file", help="Optional Copilot OTel JSONL file to enrich analysis."
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
        otel_records = load_events(otel_file) if otel_file is not None else None
        render_session_analysis(
            analyze_events(events, otel_records), console, title=file.name, max_turns=max_turns
        )
        return

    root = Path(root or Path.cwd())
    layout = Layout(root)
    pier_job = _resolve_pier_job(layout, last=last, run_id=run_id)
    run_dir = (
        None
        if last and pier_job is not None
        else (layout.latest_run() if last else (layout.find_run(run_id) if run_id else None))
    )
    if run_dir is None:
        if pier_job is not None:
            source_path, label, source_kind, discovered_otel = resolve_pier_trial_analysis_source(
                pier_job, trial
            )
            if source_path is None:
                err.print(f"[red]No Copilot session log or trajectory found in[/red] {pier_job}")
                diagnostic = describe_missing_pier_analysis_source(pier_job, trial)
                if diagnostic:
                    err.print(f"[yellow]{diagnostic}[/yellow]")
                raise typer.Exit(1)
            selected_otel = otel_file or discovered_otel
            analysis = (
                analyze_events(
                    load_events(source_path),
                    load_events(selected_otel) if selected_otel is not None else None,
                )
                if source_kind == "events"
                else analyze_trajectory(read_json(source_path))
            )
            render_session_analysis(analysis, console, title=label, max_turns=max_turns)
            return
    if run_dir is None:
        err.print("[red]Run not found.[/red] Pass a run id, --last, or --file.")
        raise typer.Exit(1)

    events_path, label, discovered_otel = _resolve_trial_events(run_dir, variant, task, trial)
    if events_path is None:
        err.print(f"[red]No trial session log found in[/red] {run_dir}")
        raise typer.Exit(1)

    selected_otel = otel_file or discovered_otel
    render_session_analysis(
        analyze_events(
            load_events(events_path),
            load_events(selected_otel) if selected_otel is not None else None,
        ),
        console,
        title=label,
        max_turns=max_turns,
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
    run_dir: Path, variant: str | None, task: str | None, trial: int | None
) -> tuple[Path | None, str, Path | None]:
    """Locate a trial's ``events.jsonl``, defaulting to the first variant/task/trial."""
    variants_dir = run_dir / "variants"
    if variant is not None:
        vdir = variants_dir / variant
    else:
        subdirs = (
            sorted(p for p in variants_dir.iterdir() if p.is_dir()) if variants_dir.is_dir() else []
        )
        if not subdirs:
            return None, run_dir.name, None
        vdir = subdirs[0]

    tasks_dir = vdir / "tasks"
    if task is not None:
        tkdir = tasks_dir / task
    else:
        subdirs = sorted(p for p in tasks_dir.iterdir() if p.is_dir()) if tasks_dir.is_dir() else []
        if not subdirs:
            return None, f"{run_dir.name} · {vdir.name}", None
        tkdir = subdirs[0]

    trials_dir = tkdir / "trials"
    if trial is not None:
        tdir = trials_dir / f"{trial:03d}"
    else:
        subdirs = (
            sorted(p for p in trials_dir.iterdir() if p.is_dir()) if trials_dir.is_dir() else []
        )
        if not subdirs:
            return None, f"{run_dir.name} · {vdir.name}/{tkdir.name}", None
        tdir = subdirs[0]

    label = f"{run_dir.name} · {vdir.name}/{tkdir.name}/{tdir.name}"
    events_path = tdir / "events.jsonl"
    otel_path = tdir / "copilot-otel.jsonl"
    return (
        events_path if events_path.exists() else None,
        label,
        otel_path if otel_path.exists() else None,
    )


def _resolve_pier_job(layout: Layout, *, last: bool, run_id: str | None) -> Path | None:
    if last:
        return layout.latest_pier_job()
    if run_id:
        return layout.find_pier_job(run_id)
    return None


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
        for tr in vr.tasks:
            for trial in tr.trials:
                if not trial.failed:
                    continue
                trial_dir = layout.trial_dir(
                    experiment.slug, run.run_id, vr.variant.slug, tr.task_slug, trial.trial_no
                )
                label = (
                    "harness failure" if trial.status == "harness_error" else "copilot did not run"
                )
                detail = trial.error or trial.status
                artifact = trial.error_artifact or "stdout.txt"
                problems.append(
                    f"  {vr.variant.slug}/{tr.task_slug}/{trial.trial_no:03d}: "
                    f"{label} — {detail}\n"
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


def _warn_failed_pier_trials(job_dir: Path) -> None:
    """Point Pier harness failures at the trial result artifact."""

    problems: list[str] = []
    for trial in iter_pier_trial_summaries(job_dir):
        if trial.get("status") == "ok":
            continue
        trial_name = str(trial.get("trial_name") or trial.get("trial_no") or "-")
        problems.append(
            f"  {trial_name}: harness failure — {trial.get('error') or trial.get('status')}\n"
            f"      -> {job_dir / trial_name / 'result.json'}"
        )
    if not problems:
        return
    err.print(
        f"[yellow]Warning:[/yellow] Pier job [bold]{job_dir.name}[/bold] had "
        f"{len(problems)} harness failure(s). Inspect the captured trial result:"
    )
    for line in problems:
        err.print(f"[yellow]{line}[/yellow]")


def _inspect_pier_job(job_dir: Path) -> None:
    summary = write_pier_summary(job_dir)
    console.print(f"[bold]Pier job[/bold]: {job_dir.name}")
    console.print(f"[bold]summary[/bold]: {job_dir / 'summary.json'}")
    _print_run_summary(summary)

    table = Table(title=f"Trials in {job_dir.name}")
    table.add_column("trial")
    table.add_column("status")
    table.add_column("success")
    table.add_column("analysis")
    for trial_dir in sorted(
        path for path in job_dir.iterdir() if path.is_dir() and (path / "result.json").exists()
    ):
        result = read_json(trial_dir / "result.json")
        exception = result.get("exception_info")
        rewards = (result.get("verifier_result") or {}).get("rewards") or {}
        success = "-"
        if rewards:
            success = "yes" if any(float(value) > 0 for value in rewards.values()) else "no"
        source_path, _label, source_kind, _otel_path = resolve_pier_trial_analysis_source(
            job_dir, trial_dir.name
        )
        table.add_row(
            trial_dir.name,
            "harness_error" if exception else "ok",
            success,
            source_kind or ("yes" if source_path else "no"),
        )
    console.print(table)


def _print_run_summary(summary: dict) -> None:
    sr = summary.get("overall_success_rate")
    n_tasks = summary.get("n_tasks", 1)
    multitask = n_tasks > 1
    title = (
        f"{summary['experiment']}  ·  {summary['run_id']}  ·  "
        f"{n_tasks} task(s) · {summary['n_trials']} trial(s)  ·  "
        f"success {'-' if sr is None else f'{sr * 100:.0f}%'}"
    )
    table = Table(title=title)
    table.add_column("variant")
    table.add_column("model")
    table.add_column("effort")
    table.add_column("byok")
    if multitask:
        table.add_column("tasks", justify="right")
    table.add_column("trials", justify="right")
    table.add_column("success", justify="right")
    if multitask:
        table.add_column("mean", justify="right")
        table.add_column("resolved@k", justify="right")
    table.add_column("avg dur", justify="right")
    table.add_column("turns", justify="right")
    table.add_column("tool calls", justify="right")
    table.add_column("tool fails", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("AIU", justify="right")
    table.add_column("AIU/solve", justify="right")
    for v in summary["variants"]:
        vsr = v.get("success_rate")
        ms = v.get("mean_resolved_rate")
        rk = v.get("resolved_at_k_rate")
        row = [
            v["name"],
            v.get("model") or "-",
            v.get("reasoning_effort") or "-",
            "yes" if v.get("byok") else "no",
        ]
        if multitask:
            row.append(str(v.get("n_tasks", "-")))
        row.append(str(v["n_trials"]))
        row.append("-" if vsr is None else f"{vsr * 100:.0f}%")
        if multitask:
            row.append("-" if ms is None else f"{ms * 100:.0f}%")
            row.append("-" if rk is None else f"{rk * 100:.0f}%")
        row += [
            _num(v.get("avg_duration_s")),
            _num(v.get("avg_turns")),
            _num(v.get("avg_tool_calls")),
            _num(v.get("avg_tool_failures")),
            _num(v.get("avg_total_tokens")),
            _aiu(v.get("avg_aiu")),
            _aiu(v.get("aiu_per_solve")),
        ]
        table.add_row(*row)
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
