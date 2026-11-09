"""Matching a quoted passage against prose, for checks that a model's quote
is really in the text it names (the gate's extraction and checker).

A model copies prose imperfectly in ways that don't change the words:
curly or straight quotes, an em dash or `--`, `…` or `...`, markdown
emphasis, line breaks, case. `normalize` removes those differences;
`quote_in` then matches on whole words, so "he knew" is not found inside
"she knew", and a quote whose parts are joined with an ellipsis is found
when each part is, in order.
"""

from __future__ import annotations

import re

_SUBSTITUTIONS = (
    ('‘', "'"), ('’', "'"), ('“', '"'), ('”', '"'),
    ('—', '-'), ('–', '-'), ('--', '-'), ('…', '...'),
)


def normalize(text: str) -> str:
    """Lowercased, whitespace collapsed, quotes, dashes and ellipses made
    plain, markdown emphasis (`*`, `_`) and verse hard breaks removed."""
    for old, new in _SUBSTITUTIONS:
        text = text.replace(old, new)
    # A verse line's hard break (a backslash ending the line, `source fetch
    # --verse`): a quote running across two lines matches without it, as it
    # does written with the break on one line ("kings\\ of") or with a
    # slash between the lines ("kings / of")
    text = re.sub(r'\\(?=\s|$)', '', text)
    text = re.sub(r'(?<=\S)\s+/\s+(?=\S)', ' ', text)
    text = re.sub(r'[*_]+', '', text)
    return ' '.join(text.split()).lower()


def quote_parts(quote: str) -> list[str]:
    """The normalized `...`-separated parts of `quote` that have a word."""
    parts = [p.strip(' .,;:!?"\'-') for p in normalize(quote).split('...')]
    return [p for p in parts if re.search(r'\w', p)]


def part_pattern(part: str) -> re.Pattern:
    """`part` as whole words: not found inside a longer word."""
    return re.compile((r'(?<!\w)' if re.match(r'\w', part) else '') + re.escape(part)
                      + (r'(?!\w)' if re.search(r'\w$', part) else ''))


def quote_in(text: str, quote: str) -> bool:
    """Whether `quote` is in `text`, as whole words, after `normalize`. A
    quote with `...` in it matches when each part does, in order. A quote
    with no words never matches."""
    hay = normalize(text)
    start = 0
    parts = quote_parts(quote)
    if not parts:
        return False
    for part in parts:
        m = part_pattern(part).search(hay, start)
        if not m:
            return False
        start = m.end()
    return True


def word_count(quote: str) -> int:
    return len(re.findall(r'\w+', normalize(quote)))
