Implement the three functions in `textstats.py` so the hidden verifier passes.

Expected behavior:

- `word_count(text)` returns the number of whitespace-separated words.
- `char_count(text, include_spaces=True)` returns all characters when `include_spaces` is true;
  otherwise it excludes all whitespace characters.
- `top_words(text, n)` returns the `n` most common words as `(word, count)` tuples, comparing words
  case-insensitively and ordering ties alphabetically.

You may validate with small Python snippets from `/app`. The verifier tests are outside the
workspace and should not be modified.
