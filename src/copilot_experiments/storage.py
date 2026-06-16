"""Filesystem layout for experiment results.

Layout (inside an experiment repository)::

    results/
      index.db                                  # SQLite cross-run index
      <experiment-slug>/
        <run-id>/
          run.json                              # run manifest
          summary.json                          # aggregated metrics
          summary.md                            # human-readable report
          variants/
            <variant-slug>/
              variant.json                      # variant config (secrets redacted)
              trials/
                <NNN>/
                  meta.json                     # session id, exit code, duration, success, status
                  prompt.md                     # exact prompt sent
                  stdout.txt                    # raw copilot stdout/stderr (diagnostics)
                  session.md                    # copilot's markdown transcript (--share)
                  events.jsonl                  # copied session events (structured source)
                  metrics.json                  # parsed metrics
                  analysis.json                 # richer session analysis
                  workspace.diff                # git diff of the workspace
                  verify.json                   # verification result (if any)
                  workspace/                    # the trial's working directory
"""

from __future__ import annotations

from pathlib import Path


class Layout:
    """Resolves the standard result paths for an experiment repository.

    ``root`` is where the experiment definitions and fixtures live. ``results_root``
    is where run artifacts are *written*; it defaults to ``root/results`` but can be
    pointed elsewhere (e.g. a throwaway temp dir for an ephemeral dry-run) so that
    reading fixtures and writing results are decoupled.
    """

    def __init__(self, root: Path, *, results_root: Path | None = None) -> None:
        self.root = Path(root)
        self._results_root = Path(results_root) if results_root is not None else None

    @property
    def results_dir(self) -> Path:
        return self._results_root if self._results_root is not None else self.root / "results"

    @property
    def index_db(self) -> Path:
        return self.results_dir / "index.db"

    @property
    def experiments_dir(self) -> Path:
        return self.root / "experiments"

    def experiment_dir(self, experiment_slug: str) -> Path:
        return self.results_dir / experiment_slug

    def run_dir(self, experiment_slug: str, run_id: str) -> Path:
        return self.experiment_dir(experiment_slug) / run_id

    def variant_dir(self, experiment_slug: str, run_id: str, variant_slug: str) -> Path:
        return self.run_dir(experiment_slug, run_id) / "variants" / variant_slug

    def trial_dir(
        self, experiment_slug: str, run_id: str, variant_slug: str, trial_no: int
    ) -> Path:
        return (
            self.variant_dir(experiment_slug, run_id, variant_slug)
            / "trials"
            / f"{trial_no:03d}"
        )

    # --- discovery helpers ------------------------------------------------- #
    def iter_runs(self) -> list[tuple[str, str, Path]]:
        """Yield ``(experiment_slug, run_id, run_dir)`` for every stored run."""
        runs: list[tuple[str, str, Path]] = []
        if not self.results_dir.exists():
            return runs
        for exp_dir in sorted(p for p in self.results_dir.iterdir() if p.is_dir()):
            for run_dir in sorted(p for p in exp_dir.iterdir() if p.is_dir()):
                if (run_dir / "run.json").exists():
                    runs.append((exp_dir.name, run_dir.name, run_dir))
        return runs

    def find_run(self, run_id: str) -> Path | None:
        """Locate a run directory by exact id or unique prefix."""
        matches = [rd for _, rid, rd in self.iter_runs() if rid == run_id]
        if matches:
            return matches[0]
        prefix = [rd for _, rid, rd in self.iter_runs() if rid.startswith(run_id)]
        return prefix[0] if len(prefix) == 1 else None

    def latest_run(self) -> Path | None:
        runs = self.iter_runs()
        return runs[-1][2] if runs else None
