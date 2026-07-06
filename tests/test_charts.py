"""Tests for the interactive HTML result dashboards."""

from __future__ import annotations

from pathlib import Path

import pytest

from copilot_experiments import charts
from copilot_experiments.charts import (
    ChartError,
    build_dashboard_html,
    plotly_available,
    write_dashboard,
)

_MULTI_TASK_SUMMARY = {
    "run_id": "20260612T103300Z_a1b2c3",
    "job": "strtools-vs-csvtools",
    "pier_job_id": "strtools/20260612T103300Z_a1b2c3",
    "status": "completed",
    "started_at": "2026-06-12T10:33:00Z",
    "finished_at": "2026-06-12T10:52:11Z",
    "n_agents": 2,
    "n_tasks": 2,
    "n_trials": 12,
    "n_failed_trials": 0,
    "overall_success_rate": 0.75,
    "total_aiu": 3.21,
    "agents": [
        {
            "name": "sonnet-4.6",
            "model": "claude-sonnet-4.6",
            "reasoning_effort": "medium",
            "n_tasks": 2,
            "n_trials": 6,
            "success_rate": 0.83,
            "resolved_at_k_rate": 1.0,
            "avg_aiu": 0.21,
            "std_aiu": 0.04,
            "aiu_per_solve": 0.25,
            "avg_total_tokens": 120000,
            "std_total_tokens": 15000,
            "tasks": [
                {"task": "strtools", "name": "strtools", "success_rate": 1.0, "resolved_rate": 1.0},
                {
                    "task": "csvtools",
                    "name": "csvtools",
                    "success_rate": 0.66,
                    "resolved_rate": 1.0,
                },
            ],
        },
        {
            "name": "haiku-4.5",
            "model": "claude-haiku-4.5",
            "reasoning_effort": None,
            "n_tasks": 2,
            "n_trials": 6,
            "success_rate": 0.5,
            "resolved_at_k_rate": 0.5,
            "avg_aiu": 0.08,
            "std_aiu": 0.02,
            "aiu_per_solve": 0.16,
            "avg_total_tokens": 90000,
            "std_total_tokens": 8000,
            "tasks": [
                {"task": "strtools", "name": "strtools", "success_rate": 1.0, "resolved_rate": 1.0},
                {"task": "csvtools", "name": "csvtools", "success_rate": 0.0, "resolved_rate": 0.0},
            ],
        },
    ],
}

_SINGLE_TASK_SUMMARY = {
    "run_id": "run-1",
    "job": "textstats",
    "pier_job_id": "textstats/run-1",
    "status": "completed",
    "n_agents": 2,
    "n_tasks": 1,
    "n_trials": 4,
    "overall_success_rate": 0.75,
    "total_aiu": 0.9,
    "agents": [
        {
            "name": "agent-a",
            "model": "model-a",
            "reasoning_effort": "high",
            "n_tasks": 1,
            "n_trials": 2,
            "success_rate": 1.0,
            "resolved_at_k_rate": 1.0,
            "avg_aiu": 0.3,
            "std_aiu": 0.05,
            "aiu_per_solve": 0.3,
            "avg_total_tokens": 150000,
            "tasks": [
                {
                    "task": "textstats",
                    "name": "textstats",
                    "success_rate": 1.0,
                    "resolved_rate": 1.0,
                }
            ],
        },
        {
            "name": "agent-b",
            "model": "model-b",
            "reasoning_effort": "low",
            "n_tasks": 1,
            "n_trials": 2,
            "success_rate": 0.5,
            "resolved_at_k_rate": 1.0,
            "avg_aiu": 0.15,
            "std_aiu": 0.02,
            "aiu_per_solve": 0.3,
            "avg_total_tokens": 80000,
            "tasks": [
                {
                    "task": "textstats",
                    "name": "textstats",
                    "success_rate": 0.5,
                    "resolved_rate": 1.0,
                }
            ],
        },
    ],
}


def test_build_dashboard_html_has_all_sections():
    html = build_dashboard_html(_MULTI_TASK_SUMMARY, cdn=True)

    assert html.startswith("<!DOCTYPE html>")
    assert "Plotly.newPlot" in html
    for div_id in ("chart-resolution", "chart-scatter", "chart-cost", "chart-heatmap"):
        assert div_id in html
    assert "Leaderboard" in html
    assert "strtools-vs-csvtools" in html  # job title
    assert "claude-sonnet-4.6" in html  # leaderboard model column


def test_build_dashboard_cdn_is_small_and_references_cdn():
    html = build_dashboard_html(_MULTI_TASK_SUMMARY, cdn=True)

    assert "https://cdn.plot.ly/plotly-" in html
    assert "<script>" not in html.split("<body>")[0]  # bundle not embedded in <head>
    assert len(html) < 200_000


def test_build_dashboard_offline_embeds_plotly_bundle():
    html = build_dashboard_html(_MULTI_TASK_SUMMARY)

    # The offline build inlines the full plotly.js bundle for zero-dependency viewing.
    assert "https://cdn.plot.ly/plotly-" not in html.split("<body>")[0]
    assert len(html) > 1_000_000


def test_single_task_summary_skips_heatmap():
    html = build_dashboard_html(_SINGLE_TASK_SUMMARY, cdn=True)

    assert "chart-resolution" in html
    assert "chart-heatmap" not in html


def test_empty_summary_renders_message_without_charts():
    html = build_dashboard_html({"job": "empty", "n_tasks": 0, "agents": []}, cdn=True)

    assert "No agent metrics" in html
    assert "Plotly.newPlot" not in html


def test_write_dashboard_writes_summary_html(tmp_path: Path):
    out = write_dashboard(tmp_path, summary=_MULTI_TASK_SUMMARY, cdn=True)

    assert out == tmp_path / "summary.html"
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_write_dashboard_honors_custom_out_path(tmp_path: Path):
    target = tmp_path / "nested" / "report.html"

    out = write_dashboard(tmp_path, summary=_SINGLE_TASK_SUMMARY, out_path=target, cdn=True)

    assert out == target
    assert target.exists()


def test_graceful_degradation_when_plotly_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        charts, "_PLOTLY_IMPORT_ERROR", ModuleNotFoundError("No module named 'plotly'")
    )

    assert plotly_available() is False
    with pytest.raises(ChartError) as excinfo:
        build_dashboard_html(_MULTI_TASK_SUMMARY)
    assert "charts" in str(excinfo.value).lower()

    with pytest.raises(ChartError):
        write_dashboard(tmp_path, summary=_MULTI_TASK_SUMMARY)
