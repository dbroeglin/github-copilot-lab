#!/usr/bin/env bash
set -euo pipefail

cat > /app/textstats.py <<'PY'
"""Small text-statistics helpers."""

from collections import Counter


def word_count(text):
    """Return the number of whitespace-separated words in ``text``."""
    return len(text.split())


def char_count(text, include_spaces=True):
    """Return the number of characters in ``text``.

    When ``include_spaces`` is False, whitespace characters are not counted.
    """
    if include_spaces:
        return len(text)
    return sum(1 for char in text if not char.isspace())


def top_words(text, n):
    """Return the ``n`` most common words as ``(word, count)`` tuples.

    Ordering is by descending count, then ascending word. Matching is
    case-insensitive (``"The"`` and ``"the"`` are the same word).
    """
    counts = Counter(word.lower() for word in text.split())
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]
PY
