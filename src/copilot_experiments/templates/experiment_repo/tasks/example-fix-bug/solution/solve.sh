#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

path = Path("/app/calculator.py")
path.write_text(
    'def multiply(a: int, b: int) -> int:\n'
    '    """Return the product of two integers."""\n'
    '    return a * b\n',
    encoding="utf-8",
)
PY
