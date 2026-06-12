"""Aggregate trial metrics into run summaries and human-readable reports."""

from __future__ import annotations

from statistics import mean

from .models import ExperimentRun, VariantResult


def _avg(values: list[float]) -> float | None:
    nums = [v for v in values if v is not None]
    return round(mean(nums), 3) if nums else None


def aggregate_variant(vr: VariantResult) -> dict:
    trials = vr.trials
    graded = [t.success for t in trials if t.success is not None]
    return {
        "variant": vr.variant.slug,
        "name": vr.variant.name,
        "model": vr.variant.model,
        "reasoning_effort": vr.variant.reasoning_effort,
        "byok": vr.variant.provider is not None,
        "n_trials": len(trials),
        "success_rate": (sum(1 for s in graded if s) / len(graded)) if graded else None,
        "avg_duration_s": _avg([t.duration_s for t in trials]),
        "avg_turns": _avg([float(t.metrics.n_turns) for t in trials]),
        "avg_tool_calls": _avg([float(t.metrics.n_tool_calls) for t in trials]),
        "avg_tool_failures": _avg([float(t.metrics.n_tool_failures) for t in trials]),
        "avg_total_tokens": _avg(
            [float(t.metrics.total_tokens) for t in trials if t.metrics.total_tokens is not None]
        ),
    }


def build_summary(run: ExperimentRun) -> dict:
    variant_summaries = [aggregate_variant(vr) for vr in run.variants]
    all_trials = [t for vr in run.variants for t in vr.trials]
    graded = [t.success for t in all_trials if t.success is not None]
    return {
        "run_id": run.run_id,
        "experiment": run.experiment_name,
        "experiment_slug": run.experiment_slug,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "n_variants": len(run.variants),
        "n_trials": len(all_trials),
        "overall_success_rate": (sum(1 for s in graded if s) / len(graded)) if graded else None,
        "variants": variant_summaries,
    }


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def summary_markdown(summary: dict, description: str = "") -> str:
    lines = [
        f"# {summary['experiment']}",
        "",
        f"- **Run:** `{summary['run_id']}`",
        f"- **Started:** {summary['started_at']}",
        f"- **Finished:** {summary.get('finished_at') or '-'}",
        f"- **Variants:** {summary['n_variants']} · **Trials:** {summary['n_trials']}",
        f"- **Overall success rate:** {_pct(summary['overall_success_rate'])}",
    ]
    if description:
        lines += ["", description]
    lines += [
        "",
        "| Variant | Model | Effort | BYOK | Trials | Success | Avg dur (s) | Avg turns "
        "| Tool calls | Tool fails | Avg tokens |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for v in summary["variants"]:
        lines.append(
            "| {name} | {model} | {effort} | {byok} | {n} | {sr} | {dur} | {turns} | "
            "{calls} | {fails} | {tokens} |".format(
                name=v["name"],
                model=_fmt(v["model"]),
                effort=_fmt(v["reasoning_effort"]),
                byok="yes" if v["byok"] else "no",
                n=v["n_trials"],
                sr=_pct(v["success_rate"]),
                dur=_fmt(v["avg_duration_s"]),
                turns=_fmt(v["avg_turns"]),
                calls=_fmt(v["avg_tool_calls"]),
                fails=_fmt(v["avg_tool_failures"]),
                tokens=_fmt(v["avg_total_tokens"]),
            )
        )
    lines.append("")
    return "\n".join(lines)
