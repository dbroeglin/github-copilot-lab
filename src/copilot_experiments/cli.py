"""``copilot-experiments`` command-line interface."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ._util import read_json
from .analysis import analyze_events, analyze_trajectory
from .auth import AuthError, preflight_github_token
from .deepswe import DeepSweImportError, write_deepswe_job_config
from .pier_backend import (
    PierBackendPreflightError,
    PierJobSpec,
    discover_pier_job_configs,
    inject_copilot_token,
    preflight_pier_backend,
    prepare_pier_job_for_run,
    run_pier_job,
)
from .pier_results import (
    describe_missing_pier_analysis_source,
    iter_pier_trial_summaries,
    pier_job_label,
    resolve_pier_trial_analysis_source,
    write_pier_run_manifest,
    write_pier_summary,
)
from .render import render_session_analysis
from .scaffold import ScaffoldError, init_experiment_repo
from .sessionlog import load_events
from .storage import Layout


def _force_utf8_streams() -> None:
    """Make stdout/stderr UTF-8 so Rich glyphs do not crash on Windows."""

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
    help="Create, run, and analyze Pier jobs that evaluate GitHub Copilot CLI agents.",
    no_args_is_help=True,
)
console = Console()
err = Console(stderr=True)


@dataclass(frozen=True)
class ResolvedRun:
    path: Path
    selector: str


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    ok: bool
    detail: str = ""


@app.command()
def init(
    directory: Path = typer.Argument(..., help="Directory to create or update."),
    name: str | None = typer.Option(None, "--name", help="Project/package name."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing scaffolded files."),
) -> None:
    """Scaffold a standalone Pier experiment repository."""

    try:
        init_experiment_repo(directory, name=name, force=force)
    except ScaffoldError as exc:
        err.print(f"[red]Scaffold error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"[green]Initialized[/green] Pier experiment repository at {directory}")
    console.print("Next steps:")
    console.print(f"  cd {directory}")
    console.print("  uv sync")
    console.print("  uv run copilot-experiments validate")
    console.print("  uv run copilot-experiments run")


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
    console.print("[dim]validate:[/dim] uv run copilot-experiments validate")


@app.command()
def validate(
    name: str | None = typer.Argument(None, help="Only validate this Pier job name or file stem."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Validate Pier job configs, local paths, auth, and backend preflight checks."""

    root = Path(root or Path.cwd())
    specs = _require_pier_specs(root, name=name)
    checks = _validate_pier_specs(specs)
    _print_job_config_table(root, specs)
    _print_validation_checks(checks)
    if not all(check.ok for check in checks):
        raise typer.Exit(1)


@app.command()
def run(
    name: str | None = typer.Argument(None, help="Only run this Pier job name or file stem."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug-level Pier output.",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume the latest existing run for the selected Pier job when possible.",
    ),
) -> None:
    """Run Pier job config(s) defined under ``experiments/``."""

    root = Path(root or Path.cwd())
    specs = _require_pier_specs(root, name=name)
    checks = _validate_pier_specs(specs)
    failed_checks = [check for check in checks if not check.ok]
    if failed_checks:
        _print_validation_checks(checks)
        raise typer.Exit(1)

    try:
        auth = preflight_github_token()
    except AuthError as exc:
        err.print(f"[red]Authentication error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[dim]auth:[/dim] using GitHub token from {auth.source}")

    any_failures = False
    for spec in specs:
        prepared = prepare_pier_job_for_run(spec.config, resume=resume)
        if verbose:
            prepared.config.debug = True
        inject_copilot_token(prepared.config, auth.token)
        console.print(f"[bold]Running Pier job[/bold] {prepared.label}")
        if prepared.resumed:
            console.print(f"[dim]resume:[/dim] reusing existing Pier run {prepared.label}")
        else:
            console.print(
                f"[dim]run:[/dim] writing fresh run to "
                f"{Path(prepared.config.jobs_dir) / prepared.run_name}"
            )
        try:
            run_result = run_pier_job(prepared.config)
        except Exception as exc:
            err.print(f"[red]Pier job failed:[/red] {type(exc).__name__}: {exc}")
            any_failures = True
            continue
        write_pier_run_manifest(
            run_result.job_dir,
            job_name=prepared.requested_name,
            run_id=prepared.run_name,
        )
        summary = write_pier_summary(run_result.job_dir)
        _print_run_summary(summary)
        _warn_failed_pier_trials(run_result.job_dir)
        if summary.get("status") != "completed":
            any_failures = True
        console.print(f"[dim]results:[/dim] {run_result.job_dir}\n")

    if any_failures:
        raise typer.Exit(2)


@app.command(name="list")
def list_cmd(
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """List Pier job configs and concrete run selectors."""

    root = Path(root or Path.cwd())
    specs = discover_pier_job_configs(root)
    if specs:
        _print_job_config_table(root, specs)

    layout = Layout(root)
    runs = layout.iter_pier_jobs()
    if not runs:
        console.print("[dim]No runs yet.[/dim]")
        return

    table = Table(title="Pier runs")
    table.add_column("selector (job/run)", no_wrap=True)
    table.add_column("job")
    table.add_column("run")
    table.add_column("started")
    table.add_column("agents", justify="right")
    table.add_column("tasks", justify="right")
    table.add_column("trials", justify="right")
    table.add_column("success", justify="right")
    table.add_column("status")
    for job_dir in runs:
        summary = write_pier_summary(job_dir)
        sr = summary.get("overall_success_rate")
        table.add_row(
            str(summary.get("pier_job_id") or pier_job_label(job_dir)),
            str(summary.get("job") or "-"),
            str(summary.get("run_id") or "-"),
            (summary.get("started_at") or "")[:19],
            str(summary.get("n_agents") or 0),
            str(summary.get("n_tasks") or 0),
            str(summary.get("n_trials") or 0),
            "-" if sr is None else f"{sr * 100:.0f}%",
            str(summary.get("status") or "-"),
        )
    console.print(table)


@app.command()
def show(
    selector: str | None = typer.Argument(
        None,
        help="Pier run selector from `list`: job, run id/prefix, or job/run.",
    ),
    last: bool = typer.Option(False, "--last", help="Show the most recent stored Pier run."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Print a Pier run summary and per-agent comparison."""

    resolved = _resolve_or_exit(root, selector, last=last)
    summary = write_pier_summary(resolved.path)
    _print_run_summary(summary)
    console.print(f"\n[dim]{resolved.path / 'summary.md'}[/dim]")


@app.command()
def inspect(
    selector: str | None = typer.Argument(
        None,
        help="Pier run selector from `list`: job, run id/prefix, or job/run.",
    ),
    agent: str | None = typer.Option(None, "--agent", help="Agent selector."),
    task: str | None = typer.Option(None, "--task", help="Task selector."),
    trial: str | None = typer.Option(None, "--trial", help="Trial number or Pier trial name."),
    last: bool = typer.Option(False, "--last", help="Inspect the most recent stored Pier run."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Drill into a Pier run's agents, tasks, and trials."""

    resolved = _resolve_or_exit(root, selector, last=last)
    summary = write_pier_summary(resolved.path)
    console.print(f"[bold]Pier run[/bold]: {pier_job_label(resolved.path)}")
    console.print(f"[bold]summary[/bold]: {resolved.path / 'summary.json'}")

    rows = _matching_trial_rows(resolved.path, agent=agent, task=task, trial=trial)
    if not rows:
        err.print("[red]No matching Pier trials.[/red]")
        _print_trial_filter_hint()
        raise typer.Exit(1)

    _print_trials_table(rows, title=f"Trials in {pier_job_label(resolved.path)}")
    if len(rows) == 1:
        row = rows[0]
        console.print(f"\n[bold]selected[/bold]: {row['trial_dir']}")
        console.print(f"[bold]agent[/bold]: {row['agent']}")
        console.print(f"[bold]task[/bold]: {row['task']}")
        console.print(f"[bold]result[/bold]: {resolved.path / row['trial_dir'] / 'result.json'}")
        source_path, _label, source_kind, _otel_path = resolve_pier_trial_analysis_source(
            resolved.path, row["trial_dir"]
        )
        if source_path is not None:
            console.print(f"[bold]analysis source[/bold]: {source_kind} · {source_path}")
    elif agent or task or trial:
        console.print(
            "\n[yellow]Multiple trials match.[/yellow] Add more filters, for example "
            "`--agent`, `--task`, and `--trial`."
        )
    else:
        _print_run_summary(summary)


@app.command()
def analyze(
    selector: str | None = typer.Argument(
        None,
        help="Pier run selector from `list`: job, run id/prefix, or job/run.",
    ),
    agent: str | None = typer.Option(None, "--agent", help="Agent selector."),
    task: str | None = typer.Option(None, "--task", help="Task selector."),
    trial: str | None = typer.Option(None, "--trial", help="Trial number or Pier trial name."),
    file: Path | None = typer.Option(
        None, "--file", help="Analyze an events.jsonl file directly (ignores run filters)."
    ),
    otel_file: Path | None = typer.Option(
        None, "--otel-file", help="Optional Copilot OTel JSONL file to enrich analysis."
    ),
    last: bool = typer.Option(False, "--last", help="Analyze the most recent stored Pier run."),
    max_turns: int = typer.Option(0, "--max-turns", help="Limit timeline rows (0 = all)."),
    root: Path | None = typer.Option(None, "--root", help="Experiment repository root."),
) -> None:
    """Analyze a captured Copilot CLI session from a Pier trial."""

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

    resolved = _resolve_or_exit(root, selector, last=last, file_hint=True)
    rows = _matching_trial_rows(resolved.path, agent=agent, task=task, trial=trial)
    if not rows:
        err.print("[red]No matching Pier trials.[/red]")
        _print_trial_filter_hint()
        raise typer.Exit(1)
    if len(rows) > 1:
        err.print("[red]Multiple Pier trials match.[/red]")
        _print_trials_table(rows, title="Matching trials")
        err.print("[dim]Add --agent, --task, and/or --trial to select exactly one trial.[/dim]")
        raise typer.Exit(1)

    row = rows[0]
    source_path, label, source_kind, discovered_otel = resolve_pier_trial_analysis_source(
        resolved.path, row["trial_dir"]
    )
    if source_path is None:
        err.print(f"[red]No Copilot session log or trajectory found in[/red] {resolved.path}")
        diagnostic = describe_missing_pier_analysis_source(resolved.path, row["trial_dir"])
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


def _require_pier_specs(root: Path, *, name: str | None = None) -> list[PierJobSpec]:
    specs = discover_pier_job_configs(root, name=name)
    if specs:
        return specs
    target = f" matching {name!r}" if name else ""
    err.print(f"[red]No Pier job configs{target} found in[/red] {root / 'experiments'}")
    err.print("[dim]Create one with `copilot-experiments init` or `deepswe-import`.[/dim]")
    raise typer.Exit(1)


def _validate_pier_specs(specs: list[PierJobSpec]) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    for spec in specs:
        prefix = spec.name
        task_count = len(spec.config.tasks) + len(spec.config.datasets)
        agent_count = len(spec.config.agents)
        checks.append(
            ValidationCheck(
                f"{prefix}: agents",
                agent_count > 0,
                f"{agent_count} configured" if agent_count else "no agents configured",
            )
        )
        checks.append(
            ValidationCheck(
                f"{prefix}: tasks",
                task_count > 0,
                f"{task_count} configured" if task_count else "no tasks or datasets configured",
            )
        )
        for path in _local_task_paths(spec):
            checks.append(
                ValidationCheck(
                    f"{prefix}: path {path.name}",
                    path.exists(),
                    str(path) if path.exists() else f"missing: {path}",
                )
            )
        try:
            preflight_pier_backend(spec.config)
        except PierBackendPreflightError as exc:
            checks.append(ValidationCheck(f"{prefix}: backend", False, str(exc)))
        else:
            checks.append(ValidationCheck(f"{prefix}: backend", True, "preflight OK"))

    if all(check.ok for check in checks):
        try:
            auth = preflight_github_token()
        except AuthError as exc:
            checks.append(ValidationCheck("auth", False, str(exc)))
        else:
            checks.append(ValidationCheck("auth", True, f"using {auth.source}"))
    return checks


def _local_task_paths(spec: PierJobSpec) -> list[Path]:
    paths: list[Path] = []
    for item in [*spec.config.tasks, *spec.config.datasets]:
        path = getattr(item, "path", None)
        if path is not None:
            paths.append(Path(path))
    return paths


def _print_job_config_table(root: Path, specs: list[PierJobSpec]) -> None:
    table = Table(title="Pier job configs", show_edge=False)
    table.add_column("job")
    table.add_column("config")
    table.add_column("tasks", justify="right")
    table.add_column("agents", justify="right")
    for spec in specs:
        table.add_row(
            spec.name,
            str(spec.path.relative_to(root)) if spec.path.is_relative_to(root) else str(spec.path),
            str(len(spec.config.tasks) + len(spec.config.datasets)),
            str(len(spec.config.agents)),
        )
    console.print(table)


def _print_validation_checks(checks: list[ValidationCheck]) -> None:
    table = Table(title="Validation")
    table.add_column("")
    table.add_column("check")
    table.add_column("detail", style="dim")
    for check in checks:
        mark = "[green]✓[/green]" if check.ok else "[red]✗[/red]"
        table.add_row(mark, check.name, check.detail)
    console.print(table)


def _resolve_or_exit(
    root: Path | None,
    selector: str | None,
    *,
    last: bool,
    file_hint: bool = False,
) -> ResolvedRun:
    root = Path(root or Path.cwd())
    layout = Layout(root)
    resolved = _resolve_run(layout, last=last, selector=selector)
    if resolved is None:
        _print_run_not_found(selector, file_hint=file_hint)
        raise typer.Exit(1)
    return resolved


def _resolve_run(layout: Layout, *, last: bool, selector: str | None) -> ResolvedRun | None:
    if last:
        latest = layout.latest_pier_job()
        return ResolvedRun(latest, pier_job_label(latest)) if latest else None
    if selector is None:
        return None
    run = layout.find_pier_job(selector)
    return ResolvedRun(run, pier_job_label(run)) if run else None


def _print_run_not_found(selector: str | None, *, file_hint: bool = False) -> None:
    if selector:
        err.print(f"[red]Pier run not found:[/red] {selector!r}")
    else:
        err.print("[red]Pier run not found.[/red] Pass a run selector or --last.")
    hints = [
        "Use `copilot-experiments list` to copy a selector.",
        "Selectors look like `job-name/run-id`; `job-name` selects that job's latest run.",
    ]
    if file_hint:
        hints.append("Use `--file path/to/events.jsonl` to analyze a session log directly.")
    err.print("[dim]" + " ".join(hints) + "[/dim]")


def _matching_trial_rows(
    job_dir: Path,
    *,
    agent: str | None = None,
    task: str | None = None,
    trial: str | None = None,
) -> list[dict]:
    rows = iter_pier_trial_summaries(job_dir)
    filtered = []
    for index, row in enumerate(rows, start=1):
        if agent and not _matches_agent(row, agent):
            continue
        if task and task not in {row.get("task"), row.get("task_name")}:
            continue
        if trial and not _matches_trial(
            row,
            trial,
            overall_index=index,
            filtered=bool(agent or task),
        ):
            continue
        filtered.append(row)
    return filtered


def _matches_agent(row: dict, selector: str) -> bool:
    candidates = {str(row.get("agent") or ""), str(row.get("agent_name") or "")}
    return selector in candidates or any(candidate.startswith(selector) for candidate in candidates)


def _matches_trial(row: dict, selector: str, *, overall_index: int, filtered: bool) -> bool:
    if selector.isdigit():
        number = int(selector)
        if filtered:
            return row.get("trial_no") == number
        return overall_index == number
    return selector in {str(row.get("trial_dir") or ""), str(row.get("trial_name") or "")}


def _print_trials_table(rows: list[dict], *, title: str) -> None:
    table = Table(title=title)
    table.add_column("trial")
    table.add_column("agent")
    table.add_column("task")
    table.add_column("attempt", justify="right")
    table.add_column("status")
    table.add_column("success")
    table.add_column("analysis")
    for row in rows:
        table.add_row(
            str(row.get("trial_dir") or row.get("trial_name") or "-"),
            str(row.get("agent") or "-"),
            str(row.get("task") or "-"),
            str(row.get("trial_no") or "-"),
            str(row.get("status") or "-"),
            _yes_no(row.get("success")),
            "yes" if row.get("metrics") else "-",
        )
    console.print(table)


def _print_trial_filter_hint() -> None:
    err.print(
        "[dim]Use `copilot-experiments inspect <job/run>` to see agents, tasks, "
        "and trial names.[/dim]"
    )


def _warn_failed_pier_trials(job_dir: Path) -> None:
    failed = [row for row in iter_pier_trial_summaries(job_dir) if row.get("status") != "ok"]
    if not failed:
        return
    table = Table(title="Failed Pier trials")
    table.add_column("trial")
    table.add_column("agent")
    table.add_column("task")
    table.add_column("status")
    table.add_column("error")
    for row in failed:
        table.add_row(
            str(row.get("trial_name") or "-"),
            str(row.get("agent") or "-"),
            str(row.get("task") or "-"),
            str(row.get("status") or "-"),
            str(row.get("error") or "-"),
        )
    console.print(table)


def _print_run_summary(summary: dict) -> None:
    console.print(
        f"[bold]{summary['job']}[/bold] · run [cyan]{summary['run_id']}[/cyan] · "
        f"status={summary.get('status', '-')}"
    )
    console.print(
        f"agents={summary['n_agents']} tasks={summary.get('n_tasks', 0)} "
        f"trials={summary['n_trials']} success={_pct(summary.get('overall_success_rate'))}"
    )
    multitask = summary.get("n_tasks", 0) > 1
    table = Table(title="Agents")
    table.add_column("agent")
    table.add_column("model")
    table.add_column("effort")
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
    for agent in summary["agents"]:
        row = [
            agent["name"],
            agent.get("model") or "-",
            agent.get("reasoning_effort") or "-",
        ]
        if multitask:
            row.append(str(agent.get("n_tasks", "-")))
        row.append(str(agent["n_trials"]))
        row.append(_pct(agent.get("success_rate")))
        if multitask:
            row.append(_pct(agent.get("mean_resolved_rate")))
            row.append(_pct(agent.get("resolved_at_k_rate")))
        row += [
            _num(agent.get("avg_duration_s")),
            _num(agent.get("avg_turns")),
            _num(agent.get("avg_tool_calls")),
            _num(agent.get("avg_tool_failures")),
            _num(agent.get("avg_total_tokens")),
            _aiu(agent.get("avg_aiu")),
            _aiu(agent.get("aiu_per_solve")),
        ]
        table.add_row(*row)
    console.print(table)
    total_aiu = summary.get("total_aiu")
    if total_aiu is not None:
        console.print(f"[dim]total cost:[/dim] {_aiu(total_aiu)} AIU")


def _yes_no(value: object) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def _num(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _aiu(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.3f}" if float(value) < 1 else f"{float(value):,.2f}"


if __name__ == "__main__":  # pragma: no cover
    app()
