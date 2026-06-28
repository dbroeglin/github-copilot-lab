"""Tests for Pier job config loading and normalization."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from typer.testing import CliRunner

from copilot_experiments.cli import app
from copilot_experiments.pier_backend import (
    COPILOT_CLI_AGENT_IMPORT_PATH,
    PierBackendPreflightError,
    discover_pier_job_configs,
    inject_copilot_token,
    load_pier_job_config,
    preflight_pier_backend,
    prepare_pier_job_for_run,
)


def test_load_pier_job_config_resolves_paths_and_local_agent(tmp_path: Path):
    (tmp_path / "experiments").mkdir()
    (tmp_path / "tasks" / "one").mkdir(parents=True)
    config_path = tmp_path / "experiments" / "job.yaml"
    config_path.write_text(
        "\n".join(
            [
                "job_name: smoke",
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

    config = load_pier_job_config(config_path, root=tmp_path)

    assert config.jobs_dir == (tmp_path / "jobs").resolve()
    assert config.tasks[0].path == (tmp_path / "tasks" / "one").resolve()
    assert config.agents[0].name is None
    assert config.agents[0].import_path == COPILOT_CLI_AGENT_IMPORT_PATH


def test_discover_pier_job_configs_can_filter_by_name(tmp_path: Path):
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "first.yaml").write_text("job_name: alpha\n", encoding="utf-8")
    (experiments / "second.yaml").write_text("job_name: beta\n", encoding="utf-8")

    specs = discover_pier_job_configs(tmp_path, name="beta")

    assert [spec.name for spec in specs] == ["beta"]


def test_inject_copilot_token_only_updates_copilot_agents(tmp_path: Path):
    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        "\n".join(
            [
                "job_name: smoke",
                "agents:",
                "  - name: copilot-cli",
                "  - name: nop",
            ]
        ),
        encoding="utf-8",
    )
    config = load_pier_job_config(config_path, root=tmp_path)

    inject_copilot_token(config, "token-123")

    assert config.agents[0].env["COPILOT_GITHUB_TOKEN"] == "token-123"
    assert config.agents[0].env["GITHUB_TOKEN"] == "token-123"
    assert config.agents[1].env == {}


def test_prepare_pier_job_for_run_creates_timestamped_run_under_job_group(tmp_path: Path):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\njobs_dir: jobs\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)

    prepared = prepare_pier_job_for_run(config, now=datetime(2026, 6, 20, 15, 30, 0))

    assert prepared.requested_name == "smoke"
    assert prepared.run_name == "20260620-153000"
    assert prepared.label == "smoke/20260620-153000"
    assert prepared.config.jobs_dir == tmp_path / "jobs" / "smoke"
    assert prepared.config.job_name == "20260620-153000"
    assert prepared.renamed
    assert not prepared.resumed
    assert config.job_name == "smoke"


def test_prepare_pier_job_for_run_uses_collision_suffix_when_run_exists(tmp_path: Path):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\njobs_dir: jobs\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)
    (tmp_path / "jobs" / "smoke" / "20260620-153000").mkdir(parents=True)

    prepared = prepare_pier_job_for_run(
        config,
        now=datetime(2026, 6, 20, 15, 30, 0),
    )

    assert prepared.requested_name == "smoke"
    assert prepared.run_name == "20260620-153000-2"
    assert prepared.config.jobs_dir == tmp_path / "jobs" / "smoke"
    assert prepared.config.job_name == "20260620-153000-2"
    assert prepared.renamed
    assert config.job_name == "smoke"


def test_prepare_pier_job_for_run_resume_uses_latest_nested_run(tmp_path: Path):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\njobs_dir: jobs\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)
    old_run = tmp_path / "jobs" / "smoke" / "20260620-153000"
    latest_run = tmp_path / "jobs" / "smoke" / "20260620-160000"
    old_run.mkdir(parents=True)
    latest_run.mkdir()
    (old_run / "config.json").write_text("{}", encoding="utf-8")
    (old_run / "copilot-experiments-run.json").write_text("{}", encoding="utf-8")
    (latest_run / "config.json").write_text("{}", encoding="utf-8")
    (latest_run / "copilot-experiments-run.json").write_text("{}", encoding="utf-8")

    prepared = prepare_pier_job_for_run(config, resume=True)

    assert prepared.requested_name == "smoke"
    assert prepared.run_name == "20260620-160000"
    assert prepared.config.jobs_dir == tmp_path / "jobs" / "smoke"
    assert prepared.config.job_name == "20260620-160000"
    assert prepared.resumed


def test_prepare_pier_job_for_run_resume_supports_legacy_flat_job(tmp_path: Path):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\njobs_dir: jobs\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)
    legacy_job = tmp_path / "jobs" / "smoke"
    legacy_job.mkdir(parents=True)
    (legacy_job / "config.json").write_text("{}", encoding="utf-8")

    prepared = prepare_pier_job_for_run(config, resume=True)

    assert prepared.run_name == "smoke"
    assert prepared.config.jobs_dir == tmp_path / "jobs"
    assert prepared.config.job_name == "smoke"
    assert prepared.resumed


def test_preflight_pier_backend_reports_missing_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)
    monkeypatch.setattr("copilot_experiments.pier_backend.shutil.which", lambda _name: None)

    with pytest.raises(PierBackendPreflightError, match="docker.*not found"):
        preflight_pier_backend(config)


def test_preflight_pier_backend_checks_docker_compose_and_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("copilot_experiments.pier_backend.shutil.which", lambda _name: "docker")
    monkeypatch.setattr("copilot_experiments.pier_backend.subprocess.run", fake_run)

    preflight_pier_backend(config)

    assert calls == [["docker", "compose", "version"], ["docker", "info"]]


def test_preflight_pier_backend_reports_unreachable_docker_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)

    def fake_run(command: list[str], **_kwargs):
        if command == ["docker", "info"]:
            return CompletedProcess(command, 1, stdout="", stderr="Cannot connect to Docker daemon")
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("copilot_experiments.pier_backend.shutil.which", lambda _name: "docker")
    monkeypatch.setattr("copilot_experiments.pier_backend.subprocess.run", fake_run)

    with pytest.raises(PierBackendPreflightError, match="Cannot connect to Docker daemon"):
        preflight_pier_backend(config)


def test_cli_run_fails_before_auth_when_pier_backend_preflight_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "job.yaml").write_text("job_name: smoke\n", encoding="utf-8")

    def fail_preflight(_config):
        raise PierBackendPreflightError("Docker is unavailable")

    def fail_if_called():
        pytest.fail("auth should not run after backend preflight failure")

    monkeypatch.setattr("copilot_experiments.cli.preflight_pier_backend", fail_preflight)
    monkeypatch.setattr("copilot_experiments.cli.preflight_github_token", fail_if_called)
    monkeypatch.setattr(
        "copilot_experiments.cli.run_pier_job",
        lambda _config: pytest.fail("Pier job should not start after backend preflight failure"),
    )

    result = CliRunner().invoke(app, ["run", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "Pier backend preflight failed" in result.output
    assert "Docker is unavailable" in result.output


@pytest.mark.parametrize(
    "example_root",
    [
        "examples/tracer_bullet",
        "examples/task_suite",
    ],
)
def test_committed_examples_are_valid_pier_configs(example_root: str):
    root = Path(__file__).parents[1] / example_root

    specs = discover_pier_job_configs(root)

    assert specs
    for spec in specs:
        assert all(task.path and task.path.exists() for task in spec.config.tasks)
        assert all(
            agent.import_path == COPILOT_CLI_AGENT_IMPORT_PATH for agent in spec.config.agents
        )
