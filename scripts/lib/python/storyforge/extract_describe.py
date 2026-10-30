"""Extract phase 5, "describe": the reference layers above the scenes (#440).

Phases 0-4 build the scene layer. Phase 5 writes what sits above it (spine,
architecture, story summary, story architecture, the bibles, the voice
guide, themes and motifs) from what those phases found, describing the book
as written. Plan: docs/plans/2026-10-30-extract-upper-layers.md.

This module so far holds the rule every phase 5 writer goes through,
`file_state` / `may_write`, and the provenance record that rule reads.

**Never overwrite an author's file.** A file is written only when it holds
nothing of the author's: missing, empty, a CSV with only a header, or still
the template init copied in. Under `--force`, a file extraction itself
wrote is rewritten too, but only while its bytes still match the hash
recorded when it was written: an extracted doc the author has since edited
is theirs, and is reported rather than replaced.

**Provenance** lives in `working/extraction-provenance.csv`
(`file|version|step|written_at|sha256`), one row per file. Markdown docs
also carry `provenance_header`'s comment line for a person reading them,
but the code trusts only the hash: an author can edit a body and keep the
header line.
"""

from __future__ import annotations

import csv
import hashlib
import os
from datetime import datetime, timezone
from typing import Literal

from .common import is_unfilled_template, log

PROVENANCE_FILE = os.path.join('working', 'extraction-provenance.csv')
PROVENANCE_COLUMNS = ['file', 'version', 'step', 'written_at', 'sha256']

FileState = Literal[
    'missing',        # not on disk
    'empty',          # whitespace only
    'header_only',    # a CSV with a header row and no data rows
    'template',       # still the template init copied in
    'extracted',      # written by phase 5 and unchanged since
    'edited',         # written by phase 5, changed since: the author's now
    'author',         # anything else with content
    'unreadable',     # can't be read or decoded: never written over
]

#: States phase 5 writes over without being asked. Everything else is either
#: the author's or unknown.
_FREE_STATES: frozenset[FileState] = frozenset(
    {'missing', 'empty', 'header_only', 'template'})


def _sha256(path: str) -> str:
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_provenance(project_dir: str) -> dict[str, dict[str, str]]:
    """Provenance rows keyed by project-relative path (`/`-separated).

    A missing file is an empty record. An unreadable one is also empty, with a
    WARNING: every extracted doc then reads as the author's, so `--force`
    refuses rather than overwrites, which is the safe direction to fail.
    """
    path = os.path.join(project_dir, PROVENANCE_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f, delimiter='|'))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        log(f'WARNING: {PROVENANCE_FILE} could not be read ({e}); every '
            f'extracted reference doc is treated as the author\'s')
        return {}
    return {r['file']: r for r in rows if r.get('file')}


def file_state(project_dir: str, rel_path: str,
               provenance: dict[str, dict[str, str]] | None = None) -> FileState:
    """What `rel_path` (relative to the project) holds, for `may_write`.

    `provenance` is `read_provenance`'s result, passed in so a step checking
    several files reads the record once.
    """
    if provenance is None:
        provenance = read_provenance(project_dir)
    path = os.path.join(project_dir, rel_path)
    if not os.path.exists(path):
        return 'missing'
    try:
        with open(path, encoding='utf-8-sig') as f:
            text = f.read()
        digest = _sha256(path)
    except (OSError, UnicodeDecodeError):
        return 'unreadable'
    # Content-free states first: a file emptied or reset to its template
    # holds nothing of the author's, whoever wrote it before
    if not text.strip():
        return 'empty'
    if rel_path.endswith('.csv'):
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) <= 1:
            # Any header: templates have lagged the schema before
            return 'header_only'
    if is_unfilled_template(path):
        return 'template'
    record = provenance.get(rel_path.replace(os.sep, '/'))
    if record is not None:
        return 'extracted' if record.get('sha256') == digest else 'edited'
    return 'author'


def may_write(state: FileState, force: bool) -> bool:
    """Whether phase 5 writes over a file in `state`.

    Free states always; `extracted` only under `force`; never `edited`,
    `author` or `unreadable`.
    """
    return state in _FREE_STATES or (force and state == 'extracted')


def refusal(rel_path: str, state: FileState, force: bool) -> str:
    """The sentence reporting why `rel_path` was left alone ('' if it wasn't)."""
    if may_write(state, force):
        return ''
    if state == 'extracted':
        return f'{rel_path}: kept (extracted earlier; --force regenerates it)'
    if state == 'edited':
        return (f'{rel_path}: kept (extracted earlier, then edited; delete it '
                f'to have extraction write it again)')
    if state == 'unreadable':
        return f'{rel_path}: kept (could not be read, so it was not replaced)'
    return f'{rel_path}: kept (the author\'s own; extraction never replaces it)'


def provenance_header(version: str, step: str, sources: list[str]) -> str:
    """The first line of an extracted markdown doc, for a person reading it."""
    return (f'<!-- storyforge:extracted v{version or "unknown"} step={step} '
            f'from={",".join(sources)} -->')


def record_written(project_dir: str, rel_path: str, step: str,
                   version: str) -> None:
    """Record that phase 5 just wrote `rel_path`, with the hash of its bytes.

    Call it right after the write, so the hash is what was written. Replaces
    any earlier row for the file. Written with LF endings, like every CSV
    Storyforge writes.
    """
    key = rel_path.replace(os.sep, '/')
    rows = read_provenance(project_dir)
    rows[key] = {
        'file': key,
        'version': version,
        'step': step,
        'written_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'sha256': _sha256(os.path.join(project_dir, rel_path)),
    }
    path = os.path.join(project_dir, PROVENANCE_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=PROVENANCE_COLUMNS, delimiter='|',
                                lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows[k] for k in sorted(rows))
