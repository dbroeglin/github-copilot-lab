"""Tests for the SQLite index reindex/list operations."""

from __future__ import annotations

from pathlib import Path

from copilot_experiments import Experiment, run_experiment
from copilot_experiments.index import list_runs, reindex
from copilot_experiments.storage import Layout


def test_reindex_rebuilds_from_filesystem(repo_root: Path, experiment: Experiment):
    run = run_experiment(experiment, root=repo_root, dry_run=True)
    layout = Layout(repo_root)

    # Delete the DB and rebuild it purely from results/.
    layout.index_db.unlink()
    count = reindex(layout)
    assert count == 1

    rows = list_runs(layout)
    assert any(r["run_id"] == run.run_id for r in rows)
