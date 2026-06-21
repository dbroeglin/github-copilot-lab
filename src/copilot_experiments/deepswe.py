"""DeepSWE import helpers.

DeepSWE already uses Harbor/Pier task directories, so importing means generating a
``copilot-experiments`` Pier JobConfig that points at a DeepSWE task corpus.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from ._util import slugify

DeepSweSourceKind = Literal["dataset", "task"]

_REQUIRED_TASK_FILES = ("task.toml", "instruction.md", "pre_artifacts.sh")
_REQUIRED_TASK_DIRS = ("environment", "tests")


class DeepSweImportError(RuntimeError):
    """Raised when a DeepSWE source cannot be converted to a Pier job config."""


@dataclass(frozen=True)
class DeepSweSource:
    """Resolved DeepSWE source path and shape."""

    path: Path
    kind: DeepSweSourceKind
    task_count: int


@dataclass(frozen=True)
class DeepSweImportResult:
    """Generated job config and where it was written."""

    path: Path
    source: DeepSweSource
    config: dict[str, Any]


def discover_deepswe_source(source: Path) -> DeepSweSource:
    """Resolve ``source`` to either one DeepSWE task or a task corpus directory.

    ``source`` may be a DeepSWE checkout root, its ``tasks/`` directory, or one
    individual task directory. The returned path is the exact path used in the
    generated Pier config.
    """

    source = Path(source).expanduser()
    if not source.exists():
        raise DeepSweImportError(f"DeepSWE source does not exist: {source}")
    source = source.resolve()

    if _is_task_dir(source):
        _validate_task_dir(source)
        return DeepSweSource(path=source, kind="task", task_count=1)

    tasks_dir = source / "tasks" if (source / "tasks").is_dir() else source
    task_dirs = _task_dirs(tasks_dir)
    if not task_dirs:
        raise DeepSweImportError(
            "Expected a DeepSWE checkout, a DeepSWE tasks directory, or one task directory "
            f"containing task.toml: {source}"
        )

    invalid = [task_dir for task_dir in task_dirs if not _valid_task_dir(task_dir)]
    if invalid:
        shown = ", ".join(str(path) for path in invalid[:3])
        suffix = "" if len(invalid) <= 3 else f", and {len(invalid) - 3} more"
        raise DeepSweImportError(f"Invalid DeepSWE task directory shape: {shown}{suffix}")

    return DeepSweSource(path=tasks_dir.resolve(), kind="dataset", task_count=len(task_dirs))


def build_deepswe_job_config(
    source: DeepSweSource,
    *,
    output_path: Path,
    job_name: str = "deepswe-copilot",
    jobs_dir: str = "jobs",
    model: str = "gpt-5-mini",
    reasoning_effort: str | None = "medium",
    mode: str | None = None,
    context_tier: str | None = None,
    environment: str | None = None,
    n_attempts: int = 1,
    n_concurrent_trials: int = 1,
    task_names: list[str] | None = None,
    n_tasks: int | None = None,
    sample_seed: int | None = None,
) -> dict[str, Any]:
    """Build a Pier JobConfig dictionary for a DeepSWE source."""

    if n_attempts < 1:
        raise DeepSweImportError("n_attempts must be at least 1.")
    if n_concurrent_trials < 1:
        raise DeepSweImportError("n_concurrent_trials must be at least 1.")
    if n_tasks is not None and n_tasks < 1:
        raise DeepSweImportError("n_tasks must be at least 1 when provided.")

    config: dict[str, Any] = {
        "job_name": slugify(job_name),
        "jobs_dir": jobs_dir,
        "n_attempts": n_attempts,
        "n_concurrent_trials": n_concurrent_trials,
    }
    if environment is not None:
        config["environment"] = {"type": environment}

    agent: dict[str, Any] = {
        "name": "copilot-cli",
        "model_name": model,
    }
    kwargs: dict[str, Any] = {}
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    if mode is not None:
        kwargs["mode"] = mode
    if context_tier is not None:
        kwargs["context_tier"] = context_tier
    if kwargs:
        agent["kwargs"] = kwargs
    config["agents"] = [agent]

    source_path = _yaml_path(source.path, output_path.parent)
    if source.kind == "task":
        config["tasks"] = [{"path": source_path}]
    else:
        dataset: dict[str, Any] = {"path": source_path}
        if task_names:
            dataset["task_names"] = task_names
        if n_tasks is not None:
            dataset["n_tasks"] = n_tasks
        if sample_seed is not None:
            dataset["sample_seed"] = sample_seed
        config["datasets"] = [dataset]

    return config


def write_deepswe_job_config(
    source: Path,
    *,
    root: Path,
    output: Path | None = None,
    overwrite: bool = False,
    job_name: str = "deepswe-copilot",
    jobs_dir: str = "jobs",
    model: str = "gpt-5-mini",
    reasoning_effort: str | None = "medium",
    mode: str | None = None,
    context_tier: str | None = None,
    environment: str | None = None,
    n_attempts: int = 1,
    n_concurrent_trials: int = 1,
    task_names: list[str] | None = None,
    n_tasks: int | None = None,
    sample_seed: int | None = None,
) -> DeepSweImportResult:
    """Write a Pier JobConfig YAML file for DeepSWE tasks."""

    root = Path(root).expanduser().resolve()
    output_path = (
        Path(output) if output is not None else root / "experiments" / f"{slugify(job_name)}.yaml"
    )
    if not output_path.is_absolute():
        output_path = root / output_path
    output_path = output_path.resolve()

    if output_path.exists() and not overwrite:
        raise DeepSweImportError(
            f"Output already exists: {output_path}. Pass --force to overwrite."
        )

    resolved_source = discover_deepswe_source(source)
    config = build_deepswe_job_config(
        resolved_source,
        output_path=output_path,
        job_name=job_name,
        jobs_dir=jobs_dir,
        model=model,
        reasoning_effort=reasoning_effort,
        mode=mode,
        context_tier=context_tier,
        environment=environment,
        n_attempts=n_attempts,
        n_concurrent_trials=n_concurrent_trials,
        task_names=task_names,
        n_tasks=n_tasks,
        sample_seed=sample_seed,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return DeepSweImportResult(path=output_path, source=resolved_source, config=config)


def _is_task_dir(path: Path) -> bool:
    return path.is_dir() and (path / "task.toml").is_file()


def _task_dirs(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(child for child in path.iterdir() if _is_task_dir(child))


def _valid_task_dir(path: Path) -> bool:
    return all((path / name).is_file() for name in _REQUIRED_TASK_FILES) and all(
        (path / name).is_dir() for name in _REQUIRED_TASK_DIRS
    )


def _validate_task_dir(path: Path) -> None:
    if _valid_task_dir(path):
        return

    missing = [name for name in _REQUIRED_TASK_FILES if not (path / name).is_file()] + [
        name for name in _REQUIRED_TASK_DIRS if not (path / name).is_dir()
    ]
    raise DeepSweImportError(
        f"Invalid DeepSWE task directory shape at {path}; missing: {', '.join(missing)}"
    )


def _yaml_path(path: Path, base: Path) -> str:
    try:
        rel = os.path.relpath(path, start=base)
    except ValueError:
        return str(path)
    return rel.replace(os.sep, "/")
