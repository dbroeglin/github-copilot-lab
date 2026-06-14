"""Workspace provisioning and diff-capture tests.

These prove the parts a no-op dry-run does *not*: that provisioning creates a
real git baseline (a resolvable ``HEAD``) and that subsequent changes are either
captured as a diff or surfaced as an error. This is the path that silently
returned an empty ``workspace.diff`` on Windows (MAX_PATH), so the tests assert
the baseline and diff explicitly rather than trusting an empty string.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from copilot_experiments.models import Task
from copilot_experiments.workspace import WorkspaceError, capture_diff, provision


def _make_fixture(root: Path, name: str = "fix") -> str:
    d = root / "fixtures" / name
    d.mkdir(parents=True)
    (d / "hello.txt").write_text("hello\n", encoding="utf-8")
    return f"fixtures/{name}"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _force_rmtree(path: Path) -> None:
    """Remove a tree that may contain >260-char paths (Windows MAX_PATH)."""
    target = os.path.abspath(str(path))
    if sys.platform == "win32":
        target = "\\\\?\\" + target
    shutil.rmtree(target, ignore_errors=True)


def test_provision_copies_fixture(tmp_path: Path):
    fixture = _make_fixture(tmp_path)
    ws = tmp_path / "ws"
    provision(Task(prompt="p", fixture=fixture), ws, tmp_path)
    assert (ws / "hello.txt").read_text(encoding="utf-8") == "hello\n"


def test_provision_creates_resolvable_baseline(tmp_path: Path):
    # The bug: a silently-failed baseline left no HEAD, so every diff was empty.
    # Assert HEAD resolves and the tree is clean (everything committed).
    fixture = _make_fixture(tmp_path)
    ws = tmp_path / "ws"
    provision(Task(prompt="p", fixture=fixture), ws, tmp_path)

    head = _git(["rev-parse", "HEAD"], ws)
    assert head.returncode == 0
    assert head.stdout.strip()  # a real commit sha

    status = _git(["status", "--porcelain"], ws)
    assert status.stdout.strip() == ""


def test_provision_runs_setup_commands(tmp_path: Path):
    fixture = _make_fixture(tmp_path)
    ws = tmp_path / "ws"
    provision(
        Task(prompt="p", fixture=fixture, setup=["echo seeded > SETUP_RAN"]),
        ws,
        tmp_path,
    )
    assert (ws / "SETUP_RAN").exists()


def test_provision_failing_setup_raises(tmp_path: Path):
    fixture = _make_fixture(tmp_path)
    ws = tmp_path / "ws"
    with pytest.raises(WorkspaceError):
        provision(Task(prompt="p", fixture=fixture, setup=["exit 7"]), ws, tmp_path)


def test_provision_rejects_fixture_and_repo(tmp_path: Path):
    ws = tmp_path / "ws"
    with pytest.raises(WorkspaceError):
        provision(Task(prompt="p", fixture="x", repo="https://example/r.git"), ws, tmp_path)


def test_provision_missing_fixture_raises(tmp_path: Path):
    ws = tmp_path / "ws"
    with pytest.raises(WorkspaceError):
        provision(Task(prompt="p", fixture="fixtures/does-not-exist"), ws, tmp_path)


def test_capture_diff_reflects_changes(tmp_path: Path):
    fixture = _make_fixture(tmp_path)
    ws = tmp_path / "ws"
    provision(Task(prompt="p", fixture=fixture), ws, tmp_path)

    # Emulate Copilot editing a file and adding a new one.
    (ws / "hello.txt").write_text("hello world\n", encoding="utf-8")
    (ws / "NEW.txt").write_text("brand new\n", encoding="utf-8")

    diff = capture_diff(ws)
    assert "hello world" in diff
    assert "NEW.txt" in diff
    assert diff.strip() != ""


def test_capture_diff_empty_when_unchanged(tmp_path: Path):
    fixture = _make_fixture(tmp_path)
    ws = tmp_path / "ws"
    provision(Task(prompt="p", fixture=fixture), ws, tmp_path)
    assert capture_diff(ws) == ""


def test_capture_diff_without_git_returns_empty(tmp_path: Path):
    ws = tmp_path / "plain"
    ws.mkdir()
    assert capture_diff(ws) == ""


def test_capture_diff_surfaces_git_failure(tmp_path: Path):
    # A ``.git`` that is not a valid repository must raise, not silently return
    # "" (the failure mode that hid the broken baseline).
    ws = tmp_path / "broken"
    ws.mkdir()
    (ws / ".git").write_text("not a git repository", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        capture_diff(ws)


def test_provision_baseline_survives_deep_paths(tmp_path: Path):
    # Regression for the Windows MAX_PATH failure. The *workspace* path stays
    # under 260 (so plain Python can create it and copy fixtures into it), but the
    # nested ``.git/objects/<..>`` files it writes cross 260 -- which only succeeds
    # when git is invoked with core.longpaths=true. Before the fix this left no
    # HEAD and every diff came back empty. On POSIX there is no 260-char limit, so
    # this simply still passes.
    fixture = _make_fixture(tmp_path)

    deep = tmp_path
    seg = "deeppath__"  # 10 chars per level
    first_seg = tmp_path / seg
    try:
        # Grow until the workspace path is long enough that the git object files
        # inside it (~+55 chars) will exceed 260, while the workspace path itself
        # stays creatable by plain Python (< ~245).
        while len(str(deep / seg / "workspace")) < 235:
            deep = deep / seg
            deep.mkdir()
        ws = deep / "workspace"

        provision(Task(prompt="p", fixture=fixture), ws, tmp_path)
        head = _git(["rev-parse", "HEAD"], ws)
        assert head.returncode == 0
        assert head.stdout.strip()
    finally:
        # The deepest .git/objects paths exceed MAX_PATH, so a plain rmtree
        # (pytest's teardown) would fail to delete them.
        _force_rmtree(first_seg)
