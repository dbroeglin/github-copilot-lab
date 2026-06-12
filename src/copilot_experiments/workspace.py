"""Provision isolated per-trial workspaces and capture their diffs."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .models import Task

_GIT_IDENTITY = [
    "-c",
    "user.email=copilot-experiments@example.com",
    "-c",
    "user.name=copilot-experiments",
]


class WorkspaceError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def run_shell(command: str, cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run a shell command in ``cwd``; return (exit_code, combined_output)."""
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def provision(task: Task, workspace: Path, repo_root: Path) -> Path:
    """Create the starting workspace for a trial and commit a git baseline.

    The baseline commit lets us compute a clean diff of whatever Copilot changes.
    """
    workspace.mkdir(parents=True, exist_ok=True)

    if task.fixture and task.repo:
        raise WorkspaceError("Task defines both 'fixture' and 'repo'; choose one.")

    if task.fixture:
        src = (repo_root / task.fixture).resolve()
        if not src.is_dir():
            raise WorkspaceError(f"Fixture directory not found: {src}")
        shutil.copytree(src, workspace, dirs_exist_ok=True)
    elif task.repo:
        proc = _git(["clone", "--quiet", task.repo, "."], workspace)
        if proc.returncode != 0:
            raise WorkspaceError(f"git clone failed: {proc.stderr.strip()}")
        if task.ref:
            proc = _git(["checkout", "--quiet", task.ref], workspace)
            if proc.returncode != 0:
                raise WorkspaceError(f"git checkout {task.ref} failed: {proc.stderr.strip()}")

    # Establish a git baseline so diffing is reliable.
    if not (workspace / ".git").exists():
        _git(["init", "--quiet"], workspace)
    _git(["add", "-A"], workspace)
    _git([*_GIT_IDENTITY, "commit", "--quiet", "--allow-empty", "-m", "baseline"], workspace)

    for command in task.setup:
        code, output = run_shell(command, workspace)
        if code != 0:
            raise WorkspaceError(f"setup command failed ({command!r}): {output.strip()}")

    return workspace


def capture_diff(workspace: Path) -> str:
    """Return a unified diff of all changes since the baseline commit."""
    if not (workspace / ".git").exists():
        return ""
    _git(["add", "-A"], workspace)
    proc = _git(["diff", "--cached", "HEAD"], workspace)
    return proc.stdout or ""
