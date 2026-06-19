"""Tests for adapting Pier job outputs into copilot-experiments summaries."""

from __future__ import annotations

import json
from pathlib import Path

from copilot_experiments.index import connect, index_pier_job_dir
from copilot_experiments.pier_results import (
    build_pier_summary,
    resolve_pier_trial_events,
    write_pier_summary,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def _make_pier_job(job_dir: Path) -> Path:
    _write_json(
        job_dir / "config.json",
        {"job_name": "demo-job"},
    )
    _write_json(
        job_dir / "result.json",
        {
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:05Z",
            "stats": {"n_errored_trials": 0},
        },
    )
    trial = job_dir / "copilot-cli__textstats__1"
    _write_json(
        trial / "result.json",
        {
            "trial_name": "copilot-cli__textstats__1",
            "task_name": "textstats",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:05Z",
            "agent_info": {
                "name": "copilot-cli",
                "model_info": {"name": "gpt-5-mini"},
            },
            "config": {"agent": {"kwargs": {"reasoning_effort": "low"}}},
            "verifier_result": {"rewards": {"reward": 1}},
        },
    )
    _write_jsonl(
        trial / "agent" / "copilot-session" / "session-1" / "events.jsonl",
        [
            {
                "type": "session.start",
                "timestamp": "2026-01-01T00:00:00Z",
                "data": {"selectedModel": "gpt-5-mini"},
            },
            {
                "type": "assistant.turn_start",
                "timestamp": "2026-01-01T00:00:01Z",
                "data": {},
            },
            {
                "type": "assistant.message",
                "timestamp": "2026-01-01T00:00:02Z",
                "data": {
                    "model": "gpt-5-mini",
                    "inputTokens": 10,
                    "outputTokens": 5,
                },
            },
            {
                "type": "tool.execution_complete",
                "timestamp": "2026-01-01T00:00:03Z",
                "data": {"success": True},
            },
        ],
    )
    return job_dir


def test_build_pier_summary_reads_native_copilot_events(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job")

    summary = build_pier_summary(job_dir)

    assert summary["run_id"] == "demo-job"
    assert summary["status"] == "completed"
    assert summary["overall_success_rate"] == 1.0
    variant = summary["variants"][0]
    assert variant["variant"] == "copilot-cli-gpt-5-mini"
    assert variant["avg_turns"] == 1.0
    assert variant["avg_tool_calls"] == 1.0
    assert variant["avg_total_tokens"] == 15.0
    assert variant["tasks"][0]["task"] == "textstats"


def test_resolve_pier_trial_events(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job")

    events_path, label = resolve_pier_trial_events(job_dir)

    assert events_path is not None
    assert events_path.name == "events.jsonl"
    assert label == "demo-job · copilot-cli__textstats__1"


def test_write_pier_summary_and_index(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job")

    summary = write_pier_summary(job_dir)

    assert (job_dir / "summary.json").exists()
    assert (job_dir / "summary.md").exists()
    assert summary["n_trials"] == 1

    conn = connect(tmp_path / "results" / "index.db")
    try:
        index_pier_job_dir(conn, job_dir)
        job = conn.execute("SELECT * FROM pier_jobs WHERE job_name='demo-job'").fetchone()
        trial = conn.execute("SELECT * FROM pier_trials WHERE job_name='demo-job'").fetchone()
    finally:
        conn.close()

    assert job["success_rate"] == 1.0
    assert trial["trial_name"] == "copilot-cli__textstats__1"
    assert trial["success"] == 1
    assert trial["total_tokens"] == 15.0
