"""Filesystem layout for Pier-first experiment repositories.

The filesystem is the source of truth. Concrete Pier runs live under::

    jobs/
      <job-name>/
        <run-id>/
          config.json
          result.json
          copilot-experiments-run.json
          <trial-name>/
            config.json
            result.json
            agent/
              trajectory.json
              copilot-cli.jsonl
              copilot-otel.jsonl
              copilot-session/**/events.jsonl
            verifier/
            artifacts/
"""

from __future__ import annotations

from pathlib import Path

from .pier_results import PIER_RUN_MANIFEST


class Layout:
    """Resolve the standard paths for a Pier experiment repository."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    @property
    def experiments_dir(self) -> Path:
        return self.root / "experiments"

    def iter_pier_jobs(self) -> list[Path]:
        """Return concrete Pier run directories under ``jobs/<job>/<run-id>``."""

        if not self.jobs_dir.exists():
            return []
        runs: list[Path] = []
        for job_group in sorted(path for path in self.jobs_dir.iterdir() if path.is_dir()):
            runs.extend(
                run_dir
                for run_dir in sorted(path for path in job_group.iterdir() if path.is_dir())
                if self._is_pier_run_dir(run_dir)
            )
        return sorted(runs, key=self._pier_run_sort_key)

    def find_pier_job(self, selector: str) -> Path | None:
        """Locate a Pier run by job name, run id, ``job/run`` id, or unique prefix."""

        runs = self.iter_pier_jobs()

        group = self.jobs_dir / selector
        group_runs = [path for path in runs if path.parent == group]
        if group_runs:
            return group_runs[-1]

        exact = [
            path for path in runs if path.name == selector or self.pier_job_key(path) == selector
        ]
        if len(exact) == 1:
            return exact[0]

        prefix = [
            path
            for path in runs
            if path.name.startswith(selector) or self.pier_job_key(path).startswith(selector)
        ]
        return prefix[0] if len(prefix) == 1 else None

    def latest_pier_job(self) -> Path | None:
        runs = self.iter_pier_jobs()
        return runs[-1] if runs else None

    def pier_job_key(self, job_dir: Path) -> str:
        """Return the stable ``job/run`` selector for a concrete Pier run directory."""

        job_dir = Path(job_dir)
        return f"{job_dir.parent.name}/{job_dir.name}"

    @staticmethod
    def _is_pier_run_dir(path: Path) -> bool:
        return (
            (path / "config.json").exists()
            and (path / "result.json").exists()
            and (path / PIER_RUN_MANIFEST).exists()
        )

    @staticmethod
    def _pier_run_sort_key(path: Path) -> tuple[str, str]:
        return (path.parent.name, path.name)
