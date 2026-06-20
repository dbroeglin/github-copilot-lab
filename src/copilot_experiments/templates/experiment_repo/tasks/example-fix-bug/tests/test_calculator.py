import importlib.util
from pathlib import Path


def _load_calculator():
    path = Path("/app/calculator.py")
    spec = importlib.util.spec_from_file_location("calculator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_multiply():
    calculator = _load_calculator()
    assert calculator.multiply(6, 7) == 42
    assert calculator.multiply(-3, 5) == -15
