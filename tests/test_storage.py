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
    trial = layout.trial_dir("exp", "run1", "v1", "task-001", 3)
    assert trial.name == "003"
    assert trial.parent.name == "trials"
    assert trial.parent.parent.name == "task-001"
    assert trial.parent.parent.parent.name == "tasks"
    assert trial.parent.parent.parent.parent.name == "v1"


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


def test_pier_job_helpers(tmp_path: Path):
    jobs = tmp_path / "jobs"
    good = jobs / "smoke" / "20260102-000000"
    good.mkdir(parents=True)
    (good / "config.json").write_text("{}", encoding="utf-8")
    (good / "result.json").write_text("{}", encoding="utf-8")
    latest = jobs / "smoke" / "20260103-000000"
    latest.mkdir()
    (latest / "config.json").write_text("{}", encoding="utf-8")
    (latest / "result.json").write_text("{}", encoding="utf-8")
    incomplete = jobs / "smoke" / "20260104-000000"
    incomplete.mkdir()
    legacy = jobs / "legacy-job"
    legacy.mkdir()
    (legacy / "config.json").write_text("{}", encoding="utf-8")
    (legacy / "result.json").write_text("{}", encoding="utf-8")
    legacy_trial = legacy / "copilot-cli__task__1"
    legacy_trial.mkdir()
    (legacy_trial / "config.json").write_text("{}", encoding="utf-8")
    (legacy_trial / "result.json").write_text("{}", encoding="utf-8")

    layout = Layout(tmp_path)

    assert layout.iter_pier_jobs() == [legacy, good, latest]
    assert layout.pier_job_key(good) == "smoke/20260102-000000"
    assert layout.latest_pier_job() == latest
    assert layout.find_pier_job("smoke") == latest
    assert layout.find_pier_job("smoke/20260102") == good
    assert layout.find_pier_job("20260102") == good
    assert layout.find_pier_job("legacy-job") == legacy
    assert layout.find_pier_job("missing") is None
