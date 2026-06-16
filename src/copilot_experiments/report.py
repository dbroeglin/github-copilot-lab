"""Aggregate trial metrics into run summaries and human-readable reports."""

from __future__ import annotations

from statistics import mean, stdev

from .models import ExperimentRun, VariantResult


def _avg(values: list[float]) -> float | None:
    nums = [v for v in values if v is not None]
    return round(mean(nums), 3) if nums else None


def _std(values: list[float]) -> float | None:
    nums = [v for v in values if v is not None]
    return round(stdev(nums), 3) if len(nums) >= 2 else (0.0 if nums else None)


def _cv(values: list[float]) -> float | None:
    """Coefficient of variation (std / mean) -- the paper's headline variability measure."""
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return None
    m = mean(nums)
    return round(stdev(nums) / m, 3) if m else None


def _vals(trials: list, attr: str) -> list[float]:
    out = []
    for t in trials:
        v = getattr(t.metrics, attr, None)
        if v is not None:
            out.append(float(v))
    return out


def aggregate_variant(vr: VariantResult) -> dict:
    trials = vr.trials
    graded = [t.success for t in trials if t.success is not None]
    n_solved = sum(1 for s in graded if s)
    aiu = _vals(trials, "aiu")
    tokens = _vals(trials, "total_tokens")
    total_aiu = sum(aiu) if aiu else None
    return {
        "variant": vr.variant.slug,
        "name": vr.variant.name,
        "model": vr.variant.model,
        "reasoning_effort": vr.variant.reasoning_effort,
        "byok": vr.variant.provider is not None,
        "n_trials": len(trials),
        "success_rate": (n_solved / len(graded)) if graded else None,
        "avg_duration_s": _avg([t.duration_s for t in trials]),
        "avg_turns": _avg([float(t.metrics.n_turns) for t in trials]),
        "avg_tool_calls": _avg([float(t.metrics.n_tool_calls) for t in trials]),
        "avg_tool_failures": _avg([float(t.metrics.n_tool_failures) for t in trials]),
        "avg_total_tokens": _avg(tokens),
        "std_total_tokens": _std(tokens),
        "cv_total_tokens": _cv(tokens),
        "avg_input_tokens": _avg(_vals(trials, "input_tokens")),
        "avg_output_tokens": _avg(_vals(trials, "output_tokens")),
        "avg_cache_read_tokens": _avg(_vals(trials, "cache_read_tokens")),
        "avg_reasoning_tokens": _avg(_vals(trials, "reasoning_tokens")),
        "avg_aiu": _avg(aiu),
        "std_aiu": _std(aiu),
        "cv_aiu": _cv(aiu),
        "total_aiu": round(total_aiu, 3) if total_aiu is not None else None,
        # Cost-vs-accuracy: AIU spent per successfully solved task (lower is better).
        "aiu_per_solve": (round(total_aiu / n_solved, 3) if total_aiu and n_solved else None),
        "avg_lines_added": _avg(_vals(trials, "lines_added")),
        "avg_files_modified": _avg(_vals(trials, "files_modified")),
        "avg_api_duration_s": _avg([v / 1000 for v in _vals(trials, "api_duration_ms")]),
    }


def build_summary(run: ExperimentRun) -> dict:
    variant_summaries = [aggregate_variant(vr) for vr in run.variants]
    all_trials = [t for vr in run.variants for t in vr.trials]
    graded = [t.success for t in all_trials if t.success is not None]
    total_aiu = sum(_vals(all_trials, "aiu")) if all_trials else 0.0
    n_harness_errors = sum(1 for t in all_trials if t.status == "harness_error")
    n_copilot_failures = sum(1 for t in all_trials if t.status == "copilot_failed")
    return {
        "run_id": run.run_id,
        "experiment": run.experiment_name,
        "experiment_slug": run.experiment_slug,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "n_variants": len(run.variants),
        "n_trials": len(all_trials),
        "n_failed_trials": n_harness_errors + n_copilot_failures,
        "n_harness_errors": n_harness_errors,
        "n_copilot_failures": n_copilot_failures,
        "overall_success_rate": (sum(1 for s in graded if s) / len(graded)) if graded else None,
        "total_aiu": round(total_aiu, 3) if total_aiu else None,
        "variants": variant_summaries,
    }


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
    lines = [
        f"# {summary['experiment']}",
        "",
        f"- **Run:** `{summary['run_id']}`",
        f"- **Status:** {summary.get('status', '-')}",
        f"- **Started:** {summary['started_at']}",
        f"- **Finished:** {summary.get('finished_at') or '-'}",
        f"- **Variants:** {summary['n_variants']} · **Trials:** {summary['n_trials']}",
        f"- **Overall success rate:** {_pct(summary['overall_success_rate'])}",
        f"- **Total cost:** {_aiu(summary.get('total_aiu'))} AIU",
    ]
    n_failed = summary.get("n_failed_trials") or 0
    if n_failed:
        lines.append(
            f"- **⚠ Harness failures:** {n_failed} trial(s) did not run cleanly "
            f"({summary.get('n_harness_errors', 0)} harness, "
            f"{summary.get('n_copilot_failures', 0)} copilot) — see each trial's "
            "`stdout.txt`."
        )
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

    # Cost, variability, and productivity -- the paper's token-economics lens.
    if any(v.get("avg_aiu") is not None for v in summary["variants"]):
        lines += [
            "",
            "## Cost & token economics",
            "",
            "| Variant | Avg AIU | AIU CV | AIU / solve | Avg tokens | Token CV "
            "| Avg cache-read | Avg lines + | API time (s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for v in summary["variants"]:
            lines.append(
                "| {name} | {aiu} | {cva} | {aps} | {tok} | {cvt} | {cr} | {la} | {api} |".format(
                    name=v["name"],
                    aiu=_aiu(v.get("avg_aiu")),
                    cva=_fmt(v.get("cv_aiu")),
                    aps=_aiu(v.get("aiu_per_solve")),
                    tok=_fmt(v.get("avg_total_tokens")),
                    cvt=_fmt(v.get("cv_total_tokens")),
                    cr=_fmt(v.get("avg_cache_read_tokens")),
                    la=_fmt(v.get("avg_lines_added")),
                    api=_fmt(v.get("avg_api_duration_s")),
                )
            )
    lines.append("")
    return "\n".join(lines)
