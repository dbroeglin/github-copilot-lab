"""Offline tests for the SWE-bench integration (no Docker, no network)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from copilot_experiments import Experiment, Task, Variant, run_experiment
from copilot_experiments.invoker import MockInvoker
from copilot_experiments.models import SweBenchInstance
from copilot_experiments.storage import Layout
from copilot_experiments.swebench import (
    DEFAULT_DATASET,
    PredictionFile,
    SweBenchError,
    export_pier_predictions,
    export_predictions,
    grade_pier_job,
    grade_run,
    instance_to_task,
    load_instances,
    load_tasks,
    materialize_pier_swebench,
    parse_report,
)

# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #
SAMPLE_INSTANCE = {
    "instance_id": "acme__widget-42",
    "repo": "acme/widget",
    "base_commit": "abc123",
    "environment_setup_commit": "def456",
    "version": "1.2",
    "difficulty": "easy",
    "problem_statement": "The frobnicator crashes on empty input.",
    # SWE-bench stores these as JSON-encoded strings on Hugging Face.
    "FAIL_TO_PASS": '["tests/test_frob.py::test_empty"]',
    "PASS_TO_PASS": '["tests/test_frob.py::test_basic"]',
}


def _write_instances(path: Path, records: list[dict]) -> Path:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def test_load_instances_from_json_file(tmp_path: Path):
    f = _write_instances(tmp_path / "inst.json", [SAMPLE_INSTANCE])
    records = load_instances(instances_file=f)
    assert len(records) == 1
    assert records[0]["instance_id"] == "acme__widget-42"


def test_load_instances_from_jsonl(tmp_path: Path):
    f = tmp_path / "inst.jsonl"
    f.write_text(json.dumps(SAMPLE_INSTANCE) + "\n", encoding="utf-8")
    records = load_instances(instances_file=f)
    assert records[0]["repo"] == "acme/widget"


def test_load_instances_id_filter_and_limit(tmp_path: Path):
    a = {**SAMPLE_INSTANCE, "instance_id": "a"}
    b = {**SAMPLE_INSTANCE, "instance_id": "b"}
    c = {**SAMPLE_INSTANCE, "instance_id": "c"}
    f = _write_instances(tmp_path / "inst.json", [a, b, c])

    selected = load_instances(instances_file=f, instance_ids=["c", "a"])
    assert [r["instance_id"] for r in selected] == ["c", "a"]
    assert [r["instance_id"] for r in load_instances(instances_file=f, limit=2)] == ["a", "b"]


def test_load_instances_missing_id_raises(tmp_path: Path):
    f = _write_instances(tmp_path / "inst.json", [SAMPLE_INSTANCE])
    with pytest.raises(SweBenchError):
        load_instances(instances_file=f, instance_ids=["nope"])


def test_instance_to_task_metadata():
    task = instance_to_task(SAMPLE_INSTANCE)
    assert task.name == "acme__widget-42"
    assert task.repo == "https://github.com/acme/widget.git"
    assert task.ref == "abc123"
    assert "frobnicator crashes" in task.prompt
    assert task.swebench is not None
    swe = task.swebench
    assert swe.instance_id == "acme__widget-42"
    assert swe.dataset == DEFAULT_DATASET
    assert swe.difficulty == "easy"
    # JSON-encoded test lists are decoded.
    assert swe.fail_to_pass == ["tests/test_frob.py::test_empty"]
    assert swe.pass_to_pass == ["tests/test_frob.py::test_basic"]


def test_load_tasks(tmp_path: Path):
    f = _write_instances(tmp_path / "inst.json", [SAMPLE_INSTANCE])
    tasks = load_tasks(instances_file=f)
    assert len(tasks) == 1 and tasks[0].swebench.instance_id == "acme__widget-42"


def test_instance_to_task_requires_instance_id():
    with pytest.raises(SweBenchError):
        instance_to_task({"repo": "x/y"})


def test_materialize_pier_swebench_writes_tasks_and_job(tmp_path: Path):
    from copilot_experiments.pier_backend import discover_pier_job_configs

    materialized = materialize_pier_swebench(
        tmp_path,
        [SAMPLE_INSTANCE],
        name="SWE smoke",
        models=["gpt-5-mini"],
        effort="low",
        trials=2,
    )

    assert materialized.instances_path.exists()
    assert materialized.job_path == tmp_path / "experiments" / "swe-smoke.yaml"
    task_dir = tmp_path / "tasks" / "acme-widget-42"
    assert task_dir in materialized.task_dirs
    assert (task_dir / "task.toml").exists()
    assert (task_dir / "instruction.md").read_text(encoding="utf-8").startswith("You are working")
    assert "git clone" in (task_dir / "environment" / "Dockerfile").read_text(encoding="utf-8")

    specs = discover_pier_job_configs(tmp_path)
    assert len(specs) == 1
    assert specs[0].config.job_name == "swe-smoke"
    assert specs[0].config.n_attempts == 2
    assert specs[0].config.verifier.disable is True
    assert specs[0].config.tasks[0].path == task_dir.resolve()


# --------------------------------------------------------------------------- #
# Report parsing
# --------------------------------------------------------------------------- #
def test_parse_report(tmp_path: Path):
    report = tmp_path / "model.run.json"
    report.write_text(
        json.dumps({"resolved_ids": ["a", "b"], "unresolved_ids": ["c"]}), encoding="utf-8"
    )
    assert parse_report(report) == {"a", "b"}


# --------------------------------------------------------------------------- #
# Predictions export + grading (end-to-end with a stub evaluator)
# --------------------------------------------------------------------------- #
class StubEvaluator:
    """Resolve exactly the configured instance ids (when they have a non-empty patch)."""

    def __init__(self, resolve: set[str] | None = None):
        self.resolve = resolve
        self.calls: list[PredictionFile] = []

    def evaluate(self, pf: PredictionFile, *, run_id: str, work_dir: Path) -> set[str]:
        self.calls.append(pf)
        resolved: set[str] = set()
        for line in pf.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if not rec["model_patch"].strip():
                continue
            iid = rec["instance_id"]
            if self.resolve is None or iid in self.resolve:
                resolved.add(iid)
        return resolved


def _swe_task(name: str, instance_id: str, difficulty: str, fixture: str) -> Task:
    return Task(
        name=name,
        prompt="Fix the bug described in the issue.",
        fixture=fixture,
        swebench=SweBenchInstance(
            instance_id=instance_id,
            dataset="local-test",
            repo="local/test",
            base_commit="0" * 40,
            difficulty=difficulty,
            fail_to_pass=[f"tests/test_{name}.py::test_it"],
        ),
    )


@pytest.fixture
def swe_run(tmp_path: Path):
    """Persist a finished 2-instance × 2-trial SWE-bench run solved by the mock invoker."""
    fixtures = tmp_path / "fixtures" / "seed"
    fixtures.mkdir(parents=True)
    (fixtures / "seed.txt").write_text("seed\n", encoding="utf-8")

    experiment = Experiment(
        name="SWE test",
        tasks=[
            _swe_task("inst-a", "local__a-1", "easy", "fixtures/seed"),
            _swe_task("inst-b", "local__b-1", "hard", "fixtures/seed"),
        ],
        variants=[Variant(name="default", model="m", trials=2)],
    )

    def solve(workspace: Path) -> None:
        (workspace / "SOLVED").write_text("done\n", encoding="utf-8")

    run = run_experiment(
        experiment,
        root=tmp_path,
        invoker=MockInvoker(solver=solve),
        session_state_root=tmp_path / ".session-state",
    )
    layout = Layout(tmp_path)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    return tmp_path, layout, run_dir


def test_export_predictions_groups_by_variant_trial(swe_run):
    _root, _layout, run_dir = swe_run
    pred_files = export_predictions(run_dir)
    # One variant × two trials -> two predictions files.
    assert len(pred_files) == 2
    for pf in pred_files:
        assert pf.path.exists()
        raw = pf.path.read_text(encoding="utf-8").splitlines()
        lines = [json.loads(x) for x in raw if x.strip()]
        # Both instances appear once each in every (variant, trial) file.
        ids = sorted(rec["instance_id"] for rec in lines)
        assert ids == ["local__a-1", "local__b-1"]
        for rec in lines:
            assert rec["model_name_or_path"] == "default"
            assert "SOLVED" in rec["model_patch"]


def test_grade_run_writes_back_success_and_regrades(swe_run):
    _root, layout, run_dir = swe_run
    evaluator = StubEvaluator()  # resolve everything with a non-empty patch
    report = grade_run(run_dir, evaluator=evaluator, layout=layout)

    # 2 instances × 2 trials graded, all resolved.
    assert report.n_graded == 4
    assert report.n_resolved == 4

    # Per-trial write-back: meta.json success + swebench.json verdict.
    trial = run_dir / "variants" / "default" / "tasks" / "inst-a" / "trials" / "001"
    assert json.loads((trial / "meta.json").read_text(encoding="utf-8"))["success"] is True
    swe_json = json.loads((trial / "swebench.json").read_text(encoding="utf-8"))
    assert swe_json["instance_id"] == "local__a-1" and swe_json["resolved"] is True

    # Re-aggregated summary reflects ground-truth resolution.
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall_success_rate"] == 1.0


def test_grade_run_partial_resolution_and_difficulty(swe_run):
    _root, layout, run_dir = swe_run
    # Resolve only the easy instance.
    report = grade_run(run_dir, evaluator=StubEvaluator(resolve={"local__a-1"}), layout=layout)
    assert report.n_resolved == 2  # easy instance across 2 trials

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    buckets = {d["difficulty"]: d for d in summary["difficulty_breakdown"]}
    assert set(buckets) == {"easy", "hard"}
    assert buckets["easy"]["resolved_at_k_rate"] == 1.0
    assert buckets["hard"]["resolved_at_k_rate"] == 0.0
    assert buckets["easy"]["n_instances"] == 1

    md = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "Difficulty vs cost" in md


def test_grade_run_derives_layout_when_omitted(swe_run):
    """With no explicit layout, grade_run derives results_root from the run dir."""
    root, _layout, run_dir = swe_run
    grade_run(run_dir, evaluator=StubEvaluator())
    assert (root / "results" / "index.db").exists()


def test_export_predictions_uses_variant_slug_not_name(tmp_path: Path):
    """A variant whose name differs from its slug must still resolve trial paths."""
    fixtures = tmp_path / "fixtures" / "seed"
    fixtures.mkdir(parents=True)
    (fixtures / "seed.txt").write_text("seed\n", encoding="utf-8")

    experiment = Experiment(
        name="SWE slug test",
        tasks=[_swe_task("inst-a", "local__a-1", "easy", "fixtures/seed")],
        # "claude-sonnet-4.5" slugifies to "claude-sonnet-4-5".
        variants=[Variant(name="claude-sonnet-4.5", model="m", trials=1)],
    )

    def solve(workspace: Path) -> None:
        (workspace / "SOLVED").write_text("done\n", encoding="utf-8")

    run = run_experiment(
        experiment,
        root=tmp_path,
        invoker=MockInvoker(solver=solve),
        session_state_root=tmp_path / ".session-state",
    )
    run_dir = Layout(tmp_path).run_dir(experiment.slug, run.run_id)

    pred_files = export_predictions(run_dir)
    assert len(pred_files) == 1
    pf = pred_files[0]
    assert pf.variant_slug == "claude-sonnet-4-5"
    # The predictions file lives under the slug directory and the diff was found.
    assert "claude-sonnet-4-5" in str(pf.path)
    rec = json.loads(pf.path.read_text(encoding="utf-8").strip())
    assert "SOLVED" in rec["model_patch"]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_pier_swebench_job(tmp_path: Path) -> tuple[Path, Path]:
    task_dir = tmp_path / "tasks" / "acme-widget-42"
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text(
        "\n".join(
            [
                'version = "1.0"',
                "",
                "[task]",
                'name = "swebench/acme__widget-42"',
                "",
                "[metadata]",
                'dataset = "local-test"',
                'instance_id = "acme__widget-42"',
                'difficulty = "easy"',
            ]
        ),
        encoding="utf-8",
    )

    job_dir = tmp_path / "jobs" / "swe-job"
    _write_json(job_dir / "config.json", {"job_name": "swe-job"})
    _write_json(job_dir / "result.json", {"stats": {"n_errored_trials": 0}})
    trial_dir = job_dir / "copilot-cli__acme-widget-42__1"
    _write_json(
        trial_dir / "result.json",
        {
            "trial_name": trial_dir.name,
            "task_name": "swebench/acme__widget-42",
            "agent_info": {"name": "copilot-cli", "model_info": {"name": "gpt-5-mini"}},
            "config": {"task": {"path": str(task_dir)}},
            "verifier_result": {"rewards": {}},
        },
    )

    repo = trial_dir / "artifacts" / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "widget.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "widget.py").write_text("value = 2\n", encoding="utf-8")
    return job_dir, trial_dir


def test_export_pier_predictions_reads_swebench_metadata_and_artifact_diff(tmp_path: Path):
    job_dir, _trial_dir = _make_pier_swebench_job(tmp_path)

    pred_files = export_pier_predictions(job_dir)

    assert len(pred_files) == 1
    pf = pred_files[0]
    assert pf.dataset == "local-test"
    assert pf.instances == {"acme__widget-42": job_dir / "copilot-cli__acme-widget-42__1"}
    rec = json.loads(pf.path.read_text(encoding="utf-8"))
    assert rec["instance_id"] == "acme__widget-42"
    assert "-value = 1" in rec["model_patch"]
    assert "+value = 2" in rec["model_patch"]


def test_grade_pier_job_writes_back_rewards_summary_and_index(tmp_path: Path):
    job_dir, trial_dir = _make_pier_swebench_job(tmp_path)

    report = grade_pier_job(job_dir, evaluator=StubEvaluator(), layout=Layout(tmp_path))

    assert report.n_graded == 1
    assert report.n_resolved == 1
    result = json.loads((trial_dir / "result.json").read_text(encoding="utf-8"))
    assert result["verifier_result"]["rewards"]["reward"] == 1.0
    assert json.loads((trial_dir / "swebench.json").read_text(encoding="utf-8"))["resolved"] is True
    summary = json.loads((job_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall_success_rate"] == 1.0
    assert (tmp_path / "results" / "index.db").exists()


def test_grade_run_without_swebench_tasks_raises(repo_root: Path, experiment):
    run = run_experiment(
        experiment,
        root=repo_root,
        invoker=MockInvoker(),
        session_state_root=repo_root / ".session-state",
    )
    layout = Layout(repo_root)
    run_dir = layout.run_dir(experiment.slug, run.run_id)
    with pytest.raises(SweBenchError):
        grade_run(run_dir, evaluator=StubEvaluator(), layout=layout)
