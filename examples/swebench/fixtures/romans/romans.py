"""Convert integers to Roman numerals (stand-in for a harder SWE-bench instance)."""


def to_roman(n: int) -> str:
    """Return the Roman-numeral representation of ``n`` (1..3999).

    BUG: the subtractive forms (4, 9, 40, 90, 400, 900) are missing, so
    to_roman(4) returns "IIII" instead of "IV" and to_roman(9) returns
    "VIIII" instead of "IX".
    """
    table = [(1000, "M"), (500, "D"), (100, "C"), (50, "L"), (10, "X"), (5, "V"), (1, "I")]
    out = []
    for value, symbol in table:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)
