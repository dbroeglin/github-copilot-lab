"""SWE-bench integration for the harness.

This module lets the harness reproduce the experimental protocol of Bai et al.
("How Do Coding Agents Spend Your Money?", COLM 2026) with **Copilot CLI as the
agent** instead of OpenHands:

* :func:`load_tasks` turns SWE-bench instances (from the HF dataset or a cached
  JSON/JSONL file) into :class:`~copilot_experiments.models.Task` objects. Each
  instance becomes one task; the experiment's ``trials`` axis is the paper's
  repeated "runs".
* :func:`export_predictions` collects each trial's captured ``workspace.diff`` as a
  candidate ``model_patch`` and writes SWE-bench ``predictions.jsonl`` files (one per
  variant × trial, so instance ids stay unique within a file).
* :func:`grade_run` shells out to the **official ``swebench`` Docker harness**
  (``python -m swebench.harness.run_evaluation``) for ground-truth resolution, writes
  the resolved/unresolved verdict back into each trial, and re-aggregates the run's
  summary and SQLite index.

The Copilot run itself is host-native (Windows or Linux). Only :func:`grade_run`
needs Docker, and the ``swebench`` package + Docker are *optional*: importing this
module never requires them, and grading fails with a clear message when they are
absent. Tests inject a stub :class:`Evaluator` so the whole pipeline is exercised
offline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ._util import read_json, slugify, write_json, write_text
from .index import connect, index_pier_job_dir, index_run_dir
from .models import ExperimentRun, SweBenchInstance, Task
from .pier_results import iter_trial_dirs, write_pier_summary
from .report import build_summary, summary_markdown
from .storage import Layout

DEFAULT_DATASET = "princeton-nlp/SWE-bench_Verified"
DEFAULT_SPLIT = "test"

# A faithful "no-hint" prompt: the agent gets only the issue text and is told to fix
# the code in place without touching tests (the hidden test patch is never revealed,
# matching the paper's setup and avoiding leakage).
DEFAULT_PROMPT_TEMPLATE = (
    "You are working in the `{repo}` repository, checked out at the commit where a "
    "bug was reported. Resolve the issue described below by editing the source code in "
    "the current working directory.\n\n"
    "Guidelines:\n"
    "- Make the minimal code changes needed to fix the issue.\n"
    "- Do NOT modify, add, or delete any test files; the change will be graded against "
    "a hidden test suite.\n"
    "- Do not revert unrelated code or change project configuration.\n\n"
    "<issue>\n{problem_statement}\n</issue>\n"
)


class SweBenchError(RuntimeError):
    """Raised for SWE-bench loading or grading failures."""


# --------------------------------------------------------------------------- #
# Loading instances -> Tasks
# --------------------------------------------------------------------------- #
def _as_test_list(value: object) -> list[str]:
    """SWE-bench stores FAIL_TO_PASS / PASS_TO_PASS as a JSON-encoded string on HF
    but as a real list in some exports. Normalise both to ``list[str]``."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
        return [str(parsed)]
    return [str(value)]


def _repo_url(repo: str | None) -> str | None:
    """Map a SWE-bench ``owner/name`` repo to a clonable GitHub URL."""
    if not repo:
        return None
    if repo.startswith(("http://", "https://", "git@")):
        return repo
    return f"https://github.com/{repo}.git"


def _load_instances_file(path: Path) -> list[dict]:
    """Read instances from a ``.json`` (array) or ``.jsonl`` (one object per line)."""
    if not path.is_file():
        raise SweBenchError(f"Instances file not found: {path}")
    text = path.read_text(encoding="utf-8")
    records: list[dict]
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        if isinstance(data, dict):
            # Tolerate a wrapper like {"instances": [...]}.
            data = data.get("instances", data)
        if not isinstance(data, list):
            raise SweBenchError(f"Expected a JSON array of instances in {path}")
        records = list(data)
    return records


def _load_from_hf(dataset: str, split: str) -> list[dict]:
    try:
        from datasets import load_dataset  # type: ignore import-not-found
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise SweBenchError(
            "Loading SWE-bench from Hugging Face requires the 'datasets' package. "
            "Install it (e.g. `uv pip install datasets`) or pass an instances_file= "
            "JSON/JSONL exported from the dataset."
        ) from exc
    ds = load_dataset(dataset, split=split)
    return [dict(record) for record in ds]


def load_instances(
    *,
    dataset: str = DEFAULT_DATASET,
    split: str = DEFAULT_SPLIT,
    instances_file: str | Path | None = None,
    instance_ids: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Load raw SWE-bench instance dicts, selecting a config-driven subset.

    Provide ``instances_file`` (a JSON array or JSONL exported from the dataset) to
    stay fully offline; otherwise the HF ``dataset``/``split`` is loaded (needs the
    optional ``datasets`` package). ``instance_ids`` keeps only the named instances
    in the given order; ``limit`` truncates to the first N (applied after id
    filtering) for a quick smoke set.
    """
    if instances_file is not None:
        records = _load_instances_file(Path(instances_file))
    else:
        records = _load_from_hf(dataset, split)

    if instance_ids:
        by_id = {r.get("instance_id"): r for r in records}
        missing = [i for i in instance_ids if i not in by_id]
        if missing:
            raise SweBenchError(f"Instance id(s) not found in dataset: {', '.join(missing)}")
        records = [by_id[i] for i in instance_ids]

    if limit is not None:
        records = records[:limit]
    return records


def instance_to_task(
    record: dict,
    *,
    dataset: str = DEFAULT_DATASET,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
) -> Task:
    """Build a :class:`Task` (one SWE-bench instance) from a raw instance dict."""
    instance_id = record.get("instance_id")
    if not instance_id:
        raise SweBenchError("Instance record is missing 'instance_id'")
    repo = record.get("repo")
    base_commit = record.get("base_commit")
    problem_statement = record.get("problem_statement", "") or ""
    prompt = prompt_template.format(repo=repo or instance_id, problem_statement=problem_statement)
    return Task(
        name=instance_id,
        prompt=prompt,
        repo=_repo_url(repo),
        ref=base_commit,
        swebench=SweBenchInstance(
            instance_id=instance_id,
            dataset=dataset,
            repo=repo,
            base_commit=base_commit,
            environment_setup_commit=record.get("environment_setup_commit"),
            version=str(record["version"]) if record.get("version") is not None else None,
            difficulty=record.get("difficulty"),
            fail_to_pass=_as_test_list(record.get("FAIL_TO_PASS")),
            pass_to_pass=_as_test_list(record.get("PASS_TO_PASS")),
        ),
    )


def load_tasks(
    *,
    dataset: str = DEFAULT_DATASET,
    split: str = DEFAULT_SPLIT,
    instances_file: str | Path | None = None,
    instance_ids: Sequence[str] | None = None,
    limit: int | None = None,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
) -> list[Task]:
    """Convenience wrapper: load a subset and convert it to :class:`Task` objects."""
    records = load_instances(
        dataset=dataset,
        split=split,
        instances_file=instances_file,
        instance_ids=instance_ids,
        limit=limit,
    )
    return [instance_to_task(r, dataset=dataset, prompt_template=prompt_template) for r in records]


# --------------------------------------------------------------------------- #
# Pier task materialization
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PierSweBenchMaterialization:
    """Files written by the Pier-native SWE-bench initializer."""

    instances_path: Path
    job_path: Path
    task_dirs: list[Path]


def materialize_pier_swebench(
    root: Path,
    records: Sequence[dict],
    *,
    name: str = "swebench",
    dataset: str = DEFAULT_DATASET,
    models: Sequence[str] = ("gpt-5-mini",),
    effort: str | None = None,
    trials: int = 2,
    force: bool = False,
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
) -> PierSweBenchMaterialization:
    """Write SWE-bench instances as Pier task directories plus one Pier job YAML."""

    root = Path(root)
    instances_path = root / "swebench" / "instances.json"
    job_path = root / "experiments" / f"{slugify(name)}.yaml"
    if job_path.exists() and not force:
        raise SweBenchError(f"{job_path} already exists (use --force to overwrite)")

    task_dirs: list[Path] = []
    for record in records:
        task_dirs.append(
            _write_pier_swebench_task(
                root,
                record,
                dataset=dataset,
                prompt_template=prompt_template,
                force=force,
            )
        )

    write_json(instances_path, list(records))
    write_text(
        job_path,
        _pier_swebench_job_yaml(
            name=name,
            models=list(models),
            effort=effort,
            trials=trials,
            task_dirs=task_dirs,
            root=root,
        ),
    )
    return PierSweBenchMaterialization(
        instances_path=instances_path,
        job_path=job_path,
        task_dirs=task_dirs,
    )


def _write_pier_swebench_task(
    root: Path,
    record: dict,
    *,
    dataset: str,
    prompt_template: str,
    force: bool,
) -> Path:
    instance_id = str(record.get("instance_id") or "")
    repo = record.get("repo")
    base_commit = record.get("base_commit")
    repo_url = _repo_url(repo)
    if not instance_id:
        raise SweBenchError("Instance record is missing 'instance_id'")
    if not repo_url or not base_commit:
        raise SweBenchError(f"Instance {instance_id} is missing repo or base_commit")

    task_dir = root / "tasks" / slugify(instance_id)
    if task_dir.exists() and any(task_dir.iterdir()) and not force:
        raise SweBenchError(f"{task_dir} already exists (use --force to overwrite)")

    instruction = prompt_template.format(
        repo=repo or instance_id,
        problem_statement=record.get("problem_statement", "") or "",
    )
    write_text(task_dir / "instruction.md", instruction)
    write_text(task_dir / "task.toml", _pier_swebench_task_toml(record, dataset=dataset))
    write_text(
        task_dir / "environment" / "Dockerfile",
        _pier_swebench_dockerfile(repo_url, base_commit),
    )
    write_text(task_dir / "tests" / "test.sh", _pier_swebench_disabled_verifier())
    return task_dir


def _pier_swebench_task_toml(record: dict, *, dataset: str) -> str:
    instance_id = str(record["instance_id"])
    difficulty = record.get("difficulty")
    fail_to_pass = _as_test_list(record.get("FAIL_TO_PASS"))
    pass_to_pass = _as_test_list(record.get("PASS_TO_PASS"))
    version = str(record["version"]) if record.get("version") is not None else ""
    return "\n".join(
        [
            'version = "1.0"',
            "",
            "[task]",
            f"name = {_q(f'swebench/{instance_id}')}",
            f"description = {_q('SWE-bench instance ' + instance_id)}",
            'authors = [{ name = "copilot-experiments" }]',
            'keywords = ["copilot", "swebench", "python"]',
            "",
            "[metadata]",
            f"dataset = {_q(dataset)}",
            f"instance_id = {_q(instance_id)}",
            f"repo = {_q(str(record.get('repo') or ''))}",
            f"base_commit = {_q(str(record.get('base_commit') or ''))}",
            f"version = {_q(version)}",
            f"difficulty = {_q(str(difficulty or 'unknown'))}",
            f"fail_to_pass = {_toml_list(fail_to_pass)}",
            f"pass_to_pass = {_toml_list(pass_to_pass)}",
            "",
            "[agent]",
            "timeout_sec = 1800.0",
            "",
            "[verifier]",
            "timeout_sec = 120.0",
            "",
            "[environment]",
            "build_timeout_sec = 1800.0",
            "cpus = 2",
            "memory_mb = 4096",
            "storage_mb = 20480",
            "gpus = 0",
            "allow_internet = true",
            'workdir = "/repo"',
            "",
        ]
    )


def _pier_swebench_dockerfile(repo_url: str, base_commit: str) -> str:
    return "\n".join(
        [
            "FROM python:3.12-slim",
            "",
            "RUN apt-get update \\",
            "    && apt-get install -y --no-install-recommends ca-certificates git \\",
            "    && rm -rf /var/lib/apt/lists/*",
            "",
            f"RUN git clone --no-checkout {_shell_q(repo_url)} /repo",
            "WORKDIR /repo",
            f"RUN git checkout {_shell_q(base_commit)}",
            "",
        ]
    )


def _pier_swebench_disabled_verifier() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "# Real SWE-bench grading happens outside this placeholder verifier.",
            "echo 0 > /logs/verifier/reward.txt",
            "",
        ]
    )


def _pier_swebench_job_yaml(
    *,
    name: str,
    models: list[str],
    effort: str | None,
    trials: int,
    task_dirs: list[Path],
    root: Path,
) -> str:
    lines = [
        f"job_name: {slugify(name)}",
        "jobs_dir: jobs",
        f"n_attempts: {trials}",
        "n_concurrent_trials: 1",
        "verifier:",
        "  disable: true",
        "",
        "agents:",
    ]
    for model in models:
        lines.extend(
            [
                "  - name: copilot-cli",
                f"    model_name: {model}",
            ]
        )
        if effort:
            lines.extend(["    kwargs:", f"      reasoning_effort: {effort}"])
    lines.extend(["", "tasks:"])
    for task_dir in task_dirs:
        rel = Path(os.path.relpath(task_dir, root / "experiments"))
        lines.append(f"  - path: {rel.as_posix()}")
    lines.extend(
        [
            "",
            "artifacts:",
            "  - source: /repo",
            "    destination: repo",
            "",
        ]
    )
    return "\n".join(lines)


def _q(value: str) -> str:
    return json.dumps(value)


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(_q(value) for value in values) + "]"


def _shell_q(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


# --------------------------------------------------------------------------- #
# Predictions export
# --------------------------------------------------------------------------- #
@dataclass
class PredictionFile:
    """A SWE-bench ``predictions.jsonl`` for one (variant, trial) plus back-mapping."""

    path: Path
    variant_slug: str
    model_name: str
    trial_no: int
    dataset: str
    # instance_id -> the trial directory that produced the patch (for write-back).
    instances: dict[str, Path] = field(default_factory=dict)


def _task_dataset(task_dir: Path) -> str | None:
    """Read a task's dataset from its persisted ``task.json`` swebench block."""
    task_json = task_dir / "task.json"
    if not task_json.exists():
        return None
    swe = (read_json(task_json) or {}).get("swebench") or {}
    return swe.get("dataset")


def export_predictions(run_dir: Path) -> list[PredictionFile]:
    """Build SWE-bench predictions files from a finished run's captured diffs.

    One file per (variant, trial) is written under ``<run_dir>/swebench/<variant>/
    trial-<NNN>/predictions.jsonl``. Each entry's ``model_patch`` is that trial's
    ``workspace.diff`` (an empty patch when the trial produced no changes, which the
    grader treats as unresolved). Only tasks carrying an ``instance_id`` are included.
    """
    # Validate into the model so ``variant.slug`` / ``task_slug`` resolve correctly --
    # ``run.json`` does not serialize the ``slug`` @property, and a variant's slug can
    # differ from its name (e.g. "claude-sonnet-4.5" -> "claude-sonnet-4-5").
    run = ExperimentRun.model_validate(read_json(run_dir / "run.json"))
    out: list[PredictionFile] = []
    for vr in run.variants:
        vslug = vr.variant.slug
        model_name = vslug
        # Collect (trial_no -> [(instance_id, dataset, trial_dir)]) across all tasks.
        per_trial: dict[int, list[tuple[str, str, Path]]] = {}
        for tr in vr.tasks:
            if not tr.instance_id:
                continue
            task_dir = run_dir / "variants" / vslug / "tasks" / tr.task_slug
            dataset = _task_dataset(task_dir) or DEFAULT_DATASET
            for trial in tr.trials:
                trial_dir = task_dir / "trials" / f"{trial.trial_no:03d}"
                per_trial.setdefault(trial.trial_no, []).append(
                    (tr.instance_id, dataset, trial_dir)
                )

        for trial_no, entries in sorted(per_trial.items()):
            predictions: list[dict] = []
            instances: dict[str, Path] = {}
            dataset = DEFAULT_DATASET
            for instance_id, ds, trial_dir in entries:
                dataset = ds
                diff_path = trial_dir / "workspace.diff"
                patch = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
                predictions.append(
                    {
                        "instance_id": instance_id,
                        "model_name_or_path": model_name,
                        "model_patch": patch,
                    }
                )
                instances[instance_id] = trial_dir
            pf_path = run_dir / "swebench" / vslug / f"trial-{trial_no:03d}" / "predictions.jsonl"
            write_text(pf_path, "\n".join(json.dumps(p) for p in predictions) + "\n")
            out.append(
                PredictionFile(
                    path=pf_path,
                    variant_slug=vslug,
                    model_name=model_name,
                    trial_no=trial_no,
                    dataset=dataset,
                    instances=instances,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Pier predictions export + grading
# --------------------------------------------------------------------------- #
def export_pier_predictions(job_dir: Path) -> list[PredictionFile]:
    """Build SWE-bench predictions from Pier trial artifacts.

    Pier runs do not have the legacy ``workspace.diff`` artifact. For SWE-bench tasks
    generated by :func:`materialize_pier_swebench`, the job captures ``/repo`` as
    ``artifacts/repo``; this function derives a patch with local ``git diff`` from
    that copied repository. No network or Docker work is performed here.
    """

    out: list[PredictionFile] = []
    per_variant_task: dict[tuple[str, str], int] = {}
    for trial_dir in iter_trial_dirs(job_dir):
        trial = read_json(trial_dir / "result.json")
        metadata = _pier_trial_swebench_metadata(trial)
        instance_id = metadata.get("instance_id")
        if not instance_id:
            continue
        agent = trial.get("agent_info") or {}
        model_info = agent.get("model_info") or {}
        variant_slug = _pier_variant_slug(agent, model_info)
        task_name = str(trial.get("task_name") or instance_id)
        key = (variant_slug, task_name)
        per_variant_task[key] = per_variant_task.get(key, 0) + 1
        trial_no = per_variant_task[key]
        patch = _pier_trial_patch(trial_dir)

        pf_path = (
            Path(job_dir)
            / "swebench"
            / variant_slug
            / task_name.replace("/", "__")
            / f"trial-{trial_no:03d}"
            / "predictions.jsonl"
        )
        prediction = {
            "instance_id": instance_id,
            "model_name_or_path": model_info.get("name") or variant_slug,
            "model_patch": patch,
        }
        write_text(pf_path, json.dumps(prediction) + "\n")
        out.append(
            PredictionFile(
                path=pf_path,
                variant_slug=variant_slug,
                model_name=model_info.get("name") or variant_slug,
                trial_no=trial_no,
                dataset=metadata.get("dataset") or DEFAULT_DATASET,
                instances={instance_id: trial_dir},
            )
        )
    return out


def grade_pier_job(
    job_dir: Path,
    *,
    evaluator: Evaluator | None = None,
    run_id_prefix: str = "copilot-exp",
    layout: Layout | None = None,
    work_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> GradeReport:
    """Grade a Pier SWE-bench job and write verdicts back to trial ``result.json``."""

    job_dir = Path(job_dir)
    evaluator = evaluator or SwebenchDockerEvaluator()
    pred_files = export_pier_predictions(job_dir)
    if not pred_files:
        raise SweBenchError(
            f"No Pier SWE-bench tasks found in {job_dir}. Expected task.toml metadata "
            "with an instance_id and a captured artifacts/repo git checkout."
        )

    report = GradeReport(run_id=job_dir.name)
    work_root = work_dir or (job_dir / "swebench")
    for pf in pred_files:
        eval_run_id = f"{run_id_prefix}-{job_dir.name}-{pf.variant_slug}-t{pf.trial_no:03d}"
        if progress is not None:
            progress(
                f"grading {pf.variant_slug} trial {pf.trial_no:03d} "
                f"({len(pf.instances)} instance(s)) — run_id {eval_run_id}"
            )
        resolved = evaluator.evaluate(pf, run_id=eval_run_id, work_dir=work_root / "eval")
        for instance_id, trial_dir in pf.instances.items():
            is_resolved = instance_id in resolved
            _write_back_pier_success(trial_dir, instance_id, is_resolved, eval_run_id)
            report.verdicts.append(
                TrialVerdict(
                    variant_slug=pf.variant_slug,
                    instance_id=instance_id,
                    trial_no=pf.trial_no,
                    resolved=is_resolved,
                )
            )

    write_pier_summary(job_dir)
    if layout is None:
        layout = Layout(job_dir.parent.parent)
    conn = connect(layout.index_db)
    try:
        index_pier_job_dir(conn, job_dir)
    finally:
        conn.close()
    if progress is not None:
        progress(f"graded {report.n_graded} trial(s): {report.n_resolved} resolved")
    return report


def _pier_trial_swebench_metadata(trial: dict) -> dict[str, str | None]:
    task = (trial.get("config") or {}).get("task") or {}
    task_path = task.get("path")
    if not task_path:
        return {}
    task_toml = Path(task_path) / "task.toml"
    if not task_toml.exists():
        return {}
    metadata = tomllib.loads(task_toml.read_text(encoding="utf-8")).get("metadata") or {}
    return {
        "dataset": metadata.get("dataset"),
        "instance_id": metadata.get("instance_id"),
        "difficulty": metadata.get("difficulty"),
    }


def _pier_variant_slug(agent: dict[str, Any], model_info: dict[str, Any]) -> str:
    agent_name = str(agent.get("name") or "agent")
    model_name = model_info.get("name")
    return f"{agent_name}-{model_name}" if model_name else agent_name


def _pier_trial_patch(trial_dir: Path) -> str:
    diff_path = trial_dir / "workspace.diff"
    if diff_path.exists():
        return diff_path.read_text(encoding="utf-8")
    repo_dir = trial_dir / "artifacts" / "repo"
    if not (repo_dir / ".git").exists():
        return ""
    subprocess.run(
        ["git", "-C", str(repo_dir), "add", "-N", "."],
        capture_output=True,
        text=True,
        check=False,
    )
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--binary", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _write_back_pier_success(
    trial_dir: Path, instance_id: str, resolved: bool, run_id: str
) -> None:
    result_path = trial_dir / "result.json"
    result = read_json(result_path)
    verifier_result = result.setdefault("verifier_result", {})
    rewards = verifier_result.setdefault("rewards", {})
    rewards["reward"] = 1.0 if resolved else 0.0
    write_json(result_path, result)
    write_json(
        trial_dir / "swebench.json",
        {"instance_id": instance_id, "resolved": resolved, "eval_run_id": run_id},
    )


# --------------------------------------------------------------------------- #
# Grading via the official swebench Docker harness
# --------------------------------------------------------------------------- #
class Evaluator(Protocol):
    """Strategy that turns a predictions file into the set of resolved instance ids."""

    def evaluate(self, pf: PredictionFile, *, run_id: str, work_dir: Path) -> set[str]: ...


def parse_report(path: Path) -> set[str]:
    """Extract ``resolved_ids`` from an official swebench evaluation report json."""
    data = read_json(path)
    return {str(i) for i in (data.get("resolved_ids") or [])}


def docker_available() -> bool:
    return shutil.which("docker") is not None


def swebench_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("swebench") is not None
    except (ImportError, ValueError):  # pragma: no cover - defensive
        return False


@dataclass
class SwebenchDockerEvaluator:
    """Run the official ``swebench`` harness in Docker and read back ``resolved_ids``.

    Requires Docker (Linux containers) and the ``swebench`` package on the same
    interpreter. The harness writes its report as ``<model>.<run_id>.json`` in its
    working directory; we glob for it to tolerate the harness's own name-sanitising.
    """

    max_workers: int = 4
    python: str = sys.executable
    timeout: int | None = None
    extra_args: Sequence[str] = ()
    stream: Callable[[str], None] | None = None

    def evaluate(self, pf: PredictionFile, *, run_id: str, work_dir: Path) -> set[str]:
        if not swebench_available():
            raise SweBenchError(
                "The 'swebench' package is not installed. Install it (e.g. "
                "`uv pip install swebench`) to grade with the official Docker harness."
            )
        if not docker_available():
            raise SweBenchError(
                "Docker was not found on PATH. The official swebench harness grades "
                "inside per-instance Linux containers; start Docker Desktop or point "
                "DOCKER_HOST at a remote engine."
            )
        work_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.python,
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            pf.dataset,
            "--predictions_path",
            str(pf.path.resolve()),
            "--max_workers",
            str(self.max_workers),
            "--run_id",
            run_id,
            *self.extra_args,
        ]
        if self.stream is not None:
            self.stream(f"$ {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if self.stream is not None:
            for line in (proc.stdout or "").splitlines():
                self.stream(line)
        report = _find_report(work_dir, pf.model_name, run_id)
        if report is None:
            detail = (proc.stderr or proc.stdout or "").strip()[-1500:]
            raise SweBenchError(
                f"swebench evaluation produced no report for run_id={run_id!r} "
                f"(exit {proc.returncode}). Last output:\n{detail}"
            )
        return parse_report(report)


def _find_report(work_dir: Path, model_name: str, run_id: str) -> Path | None:
    """Locate the harness's ``<model>.<run_id>.json`` report, tolerating sanitising."""
    exact = work_dir / f"{model_name}.{run_id}.json"
    if exact.exists():
        return exact
    candidates = sorted(work_dir.glob(f"*.{run_id}.json"))
    return candidates[0] if candidates else None


@dataclass
class TrialVerdict:
    variant_slug: str
    instance_id: str
    trial_no: int
    resolved: bool


@dataclass
class GradeReport:
    run_id: str
    verdicts: list[TrialVerdict] = field(default_factory=list)

    @property
    def n_graded(self) -> int:
        return len(self.verdicts)

    @property
    def n_resolved(self) -> int:
        return sum(1 for v in self.verdicts if v.resolved)


def _write_back_success(trial_dir: Path, instance_id: str, resolved: bool, run_id: str) -> None:
    """Record the SWE-bench verdict on a trial: update meta.json + a swebench.json."""
    meta_path = trial_dir / "meta.json"
    if meta_path.exists():
        meta = read_json(meta_path)
        meta["success"] = resolved
        write_json(meta_path, meta)
    write_json(
        trial_dir / "swebench.json",
        {"instance_id": instance_id, "resolved": resolved, "eval_run_id": run_id},
    )


def _apply_verdicts(run: ExperimentRun, verdicts: dict[tuple[str, str, int], bool]) -> None:
    """Set ``trial.success`` on the in-memory run from (variant, instance, trial) verdicts."""
    for vr in run.variants:
        vslug = vr.variant.slug
        for tr in vr.tasks:
            if not tr.instance_id:
                continue
            for trial in tr.trials:
                key = (vslug, tr.instance_id, trial.trial_no)
                if key in verdicts:
                    trial.success = verdicts[key]


def _persist_regrade(run_dir: Path, run: ExperimentRun, layout: Layout | None) -> None:
    """Rewrite run.json/summary and refresh the index after grading."""
    write_json(run_dir / "run.json", run.model_dump(mode="json"))
    summary = build_summary(run)
    write_json(run_dir / "summary.json", summary)
    write_text(run_dir / "summary.md", summary_markdown(summary, run.experiment_description))
    if layout is None:
        # results_root is <run_dir>/.. /.. (results/<exp_slug>/<run_id>); derive a Layout
        # so the SQLite index lives next to the other runs.
        results_root = run_dir.parent.parent
        layout = Layout(results_root.parent, results_root=results_root)
    conn = connect(layout.index_db)
    try:
        index_run_dir(conn, run_dir)
    finally:
        conn.close()


def grade_run(
    run_dir: Path,
    *,
    evaluator: Evaluator | None = None,
    run_id_prefix: str = "copilot-exp",
    layout: Layout | None = None,
    work_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> GradeReport:
    """Grade every SWE-bench trial of a finished run and re-aggregate its results.

    Exports predictions, runs ``evaluator`` once per (variant, trial) predictions
    file, writes the resolved/unresolved verdict back into each trial's ``meta.json``
    (and a ``swebench.json``), then rebuilds ``run.json``, ``summary.{json,md}`` and
    the SQLite index so resolved@k / mean-success / AIU-per-solve reflect ground truth.

    ``evaluator`` defaults to :class:`SwebenchDockerEvaluator` (needs Docker +
    ``swebench``); tests pass a stub to run the whole flow offline.
    """
    run_dir = Path(run_dir)
    evaluator = evaluator or SwebenchDockerEvaluator()
    pred_files = export_predictions(run_dir)
    if not pred_files:
        raise SweBenchError(
            f"No SWE-bench tasks found in {run_dir}. Are these tasks built with "
            "swebench metadata (e.g. via copilot_experiments.swebench.load_tasks)?"
        )

    report = GradeReport(run_id=run_dir.name)
    verdict_map: dict[tuple[str, str, int], bool] = {}
    work_root = work_dir or (run_dir / "swebench")
    for pf in pred_files:
        eval_run_id = f"{run_id_prefix}-{run_dir.name}-{pf.variant_slug}-t{pf.trial_no:03d}"
        if progress is not None:
            progress(
                f"grading {pf.variant_slug} trial {pf.trial_no:03d} "
                f"({len(pf.instances)} instance(s)) — run_id {eval_run_id}"
            )
        resolved = evaluator.evaluate(pf, run_id=eval_run_id, work_dir=work_root / "eval")
        for instance_id, trial_dir in pf.instances.items():
            is_resolved = instance_id in resolved
            _write_back_success(trial_dir, instance_id, is_resolved, eval_run_id)
            verdict_map[(pf.variant_slug, instance_id, pf.trial_no)] = is_resolved
            report.verdicts.append(
                TrialVerdict(
                    variant_slug=pf.variant_slug,
                    instance_id=instance_id,
                    trial_no=pf.trial_no,
                    resolved=is_resolved,
                )
            )

    run = ExperimentRun.model_validate(read_json(run_dir / "run.json"))
    _apply_verdicts(run, verdict_map)
    _persist_regrade(run_dir, run, layout)
    if progress is not None:
        progress(f"graded {report.n_graded} trial(s): {report.n_resolved} resolved")
    return report


__all__ = [
    "DEFAULT_DATASET",
    "DEFAULT_PROMPT_TEMPLATE",
    "Evaluator",
    "GradeReport",
    "PredictionFile",
    "SwebenchDockerEvaluator",
    "SweBenchError",
    "TrialVerdict",
    "docker_available",
    "export_pier_predictions",
    "export_predictions",
    "grade_pier_job",
    "grade_run",
    "instance_to_task",
    "load_instances",
    "load_tasks",
    "parse_report",
    "swebench_available",
]
