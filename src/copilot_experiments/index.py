"""SQLite index over the ``results/`` filesystem for cross-run queries.

The filesystem is the source of truth; the database is a derived, rebuildable
index. :func:`reindex` drops and rebuilds it by scanning ``results/``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ._util import read_json
from .storage import Layout

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    slug         TEXT PRIMARY KEY,
    name         TEXT,
    description  TEXT,
    first_seen   TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    experiment_slug  TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    git_base         TEXT,
    n_variants       INTEGER,
    status           TEXT
);
CREATE TABLE IF NOT EXISTS variants (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    variant_slug  TEXT,
    model         TEXT,
    reasoning_effort TEXT,
    agent         TEXT,
    mode          TEXT,
    byok          INTEGER,
    params_json   TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    variant_slug  TEXT,
    task_slug     TEXT,
    task_name     TEXT,
    instance_id   TEXT,
    difficulty    TEXT,
    n_trials      INTEGER,
    success_rate  REAL,
    resolved      INTEGER
);
CREATE TABLE IF NOT EXISTS trials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    variant_slug    TEXT,
    task_slug       TEXT,
    trial_no        INTEGER,
    session_id      TEXT,
    exit_code       INTEGER,
    duration_s      REAL,
    success         INTEGER,
    n_turns         INTEGER,
    n_tool_calls    INTEGER,
    n_tool_failures INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER,
    cache_read_tokens     INTEGER,
    cache_write_tokens    INTEGER,
    input_tokens_noncached INTEGER,
    reasoning_tokens      INTEGER,
    aiu             REAL,
    api_duration_ms INTEGER,
    n_requests      INTEGER,
    peak_context_tokens   INTEGER,
    n_compactions   INTEGER,
    n_truncations   INTEGER,
    files_modified  INTEGER,
    lines_added     INTEGER,
    lines_removed   INTEGER,
    model           TEXT,
    status          TEXT,
    error           TEXT
);
"""

# Columns added after the initial schema. ``connect`` ALTERs any that a pre-existing
# index.db is missing (the index is a derived cache, but this avoids a forced reindex).
_TRIAL_MIGRATIONS = {
    "status": "ALTER TABLE trials ADD COLUMN status TEXT",
    "error": "ALTER TABLE trials ADD COLUMN error TEXT",
}

_TASK_MIGRATIONS = {
    "instance_id": "ALTER TABLE tasks ADD COLUMN instance_id TEXT",
    "difficulty": "ALTER TABLE tasks ADD COLUMN difficulty TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(trials)")}
    for column, ddl in _TRIAL_MIGRATIONS.items():
        if column not in existing:
            conn.execute(ddl)
    existing_tasks = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    for column, ddl in _TASK_MIGRATIONS.items():
        if column not in existing_tasks:
            conn.execute(ddl)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def index_run_dir(conn: sqlite3.Connection, run_dir: Path) -> None:
    """Insert (or replace) one stored run into the index."""
    run = read_json(run_dir / "run.json")
    run_id = run["run_id"]
    slug = run["experiment_slug"]

    conn.execute(
        "INSERT OR IGNORE INTO experiments(slug, name, description, first_seen) VALUES (?,?,?,?)",
        (
            slug,
            run.get("experiment_name"),
            run.get("experiment_description"),
            run.get("started_at"),
        ),
    )
    conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
    conn.execute("DELETE FROM variants WHERE run_id=?", (run_id,))
    conn.execute("DELETE FROM tasks WHERE run_id=?", (run_id,))
    conn.execute("DELETE FROM trials WHERE run_id=?", (run_id,))

    variants = run.get("variants", [])
    conn.execute(
        "INSERT INTO runs(run_id, experiment_slug, started_at, finished_at, git_base, "
        "n_variants, status) VALUES (?,?,?,?,?,?,?)",
        (
            run_id,
            slug,
            run.get("started_at"),
            run.get("finished_at"),
            run.get("git_base"),
            len(variants),
            run.get("status"),
        ),
    )

    for vr in variants:
        v = vr["variant"]
        vslug = v.get("slug") or v.get("name")
        conn.execute(
            "INSERT INTO variants(run_id, variant_slug, model, reasoning_effort, agent, mode, "
            "byok, params_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id,
                vslug,
                v.get("model"),
                v.get("reasoning_effort"),
                v.get("agent"),
                v.get("mode"),
                1 if v.get("provider") else 0,
                json.dumps(v),
            ),
        )
        for tr in vr.get("tasks", []):
            task_slug = tr.get("task_slug")
            trials = tr.get("trials", [])
            graded = [t for t in trials if t.get("success") is not None]
            n_solved = sum(1 for t in graded if t.get("success"))
            conn.execute(
                "INSERT INTO tasks(run_id, variant_slug, task_slug, task_name, instance_id, "
                "difficulty, n_trials, success_rate, resolved) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    vslug,
                    task_slug,
                    tr.get("task_name"),
                    tr.get("instance_id"),
                    tr.get("difficulty"),
                    len(trials),
                    (n_solved / len(graded)) if graded else None,
                    None if not graded else int(any(t.get("success") for t in graded)),
                ),
            )
            for trial in trials:
                m = trial.get("metrics", {})
                models = m.get("models") or []
                conn.execute(
                    "INSERT INTO trials(run_id, variant_slug, task_slug, trial_no, session_id, "
                    "exit_code, duration_s, success, n_turns, n_tool_calls, n_tool_failures, "
                    "input_tokens, output_tokens, total_tokens, cache_read_tokens, "
                    "cache_write_tokens, input_tokens_noncached, reasoning_tokens, aiu, "
                    "api_duration_ms, n_requests, peak_context_tokens, n_compactions, "
                    "n_truncations, files_modified, lines_added, lines_removed, model, "
                    "status, error) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        vslug,
                        task_slug,
                        trial.get("trial_no"),
                        trial.get("session_id"),
                        trial.get("exit_code"),
                        trial.get("duration_s"),
                        None if trial.get("success") is None else int(bool(trial.get("success"))),
                        m.get("n_turns"),
                        m.get("n_tool_calls"),
                        m.get("n_tool_failures"),
                        m.get("input_tokens"),
                        m.get("output_tokens"),
                        m.get("total_tokens"),
                        m.get("cache_read_tokens"),
                        m.get("cache_write_tokens"),
                        m.get("input_tokens_noncached"),
                        m.get("reasoning_tokens"),
                        m.get("aiu"),
                        m.get("api_duration_ms"),
                        m.get("n_requests"),
                        m.get("peak_context_tokens"),
                        m.get("n_compactions"),
                        m.get("n_truncations"),
                        m.get("files_modified"),
                        m.get("lines_added"),
                        m.get("lines_removed"),
                        models[-1] if models else v.get("model"),
                        trial.get("status"),
                        trial.get("error"),
                    ),
                )
    conn.commit()


def reindex(layout: Layout) -> int:
    """Rebuild the index from scratch by scanning ``results/``. Returns run count."""
    if layout.index_db.exists():
        layout.index_db.unlink()
    conn = connect(layout.index_db)
    count = 0
    try:
        for _slug, _run_id, run_dir in layout.iter_runs():
            index_run_dir(conn, run_dir)
            count += 1
    finally:
        conn.close()
    return count


def list_runs(layout: Layout) -> list[dict]:
    if not layout.index_db.exists():
        reindex(layout)
    conn = connect(layout.index_db)
    try:
        rows = conn.execute(
            "SELECT r.*, "
            "(SELECT COUNT(*) FROM trials t WHERE t.run_id=r.run_id) AS n_trials, "
            "(SELECT AVG(success) FROM trials t WHERE t.run_id=r.run_id AND t.success IS NOT NULL)"
            " AS success_rate "
            "FROM runs r ORDER BY r.started_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
