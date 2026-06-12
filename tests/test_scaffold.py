"""Tests for scaffolding a standalone experiment repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from copilot_experiments.scaffold import ScaffoldError, init_experiment_repo


def test_init_creates_expected_files(tmp_path: Path):
    dest = tmp_path / "my-experiments"
    created = init_experiment_repo(dest, project_name="my-experiments")

    assert (dest / "pyproject.toml").exists()
    assert (dest / "README.md").exists()
    assert (dest / "AGENTS.md").exists()
    assert (dest / "apm.yml").exists()
    assert (dest / "experiments" / "example_fix_bug.py").exists()
    assert (dest / "fixtures" / "buggy_calculator" / "calculator.py").exists()
    # No .tmpl files should remain.
    assert not list(dest.rglob("*.tmpl"))
    assert created


def test_init_renders_placeholders(tmp_path: Path):
    dest = tmp_path / "cool-proj"
    init_experiment_repo(dest, project_name="cool-proj")
    pyproject = (dest / "pyproject.toml").read_text(encoding="utf-8")
    assert "cool-proj" in pyproject
    assert "{{project_name}}" not in pyproject


def test_init_refuses_nonempty_without_force(tmp_path: Path):
    dest = tmp_path / "occupied"
    dest.mkdir()
    (dest / "keep.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ScaffoldError):
        init_experiment_repo(dest)

    # With force it proceeds.
    created = init_experiment_repo(dest, force=True)
    assert created
