"""Tests for scaffolding a standalone experiment repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from copilot_experiments.cli import app
from copilot_experiments.scaffold import ScaffoldError, init_experiment_repo


def test_init_creates_expected_files(tmp_path: Path):
    dest = tmp_path / "my-experiments"
    created = init_experiment_repo(dest, project_name="my-experiments")

    assert (dest / "pyproject.toml").exists()
    assert (dest / "README.md").exists()
    assert (dest / "AGENTS.md").exists()
    assert (dest / "apm.yml").exists()
    assert (dest / "experiments" / "example.yaml").exists()
    assert (dest / "tasks" / "example-fix-bug" / "task.toml").exists()
    assert (dest / "tasks" / "example-fix-bug" / "environment" / "calculator.py").exists()
    # No .tmpl files should remain.
    assert not list(dest.rglob("*.tmpl"))
    assert created


def test_init_renders_placeholders(tmp_path: Path):
    dest = tmp_path / "cool-proj"
    init_experiment_repo(dest, project_name="cool-proj")
    pyproject = (dest / "pyproject.toml").read_text(encoding="utf-8")
    task_toml = (dest / "tasks" / "example-fix-bug" / "task.toml").read_text(encoding="utf-8")
    assert "cool-proj" in pyproject
    assert "{{project_name}}" not in pyproject
    assert 'name = "cool-proj/example-fix-bug"' in task_toml
    assert "{{project_name}}" not in task_toml


def test_init_refuses_nonempty_without_force(tmp_path: Path):
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "keep.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ScaffoldError):
        init_experiment_repo(dest)

    # With force it proceeds.
    created = init_experiment_repo(dest, force=True)
    assert created


def test_cli_init_scaffolds_repository_with_name(tmp_path: Path):
    dest = tmp_path / "generated"

    result = CliRunner().invoke(app, ["init", str(dest), "--name", "custom-experiment"])

    assert result.exit_code == 0, result.output
    assert "Initialized" in result.output
    pyproject = (dest / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "custom-experiment"' in pyproject
