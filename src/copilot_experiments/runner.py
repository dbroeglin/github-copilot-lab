"""Orchestrate running an experiment: variants x trials -> result artifacts."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ._util import (
    force_rmtree,
    iso,
    new_run_id,
    new_session_id,
    read_json,
    utcnow,
    write_json,
    write_text,
)
from .analysis import analyze_events
from .index import connect, index_run_dir
from .invoker import CopilotInvoker, Invocation, Invoker, MockInvoker
from .models import (
    DryRunCheck,
    DryRunReport,
    Experiment,
    ExperimentRun,
    TrialResult,
    Variant,
    VariantResult,
)
from .report import build_summary, summary_markdown
from .sessionlog import copy_events, load_events, parse_metrics
from .storage import Layout
from .workspace import capture_diff, provision, run_shell


def _git_head(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _report(progress: Callable[[str], None] | None, msg: str) -> None:
    """Forward a human-readable progress line to ``progress`` if one is set."""
    if progress is not None:
        progress(msg)


def run_experiment(
    experiment: Experiment,
    *,
    root: Path | None = None,
    invoker: Invoker | None = None,
    results_root: Path | None = None,
    session_state_root: Path | None = None,
    copilot_binary: str = "copilot",
    progress: Callable[[str], None] | None = None,
    copilot_stream: Callable[[str], None] | None = None,
) -> ExperimentRun:
    """Run every variant x trial of ``experiment`` and write result artifacts.

    Parameters
    ----------
    root:
        Experiment repository root (defaults to the current directory). Fixtures
        and experiment definitions are read from here.
    invoker:
        Strategy used to invoke Copilot. Defaults to :class:`CopilotInvoker`.
        Tests pass a :class:`MockInvoker`; :func:`dry_run_experiment` uses one too.
    results_root:
        Where run artifacts are written. Defaults to ``root/results``. Pointed at a
        throwaway temp dir by :func:`dry_run_experiment` so nothing is persisted.
    session_state_root:
        Where Copilot session state lives. Defaults to ``~/.copilot/session-state``.
    progress:
        Optional sink for high-level per-trial phase messages (``--verbose``).
    copilot_stream:
        Optional sink for Copilot's live output, one rendered line at a time
        (``--verbose``). Only used when the default :class:`CopilotInvoker` is built.
    """
    root = Path(root or Path.cwd()).resolve()
    layout = Layout(root, results_root=results_root)

    if invoker is None:
        invoker = CopilotInvoker(binary=copilot_binary, stream=copilot_stream)

    run_id = new_run_id()
    run_dir = layout.run_dir(experiment.slug, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    run = ExperimentRun(
        run_id=run_id,
        experiment_slug=experiment.slug,
        experiment_name=experiment.name,
        experiment_description=experiment.description,
        started_at=iso(utcnow()),
        git_base=_git_head(root),
    )

    for variant in experiment.variants:
        _report(progress, f"variant {variant.slug}: {variant.trials} trial(s)")
        vr = _run_variant(
            experiment, variant, layout, run_id, invoker, session_state_root, progress
        )
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
    progress: Callable[[str], None] | None = None,
) -> VariantResult:
    vr = VariantResult(variant=variant)
    for trial_no in range(1, variant.trials + 1):
        vr.trials.append(
            _run_trial(
                experiment,
                variant,
                trial_no,
                layout,
                run_id,
                invoker,
                session_state_root,
                progress,
            )
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
    progress: Callable[[str], None] | None = None,
) -> TrialResult:
    task = experiment.task
    tag = f"{variant.slug}/{trial_no:03d}"
    trial_dir = layout.trial_dir(experiment.slug, run_id, variant.slug, trial_no)
    trial_dir.mkdir(parents=True, exist_ok=True)
    workspace = trial_dir / "workspace"
    stdout_path = trial_dir / "stdout.jsonl"
    # Copilot's own --log-dir debug log is large (megabytes) and echoes masked auth
    # material; keep it in an ephemeral temp dir so it never lands under results/.
    # The session events.jsonl (copied below) is our real data source -- see ADR-0010.
    log_dir = Path(tempfile.mkdtemp(prefix="copilot-log-"))

    try:
        write_text(trial_dir / "prompt.md", task.prompt)
        provision(task, workspace, layout.root)
        _report(progress, f"[{tag}] workspace provisioned -> {workspace}")

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
        _report(progress, f"[{tag}] invoking copilot (session {session_id})")
        result = invoker.run(inv)
        _report(
            progress,
            f"[{tag}] copilot exited {result.exit_code} in {result.duration_s:.1f}s",
        )

        # Collect the session events and parse metrics.
        copy_events(session_id, trial_dir / "events.jsonl", inv.session_state_root)
        events = load_events(trial_dir / "events.jsonl")
        metrics = parse_metrics(events)
        if metrics.duration_s is None:
            metrics.duration_s = round(result.duration_s, 3)
        _report(
            progress,
            f"[{tag}] session log: {len(events)} events -> {metrics.n_turns} turns, "
            f"{metrics.n_tool_calls} tool calls, {metrics.total_tokens or 0} tokens",
        )

        # Build and persist the richer session analysis (timeline, tool histogram).
        analysis = analyze_events(events)
        write_json(trial_dir / "analysis.json", analysis.model_dump(mode="json"))

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
            _report(progress, f"[{tag}] verify: {'pass' if success else 'fail'} (exit {code})")

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
    finally:
        force_rmtree(log_dir)


def _default_session_state_root() -> Path:
    from .sessionlog import session_state_root

    return session_state_root()


# --------------------------------------------------------------------------- #
# Dry-run: validate the whole pipeline, persist nothing
# --------------------------------------------------------------------------- #
def dry_run_experiment(
    experiment: Experiment,
    *,
    root: Path | None = None,
    invoker: Invoker | None = None,
) -> DryRunReport:
    """Validate the full run pipeline without leaving anything behind.

    Runs every stage with a mock invoker inside a throwaway temp directory,
    asserts that each stage produced its artifact, then deletes the temp dir.
    Fixtures are still read from ``root``; only the *outputs* are redirected.
    Returns a :class:`DryRunReport` -- nothing is persisted under ``root``.
    """
    root = Path(root or Path.cwd())
    tmp = Path(tempfile.mkdtemp(prefix="copilot-exp-dryrun-"))
    try:
        run = run_experiment(
            experiment,
            root=root,
            invoker=invoker or MockInvoker(),
            results_root=tmp,
            session_state_root=tmp / ".session-state",
        )
        layout = Layout(root, results_root=tmp)
        checks = _validate_plumbing(layout, experiment, run)
        return DryRunReport(experiment=experiment.name, checks=checks)
    finally:
        force_rmtree(tmp)


def _check(name: str, ok: bool, detail: str = "") -> DryRunCheck:
    return DryRunCheck(name=name, ok=ok, detail=detail)


def _validate_plumbing(
    layout: Layout, experiment: Experiment, run: ExperimentRun
) -> list[DryRunCheck]:
    """Inspect the on-disk artifacts of the first trial (and the run) and report
    whether each pipeline stage actually did its job."""
    checks: list[DryRunCheck] = []
    variant = experiment.variants[0]
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    trial_dir = layout.trial_dir(experiment.slug, run.run_id, variant.slug, 1)
    workspace = trial_dir / "workspace"

    # 1. Workspace provisioned with a git baseline.
    head = _git_head(workspace) if workspace.exists() else None
    checks.append(
        _check(
            "workspace provisioned",
            workspace.exists() and head is not None,
            f"git baseline {head[:10]}" if head else "no workspace / git HEAD",
        )
    )

    # 2. Session log captured and parseable.
    events_path = trial_dir / "events.jsonl"
    n_events = 0
    if events_path.exists():
        try:
            n_events = len(load_events(events_path))
        except Exception:  # pragma: no cover - defensive
            n_events = 0
    checks.append(
        _check("session log captured", events_path.exists() and n_events >= 1, f"{n_events} events")
    )

    # 3. Metrics parsed from the session log.
    metrics_path = trial_dir / "metrics.json"
    n_turns = int(read_json(metrics_path).get("n_turns") or 0) if metrics_path.exists() else 0
    checks.append(
        _check("metrics parsed", metrics_path.exists() and n_turns >= 1, f"{n_turns} turns")
    )

    # 4. Session analysis written.
    checks.append(_check("analysis written", (trial_dir / "analysis.json").exists()))

    # 5. Workspace diff captured and non-empty -- this is what caught the MAX_PATH bug.
    diff_path = trial_dir / "workspace.diff"
    diff = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
    checks.append(
        _check(
            "workspace diff captured",
            diff.strip() != "",
            f"{len(diff)} bytes" if diff.strip() else "empty diff (invoker changed nothing?)",
        )
    )

    # 6. Verification ran (we only assert it ran, not that it passed).
    if experiment.task.verify:
        checks.append(_check("verify ran", (trial_dir / "verify.json").exists()))

    # 7. Run-level summary written.
    checks.append(
        _check(
            "run summary written",
            (run_dir / "summary.json").exists() and (run_dir / "summary.md").exists(),
        )
    )

    # 8. Run recorded in the SQLite index.
    indexed = False
    if layout.index_db.exists():
        conn = connect(layout.index_db)
        try:
            row = conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone()
            indexed = row is not None
        finally:
            conn.close()
    checks.append(_check("indexed", indexed))

    return checks
