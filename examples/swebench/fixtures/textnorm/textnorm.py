"""A tiny text-normalisation helper with a reported bug (stand-in for a SWE-bench repo)."""


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip the ends.

    BUG: the current implementation only strips, it does not collapse internal
    runs of whitespace, so "a   b\\t c" should become "a b c" but does not.
    """
    return text.strip()
