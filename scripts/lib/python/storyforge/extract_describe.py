"""Extract phase 5, "describe": the reference layers above the scenes (#440).

Phases 0-4 build the scene layer. Phase 5 is to write what sits above it
(spine, architecture, story summary, story architecture, the bibles, the
voice guide, themes and motifs) from what those phases found, describing the
book as written. Plan: docs/plans/2026-10-30-extract-upper-layers.md.

It holds the one gate every phase 5 writer goes through (`write_described`)
and the provenance record it keeps, the scene evidence the steps share, and
the steps themselves.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, TypedDict, get_args

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


# ============================================================================
# Shared evidence: the scene layer in reading order
# ============================================================================

def scene_table(ref_dir: str) -> list[dict[str, str]]:
    """Every scene phases 1-3 recorded, in reading order, with the columns
    phase 5 reads: scenes.csv joined with scene-intent.csv and the briefs'
    `motifs`. Cut and merged scenes are left out (`build_scene_list`)."""
    from .elaborate import _read_csv_as_map
    from .scene_filter import build_scene_list

    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    rows = []
    for sid in build_scene_list(os.path.join(ref_dir, 'scenes.csv')):
        row = dict(scenes.get(sid, {}))
        for k, v in intent.get(sid, {}).items():
            row.setdefault(k, v)
        row['motifs'] = briefs.get(sid, {}).get('motifs', '')
        rows.append(row)
    return rows


def _scene_lines(scenes: list[dict[str, str]]) -> str:
    """One line per scene for a prompt: what phase 5's structure pass sees."""
    lines = ['seq | id | act | pov | words | action/sequel | value shift | '
             'turning point | what happens']
    for s in scenes:
        what = s.get('summary', '').strip() or s.get('function', '').strip()
        lines.append(' | '.join([
            s.get('seq', ''), s.get('id', ''), s.get('act', ''), s.get('pov', ''),
            s.get('word_count', ''), s.get('action_sequel', ''),
            s.get('value_shift', ''), s.get('turning_point', ''), what]))
    return '\n'.join(lines)


def _profile_lines(profile: dict, keys: tuple[str, ...]) -> str:
    return '\n'.join(f'- {k}: {profile[k]}' for k in keys if profile.get(k))


_DESCRIBE_STANCE = """You are describing a finished book, not planning one. Everything you write
must be true of the text as it stands. Describe what the book does; never
recommend, never correct, never call a choice a flaw. Flashbacks, frame
narration, uneven scene lengths and nested threads are the author's
decisions: describe them like any other."""


# ============================================================================
# Step 5a: structure (spine.csv, architecture.csv, genre)
# ============================================================================

#: The novel ranges `scoring_levels.score_spine` / `score_architecture` check.
SPINE_RANGE = (5, 10)
ARCHITECTURE_RANGE = (15, 25)
_SUMMARY_MAX_WORDS = 35   # scoring_levels._SUMMARY_MAX_WORDS

STRUCTURE_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['genre', 'subgenre', 'scene_summaries', 'spine', 'architecture'],
    'properties': {
        'genre': {'type': 'string'},
        'subgenre': {'type': 'string'},
        'scene_summaries': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['scene_id', 'summary'],
            'properties': {k: {'type': 'string'} for k in ('scene_id', 'summary')}}},
        'spine': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['id', 'title', 'summary', 'function'],
            'properties': {k: {'type': 'string'}
                           for k in ('id', 'title', 'summary', 'function')}}},
        'architecture': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['scene_id', 'spine_event'],
            'properties': {k: {'type': 'string'} for k in ('scene_id', 'spine_event')}}},
    },
}


class ReplyProblems(Exception):
    """A reply that parsed but can't be written; `problems` go back to the
    model on the one retry. Not a ValueError, so `_ask` can't confuse it
    with an unreadable reply whatever order its handlers are in."""

    def __init__(self, problems: list[str]):
        super().__init__('; '.join(problems))
        self.problems = problems


#: A model-chosen id: lowercase words joined by hyphens. It goes into `;`
#: lists and is looked up exactly, so anything else would break a reader.
_SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def _bounds(rng: tuple[int, int], available: int) -> tuple[int, int]:
    low, high = rng
    return min(low, available), min(high, available)


def build_structure_prompt(profile: dict, scenes: list[dict[str, str]],
                           problems: list[str] | None = None) -> str:
    """Step 5a's prompt: choose the spine events and the anchor scenes.

    Selection only. Act, POV, value shift and the other architecture columns
    are copied from the scene CSVs by code, and the anchors are existing
    scenes, so nothing here can invent a scene.
    """
    spine_lo, spine_hi = _bounds(SPINE_RANGE, len(scenes))
    blank = [s['id'] for s in scenes if not s.get('summary', '').strip()]
    summaries_ask = (
        f'2. **scene_summaries**: one sentence (at most {_SUMMARY_MAX_WORDS} words) saying '
        f'what happens, for each of these scenes, which have none yet: '
        + ', '.join(blank) + '.'
        if blank else '2. **scene_summaries**: an empty list (every scene has one).')
    arch_lo, arch_hi = _bounds(ARCHITECTURE_RANGE, len(scenes))
    retry = ''
    if problems:
        retry = ('\n## Your previous answer could not be used\n\n'
                 + '\n'.join(f'- {p}' for p in problems)
                 + '\n\nAnswer again with these fixed.\n')
    return f"""{_DESCRIBE_STANCE}

## The book

{_profile_lines(profile, ('narrative_mode', 'timeline', 'act_structure',
                          'central_conflict', 'protagonist_arc', 'major_threads', 'tone'))}

## Its scenes, in reading order

{_scene_lines(scenes)}
{retry}
## What to produce

1. **genre** and **subgenre**: how a bookseller would shelve this book (subgenre may be empty).

{summaries_ask}

3. **spine**: the {spine_lo}-{spine_hi} irreducible events of this story, in reading
   order. Remove any one and the story stops making sense. For each:
   - id: a 2-5 word lowercase-hyphenated slug of the event
   - title: a short title
   - summary: one sentence, at most {_SUMMARY_MAX_WORDS} words, saying what happens
   - function: one sentence on what the event does for the story

4. **architecture**: the {arch_lo}-{arch_hi} anchor scenes that carry the spine,
   chosen from the scene ids above (use the ids exactly). Every spine event
   needs at least one anchor. For each: scene_id, and spine_event (the spine id
   it carries). A scene is an anchor at most once. Choose the scenes where the
   story actually turns, wherever they fall; don't space them evenly.
"""


def parse_structure(response: str, scenes: list[dict[str, str]]) -> dict:
    """Read and check step 5a's reply. Returns `{genre, subgenre,
    scene_summaries, spine, architecture}`: spine events in reading order
    (by their first anchor), anchors in reading order, and scene_summaries
    mapping each scene that had no summary to the reply's.

    Raises ReplyProblems listing every problem, so one retry can fix them
    all: a scene with no summary left without one, a spine id empty,
    repeated or not a slug, a spine event with no function, an id that is
    no scene, a scene anchored twice, an anchor naming
    no spine event, a spine event with no anchor, counts outside the ranges,
    an empty or overlong summary. These are the mechanical floors; whether
    the book balances action and sequel is a fact about the book, and is
    left to the scorer to report.
    """
    from .extract import _json_answer
    data = _json_answer(response, STRUCTURE_SCHEMA)
    order = {s['id']: i for i, s in enumerate(scenes)}
    problems = []

    blank = {s['id'] for s in scenes if not s.get('summary', '').strip()}
    scene_summaries = {}
    for item in data['scene_summaries']:
        sid, text = item['scene_id'].strip(), ' '.join(item['summary'].split())
        if sid not in blank:
            continue   # a scene that has one keeps it
        if not text or len(text.split()) > _SUMMARY_MAX_WORDS:
            problems.append(f'scene {sid}\'s summary is empty or over {_SUMMARY_MAX_WORDS} words')
            continue
        scene_summaries[sid] = text
    missing = sorted(blank - set(scene_summaries), key=order.get)
    if missing:
        problems.append(f'{len(missing)} scene(s) still have no summary: '
                        + ', '.join(missing[:5]) + ('…' if len(missing) > 5 else ''))

    spine = []
    seen_spine = set()
    for e in data['spine']:
        sid = e['id'].strip()
        if not _SLUG.match(sid) or sid in seen_spine:
            problems.append(f'spine event id {sid!r} is empty, repeated, or not a '
                            f'lowercase-hyphenated slug')
            continue
        seen_spine.add(sid)
        summary = ' '.join(e['summary'].split())
        if not summary:
            problems.append(f'spine event {sid} has no summary')
        elif len(summary.split()) > _SUMMARY_MAX_WORDS:
            problems.append(f'spine event {sid}\'s summary has {len(summary.split())} '
                            f'words; at most {_SUMMARY_MAX_WORDS}')
        if not e['function'].strip():
            problems.append(f'spine event {sid} has no function')
        spine.append({'id': sid, 'title': ' '.join(e['title'].split()),
                      'summary': summary, 'function': ' '.join(e['function'].split())})

    anchors = []
    anchored = set()
    for a in data['architecture']:
        scene_id, event = a['scene_id'].strip(), a['spine_event'].strip()
        if scene_id not in order:
            problems.append(f'anchor {scene_id!r} is not one of the scene ids')
            continue
        if scene_id in anchored:
            problems.append(f'scene {scene_id} is anchored twice')
            continue
        if event not in seen_spine:
            problems.append(f'anchor {scene_id} names spine event {event!r}, '
                            f'which is not in your spine')
            continue
        anchored.add(scene_id)
        anchors.append({'scene_id': scene_id, 'spine_event': event})

    carried = {a['spine_event'] for a in anchors}
    for e in spine:
        if e['id'] not in carried:
            problems.append(f'spine event {e["id"]} has no anchor scene')

    for label, items, rng in (('spine', spine, SPINE_RANGE),
                              ('architecture', anchors, ARCHITECTURE_RANGE)):
        lo, hi = _bounds(rng, len(scenes))
        if not lo <= len(items) <= hi:
            problems.append(f'{label} has {len(items)} entries; expected {lo}-{hi}')

    if problems:
        raise ReplyProblems(problems)

    anchors.sort(key=lambda a: order[a['scene_id']])
    first = {}
    for a in anchors:
        first.setdefault(a['spine_event'], order[a['scene_id']])
    spine.sort(key=lambda e: first[e['id']])
    return {'genre': ' '.join(data['genre'].split()),
            'subgenre': ' '.join(data['subgenre'].split()),
            'scene_summaries': scene_summaries,
            'spine': spine, 'architecture': anchors}


def structure_rows(structure: dict, scenes: list[dict[str, str]],
                   ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """spine.csv and architecture.csv rows for a parsed structure.

    An anchor's row is its scene: id, seq, title, act, pov and the intent
    columns are copied from the scene CSVs, and its summary is the scene's
    own (or the one this reply gave a scene that had none). A spine event's act is the act of its first anchor, so the two
    files can't disagree about where an event falls.
    """
    by_id = {s['id']: s for s in scenes}
    arch = []
    for a in structure['architecture']:
        s = by_id[a['scene_id']]
        arch.append({
            'id': s['id'], 'seq': s.get('seq', ''), 'title': s.get('title', ''),
            'summary': s.get('summary', '').strip()
            or structure['scene_summaries'].get(s['id'], ''),
            'act': s.get('act', ''),
            'pov': s.get('pov', ''), 'spine_event': a['spine_event'],
            **{k: s.get(k, '') for k in ('action_sequel', 'emotional_arc',
                                          'value_at_stake', 'value_shift',
                                          'turning_point')},
        })
    act_of = {}
    for row in arch:
        act_of.setdefault(row['spine_event'], row['act'])
    spine = [{'id': e['id'], 'seq': str(i), 'title': e['title'],
              'summary': e['summary'], 'function': e['function'],
              'act': act_of.get(e['id'], '')}
             for i, e in enumerate(structure['spine'], 1)]
    return spine, arch


# ============================================================================
# Step 5b: themes and motifs (themes.csv, motif-taxonomy.csv, theme_threads)
# ============================================================================

Tier = Literal['primary', 'secondary', 'tertiary']
TIERS: tuple[Tier, ...] = get_args(Tier)
THEME_RANGE = (3, 7)
#: A motif must be named in at least this many scenes to be recurring.
MOTIF_MIN_SCENES = 2
#: Each brief mention is cut to this many characters in the prompt: briefs
#: describe a motif at length, and the image is in the opening words.
_MENTION_CHARS = 100


def motif_mentions(scenes: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Every motif mention in the briefs, as `(scene id, text)` in reading
    order. Briefs describe motifs in their own words ("fog pouring through
    every chink"), so the same image is rarely spelled the same way twice:
    the model groups these by number, and code checks each group recurs."""
    return [(s['id'], m.strip()) for s in scenes
            for m in s.get('motifs', '').split(';') if m.strip()]


THEMES_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['themes', 'scene_themes', 'motifs'],
    'properties': {
        'themes': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['id', 'name', 'tier', 'description'],
            'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'},
                           'tier': {'type': 'string', 'enum': list(TIERS)},
                           'description': {'type': 'string'}}}},
        'scene_themes': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['scene_id', 'themes'],
            'properties': {'scene_id': {'type': 'string'},
                           'themes': {'type': 'array', 'items': {'type': 'string'}}}}},
        'motifs': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['id', 'name', 'aliases', 'tier', 'mentions'],
            'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'},
                           'aliases': {'type': 'array', 'items': {'type': 'string'}},
                           'tier': {'type': 'string', 'enum': list(TIERS)},
                           'mentions': {'type': 'array', 'items': {'type': 'integer'}}}}},
    },
}


def build_themes_prompt(profile: dict, scenes: list[dict[str, str]],
                        mentions: list[tuple[str, str]],
                        problems: list[str] | None = None) -> str:
    """Step 5b's prompt: name the themes, tag scenes with them, and group the
    briefs' numbered motif mentions into the book's recurring motifs."""
    lo, hi = THEME_RANGE
    scene_lines = '\n'.join(
        f'{s["id"]}: {s.get("function", "").strip() or s.get("summary", "").strip()}'
        f' [stake: {s.get("value_at_stake", "")}; shift: {s.get("value_shift", "")}]'
        for s in scenes)
    mention_lines = '\n'.join(
        f'[{i}] {sid}: {" ".join(text.split())[:_MENTION_CHARS]}'
        for i, (sid, text) in enumerate(mentions)) or '(the briefs name no motifs)'
    retry = ''
    if problems:
        retry = ('\n## Your previous answer could not be used\n\n'
                 + '\n'.join(f'- {p}' for p in problems)
                 + '\n\nAnswer again with these fixed.\n')
    return f"""{_DESCRIBE_STANCE}

## The book

{_profile_lines(profile, ('central_conflict', 'protagonist_arc', 'major_threads', 'tone'))}

## Its scenes, in reading order (what each does, and the value it turns on)

{scene_lines}

## Every motif the scene briefs name, numbered

{mention_lines}
{retry}
## What to produce

1. **themes**: the {lo}-{hi} abstract concerns this book argues, each phrased as
   what the book is about rather than a moral. For each: id (a 1-4 word
   lowercase-hyphenated slug, letters and digits only), name, tier (primary for the book's central
   concerns, then secondary and tertiary), and description (one or two
   sentences on how the book treats it). Themes are abstract; concrete
   recurring images are motifs, below.

2. **scene_themes**: for every scene id above, the theme ids it engages
   (an empty list where a scene engages none).

3. **motifs**: the book's recurring images and objects, found by grouping
   the numbered mentions above that name the same image. Each: id (a 1-3
   word slug), name, aliases (1-4 short names a reader might use for it,
   such as "fog", with no semicolons; each alias names one motif only),
   tier, and mentions (the numbers of every mention it covers). A motif must
   recur: its mentions must come from at least {MOTIF_MIN_SCENES} different
   scenes. Leave out mentions that belong to no recurring image; a mention
   belongs to at most one motif. If any image recurs, return at least one
   motif.
"""


def parse_themes(response: str, scenes: list[dict[str, str]],
                 mentions: list[tuple[str, str]]) -> dict:
    """Read and check step 5b's reply. Returns `{themes, scene_themes,
    motifs, mention_motif}`: `scene_themes` maps every scene id to a list of
    theme ids, each motif carries `scenes` (the scene ids its mentions come
    from), and `mention_motif` maps each claimed mention's number to its
    motif id.

    Raises ReplyProblems listing every problem: an id empty, repeated or not
    a slug, a tier outside TIERS, a theme count outside THEME_RANGE, a scene
    tagged with an unknown theme, a scene left out or invented, a mention
    number out of range or claimed twice, an alias with a `;` or given to
    two motifs, a motif that doesn't recur, or no motif at all when the
    mentions span two or more scenes (whether any recur is the model's
    call; code can only see that they could).
    """
    from .extract import _json_answer
    data = _json_answer(response, THEMES_SCHEMA)
    problems = []

    themes, theme_ids = [], set()
    for t in data['themes']:
        tid = t['id'].strip()
        if not _SLUG.match(tid) or tid in theme_ids:
            problems.append(f'theme id {tid!r} is empty, repeated, or not a '
                            f'lowercase-hyphenated slug')
            continue
        if t['tier'] not in TIERS:
            problems.append(f'theme {tid}\'s tier {t["tier"]!r} is not one of {", ".join(TIERS)}')
        theme_ids.add(tid)
        themes.append({'id': tid, 'name': ' '.join(t['name'].split()),
                       'tier': t['tier'],
                       'description': ' '.join(t['description'].split())})
    lo, hi = THEME_RANGE
    if not lo <= len(themes) <= hi:
        problems.append(f'themes has {len(themes)} entries; expected {lo}-{hi}')

    scene_ids = [s['id'] for s in scenes]
    tagged: dict[str, list[str]] = {}
    for st in data['scene_themes']:
        sid = st['scene_id'].strip()
        if sid not in scene_ids:
            problems.append(f'scene_themes names {sid!r}, which is not a scene id')
            continue
        unknown = [t for t in st['themes'] if t.strip() not in theme_ids]
        if unknown:
            problems.append(f'scene {sid} is tagged with unknown theme(s): '
                            + ', '.join(unknown))
        tagged[sid] = list(dict.fromkeys(t.strip() for t in st['themes']
                                         if t.strip() in theme_ids))
    missing = [sid for sid in scene_ids if sid not in tagged]
    if missing:
        problems.append(f'{len(missing)} scene(s) missing from scene_themes: '
                        + ', '.join(missing[:5]) + ('…' if len(missing) > 5 else ''))

    claimed: dict[int, str] = {}
    alias_of: dict[str, str] = {}
    out_motifs, motif_ids = [], set()
    for m in data['motifs']:
        mid = m['id'].strip()
        if not _SLUG.match(mid) or mid in motif_ids:
            problems.append(f'motif id {mid!r} is empty, repeated, or not a '
                            f'lowercase-hyphenated slug')
            continue
        if m['tier'] not in TIERS:
            problems.append(f'motif {mid}\'s tier {m["tier"]!r} is not one of {", ".join(TIERS)}')
        motif_ids.add(mid)
        used = []
        for n in m['mentions']:
            if not isinstance(n, int) or not 0 <= n < len(mentions):
                problems.append(f'motif {mid} names mention [{n}], which does not exist')
            elif n in claimed and claimed[n] != mid:
                problems.append(f'mention [{n}] is claimed by both {claimed[n]} and {mid}')
            else:
                claimed[n] = mid
                used.append(n)
        in_scenes = list(dict.fromkeys(mentions[n][0] for n in sorted(used)))
        if len(in_scenes) < MOTIF_MIN_SCENES:
            problems.append(f'motif {mid} is named in {len(in_scenes)} scene(s); a motif '
                            f'must recur in at least {MOTIF_MIN_SCENES}')
        bad = [a for a in m['aliases'] if ';' in a]
        if bad:
            problems.append(f'motif {mid}\'s alias(es) contain a semicolon: '
                            + ', '.join(repr(a) for a in bad))
        aliases = list(dict.fromkeys(' '.join(a.split()).lower() for a in m['aliases']
                                     if a.strip() and ';' not in a))
        # An alias names one motif, or normalizing a brief against the
        # registry can't tell which it means
        for a in aliases:
            if alias_of.setdefault(a, mid) != mid:
                problems.append(f'alias {a!r} is given to both {alias_of[a]} and {mid}')
        out_motifs.append({'id': mid, 'name': ' '.join(m['name'].split()),
                           'aliases': aliases, 'tier': m['tier'], 'scenes': in_scenes})
    if not out_motifs and len({sid for sid, _ in mentions}) >= MOTIF_MIN_SCENES:
        problems.append('motifs is empty; group the mentions that name the same image '
                        'into the motifs that recur')

    if problems:
        raise ReplyProblems(problems)
    return {'themes': themes, 'scene_themes': tagged, 'motifs': out_motifs,
            'mention_motif': dict(claimed)}


# ============================================================================
# Running the steps
# ============================================================================

STRUCTURE_MAX_TOKENS = 12_000
THEMES_MAX_TOKENS = 12_000
#: What 5b's brief rewrite replaced: every mention as the brief had it, and
#: the motif it was grouped into ('' when it named no recurring image).
MENTIONS_FILE = os.path.join('working', 'extraction-motif-mentions.csv')

#: What a step did: wrote all its files, wrote none (each reason reported),
#: or wrote some and stopped (a file changed during the call).
StepOutcome = Literal['written', 'skipped', 'partial']

ProjectField = Literal['genre', 'subgenre']
#: The values that count as unfilled, per field. The template's genre is the
#: placeholder; its subgenre is empty.
_PROJECT_PLACEHOLDERS: dict[ProjectField, frozenset[str]] = {
    'genre': frozenset({'', 'PROJECT_GENRE'}),
    'subgenre': frozenset({''}),
}


class DescribeFailed(RuntimeError):
    """A phase 5 step could not get a usable answer; nothing was written for it."""


@dataclass(kw_only=True)
class Run:
    """What every step shares: where to write, how to call, what to record."""
    project_dir: str
    model: str
    log_dir: str
    force: bool
    version: str
    #: Read once by the caller, which stops when it is unusable (None)
    provenance: dict[str, ProvenanceRow]
    #: (log file, operation, target, model): records the call's cost
    on_usage: Callable[[str, str, str, str], None]
    reports: list[str] = field(default_factory=list)

    @property
    def ref_dir(self) -> str:
        return os.path.join(self.project_dir, 'reference')


def _cell(value: str) -> str:
    """A value as an unquoted pipe-CSV cell: one line, no `|`
    (`common.csv_safe`), and no leading `"`, which `csv.DictReader` would
    read as an opening quote."""
    from .common import csv_safe
    text = csv_safe(str(value))
    return '\u201c' + text[1:] if text.startswith('"') else text


def _csv_text(rows: list[dict[str, str]], columns: list[str]) -> str:
    """Rows as this project writes CSV: `|`-joined, unquoted, LF. A quoting
    writer would wrap a cell holding `"` or `|`, which the readers that
    split on `|` (story-power, alias maps, export) can't undo."""
    lines = ['|'.join(columns)]
    lines += ['|'.join(_cell(row.get(c, '')) for c in columns) for row in rows]
    return '\n'.join(lines) + '\n'


def _ask(run: Run, label: str, prompt_for, parse, schema: dict, max_tokens: int):
    """One structured call, with one retry carrying the parser's problems.

    Raises DescribeFailed on an API error or refusal, a cut-off, unreadable
    or malformed reply, or when the retry still has problems: a step either
    gets an answer it can write whole or writes nothing.
    """
    from .api import extract_text, invoke_to_file, is_truncated
    problems = None
    for attempt in (1, 2):
        log_file = os.path.join(run.log_dir, f'extract-describe-{label}-{attempt}.json')
        try:
            response = invoke_to_file(prompt_for(problems), run.model, log_file, max_tokens,
                                      output_schema=schema)
        except RuntimeError as e:   # HTTP errors, retries exhausted, a refusal
            raise DescribeFailed(f'{label}: the API call failed ({e})') from e
        run.on_usage(log_file, f'extract-describe-{label}', 'book', run.model)
        if is_truncated(response):
            raise DescribeFailed(f'{label}: the reply hit its token limit')
        try:
            return parse(extract_text(response))
        except ReplyProblems as e:
            if attempt == 2:
                raise DescribeFailed(f'{label}: still unusable after a retry: {e}') from e
            log(f'  {label}: {len(e.problems)} problem(s) in the reply; asking once more')
            problems = e.problems
        except ValueError as e:
            raise DescribeFailed(f'{label}: unreadable reply ({e})') from e
        except (KeyError, TypeError, AttributeError) as e:
            # Structured outputs shouldn't send a malformed item, but one
            # that comes is the reply's fault, not a crash
            raise DescribeFailed(f'{label}: malformed reply ({type(e).__name__}: {e})') from e
    raise AssertionError('unreachable')


def _gate(run: Run, rels: list[str], step: str, also: str) -> bool:
    """Whether every file a step writes may be written; reports the ones
    that can't, and what else the step then doesn't do (`also`). A step
    writes all its files or none, so its outputs can't disagree (an
    architecture naming a spine the author kept)."""
    verdicts = [decide(run.project_dir, rel, run.force, run.provenance) for rel in rels]
    kept = [v for v in verdicts if not v.write]
    if kept:
        run.reports.extend(v.report() for v in kept)
        run.reports.append(f'{step} skipped: it writes {", ".join(rels)} together, and '
                           f'{len(kept)} of them must be kept; {also} were not filled either')
        return False
    return True


def _write_all(run: Run, files: list[tuple[str, str]], step: str, label: str) -> bool:
    """Write a step's files through the gate. False, with a report, when one
    was refused after all: the author changed it during the call. The step
    then stops before anything that depends on its files."""
    refused = []
    for rel, content in files:
        verdict = write_described(run.project_dir, rel, content, step=step,
                                  version=run.version, force=run.force,
                                  provenance=run.provenance)
        if verdict.write:
            log(f'  wrote {rel}')
        else:
            refused.append(verdict.report())
    if refused:
        run.reports.extend(refused)
        run.reports.append(f'{label} stopped part-way: a file changed while it ran, so '
                           f'its files may disagree; check them and run it again')
        return False
    return True


def _registry_ids(path: str) -> set[str]:
    from .elaborate import _read_csv
    return {r.get('id', '').strip() for r in _read_csv(path) if r.get('id', '').strip()}


def _set_cells(run: Run, filename: str, column: str, values: dict[str, str],
               replaceable: Callable[[str], bool]) -> tuple[int, dict[str, str]]:
    """Set `column` for each scene id in `values` whose current cell is
    `replaceable`, in the scene CSV that owns it; a scene with no row there
    gets none (a row written here would have nothing else in it). Returns
    how many were set, and the cells kept because they were not replaceable
    (scene id: current value)."""
    from .elaborate import _read_csv_as_map, update_scene
    rows = _read_csv_as_map(os.path.join(run.ref_dir, filename))
    changed, kept = 0, {}
    for sid, value in values.items():
        row = rows.get(sid)
        if row is None:
            continue
        current = row.get(column, '').strip()
        if current == value:
            continue
        if not replaceable(current):
            kept[sid] = current
            continue
        update_scene(sid, run.ref_dir, {column: _cell(value)})
        changed += 1
    return changed, kept


def _fill_project_field(run: Run, key: ProjectField, value: str) -> None:
    """Set `project.<key>` in storyforge.yaml when it is still empty or the
    template's placeholder; an author's value is kept. Edits that one line
    inside the `project:` block, keeping its inline comment where it was and
    the file's line endings."""
    from .common import _yaml_double_quote, read_yaml_field, rewrite_preserving_newlines
    if not value:
        return
    path = os.path.join(run.project_dir, 'storyforge.yaml')
    if not os.path.isfile(path):
        run.reports.append(f'storyforge.yaml: missing, so project.{key} was not set '
                           f'(the book reads as {value!r})')
        return
    current = read_yaml_field(f'project.{key}', run.project_dir)
    if current not in _PROJECT_PLACEHOLDERS[key]:
        return
    values = [r'""', r"''"]
    for v in sorted(_PROJECT_PLACEHOLDERS[key]):
        if v:
            values += [f'"{re.escape(v)}"', f"'{re.escape(v)}'", re.escape(v)]
    line_re = re.compile(rf'^([ \t]+{key}:)[ \t]*(?:{"|".join(values)})?[ \t]*(#.*)?$')
    done = []

    def edit(text: str) -> str:
        lines = text.split('\n')
        in_project = False
        for i, line in enumerate(lines):
            if line and not line[0].isspace() and not line.startswith('#'):
                in_project = line.rstrip() == 'project:'
                continue
            m = line_re.match(line) if in_project else None
            if not m:
                continue
            head = f'{m.group(1)} {_yaml_double_quote(value)}'
            comment = m.group(2) or ''
            if comment:
                # Keep the comment in its column when the value fits before it
                col = len(line) - len(comment)
                head += ' ' * max(1, col - len(head)) + comment
            lines[i] = head
            done.append(i)
            break
        return '\n'.join(lines)

    if rewrite_preserving_newlines(path, edit):
        log(f'  set project.{key}: {value}')
    elif not done:
        run.reports.append(f'storyforge.yaml: project.{key} not set (no `{key}:` line '
                           f'under project: to fill); the book reads as {value!r}')


def run_structure(run: Run, profile: dict, scenes: list[dict[str, str]]) -> StepOutcome:
    """Step 5a: spine.csv, architecture.csv, blank scene summaries,
    anchors' architecture_scene, and project.genre / subgenre."""
    from .elaborate import _ARCHITECTURE_COLS, _SPINE_COLS
    rels = ['reference/spine.csv', 'reference/architecture.csv']
    if not _gate(run, rels, '5a (structure)',
                 'blank scene summaries, architecture_scene and project.genre'):
        return 'skipped'
    old_anchors = _registry_ids(os.path.join(run.project_dir, rels[1]))
    structure = _ask(run, 'structure',
                     lambda problems: build_structure_prompt(profile, scenes, problems),
                     lambda text: parse_structure(text, scenes),
                     STRUCTURE_SCHEMA, STRUCTURE_MAX_TOKENS)
    spine, arch = structure_rows(structure, scenes)
    if not _write_all(run, [(rels[0], _csv_text(spine, _SPINE_COLS)),
                            (rels[1], _csv_text(arch, _ARCHITECTURE_COLS))], '5a', '5a'):
        return 'partial'
    n, _ = _set_cells(run, 'scenes.csv', 'summary', structure['scene_summaries'],
                      replaceable=lambda cur: not cur)
    if n:
        log(f'  filled {n} blank scene summar{"y" if n == 1 else "ies"}')
    # An anchor marks itself. A cell naming an anchor this run dropped is
    # the last run's mark (an author's would name a scene of their own
    # choosing that still exists) and is cleared, or it would dangle
    anchors = {r['id'] for r in arch}
    marks = {s['id']: (s['id'] if s['id'] in anchors else '') for s in scenes}
    _, kept = _set_cells(
        run, 'scenes.csv', 'architecture_scene', marks,
        replaceable=lambda cur: not cur or (cur in old_anchors and cur not in anchors))
    dangling = [sid for sid, cur in kept.items() if cur not in anchors]
    if dangling:
        run.reports.append(f'{len(dangling)} scene(s) keep an architecture_scene that names no '
                           f'anchor in architecture.csv: ' + ', '.join(dangling[:5])
                           + ('…' if len(dangling) > 5 else ''))
    _fill_project_field(run, 'genre', structure['genre'])
    _fill_project_field(run, 'subgenre', structure['subgenre'])
    return 'written'


def _write_mentions(run: Run, scenes_mentions: list[tuple[str, str]],
                    mention_motif: dict[int, str]) -> None:
    path = os.path.join(run.project_dir, MENTIONS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = [{'scene_id': sid, 'mention': text, 'motif': mention_motif.get(i, '')}
            for i, (sid, text) in enumerate(scenes_mentions)]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(_csv_text(rows, ['scene_id', 'mention', 'motif']))


def run_themes(run: Run, profile: dict, scenes: list[dict[str, str]]) -> StepOutcome:
    """Step 5b: themes.csv, motif-taxonomy.csv, theme_threads, and each
    brief's `motifs` cell as motif ids.

    The brief rewrite is what keeps `validate` passing: once the taxonomy
    has rows, a brief's `motifs` is checked against it, and a description
    ("fog pouring through every chink") matches no alias. Each cell becomes
    the ids its mentions were grouped into; a mention that named no
    recurring image is dropped from the cell. Nothing is lost: every
    mention as the brief had it, and its motif, is kept in MENTIONS_FILE.
    """
    from .elaborate import _MOTIF_COLS, _THEMES_COLS
    rels = ['reference/themes.csv', 'reference/motif-taxonomy.csv']
    if not _gate(run, rels, '5b (themes and motifs)', 'theme_threads and brief motifs'):
        return 'skipped'
    old_themes = _registry_ids(os.path.join(run.project_dir, rels[0]))
    mentions = motif_mentions(scenes)
    result = _ask(run, 'themes',
                  lambda problems: build_themes_prompt(profile, scenes, mentions, problems),
                  lambda text: parse_themes(text, scenes, mentions),
                  THEMES_SCHEMA, THEMES_MAX_TOKENS)
    motif_rows = [{**m, 'aliases': ';'.join(m['aliases'])} for m in result['motifs']]
    if not _write_all(run, [(rels[0], _csv_text(result['themes'], _THEMES_COLS)),
                            (rels[1], _csv_text(motif_rows, _MOTIF_COLS))], '5b', '5b'):
        return 'partial'
    # A cell made only of the last run's theme ids is the last run's tagging
    # (themes.csv was extraction's, or the gate would have kept it), so it is
    # retagged; one naming anything else is the author's, and kept
    def stale_or_blank(cur: str) -> bool:
        ids = [t.strip() for t in cur.split(';') if t.strip()]
        return not ids or all(t in old_themes for t in ids)
    _, kept = _set_cells(run, 'scene-intent.csv', 'theme_threads',
                         {sid: ';'.join(ids) for sid, ids in result['scene_themes'].items()},
                         replaceable=stale_or_blank)
    if kept:
        ids = list(kept)
        run.reports.append(f'{len(ids)} scene(s) keep a theme_threads cell of the author\'s: '
                           + ', '.join(ids[:5]) + ('…' if len(ids) > 5 else ''))
    by_scene: dict[str, list[str]] = {}
    for n, (sid, _) in enumerate(mentions):
        by_scene.setdefault(sid, [])
        motif = result['mention_motif'].get(n)
        if motif and motif not in by_scene[sid]:
            by_scene[sid].append(motif)
    _write_mentions(run, mentions, result['mention_motif'])
    n, _ = _set_cells(run, 'scene-briefs.csv', 'motifs',
                      {sid: ';'.join(ids) for sid, ids in by_scene.items()},
                      replaceable=lambda cur: True)
    if n:
        log(f'  briefs: {n} motifs cell(s) now name motif ids (the descriptions are in '
            f'{MENTIONS_FILE})')
    return 'written'


#: Every path phase 5 may change, for the commit. `working/` covers the
#: provenance record, the mentions file, the logs and the cost ledger.
WRITTEN_PATHS = ['reference/spine.csv', 'reference/architecture.csv',
                 'reference/scenes.csv', 'reference/scene-intent.csv',
                 'reference/scene-briefs.csv', 'reference/themes.csv',
                 'reference/motif-taxonomy.csv', 'storyforge.yaml', 'working/']
