"""A small RFC 4180-style CSV parser.

The single function below is intentionally left unimplemented. The accompanying tests in
``test_csvtools.py`` are the exact behavioral spec - read them first, then implement the
parser so they pass. This is the harder task because it needs a small character-by-
character state machine to handle quoting correctly.
"""


def parse_csv(text):
    """Parse ``text`` as CSV and return a list of records, each a list of string fields.

    Rules (a deterministic subset of RFC 4180):

    * Records are separated by a newline. A ``\r\n`` sequence counts as one separator.
    * Fields within a record are separated by commas.
    * A field may be wrapped in double quotes. Inside a quoted field, commas and newlines
      are literal, and a doubled quote (``""``) is an escaped single quote.
    * Whitespace is significant: fields are never trimmed.
    * Empty input returns ``[]``. A single trailing newline does not add an empty record.
    """
    raise NotImplementedError
