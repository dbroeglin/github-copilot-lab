"""Behavioral spec for csvtools.py — do not modify these tests."""

from csvtools import parse_csv


def test_empty_input_is_no_records():
    assert parse_csv("") == []


def test_plain_rows():
    assert parse_csv("a,b,c\n1,2,3") == [["a", "b", "c"], ["1", "2", "3"]]


def test_trailing_newline_does_not_add_a_record():
    assert parse_csv("a,b\n") == [["a", "b"]]


def test_empty_fields_are_preserved():
    assert parse_csv("a,,c") == [["a", "", "c"]]
    assert parse_csv(",") == [["", ""]]


def test_whitespace_is_significant():
    assert parse_csv("a, b ,c") == [["a", " b ", "c"]]


def test_quoted_field_keeps_comma_literal():
    assert parse_csv('a,"b,c",d') == [["a", "b,c", "d"]]


def test_escaped_quote_inside_quoted_field():
    assert parse_csv('"she said ""hi"""') == [['she said "hi"']]


def test_newline_inside_quoted_field():
    assert parse_csv('"line1\nline2",x') == [["line1\nline2", "x"]]


def test_crlf_separates_records():
    assert parse_csv("a,b\r\nc,d") == [["a", "b"], ["c", "d"]]
