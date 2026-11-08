"""A series' shared canon: reference files several books read in place.

A book in a series names the canon it shares in `storyforge.yaml`:

    series:
      canon:
        - ../../homer/series-bible/gods.md
        - ../../homer/series-bible/cast.md

`canon:` is a list, or one path on its line. Each path is relative to the
project (or absolute, or `~/...`). A path to a directory means its `.md`
files, in name order. List the files when the directory also holds notes or
open questions that aren't canon.

The canon goes into every prompt that carries the project's bibles: the
shared system context (`common.build_shared_context`: drafting, revision,
scoring) and the elaborate stages' reference section
(`prompts_elaborate._existing_refs`). Storyforge never writes to it. The
book's own bibles hold what is particular to that book; stages that rewrite a
bible rewrite the book's, so one book's run can't change the canon the other
books read.

A canon that can't be used is an error, never skipped: a file that is
missing, empty or unreadable, or a directory with no `.md` file in it, raises
`SeriesError`. `SeriesError` is a `source.SourceError`, so every command that
stops cleanly on a bad `source:` block stops the same way on a bad `series:`
block, and `validate` reports it as a blocking finding.
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


class SeriesError(SourceError):
    """A `series:` block, or a canon file it names, that can't be used."""


def _series_block(project_dir: str) -> list[str] | None:
    """The lines under a top-level `series:` key, or None without one."""
    path = os.path.join(project_dir, 'storyforge.yaml')
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise SeriesError(f'storyforge.yaml could not be read: {e}') from e
    for i, line in enumerate(lines):
        if re.match(r'^series:\s*(#.*)?$', line):
            block = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[0].isspace() and not nxt.lstrip().startswith('#'):
                    break
                block.append(nxt)
            return block
        if re.match(r'^series:\s*\S', line):
            raise SeriesError('storyforge.yaml: `series:` must be a block holding '
                              '`canon:`, not a value')
    return None


def canon_paths(project_dir: str) -> list[str]:
    """The `series.canon` paths as written, in order; [] with no `series:`
    block or no `canon:` in it.

    Raises:
        SeriesError: a key the block doesn't take, `canon:` given twice, or a
            line that is neither a key nor a list item.
    """
    block = _series_block(project_dir)
    if block is None:
        return []
    content = [l for l in block if l.strip() and not l.lstrip().startswith('#')]
    if not content:
        return []
    indent = len(content[0]) - len(content[0].lstrip())
    paths: list[str] = []
    seen: set[str] = set()
    current = None
    for line in content:
        depth = len(line) - len(line.lstrip())
        stripped = line.strip()
        if depth == indent and not stripped.startswith('-'):
            m = re.match(r'^(\w+):\s*(.*)$', stripped)
            if not m:
                raise SeriesError(f"storyforge.yaml: can't read {stripped!r} in the "
                                  f'`series:` block (write `canon:` and a list of paths)')
            key, value = m.group(1), parse_yaml_scalar(m.group(2))
            if key not in BLOCK_KEYS:
                raise SeriesError(f'storyforge.yaml: the `series:` block has `{key}`; '
                                  f'it takes {", ".join(BLOCK_KEYS)}')
            if key in seen:
                raise SeriesError(f'storyforge.yaml: the `series:` block gives `{key}` twice')
            seen.add(key)
            current = key
            if value:
                paths.append(value)
            continue
        if stripped.startswith('-') and current == 'canon':
            value = parse_yaml_scalar(stripped[1:].strip())
            if not value:
                raise SeriesError('storyforge.yaml: `series.canon` has an empty list item')
            paths.append(value)
            continue
        raise SeriesError(f"storyforge.yaml: can't read {stripped!r} in the `series:` block "
                          f'(write `canon:` and a list of paths)')
    return paths


def _resolve(project_dir: str, path: str) -> str:
    return os.path.normpath(os.path.join(project_dir, os.path.expanduser(path)))


def canon_files(project_dir: str) -> list[tuple[str, str]]:
    """[(path as configured, absolute path)] for each canon file, a
    directory expanded to its `.md` files in name order. A file named twice
    (directly and through its directory) is read once, where it first comes.

    Raises:
        SeriesError: the block can't be read, or a path is neither a file nor
            a directory holding `.md` files.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in canon_paths(project_dir):
        full = _resolve(project_dir, path)
        if os.path.isdir(full):
            names = sorted(n for n in os.listdir(full)
                           if n.endswith('.md') and os.path.isfile(os.path.join(full, n)))
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


def canon_text(project_dir: str) -> list[tuple[str, str]]:
    """[(label, text)] of the series canon for a prompt, in order; [] with no
    `series.canon`. Each label names the file as configured; the first
    text opens with `CANON_NOTE`.

    Raises:
        SeriesError: as `canon_files`, or a canon file that is empty or
            can't be read as UTF-8.
    """
    out = []
    for shown, abs_path in canon_files(project_dir):
        try:
            with open(abs_path, encoding='utf-8') as f:
                text = f.read().lstrip('﻿').strip()
        except (OSError, UnicodeDecodeError) as e:
            raise SeriesError(f"series.canon: can't read {shown}: {e}") from e
        if not text:
            raise SeriesError(f'series.canon: {shown} is empty')
        if not out:
            text = f'{CANON_NOTE}\n\n{text}'
        out.append((f'Series Canon ({shown})', text))
    return out


def summary_line(project_dir: str) -> str:
    """One line for `validate`: what the canon holds, or '' with none.

    Raises:
        SeriesError: as `canon_text`.
    """
    texts = canon_text(project_dir)
    if not texts:
        return ''
    words = sum(len(t.split()) for _, t in texts)
    return f'Series canon: {len(texts)} file(s), {words:,} words, read from outside the project'
