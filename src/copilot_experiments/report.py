"""Markdown reports for Pier job runs."""

from __future__ import annotations


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _aiu(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.3f}" if float(value) < 1 else f"{float(value):,.2f}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def summary_markdown(summary: dict, description: str = "") -> str:
    """Render a Pier run summary as Markdown."""

    lines = [
        f"# {summary['job']}",
        "",
        f"- **Run:** `{summary['run_id']}`",
        f"- **Selector:** `{summary['pier_job_id']}`",
        f"- **Status:** {summary.get('status', '-')}",
        f"- **Started:** {summary['started_at']}",
        f"- **Finished:** {summary.get('finished_at') or '-'}",
        f"- **Agents:** {summary['n_agents']} · **Tasks:** {summary.get('n_tasks', 1)} "
        f"· **Trials:** {summary['n_trials']}",
        f"- **Overall success rate:** {_pct(summary['overall_success_rate'])}",
        f"- **Total cost:** {_aiu(summary.get('total_aiu'))} AIU",
    ]
    n_failed = summary.get("n_failed_trials") or 0
    if n_failed:
        lines.append(
            f"- **⚠ Harness failures:** {n_failed} trial(s) did not run cleanly "
            f"({summary.get('n_harness_errors', 0)} harness, "
            f"{summary.get('n_copilot_failures', 0)} copilot)."
        )
    if description:
        lines += ["", description]

    lines += [
        "",
        "| Agent | Model | Effort | Tasks | Trials | Success | Avg dur (s) | Avg turns "
        "| Tool calls | Tool fails | Avg tokens |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for agent in summary["agents"]:
        lines.append(
            "| {name} | {model} | {effort} | {tasks} | {trials} | {success} | {dur} | "
            "{turns} | {calls} | {fails} | {tokens} |".format(
                name=agent["name"],
                model=_fmt(agent["model"]),
                effort=_fmt(agent["reasoning_effort"]),
                tasks=agent["n_tasks"],
                trials=agent["n_trials"],
                success=_pct(agent["success_rate"]),
                dur=_fmt(agent["avg_duration_s"]),
                turns=_fmt(agent["avg_turns"]),
                calls=_fmt(agent["avg_tool_calls"]),
                fails=_fmt(agent["avg_tool_failures"]),
                tokens=_fmt(agent["avg_total_tokens"]),
            )
        )

    if any(agent.get("avg_aiu") is not None for agent in summary["agents"]):
        lines += [
            "",
            "| Agent | Avg AIU | AIU CV | AIU / solve | Avg tokens | Token CV "
            "| Avg API duration (s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for agent in summary["agents"]:
            lines.append(
                "| {name} | {avg_aiu} | {aiu_cv} | {aiu_solve} | {tokens} | {token_cv} | "
                "{api} |".format(
                    name=agent["name"],
                    avg_aiu=_aiu(agent.get("avg_aiu")),
                    aiu_cv=_fmt(agent.get("cv_aiu")),
                    aiu_solve=_aiu(agent.get("aiu_per_solve")),
                    tokens=_fmt(agent.get("avg_total_tokens")),
                    token_cv=_fmt(agent.get("cv_total_tokens")),
                    api=_fmt(agent.get("avg_api_duration_s")),
                )
            )

    if summary.get("n_tasks", 1) > 1:
        lines += [
            "",
            "## Task suite coverage",
            "",
            "| Agent | Tasks | Mean success | Resolved@k |",
            "| --- | ---: | ---: | ---: |",
        ]
        for agent in summary["agents"]:
            lines.append(
                f"| {agent['name']} | {agent.get('n_tasks', '-')} | "
                f"{_pct(agent.get('mean_resolved_rate'))} | "
                f"{_pct(agent.get('resolved_at_k_rate'))} |"
            )

        lines += [
            "",
            "| Agent | Task | Trials | Mean success | Resolved@k | Avg AIU |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for agent in summary["agents"]:
            for task in agent.get("tasks", []):
                lines.append(
                    f"| {agent['name']} | {task['task_slug']} | {task['n_trials']} | "
                    f"{_pct(task.get('success_rate'))} | {_pct(task.get('resolved_rate'))} | "
                    f"{_aiu(task.get('avg_aiu'))} |"
                )

    return "\n".join(lines) + "\n"
