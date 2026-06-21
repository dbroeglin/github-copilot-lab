"""Read Pier job outputs into copilot-experiments summaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ._util import read_json, write_json, write_text
from .analysis import analyze_trajectory
from .pier_agents.copilot_cli import find_copilot_otel_file, find_copilot_session_events
from .report import summary_markdown
from .sessionlog import load_events, parse_metrics

AnalysisSource = Literal["events", "trajectory"]


def iter_trial_dirs(job_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in Path(job_dir).iterdir()
        if path.is_dir() and (path / "result.json").exists()
    )


def iter_pier_trial_summaries(job_dir: Path) -> list[dict[str, Any]]:
    """Return one adapted summary row for each Pier trial directory."""

    rows: list[dict[str, Any]] = []
    for trial_dir in iter_trial_dirs(job_dir):
        rows.append(_trial_summary(trial_dir, read_json(trial_dir / "result.json")))
    return rows


def build_pier_summary(job_dir: Path) -> dict[str, Any]:
    """Build the familiar summary shape from a Pier job directory."""

    job_dir = Path(job_dir)
    job_result = read_json(job_dir / "result.json")
    job_config = read_json(job_dir / "config.json") if (job_dir / "config.json").exists() else {}

    variant_cells: dict[str, dict[str, Any]] = {}
    for row in iter_pier_trial_summaries(job_dir):
        variant_key = row["variant"]
        cell = variant_cells.setdefault(
            variant_key,
            {
                "variant": variant_key,
                "name": variant_key,
                "model": row.get("model"),
                "reasoning_effort": row.get("reasoning_effort"),
                "byok": False,
                "n_tasks": 0,
                "n_trials": 0,
                "tasks": defaultdict(list),
            },
        )
        cell["n_trials"] += 1
        cell["tasks"][row["task"]].append(row)

    variants = []
    for cell in variant_cells.values():
        task_summaries = []
        all_trials = []
        for task_slug, trials in sorted(cell["tasks"].items()):
            all_trials.extend(trials)
            task_summaries.append(_aggregate_task(task_slug, trials))
        cell["tasks"] = task_summaries
        cell["n_tasks"] = len(task_summaries)
        cell.update(_aggregate_variant(all_trials))
        variants.append(cell)

    all_trials = [
        trial for variant in variants for task in variant["tasks"] for trial in task["_trials"]
    ]
    graded = [trial["success"] for trial in all_trials if trial.get("success") is not None]
    total_aiu = sum((trial.get("metrics") or {}).get("aiu") or 0 for trial in all_trials)

    summary = {
        "run_id": job_dir.name,
        "experiment": job_config.get("job_name") or job_dir.name,
        "experiment_slug": job_dir.name,
        "started_at": job_result.get("started_at"),
        "finished_at": job_result.get("finished_at"),
        "status": _job_status(job_result),
        "n_variants": len(variants),
        "n_tasks": max((variant.get("n_tasks", 0) for variant in variants), default=0),
        "n_trials": len(all_trials),
        "n_failed_trials": sum(1 for trial in all_trials if trial.get("status") != "ok"),
        "n_harness_errors": sum(
            1 for trial in all_trials if trial.get("status") == "harness_error"
        ),
        "n_copilot_failures": sum(
            1 for trial in all_trials if trial.get("status") == "copilot_failed"
        ),
        "overall_success_rate": (
            (sum(1 for value in graded if value) / len(graded)) if graded else None
        ),
        "total_aiu": round(total_aiu, 3) if total_aiu else None,
        "variants": [_strip_internal_trials(variant) for variant in variants],
    }
    return summary


def write_pier_summary(job_dir: Path) -> dict[str, Any]:
    summary = build_pier_summary(job_dir)
    write_json(job_dir / "summary.json", summary)
    write_text(job_dir / "summary.md", summary_markdown(summary))
    return summary


def resolve_pier_trial_events(
    job_dir: Path, trial: int | str | None = None
) -> tuple[Path | None, str]:
    trial_dir = _resolve_trial_dir(job_dir, trial)
    if trial_dir is None:
        return None, Path(job_dir).name
    events = find_copilot_session_events(trial_dir / "agent")
    return events, f"{Path(job_dir).name} · {trial_dir.name}"


def resolve_pier_trial_analysis_source(
    job_dir: Path, trial: int | str | None = None
) -> tuple[Path | None, str, AnalysisSource | None, Path | None]:
    trial_dir = _resolve_trial_dir(job_dir, trial)
    if trial_dir is None:
        return None, Path(job_dir).name, None, None

    label = f"{Path(job_dir).name} · {trial_dir.name}"
    agent_dir = trial_dir / "agent"
    events = find_copilot_session_events(agent_dir)
    if events is not None:
        return events, label, "events", find_copilot_otel_file(agent_dir)

    trajectory = agent_dir / "trajectory.json"
    if trajectory.exists():
        return trajectory, label, "trajectory", None
    return None, label, None, None


def _resolve_trial_dir(job_dir: Path, trial: int | str | None = None) -> Path | None:
    trial_dirs = iter_trial_dirs(job_dir)
    if not trial_dirs:
        return None
    if trial is None:
        return trial_dirs[0]
    if isinstance(trial, int):
        index = trial - 1
        return trial_dirs[index] if 0 <= index < len(trial_dirs) else None
    return next((path for path in trial_dirs if path.name == trial), None)


def _trial_summary(trial_dir: Path, trial: dict[str, Any]) -> dict[str, Any]:
    agent = trial.get("agent_info") or {}
    model_info = agent.get("model_info") or {}
    task_name = trial.get("task_name") or trial.get("trial_name") or trial_dir.name
    metrics = _native_metrics(trial_dir / "agent")
    success = _trial_success(trial)
    exception = trial.get("exception_info")

    return {
        "trial_no": _trial_number(trial_dir),
        "trial_name": trial.get("trial_name") or trial_dir.name,
        "task": task_name,
        "task_name": task_name,
        "variant": _variant_name(agent, model_info),
        "model": model_info.get("name"),
        "reasoning_effort": (
            ((trial.get("config") or {}).get("agent") or {})
            .get("kwargs", {})
            .get("reasoning_effort")
        ),
        "success": success,
        "duration_s": _duration_seconds(trial.get("started_at"), trial.get("finished_at")),
        "status": _trial_status(trial),
        "error": (exception or {}).get("exception_message"),
        "metrics": metrics,
    }


def _native_metrics(agent_dir: Path) -> dict[str, Any]:
    events = find_copilot_session_events(agent_dir)
    if events is None:
        trajectory = agent_dir / "trajectory.json"
        if not trajectory.exists():
            return {}
        analysis = analyze_trajectory(read_json(trajectory))
        return {
            "n_turns": analysis.n_turns,
            "n_assistant_messages": analysis.n_assistant_messages,
            "n_tool_calls": analysis.n_tool_calls,
            "n_tool_failures": analysis.n_tool_failures,
            "models": analysis.models,
            "duration_s": analysis.duration_s,
            "input_tokens": analysis.input_tokens,
            "output_tokens": analysis.output_tokens,
            "total_tokens": analysis.total_tokens,
            "cache_read_tokens": analysis.economics.cache_read_tokens,
            "reasoning_tokens": analysis.economics.reasoning_tokens,
            "aiu": analysis.economics.aiu,
            "peak_context_tokens": analysis.economics.peak_context_tokens,
            "n_compactions": analysis.economics.n_compactions,
        }
    parsed = parse_metrics(load_events(events))
    return parsed.model_dump(mode="json")


def _trial_success(trial: dict[str, Any]) -> bool | None:
    if trial.get("exception_info") is not None:
        return False
    rewards = (trial.get("verifier_result") or {}).get("rewards") or {}
    if not rewards:
        return None
    if "reward" in rewards:
        return float(rewards["reward"]) > 0
    return any(float(value) > 0 for value in rewards.values())


def _trial_status(trial: dict[str, Any]) -> str:
    if trial.get("exception_info") is not None:
        return "harness_error"
    return "ok"


def _job_status(job_result: dict[str, Any]) -> str:
    stats = job_result.get("stats") or {}
    errored = stats.get("n_errored_trials") or stats.get("n_errors") or 0
    pending = stats.get("n_pending_trials") or 0
    running = stats.get("n_running_trials") or 0
    if running or pending:
        return "running"
    return "failed" if errored else "completed"


def _aggregate_task(task_slug: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    graded = [trial["success"] for trial in trials if trial.get("success") is not None]
    aiu_values = [(trial.get("metrics") or {}).get("aiu") for trial in trials]
    total_aiu = sum(value for value in aiu_values if value is not None)
    solved = sum(1 for value in graded if value)
    return {
        "task": task_slug,
        "name": trials[0].get("task_name") or task_slug,
        "n_trials": len(trials),
        "success_rate": (solved / len(graded)) if graded else None,
        "resolved": None if not graded else int(any(graded)),
        "avg_duration_s": _avg([trial.get("duration_s") for trial in trials]),
        "avg_turns": _avg(_metric_values(trials, "n_turns")),
        "avg_total_tokens": _avg(_metric_values(trials, "total_tokens")),
        "cv_total_tokens": None,
        "avg_aiu": _avg(aiu_values),
        "cv_aiu": None,
        "total_aiu": round(total_aiu, 3) if total_aiu else None,
        "aiu_per_solve": round(total_aiu / solved, 3) if total_aiu and solved else None,
        "_trials": trials,
    }


def _aggregate_variant(trials: list[dict[str, Any]]) -> dict[str, Any]:
    graded = [trial["success"] for trial in trials if trial.get("success") is not None]
    solved = sum(1 for value in graded if value)
    aiu_values = [(trial.get("metrics") or {}).get("aiu") for trial in trials]
    total_aiu = sum(value for value in aiu_values if value is not None)
    return {
        "success_rate": (solved / len(graded)) if graded else None,
        "mean_resolved_rate": None,
        "resolved_at_k_rate": None,
        "avg_duration_s": _avg([trial.get("duration_s") for trial in trials]),
        "avg_turns": _avg(_metric_values(trials, "n_turns")),
        "avg_tool_calls": _avg(_metric_values(trials, "n_tool_calls")),
        "avg_tool_failures": _avg(_metric_values(trials, "n_tool_failures")),
        "avg_total_tokens": _avg(_metric_values(trials, "total_tokens")),
        "std_total_tokens": None,
        "cv_total_tokens": None,
        "avg_input_tokens": _avg(_metric_values(trials, "input_tokens")),
        "avg_output_tokens": _avg(_metric_values(trials, "output_tokens")),
        "avg_cache_read_tokens": _avg(_metric_values(trials, "cache_read_tokens")),
        "avg_reasoning_tokens": _avg(_metric_values(trials, "reasoning_tokens")),
        "avg_aiu": _avg(aiu_values),
        "std_aiu": None,
        "cv_aiu": None,
        "total_aiu": round(total_aiu, 3) if total_aiu else None,
        "aiu_per_solve": round(total_aiu / solved, 3) if total_aiu and solved else None,
        "avg_lines_added": _avg(_metric_values(trials, "lines_added")),
        "avg_files_modified": _avg(_metric_values(trials, "files_modified")),
        "avg_api_duration_s": _avg(
            [
                ((trial.get("metrics") or {}).get("api_duration_ms") or 0) / 1000
                for trial in trials
                if (trial.get("metrics") or {}).get("api_duration_ms") is not None
            ]
        ),
    }


def _strip_internal_trials(variant: dict[str, Any]) -> dict[str, Any]:
    variant = dict(variant)
    variant["tasks"] = [
        {key: value for key, value in task.items() if key != "_trials"}
        for task in variant.get("tasks", [])
    ]
    return variant


def _avg(values: list[Any]) -> float | None:
    nums = [float(value) for value in values if value is not None]
    return round(sum(nums) / len(nums), 3) if nums else None


def _metric_values(trials: list[dict[str, Any]], name: str) -> list[Any]:
    return [(trial.get("metrics") or {}).get(name) for trial in trials]


def _duration_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((finish - start).total_seconds(), 3)


def _variant_name(agent: dict[str, Any], model: dict[str, Any]) -> str:
    agent_name = agent.get("name") or "agent"
    model_name = model.get("name")
    return f"{agent_name}-{model_name}" if model_name else agent_name


def _trial_number(trial_dir: Path) -> int:
    for part in reversed(trial_dir.name.split("__")):
        if part.isdigit():
            return int(part)
    return 1
