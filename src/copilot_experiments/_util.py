"""Small shared helpers."""

from __future__ import annotations

import datetime as _dt
import json
import re
import uuid
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Turn an arbitrary string into a filesystem- and URL-safe slug."""
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "unnamed"


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def iso(ts: _dt.datetime) -> str:
    return ts.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def new_run_id(now: _dt.datetime | None = None) -> str:
    """Generate a sortable run id: ``20260612T103300Z_a1b2c3``."""
    now = now or utcnow()
    stamp = now.astimezone(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid.uuid4().hex[:6]}"


def new_session_id() -> str:
    return str(uuid.uuid4())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
