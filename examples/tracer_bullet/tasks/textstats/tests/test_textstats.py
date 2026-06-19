"""Behavioral spec for textstats.py - do not modify these tests."""

from textstats import char_count, top_words, word_count


def test_word_count_basic():
    assert word_count("the quick brown fox") == 4


def test_word_count_collapses_whitespace():
    assert word_count("  the   quick\tbrown\nfox  ") == 4
    assert word_count("   ") == 0


def test_char_count_with_spaces():
    assert char_count("ab c") == 4


def test_char_count_without_spaces():
    assert char_count("a b\tc\n") == 3


def test_top_words_orders_by_count_then_word():
    text = "the cat sat on the mat the cat"
    assert top_words(text, 2) == [("the", 3), ("cat", 2)]


def test_top_words_is_case_insensitive():
    assert top_words("The the THE cat", 1) == [("the", 3)]
