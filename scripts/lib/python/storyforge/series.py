"""A series' shared canon: reference files several books read in place.

A book in a series names the canon it shares in `storyforge.yaml`:

    series:
      canon:
        - ../../homer/series-bible/gods.md
        - ../../homer/series-bible/cast.md

`canon:` is a block list, or one path on its line. Each path is relative to
the project (or absolute, or `~/...`). A path to a directory means the files
directly in it whose names end in `.md` (any case), sorted by name; list the
files instead when the directory also holds notes or open questions that
aren't canon.

Who reads it (`canon_text`):
- the shared system context, `common.build_shared_context` (every direct-API
  run that sends it: drafting, revision, scoring, evaluation, elaborate,
  extract, enrich, scenes-setup, timeline);
- the elaborate stages' reference section, `prompts_elaborate._existing_refs`,
  when no system context carries it;
- the drafting prompt when no system context does (`write`/`revise`
  `--interactive` and `--dry-run`): the files inline in API mode, their paths
  in the list Claude reads otherwise;
- the gate's continuity checker (`checker.reference_docs`), beside the
  book's bibles, so a scene contradicting the canon is a finding.

A series can also keep one appearance sheet per character, in a directory
named by `characters:`:

    series:
      canon:
        - ../../homer/series-bible/gods.md
      characters: ../../homer/series-bible/characters

Each `<id>.md` there opens with frontmatter whose `canon_id` is its file
name (the character's id in `reference/characters.csv`); a `README.md` is
the directory's own notes and is skipped. Unlike the canon, a sheet is
never sent whole to every prompt: a scene's drafting prompt and its
continuity check get the sheets of the scene's cast only (`scene_cast`:
its pov, characters and on_stage, names resolved to ids through
`reference/characters.csv`), so a cast of thirty sheets costs a
scene only the people in it.

Storyforge never writes to it. The book's own bibles hold what is particular
to that book; stages that rewrite a bible rewrite the book's, so one book's
run can't change the canon the other books read.

A canon that can't be used is an error, never skipped: a block that names no
canon, a value that isn't a path (`~`, `null`, a flow list), a `series:` that
isn't a top-level block, a path that isn't there, a directory that can't be
listed or holds no `.md` file, or a file that is empty or not UTF-8 raises
`SeriesError`. The commands that spend (`write`, `revise`, `score`,
`evaluate`, `elaborate`, `extract`) call `require_canon` up front, before a
branch or a forecast; `validate` reports it as a blocking finding.
`SeriesError` is a `source.SourceError`, so the dispatcher turns one raised
anywhere later into `ERROR: ...` and exit 1 rather than a traceback.
"""

from __future__ import annotations

import os
import re

from storyforge.common import parse_yaml_scalar
from storyforge.source import SourceError

#: the keys the `series:` block takes
BLOCK_KEYS = ('canon', 'characters')
#: a character sheet's name in a prompt, and in a finding citing it
SHEET_NAME = 'series-character-{}.md'
#: leads the scene's character sheets in a prompt
SHEETS_NOTE = ("(The series' character sheets for this scene's cast: how each one looks. "
               "They are what the writer knows, not a list to mention; a scene uses what "
               "it needs and never contradicts them.)")
#: leads the first canon file's text in a prompt, once
CANON_NOTE = ('(The series canon is shared by every book in this series. This book\'s '
              'own bibles add to it and never contradict it.)')
#: scalar values that mean "nothing" in YAML: never a path (`~` would
#: otherwise expand to the home directory)
_NOT_A_PATH = ('~', 'null', 'none', 'nil')


class SeriesError(SourceError):
    """A `series:` block, or a canon file it names, that can't be used."""


def _yaml_lines(project_dir: str) -> list[str] | None:
    path = os.path.join(project_dir, 'storyforge.yaml')
    try:
        with open(path, encoding='utf-8-sig') as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise SeriesError(f'storyforge.yaml could not be read: {e}') from e


def _series_block(project_dir: str) -> list[str] | None:
    """The lines under the top-level `series:` key, or None without one.

    Raises:
        SeriesError: `series:` given a value, given twice, or written
            indented (under another block) or as a top-level `canon:`.
    """
    lines = _yaml_lines(project_dir)
    if lines is None:
        return None
    block = None
    for i, line in enumerate(lines):
        if re.match(r'^series:\s*(#.*)?$', line):
            if block is not None:
                raise SeriesError('storyforge.yaml: `series:` is given twice; '
                                  'keep one block')
            block = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[0].isspace() and not nxt.lstrip().startswith('#'):
                    break
                block.append(nxt)
        elif re.match(r'^series:\s*\S', line):
            raise SeriesError('storyforge.yaml: `series:` must be a block holding '
                              '`canon:`, not a value')
        elif re.match(r'^\s+series:\s*(#.*)?$', line):
            raise SeriesError('storyforge.yaml: `series:` is indented under another block; '
                              'it is a top-level block of its own (not under `project:`)')
        elif re.match(r'^canon:', line):
            raise SeriesError('storyforge.yaml: `canon:` is at the top level; '
                              'put it under a top-level `series:` block')
    return block


def _path_value(raw: str) -> str:
    """One canon path from a scalar; '' for an empty one.

    Raises:
        SeriesError: a YAML null (`~`, `null`) or a flow list or map.
    """
    value = parse_yaml_scalar(raw)
    if value.lower() in _NOT_A_PATH or raw.strip().lower() in _NOT_A_PATH:
        raise SeriesError(f'series.canon: {raw.strip()!r} is not a path; name the canon '
                          f'files, or remove the `series:` block')
    if raw.strip().startswith(('[', '{')):
        raise SeriesError(f'series.canon: write the paths as a block list, one `- path` '
                          f'a line, not {raw.strip()!r}')
    return value


def canon_paths(project_dir: str) -> list[str]:
    """The `series.canon` paths as written, in order; [] with no `series:`
    block, or one with only `characters:`.

    Raises:
        SeriesError: as `_parse_block`.
    """
    return _parse_block(project_dir)[0]


def characters_path(project_dir: str) -> str:
    """The `series.characters` directory as written; '' without one.

    Raises:
        SeriesError: as `_parse_block`.
    """
    return _parse_block(project_dir)[1]


def _parse_block(project_dir: str) -> tuple[list[str], str]:
    """The `series:` block's canon paths and characters directory; ([], '')
    with no block.

    Raises:
        SeriesError: as `_series_block`; a block that names neither (empty,
            or `canon:` with no paths); a key the block doesn't take, a key
            given twice, a value that isn't a path, an empty list item, a
            list under `characters:`, or a line that is neither a key nor a
            list item.
    """
    block = _series_block(project_dir)
    if block is None:
        return [], ''
    characters = ''
    content = [l for l in block if l.strip() and not l.lstrip().startswith('#')]
    paths: list[str] = []
    seen: set[str] = set()
    current = None
    indent = len(content[0]) - len(content[0].lstrip()) if content else 0
    for line in content:
        depth = len(line) - len(line.lstrip())
        stripped = line.strip()
        if depth == indent and not stripped.startswith('-'):
            m = re.match(r'^(\w+):\s*(.*)$', stripped)
            if not m:
                raise SeriesError(f"storyforge.yaml: can't read {stripped!r} in the "
                                  f'`series:` block (write `canon:` and a list of paths)')
            key, raw = m.group(1), m.group(2)
            if key not in BLOCK_KEYS:
                raise SeriesError(f'storyforge.yaml: the `series:` block has `{key}`; '
                                  f'it takes {", ".join(BLOCK_KEYS)}')
            if key in seen:
                raise SeriesError(f'storyforge.yaml: the `series:` block gives `{key}` twice')
            seen.add(key)
            current = key
            value = _path_value(raw) if raw.strip() and not raw.strip().startswith('#') else ''
            if key == 'characters':
                if not value:
                    raise SeriesError('series.characters: name the directory of character '
                                      'sheets on the same line (`characters: path`)')
                characters = value
            elif value:
                paths.append(value)
            continue
        if stripped.startswith('-') and current == 'characters':
            raise SeriesError('series.characters: one directory, on the same line '
                              '(`characters: path`), not a list')
        if stripped.startswith('-') and current == 'canon':
            value = _path_value(stripped[1:])
            if not value:
                raise SeriesError('series.canon: an empty list item')
            paths.append(value)
            continue
        raise SeriesError(f"storyforge.yaml: can't read {stripped!r} in the `series:` block "
                          f'(write `canon:` and a list of paths)')
    if not paths and not characters:
        raise SeriesError('storyforge.yaml: the `series:` block names no canon; '
                          'list the files under `canon:`, or remove the block')
    return paths, characters


def _resolve(project_dir: str, path: str) -> str:
    return os.path.normpath(os.path.join(project_dir, os.path.expanduser(path)))


def canon_files(project_dir: str) -> list[tuple[str, str]]:
    """[(path as configured, absolute path)] for each canon file, a
    directory expanded to its `.md` files sorted by name. A file named twice
    (directly and through its directory) is read once, where it first comes.

    Raises:
        SeriesError: as `canon_paths`; a path that is neither a file nor a
            directory; a directory that can't be listed or holds no `.md`
            file.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in canon_paths(project_dir):
        full = _resolve(project_dir, path)
        if os.path.isdir(full):
            try:
                entries = os.listdir(full)
            except OSError as e:
                raise SeriesError(f"series.canon: can't list {path}: {e}") from e
            names = sorted(n for n in entries if n.lower().endswith('.md')
                           and os.path.isfile(os.path.join(full, n)))
            if not names:
                raise SeriesError(f'series.canon: {path} is a directory with no .md file in it')
            found = [(os.path.join(path, n), os.path.join(full, n)) for n in names]
        elif os.path.isfile(full):
            found = [(path, full)]
        else:
            raise SeriesError(f'series.canon: {path} is not there ({full})')
        for shown, abs_path in found:
            if abs_path not in seen:
                seen.add(abs_path)
                out.append((shown, abs_path))
    return out


def _read(shown: str, abs_path: str) -> str:
    try:
        with open(abs_path, encoding='utf-8-sig') as f:
            text = f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        raise SeriesError(f"series.canon: can't read {shown}: {e}") from e
    if not text:
        raise SeriesError(f'series.canon: {shown} is empty')
    return text


def canon_docs(project_dir: str) -> list[tuple[str, str]]:
    """[(path as configured, the file's text)], in order; [] with no
    `series:` block.

    Raises:
        SeriesError: as `canon_files`, or a file that is empty or can't be
            read as UTF-8.
    """
    return [(shown, _read(shown, abs_path)) for shown, abs_path in canon_files(project_dir)]


def canon_text(project_dir: str) -> list[tuple[str, str]]:
    """[(label, text)] of the series canon for a prompt, in order; [] with no
    `series:` block. Each label is `Series Canon (<path as configured>)`;
    the first text opens with `CANON_NOTE`.

    Raises:
        SeriesError: as `canon_docs`.
    """
    out = []
    for shown, text in canon_docs(project_dir):
        if not out:
            text = f'{CANON_NOTE}\n\n{text}'
        out.append((f'Series Canon ({shown})', text))
    return out


def require_canon(project_dir: str) -> None:
    """Read the whole canon once, so a command stops on a bad one before it
    branches, forecasts or spends. Nothing without a `series:` block.

    Raises:
        SeriesError: as `canon_docs`.
    """
    canon_docs(project_dir)
    for cid in character_sheets(project_dir):
        sheet_text(project_dir, cid)


def summary_lines(project_dir: str) -> list[str]:
    """`validate`'s lines: the files read and their words (the files' own,
    not `CANON_NOTE`); [] without a `series:` block.

    Raises:
        SeriesError: as `canon_docs`.
    """
    docs = canon_docs(project_dir)
    lines = []
    if docs:
        words = sum(len(t.split()) for _, t in docs)
        lines = ([f'Series canon: {len(docs)} file(s), {words:,} words, read in place '
                  f'and never written'] + [f'  {shown}' for shown, _ in docs])
    sheets = character_sheets(project_dir)
    if sheets:
        for cid in sheets:
            sheet_text(project_dir, cid)
        lines.append(f'Series character sheets: {len(sheets)} in {characters_path(project_dir)}, '
                     f"each sent only with the scenes its character is in")
    return lines


# ============================================================================
# Character sheets (`series.characters`)
# ============================================================================

_FRONTMATTER = re.compile(r'\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)', re.S)


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    """(frontmatter keys, the text after it); ({}, text) without one."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    keys = {}
    for line in m.group(1).splitlines():
        km = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', line)
        if km:
            keys[km.group(1)] = parse_yaml_scalar(km.group(2))
    return keys, text[m.end():]


def character_sheets(project_dir: str) -> dict[str, tuple[str, str]]:
    """{character id: (path as shown, absolute path)} for the sheets in the
    `series.characters` directory, by file name; {} without one. A
    `README.md` (any case) is skipped.

    Raises:
        SeriesError: as `_parse_block`; a directory that isn't there, can't
            be listed or holds no sheet.
    """
    path = characters_path(project_dir)
    if not path:
        return {}
    full = _resolve(project_dir, path)
    if not os.path.isdir(full):
        raise SeriesError(f'series.characters: {path} is not a directory ({full})')
    try:
        entries = os.listdir(full)
    except OSError as e:
        raise SeriesError(f"series.characters: can't list {path}: {e}") from e
    names = sorted(n for n in entries if n.lower().endswith('.md') and n.lower() != 'readme.md'
                   and os.path.isfile(os.path.join(full, n)))
    if not names:
        raise SeriesError(f'series.characters: {path} holds no character sheet (`<id>.md`)')
    return {n[:-3]: (os.path.join(path, n), os.path.join(full, n)) for n in names}


def sheet_text(project_dir: str, cid: str) -> str:
    """Character `cid`'s sheet, without its frontmatter; '' when the series
    has no sheet for them.

    Raises:
        SeriesError: as `character_sheets`; a sheet that is empty, can't be
            read as UTF-8, or has no frontmatter `canon_id` naming its file.
    """
    sheets = character_sheets(project_dir)
    if cid not in sheets:
        return ''
    shown, abs_path = sheets[cid]
    text = _read(shown, abs_path)
    keys, body = _frontmatter(text)
    if keys.get('canon_id') != cid:
        found = keys.get('canon_id')
        raise SeriesError(f'series.characters: {shown} needs frontmatter with '
                          f'`canon_id: {cid}`' + (f' (it has {found!r})' if found else ''))
    if not body.strip():
        raise SeriesError(f'series.characters: {shown} has frontmatter and nothing else')
    return body.strip()


def scene_cast(scene: dict[str, str], aliases: dict[str, str] | None = None) -> list[str]:
    """The ids of a scene's cast, in order and once each: its pov, then its
    `characters`, then its `on_stage` (`;`-separated cells). A name or alias
    in `aliases` (lower-cased, `enrich.load_alias_map` of characters.csv)
    becomes its id; anything else is kept as written."""
    aliases = aliases or {}
    out: list[str] = []
    for col in ('pov', 'characters', 'on_stage'):
        for raw in (scene.get(col) or '').split(';'):
            raw = raw.strip()
            cid = aliases.get(raw.lower(), raw)
            if cid and cid not in out:
                out.append(cid)
    return out


def cast_sheets(project_dir: str, scene: dict[str, str]) -> list[tuple[str, str]]:
    """[(name, text)] of the series' sheets for the scene's cast
    (`scene_cast`), in cast order; each name is `SHEET_NAME`. [] without
    `series.characters`, or when no one in the scene has a sheet.

    Raises:
        SeriesError: as `sheet_text`.
    """
    sheets = character_sheets(project_dir)
    if not sheets:
        return []
    from storyforge.enrich import load_alias_map
    aliases = load_alias_map(os.path.join(project_dir, 'reference', 'characters.csv'))
    return [(SHEET_NAME.format(cid), sheet_text(project_dir, cid))
            for cid in scene_cast(scene, aliases) if cid in sheets]


def cast_sheets_block(project_dir: str, scene: dict[str, str]) -> str:
    """The scene's character sheets as one prompt section; '' with none.

    Raises:
        SeriesError: as `sheet_text`.
    """
    sheets = cast_sheets(project_dir, scene)
    if not sheets:
        return ''
    return ("## How this scene's characters look\n\n" + SHEETS_NOTE + '\n\n'
            + '\n\n'.join(f'<reference file="{name}">\n{text}\n</reference>'
                            for name, text in sheets))


# ============================================================================
# Measurements: a costume department's sheet, in a character sheet's
# `## Measurements` table
# ============================================================================

#: the measurements a sheet may give, by lower-cased row label, with the
#: metric unit each is written in
MEASUREMENTS = {
    'height': 'cm', 'weight': 'kg', 'chest': 'cm', 'bust': 'cm', 'underbust': 'cm',
    'waist': 'cm', 'hips': 'cm', 'inseam': 'cm', 'shoulder width': 'cm', 'sleeve': 'cm',
    'neck': 'cm', 'head': 'cm', 'calf': 'cm', 'foot': 'cm',
}
#: each imperial unit, and its value in the metric one
_IMPERIAL = {'in': 2.54, 'lb': 0.45359237}
#: the share of height each length plausibly takes in an adult human body
#: (anthropometric ranges, widened at both ends for heroes, the old and the
#: gods, who keep a human's proportions at any size); outside one is advisory
RATIO_BANDS = {
    'chest': (0.45, 0.75), 'bust': (0.45, 0.75), 'underbust': (0.38, 0.60),
    'waist': (0.33, 0.72), 'hips': (0.45, 0.75), 'inseam': (0.40, 0.50),
    'shoulder width': (0.19, 0.30), 'sleeve': (0.42, 0.53), 'neck': (0.17, 0.27),
    'head': (0.25, 0.38), 'calf': (0.17, 0.27), 'foot': (0.13, 0.17),
}
#: body-mass index, scaled to a 175 cm body so a giant of human proportions
#: (weight growing as the cube of height) reads like a man
BMI_BAND = (15.0, 40.0)
#: how far the imperial column may drift from the metric one
IMPERIAL_TOLERANCE = 0.03

_MEASURE_HEADING = re.compile(r'^##\s+Measurements\s*$', re.M | re.I)
_NUMBER = re.compile(r'(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?')


def _table_after(text: str, heading: re.Pattern) -> list[list[str]] | None:
    """The cells of the first markdown table under `heading` (header and
    separator rows dropped); None without the heading."""
    m = heading.search(text)
    if not m:
        return None
    rows = []
    for line in text[m.end():].splitlines():
        if line.startswith('## '):
            break
        if not line.strip().startswith('|'):
            if rows:
                break
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if all(re.fullmatch(r':?-+:?', c) for c in cells if c):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


def sheet_measurements(text: str, shown: str = '') -> tuple[dict[str, float], list[str]]:
    """({measurement: metric value}, problems) from a sheet's
    `## Measurements` table: rows `| <measurement> | <metric> | <imperial> |`,
    e.g. `| Chest | 104 cm | 41 in |`. ({}, []) without the section. A
    problem is a row that can't be used: an unknown measurement, one given
    twice, a metric value that isn't a number in its unit, or an imperial
    value more than `IMPERIAL_TOLERANCE` from it."""
    rows = _table_after(text, _MEASURE_HEADING)
    where = f'{shown}: ' if shown else ''
    if rows is None:
        return {}, []
    out: dict[str, float] = {}
    problems: list[str] = []
    if not rows:
        return {}, [f'{where}## Measurements holds no table']
    for cells in rows:
        label = cells[0].lower().strip('* ')
        if label not in MEASUREMENTS:
            problems.append(f'{where}measurement {cells[0]!r} is not one of '
                            + ', '.join(MEASUREMENTS))
            continue
        if label in out:
            problems.append(f'{where}{label} is given twice')
            continue
        unit = MEASUREMENTS[label]
        m = _NUMBER.fullmatch((cells[1] if len(cells) > 1 else '').strip())
        if not m or (m.group(2) or unit) != unit:
            problems.append(f'{where}{label}: {(cells[1] if len(cells) > 1 else "")!r} is not '
                            f'a number in {unit}')
            continue
        value = float(m.group(1))
        out[label] = value
        imperial = (cells[2] if len(cells) > 2 else '').strip()
        im = _NUMBER.fullmatch(imperial)
        if imperial and im and im.group(2) in _IMPERIAL:
            converted = float(im.group(1)) * _IMPERIAL[im.group(2)]
            if abs(converted - value) > IMPERIAL_TOLERANCE * value:
                problems.append(f'{where}{label}: {imperial} is {converted:.1f} {unit}, '
                                f'not {cells[1]}')
    return out, problems


def implausible(m: dict[str, float]) -> list[str]:
    """Why a set of measurements doesn't fit one body ([] when it does): a
    length outside `RATIO_BANDS` for its height, a scaled body-mass index
    outside `BMI_BAND`, an underbust not under the bust, or a waist over
    both chest (or bust) and hips."""
    out = []
    h = m.get('height')
    if not h:
        return ['no height, so nothing else can be checked'] if len(m) > 1 else []
    for key, (lo, hi) in RATIO_BANDS.items():
        if key in m and not lo <= m[key] / h <= hi:
            out.append(f'{key} {m[key]:g} cm is {m[key] / h:.2f} of the height '
                       f'(a body takes {lo:.2f}-{hi:.2f})')
    if 'weight' in m:
        bmi = m['weight'] / (h / 100) ** 2 * (175 / h)
        if not BMI_BAND[0] <= bmi <= BMI_BAND[1]:
            out.append(f'weight {m["weight"]:g} kg at {h:g} cm is a body-mass index of '
                       f'{bmi:.0f} (scaled to 175 cm; a body takes {BMI_BAND[0]:g}-{BMI_BAND[1]:g})')
    if 'underbust' in m and 'bust' in m and m['underbust'] >= m['bust']:
        out.append(f'underbust {m["underbust"]:g} cm is not under the bust ({m["bust"]:g} cm)')
    top = m.get('chest') or m.get('bust')
    if top and 'waist' in m and 'hips' in m and m['waist'] > top and m['waist'] > m['hips']:
        out.append(f'waist {m["waist"]:g} cm is over both chest/bust and hips')
    return out


def measurement_findings(project_dir: str) -> list[tuple[str, str]]:
    """[(severity, message)] for every sheet's measurements: a row that
    can't be used is blocking (the costume department would misread it);
    a set that doesn't fit one body is advisory (a giant, a child or a
    hunchback may be meant). [] without `series.characters`.

    Raises:
        SeriesError: as `sheet_text`.
    """
    out = []
    for cid, (shown, _) in character_sheets(project_dir).items():
        m, problems = sheet_measurements(sheet_text(project_dir, cid), shown)
        out += [('blocking', f'series.characters: {p}') for p in problems]
        out += [('advisory', f'series.characters: {shown}: {p}') for p in implausible(m)]
    return out
