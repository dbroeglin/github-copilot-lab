"""Tests for the filesystem Layout helpers."""

from __future__ import annotations

import json
from pathlib import Path

from copilot_experiments.storage import Layout


def _make_run(root: Path, exp: str, run_id: str) -> Path:
    rd = root / "results" / exp / run_id
    rd.mkdir(parents=True)
    (rd / "run.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    return rd


def test_layout_paths(tmp_path: Path):
    layout = Layout(tmp_path)
    assert layout.results_dir == tmp_path / "results"
    assert layout.index_db == tmp_path / "results" / "index.db"
    trial = layout.trial_dir("exp", "run1", "v1", 3)
    assert trial.name == "003"
    assert trial.parent.parent.name == "v1"


def test_find_and_latest_run(tmp_path: Path):
    _make_run(tmp_path, "exp", "20260101T000000Z_aaa111")
    rd2 = _make_run(tmp_path, "exp", "20260102T000000Z_bbb222")
    layout = Layout(tmp_path)

    assert layout.latest_run() == rd2
    assert layout.find_run("20260102T000000Z_bbb222") == rd2
    # Unique prefix resolves.
    assert layout.find_run("20260101") is not None
    # Unknown id returns None.
    assert layout.find_run("nope") is None


def test_iter_runs_skips_incomplete(tmp_path: Path):
    _make_run(tmp_path, "exp", "good")
    (tmp_path / "results" / "exp" / "incomplete").mkdir(parents=True)
    layout = Layout(tmp_path)
    ids = [rid for _, rid, _ in layout.iter_runs()]
    assert ids == ["good"]
