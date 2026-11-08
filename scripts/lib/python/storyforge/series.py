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
BLOCK_KEYS = ('canon',)
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
    block.

    Raises:
        SeriesError: as `_series_block`; a block that names no canon (empty,
            or `canon:` with no paths); a key the block doesn't take, `canon:`
            given twice, a value that isn't a path, an empty list item, or a
            line that is neither a key nor a list item.
    """
    block = _series_block(project_dir)
    if block is None:
        return []
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
            if value:
                paths.append(value)
            continue
        if stripped.startswith('-') and current == 'canon':
            value = _path_value(stripped[1:])
            if not value:
                raise SeriesError('series.canon: an empty list item')
            paths.append(value)
            continue
        raise SeriesError(f"storyforge.yaml: can't read {stripped!r} in the `series:` block "
                          f'(write `canon:` and a list of paths)')
    if not paths:
        raise SeriesError('storyforge.yaml: the `series:` block names no canon; '
                          'list the files under `canon:`, or remove the block')
    return paths


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


def summary_lines(project_dir: str) -> list[str]:
    """`validate`'s lines: the files read and their words (the files' own,
    not `CANON_NOTE`); [] without a `series:` block.

    Raises:
        SeriesError: as `canon_docs`.
    """
    docs = canon_docs(project_dir)
    if not docs:
        return []
    words = sum(len(t.split()) for _, t in docs)
    return ([f'Series canon: {len(docs)} file(s), {words:,} words, read in place '
             f'and never written'] + [f'  {shown}' for shown, _ in docs])
