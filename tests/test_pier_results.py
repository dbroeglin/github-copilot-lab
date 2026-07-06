"""Tests for adapting Pier job outputs into copilot-experiments summaries."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from copilot_experiments.cli import app
from copilot_experiments.pier_results import (
    _aggregate_agent,
    _aggregate_task,
    _cv,
    _std,
    build_pier_summary,
    describe_missing_pier_analysis_source,
    pier_job_identity,
    resolve_pier_trial_events,
    write_pier_run_manifest,
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


def _make_pier_job_with_trajectory(job_dir: Path) -> Path:
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
    _write_json(
        trial / "agent" / "trajectory.json",
        {
            "schema_version": "ATIF-v1.7",
            "session_id": "copilot-cli",
            "agent": {
                "name": "copilot-cli",
                "version": "1.0.63",
                "model_name": "gpt-5-mini",
            },
            "steps": [
                {
                    "step_id": 1,
                    "timestamp": "2026-01-01T00:00:00Z",
                    "source": "user",
                    "message": "Fix textstats.py",
                },
                {
                    "step_id": 2,
                    "timestamp": "2026-01-01T00:00:02Z",
                    "source": "agent",
                    "model_name": "gpt-5-mini",
                    "message": "Tool call",
                    "tool_calls": [
                        {
                            "tool_call_id": "call-1",
                            "function_name": "view",
                            "arguments": {"path": "/app/textstats.py"},
                        }
                    ],
                    "observation": {
                        "results": [
                            {
                                "source_call_id": "call-1",
                                "content": "1. raise NotImplementedError",
                            }
                        ]
                    },
                    "metrics": {"completion_tokens": 7},
                },
            ],
        },
    )
    return job_dir


def _make_pier_job_with_harness_error(job_dir: Path) -> Path:
    _write_json(
        job_dir / "config.json",
        {"job_name": "demo-job"},
    )
    _write_json(
        job_dir / "result.json",
        {
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:05Z",
            "stats": {"n_errored_trials": 1},
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
            "exception_info": {
                "exception_type": "RuntimeError",
                "exception_message": "Docker daemon unavailable",
            },
        },
    )
    return job_dir


def test_build_pier_summary_reads_native_copilot_events(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job")

    summary = build_pier_summary(job_dir)

    assert summary["run_id"] == "demo-job"
    assert summary["status"] == "completed"
    assert summary["overall_success_rate"] == 1.0
    agent = summary["agents"][0]
    assert agent["agent"] == "copilot-cli-gpt-5-mini"
    assert agent["avg_turns"] == 1.0
    assert agent["avg_tool_calls"] == 1.0
    assert agent["avg_total_tokens"] == 15.0
    assert agent["tasks"][0]["task"] == "textstats"


def test_build_pier_summary_reads_nested_run_identity(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")

    summary = build_pier_summary(job_dir)

    assert summary["job"] == "demo-job"
    assert summary["job_name"] == "demo-job"
    assert summary["run_id"] == "20260620-153000"
    assert summary["pier_job_id"] == "demo-job/20260620-153000"
    assert pier_job_identity(job_dir) == {
        "job_name": "demo-job",
        "run_id": "20260620-153000",
        "id": "demo-job/20260620-153000",
    }


def test_resolve_pier_trial_events(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")

    events_path, label = resolve_pier_trial_events(job_dir)

    assert events_path is not None
    assert events_path.name == "events.jsonl"
    assert label == "demo-job/20260620-153000 · copilot-cli__textstats__1"


def test_build_pier_summary_reads_trajectory_when_native_events_are_absent(tmp_path: Path):
    job_dir = _make_pier_job_with_trajectory(tmp_path / "jobs" / "demo-job")

    summary = build_pier_summary(job_dir)

    agent = summary["agents"][0]
    assert agent["avg_turns"] == 1.0
    assert agent["avg_tool_calls"] == 1.0
    assert agent["avg_output_tokens"] == 7.0


def test_describe_missing_pier_analysis_source_explains_harness_error(tmp_path: Path):
    job_dir = _make_pier_job_with_harness_error(tmp_path / "jobs" / "demo-job")

    diagnostic = describe_missing_pier_analysis_source(job_dir)

    assert diagnostic is not None
    assert "failed before a Copilot session was captured" in diagnostic
    assert "Docker daemon unavailable" in diagnostic
    assert "result.json" in diagnostic


def test_cli_analyze_reads_pier_job_events(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "analyze",
            "demo-job",
            "--root",
            str(tmp_path),
            "--agent",
            "copilot-cli",
            "--task",
            "textstats",
            "--trial",
            "1",
            "--max-turns",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "demo-job" in result.output
    assert "gpt-5-mini" in result.output
    assert "Tool usage" in result.output


def test_cli_analyze_reads_pier_job_trajectory_when_events_are_absent(tmp_path: Path):
    job_dir = _make_pier_job_with_trajectory(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "analyze",
            "demo-job",
            "--root",
            str(tmp_path),
            "--agent",
            "copilot-cli",
            "--task",
            "textstats",
            "--trial",
            "1",
            "--max-turns",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "demo-job" in result.output
    assert "gpt-5-mini" in result.output
    assert "view" in result.output


def test_cli_analyze_reports_pier_harness_error_when_logs_are_absent(tmp_path: Path):
    job_dir = _make_pier_job_with_harness_error(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "analyze",
            "demo-job",
            "--root",
            str(tmp_path),
            "--agent",
            "copilot-cli",
            "--task",
            "textstats",
            "--trial",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "No Copilot session log or trajectory found" in result.output
    assert "failed before a Copilot session was captured" in result.output
    assert "Docker daemon" in result.output
    assert "unavailable" in result.output


def test_cli_list_displays_pier_run_selectors(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")
    runner = CliRunner()

    result = runner.invoke(app, ["list", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Pier runs" in result.output
    assert "selector" in result.output
    assert "demo-job/20260620-153000" in result.output
    assert "demo-job" in result.output
    assert "20260620-153000" in result.output
    assert "No runs yet" not in result.output


def test_cli_validate_checks_pier_config(
    tmp_path: Path,
    monkeypatch,
):
    experiments = tmp_path / "experiments"
    task = tmp_path / "tasks" / "one"
    experiments.mkdir()
    task.mkdir(parents=True)
    (experiments / "job.yaml").write_text(
        "\n".join(
            [
                "job_name: demo-job",
                "jobs_dir: jobs",
                "agents:",
                "  - name: copilot-cli",
                "    model_name: gpt-5-mini",
                "tasks:",
                "  - path: ../tasks/one",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("copilot_experiments.auth._gh_auth_token", lambda: "token")
    runner = CliRunner()

    result = runner.invoke(app, ["validate", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Pier job configs" in result.output
    assert "Validation" in result.output
    assert "demo-job: agents" in result.output
    assert "auth" in result.output


def test_cli_show_accepts_pier_job_run_selector(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["show", "demo-job/20260620-153000", "--root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "demo-job" in result.output
    assert "20260620-153000" in result.output
    assert "summary.md" in result.output


def test_cli_show_missing_run_points_to_list(tmp_path: Path):
    runner = CliRunner()

    result = runner.invoke(app, ["show", "missing", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "Pier run not found" in result.output
    assert "copilot-experiments list" in result.output
    assert "job-name/run-id" in result.output


def test_write_pier_summary(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")

    summary = write_pier_summary(job_dir)

    assert (job_dir / "summary.json").exists()
    assert (job_dir / "summary.md").exists()
    assert summary["n_trials"] == 1
    assert summary["n_agents"] == 1
    assert summary["agents"][0]["name"] == "copilot-cli-gpt-5-mini"
    assert "Agent" in (job_dir / "summary.md").read_text(encoding="utf-8")


def _trial(success: bool | None, aiu: float | None, tokens: float | None, task: str = "t") -> dict:
    return {
        "success": success,
        "task": task,
        "task_name": task,
        "metrics": {"aiu": aiu, "total_tokens": tokens},
    }


def test_std_and_cv_helpers():
    assert _std([100, 200, 300]) == 81.65
    assert _cv([100, 200, 300]) == 0.408
    assert _std([50]) == 0.0  # a single trial has zero spread, not None
    assert _std([]) is None
    assert _cv([]) is None
    assert _cv([0, 0]) is None  # undefined when the mean is zero


def test_aggregate_task_populates_variance_and_resolved_rate():
    task = _aggregate_task("t", [_trial(True, 0.2, 100), _trial(False, 0.3, 300)])

    assert task["success_rate"] == 0.5
    assert task["resolved"] == 1
    assert task["resolved_rate"] == 1.0
    assert task["cv_aiu"] == _cv([0.2, 0.3])
    assert task["cv_total_tokens"] == _cv([100, 300])


def test_aggregate_task_resolved_rate_zero_when_never_solved():
    task = _aggregate_task("t", [_trial(False, 0.2, 100), _trial(False, 0.3, 300)])

    assert task["resolved"] == 0
    assert task["resolved_rate"] == 0.0


def test_aggregate_agent_populates_std_cv_and_suite_coverage():
    trials = [
        _trial(True, 0.2, 100, "a"),
        _trial(False, 0.4, 300, "a"),
        _trial(True, 0.1, 90, "b"),
    ]
    task_summaries = [
        {"success_rate": 0.5, "resolved_rate": 1.0},
        {"success_rate": 1.0, "resolved_rate": 0.0},
    ]

    agent = _aggregate_agent(trials, task_summaries)

    assert agent["std_aiu"] == _std([0.2, 0.4, 0.1])
    assert agent["cv_aiu"] == _cv([0.2, 0.4, 0.1])
    assert agent["std_total_tokens"] == _std([100, 300, 90])
    assert agent["cv_total_tokens"] == _cv([100, 300, 90])
    assert agent["mean_resolved_rate"] == 0.75  # mean of per-task success rates
    assert agent["resolved_at_k_rate"] == 0.5  # fraction of tasks solved at least once


def test_build_pier_summary_populates_new_aggregates(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job")

    summary = build_pier_summary(job_dir)
    agent = summary["agents"][0]

    # A single graded trial resolves its one task, so coverage is fully populated.
    assert agent["mean_resolved_rate"] == 1.0
    assert agent["resolved_at_k_rate"] == 1.0
    assert agent["cv_total_tokens"] is not None
    assert agent["tasks"][0]["resolved_rate"] == 1.0


def test_cli_chart_writes_dashboard(tmp_path: Path):
    job_dir = _make_pier_job(tmp_path / "jobs" / "demo-job" / "20260620-153000")
    write_pier_run_manifest(job_dir, job_name="demo-job", run_id="20260620-153000")
    runner = CliRunner()

    result = runner.invoke(app, ["chart", "--last", "--cdn", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    dashboard = job_dir / "summary.html"
    assert dashboard.exists()
    assert "<!DOCTYPE html>" in dashboard.read_text(encoding="utf-8")
