"""Tests for the Pier-only filesystem layout helpers."""

from __future__ import annotations

import json
from pathlib import Path

from copilot_experiments.storage import Layout


def _make_pier_run(root: Path, job: str, run_id: str) -> Path:
    run_dir = root / "jobs" / job / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "config.json").write_text("{}", encoding="utf-8")
    (run_dir / "result.json").write_text("{}", encoding="utf-8")
    (run_dir / "copilot-experiments-run.json").write_text(
        json.dumps({"job_name": job, "run_id": run_id, "id": f"{job}/{run_id}"}),
        encoding="utf-8",
    )
    return run_dir


def test_layout_paths(tmp_path: Path):
    layout = Layout(tmp_path)
    assert layout.jobs_dir == tmp_path / "jobs"
    assert layout.experiments_dir == tmp_path / "experiments"


def test_pier_run_helpers(tmp_path: Path):
    old = _make_pier_run(tmp_path, "smoke", "20260102-000000")
    latest = _make_pier_run(tmp_path, "smoke", "20260103-000000")
    other = _make_pier_run(tmp_path, "other", "20260104-000000")
    incomplete = tmp_path / "jobs" / "smoke" / "20260105-000000"
    incomplete.mkdir()
    flat_legacy = tmp_path / "jobs" / "legacy-job"
    flat_legacy.mkdir()
    (flat_legacy / "config.json").write_text("{}", encoding="utf-8")
    (flat_legacy / "result.json").write_text("{}", encoding="utf-8")

    layout = Layout(tmp_path)

    assert layout.iter_pier_jobs() == [other, old, latest]
    assert layout.pier_job_key(old) == "smoke/20260102-000000"
    assert layout.latest_pier_job() == latest
    assert layout.find_pier_job("smoke") == latest
    assert layout.find_pier_job("smoke/20260102") == old
    assert layout.find_pier_job("20260102") == old
    assert layout.find_pier_job("legacy-job") is None
    assert layout.find_pier_job("missing") is None
