"""Extract phase 5, "describe": the reference layers above the scenes (#440).

Phases 0-4 build the scene layer. Phase 5 is to write what sits above it
(spine, architecture, story summary, story architecture, the bibles, the
voice guide, themes and motifs) from what those phases found, describing the
book as written. Plan: docs/plans/2026-10-30-extract-upper-layers.md.

This module so far holds the one gate every phase 5 writer goes through,
`write_described`, and the provenance record it keeps.

**Never overwrite an author's file.** A file is written only when it holds
nothing of the author's: missing, empty, a CSV with only a header, or still
the template init copied in. Under `--force`, a file extraction itself
wrote is rewritten too, but only while its bytes still match the hash
recorded when it was written: an extracted doc the author has since edited
is theirs, and is reported rather than replaced. `_POLICY` is the whole
rule, one entry per `FileState`.

**Provenance** lives in `working/extraction-provenance.csv`
(`file|version|step|written_at|sha256`), one row per file. Markdown docs
also carry `provenance_header`'s comment line for a person reading them,
but the code trusts only the hash: an author can edit a body and keep the
header line. The content-free states are judged on decoded text (a BOM and
CRLF don't count), the hash on raw bytes, so an extracted doc an editor
re-saves with CRLF reads as `edited` and is kept. That asymmetry is the safe
direction and deliberate.
"""

from __future__ import annotations

import csv
import hashlib
import os
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypedDict

from .common import is_unfilled_template, log

PROVENANCE_FILE = os.path.join('working', 'extraction-provenance.csv')


class ProvenanceRow(TypedDict):
    file: str          # project-relative, '/'-separated (`_key`)
    version: str       # the Storyforge version that wrote it
    step: str          # the phase 5 step ('5a', '5c', ...)
    written_at: str    # ISO 8601 UTC
    sha256: str        # of the bytes written


PROVENANCE_COLUMNS: list[str] = list(ProvenanceRow.__annotations__)

#: Provenance as read: rows by `_key`, or None when the record exists but
#: can't be trusted (unreadable, or not this file's shape). None is not {}:
#: an empty record means extraction has written nothing yet.
Provenance = dict[str, ProvenanceRow] | None

FileState = Literal[
    'missing',        # not on disk
    'empty',          # whitespace only
    'header_only',    # a CSV with a header row and no data rows
    'template',       # still the template init copied in
    'extracted',      # written by phase 5, bytes unchanged since
    'edited',         # written by phase 5, changed since: the author's now
    'author',         # anything else with content
    'symlink',        # a link, live or dangling: writing would land elsewhere
    'unreadable',     # can't be read or decoded
    'unverified',     # has content, and the provenance record can't be read
]

Rule = Literal['free', 'force', 'never']

#: The whole write rule: whether each state is written over, and the reason
#: reported when it isn't. A test holds this total over FileState.
_POLICY: dict[FileState, tuple[Rule, str]] = {
    'missing': ('free', ''),
    'empty': ('free', ''),
    'header_only': ('free', ''),
    'template': ('free', ''),
    'extracted': ('force', 'extracted earlier; --force regenerates it'),
    'edited': ('never', 'extracted earlier, then edited; delete it to have '
                        'extraction write it again'),
    'author': ('never', "the author's own; extraction never replaces it"),
    'symlink': ('never', 'a symbolic link; extraction never writes through one'),
    'unreadable': ('never', 'could not be read, so it was not replaced'),
    'unverified': ('never', f'{PROVENANCE_FILE} could not be read, so whether '
                            f'extraction wrote this is unknown'),
}

#: A one-line CSV is only a header if its fields look like column names and
#: include a key column; `grief|Grief|core` is a row someone wrote.
_COLUMN_NAME = re.compile(r'^[a-z_][a-z0-9_]*$')
_KEY_COLUMNS = frozenset({'id', 'character', 'principle', 'entity', 'scope', 'cycle'})


class ProvenanceError(RuntimeError):
    """The provenance record can't be read, so nothing can be recorded in it.

    Raised rather than rewriting the record from nothing, which would erase
    every other file's row."""


@dataclass(frozen=True)
class Verdict:
    """What the gate decided for one file. `reason` is None exactly when it
    was (or may be) written; otherwise it is the sentence to report."""
    rel_path: str
    state: FileState
    reason: str | None

    @property
    def write(self) -> bool:
        return self.reason is None

    def report(self) -> str:
        return f'{self.rel_path}: kept ({self.reason})' if self.reason else ''


def _key(rel_path: str) -> str:
    """One spelling per file, so `./reference/x.md` and `reference/x.md`
    can't become two rows."""
    return posixpath.normpath(rel_path.replace(os.sep, '/'))


def _sha256(path: str) -> str:
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_provenance(project_dir: str) -> Provenance:
    """Provenance rows keyed by `_key`; `{}` when there is no record yet.

    None, with a WARNING, when a record exists that can't be used: not a
    regular file, unreadable, or a header other than PROVENANCE_COLUMNS.
    Callers then treat every file with content as `unverified` (never
    written) and `write_described` refuses to record, so a broken record
    is never silently replaced by a one-row one.
    """
    path = os.path.join(project_dir, PROVENANCE_FILE)
    if not os.path.lexists(path):
        return {}
    problem = ''
    if os.path.islink(path) or not os.path.isfile(path):
        problem = 'it is not a regular file'
    else:
        try:
            with open(path, encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f, delimiter='|')
                rows = list(reader)
                fields = reader.fieldnames or []
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            problem = str(e)
        else:
            if fields != PROVENANCE_COLUMNS:
                problem = (f'its header is {"|".join(fields)!r}, '
                           f'not {"|".join(PROVENANCE_COLUMNS)!r}')
    if problem:
        log(f'WARNING: {PROVENANCE_FILE} could not be used ({problem}); no '
            f'extracted reference doc can be regenerated or recorded until it '
            f'is fixed or deleted')
        return None
    return {_key(r['file']): r for r in rows if r.get('file')}  # type: ignore[misc]


def file_state(project_dir: str, rel_path: str, provenance: Provenance) -> FileState:
    """What `rel_path` (relative to the project) holds.

    `provenance` is `read_provenance`'s result, read once by the caller: a
    broken record warns once, not once per file.
    """
    path = os.path.join(project_dir, rel_path)
    if os.path.islink(path):
        return 'symlink'
    if not os.path.exists(path):
        return 'missing'
    try:
        with open(path, encoding='utf-8-sig') as f:
            text = f.read()
        digest = _sha256(path)
    except (OSError, UnicodeDecodeError) as e:
        log(f'WARNING: {rel_path} could not be read ({e})')
        return 'unreadable'
    # Content-free states first: a file emptied or reset to its template
    # holds nothing of the author's, whoever wrote it before
    if not text.strip():
        return 'empty'
    if rel_path.endswith('.csv'):
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) == 1:
            fields = [f.strip() for f in lines[0].split('|')]
            # Any header, not just today's: projects initialized from older
            # templates carry older headers
            if all(_COLUMN_NAME.match(f) for f in fields) and _KEY_COLUMNS & set(fields):
                return 'header_only'
    if is_unfilled_template(path):
        return 'template'
    if provenance is None:
        return 'unverified'
    record = provenance.get(_key(rel_path))
    if record is not None:
        return 'extracted' if record.get('sha256') == digest else 'edited'
    return 'author'


def decide(project_dir: str, rel_path: str, force: bool,
           provenance: Provenance) -> Verdict:
    """The gate's verdict for one file, from `_POLICY`."""
    state = file_state(project_dir, rel_path, provenance)
    rule, reason = _POLICY[state]
    writable = rule == 'free' or (rule == 'force' and force)
    return Verdict(rel_path, state, None if writable else reason)


def provenance_header(version: str, step: str, sources: list[str]) -> str:
    """The first line of an extracted markdown doc, for a person reading it."""
    return (f'<!-- storyforge:extracted v{version or "unknown"} step={step} '
            f'from={",".join(sources)} -->')


def _save_provenance(project_dir: str, rows: dict[str, ProvenanceRow]) -> None:
    path = os.path.join(project_dir, PROVENANCE_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=PROVENANCE_COLUMNS, delimiter='|',
                                lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows[k] for k in sorted(rows))


def write_described(project_dir: str, rel_path: str, content: str, *,
                    step: str, version: str, force: bool,
                    provenance: Provenance) -> Verdict:
    """The only way phase 5 writes a file: decide, write, record.

    Writes `content` (LF, UTF-8) only when `decide` allows it, then records
    the hash of the bytes written in the record and in `provenance` (updated
    in place, so later checks in the same run see it). Returns the verdict
    for the caller to report: `verdict.report()` is the refusal, '' when
    written.

    Raises ProvenanceError, before writing anything, when the record can't
    be read (`provenance` is None): a file written now could never be
    recorded, and rewriting the record would erase every other row.
    """
    if provenance is None:
        raise ProvenanceError(f'{PROVENANCE_FILE} could not be read; fix or '
                              f'delete it, then run this step again')
    verdict = decide(project_dir, rel_path, force, provenance)
    if not verdict.write:
        return verdict
    path = os.path.join(project_dir, rel_path)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    key = _key(rel_path)
    provenance[key] = {
        'file': key, 'version': version, 'step': step,
        'written_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'sha256': _sha256(path),
    }
    _save_provenance(project_dir, provenance)
    return verdict
