"""Scaffold a standalone experiment repository from bundled templates."""

from __future__ import annotations

from pathlib import Path

from ._util import slugify

TEMPLATE_DIR = Path(__file__).parent / "templates" / "experiment_repo"


class ScaffoldError(RuntimeError):
    pass


def _render(text: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def init_experiment_repo(
    dest: Path,
    *,
    project_name: str | None = None,
    force: bool = False,
) -> list[Path]:
    """Render the experiment-repo template into ``dest``.

    Returns the list of files created. ``.tmpl`` files are rendered with simple
    ``{{placeholder}}`` substitution and written without the ``.tmpl`` suffix.
    """
    dest = Path(dest)
    if not TEMPLATE_DIR.is_dir():
        raise ScaffoldError(f"Template directory missing: {TEMPLATE_DIR}")

    if dest.exists() and any(dest.iterdir()) and not force:
        raise ScaffoldError(f"Destination '{dest}' is not empty. Use --force to scaffold anyway.")

    project_name = project_name or slugify(dest.resolve().name)
    replacements = {
        "project_name": project_name,
        "project_title": project_name.replace("-", " ").title(),
    }

    created: list[Path] = []
    for src in sorted(TEMPLATE_DIR.rglob("*")):
        rel = src.relative_to(TEMPLATE_DIR)
        target = dest / rel
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".tmpl":
            target = target.with_suffix("")
            content = _render(src.read_text(encoding="utf-8"), replacements)
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(src.read_bytes())
        created.append(target)
    return created
