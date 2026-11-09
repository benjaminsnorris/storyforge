"""A brief beat the author marks as required: the `must:` marker (#642).

A brief is a plan, and the prose wins: the gate reports a promise the scene
doesn't keep (a broken promise), but it doesn't stop the scene for one
(`gate.GateResult.advisory`). A `key_actions` or `key_dialogue` item the
author starts with `must:` is the exception. A broken `must` beat still
stops the scene, and the quoted words in one (a source line a faithful
adaptation keeps verbatim) must be in the prose word for word, which the
gate checks by code (`gate._verbatim_findings`).

    key_actions: Achilles drags Hector's body; must: Priam kisses Achilles' hands
    key_dialogue: must: Priam: "I have kissed the hands of the man who killed my son"

The marker is `must`, any case, then a colon, with any spacing around it
(`must:`, `MUST :`, ` Must:x`). It must open the item: `;` separates items,
and a `must:` anywhere else in an item is just words. An item that is only
the marker (`must:`) marks nothing, nor does a marker after other words or
in a field that takes none (`misplaced`); the gate reports both.

This module is the one place that reads the marker. A `must` beat is the
author's: nothing Storyforge writes may drop or reword one. Each command
that rewrites a brief's `key_actions` or `key_dialogue` from a model's reply
(hone's rewrites, revise's brief fixes, elaborate's briefs stage, a forced
extract or extract-gn merge, enrich re-reads; agent-reference's `must` row
is the list) passes the result through `keep_must`, which puts back every `must` item the reply
lost or reworded, word for word, and drops any `must:` item the reply made
up (only the author marks a beat).
"""

from __future__ import annotations

import re
from typing import NamedTuple

#: The brief fields whose items may be marked `must:`
MUST_FIELDS = ('key_actions', 'key_dialogue')

_MARK = re.compile(r'^\s*must\s*:\s*', re.IGNORECASE)


class Item(NamedTuple):
    """One `;`-separated item of a brief cell."""
    raw: str        # the item as written, stripped
    must: bool      # it opens with the marker
    text: str       # the item without the marker, stripped ('' for a bare `must:`)

    @property
    def beat(self) -> bool:
        """Whether it is a `must` beat: marked, and naming something (a
        bare `must:` marks nothing)."""
        return self.must and bool(self.text)


def parse_item(item: str) -> Item:
    """`item` read for the marker."""
    raw = (item or '').strip()
    m = _MARK.match(raw)
    if not m:
        return Item(raw, False, raw)
    return Item(raw, True, raw[m.end():].strip())


def strip_marker(text: str) -> str:
    """`text` without a leading `must:` marker (stripped)."""
    return parse_item(text).text


def is_must(item: str) -> bool:
    """Whether `item` opens with the marker."""
    return parse_item(item).must


def items(cell: str) -> list[Item]:
    """The cell's non-empty items, in order, each read for the marker."""
    return [parse_item(part) for part in (cell or '').split(';') if part.strip()]


def must_items(cell: str) -> list[Item]:
    """The cell's `must` items that name a beat (a bare `must:` names none)."""
    return [i for i in items(cell) if i.beat]


def unmarked(cell: str) -> str:
    """The cell without its `must` items (the rest, `; `-joined): what a
    rewrite wrote, once `keep_must` has put back the author's."""
    return '; '.join(i.raw for i in items(cell) if not i.must)


def bare_markers(cell: str) -> int:
    """How many items of the cell are only the marker."""
    return sum(1 for i in items(cell) if i.must and not i.text)


_ANY_MARK = re.compile(r'(?<!\w)must\s*:', re.IGNORECASE)


def misplaced(cell: str, col: str) -> list[str]:
    """The items of `col`'s cell that write the marker where it marks
    nothing (#642's review SF-3): after other words (`Priam: must: "..."`,
    `**must:** ...`, `"must: ..."`) in `MUST_FIELDS`, or anywhere in a field
    that takes no marker (`outcome`, the registry fields). Raw, for a NOTE:
    a beat the author meant to require would otherwise go advisory
    unsaid."""
    out = []
    for item in items(cell):
        if col in MUST_FIELDS:
            if not item.must and _ANY_MARK.search(item.raw):
                out.append(item.raw)
        elif item.must or _ANY_MARK.search(item.raw):
            out.append(item.raw)
    return out


#: The fewest words a quote and a beat must share, one inside the other,
#: for `names_beat` to read them as the same beat (a word or two is in
#: everything)
MIN_SHARED_WORDS = 4


def _words(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize('NFC', text or '')
    return ' ' + ' '.join(re.findall(r'\w+', text.lower())) + ' '


def names_beat(quote: str, beat: str) -> bool:
    """Whether `quote` (a check's or a judge's words for a broken promise)
    is about the beat `beat`: the same words, the marker, case and
    punctuation aside, or one inside the other, word for word, the shorter
    `MIN_SHARED_WORDS` words or more."""
    q, b = _words(strip_marker(quote)), _words(strip_marker(beat))
    if not q.strip() or not b.strip():
        return False
    if q == b:
        return True
    short, long_ = sorted((q, b), key=len)
    return len(short.split()) >= MIN_SHARED_WORDS and short in long_


def _key(text: str) -> str:
    return ' '.join(text.split())


class Kept(NamedTuple):
    """`keep_must`'s answer."""
    value: str              # the cell to write
    restored: list[str]     # the author's `must` items put back (raw)
    dropped: list[str]      # `must:` items the rewrite made up or reworded, left out (raw)

    @property
    def changed(self) -> bool:
        return bool(self.restored or self.dropped)


def keep_must(old: str, new: str) -> Kept:
    """`new` (a rewrite of the cell `old`) with every `must` item of `old`
    in it word for word (the beat's words; the marker's spelling and the
    spacing aside), and no other `must` item.

    A `must` item of `old` the rewrite lost or reworded is put back as the
    author wrote it, at its place in `old` (clamped to the rewrite's
    length); a `must:` item of `new` that isn't one of `old`'s (a reworded
    one, or one the rewrite made up) is left out. When nothing is put back
    or left out, `value` is `new` unchanged."""
    keep = must_items(old)
    wanted = {_key(i.text) for i in keep}
    new_items = items(new)
    dropped = [i.raw for i in new_items if i.beat and _key(i.text) not in wanted]
    present = {_key(i.text) for i in new_items if i.must and _key(i.text) in wanted}
    restored = [i for i in keep if _key(i.text) not in present]
    if not dropped and not restored:
        return Kept(new, [], [])
    kept = [i for i in new_items if not (i.beat and _key(i.text) not in wanted)]
    out = [i.raw for i in kept]
    old_items = items(old)
    missing = []
    for item in restored:
        # the rewrite kept the beat's words but not the marker: mark it again
        # in place, rather than adding a second copy
        same = next((n for n, i in enumerate(kept)
                     if not i.must and _key(i.text) == _key(item.text)), None)
        if same is None:
            missing.append(item)
        else:
            out[same] = item.raw
    for item in missing:
        out.insert(min(old_items.index(item), len(out)), item.raw)
    return Kept('; '.join(out), [i.raw for i in restored], dropped)


def keep_must_fields(old_row: dict, new_values: dict) -> tuple[dict, list[str]]:
    """`new_values` (field → rewritten cell) with `keep_must` applied to each
    of `MUST_FIELDS` in it, against `old_row`'s cell; and one line per field
    it changed, saying what was put back or left out, for the caller to
    log."""
    out = dict(new_values)
    notes = []
    for col in MUST_FIELDS:
        if col not in out:
            continue
        kept = keep_must(old_row.get(col, '') or '', out[col] or '')
        if kept.changed:
            out[col] = kept.value
            parts = []
            if kept.restored:
                parts.append('put back the author\'s must item(s) the rewrite lost or '
                             'reworded: ' + ' / '.join(kept.restored))
            if kept.dropped:
                parts.append('left out must: item(s) the author did not write: '
                             + ' / '.join(kept.dropped))
            notes.append(f'{col}: ' + '; '.join(parts))
    return out, notes
