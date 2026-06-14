"""End-to-end runner tests using the MockInvoker (no real Copilot needed)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from copilot_experiments import Experiment, run_experiment
from copilot_experiments.invoker import MockInvoker
from copilot_experiments.storage import Layout


def solve(workspace: Path) -> None:
    """A MockInvoker solver that completes the sample task."""
    (workspace / "SOLVED").write_text("done\n", encoding="utf-8")


def test_run_experiment_dry_run_produces_artifacts(repo_root: Path, experiment: Experiment):
    run = run_experiment(experiment, root=repo_root, dry_run=True)

    layout = Layout(repo_root)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    assert (run_dir / "run.json").exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "summary.md").exists()

    # alpha has 1 trial, beta has 2 -> 3 trial dirs total.
    trial_dirs = list((run_dir / "variants").glob("*/trials/*"))
    assert len(trial_dirs) == 3
    for td in trial_dirs:
        assert (td / "meta.json").exists()
        assert (td / "metrics.json").exists()
        assert (td / "analysis.json").exists()
        assert (td / "events.jsonl").exists()
        assert (td / "prompt.md").exists()


def test_run_experiment_without_solver_fails_verify(repo_root: Path, experiment: Experiment):
    run = run_experiment(experiment, root=repo_root, dry_run=True)
    successes = [t.success for vr in run.variants for t in vr.trials]
    assert all(s is False for s in successes)


def test_run_experiment_with_solver_succeeds(repo_root: Path, experiment: Experiment):
    invoker = MockInvoker(solver=solve)
    run = run_experiment(
        experiment,
        root=repo_root,
        invoker=invoker,
        session_state_root=repo_root / ".session-state",
    )
    successes = [t.success for vr in run.variants for t in vr.trials]
    assert all(s is True for s in successes)

    # A diff should have been captured for the new SOLVED file.
    layout = Layout(repo_root)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    a_diff = (run_dir / "variants" / "alpha" / "trials" / "001" / "workspace.diff")
    assert "SOLVED" in a_diff.read_text(encoding="utf-8")


def test_run_experiment_populates_index(repo_root: Path, experiment: Experiment):
    run = run_experiment(experiment, root=repo_root, dry_run=True)
    layout = Layout(repo_root)
    conn = sqlite3.connect(str(layout.index_db))
    try:
        runs = conn.execute("SELECT run_id FROM runs").fetchall()
        variants = conn.execute("SELECT variant_slug FROM variants").fetchall()
        trials = conn.execute("SELECT trial_no FROM trials").fetchall()
    finally:
        conn.close()
    assert [r[0] for r in runs] == [run.run_id]
    assert {v[0] for v in variants} == {"alpha", "beta"}
    assert len(trials) == 3
