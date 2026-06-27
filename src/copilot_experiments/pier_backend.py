"""Pier job loading and execution helpers."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .pier_agents.copilot_cli import COPILOT_CLI_AGENT_NAME, CopilotCli

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
    """A Pier config ready to run, plus any job-name adjustment made for freshness."""

    config: Any
    requested_name: str
    run_name: str

    @property
    def renamed(self) -> bool:
        return self.requested_name != self.run_name


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

    Pier resumes an existing matching ``jobs/<job_name>`` directory and skips completed trials.
    For an experiment harness, a plain ``run`` should create a new measurement instead, while
    explicit ``--resume`` should preserve Pier's native behavior.
    """

    prepared = config.model_copy(deep=True)
    requested_name = str(prepared.job_name)
    if resume:
        return PreparedPierJob(prepared, requested_name, requested_name)

    requested_dir = _job_dir(prepared)
    if not requested_dir.exists():
        return PreparedPierJob(prepared, requested_name, requested_name)

    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = f"{requested_name}-{stamp}"
    run_name = base
    index = 2
    while (Path(prepared.jobs_dir) / run_name).exists():
        run_name = f"{base}-{index}"
        index += 1

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
