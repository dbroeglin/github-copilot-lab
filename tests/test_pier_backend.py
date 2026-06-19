"""Tests for Pier job config loading and normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from copilot_experiments.pier_backend import (
    COPILOT_CLI_AGENT_IMPORT_PATH,
    discover_pier_job_configs,
    inject_copilot_token,
    load_pier_job_config,
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


@pytest.mark.parametrize(
    "example_root",
    [
        "examples/tracer_bullet",
        "examples/task_suite",
        "examples/swebench",
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
