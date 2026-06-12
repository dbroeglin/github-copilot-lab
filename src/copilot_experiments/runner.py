"""Orchestrate running an experiment: variants x trials -> result artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ._util import iso, new_run_id, new_session_id, utcnow, write_json, write_text
from .index import connect, index_run_dir
from .invoker import CopilotInvoker, Invocation, Invoker, MockInvoker
from .models import Experiment, ExperimentRun, TrialResult, Variant, VariantResult
from .report import build_summary, summary_markdown
from .sessionlog import copy_events, load_events, parse_metrics
from .storage import Layout
from .workspace import capture_diff, provision, run_shell


def _git_head(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def run_experiment(
    experiment: Experiment,
    *,
    root: Path | None = None,
    invoker: Invoker | None = None,
    dry_run: bool = False,
    session_state_root: Path | None = None,
    copilot_binary: str = "copilot",
) -> ExperimentRun:
    """Run every variant x trial of ``experiment`` and write result artifacts.

    Parameters
    ----------
    root:
        Experiment repository root (defaults to the current directory). Results
        are written under ``root/results``.
    invoker:
        Strategy used to invoke Copilot. Defaults to :class:`CopilotInvoker`,
        or :class:`MockInvoker` when ``dry_run`` is true.
    dry_run:
        Use the mock invoker (no Copilot credits / network needed).
    session_state_root:
        Where Copilot session state lives. Defaults to ``~/.copilot/session-state``.
        Overridden automatically for dry-runs so synthetic events are isolated.
    """
    root = Path(root or Path.cwd())
    layout = Layout(root)

    if invoker is None:
        invoker = MockInvoker() if dry_run else CopilotInvoker(binary=copilot_binary)

    run_id = new_run_id()
    run_dir = layout.run_dir(experiment.slug, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    if session_state_root is None and dry_run:
        session_state_root = run_dir / ".session-state"

    run = ExperimentRun(
        run_id=run_id,
        experiment_slug=experiment.slug,
        experiment_name=experiment.name,
        experiment_description=experiment.description,
        started_at=iso(utcnow()),
        git_base=_git_head(root),
    )

    for variant in experiment.variants:
        vr = _run_variant(experiment, variant, layout, run_id, invoker, session_state_root)
        run.variants.append(vr)
        write_json(
            layout.variant_dir(experiment.slug, run_id, variant.slug) / "variant.json",
            variant.stored(),
        )

    run.finished_at = iso(utcnow())
    run.status = "completed"

    # Write run manifest, summary, and report.
    write_json(run_dir / "run.json", run.model_dump(mode="json"))
    summary = build_summary(run)
    write_json(run_dir / "summary.json", summary)
    write_text(run_dir / "summary.md", summary_markdown(summary, experiment.description))

    # Update the SQLite index.
    conn = connect(layout.index_db)
    try:
        index_run_dir(conn, run_dir)
    finally:
        conn.close()

    return run


def _run_variant(
    experiment: Experiment,
    variant: Variant,
    layout: Layout,
    run_id: str,
    invoker: Invoker,
    session_state_root: Path | None,
) -> VariantResult:
    vr = VariantResult(variant=variant)
    for trial_no in range(1, variant.trials + 1):
        vr.trials.append(
            _run_trial(experiment, variant, trial_no, layout, run_id, invoker, session_state_root)
        )
    return vr


def _run_trial(
    experiment: Experiment,
    variant: Variant,
    trial_no: int,
    layout: Layout,
    run_id: str,
    invoker: Invoker,
    session_state_root: Path | None,
) -> TrialResult:
    task = experiment.task
    trial_dir = layout.trial_dir(experiment.slug, run_id, variant.slug, trial_no)
    trial_dir.mkdir(parents=True, exist_ok=True)
    workspace = trial_dir / "workspace"
    log_dir = trial_dir / "logs"
    stdout_path = trial_dir / "stdout.jsonl"

    write_text(trial_dir / "prompt.md", task.prompt)
    provision(task, workspace, layout.root)

    session_id = new_session_id()
    inv = Invocation(
        prompt=task.prompt,
        workspace=workspace,
        session_id=session_id,
        variant=variant,
        log_dir=log_dir,
        stdout_path=stdout_path,
        session_state_root=session_state_root or _default_session_state_root(),
    )
    result = invoker.run(inv)

    # Collect the session events and parse metrics.
    copy_events(session_id, trial_dir / "events.jsonl", inv.session_state_root)
    events = load_events(trial_dir / "events.jsonl")
    metrics = parse_metrics(events)
    if metrics.duration_s is None:
        metrics.duration_s = round(result.duration_s, 3)

    # Capture what changed in the workspace.
    write_text(trial_dir / "workspace.diff", capture_diff(workspace))

    # Run the verification command, if any.
    success: bool | None = None
    if task.verify:
        code, output = run_shell(task.verify, workspace)
        success = code == 0
        write_json(
            trial_dir / "verify.json",
            {"command": task.verify, "exit_code": code, "success": success, "output": output},
        )

    trial = TrialResult(
        trial_no=trial_no,
        session_id=session_id,
        exit_code=result.exit_code,
        duration_s=round(result.duration_s, 3),
        success=success,
        metrics=metrics,
    )
    write_json(trial_dir / "meta.json", {
        "trial_no": trial_no,
        "session_id": session_id,
        "exit_code": result.exit_code,
        "duration_s": trial.duration_s,
        "success": success,
        "workspace": str(workspace),
    })
    write_json(trial_dir / "metrics.json", metrics.model_dump(mode="json"))
    return trial


def _default_session_state_root() -> Path:
    from .sessionlog import session_state_root

    return session_state_root()
