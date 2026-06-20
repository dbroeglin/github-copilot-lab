"""Small text-statistics helpers.

Three functions are intentionally left unimplemented. The accompanying tests in
``test_textstats.py`` describe exactly how each one should behave. Implement them so the
test suite passes.
"""


def word_count(text):
    """Return the number of whitespace-separated words in ``text``."""
    raise NotImplementedError


def char_count(text, include_spaces=True):
    """Return the number of characters in ``text``.

    When ``include_spaces`` is False, whitespace characters are not counted.
    """
    raise NotImplementedError


def top_words(text, n):
    """Return the ``n`` most common words as ``(word, count)`` tuples.

    Ordering is by descending count, then ascending word. Matching is
    case-insensitive (``"The"`` and ``"the"`` are the same word).
    """
    raise NotImplementedError
