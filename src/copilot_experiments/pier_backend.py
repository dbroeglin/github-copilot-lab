"""Pier job loading and execution helpers."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .pier_agents.copilot_cli import COPILOT_CLI_AGENT_NAME, CopilotCli
from .pier_results import PIER_RUN_MANIFEST

COPILOT_CLI_AGENT_IMPORT_PATH = CopilotCli.import_path()


@dataclass(frozen=True)
class PierJobSpec:
    """A discovered Pier job config file."""

    path: Path
    config: Any

    @property
    def name(self) -> str:
        return str(self.config.job_name)


@dataclass(frozen=True)
class PierRunResult:
    """Result returned after running one Pier job."""

    job_dir: Path
    result: Any


@dataclass(frozen=True)
class PreparedPierJob:
    """A Pier config ready to run, plus the stable job and concrete run identity."""

    config: Any
    requested_name: str
    run_name: str
    resumed: bool = False

    @property
    def renamed(self) -> bool:
        return self.requested_name != self.run_name

    @property
    def label(self) -> str:
        return f"{self.requested_name}/{self.run_name}"


class PierBackendPreflightError(RuntimeError):
    """A Pier execution backend is not available before a job starts."""


def discover_pier_job_configs(root: Path, name: str | None = None) -> list[PierJobSpec]:
    """Load Pier JobConfig files from ``experiments/*.yaml|*.yml|*.json``."""

    root = Path(root)
    experiments_dir = root / "experiments"
    if not experiments_dir.is_dir():
        return []

    specs: list[PierJobSpec] = []
    paths = [
        *experiments_dir.glob("*.yaml"),
        *experiments_dir.glob("*.yml"),
        *experiments_dir.glob("*.json"),
    ]
    for path in sorted(paths):
        config = load_pier_job_config(path, root=root)
        spec = PierJobSpec(path=path, config=config)
        if name and name not in (path.stem, spec.name):
            continue
        specs.append(spec)
    return specs


def load_pier_job_config(path: Path, *, root: Path | None = None) -> Any:
    """Load and normalize a Pier ``JobConfig`` from YAML or JSON."""

    from pier.models.job.config import JobConfig

    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        raise ValueError(f"Unsupported Pier job config format: {path.suffix}")

    config = JobConfig.model_validate(data)
    return normalize_pier_job_config(
        config,
        root=Path(root or path.parent.parent),
        base_dir=path.parent,
    )


def normalize_pier_job_config(config: Any, *, root: Path, base_dir: Path) -> Any:
    """Resolve relative paths and map local ``copilot-cli`` agent names to import paths."""

    config.jobs_dir = _resolve_path(config.jobs_dir, root)

    for task in config.tasks:
        if task.path is not None:
            task.path = _resolve_path(task.path, base_dir)
        if task.download_dir is not None:
            task.download_dir = _resolve_path(task.download_dir, root)

    for dataset in config.datasets:
        if dataset.path is not None:
            dataset.path = _resolve_path(dataset.path, base_dir)
        if dataset.download_dir is not None:
            dataset.download_dir = _resolve_path(dataset.download_dir, root)
        if dataset.registry_path is not None:
            dataset.registry_path = _resolve_path(dataset.registry_path, root)

    for agent in config.agents:
        if agent.name == COPILOT_CLI_AGENT_NAME and agent.import_path is None:
            agent.name = None
            agent.import_path = COPILOT_CLI_AGENT_IMPORT_PATH

    return config


def preflight_pier_backend(config: Any) -> None:
    """Fail fast when the configured Pier backend is not usable locally."""

    backend = _environment_type(config)
    if backend == "docker":
        _preflight_docker_backend()


def check_jobs_dir_writable(
    config: Any,
    *,
    writable: Callable[[Path], bool] | None = None,
) -> None:
    """Fail fast when the harness cannot create the job's run directory.

    Pier creates ``jobs_dir / job_name`` with ``Path.mkdir(parents=True)``. When an
    earlier run left that tree owned by another user -- most commonly ``root``, because
    Pier's Docker backend runs containers as root and bind-mounts the jobs directory --
    the current user can no longer create entries under it and Pier raises a bare
    ``PermissionError``. Detect that here and surface an actionable remediation instead.
    """

    is_writable = writable or (lambda directory: os.access(directory, os.W_OK | os.X_OK))
    target = _job_dir(config)
    anchor = _nearest_existing_ancestor(target)
    if is_writable(anchor):
        return
    raise PierBackendPreflightError(
        f"Cannot write to {anchor}, which is needed to create the run directory "
        f"{target}. An earlier run probably created it as another user (for example "
        f"root, via the Pier Docker backend), so the current user can no longer create "
        f"entries under it. Reclaim ownership with "
        f'`sudo chown -R "$(id -u):$(id -g)" {anchor}` '
        f"or remove the stale output directory, then retry."
    )


def _nearest_existing_ancestor(path: Path) -> Path:
    """Return ``path`` or its closest existing ancestor directory."""

    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return Path(path.anchor) if path.anchor else Path(".")


def inject_copilot_token(config: Any, token: str) -> None:
    """Inject a GitHub token into local Copilot agents without persisting it to config."""

    for agent in config.agents:
        is_copilot = (
            agent.import_path == COPILOT_CLI_AGENT_IMPORT_PATH
            or agent.name == COPILOT_CLI_AGENT_NAME
        )
        if not is_copilot:
            continue
        agent.env.setdefault("COPILOT_GITHUB_TOKEN", token)
        agent.env.setdefault("GITHUB_TOKEN", token)
        agent.env.setdefault("GH_TOKEN", token)


def prepare_pier_job_for_run(
    config: Any,
    *,
    resume: bool = False,
    now: datetime | None = None,
) -> PreparedPierJob:
    """Return a run-ready config.

    Pier treats ``jobs_dir / job_name`` as the job directory and resumes any completed
    trials found there. The harness keeps the configured ``job_name`` as the stable
    experiment identity, but points Pier at ``jobs/<job_name>/<run_id>`` so every
    execution has a uniform run directory. Explicit ``--resume`` reuses the latest
    known run for that stable job when one exists.
    """

    prepared = config.model_copy(deep=True)
    requested_name = str(prepared.job_name)
    if resume:
        existing = _latest_existing_run_dir(prepared)
        if existing is not None:
            prepared.jobs_dir = existing.parent
            prepared.job_name = existing.name
            return PreparedPierJob(prepared, requested_name, existing.name, resumed=True)

    base_run_name = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    run_name = base_run_name
    job_group_dir = Path(prepared.jobs_dir) / requested_name
    index = 2
    while (job_group_dir / run_name).exists():
        run_name = f"{base_run_name}-{index}"
        index += 1

    prepared.jobs_dir = job_group_dir
    prepared.job_name = run_name
    return PreparedPierJob(prepared, requested_name, run_name)


def run_pier_job(config: Any) -> PierRunResult:
    """Run a Pier job through Pier's Python API."""

    from pier.job import Job

    async def _run() -> PierRunResult:
        job = await Job.create(config)
        result = await job.run()
        return PierRunResult(job_dir=job.job_dir, result=result)

    return asyncio.run(_run())


def _resolve_path(path: Path, base: Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else (base / path).resolve()


def _job_dir(config: Any) -> Path:
    return Path(config.jobs_dir) / str(config.job_name)


def _latest_existing_run_dir(config: Any) -> Path | None:
    """Return the latest resumable run directory for a stable job config."""

    job_group = _job_dir(config)
    if job_group.is_dir():
        runs = sorted(
            path
            for path in job_group.iterdir()
            if path.is_dir()
            and (path / "config.json").exists()
            and (path / PIER_RUN_MANIFEST).exists()
        )
        if runs:
            return runs[-1]
    return None


def _environment_type(config: Any) -> str:
    environment = getattr(config, "environment", None)
    value = getattr(environment, "type", None)
    return str(getattr(value, "value", value) or "").lower()


def _preflight_docker_backend() -> None:
    if shutil.which("docker") is None:
        raise PierBackendPreflightError(
            "Pier is configured to use the Docker backend, but the 'docker' CLI was not found. "
            "Install Docker or enable Docker Desktop WSL integration, then retry."
        )

    _run_backend_probe(
        ["docker", "compose", "version"],
        "Docker Compose is required by Pier's Docker backend but is not available.",
    )
    _run_backend_probe(
        ["docker", "info"],
        "Docker is installed, but the daemon is not reachable.",
    )


def _run_backend_probe(command: list[str], failure_message: str) -> None:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except OSError as exc:
        raise PierBackendPreflightError(f"{failure_message} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise PierBackendPreflightError(
            f"{failure_message} Probe timed out after {exc.timeout} seconds: {' '.join(command)}"
        ) from exc

    if proc.returncode == 0:
        return

    detail = "\n".join(part for part in (proc.stderr.strip(), proc.stdout.strip()) if part)
    suffix = f"\n{detail}" if detail else ""
    raise PierBackendPreflightError(
        f"{failure_message} Command failed: {' '.join(command)}{suffix}"
    )
