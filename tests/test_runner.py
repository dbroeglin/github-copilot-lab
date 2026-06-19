"""End-to-end runner tests using the MockInvoker (no real Copilot needed)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from copilot_experiments import Experiment, Task, Variant, dry_run_experiment, run_experiment
from copilot_experiments.invoker import MockInvoker
from copilot_experiments.models import ExperimentRun, TaskResult, TrialResult, VariantResult
from copilot_experiments.storage import Layout


def solve(workspace: Path) -> None:
    """A MockInvoker solver that completes the sample task."""
    (workspace / "SOLVED").write_text("done\n", encoding="utf-8")


def _mock_run(experiment: Experiment, repo_root: Path, **kwargs):
    """Run the experiment with the mock invoker, persisting artifacts under repo_root."""
    return run_experiment(
        experiment,
        root=repo_root,
        invoker=MockInvoker(**kwargs),
        session_state_root=repo_root / ".session-state",
    )


def test_run_experiment_produces_artifacts(repo_root: Path, experiment: Experiment):
    run = _mock_run(experiment, repo_root)

    layout = Layout(repo_root)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    assert (run_dir / "run.json").exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "summary.md").exists()

    # alpha has 1 trial, beta has 2 -> 3 trial dirs total (single task suite).
    trial_dirs = list((run_dir / "variants").glob("*/tasks/*/trials/*"))
    assert len(trial_dirs) == 3
    for td in trial_dirs:
        assert (td / "meta.json").exists()
        assert (td / "metrics.json").exists()
        assert (td / "analysis.json").exists()
        assert (td / "events.jsonl").exists()
        assert (td / "stdout.txt").exists()
        assert (td / "prompt.md").exists()
        # Copilot's bulky --log-dir debug log must never be persisted under results/.
        assert not (td / "logs").exists()


def test_run_experiment_without_solver_fails_verify(repo_root: Path, experiment: Experiment):
    run = _mock_run(experiment, repo_root)
    successes = [t.success for vr in run.variants for t in vr.all_trials]
    assert all(s is False for s in successes)


def test_run_experiment_with_solver_succeeds(repo_root: Path, experiment: Experiment):
    run = _mock_run(experiment, repo_root, solver=solve)
    successes = [t.success for vr in run.variants for t in vr.all_trials]
    assert all(s is True for s in successes)

    # The on-disk artifacts must corroborate success end-to-end.
    layout = Layout(repo_root)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    trial = run_dir / "variants" / "alpha" / "tasks" / "task-001" / "trials" / "001"

    diff = (trial / "workspace.diff").read_text(encoding="utf-8")
    assert "SOLVED" in diff and diff.strip() != ""

    verify = json.loads((trial / "verify.json").read_text(encoding="utf-8"))
    assert verify["success"] is True and verify["exit_code"] == 0

    meta = json.loads((trial / "meta.json").read_text(encoding="utf-8"))
    assert meta["success"] is True


def test_run_experiment_forwards_progress_per_trial(repo_root: Path, experiment: Experiment):
    msgs: list[str] = []
    _mock_run(experiment, repo_root, solver=solve)  # warm-up run (no progress)
    msgs.clear()
    run_experiment(
        experiment,
        root=repo_root,
        invoker=MockInvoker(solver=solve),
        session_state_root=repo_root / ".session-state",
        progress=msgs.append,
    )

    # Per-variant header plus a distinct, tagged set of phase lines per trial.
    assert any(m.startswith("variant beta: 2 trial(s)") for m in msgs)
    for tag in ("alpha/task-001/001", "beta/task-001/001", "beta/task-001/002"):
        assert any(m.startswith(f"[{tag}] invoking copilot") for m in msgs)
        assert any(m.startswith(f"[{tag}] session log:") for m in msgs)
        assert any(m.startswith(f"[{tag}] verify:") for m in msgs)


def test_run_experiment_populates_index(repo_root: Path, experiment: Experiment):
    run = _mock_run(experiment, repo_root)
    layout = Layout(repo_root)
    conn = sqlite3.connect(str(layout.index_db))
    try:
        runs = conn.execute("SELECT run_id FROM runs").fetchall()
        variants = conn.execute("SELECT variant_slug FROM variants").fetchall()
        trials = conn.execute("SELECT trial_no, task_slug FROM trials").fetchall()
    finally:
        conn.close()
    assert [r[0] for r in runs] == [run.run_id]
    assert {v[0] for v in variants} == {"alpha", "beta"}
    assert len(trials) == 3
    # Single-task sugar still produces exactly one task slug across all trials.
    assert {t[1] for t in trials} == {"task-001"}


def test_run_multitask_experiment(repo_root: Path, multitask_experiment: Experiment):
    run = _mock_run(multitask_experiment, repo_root, solver=solve)
    layout = Layout(repo_root)
    run_dir = layout.run_dir(multitask_experiment.slug, run.run_id)

    # Per-task dirs exist for every variant: 2 variants x 2 tasks = 4 task dirs.
    task_dirs = sorted(p.name for p in (run_dir / "variants").glob("*/tasks/*"))
    assert task_dirs == ["first-task", "first-task", "second-task", "second-task"]

    # Each variant result nests two tasks; suite measures reflect all-pass solver.
    for vr in run.variants:
        assert len(vr.tasks) == 2
        assert vr.mean_resolved_rate == 1.0
        assert vr.resolved_at_k_rate == 1.0

    # Summary records the task axis and the two suite measures side by side.
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["n_tasks"] == 2
    for v in summary["variants"]:
        assert v["n_tasks"] == 2
        assert v["mean_resolved_rate"] == 1.0
        assert v["resolved_at_k_rate"] == 1.0
        assert {t["task"] for t in v["tasks"]} == {"first-task", "second-task"}

    # Index carries the task dimension.
    conn = sqlite3.connect(str(layout.index_db))
    try:
        tasks = conn.execute("SELECT DISTINCT task_slug FROM tasks").fetchall()
        trials = conn.execute("SELECT task_slug FROM trials").fetchall()
    finally:
        conn.close()
    assert {t[0] for t in tasks} == {"first-task", "second-task"}
    # alpha: 2 tasks x 1 trial + beta: 2 tasks x 2 trials = 6 trials.
    assert len(trials) == 6


def test_dry_run_validates_and_leaves_nothing_behind(repo_root: Path, experiment: Experiment):
    report = dry_run_experiment(experiment, root=repo_root)

    # Every plumbing stage reports OK...
    assert report.ok, [(c.name, c.detail) for c in report.checks if not c.ok]
    assert {c.name for c in report.checks} >= {
        "workspace provisioned",
        "session log captured",
        "metrics parsed",
        "analysis written",
        "workspace diff captured",
        "verify ran",
        "run summary written",
        "indexed",
    }

    # ...and absolutely nothing is persisted under the repo root.
    assert not (repo_root / "results").exists()
    assert not (repo_root / ".session-state").exists()


def test_dry_run_flags_broken_plumbing(repo_root: Path, experiment: Experiment):
    # An invoker that leaves the workspace untouched (no note, no solver) yields an
    # empty diff -- exactly the failure mode the MAX_PATH bug produced.
    report = dry_run_experiment(experiment, root=repo_root, invoker=MockInvoker(leave_note=False))

    assert report.ok is False
    diff_check = next(c for c in report.checks if c.name == "workspace diff captured")
    assert diff_check.ok is False
    # Still leaves nothing behind, even on failure.
    assert not (repo_root / "results").exists()


# --------------------------------------------------------------------------- #
# Harness vs. experiment failures: status enum + roll-up
# --------------------------------------------------------------------------- #
def test_clean_run_marks_trials_ok_and_run_completed(repo_root: Path, experiment: Experiment):
    run = _mock_run(experiment, repo_root, solver=solve)
    assert run.status == "completed"
    assert all(t.status == "ok" for t in run.all_trials)
    assert run.n_failed_trials == 0


def test_copilot_nonzero_exit_is_a_harness_failure(repo_root: Path, experiment: Experiment):
    # Copilot was invoked but exited non-zero (the auth-failure scenario): every trial
    # is flagged ``copilot_failed`` and the run rolls up to ``failed`` -- not a clean
    # "0% success" that hides a broken harness.
    run = _mock_run(experiment, repo_root, exit_code=1)
    assert run.status == "failed"
    assert all(t.status == "copilot_failed" for t in run.all_trials)
    for vr in run.variants:
        for t in vr.all_trials:
            assert t.error and "exited 1" in t.error
            assert t.error_artifact == "stdout.txt"

    # The status is durable on disk.
    layout = Layout(repo_root)
    meta_path = layout.trial_dir(experiment.slug, run.run_id, "alpha", "task-001", 1) / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == "copilot_failed"


def test_harness_error_on_provision_failure_still_records_trial(repo_root: Path):
    # A missing fixture makes provisioning raise: that is a harness error, the run
    # continues, and a trial record (status=harness_error) is still written.
    broken = Experiment(
        name="Broken",
        task=Task(prompt="x", fixture="fixtures/does_not_exist"),
        variants=[Variant(name="alpha")],
    )
    run = _mock_run(broken, repo_root)
    assert run.status == "failed"
    trial = run.all_trials[0]
    assert trial.status == "harness_error"
    assert "WorkspaceError" in (trial.error or "")

    layout = Layout(repo_root)
    meta = layout.trial_dir(broken.slug, run.run_id, "alpha", "task-001", 1) / "meta.json"
    assert json.loads(meta.read_text(encoding="utf-8"))["status"] == "harness_error"


def test_partial_run_when_some_variants_fail(repo_root: Path):
    # One variant errors in the harness while the others run cleanly -> ``partial``.
    failing = Variant(name="alpha")
    failing_solver_run = ExperimentRun(
        run_id="r",
        experiment_slug="s",
        experiment_name="n",
        started_at="t",
        variants=[
            VariantResult(
                variant=failing,
                tasks=[
                    TaskResult(
                        task_slug="task-001",
                        trials=[
                            TrialResult(
                                trial_no=1, session_id="a", exit_code=0, duration_s=1.0, status="ok"
                            ),
                            TrialResult(
                                trial_no=2,
                                session_id="b",
                                exit_code=1,
                                duration_s=1.0,
                                status="copilot_failed",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    assert failing_solver_run.rollup_status() == "partial"
    assert failing_solver_run.n_failed_trials == 1


def test_token_injected_into_env_and_flagged_secret(repo_root: Path, experiment: Experiment):
    # The resolved token reaches each trial's env_overrides and the variable carrying
    # it is added to copilot's --secret-env-vars, but never to a stored artifact.
    seen: list = []

    class RecordingInvoker(MockInvoker):
        def run(self, inv):  # noqa: ANN001 - test double
            seen.append(inv)
            return super().run(inv)

    run = run_experiment(
        experiment,
        root=repo_root,
        invoker=RecordingInvoker(solver=solve),
        session_state_root=repo_root / ".session-state",
        github_token="secret-token-123",
    )
    assert run.status == "completed"
    assert seen, "invoker was never called"
    for inv in seen:
        assert inv.env_overrides.get("COPILOT_GITHUB_TOKEN") == "secret-token-123"
        assert "COPILOT_GITHUB_TOKEN" in inv.secret_env_names
        assert inv.share_path is not None and inv.share_path.name == "session.md"

    # The token must not have leaked into any persisted artifact.
    layout = Layout(repo_root)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    for path in run_dir.rglob("*"):
        if path.is_file():
            assert "secret-token-123" not in path.read_text(encoding="utf-8", errors="ignore")
