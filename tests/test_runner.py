"""End-to-end runner tests using the MockInvoker (no real Copilot needed)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from copilot_experiments import Experiment, dry_run_experiment, run_experiment
from copilot_experiments.invoker import MockInvoker
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

    # alpha has 1 trial, beta has 2 -> 3 trial dirs total.
    trial_dirs = list((run_dir / "variants").glob("*/trials/*"))
    assert len(trial_dirs) == 3
    for td in trial_dirs:
        assert (td / "meta.json").exists()
        assert (td / "metrics.json").exists()
        assert (td / "analysis.json").exists()
        assert (td / "events.jsonl").exists()
        assert (td / "prompt.md").exists()
        # Copilot's bulky --log-dir debug log must never be persisted under results/.
        assert not (td / "logs").exists()


def test_run_experiment_without_solver_fails_verify(repo_root: Path, experiment: Experiment):
    run = _mock_run(experiment, repo_root)
    successes = [t.success for vr in run.variants for t in vr.trials]
    assert all(s is False for s in successes)


def test_run_experiment_with_solver_succeeds(repo_root: Path, experiment: Experiment):
    run = _mock_run(experiment, repo_root, solver=solve)
    successes = [t.success for vr in run.variants for t in vr.trials]
    assert all(s is True for s in successes)

    # The on-disk artifacts must corroborate success end-to-end.
    layout = Layout(repo_root)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    trial = run_dir / "variants" / "alpha" / "trials" / "001"

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
    for tag in ("alpha/001", "beta/001", "beta/002"):
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
        trials = conn.execute("SELECT trial_no FROM trials").fetchall()
    finally:
        conn.close()
    assert [r[0] for r in runs] == [run.run_id]
    assert {v[0] for v in variants} == {"alpha", "beta"}
    assert len(trials) == 3


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
