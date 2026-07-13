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
    check_jobs_dir_writable,
    discover_pier_job_configs,
    inject_copilot_token,
    load_pier_job_config,
    preflight_pier_backend,
    prepare_pier_job_for_run,
    sync_saved_run_config,
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


def test_prepare_pier_job_for_run_resume_loads_saved_config_and_clears_tokens(tmp_path: Path):
    """Resume rebuilds config from config.json so Pier's equality check passes."""
    import json

    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        "job_name: smoke\njobs_dir: jobs\nagents:\n  - name: copilot-cli\n",
        encoding="utf-8",
    )
    config = load_pier_job_config(config_path, root=tmp_path)
    run_dir = tmp_path / "jobs" / "smoke" / "20260620-160000"
    run_dir.mkdir(parents=True)

    # Simulate a previous run: inject a (now-stale) token and save config.json
    inject_copilot_token(config, "old-token")
    saved_config = config.model_copy(deep=True)
    saved_config.jobs_dir = run_dir.parent
    saved_config.job_name = run_dir.name
    (run_dir / "config.json").write_text(
        json.dumps(saved_config.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "copilot-experiments-run.json").write_text("{}", encoding="utf-8")

    # Load fresh config (token not yet injected) and resume
    fresh_config = load_pier_job_config(config_path, root=tmp_path)
    prepared = prepare_pier_job_for_run(fresh_config, resume=True)

    assert prepared.resumed
    assert prepared.run_name == "20260620-160000"
    # Token env vars must be cleared so inject_copilot_token can set fresh values
    copilot_agent = prepared.config.agents[0]
    assert "COPILOT_GITHUB_TOKEN" not in copilot_agent.env
    assert "GITHUB_TOKEN" not in copilot_agent.env
    assert "GH_TOKEN" not in copilot_agent.env
    # After injecting a new token it should be present
    inject_copilot_token(prepared.config, "new-token")
    assert copilot_agent.env["COPILOT_GITHUB_TOKEN"] == "new-token"


def test_sync_saved_run_config_updates_config_json(tmp_path: Path):
    """sync_saved_run_config overwrites config.json with the current in-memory config."""
    import json

    config_path = tmp_path / "job.yaml"
    config_path.write_text(
        "job_name: smoke\njobs_dir: jobs\nagents:\n  - name: copilot-cli\n",
        encoding="utf-8",
    )
    config = load_pier_job_config(config_path, root=tmp_path)
    run_dir = tmp_path / "jobs" / "smoke" / "20260620-160000"
    run_dir.mkdir(parents=True)

    # Write a stale config.json with an old token
    config.jobs_dir = run_dir.parent
    config.job_name = run_dir.name
    inject_copilot_token(config, "old-token")
    (run_dir / "config.json").write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    # Update the in-memory token and sync to disk
    config.agents[0].env["COPILOT_GITHUB_TOKEN"] = "new-token"
    config.agents[0].env["GITHUB_TOKEN"] = "new-token"
    config.agents[0].env["GH_TOKEN"] = "new-token"
    sync_saved_run_config(config)

    saved = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    agent_env = saved["agents"][0]["env"]
    assert agent_env["COPILOT_GITHUB_TOKEN"] == "new-token"
    assert agent_env["GITHUB_TOKEN"] == "new-token"


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
    assert "Validation" in result.output
    assert "smoke: backend" in result.output
    assert "Docker is unavailable" in result.output


def test_check_jobs_dir_writable_passes_for_writable_tree(tmp_path: Path):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\njobs_dir: jobs\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)

    # tmp_path is writable, so the not-yet-created jobs/smoke tree is reachable.
    check_jobs_dir_writable(config)


def test_check_jobs_dir_writable_reports_nearest_existing_ancestor(tmp_path: Path):
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_name: smoke\njobs_dir: jobs\n", encoding="utf-8")
    config = load_pier_job_config(config_path, root=tmp_path)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    blocked = {jobs_dir}
    with pytest.raises(PierBackendPreflightError) as excinfo:
        check_jobs_dir_writable(config, writable=lambda directory: directory not in blocked)

    message = str(excinfo.value)
    # The existing but unwritable ancestor (jobs/) is reported, not the missing run dir.
    assert str(jobs_dir) in message
    assert "chown" in message
    # The intended run directory is still named for context.
    assert str(tmp_path / "jobs" / "smoke") in message


def test_cli_validate_flags_unwritable_jobs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "job.yaml").write_text("job_name: smoke\n", encoding="utf-8")

    def fail_writable(_config, **_kwargs):
        raise PierBackendPreflightError("not writable; run chown")

    monkeypatch.setattr("copilot_experiments.cli.check_jobs_dir_writable", fail_writable)

    result = CliRunner().invoke(app, ["validate", "--root", str(tmp_path)])

    assert result.exit_code == 1
    assert "smoke: jobs dir" in result.output
    assert "chown" in result.output


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
