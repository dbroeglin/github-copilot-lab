from textnorm import normalize_whitespace


def test_collapses_internal_runs():
    assert normalize_whitespace("a   b\t c") == "a b c"


def test_strips_ends():
    assert normalize_whitespace("  hello  ") == "hello"


def test_empty():
    assert normalize_whitespace("   ") == ""
