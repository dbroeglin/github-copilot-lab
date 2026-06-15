"""Tests for the SQLite index reindex/list operations."""

from __future__ import annotations

from pathlib import Path

from copilot_experiments import Experiment, run_experiment
from copilot_experiments.index import connect, list_runs, reindex
from copilot_experiments.invoker import MockInvoker
from copilot_experiments.storage import Layout


def test_reindex_rebuilds_from_filesystem(repo_root: Path, experiment: Experiment):
    run = run_experiment(
        experiment,
        root=repo_root,
        invoker=MockInvoker(),
        session_state_root=repo_root / ".session-state",
    )
    layout = Layout(repo_root)

    # Delete the DB and rebuild it purely from results/.
    layout.index_db.unlink()
    count = reindex(layout)
    assert count == 1

    rows = list_runs(layout)
    assert any(r["run_id"] == run.run_id for r in rows)


def test_index_persists_cost_columns(repo_root: Path, experiment: Experiment):
    run_experiment(
        experiment,
        root=repo_root,
        invoker=MockInvoker(),
        session_state_root=repo_root / ".session-state",
    )
    layout = Layout(repo_root)
    reindex(layout)

    conn = connect(layout.index_db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(trials)")}
        assert {"aiu", "cache_read_tokens", "lines_added", "peak_context_tokens",
                "n_requests", "n_compactions"} <= cols
        row = conn.execute(
            "SELECT aiu, cache_read_tokens, total_tokens, n_requests, lines_added "
            "FROM trials LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    # The MockInvoker emits a self-consistent session.shutdown (1.9275 AIU).
    assert row["aiu"] == 1.9275
    assert row["cache_read_tokens"] == 12_000
    assert row["n_requests"] == 4

