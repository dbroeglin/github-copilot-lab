"""Behavioral spec for strtools.py — do not modify these tests."""

from strtools import reverse_words


def test_reverses_two_words():
    assert reverse_words("hello world") == "world hello"


def test_single_word_unchanged():
    assert reverse_words("hello") == "hello"


def test_collapses_surrounding_and_inner_whitespace():
    assert reverse_words("  the   quick  brown  ") == "brown quick the"


def test_empty_and_whitespace_only():
    assert reverse_words("") == ""
    assert reverse_words("   ") == ""
