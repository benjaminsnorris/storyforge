"""Extract phase 5, "describe": the reference layers above the scenes (#440).

Phases 0-4 build the scene layer. Phase 5 writes what sits above it
(spine, architecture, themes and motifs, story summary and architecture,
the character, world and systems bibles, the voice guide and profile) from
what those phases found, describing the book as written; `timeline.md` and
the chapter map (5g) are still to come. Plan: docs/plans/2026-10-30-extract-upper-layers.md.

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
import json
import os
import posixpath
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, TypedDict, get_args

from .common import is_unfilled_template, log
#: elaborate's voice-profile.csv columns, which `validate_voice_profile` checks
from .schema import VOICE_PROFILE_COLUMNS

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
    `motifs` and `motif_details`. Cut and merged scenes are left out (`build_scene_list`)."""
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
        row['motif_details'] = briefs.get(sid, {}).get('motif_details', '')
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
    own (or the one this reply gave a scene that had none). A spine event's
    act is the act of its first anchor, so the two files can't disagree
    about where an event falls.
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
    the model groups these by number, and code checks each group recurs.

    Read from `motif_details` when the brief has it: once 5b has run,
    `motifs` holds ids and the descriptions live there."""
    return [(s['id'], m.strip()) for s in scenes
            for m in (s.get('motif_details', '').strip() or s.get('motifs', '')).split(';')
            if m.strip()]


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
# Step 5c: the story summary and the story architecture (one call)
# ============================================================================

#: The L0-L2 floors (`scoring_levels.score_logline`, `score_synopsis`,
#: `score_act_shape`). L0 and L1 are checked here with the scorer's own
#: counters, and L2 holds by construction (`render_story_summary` writes
#: exactly three `### Act N`), so a written summary can't fail them.
LOGLINE_MAX_WORDS = 35
SYNOPSIS_SENTENCES = (4, 8)
#: `story-summary.md`'s Act-shape is always three `### Act N` sections (the
#: L2 floor). The book's own division, whatever it is, goes in the
#: architecture's Structure section, keyed by `scenes.csv:act`.
ACT_SHAPE_KEYS = ('act_1', 'act_2', 'act_3')
_STRING = {'type': 'string'}
_STRINGS = {'type': 'array', 'items': _STRING}


def _object(properties: dict) -> dict:
    return {'type': 'object', 'additionalProperties': False,
            'required': list(properties), 'properties': properties}


PITCH_SCHEMA = _object({
    'logline': _STRING,
    'synopsis': _STRING,
    'act_shape': _object({k: _STRING for k in ACT_SHAPE_KEYS}),
    'theme': _STRING,
    'premise': _STRING,
    'core_theme': _STRING,
    'motif_meanings': {'type': 'array', 'items': _object(
        {'motif_id': _STRING, 'meaning': _STRING})},
    'conflict': _object({k: _STRING for k in ('external', 'internal', 'thematic')}),
    'promise': _STRINGS,
    'structural_model': _STRING,
    'acts': {'type': 'array', 'items': _object({
        'act': _STRING, 'title': _STRING, 'description': _STRING,
        'key_beats': _STRINGS, 'turning_point': _STRING})},
    'subplots': {'type': 'array', 'items': _object(
        {k: _STRING for k in ('name', 'characters', 'function', 'arc')})},
    'pov': _object({'pattern': _STRING, 'excluded': _STRING}),
    'voice': _object({'prose_style': _STRING, 'pacing': _STRING}),
    'never_does': _STRINGS,
    'title_meaning': _object({k: _STRING for k in ('surface', 'deeper', 'final')}),
    'identity': _object({'pov': _STRING, 'tone': _STRING}),
})


@dataclass(frozen=True)
class ActLength:
    """One of the book's acts as scenes.csv divides it, measured by code."""
    act: str
    scenes: int
    words: int
    uncounted: int     # scenes with no numeric word_count, left out of `words`


def _word_count(scene: dict[str, str]) -> int | None:
    """A scene's `word_count`, or None when it isn't a plain number
    (`str.isdigit` accepts digits like '²' that `int` rejects)."""
    words = scene.get('word_count', '').strip()
    return int(words) if words.isascii() and words.isdecimal() else None


def act_lengths(scenes: list[dict[str, str]]) -> list[ActLength]:
    """The book's acts in the order each first appears, from
    `scenes.csv:act`, with their scene and word counts. An act whose scenes
    recur later (a frame, braided parts) is counted under its first
    appearance; a scene with no act is grouped under ''."""
    acts: dict[str, list[int]] = {}
    for s in scenes:
        counts = acts.setdefault(s.get('act', '').strip(), [0, 0, 0])
        counts[0] += 1
        words = _word_count(s)
        if words is None:
            counts[2] += 1
        else:
            counts[1] += words
    return [ActLength(act, scenes=n, words=w, uncounted=u)
            for act, (n, w, u) in acts.items()]


@dataclass(frozen=True)
class PitchEvidence:
    """What 5c is given beyond the profile and the scenes: the spine, themes
    and motifs 5a and 5b wrote (or the author's, when they kept theirs),
    `mice-threads.csv`, the project's title and genre, and the act lengths
    from `scenes.csv`. Read by code, so the rendered docs copy them (title,
    genre, themes, motif names, lengths) rather than ask the model. `acts`
    comes from the same scenes the prompt shows, so a pitch parsed against
    this evidence is only valid with it."""
    title: str              # '' when storyforge.yaml has none or the placeholder
    genre: str
    spine: list[dict[str, str]]
    themes: list[dict[str, str]]
    motifs: list[dict[str, str]]     # rows with a blank id are left out (`notes`)
    threads: list[dict[str, str]]
    acts: list[ActLength]
    #: The evidence files that had rows, for the provenance header
    sources: list[str] = field(default_factory=list)
    #: What 5c had to work without, one sentence each, for the report
    notes: list[str] = field(default_factory=list)


#: The columns 5c reads from each evidence file. A file without them is
#: one 5c can't describe from, so it stops rather than misread it.
_EVIDENCE_COLUMNS = {
    'spine.csv': ('title', 'summary', 'function'),
    'themes.csv': ('id', 'name', 'tier', 'description'),
    'motif-taxonomy.csv': ('id', 'name'),
    'mice-threads.csv': ('id', 'name', 'type'),
}
_TITLE_PLACEHOLDERS = frozenset({'', 'PROJECT_TITLE'})


def _evidence_rows(project_dir: str, name: str) -> tuple[list[dict[str, str]], str]:
    """A reference CSV's rows, and why there are none ('' when there are).

    Raises DescribeFailed naming the file when it can't be read or lacks a
    column 5c reads: the author's file is reported, never guessed around."""
    from .elaborate import _read_csv
    rel = f'reference/{name}'
    path = os.path.join(project_dir, 'reference', name)
    if not os.path.isfile(path):
        return [], f'{rel} is absent'
    try:
        with open(path, encoding='utf-8') as f:
            header = f.readline().rstrip('\r\n')
        rows = _read_csv(path) if header.strip() else []
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise DescribeFailed(f'5c: {rel} could not be read ({e})') from e
    if not header.strip():
        return [], f'{rel} is empty'
    lacking = [c for c in _EVIDENCE_COLUMNS[name] if c not in header.split('|')]
    if lacking:
        raise DescribeFailed(f'5c: {rel} has no {", ".join(lacking)} column; fix its header, '
                             f'then run phase 5 again')
    return rows, '' if rows else f'{rel} has no rows'


def pitch_evidence(project_dir: str, scenes: list[dict[str, str]]) -> PitchEvidence:
    """Read 5c's evidence. Raises DescribeFailed when a file can't be used."""
    from .common import read_yaml_field
    found, notes, sources = {}, [], []
    for name in _EVIDENCE_COLUMNS:
        found[name], why = _evidence_rows(project_dir, name)
        if why:
            notes.append(why)
        else:
            sources.append(name.removesuffix('.csv'))
    motifs = [m for m in found['motif-taxonomy.csv'] if m.get('id', '').strip()]
    if len(motifs) < len(found['motif-taxonomy.csv']):
        notes.append(f'{len(found["motif-taxonomy.csv"]) - len(motifs)} row(s) of '
                     f'reference/motif-taxonomy.csv have no id and were left out')
    title, title_notes = _book_title(project_dir)
    notes += title_notes
    genre = read_yaml_field('project.genre', project_dir)
    if genre in _PROJECT_PLACEHOLDERS['genre']:
        genre = ''
    subgenre = read_yaml_field('project.subgenre', project_dir)
    return PitchEvidence(
        title=title,
        genre=f'{genre} ({subgenre})' if genre and subgenre else genre,
        spine=found['spine.csv'], themes=found['themes.csv'], motifs=motifs,
        threads=found['mice-threads.csv'], acts=act_lengths(scenes),
        sources=sources, notes=notes)


def _act_label(act: str) -> str:
    """An act value as a heading: `1` is "Act 1", `Part One` stays itself."""
    if not act:
        return 'Scenes with no act'
    return f'Act {act}' if act.isdigit() else act


def build_pitch_prompt(profile: dict, scenes: list[dict[str, str]], ev: PitchEvidence,
                       problems: list[str] | None = None) -> str:
    """Step 5c's prompt: the story summary and the story architecture in one
    call, so the logline, the premise and the act shapes can't disagree.

    Lengths, POV counts, the themes and the motif names are rendered by
    code from the CSVs; the model describes."""
    lo, hi = SYNOPSIS_SENTENCES
    spine = '\n'.join(f'{i}. {r.get("title", "")}: {r.get("summary", "")} '
                      f'(function: {r.get("function", "")})'
                      for i, r in enumerate(ev.spine, 1)) or '(none recorded)'
    themes = '\n'.join(f'- {r.get("id", "")} ({r.get("tier", "")}): {r.get("name", "")}. '
                       f'{r.get("description", "")}' for r in ev.themes) or '(none recorded)'
    motifs = '\n'.join(f'- {r.get("id", "")}: {r.get("name", "")}' for r in ev.motifs) \
        or '(none recorded)'
    threads = '\n'.join(f'- {r.get("id", "")} ({r.get("type", "")}): {r.get("name", "")}'
                        for r in ev.threads) or '(none recorded)'
    acts = ', '.join(json.dumps(a.act) for a in ev.acts)
    if any(not a.act for a in ev.acts):
        acts += ' ("" is the scenes with no act)'
    retry = ''
    if problems:
        retry = ('\n## Your previous answer could not be used\n\n'
                 + '\n'.join(f'- {p}' for p in problems)
                 + '\n\nAnswer again with these fixed.\n')
    return f"""{_DESCRIBE_STANCE}

## The book

- title: {ev.title or '(none recorded: leave title_meaning\'s fields empty)'}
- genre: {ev.genre or '(not recorded)'}
{_profile_lines(profile, ('narrative_mode', 'timeline', 'act_structure', 'central_conflict',
                          'protagonist_arc', 'major_threads', 'tone'))}

## Its spine (the irreducible events)

{spine}

## Its themes

{themes}

## Its recurring motifs

{motifs}

## Its narrative threads (MICE)

{threads}

## Its scenes, in reading order

{_scene_lines(scenes)}
{retry}
## What to produce

Every field is plain prose on one line: no headings, no bullets, no line
breaks. Reveal the ending everywhere; this is for the author, not a pitch.

The story summary:
1. **logline**: one sentence, at most {LOGLINE_MAX_WORDS} words: the protagonist, what
   they want, what stands in the way, and what is at stake.
2. **synopsis**: one paragraph of {lo}-{hi} sentences telling the whole story, ending included.
3. **act_shape**: the story in three movements (act_1 the setup through the
   inciting incident, act_2 the escalation and the midpoint, act_3 the climax
   and what the resolution costs), one paragraph each, whether or not the
   book divides itself into three.
4. **theme**: two to four sentences on what the story argues: its central
   question or claim.

The story architecture:
5. **premise**: one sentence saying what the novel is about.
6. **core_theme**: the central question the book dramatizes, phrased as a question.
7. **motif_meanings**: for every motif id listed above, motif_id and meaning
   (one sentence on what the image carries in this book).
8. **conflict**: external (the observable problem), internal (the
   protagonist's inner struggle) and thematic (the values that collide).
9. **promise**: 3-5 short statements of the experience the book delivers to a reader.
10. **structural_model**: one or two sentences naming how the book is built
    (three acts, four parts, a frame, braided timelines...).
11. **acts**: one entry for each of the book's acts as its scenes divide it,
    using these act values exactly: {acts}. For each: act, title, description
    (one sentence on what the act does), key_beats (3-6 events, in order) and
    turning_point (what changes at its end; for the last act, the closing
    image), without a label in front of it.
12. **subplots**: the threads beside the main plot. For each: name,
    characters, function (what it does for the main story) and arc (where it
    starts, turns and resolves). An empty list if there are none.
13. **pov**: pattern (who narrates, and in what pattern) and excluded (who
    never gets a point of view, and what that does; empty if not notable).
14. **voice**: prose_style (what makes the prose distinct) and pacing (where
    the book slows and where it accelerates).
15. **never_does**: 2-5 things the book consistently never does (a
    description of its restraint, not advice).
16. **title_meaning**: surface, deeper and final (what the title means by the
    end); all three empty when the book has no title recorded above.
17. **identity**: pov (a short phrase, such as "first person, past tense,
    Nick Carraway") and tone (a short phrase).
"""


def _one_line(text: str) -> str:
    """Model prose as one markdown line that can't start a heading, quote,
    comment or list item: a `##` line would split `parse_story_summary`'s
    sections, a `### Act N` would change the L2 act count, a leading
    `<!--` could hide the rest of the summary from its parser, and any of
    them would break `story-architecture.md`'s structure."""
    text = ' '.join(text.split())
    if text[:1] in ('#', '>', '<') or text[:2] in ('- ', '* ', '+ '):
        return '\\' + text
    return text


#: A label the model sometimes repeats at the start of a field the doc
#: already labels ("**Closing image:** Closing image: ...", live on Carol),
#: bold or not, with a colon or a dash.
_ECHOED_LABEL = re.compile(r'^\**\s*(?:closing image|turning point)\s*\**\s*[:\u2014\u2013-]'
                           r'\s*\**\s*', re.IGNORECASE)
#: Fields matched exactly against the book's own values, so only stripped:
#: cleaning them like prose could make a real act value unmatchable.
_ID_FIELDS = frozenset({'act', 'motif_id'})


def _clean_reply(value, path: str = ''):
    """Every string in a reply on one line (`_one_line`; ids only stripped),
    empty list items dropped. Raises TypeError on a value that isn't a
    string, which `_ask` reports as a malformed reply: a nested null must
    not reach the doc as the word "None"."""
    if isinstance(value, dict):
        return {k: _clean_reply(v, f'{path}.{k}' if path else k) for k, v in value.items()}
    if isinstance(value, list):
        return [c for c in (_clean_reply(v, path) for v in value) if c]
    if not isinstance(value, str):
        raise TypeError(f'{path} is {type(value).__name__}, not a string')
    return value.strip() if path.rsplit('.', 1)[-1] in _ID_FIELDS else _one_line(value)


def _empty_fields(value, path: str, optional) -> list[str]:
    """The paths of the empty strings and lists in a cleaned reply."""
    if isinstance(value, dict):
        return [p for k, v in value.items()
                for p in _empty_fields(v, f'{path}.{k}' if path else k, optional)]
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return [p for i, v in enumerate(value) for p in _empty_fields(v, f'{path}[{i}]', optional)]
    if value or optional(path):
        return []
    return [f'{path} has no items' if isinstance(value, list) else f'{path} is empty']


def parse_pitch(response: str, ev: PitchEvidence) -> dict:
    """Read and check step 5c's reply against the evidence it was asked
    with. Returns the reply cleaned (`_clean_reply`), with each act's
    turning point stripped of an echoed label, `acts` in the book's act
    order, and `motif_meanings` as {motif id: meaning} covering every motif
    in `ev.motifs`.

    Raises ValueError (from `_json_answer`) on an unreadable reply,
    TypeError on a value that isn't a string, and ReplyProblems listing
    every problem: the L0-L1 floors by the scorer's own counters (an
    overlong logline, a synopsis outside SYNOPSIS_SENTENCES), any empty
    field or list (except `pov.excluded`, an act value, and title_meaning
    when the book has no title), an act that isn't one of the book's,
    repeated or left out, and a motif id unknown, repeated, left out or
    given no meaning.
    """
    from .extract import _json_answer
    from .scoring_levels import _count_sentences, _count_words
    data = _clean_reply(_json_answer(response, PITCH_SCHEMA))
    for a in data['acts']:
        a['turning_point'] = _ECHOED_LABEL.sub('', a['turning_point'])

    def optional(path: str) -> bool:
        return (path == 'pov.excluded' or path.endswith('.act')
                or path == 'subplots' or (not ev.title and path.startswith('title_meaning.')))
    problems = _empty_fields({k: v for k, v in data.items() if k != 'motif_meanings'},
                             '', optional)

    words = _count_words(data['logline'])
    if words > LOGLINE_MAX_WORDS:
        problems.append(f'logline has {words} words; at most {LOGLINE_MAX_WORDS}')
    lo, hi = SYNOPSIS_SENTENCES
    sentences = _count_sentences(data['synopsis'])
    if not lo <= sentences <= hi:
        problems.append(f'synopsis has {sentences} sentences; expected {lo}-{hi}')

    order = {a.act: i for i, a in enumerate(ev.acts)}
    acts, seen = [], set()
    for a in data['acts']:
        act = a['act']
        if act not in order:
            problems.append(f'acts names {act!r}, which is not one of the book\'s acts '
                            f'({", ".join(json.dumps(x.act) for x in ev.acts)})')
        elif act in seen:
            problems.append(f'act {act!r} is described twice')
        else:
            seen.add(act)
            acts.append(a)
    missing = [json.dumps(a.act) for a in ev.acts if a.act not in seen]
    if missing:
        problems.append('acts leaves out act(s): ' + ', '.join(missing))
    data['acts'] = sorted(acts, key=lambda a: order[a['act']])

    known = [m['id'].strip() for m in ev.motifs]
    meanings: dict[str, str] = {}
    for m in data['motif_meanings']:
        mid = m.get('motif_id', '')
        if mid not in known:
            problems.append(f'motif_meanings names {mid!r}, which is not a motif id')
        elif mid in meanings:
            problems.append(f'motif {mid} is given two meanings')
        elif m.get('meaning'):
            meanings[mid] = m['meaning']
    unmeant = [mid for mid in known if mid not in meanings]
    if unmeant:
        problems.append(f'{len(unmeant)} motif(s) have no meaning: '
                        + ', '.join(unmeant[:5]) + ('…' if len(unmeant) > 5 else ''))
    data['motif_meanings'] = meanings

    if problems:
        raise ReplyProblems(problems)
    return data


def render_story_summary(pitch: dict, header: str, today: str) -> str:
    """`story-summary.md` in the shape `common.parse_story_summary` reads:
    the provenance comment, `_updated` stamps, and four `##` sections."""
    stamps = '\n'.join(f'{k}_updated: {today}'
                       for k in ('logline', 'synopsis', 'act_shape', 'theme'))
    acts = '\n\n'.join(f'### Act {i}\n\n{pitch["act_shape"][k]}'
                       for i, k in enumerate(ACT_SHAPE_KEYS, 1))
    return (f'{header}\n---\n{stamps}\n---\n\n# Story summary\n\n'
            f'## Logline\n\n{pitch["logline"]}\n\n'
            f'## Synopsis\n\n{pitch["synopsis"]}\n\n'
            f'## Act-shape\n\n{acts}\n\n'
            f'## Theme\n\n{pitch["theme"]}\n')


def _cell_md(text: str) -> str:
    """Text for a markdown table cell: a backslash or `|` escaped, so `\\|`
    in model text can't become a cell delimiter."""
    return text.replace('\\', '\\\\').replace('|', '\\|')


def _bullets(items: list[str]) -> str:
    return '\n'.join(f'- {i}' for i in items) or '- (none)'


def render_story_architecture(pitch: dict, ev: PitchEvidence, scenes: list[dict[str, str]],
                              header: str) -> str:
    """`story-architecture.md`, in the template's sections, with the
    prescriptive ones renamed to what they describe ("Things to Avoid" is
    "What the book never does", "Target Length" is "Length") and the POV
    section restructured as a pattern plus a counted table. Lengths,
    shares, POV counts, themes and motif names come from the CSVs."""
    total = sum(a.words for a in ev.acts)
    uncounted = sum(a.uncounted for a in ev.acts)
    meanings = pitch['motif_meanings']
    supporting = [t for t in ev.themes if t.get('tier', '') != 'primary']
    primary = [t for t in ev.themes if t.get('tier', '') == 'primary']

    out = [header, f'# {ev.title or "Untitled"} -- Story Architecture', '', '---', '',
           '## Premise', '', f'> {pitch["premise"]}', '', '---', '',
           '## Theme', '', '### Core Theme', pitch['core_theme'], '']
    if primary:
        out += [_bullets([f'**{t.get("name", "")}**: {t.get("description", "")}'
                          for t in primary]), '']
    out += ['### Supporting Themes',
            _bullets([f'**{t.get("name", "")}** ({t.get("tier", "")}): '
                      f'{t.get("description", "")}' for t in supporting]), '',
            '### Motifs & Symbols', '', '| Motif | Meaning |', '|---|---|']
    out += [f'| {_cell_md(m.get("name", ""))} | {_cell_md(meanings.get(m.get("id", ""), ""))} |'
            for m in ev.motifs] or ['| (none recorded) | |']
    c = pitch['conflict']
    out += ['', '---', '', '## Central Conflict', '',
            '### External Conflict', c['external'], '',
            '### Internal Conflict', c['internal'], '',
            '### Thematic Conflict', c['thematic'], '', '---', '',
            '## The Promise of the Premise', '', _bullets(pitch['promise']), '', '---', '',
            '## Structure', '', '### Length',
            f'{total:,} words in {len(scenes)} scenes'
            + (f' ({uncounted} scene(s) with no word count in scenes.csv are not counted)'
               if uncounted else ''), '',
            '### Structural Model', pitch['structural_model'], '']
    by_act = {a['act']: a for a in pitch['acts']}
    for i, length in enumerate(ev.acts):
        a = by_act[length.act]
        share = f'{round(100 * length.words / total)}%' if total else 'an unknown share'
        closing = 'Closing image' if i == len(ev.acts) - 1 else 'Turning point'
        out += ['---', '', f'### {_act_label(length.act)}: {a["title"]}',
                f'**{share} of the novel (~{length.words:,} words, {length.scenes} scenes)**',
                f'*{a["description"]}*', '', '**Key beats:**', _bullets(a['key_beats']), '',
                f'**{closing}:** {a["turning_point"]}', '']
    out += ['---', '', '## Subplots', '']
    for s in pitch['subplots']:
        out += [f'### {s["name"]}', f'- Characters involved: {s["characters"]}',
                f'- Function: {s["function"]}', f'- Arc: {s["arc"]}', '']
    if not pitch['subplots']:
        out += ['None: the book follows a single line.', '']
    pov_counts: dict[str, list[int]] = {}
    for s in scenes:
        counts = pov_counts.setdefault(s.get('pov', '').strip() or '(none recorded)', [0, 0])
        counts[0] += 1
        counts[1] += _word_count(s) or 0
    out += ['---', '', '## Point of View Structure', '', '### Pattern', pitch['pov']['pattern'],
            '', '| POV | Scenes | Words |', '|---|---|---|']
    out += [f'| {_cell_md(p)} | {n} | {w:,} |'
            for p, (n, w) in sorted(pov_counts.items(), key=lambda kv: -kv[1][0])]
    if pitch['pov']['excluded']:
        out += ['', '### Excluded POVs', pitch['pov']['excluded']]
    v = pitch['voice']
    t = pitch['title_meaning']
    out += ['', '---', '', '## Voice & Pacing', '', '### Prose Style', v['prose_style'], '',
            '### Pacing', v['pacing'], '', '### What the book never does',
            _bullets(pitch['never_does']), '', '---', '', '## The Title', '']
    if ev.title:
        out += [f'1. **Surface meaning:** {t["surface"]}',
                f'2. **Deeper meaning:** {t["deeper"]}',
                f'3. **Final meaning (by the end):** {t["final"]}']
    else:
        out += ['No title is recorded (`project.title` in storyforge.yaml).']
    out += ['', '---', '', '## Novel Identity Summary', '',
            f'**Title:** {ev.title or "(not recorded)"}  ', f'**Genre:** {ev.genre or "(not recorded)"}  ',
            f'**Length:** {total:,} words, {len(scenes)} scenes  ',
            f'**Structure:** {pitch["structural_model"]}  ',
            f'**POV:** {pitch["identity"]["pov"]}  ', f'**Tone:** {pitch["identity"]["tone"]}  ',
            f'**Core theme:** {pitch["core_theme"]}', '']
    return '\n'.join(out)


# ============================================================================
# Steps 5d-5f: the character bible, the world bible, the voice guide
# ============================================================================

#: What a description field says when the book doesn't show the thing.
#: The model leaves such a field empty rather than invent it.
UNSHOWN = 'Not shown in the text.'
#: Words that open an instruction. A described habit is a statement about
#: the book ("The narrator never explains the Spirits"), never an order to
#: a writer (decision 2: describe, never prescribe). "Never"/"always" are
#: instructions only before a bare verb ("Never explain"), not a described
#: one ("Never explains"); words that are as often nouns ("Close third",
#: "End-of-chapter hooks", "Use of dialect") aren't listed.
_IMPERATIVE = re.compile(
    r"^(?:(?:do|don't|do not|avoid|keep|let|make|write|prefer|vary|anchor|trust|"
    r"reserve|limit|be)\b|use\b(?! of)|(?:never|always)\s+(?![a-z']+s\b)[a-z']+\b)",
    re.IGNORECASE)
CharacterTier = Literal['primary', 'secondary']
CHARACTER_TIERS: tuple[CharacterTier, ...] = get_args(CharacterTier)
_TIER_ENUM = {'type': 'string', 'enum': list(CHARACTER_TIERS)}


def _shown(text: str) -> str:
    return text or UNSHOWN


def _imperatives(items: list[str], path: str) -> list[str]:
    return [f'{path} item {item[:40]!r} reads as an instruction; describe what the book '
            f'does instead (for example "The narrator never ...")'
            for item in items if _IMPERATIVE.match(item)]


def _sample(items: list, n: int) -> list:
    """At most `n` (two or more) of `items`, spread evenly, keeping the
    first and last."""
    if len(items) <= n:
        return list(items)
    step = (len(items) - 1) / (max(n, 2) - 1)
    return [items[round(i * step)] for i in range(max(n, 2))]


def _first(ids: list[str], n: int = 5) -> str:
    return ', '.join(ids[:n]) + ('…' if len(ids) > n else '')


def _prose(project_dir: str, scenes: list[dict[str, str]]) -> tuple[dict[str, str], list[str]]:
    """Every scene's prose (illustration markers removed), and a note
    naming the scenes with no file or a blank one.

    Raises DescribeFailed naming the file when one exists but can't be
    read: describing the voice from the scenes that are left would state
    wrong measures as the whole book's."""
    from .illustrations import strip_markers
    texts, absent = {}, []
    for s in scenes:
        rel = f'scenes/{s["id"]}.md'
        path = os.path.join(project_dir, rel)
        if not os.path.isfile(path):
            absent.append(s['id'])
            continue
        try:
            with open(path, encoding='utf-8') as f:
                text = strip_markers(f.read())
        except (OSError, UnicodeDecodeError) as e:
            raise DescribeFailed(f'{rel} could not be read ({e})') from e
        if text.strip():
            texts[s['id']] = text
        else:
            absent.append(s['id'])
    notes = [f'{len(absent)} of {len(scenes)} scene(s) have no prose in scenes/ (absent or '
             f'blank): {_first(absent)}'] if absent else []
    return texts, notes


def _fixed_facts(project_dir: str, types: tuple[str, ...]) -> tuple[list[dict[str, str]], list[str]]:
    """The ledger's binding facts of `types` that don't change (`fixed`),
    with their quotes, and a note when there are none to read: no ledger,
    one not yet migrated, or one that can't be read. The bibles are then
    described without facts, and that is said."""
    from . import ledger
    if not os.path.isfile(ledger.ledger_path(project_dir)) and \
            not ledger.legacy_files(os.path.join(project_dir, 'reference')):
        return [], ['reference/commitments.csv is absent, so the bibles use no established '
                    'facts']
    try:
        rows = ledger.load(project_dir)
    except ledger.NotMigratedError:
        return [], ['the ledger is not migrated (reference/knowledge.csv or '
                    'physical-states.csv is still there), so the bibles use no established '
                    'facts; run `storyforge migrate` to use them']
    except (ledger.LedgerError, OSError, UnicodeDecodeError) as e:
        return [], [f'the ledger could not be read ({e}), so the bibles use no established facts']
    return [r for r in rows if r.get('status') == 'binding' and r.get('mutable') == 'fixed'
            and r.get('type') in types and r.get('statement', '').strip()], []


def _fact_line(row: dict[str, str]) -> str:
    quote = ' '.join(row.get('quote', '').split())
    return (f'{row.get("type", "")}: {" ".join(row["statement"].split())}'
            + (f' ("{quote}")' if quote else ''))


def _registry(project_dir: str, name: str,
              ) -> tuple[list[dict[str, str]], dict[str, str], list[str]]:
    """A registry's rows (ids stripped), its lowercase name/alias/id → id
    map, and notes: the file absent or empty, rows with no id (left out).

    Raises DescribeFailed naming the file when it can't be read or has no
    `id` or `name` column: names could then resolve to nothing, or to a
    name `load_alias_map` falls back on, and the step would describe the
    wrong people or places."""
    from .elaborate import _read_csv
    from .enrich import load_alias_map
    rel = f'reference/{name}'
    path = os.path.join(project_dir, 'reference', name)
    if not os.path.isfile(path):
        return [], {}, [f'{rel} is absent']
    try:
        with open(path, encoding='utf-8') as f:
            header = f.readline().rstrip('\r\n')
        rows = _read_csv(path) if header.strip() else []
        alias = load_alias_map(path) if header.strip() else {}
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise DescribeFailed(f'{rel} could not be read ({e})') from e
    if not header.strip():
        return [], {}, [f'{rel} is empty']
    lacking = [c for c in ('id', 'name') if c not in header.split('|')]
    if lacking:
        raise DescribeFailed(f'{rel} has no {", ".join(lacking)} column; fix its header, then '
                             f'run phase 5 again')
    kept = [{**r, 'id': r['id'].strip()} for r in rows if r.get('id', '').strip()]
    ids = {r['id'] for r in kept}
    notes = [f'{len(rows) - len(kept)} row(s) of {rel} have no id and are left out'] \
        if len(kept) < len(rows) else []
    if not kept:
        notes.append(f'{rel} has no rows')
    return kept, {k: v for k, v in alias.items() if v in ids}, notes


def _names(cell: str) -> list[str]:
    return [n.strip() for n in cell.split(';') if n.strip()]


# --- 5d: characters ---------------------------------------------------------

#: The most characters 5d describes; past it the lowest-ranked (by POV
#: scenes, role, then scenes on stage) are left out, and that is reported.
MAX_CHARACTERS = 16
MAX_FACTS_PER_CHARACTER = 15
MAX_MOMENTS = 12
MAX_LINES = 8
#: How `characters.csv:role` ranks a character for the bible, before scene
#: counts: a supporting character on stage once (Tiny Tim) comes before a
#: minor one on stage twice. Roles not listed rank between supporting and minor.
_ROLE_RANK = {'protagonist': 0, 'antagonist': 0, 'deuteragonist': 0, 'supporting': 1,
              'minor': 3, 'referenced': 4}
#: How far either side of a quote a speech tag ("said Scrooge") is looked
#: for, never past the neighbouring quote.
_ATTRIBUTION_CHARS = 80
_SPEECH_VERBS = (r'said|says|asked|asks|cried|replied|returned|exclaimed|answered|'
                 r'whispered|muttered|shouted|added|continued|observed|rejoined|repeated|'
                 r'called|murmured|demanded|retorted|told')


def single_quoted(texts: list[str]) -> bool:
    """Whether the prose quotes speech with single quotation marks, which
    `prose_analysis` doesn't read as dialogue: then dialogue can't be
    measured or sampled, and callers say so rather than report none."""
    joined = ''.join(texts)
    return joined.count('\u2018') >= 10 and joined.count('\u2018') > joined.count('\u201c')


@dataclass(frozen=True)
class CharacterEvidence:
    """One character as code measured them. `lines` are quoted speech
    with a speech tag naming them beside it ("said Scrooge"). A reply parsed
    against this evidence renders only with it (by id)."""
    id: str
    name: str
    role: str
    pov_scenes: int
    on_stage: int
    first: str
    last: str
    moments: list[str]
    facts: list[str]
    lines: list[str]


def _who(scene: dict[str, str], alias: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """A scene's POV id, the ids on stage, and the names that resolve to no
    character. The ids on stage come from `on_stage`, or from `characters`
    when `on_stage` is empty, plus the POV character."""
    unresolved = []
    pov = alias.get(scene.get('pov', '').strip().lower(), '')
    if scene.get('pov', '').strip() and not pov:
        unresolved.append(scene['pov'].strip())
    present = []
    for name in _names(scene.get('on_stage', '') or scene.get('characters', '')):
        cid = alias.get(name.lower())
        if cid:
            present.append(cid)
        else:
            unresolved.append(name)
    if pov and pov not in present:
        present.append(pov)
    return pov, present, unresolved


def _speech(text: str, names: list[str]) -> list[str]:
    """Quoted speech in `text` with a speech tag naming one of `names`
    against it: "said NAME" or "NAME said" right after the quote, or right
    before it ending in a comma or colon, within _ATTRIBUTION_CHARS and never
    reaching past the neighbouring quote; never a possessive ("Scrooge's
    nephew" tags the nephew). Lines under four words or over 300 characters
    are left out."""
    from .prose_analysis import dialogue_spans
    if not names:
        return []
    name = r'(?:' + '|'.join(re.escape(n) for n in names) + r')(?![\'\u2019]s)\b'
    tag = rf'(?:(?:{_SPEECH_VERBS})\s+(?:the\s+)?{name}|{name}\s+(?:{_SPEECH_VERBS})\b)'
    # The tag sits against the quote: right after it ('"Bah!" said
    # Scrooge'), or right before it, ending in a comma or colon ('Scrooge
    # said, "Bah!"'). A tag ending the sentence before belongs to the quote
    # before that
    tag_after = re.compile(rf'\s*(?:[\u2014\u2013-]\s*)?{tag}')
    tag_before = re.compile(rf'\b{tag}\s*[,:]\s*$')
    spans = dialogue_spans(text)
    out = []
    for i, (start, end, inner) in enumerate(spans):
        line = ' '.join(inner.split())
        if len(line.split()) < 4 or len(line) > 300:
            continue
        before = text[max(start - _ATTRIBUTION_CHARS, spans[i - 1][1] if i else 0):start]
        after = text[end:min(end + _ATTRIBUTION_CHARS,
                             spans[i + 1][0] if i + 1 < len(spans) else len(text))]
        if tag_after.match(after) or tag_before.search(before):
            out.append(line)
    return out


def _speaker_names(characters: list[dict[str, str]]) -> dict[str, list[str]]:
    """Per character, the names a speech tag may use: the name, each alias,
    and each capitalized word of four or more letters in the name that
    belongs to them alone. A word in one name only is theirs; a word in
    several is the one character's whose name ends with it ("Scrooge" is
    Ebenezer Scrooge's, not "Boy Scrooge Sends for Turkey"'s), and no one's
    when several names end with it ("Cratchit": Bob and Mrs Cratchit).
    Shorter words like "Bob" count only through `aliases`."""
    words: dict[str, set[str]] = {}
    ends: dict[str, set[str]] = {}
    for c in characters:
        found = re.findall(r"[A-Z][\w']{3,}", c.get('name', ''))
        for w in found:
            words.setdefault(w, set()).add(c['id'])
        if found and c.get('name', '').rstrip().endswith(found[-1]):
            ends.setdefault(found[-1], set()).add(c['id'])
    out = {}
    for c in characters:
        names = [c.get('name', '').strip()] + _names(c.get('aliases', ''))
        names += [w for w, ids in words.items() if w in c.get('name', '')
                  and (ids == {c['id']} or ends.get(w) == {c['id']})]
        out[c['id']] = list(dict.fromkeys(n for n in names if n))
    return out


def character_evidence(project_dir: str, scenes: list[dict[str, str]],
                       ) -> tuple[list[CharacterEvidence], list[str], list[str]]:
    """The characters 5d describes, POV characters first (most scenes
    first), then by role (`_ROLE_RANK`), scenes on stage and scenes
    mentioned, with what code can say about each; the notes for the report
    (the registry, prose or ledger missing, names that resolve to no
    character, those past the caps); and the sources that had something
    (for the provenance header).

    Raises DescribeFailed naming the file when characters.csv or a scene
    file can't be read."""
    rows, alias, notes = _registry(project_dir, 'characters.csv')
    by_id = {r['id']: r for r in rows}
    texts, prose_notes = _prose(project_dir, scenes)
    facts, fact_notes = _fixed_facts(project_dir, ('trait', 'relationship', 'physical'))
    notes += prose_notes + fact_notes
    sources = ['scenes'] + (['characters'] if rows else []) + \
        (['commitments'] if not fact_notes else []) + (['prose'] if texts else [])
    if texts and single_quoted(list(texts.values())):
        notes.append('the prose quotes speech with single quotation marks, which are not read '
                     'as dialogue, so no lines are sampled')
    pov_count: dict[str, int] = {}
    seen: dict[str, list[dict[str, str]]] = {}
    mentioned: dict[str, int] = {}
    unresolved: set[str] = set()
    for s in scenes:
        pov, present, missing = _who(s, alias)
        unresolved.update(missing)
        if pov:
            pov_count[pov] = pov_count.get(pov, 0) + 1
        for cid in present:
            seen.setdefault(cid, []).append(s)
        for name in _names(s.get('characters', '')):
            cid = alias.get(name.lower())
            if cid:
                mentioned[cid] = mentioned.get(cid, 0) + 1
    if unresolved:
        notes.append(f'{len(unresolved)} name(s) in the scene CSVs match no character in '
                     f'characters.csv: {_first(sorted(unresolved))}')

    def rank(cid: str) -> tuple:
        role = by_id.get(cid, {}).get('role', '').strip().lower()
        return (-pov_count.get(cid, 0), _ROLE_RANK.get(role, 2), -len(seen[cid]),
                -mentioned.get(cid, 0), cid)
    order = sorted(seen, key=rank)
    if len(order) > MAX_CHARACTERS:
        notes.append(f'{len(order) - MAX_CHARACTERS} character(s) ranked lowest (by POV scenes, '
                     f'role, then scenes on stage) are left out of the character bible (it '
                     f'describes {MAX_CHARACTERS})')
    speakers = _speaker_names(rows)
    out, capped = [], []
    for cid in order[:MAX_CHARACTERS]:
        appears = seen[cid]
        lines: list[str] = []
        for s in appears:
            lines += _speech(texts.get(s['id'], ''), speakers.get(cid, []))[:2]
        own = [f for f in facts if f.get('subject', '').strip() == cid]
        if len(own) > MAX_FACTS_PER_CHARACTER:
            capped.append(cid)
        out.append(CharacterEvidence(
            id=cid, name=by_id[cid].get('name', '') or cid, role=by_id[cid].get('role', ''),
            pov_scenes=pov_count.get(cid, 0), on_stage=len(appears),
            first=appears[0]['id'], last=appears[-1]['id'],
            moments=[f'{s.get("seq", "")} {s["id"]}: '
                     f'{s.get("summary", "").strip() or s.get("function", "").strip()}'
                     for s in _sample(appears, MAX_MOMENTS)],
            facts=[_fact_line(f) for f in own[:MAX_FACTS_PER_CHARACTER]],
            lines=_sample(lines, MAX_LINES)))
    if capped:
        notes.append(f'{len(capped)} character(s) have more than {MAX_FACTS_PER_CHARACTER} '
                     f'established facts; the first {MAX_FACTS_PER_CHARACTER} are used: '
                     f'{_first(capped)}')
    return out, notes, sources


CHARACTERS_SCHEMA = _object({
    'characters': {'type': 'array', 'items': _object({
        'id': _STRING, 'tier': _TIER_ENUM, 'role': _STRING, 'physical': _STRING,
        'want': _STRING, 'need': _STRING, 'wound': _STRING, 'lie': _STRING,
        'flaw_as_strength': _STRING, 'voice': _STRING, 'relational': _STRING,
        'arc_start': _STRING, 'arc_turns': _STRING, 'arc_end': _STRING,
        'left_open': _STRINGS})},
    'relationships': {'type': 'array', 'items': _object(
        {'a': _STRING, 'b': _STRING, 'nature': _STRING})},
    'pov': {'type': 'array', 'items': _object({'id': _STRING, 'gives': _STRING})},
    'pov_excluded': _STRING,
})


def build_characters_prompt(profile: dict, chars: list[CharacterEvidence],
                            problems: list[str] | None = None) -> str:
    """Step 5d's prompt: describe each character from what code gathered."""
    blocks = []
    for c in chars:
        blocks.append('\n'.join([
            f'### {c.id} ({c.name}){" - " + c.role if c.role else ""}',
            f'POV in {c.pov_scenes} scene(s); on stage in {c.on_stage}, from {c.first} '
            f'to {c.last}.',
            'Scenes they appear in (a sample):', *[f'- {m}' for m in c.moments],
            'Established facts (from the ledger, with the text\'s words):',
            *([f'- {f}' for f in c.facts] or ['- (none recorded)']),
            'Lines spoken near their name (likely theirs):',
            *([f'- "{line}"' for line in c.lines] or ['- (none found)'])]))
    pov_ids = ', '.join(c.id for c in chars if c.pov_scenes) or '(none)'
    return f"""{_DESCRIBE_STANCE}

## The book

{_profile_lines(profile, ('narrative_mode', 'central_conflict', 'protagonist_arc',
                          'major_threads', 'tone'))}

## Its characters, as the scenes show them

{chr(10).join(blocks)}
{_retry_block(problems)}
## What to produce

Every field is plain prose on one line. Leave a field empty when the text
doesn't show it; never invent a backstory the book doesn't give.

1. **characters**: one entry for each character above, by id exactly. tier:
   primary for the characters the story is about (every POV character is
   primary), secondary for the rest. role (their function in the story),
   physical, want, need, wound, lie, flaw_as_strength (for secondary
   characters these may be empty), voice (how they speak, from their lines),
   relational (their key relationships and how they behave in each),
   arc_start, arc_turns, arc_end (where they start, what turns them, where
   they end; the same state at both ends is an answer), and left_open (0-3
   things the text leaves open about them).
2. **relationships**: the relationships that matter, as a and b (character
   ids) and nature (one sentence).
3. **pov**: for each POV character ({pov_ids}): id, and gives (what their
   point of view gives the reader that no other could).
4. **pov_excluded**: one sentence on who never gets a point of view and what
   that does (empty if not notable).
"""


def _retry_block(problems: list[str] | None) -> str:
    if not problems:
        return ''
    return ('\n## Your previous answer could not be used\n\n'
            + '\n'.join(f'- {p}' for p in problems) + '\n\nAnswer again with these fixed.\n')


def _ids_once(items: list[dict], key: str, known, label: str, problems: list[str]) -> list[dict]:
    """The items whose `key` is a known id, each once; problems for the rest."""
    out, seen = [], set()
    for item in items:
        iid = item[key]
        if iid not in known:
            problems.append(f'{label} names {iid!r}, which is not one of the ids given')
        elif iid in seen:
            problems.append(f'{label} names {iid!r} twice')
        else:
            seen.add(iid)
            out.append(item)
    return out


def parse_characters(response: str, chars: list[CharacterEvidence]) -> dict:
    """Read and check step 5d's reply against the evidence it was asked
    with. Returns it cleaned (`_clean_reply`), `characters` in evidence
    order. Raises ReplyProblems for: an id unknown, repeated or left out, a
    POV character not primary, an empty role for any character, or an empty
    voice, arc start or arc end for a primary one; a `left_open` item that
    reads as an instruction; a relationship naming an unknown id, one
    character twice, or with no nature; and a POV entry missing, unknown,
    repeated or with an empty `gives`."""
    from .extract import _json_answer
    data = _clean_reply(_json_answer(response, CHARACTERS_SCHEMA))
    ids = [c.id for c in chars]
    pov = {c.id for c in chars if c.pov_scenes}
    problems: list[str] = []
    described = _ids_once(data['characters'], 'id', ids, 'characters', problems)
    left = [i for i in ids if i not in {c['id'] for c in described}]
    if left:
        problems.append('characters leaves out: ' + ', '.join(left[:5])
                        + ('…' if len(left) > 5 else ''))
    for c in described:
        if c['id'] in pov and c['tier'] != 'primary':
            problems.append(f'{c["id"]} has a point of view, so is primary')
        need = ('role',) + (('voice', 'arc_start', 'arc_end') if c['tier'] == 'primary' else ())
        problems += [f'{c["id"]}.{k} is empty' for k in need if not c[k]]
        problems += _imperatives(c['left_open'], f'{c["id"]}.left_open')
    for r in data['relationships']:
        if r['a'] not in ids or r['b'] not in ids or r['a'] == r['b']:
            problems.append(f'relationship {r["a"]!r}-{r["b"]!r} must name two different '
                            f'character ids from the list')
        elif not r['nature']:
            problems.append(f'relationship {r["a"]}-{r["b"]} has no nature')
    given = _ids_once(data['pov'], 'id', pov, 'pov', problems)
    problems += [f'pov {p["id"]}.gives is empty' for p in given if not p['gives']]
    unexplained = sorted(pov - {p['id'] for p in given})
    if unexplained:
        problems.append('pov leaves out POV character(s): ' + ', '.join(unexplained))
    if problems:
        raise ReplyProblems(problems)
    rank = {cid: i for i, cid in enumerate(ids)}
    data['characters'] = sorted(described, key=lambda c: rank[c['id']])
    data['pov'] = sorted(given, key=lambda p: rank[p['id']])
    return data


def render_character_bible(reply: dict, chars: list[CharacterEvidence], title: str,
                           header: str) -> str:
    """`character-bible.md` in the template's sections, described:
    "Expansion Opportunities" is "What the text leaves open". Appearances,
    established facts and sample lines are the evidence's, not the model's."""
    ev = {c.id: c for c in chars}
    name = {c.id: c.name for c in chars}

    def appears(c: CharacterEvidence) -> str:
        pov = f'POV in {c.pov_scenes} scene(s); ' if c.pov_scenes else ''
        return f'{pov}on stage in {c.on_stage}, from `{c.first}` to `{c.last}`'

    out = [header, f'# {title or "Untitled"} -- Character Bible', '', '---', '',
           '## Primary Characters', '']
    for tier in CHARACTER_TIERS:
        if tier == 'secondary':
            out += ['---', '', '## Secondary Characters', '']
        for c in (x for x in reply['characters'] if x['tier'] == tier):
            e = ev[c['id']]
            out += ['---', '', f'### {e.name}', '', f'**Role:** {c["role"]}', '',
                    f'**Appears:** {appears(e)}', '']
            if tier == 'primary':
                out += ['**Physical:**', f'- {_shown(c["physical"])}', '',
                        '**Psychological:**',
                        f'- **Want:** {_shown(c["want"])}', f'- **Need:** {_shown(c["need"])}',
                        f'- **Wound:** {_shown(c["wound"])}', f'- **Lie:** {_shown(c["lie"])}',
                        f'- **Flaw-as-Strength:** {_shown(c["flaw_as_strength"])}', '',
                        '**Voice Fingerprint:**', f'- {c["voice"]}', '']
                if e.lines:
                    out += ['**Lines tagged with their name:**',
                            *[f'- "{line}"' for line in e.lines[:3]], '']
                out += ['**Relational:**', f'- {_shown(c["relational"])}', '']
            else:
                out += ['**Profile:**', f'- {_shown(c["physical"])}',
                        f'- Voice: {_shown(c["voice"])}',
                        f'- Relationships: {_shown(c["relational"])}', '']
            if e.facts:
                out += ['**Established facts:**', *[f'- {f}' for f in e.facts], '']
            if tier == 'primary':
                out += ['**Arc:**', f'1. {c["arc_start"]}', f'2. {_shown(c["arc_turns"])}',
                        f'3. {c["arc_end"]}', '']
            out += ['**What the text leaves open:**', _bullets(c['left_open']), '']
    out += ['---', '', '## Relationship Map', '']
    out += [f'- **{name[r["a"]]}** and **{name[r["b"]]}**: {r["nature"]}'
            for r in reply['relationships']] or ['- (none described)']
    out += ['', '---', '', '## Character Voice Notes', '']
    out += [f'**{name[c["id"]]}:** {c["voice"]}' + '\n'
            for c in reply['characters'] if c['tier'] == 'primary']
    out += ['---', '', '## POV Decisions', '']
    out += [f'- **{name[p["id"]]}:** {ev[p["id"]].pov_scenes} scene(s). {p["gives"]}'
            for p in reply['pov']] or ['- No character has a point of view recorded in scenes.csv.']
    if reply['pov_excluded']:
        out += [f'- **No POV:** {reply["pov_excluded"]}']
    return '\n'.join(out) + '\n'


# --- 5e: world ----------------------------------------------------------------

MAX_LOCATIONS = 15
MAX_WORLD_FACTS = 60

#: The world bible's described sections: reply key → (heading, {field →
#: subheading}). The schema and the prompt are derived from it, so a field
#: asked for is always rendered.
_SECTION_TITLES = {
    'society': ('Society & Culture', {'class_structure': 'Class & Social Structure',
                                      'norms': 'Cultural Norms',
                                      'knowledge': 'Education & Knowledge',
                                      'family': 'Gender, Family, & Relationships',
                                      'other': 'Other Cultural Notes'}),
    'power': ('Politics & Power', {'structure': 'Power Structure',
                                   'laws': 'Laws & Governance',
                                   'tensions': 'Political Tensions'}),
    'economy': ('Economy', {'drivers': 'What Drives the Economy',
                            'wealth': 'Wealth & Inequality', 'details': 'Key Economic Details'}),
    'technology': ('Technology / Magic', {'level': 'Technology Level',
                                          'extraordinary': 'Magic or Extraordinary Abilities'}),
    'history': ('History', {'deep': 'Deep History', 'recent': 'Recent History',
                            'inciting': 'The Inciting Backstory'}),
    'daily_life': ('Daily Life', {'typical_day': 'What a Typical Day Looks Like',
                                  'material': 'Food, Drink, & Material Culture'}),
    'senses': ('Sensory Palette', {'sight': 'Sight', 'sound': 'Sound', 'smell': 'Smell',
                                   'touch': 'Touch', 'taste': 'Taste'}),
}
_WORLD_SECTIONS: dict[str, tuple[str, ...]] = {
    section: tuple(fields) for section, (_, fields) in _SECTION_TITLES.items()}
_SYSTEM_FIELDS = ('name', 'what_it_is', 'who', 'how', 'costs', 'feels', 'social')

WORLD_SCHEMA = _object({
    'overview': _STRING,
    'macro': _STRING,
    'locations': {'type': 'array', 'items': _object(
        {k: _STRING for k in ('id', 'description', 'function', 'occupants')})},
    **{section: _object({k: _STRING for k in keys}) for section, keys in _WORLD_SECTIONS.items()},
    'institutions': {'type': 'array', 'items': _object(
        {k: _STRING for k in ('name', 'function', 'notes')})},
    'open_questions': _STRINGS,
    'system': _object({'present': {'type': 'string', 'enum': ['yes', 'no']},
                       **{k: _STRING for k in _SYSTEM_FIELDS}, 'rules': _STRINGS}),
})


@dataclass(frozen=True)
class LocationEvidence:
    """A place as code counted it: how many scenes are set there, and the first."""
    id: str
    name: str
    scenes: int
    first: str


@dataclass(frozen=True)
class WorldEvidence:
    """What 5e is given. A reply parsed against this evidence renders only
    with it (by location id)."""
    title: str
    locations: list[LocationEvidence]    # most scenes first
    facts: list[str]
    sources: list[str]

    @property
    def required(self) -> list[str]:
        """The places 5e must describe: those set in two or more scenes, or
        every place when none is."""
        return [loc.id for loc in self.locations if loc.scenes >= 2] \
            or [loc.id for loc in self.locations]


def world_evidence(project_dir: str, scenes: list[dict[str, str]], title: str,
                   ) -> tuple[WorldEvidence, list[str]]:
    """The places and world facts 5e describes from, and the notes for the
    report. Raises DescribeFailed naming locations.csv when it can't be read."""
    rows, alias, notes = _registry(project_dir, 'locations.csv')
    by_id = {r['id']: r for r in rows}
    counts: dict[str, list[str]] = {}
    unresolved = set()
    for s in scenes:
        # A scene set in several places lists them `;`-separated
        for loc in _names(s.get('location', '')):
            lid = alias.get(loc.lower())
            if lid:
                counts.setdefault(lid, []).append(s['id'])
            else:
                unresolved.add(loc)
    facts, fact_notes = _fixed_facts(project_dir, ('world',))
    notes += fact_notes
    if len(facts) > MAX_WORLD_FACTS:
        notes.append(f'{len(facts) - MAX_WORLD_FACTS} world fact(s) past the first '
                     f'{MAX_WORLD_FACTS} are left out of 5e\'s evidence')
    if unresolved:
        notes.append(f'{len(unresolved)} scene location(s) match no entry in locations.csv: '
                     f'{_first(sorted(unresolved))}')
    order = sorted(counts, key=lambda lid: -len(counts[lid]))[:MAX_LOCATIONS]
    if len(counts) > MAX_LOCATIONS:
        notes.append(f'{len(counts) - MAX_LOCATIONS} location(s) used in the fewest scenes '
                     f'are left out of the world bible')
    locations = [LocationEvidence(lid, by_id[lid].get('name', '') or lid, len(counts[lid]),
                                  counts[lid][0]) for lid in order]
    sources = ['scenes'] + (['locations'] if locations else []) + \
        (['commitments'] if not fact_notes else [])
    return WorldEvidence(title=title, locations=locations,
                         facts=[_fact_line(f) for f in facts[:MAX_WORLD_FACTS]],
                         sources=sources), notes


def build_world_prompt(profile: dict, scenes: list[dict[str, str]], ev: WorldEvidence,
                       problems: list[str] | None = None) -> str:
    locations = '\n'.join(f'- {loc.id} ({loc.name}): {loc.scenes} scene(s), first '
                          f'{loc.first}' for loc in ev.locations) or '(none recorded)'
    facts = '\n'.join(f'- {f}' for f in ev.facts) or '(none recorded)'
    sections = '\n'.join(f'   - {s}: {", ".join(keys)}' for s, keys in _WORLD_SECTIONS.items())
    required = f' ({", ".join(ev.required)} at least)' if ev.required else ''
    return f"""{_DESCRIBE_STANCE}

## The book

{_profile_lines(profile, ('timeline', 'key_locations', 'central_conflict', 'tone'))}

## Its places (with how many scenes are set in each)

{locations}

## Established facts about its world (from the ledger, with the text's words)

{facts}

## Its scenes, in reading order

{_scene_lines(scenes)}
{_retry_block(problems)}
## What to produce

Every field is plain prose on one line. Leave a field empty when the book
doesn't show it: a world bible for a book set in a real city says what the
book shows of that city, not what an encyclopedia would.

1. **overview**: one paragraph on the world and what makes it distinct.
2. **macro**: the landscape, climate and wider setting, as the book shows them.
3. **locations**: for each place above, by id exactly{required}: description
   (how the text renders it), function (what happens there, what it
   carries), occupants (who is there and why).
4. The sections below, each field one or two sentences or empty:
{sections}
5. **institutions**: the institutions the book shows (name, function, notes); may be empty.
6. **open_questions**: 0-5 things about the world the text leaves open.
7. **system**: whether the book has a formal system with rules (magic,
   technology, psychic powers). present: "yes" or "no". If yes, name,
   what_it_is, who (who can use it), how (how it works), rules (the rules
   the text keeps), costs, feels (what it feels like on the page) and social
   (how it shapes society). If no, what_it_is is one sentence on why the
   book has none (for example, the supernatural acts by no stated rules),
   and the rest are empty.
"""


def parse_world(response: str, ev: WorldEvidence) -> dict:
    """Read and check step 5e's reply against the evidence it was asked
    with. Returns it cleaned, `locations` in evidence order. Raises
    ReplyProblems for: an empty overview, a location id unknown, repeated or
    (when required) left out, a location with no description, an open
    question that reads as an instruction, and a system marked present with
    no name, description or rules, or absent with no reason."""
    from .extract import _json_answer
    data = _clean_reply(_json_answer(response, WORLD_SCHEMA))
    problems: list[str] = []
    if not data['overview']:
        problems.append('overview is empty')
    ids = [loc.id for loc in ev.locations]
    described = _ids_once(data['locations'], 'id', ids, 'locations', problems)
    problems += _imperatives(data['open_questions'], 'open_questions')
    left = [lid for lid in ev.required if lid not in {loc['id'] for loc in described}]
    if left:
        problems.append('locations leaves out: ' + ', '.join(left[:5]))
    problems += [f'location {loc["id"]}.description is empty'
                 for loc in described if not loc['description']]
    system = data['system']
    if system['present'] == 'yes':
        problems += [f'system.{k} is empty' for k in ('name', 'what_it_is') if not system[k]]
        if not system['rules']:
            problems.append('system.rules has no items (a formal system keeps rules)')
    elif not system['what_it_is']:
        problems.append('system.what_it_is is empty (say why the book has no formal system)')
    if problems:
        raise ReplyProblems(problems)
    rank = {lid: i for i, lid in enumerate(ids)}
    data['locations'] = sorted(described, key=lambda loc: rank[loc['id']])
    return data


def render_world_bible(reply: dict, ev: WorldEvidence, header: str) -> str:
    """`world-bible.md` in the template's sections, described: "Open
    Questions" is "What the text leaves open". Location scene counts are
    code's."""
    name = {loc.id: loc for loc in ev.locations}
    out = [header, f'# {ev.title or "Untitled"} -- World Bible', '', '## Overview', '',
           reply['overview'], '', '---', '', '## Geography & Setting', '', '### The Macro',
           _shown(reply['macro']), '', '### Key Locations', '']
    for loc in reply['locations']:
        e = name[loc['id']]
        out += [f'**{e.name}** ({e.scenes} scene(s))',
                f'- {loc["description"]}', f'- Function: {_shown(loc["function"])}',
                f'- Occupants: {_shown(loc["occupants"])}', '']
    if ev.facts:
        out += ['### Established Facts', *[f'- {f}' for f in ev.facts], '']
    for section, (heading, fields) in _SECTION_TITLES.items():
        out += ['---', '', f'## {heading}', '']
        for key, sub in fields.items():
            out += [f'### {sub}', _shown(reply[section][key]), '']
        if section == 'power' and reply['institutions']:
            out += ['### Institutions', '']
            out += [f'**{i["name"]}**\n- {_shown(i["function"])}\n- {_shown(i["notes"])}\n'
                    for i in reply['institutions']]
        if section == 'technology':
            system = reply['system']
            out += ['### Formal System',
                    (f'{system["name"]}: see `systems-bible.md`.' if system['present'] == 'yes'
                     else f'None. {system["what_it_is"]}'), '']
    out += ['---', '', '## What the text leaves open', '', _bullets(reply['open_questions'])]
    return '\n'.join(out) + '\n'


def render_systems_bible(reply: dict, title: str, header: str) -> str:
    """`systems-bible.md`: the system the book keeps, or a stub saying it
    has none and why, so a reader sees "checked, not applicable"."""
    s = reply['system']
    out = [header, f'# {title or "Untitled"} -- Systems Bible', '']
    if s['present'] != 'yes':
        return '\n'.join(out + ['No formal system: ' + s['what_it_is'], '']) + '\n'
    out += ['---', '', f'## System 1: {s["name"]}', '', '### What It Is', s['what_it_is'], '',
            '### Who Can Use It', _shown(s['who']), '', '### How It Works', _shown(s['how']), '',
            '### Rules', '', *[f'{i}. {r}' for i, r in enumerate(s['rules'], 1)], '',
            '### Costs & Limits', _shown(s['costs']), '', '### How It Feels', _shown(s['feels']),
            '', '### Social Dimension', _shown(s['social']), '']
    return '\n'.join(out) + '\n'


# --- 5f: voice --------------------------------------------------------------

#: Words of prose per sample, and how many dialogue-heavy scenes join the
#: opening, middle and close: about 30k tokens in all.
SAMPLE_WORDS = 3_000
DIALOGUE_SAMPLES = 3
#: A contraction: n't, 're, 've, 'll, 'd, 'm (not the possessive 's).
_CONTRACTION = re.compile(r"\b\w+(?:n['’]t|['’](?:re|ve|ll|d|m))\b", re.IGNORECASE)


#: The fewest words a measure is taken over; below it a percentage or a
#: rate per 1,000 words says more about the sample than the voice.
MIN_MEASURE_WORDS = 1_000


@dataclass(frozen=True)
class VoiceEvidence:
    """What 5f is given. A reply parsed against this evidence renders only
    with it (by character id)."""
    title: str
    samples: list[tuple[str, str, str]]   # (label, scene id, text)
    measures: list[tuple[str, str]]       # (what, value), measured by code
    pov: list[str]                        # POV character ids, most scenes first
    names: dict[str, str]                 # every characters.csv id → its name
    sources: list[str]


def _measure(text: str, quoted_singly: bool) -> dict[str, str]:
    """Code's measures of `text`. Dialogue share isn't stated for prose that
    quotes speech with single quotation marks (it would read 0%), and
    sentence length is left out, and said, when there are too few sentences."""
    from .exemplars import compute_rhythm_signature
    from .prose_analysis import extract_dialogue
    words = len(text.split())
    sig = compute_rhythm_signature(text)
    dialogue, _ = extract_dialogue(text)
    out = {'dialogue share': (
        'not measured: speech is in single quotation marks, which are not read as dialogue'
        if quoted_singly else
        f'{round(100 * len(dialogue.split()) / words)}% of words are inside quotation marks'),
        'contractions': f'{round(1000 * len(_CONTRACTION.findall(text)) / words, 1)} '
                        f'per 1,000 words'}
    if sig:
        b = sig['buckets']
        out['sentence length'] = (
            f'mean {sig["mean_sentence_words"]} words (sd {sig["stddev_sentence_words"]}, '
            f'range {sig["min_sentence_words"]}-{sig["max_sentence_words"]}); {b["short"]}% '
            f'under 8, {b["long"] + b["very_long"]}% over 25')
    else:
        out['sentence length'] = 'not measured: too few sentences'
    return out


def voice_evidence(project_dir: str, scenes: list[dict[str, str]], title: str,
                   ) -> tuple[VoiceEvidence | None, list[str]]:
    """The prose 5f reads and the measures code takes of it, each labelled
    with what it covers; None when no scene has prose (a voice can't be
    described from summaries), with the notes saying why.

    Raises DescribeFailed naming the file when characters.csv or a scene
    file can't be read."""
    from .prose_analysis import extract_dialogue
    texts, notes = _prose(project_dir, scenes)
    if not texts:
        return None, notes
    ordered = [s['id'] for s in scenes if s['id'] in texts]
    quoted_singly = single_quoted(list(texts.values()))

    def cut(text: str) -> str:
        words = text.split()
        return text if len(words) <= SAMPLE_WORDS else ' '.join(words[:SAMPLE_WORDS]) + ' […]'
    picks: list[tuple[str, str]] = []
    for label, sid in (('opening', ordered[0]), ('middle', ordered[len(ordered) // 2]),
                       ('close', ordered[-1])):
        if sid not in {p for _, p in picks}:     # a short book has fewer than three
            picks.append((label, sid))
    if not quoted_singly:
        share = {sid: len(extract_dialogue(texts[sid])[0].split()) / len(texts[sid].split())
                 for sid in ordered if len(texts[sid].split()) >= 300}
        for sid in sorted(share, key=lambda k: -share[k]):
            if len([p for p in picks if p[0] == 'most dialogue']) >= DIALOGUE_SAMPLES:
                break
            if sid not in {p for _, p in picks}:
                picks.append(('most dialogue', sid))
    else:
        notes.append('the prose quotes speech with single quotation marks, which are not read '
                     'as dialogue, so dialogue is neither measured nor used to pick samples')

    def measured(label: str, ids: list[str]) -> list[tuple[str, str]]:
        text = '\n\n'.join(texts[sid] for sid in ids)
        words = len(text.split())
        if words < MIN_MEASURE_WORDS:
            notes.append(f'{label} has {words:,} words of prose, under {MIN_MEASURE_WORDS:,}, '
                         f'so it is not measured')
            return []
        what = f'{label} ({len(ids)} of {len(scenes)} scenes, {words:,} words)'
        return [(f'{what}: {k}', v) for k, v in _measure(text, quoted_singly).items()]
    measures = measured('the book', ordered)
    rows, alias, registry_notes = _registry(project_dir, 'characters.csv')
    notes += registry_notes
    pov_scenes: dict[str, list[str]] = {}
    unresolved = set()
    for s in scenes:
        named = s.get('pov', '').strip()
        pid = alias.get(named.lower())
        if named and not pid:
            unresolved.add(named)
        elif pid and s['id'] in texts:
            pov_scenes.setdefault(pid, []).append(s['id'])
    if unresolved:
        notes.append(f'{len(unresolved)} POV name(s) match no character in characters.csv, so '
                     f'their voices are not described: {_first(sorted(unresolved))}')
    pov = sorted(pov_scenes, key=lambda p: -len(pov_scenes[p]))
    for pid in pov:
        measures += measured(f"{pid}'s scenes", pov_scenes[pid])
    return VoiceEvidence(title=title, samples=[(label, sid, cut(texts[sid]))
                                               for label, sid in picks],
                         measures=measures, pov=pov,
                         names={r['id']: r.get('name', '') or r['id'] for r in rows},
                         sources=['prose'] + (['characters'] if rows else [])), notes


#: The POV voice fields, with the guide's label for each; the schema and
#: the renderer both read this, so a field asked for is always rendered.
_POV_VOICE_LABELS = {'interiority': 'Interiority style', 'sentence_patterns': 'Sentence patterns',
                     'metaphor_domain': 'Metaphor domain', 'notices': 'What they notice',
                     'emotional_register': 'Emotional register', 'speech': 'Speech patterns'}
_POV_VOICE_FIELDS = tuple(_POV_VOICE_LABELS)
#: The fewest items the voice guide's lists may have (the prompt asks for
#: more); an empty list would render as if the book had none.
_VOICE_LIST_MINIMUMS = {'lineage': 1, 'habits': 1, 'never_does': 1, 'pacing': 1}

VOICE_SCHEMA = _object({
    'lineage': {'type': 'array', 'items': _object({'influence': _STRING, 'what': _STRING})},
    'blend': _STRING,
    'pov_voices': {'type': 'array', 'items': _object(
        {'id': _STRING, **{k: _STRING for k in _POV_VOICE_FIELDS}})},
    'senses': _object({k: _STRING for k in ('sight', 'sound', 'smell', 'touch', 'taste')}),
    'dialogue': _object({k: _STRING for k in ('balance', 'use', 'subtext', 'declarations',
                                              'silence')}),
    'emotion': _object({'restraint': _STRING, 'key_moments': _STRINGS, 'physical': _STRING}),
    'habits': _STRINGS,
    'never_does': _STRINGS,
    'pacing': {'type': 'array', 'items': _object({'scene_type': _STRING,
                                                  'description': _STRING})},
    'recurring': {'type': 'array', 'items': _object(
        {k: _STRING for k in ('phrase', 'usage', 'significance')})},
    'register': _STRING,
    'profiles': {'type': 'array', 'items': _object({
        'id': _STRING, 'preferred_words': _STRINGS, 'metaphor_families': _STRINGS,
        'rhythm': _STRING, 'dialogue_style': _STRING})},
})


def build_voice_prompt(profile: dict, ev: VoiceEvidence,
                       problems: list[str] | None = None) -> str:
    samples = '\n\n'.join(f'### {label}: {sid}\n\n{text}' for label, sid, text in ev.samples)
    measures = '\n'.join(f'- {what}: {value}' for what, value in ev.measures)
    pov = ', '.join(ev.pov) or '(none recorded)'
    return f"""{_DESCRIBE_STANCE}

## The book

{_profile_lines(profile, ('narrative_mode', 'tone'))}

## Measured by code (use these numbers; don't estimate your own)

{measures}

## Samples of its prose

{samples}
{_retry_block(problems)}
## What to produce

Describe the voice as it is, from the samples: the book's habits, never
rules for a writer. Every field is plain prose on one line. Phrase every
list item as a statement about the book ("The narrator addresses the reader
directly"), never as an instruction ("Address the reader").

1. **lineage**: 2-4 writers, works or traditions the voice belongs with
   (influence, and what it shares with them), and **blend**: one sentence on
   what the voice sounds like.
2. **pov_voices**: for each POV character ({pov}), by id: interiority,
   sentence_patterns, metaphor_domain, notices (what registers first),
   emotional_register, speech.
3. **senses**: the dominant sight, sound, smell, touch and taste (empty if
   the book has none).
4. **dialogue**: balance (dialogue vs narration, using the measured share),
   use (how characters use language), subtext, declarations (how rare open
   emotional statements are), silence (how the unsaid is rendered).
5. **emotion**: restraint (where the book holds back and where it opens),
   key_moments (3-5 scenes that land hardest, by what happens), physical
   (how bodies carry emotion).
6. **habits**: 3-6 things the prose consistently does; **never_does**: 2-5
   things it consistently doesn't do.
7. **pacing**: 2-4 kinds of scene (scene_type) and how the prose moves in each.
8. **recurring**: 0-6 words or phrases the book returns to (phrase, usage,
   significance).
9. **register**: one sentence on the narration's register.
10. **profiles**: one per POV character, by id: preferred_words (5-12 words
    the text actually uses in their scenes, no semicolons), metaphor_families
    (2-4 domains their comparisons come from), rhythm (their sentence
    rhythm), dialogue_style.
"""


def parse_voice(response: str, ev: VoiceEvidence) -> dict:
    """Read and check step 5f's reply against the evidence it was asked
    with. Returns it cleaned. Raises ReplyProblems for: a POV voice missing,
    unknown or repeated, a profile unknown (not in characters.csv),
    repeated or missing for a POV character, an empty POV voice field, a
    list shorter than _VOICE_LIST_MINIMUMS or no key moment, a list item
    or pacing description that reads as an instruction (decision 2), a
    profile word with a `;` (it would split the CSV list), and an empty
    blend, register or dialogue balance."""
    from .extract import _json_answer
    data = _clean_reply(_json_answer(response, VOICE_SCHEMA))
    problems: list[str] = []
    problems += [f'{k} is empty' for k in ('blend', 'register') if not data[k]]
    if not data['dialogue']['balance']:
        problems.append('dialogue.balance is empty')
    problems += [f'{k} has {len(data[k])} item(s); at least {n}'
                 for k, n in _VOICE_LIST_MINIMUMS.items() if len(data[k]) < n]
    if not data['emotion']['key_moments']:
        problems.append('emotion.key_moments has no items')
    voices = _ids_once(data['pov_voices'], 'id', ev.pov, 'pov_voices', problems)
    for v in voices:
        problems += [f'pov_voices {v["id"]}.{k} is empty' for k in _POV_VOICE_FIELDS if not v[k]]
    profiles = _ids_once(data['profiles'], 'id', list(ev.names), 'profiles', problems)
    for label, got in (('pov_voices', voices), ('profiles', profiles)):
        left = [p for p in ev.pov if p not in {g['id'] for g in got}]
        if left:
            problems.append(f'{label} leaves out POV character(s): ' + ', '.join(left))
    for p in profiles:
        bad = [w for w in p['preferred_words'] + p['metaphor_families'] if ';' in w]
        if bad:
            problems.append(f'profile {p["id"]} has item(s) with a semicolon: '
                            + ', '.join(repr(b) for b in bad))
    for key in ('habits', 'never_does'):
        problems += _imperatives(data[key], key)
    problems += _imperatives(data['emotion']['key_moments'], 'emotion.key_moments')
    problems += _imperatives([p['description'] for p in data['pacing']], 'pacing')
    if problems:
        raise ReplyProblems(problems)
    data['pov_voices'], data['profiles'] = voices, profiles
    return data





def voice_profile_rows(reply: dict) -> list[dict[str, str]]:
    """`voice-profile.csv` in elaborate's shape: a `_project` row with the
    register, then one row per profile in the reply (every POV character,
    and any other character it profiled). `banned_words` stays empty: a
    word the book never uses isn't banned."""
    rows = [{'character': '_project', 'register': reply['register']}]
    rows += [{'character': p['id'], 'preferred_words': ';'.join(p['preferred_words']),
              'metaphor_families': ';'.join(p['metaphor_families']),
              'rhythm_preference': p['rhythm'], 'dialogue_style': p['dialogue_style']}
             for p in reply['profiles']]
    return rows


def render_voice_guide(reply: dict, ev: VoiceEvidence, header: str) -> str:
    """`voice-guide.md`, described. The template's prescriptive sections
    become descriptions ("Influence Blend" is "Lineage", "Style Rules" is
    "What the prose does" and "What the prose never does", "Pacing Rules"
    is "Pacing"), its "Prose Naturalness" rules for a drafter are left out,
    and a "Measured" section gives code's numbers."""
    out = [header, f'# {ev.title or "Untitled"} -- Voice Guide', '', '---', '', '## Lineage', '',
           '| Influence | What the voice shares with it |', '|---|---|']
    out += [f'| {_cell_md(x["influence"])} | {_cell_md(x["what"])} |' for x in reply['lineage']] \
        or ['| (none named) | |']
    out += ['', f'**The blend:** {reply["blend"]}', '', '---', '', '## Measured', '']
    out += [f'- **{what}:** {value}' for what, value in ev.measures] \
        or ['- Nothing was measured: too little prose (see the extraction report).']
    out += ['', '---', '', '## POV Voices', '']
    for v in reply['pov_voices']:
        out += [f'### {ev.names.get(v["id"], v["id"])}', '']
        out += [f'**{label}:** {v[k]}\n' for k, label in _POV_VOICE_LABELS.items()]
    out += ['---', '', '## Sensory Palette', '']
    for k in ('sight', 'sound', 'smell', 'touch', 'taste'):
        out += [f'### {k.title()}', _shown(reply['senses'][k]), '']
    d = reply['dialogue']
    out += ['---', '', '## Dialogue', '', f'**Balance:** {_shown(d["balance"])}', '',
            f'**How characters use language:** {_shown(d["use"])}', '',
            f'**Subtext:** {_shown(d["subtext"])}', '',
            f'**Emotional declarations:** {_shown(d["declarations"])}', '',
            f'**Silence and pauses:** {_shown(d["silence"])}', '', '---', '',
            '## Emotional Register', '', f'**Restraint and release:** '
            f'{_shown(reply["emotion"]["restraint"])}', '', '**Key emotional moments:**',
            _bullets(reply['emotion']['key_moments']), '',
            f'**Physical expression:** {_shown(reply["emotion"]["physical"])}', '', '---', '',
            '## What the prose does', '', _bullets(reply['habits']), '',
            '## What the prose never does', '', _bullets(reply['never_does']), '', '---', '',
            '## Pacing', '']
    out += [f'- **{p["scene_type"]}:** {p["description"]}' for p in reply['pacing']] \
        or ['- (none described)']
    out += ['', '---', '', '## Recurring Language', '',
            '| Word/Phrase | Usage | Significance |', '|---|---|---|']
    out += [f'| {_cell_md(r["phrase"])} | {_cell_md(r["usage"])} | {_cell_md(r["significance"])} |'
            for r in reply['recurring']] or ['| (none) | | |']
    return '\n'.join(out) + '\n'


def _book_title(project_dir: str) -> tuple[str, list[str]]:
    """`project.title`, or '' and a note when it is unset or the template's
    placeholder: a doc then says the book has no title rather than describe
    one."""
    from .common import read_yaml_field
    title = read_yaml_field('project.title', project_dir)
    if title in _TITLE_PLACEHOLDERS:
        return '', ['storyforge.yaml has no project.title, so the docs say so rather than '
                    'describe one']
    return title, []


# ============================================================================
# Running the steps
# ============================================================================

STRUCTURE_MAX_TOKENS = 12_000
THEMES_MAX_TOKENS = 12_000
PITCH_MAX_TOKENS = 16_000
CHARACTERS_MAX_TOKENS = 24_000
WORLD_MAX_TOKENS = 16_000
VOICE_MAX_TOKENS = 16_000

#: Every scene-CSV cell phase 5 wrote, with the value it wrote. A cell is
#: phase 5's to replace only while it still holds exactly that value; any
#: other filled cell is the author's (#444 review: an id-based guess could
#: not tell an author's hand-tag from the last run's).
CELLS_FILE = os.path.join('working', 'extraction-cells.csv')
_CELLS_COLUMNS = ['file', 'scene_id', 'column', 'value']

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


def _gate(run: Run, rels: list[str], step: str, also: str = '') -> bool:
    """Whether every file a step writes may be written; reports the ones
    that can't, and what else the step then doesn't do (`also`, if
    anything). A step writes all its files or none, so its outputs can't
    disagree (an architecture naming a spine the author kept)."""
    verdicts = [decide(run.project_dir, rel, run.force, run.provenance) for rel in rels]
    kept = [v for v in verdicts if not v.write]
    if kept:
        run.reports.extend(v.report() for v in kept)
        why = (f'it writes {", ".join(rels)} together, and {len(kept)} of them must be kept'
               if len(rels) > 1 else f'{rels[0]} must be kept')
        run.reports.append(f'{step} skipped: {why}'
                           + (f'; {also} were not filled either' if also else ''))
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


def _read_cells(run: Run) -> dict[tuple[str, str, str], str] | None:
    """CELLS_FILE as {(file, scene id, column): value}; {} when absent. None,
    with a WARNING, when it exists but can't be read: then no filled cell
    can be shown to be phase 5's, so only blank cells are written, and the
    record is not rewritten (it would lose every other cell)."""
    from .elaborate import _read_csv
    path = os.path.join(run.project_dir, CELLS_FILE)
    if not os.path.lexists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            header = f.readline().rstrip('\n').split('|')
        if header != _CELLS_COLUMNS:
            raise ValueError(f'its header is {"|".join(header)!r}')
        rows = _read_csv(path)
    except (OSError, ValueError) as e:
        log(f'WARNING: {CELLS_FILE} could not be read ({e}); only blank cells are filled')
        return None
    return {(r['file'], r['scene_id'], r['column']): r['value'] for r in rows}


def _save_cells(run: Run, cells: dict[tuple[str, str, str], str]) -> None:
    path = os.path.join(run.project_dir, CELLS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = [{'file': f, 'scene_id': sid, 'column': col, 'value': v}
            for (f, sid, col), v in sorted(cells.items())]
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(_csv_text(rows, _CELLS_COLUMNS))


def _set_cells(run: Run, filename: str, column: str, values: dict[str, str], *,
               replace_any: bool = False) -> tuple[int, dict[str, str]]:
    """Set `column` for each scene id in `values`, in the scene CSV that owns
    it, where the cell is blank or still holds what phase 5 last wrote there
    (CELLS_FILE); `replace_any` replaces whatever is there. A scene with no
    row in that file gets none (a row written here would have nothing else
    in it). Records what it wrote. Returns how many cells changed, and the
    cells kept because they were the author's (scene id: current value).
    """
    from .elaborate import _read_csv_as_map, update_scene
    rows = _read_csv_as_map(os.path.join(run.ref_dir, filename))
    cells = _read_cells(run)
    record = cells if cells is not None else {}
    changed, kept = 0, {}
    for sid, value in values.items():
        row = rows.get(sid)
        if row is None:
            continue
        key = (filename, sid, column)
        value = _cell(value)
        current = row.get(column, '').strip()
        ours = current and record.get(key) == current
        if current != value and not (replace_any or not current or ours):
            kept[sid] = current
            continue
        if current != value:
            update_scene(sid, run.ref_dir, {column: value})
            changed += 1
        if value:
            record[key] = value
        else:
            record.pop(key, None)
    if cells is not None:
        _save_cells(run, record)
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
    structure = _ask(run, 'structure',
                     lambda problems: build_structure_prompt(profile, scenes, problems),
                     lambda text: parse_structure(text, scenes),
                     STRUCTURE_SCHEMA, STRUCTURE_MAX_TOKENS)
    spine, arch = structure_rows(structure, scenes)
    if not _write_all(run, [(rels[0], _csv_text(spine, _SPINE_COLS)),
                            (rels[1], _csv_text(arch, _ARCHITECTURE_COLS))], '5a', '5a'):
        return 'partial'
    n, _ = _set_cells(run, 'scenes.csv', 'summary', structure['scene_summaries'])
    if n:
        log(f'  filled {n} scene summar{"y" if n == 1 else "ies"}')
    # An anchor marks itself; a scene this run didn't anchor has its mark
    # cleared if phase 5 put it there, or it would name a dropped anchor
    anchors = {r['id'] for r in arch}
    marks = {s['id']: (s['id'] if s['id'] in anchors else '') for s in scenes}
    _, kept = _set_cells(run, 'scenes.csv', 'architecture_scene', marks)
    dangling = [sid for sid, cur in kept.items() if cur not in anchors]
    if dangling:
        run.reports.append(f'{len(dangling)} scene(s) keep an architecture_scene that names no '
                           f'anchor in architecture.csv: ' + ', '.join(dangling[:5])
                           + ('…' if len(dangling) > 5 else ''))
    _fill_project_field(run, 'genre', structure['genre'])
    _fill_project_field(run, 'subgenre', structure['subgenre'])
    return 'written'


def run_themes(run: Run, profile: dict, scenes: list[dict[str, str]]) -> StepOutcome:
    """Step 5b: themes.csv, motif-taxonomy.csv, theme_threads, and each
    brief's motifs split into ids and descriptions.

    Once the taxonomy has rows, `validate` checks a brief's `motifs` against
    it, and a description ("fog pouring through every chink") matches no
    alias. So `motifs` becomes the ids the scene's mentions were grouped
    into, and every description, including those that named no recurring
    image, moves to `motif_details`, which the drafting prompt reads
    beside it. Nothing the brief said is dropped.
    """
    from .elaborate import _MOTIF_COLS, _THEMES_COLS
    rels = ['reference/themes.csv', 'reference/motif-taxonomy.csv']
    if not _gate(run, rels, '5b (themes and motifs)', 'theme_threads and brief motifs'):
        return 'skipped'
    mentions = motif_mentions(scenes)
    result = _ask(run, 'themes',
                  lambda problems: build_themes_prompt(profile, scenes, mentions, problems),
                  lambda text: parse_themes(text, scenes, mentions),
                  THEMES_SCHEMA, THEMES_MAX_TOKENS)
    motif_rows = [{**m, 'aliases': ';'.join(m['aliases'])} for m in result['motifs']]
    if not _write_all(run, [(rels[0], _csv_text(result['themes'], _THEMES_COLS)),
                            (rels[1], _csv_text(motif_rows, _MOTIF_COLS))], '5b', '5b'):
        return 'partial'
    _, kept = _set_cells(run, 'scene-intent.csv', 'theme_threads',
                         {sid: ';'.join(ids) for sid, ids in result['scene_themes'].items()})
    # A kept cell is the author's. Say whether it still resolves: one
    # naming a theme themes.csv lacks fails validate
    new_themes = {t['id'] for t in result['themes']}
    dangling = [sid for sid, cur in kept.items()
                if any(t.strip() not in new_themes for t in cur.split(';') if t.strip())]
    valid = [sid for sid in kept if sid not in dangling]
    for ids, what in ((valid, 'a theme_threads cell of their own, kept'),
                      (dangling, 'a theme_threads cell naming themes not in themes.csv, kept '
                                 'because phase 5 did not write it (retag or clear it by '
                                 'hand)')):
        if ids:
            run.reports.append(f'{len(ids)} scene(s) have {what}: '
                               + ', '.join(ids[:5]) + ('…' if len(ids) > 5 else ''))
    by_scene: dict[str, list[str]] = {}
    for n, (sid, _) in enumerate(mentions):
        by_scene.setdefault(sid, [])
        motif = result['mention_motif'].get(n)
        if motif and motif not in by_scene[sid]:
            by_scene[sid].append(motif)
    details: dict[str, list[str]] = {}
    for sid, text in mentions:
        details.setdefault(sid, []).append(text)
    # Descriptions first, since the ids replace the only copy of them. A
    # brief that already has motif_details was read from it (motif_mentions),
    # so this writes the same text back and its cell is unchanged
    _set_cells(run, 'scene-briefs.csv', 'motif_details',
               {sid: '; '.join(texts) for sid, texts in details.items()})
    n, _ = _set_cells(run, 'scene-briefs.csv', 'motifs',
                      {sid: ';'.join(ids) for sid, ids in by_scene.items()},
                      replace_any=True)
    if n:
        log(f'  briefs: {n} motifs cell(s) now name motif ids; the descriptions are in '
            f'motif_details')
    return 'written'


def run_pitch(run: Run, profile: dict, scenes: list[dict[str, str]]) -> StepOutcome:
    """Step 5c: story-summary.md and story-architecture.md, from one call.

    Reads the spine, themes and motifs 5a and 5b wrote, or the author's when
    they kept theirs, and mice-threads.csv. Working without one of them is
    allowed (the scenes cover the whole book) but reported, and the
    provenance header names only the files that had rows."""
    rels = ['reference/story-summary.md', 'reference/story-architecture.md']
    if not _gate(run, rels, '5c (story summary and architecture)'):
        return 'skipped'
    ev = pitch_evidence(run.project_dir, scenes)
    run.reports.extend(f'5c: {note}' for note in ev.notes)
    uncounted = sum(a.uncounted for a in ev.acts)
    if uncounted:
        run.reports.append(f'5c: {uncounted} scene(s) have no word count in scenes.csv, so '
                           f'story-architecture.md\'s lengths leave them out')
    pitch = _ask(run, 'pitch',
                 lambda problems: build_pitch_prompt(profile, scenes, ev, problems),
                 lambda text: parse_pitch(text, ev), PITCH_SCHEMA, PITCH_MAX_TOKENS)
    header = provenance_header(run.version, '5c', ['profile', 'scenes', *ev.sources])
    today = datetime.now(timezone.utc).date().isoformat()
    if not _write_all(run, [(rels[0], render_story_summary(pitch, header, today)),
                            (rels[1], render_story_architecture(pitch, ev, scenes, header))],
                      '5c', '5c'):
        return 'partial'
    return 'written'


def run_characters(run: Run, profile: dict, scenes: list[dict[str, str]]) -> StepOutcome:
    """Step 5d: character-bible.md, from the characters the scenes put on
    stage, their established facts and lines tagged with their name."""
    rel = 'reference/character-bible.md'
    if not _gate(run, [rel], '5d (character bible)'):
        return 'skipped'
    chars, notes, sources = character_evidence(run.project_dir, scenes)
    title, title_notes = _book_title(run.project_dir)
    run.reports.extend(f'5d: {n}' for n in notes + title_notes)
    if not chars:
        run.reports.append('5d skipped: no scene names a character in characters.csv, so '
                           'there is no one to describe')
        return 'skipped'
    reply = _ask(run, 'characters',
                 lambda problems: build_characters_prompt(profile, chars, problems),
                 lambda text: parse_characters(text, chars),
                 CHARACTERS_SCHEMA, CHARACTERS_MAX_TOKENS)
    header = provenance_header(run.version, '5d', ['profile', *sources])
    doc = render_character_bible(reply, chars, title, header)
    return 'written' if _write_all(run, [(rel, doc)], '5d', '5d') else 'partial'


def run_world(run: Run, profile: dict, scenes: list[dict[str, str]]) -> StepOutcome:
    """Step 5e: world-bible.md, and systems-bible.md (the book's formal
    system, or a stub saying it has none and why). Skipped, and said, when
    no scene's location is in locations.csv: a world bible with no places
    would read as a book set nowhere."""
    rels = ['reference/world-bible.md', 'reference/systems-bible.md']
    if not _gate(run, rels, '5e (world and systems bibles)'):
        return 'skipped'
    title, title_notes = _book_title(run.project_dir)
    ev, notes = world_evidence(run.project_dir, scenes, title)
    run.reports.extend(f'5e: {n}' for n in notes + title_notes)
    if not ev.locations:
        run.reports.append('5e skipped: no scene is set in a place locations.csv names')
        return 'skipped'
    reply = _ask(run, 'world', lambda problems: build_world_prompt(profile, scenes, ev, problems),
                 lambda text: parse_world(text, ev), WORLD_SCHEMA, WORLD_MAX_TOKENS)
    header = provenance_header(run.version, '5e', ['profile', *ev.sources])
    files = [(rels[0], render_world_bible(reply, ev, header)),
             (rels[1], render_systems_bible(reply, title, header))]
    return 'written' if _write_all(run, files, '5e', '5e') else 'partial'


def run_voice(run: Run, profile: dict, scenes: list[dict[str, str]]) -> StepOutcome:
    """Step 5f: voice-guide.md and voice-profile.csv, from sampled prose and
    the measures code takes of it. Skipped, and said, when no scene has
    prose: a voice can't be described from summaries."""
    rels = ['reference/voice-guide.md', 'reference/voice-profile.csv']
    if not _gate(run, rels, '5f (voice guide and profile)'):
        return 'skipped'
    title, title_notes = _book_title(run.project_dir)
    ev, notes = voice_evidence(run.project_dir, scenes, title)
    run.reports.extend(f'5f: {n}' for n in title_notes + (notes if ev else []))
    if ev is None:
        run.reports.append('5f skipped: no scene has prose to describe a voice from ('
                           + '; '.join(notes) + ')')
        return 'skipped'
    reply = _ask(run, 'voice', lambda problems: build_voice_prompt(profile, ev, problems),
                 lambda text: parse_voice(text, ev), VOICE_SCHEMA, VOICE_MAX_TOKENS)
    header = provenance_header(run.version, '5f', ['profile', *ev.sources])
    files = [(rels[0], render_voice_guide(reply, ev, header)),
             (rels[1], _csv_text(voice_profile_rows(reply), VOICE_PROFILE_COLUMNS))]
    return 'written' if _write_all(run, files, '5f', '5f') else 'partial'


#: Every path phase 5 may change, for the commit. `working/` covers the
#: provenance record, the cell record, the logs and the cost ledger.
WRITTEN_PATHS = ['reference/spine.csv', 'reference/architecture.csv',
                 'reference/scenes.csv', 'reference/scene-intent.csv',
                 'reference/scene-briefs.csv', 'reference/themes.csv',
                 'reference/motif-taxonomy.csv', 'reference/story-summary.md',
                 'reference/story-architecture.md', 'reference/character-bible.md',
                 'reference/world-bible.md', 'reference/systems-bible.md',
                 'reference/voice-guide.md', 'reference/voice-profile.csv',
                 'storyforge.yaml', 'working/']
