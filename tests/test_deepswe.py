"""Tests for DeepSWE Pier job config import."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from copilot_experiments.cli import app
from copilot_experiments.deepswe import DeepSweImportError, write_deepswe_job_config
from copilot_experiments.pier_backend import (
    COPILOT_CLI_AGENT_IMPORT_PATH,
    discover_pier_job_configs,
)


def test_write_deepswe_job_config_generates_dataset_config(tmp_path: Path):
    tasks_dir = tmp_path / "deep-swe" / "tasks"
    _make_deepswe_task(tasks_dir, "alpha")
    _make_deepswe_task(tasks_dir, "beta")
    root = tmp_path / "experiment-repo"

    result = write_deepswe_job_config(
        tmp_path / "deep-swe",
        root=root,
        job_name="DeepSWE Smoke",
        model="gpt-5.5",
        reasoning_effort="high",
        environment="docker",
        n_attempts=4,
        n_concurrent_trials=2,
        task_names=["a*"],
        n_tasks=1,
        sample_seed=7,
    )

    assert result.source.kind == "dataset"
    assert result.source.task_count == 2
    data = yaml.safe_load(result.path.read_text(encoding="utf-8"))
    assert data == {
        "job_name": "deepswe-smoke",
        "jobs_dir": "jobs",
        "n_attempts": 4,
        "n_concurrent_trials": 2,
        "environment": {"type": "docker"},
        "agents": [
            {
                "name": "copilot-cli",
                "model_name": "gpt-5.5",
                "kwargs": {"reasoning_effort": "high"},
            }
        ],
        "datasets": [
            {
                "path": "../../deep-swe/tasks",
                "task_names": ["a*"],
                "n_tasks": 1,
                "sample_seed": 7,
            }
        ],
    }

    specs = discover_pier_job_configs(root)
    assert len(specs) == 1
    assert specs[0].config.datasets[0].path == tasks_dir.resolve()
    assert specs[0].config.agents[0].import_path == COPILOT_CLI_AGENT_IMPORT_PATH


def test_write_deepswe_job_config_generates_single_task_config(tmp_path: Path):
    task_dir = _make_deepswe_task(tmp_path / "deep-swe" / "tasks", "alpha")
    root = tmp_path / "experiment-repo"

    result = write_deepswe_job_config(
        task_dir,
        root=root,
        output=Path("experiments/single.yaml"),
        reasoning_effort=None,
        mode="autopilot",
        context_tier="long_context",
    )

    data = yaml.safe_load(result.path.read_text(encoding="utf-8"))
    assert result.source.kind == "task"
    assert data["agents"] == [
        {
            "name": "copilot-cli",
            "model_name": "gpt-5-mini",
            "kwargs": {"mode": "autopilot", "context_tier": "long_context"},
        }
    ]
    assert data["tasks"] == [{"path": "../../deep-swe/tasks/alpha"}]
    assert "datasets" not in data


def test_write_deepswe_job_config_refuses_to_overwrite(tmp_path: Path):
    _make_deepswe_task(tmp_path / "deep-swe" / "tasks", "alpha")
    root = tmp_path / "experiment-repo"
    output = root / "experiments" / "deepswe-copilot.yaml"
    output.parent.mkdir(parents=True)
    output.write_text("existing: true\n", encoding="utf-8")

    with pytest.raises(DeepSweImportError, match="Output already exists"):
        write_deepswe_job_config(tmp_path / "deep-swe", root=root)


def test_write_deepswe_job_config_rejects_invalid_task_shape(tmp_path: Path):
    task_dir = tmp_path / "deep-swe" / "tasks" / "broken"
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text("[task]\nname = 'broken'\n", encoding="utf-8")

    with pytest.raises(DeepSweImportError, match="Invalid DeepSWE task directory shape"):
        write_deepswe_job_config(tmp_path / "deep-swe", root=tmp_path / "experiment-repo")


def test_deepswe_import_cli_writes_config(tmp_path: Path):
    _make_deepswe_task(tmp_path / "deep-swe" / "tasks", "alpha")
    root = tmp_path / "experiment-repo"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "deepswe-import",
            str(tmp_path / "deep-swe"),
            "--root",
            str(root),
            "--job-name",
            "DeepSWE CLI",
            "--n-tasks",
            "1",
            "--sample-seed",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Wrote" in result.output
    data = yaml.safe_load((root / "experiments" / "deepswe-cli.yaml").read_text(encoding="utf-8"))
    assert data["job_name"] == "deepswe-cli"
    assert data["datasets"][0]["n_tasks"] == 1
    assert data["datasets"][0]["sample_seed"] == 0


def _make_deepswe_task(tasks_dir: Path, name: str) -> Path:
    task_dir = tasks_dir / name
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "tests").mkdir()
    (task_dir / "task.toml").write_text(
        "\n".join(
            [
                'schema_version = "1.1"',
                'artifacts = ["/logs/artifacts/model.patch"]',
                "[task]",
                f'name = "datacurve/{name}"',
                "[metadata]",
                f'task_id = "{name}"',
                'repository_url = "https://github.com/example/repo"',
                'base_commit_hash = "abc123"',
                "[environment]",
                'docker_image = "example/image:latest"',
            ]
        ),
        encoding="utf-8",
    )
    (task_dir / "instruction.md").write_text("Fix the issue.\n", encoding="utf-8")
    (task_dir / "pre_artifacts.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (task_dir / "environment" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (task_dir / "tests" / "test.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    return task_dir
