"""Extract phase 2, the casts alone (`extract --phase 2 --casts-only`, #523).

Casts extracted before #524 keep to the POV-only character list phase 2
was offered, so most of the people in a scene are missing from
`scene-intent.csv`'s `characters` and `on_stage`. Re-running phase 2 with
`--force` would replace every intent field and undo an author's fixes, so
this mode asks each scene for its cast alone (`extract.build_cast_prompt`,
phase 2's own cast instructions and partial-labelled registry) and merges
the answer in by union:

- **Nothing is removed or reordered.** A cell's existing entries are kept
  as written, in their order; ids the answer adds go after them. A cell
  that gains nothing is left byte for byte as it was.
- **Ids are compared through the character registry's aliases**
  (`enrich.load_alias_map`, less any alias two characters share, which
  names neither: `hone.find_alias_collisions`): an answer's "Eumaeus" is
  the cast's `eumaeus`, and every entry added is written as the registry
  id it resolves to (unknown ids as given, for hone to add).
- **`on_stage` stays inside `characters`.** An id added to `on_stage` is
  added to `characters` too, and so is one `on_stage` already listed that
  `characters` left out.
- **The merge touches no other column or row** (`apply_casts`): only the
  two cells of rows that gain someone change. Writing the file makes it LF
  throughout, as every CSV we write is.

The author's edits: phase 2 keeps no per-cell record of what it wrote
(`working/extraction-cells.csv` and `extraction-provenance.csv` are phase
5's, and hold neither cast column), so an author-edited cast can't be told
from an extracted one. A union can't undo an edit, since it only adds, so
every scene the filter selects is merged; a scene the author wants kept
out of the merge goes in `--exclude-scenes` (or out of the selection).
Both records are left as they are.

After the merge, hone's character pass (`hone --domain characters`, run by
`cmd_extract`) works on the whole book, as it does after phase 2: it
rewrites names as ids in every scene's casts and `scenes.csv:pov`, excluded
scenes included, and may drop a reference it decides is no character. The
review (`review_text`) lists every entry that went and every pov that
changed, so nothing it does goes unseen.
"""

from __future__ import annotations

import os
from typing import NamedTuple

from .csv_cli import DELIMITER, _read_lines, _write_lines
from .enrich import strip_parentheticals

CAST_COLUMNS = ('characters', 'on_stage')

#: Per-scene review of what a run added (`review_text`), rewritten each run
REVIEW_FILE = os.path.join('working', 'extract-casts-review.md')

#: The batch's per-scene replies (`{id}.json`, `{id}.txt`), cleared at the
#: start of each run so no reply from an earlier one is read
LOG_SUBDIR = 'extract-casts'

#: Reply tokens a scene's cast is forecast at: two JSON lists of ids. The
#: Iliad's largest casts run to about 25 ids, some 150 tokens; this leaves
#: room above that
OUTPUT_TOKENS_PER_SCENE = 250
MAX_TOKENS = 1024


class CastAnswer(NamedTuple):
    """A reply's cast (`extract.parse_cast_response`), entries as given."""
    characters: list[str]
    on_stage: list[str]


class CastMerge(NamedTuple):
    """One scene's cast after a merge: the two cells, and the ids each gained."""
    characters: str
    on_stage: str
    added_characters: list[str]
    added_on_stage: list[str]

    @property
    def changed(self) -> bool:
        return bool(self.added_characters or self.added_on_stage)


def split_ids(cell: str) -> list[str]:
    """A `;` list cell's entries, trimmed, blanks dropped."""
    return [p.strip() for p in (cell or '').split(';') if p.strip()]


def _canonical(entry: str, alias_map: dict[str, str]) -> str:
    """The registry id an entry resolves to, or the entry itself (its
    parenthetical dropped) when the registry doesn't know it."""
    bare = strip_parentheticals(entry.strip())
    return alias_map.get(bare.lower(), bare)


def _append(cell: str, added: list[str]) -> str:
    """`cell` with `added` after its entries, its own text kept as written
    but for surrounding spaces and a trailing `;`, dropped so the list
    stays well formed."""
    if not added:
        return cell
    base = cell.strip()
    while base.endswith(';'):
        base = base[:-1].rstrip()
    return ';'.join([base, *added] if base else added)


def merge_cast(characters: str, on_stage: str, new_characters: list[str],
               new_on_stage: list[str], alias_map: dict[str, str]) -> CastMerge:
    """Union an answered cast into a scene's existing one (see the module
    docstring). Entries match case-insensitively through `alias_map`
    (lowercased name, id or alias → id); each entry added is written as its
    registry id, deduplicated, in the answer's order. `characters` gains,
    in this order, the entries `on_stage` already held that it lacked, the
    answer's characters, and the answer's on_stage ids."""
    chars, present = split_ids(characters), split_ids(on_stage)
    char_keys = {_canonical(c, alias_map).lower() for c in chars}
    on_keys = {_canonical(c, alias_map).lower() for c in present}

    added_on: list[str] = []
    for entry in new_on_stage:
        cid = _canonical(entry, alias_map)
        if cid and cid.lower() not in on_keys:
            on_keys.add(cid.lower())
            added_on.append(cid)

    added_chars: list[str] = []
    candidates = ([_canonical(p, alias_map) for p in present]
                  + [_canonical(e, alias_map) for e in new_characters] + added_on)
    for cid in candidates:
        key = _canonical(cid, alias_map).lower()
        if cid and key not in char_keys:
            char_keys.add(key)
            added_chars.append(cid)

    return CastMerge(_append(characters, added_chars), _append(on_stage, added_on),
                     added_chars, added_on)


class CastFileError(ValueError):
    """scene-intent.csv can't be merged into: missing, empty, or without an
    `id`, `characters` or `on_stage` column."""


def _columns(path: str) -> tuple[list[str], int, int, int]:
    """The file's lines and its id, characters and on_stage column indexes."""
    if not os.path.isfile(path):
        raise CastFileError(f'{path} does not exist (run extract --phase 2 first)')
    lines = _read_lines(path)
    if not lines:
        raise CastFileError(f'{path} is empty (run extract --phase 2 first)')
    header = lines[0].lstrip('﻿').split(DELIMITER)
    missing = [c for c in ('id', *CAST_COLUMNS) if c not in header]
    if missing:
        raise CastFileError(f'{path} has no {", ".join(missing)} column')
    return lines, header.index('id'), header.index('characters'), header.index('on_stage')


def overlong_rows(path: str) -> list[str]:
    """Ids of rows with more fields than the header: a stray `|` has moved
    their cells, so the cast columns can't be found. Raises CastFileError."""
    lines, id_i, _, _ = _columns(path)
    width = len(lines[0].split(DELIMITER))
    return [f[id_i].strip() for f in (line.split(DELIMITER) for line in lines[1:])
            if len(f) > width and id_i < len(f) and f[id_i].strip()]


def read_casts(path: str) -> dict[str, list[tuple[str, str]]]:
    """Every row's (characters, on_stage) by scene id, a list per id (more
    than one entry: the id is on several rows). Raises CastFileError."""
    lines, id_i, ch_i, on_i = _columns(path)
    casts: dict[str, list[tuple[str, str]]] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split(DELIMITER)
        sid = fields[id_i].strip() if id_i < len(fields) else ''
        if sid:
            cell = lambda i: fields[i] if i < len(fields) else ''   # noqa: E731
            casts.setdefault(sid, []).append((cell(ch_i), cell(on_i)))
    return casts


def apply_casts(path: str, answers: dict[str, CastAnswer],
                alias_map: dict[str, str]) -> dict[str, CastMerge]:
    """Merge each scene's answered (characters, on_stage) into its row of
    scene-intent.csv, read now (not when the batch was sent), so an edit
    made while it ran is kept. Only the two cells of the rows that gain an
    id change; the file is written only when one does (LF, atomically,
    `csv_cli._write_lines`). Returns each answered scene's merge; a scene
    with no row, on several rows, or on a row with more fields than the
    header (`overlong_rows`), is left out (the caller names it). Raises
    CastFileError."""
    lines, id_i, ch_i, on_i = _columns(path)
    width = len(lines[0].split(DELIMITER))
    rows_per_id: dict[str, int] = {}
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        if id_i < len(fields) and fields[id_i].strip():
            rows_per_id[fields[id_i].strip()] = rows_per_id.get(fields[id_i].strip(), 0) + 1

    merges: dict[str, CastMerge] = {}
    out = [lines[0]]
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        sid = fields[id_i].strip() if id_i < len(fields) else ''
        if sid not in answers or rows_per_id.get(sid) != 1 or len(fields) > width:
            out.append(line)
            continue
        while len(fields) <= max(ch_i, on_i):
            fields.append('')
        answer = answers[sid]
        merge = merge_cast(fields[ch_i], fields[on_i], answer.characters, answer.on_stage,
                           alias_map)
        merges[sid] = merge
        if merge.changed:
            fields[ch_i], fields[on_i] = merge.characters, merge.on_stage
            out.append(DELIMITER.join(fields))
        else:
            out.append(line)
    if any(m.changed for m in merges.values()):
        _write_lines(path, out)
    return merges


def forecast(prompts: list[str], model: str) -> float:
    """The batch's cost: each prompt priced as its own request (so a
    long-prompt rate applies per request, not to the total), at
    `extract._CHARS_PER_TOKEN` characters a token plus
    `OUTPUT_TOKENS_PER_SCENE`, at the Batch API's price. No shared system
    context is sent, so there is no cache to assume."""
    from .costs import calculate_cost
    from .extract import _CHARS_PER_TOKEN
    return sum(calculate_cost(model, len(p) // _CHARS_PER_TOKEN, OUTPUT_TOKENS_PER_SCENE,
                              batch=True) for p in prompts)


def _entry(cid: str, names: dict[str, str]) -> str:
    name = names.get(cid.lower())
    return f'{cid} ({name})' if name else f'{cid} (not in characters.csv)'


def _difference(cell: str, other: str, alias_map: dict[str, str]) -> list[str]:
    """The entries of `cell` that `other` doesn't hold, matched through
    `alias_map` (so a name hone rewrote as its id is the same entry)."""
    held = {_canonical(e, alias_map).lower() for e in split_ids(other)}
    return [e for e in split_ids(cell) if _canonical(e, alias_map).lower() not in held]


def review_text(*, selected: list[str], before: dict[str, list[tuple[str, str]]],
                after: dict[str, list[tuple[str, str]]], names: dict[str, str],
                alias_map: dict[str, str], not_merged: dict[str, str], empty: list[str],
                cost: float | None, forecast_cost: float, registry_note: str,
                pov_changes: dict[str, tuple[str, str]] | None = None,
                shared_aliases: dict[str, list[str]] | None = None) -> str:
    """The review file: per scene, the ids each column gained since the run
    began (read after hone's registry pass, so they are the ids that
    stayed), each with its registry name; any entry that went missing (hone
    drops a reference it decides isn't a character), in the selected scenes
    or any other; and what wasn't merged, and why.

    `before` and `after` are `read_casts` results; `names` maps lowercased
    id to name; `alias_map` is the registry's after the run, so an entry
    hone only rewrote as its id counts as neither added nor lost;
    `not_merged` maps scene id to the reason; `pov_changes` maps scene id
    to the (old, new) `scenes.csv:pov` after the registry pass;
    `shared_aliases` are aliases several characters share, not matched."""
    added: dict[str, tuple[list[str], list[str]]] = {}
    lost: dict[str, tuple[list[str], list[str]]] = {}
    several: list[str] = []
    for sid in dict.fromkeys([*selected, *after, *before]):
        old_rows, new_rows = before.get(sid) or [('', '')], after.get(sid) or [('', '')]
        if len(old_rows) > 1 or len(new_rows) > 1:
            several.append(sid)   # never merged, so not compared
            continue
        (old_ch, old_on), (new_ch, new_on) = old_rows[0], new_rows[0]
        gained = (_difference(new_ch, old_ch, alias_map), _difference(new_on, old_on, alias_map))
        gone = (_difference(old_ch, new_ch, alias_map), _difference(old_on, new_on, alias_map))
        if any(gained):
            added[sid] = gained
        if any(gone):
            lost[sid] = gone

    n_chars = sum(len(a[0]) for a in added.values())
    n_on = sum(len(a[1]) for a in added.values())
    lines = ['# Extract: cast-only re-extraction review', '',
             f'Scenes asked: {len(selected)}. Scenes that gained someone: {len(added)}. '
             f'Ids added: {n_chars} to characters, {n_on} to on_stage.',
             f'Cost of the batch: '
             f'{"$%.2f" % cost if cost is not None else "not known (see the WARNINGs)"} '
             f'(forecast ${forecast_cost:.2f}); the registry pass\'s calls are in the cost '
             f'ledger.', '',
             f'Registry: {registry_note}', '',
             'Entries already in a cast were kept as written; nothing below was removed by '
             'the merge. Check each addition against the scene: an id named here that the '
             'scene only mentions in passing belongs in neither column.', '']
    if shared_aliases:
        lines += ['## Aliases shared by several characters', '',
                  'Not used to match an answer to a cast, since they name no one character:', '']
        lines += [f'- {alias}: {", ".join(ids)}' for alias, ids in shared_aliases.items()] + ['']
    if not_merged:
        lines += ['## Not merged', '']
        lines += [f'- {sid}: {why}' for sid, why in not_merged.items()] + ['']
    several = [s for s in several if s not in not_merged]
    if several:
        lines += ['## Not compared', '',
                  'On several rows of scene-intent.csv, so what changed in their casts is not '
                  'listed:', '']
        lines += [f'- {sid}' for sid in several] + ['']
    if empty:
        lines += ['## Answered with no one', '',
                  'The reply listed nobody for these scenes; their casts are as they were.', '']
        lines += [f'- {sid}' for sid in empty] + ['']
    lines += ['## Added', '']
    if not added:
        lines += ['No scene gained anyone.', '']
    for sid in [s for s in dict.fromkeys([*selected, *added]) if s in added]:
        gained_chars, gained_on = added[sid]
        outside = '' if sid in selected else ' (not asked; changed by the registry pass)'
        lines.append(f'### {sid}{outside}')
        for column, ids in (('characters', gained_chars), ('on_stage', gained_on)):
            if ids:
                lines.append(f'- {column}: ' + ', '.join(_entry(i, names) for i in ids))
        lines.append('')
    if lost:
        lines += ['## Entries no longer in a cast', '',
                  'The merge removes nothing: these went in the registry pass (hone drops a '
                  'reference it decides is not a character, and may map one to other ids), '
                  'or were edited while the run was going. Put back any that should stay.', '']
        for sid, (gone_chars, gone_on) in lost.items():
            parts = [f'{col}: {", ".join(ids)}' for col, ids in
                     (('characters', gone_chars), ('on_stage', gone_on)) if ids]
            lines.append(f'- {sid}: ' + '; '.join(parts))
        lines.append('')
    if pov_changes:
        lines += ['## POV changed by the registry pass', '']
        lines += [f'- {sid}: {old} → {new or "(blank)"}' for sid, (old, new) in pov_changes.items()]
        lines.append('')
    return '\n'.join(lines)
