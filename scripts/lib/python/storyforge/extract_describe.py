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
    'required': ['genre', 'subgenre', 'spine', 'architecture'],
    'properties': {
        'genre': {'type': 'string'},
        'subgenre': {'type': 'string'},
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


class StructureError(ValueError):
    """A structure reply that can't be written; `problems` go back to the
    model on the one retry."""

    def __init__(self, problems: list[str]):
        super().__init__('; '.join(problems))
        self.problems = problems


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

2. **spine**: the {spine_lo}-{spine_hi} irreducible events of this story, in reading
   order. Remove any one and the story stops making sense. For each:
   - id: a 2-5 word lowercase-hyphenated slug of the event
   - title: a short title
   - summary: one sentence, at most {_SUMMARY_MAX_WORDS} words, saying what happens
   - function: one sentence on what the event does for the story

3. **architecture**: the {arch_lo}-{arch_hi} anchor scenes that carry the spine,
   chosen from the scene ids above (use the ids exactly). Every spine event
   needs at least one anchor. For each: scene_id, and spine_event (the spine id
   it carries). Choose the scenes where the story actually turns, wherever they
   fall; don't space them evenly.
"""


def parse_structure(response: str, scenes: list[dict[str, str]]) -> dict:
    """Read and check step 5a's reply. Returns `{genre, subgenre, spine,
    architecture}` with spine events in reading order (by their first
    anchor) and anchors in reading order.

    Raises StructureError listing every problem, so one retry can fix them
    all: an id that is no scene, a scene anchored twice, an anchor naming
    no spine event, a spine event with no anchor, counts outside the ranges,
    an empty or overlong summary. These are the mechanical floors; whether
    the book balances action and sequel is a fact about the book, and is
    left to the scorer to report.
    """
    from .extract import _json_answer
    data = _json_answer(response, STRUCTURE_SCHEMA)
    order = {s['id']: i for i, s in enumerate(scenes)}
    problems = []

    spine = []
    seen_spine = set()
    for e in data['spine']:
        sid = e['id'].strip()
        if not sid or sid in seen_spine:
            problems.append(f'spine event id {sid!r} is empty or repeated')
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
        raise StructureError(problems)

    anchors.sort(key=lambda a: order[a['scene_id']])
    first = {}
    for a in anchors:
        first.setdefault(a['spine_event'], order[a['scene_id']])
    spine.sort(key=lambda e: first[e['id']])
    return {'genre': ' '.join(data['genre'].split()),
            'subgenre': ' '.join(data['subgenre'].split()),
            'spine': spine, 'architecture': anchors}


def structure_rows(structure: dict, scenes: list[dict[str, str]],
                   ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """spine.csv and architecture.csv rows for a parsed structure.

    An anchor's row is its scene: id, seq, title, act, pov and the intent
    columns are copied from the scene CSVs, and its summary is the scene's
    own. A spine event's act is the act of its first anchor, so the two
    files can't disagree about where an event falls.
    """
    by_id = {s['id']: s for s in scenes}
    arch = []
    for a in structure['architecture']:
        s = by_id[a['scene_id']]
        arch.append({
            'id': s['id'], 'seq': s.get('seq', ''), 'title': s.get('title', ''),
            'summary': s.get('summary', ''), 'act': s.get('act', ''),
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

TIERS = ('primary', 'secondary', 'tertiary')
THEME_RANGE = (3, 7)
#: A motif the briefs name in fewer scenes than this isn't recurring.
MOTIF_MIN_SCENES = 2


def motif_candidates(scenes: list[dict[str, str]]) -> list[tuple[str, list[str]]]:
    """The briefs' motif mentions that recur: `(mention, scene ids)` for each
    lowercased mention found in at least MOTIF_MIN_SCENES scenes, most
    frequent first. Counted here, not by the model, so the taxonomy is built
    from what the briefs actually name."""
    seen: dict[str, list[str]] = {}
    for s in scenes:
        for m in {m.strip().lower() for m in s.get('motifs', '').split(';') if m.strip()}:
            seen.setdefault(m, []).append(s['id'])
    recurring = [(m, ids) for m, ids in seen.items() if len(ids) >= MOTIF_MIN_SCENES]
    return sorted(recurring, key=lambda kv: (-len(kv[1]), kv[0]))


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
            'required': ['id', 'name', 'aliases', 'tier'],
            'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'},
                           'aliases': {'type': 'array', 'items': {'type': 'string'}},
                           'tier': {'type': 'string', 'enum': list(TIERS)}}}},
    },
}


def build_themes_prompt(profile: dict, scenes: list[dict[str, str]],
                        motifs: list[tuple[str, list[str]]],
                        problems: list[str] | None = None) -> str:
    """Step 5b's prompt: name the themes, tag scenes with them, and group the
    briefs' recurring motif mentions into a taxonomy."""
    lo, hi = THEME_RANGE
    scene_lines = '\n'.join(
        f'{s["id"]}: {s.get("function", "").strip() or s.get("summary", "").strip()}'
        f' [stake: {s.get("value_at_stake", "")}; shift: {s.get("value_shift", "")}]'
        for s in scenes)
    motif_lines = '\n'.join(f'- {m} ({len(ids)} scenes)' for m, ids in motifs) \
        or '- (the briefs name no motif in more than one scene)'
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

## Motifs the scene briefs name in more than one scene

{motif_lines}
{retry}
## What to produce

1. **themes**: the {lo}-{hi} abstract concerns this book argues, each phrased as
   what the book is about rather than a moral. For each: id (a 1-4 word
   lowercase-hyphenated slug), name, tier (primary for the book's central
   concern, then secondary and tertiary), and description (one or two
   sentences on how the book treats it). Themes are abstract; concrete
   recurring images are motifs, below.

2. **scene_themes**: for every scene id above, the theme ids it engages
   (an empty list where a scene engages none).

3. **motifs**: group the motif mentions above into the book's recurring
   images and objects. Each: id (a slug), name, aliases (every listed mention
   it covers, exactly as written above), tier. Leave out a mention that isn't
   a real recurring image; don't add motifs the list doesn't contain.
"""


def parse_themes(response: str, scenes: list[dict[str, str]],
                 motifs: list[tuple[str, list[str]]]) -> dict:
    """Read and check step 5b's reply. Returns `{themes, scene_themes,
    motifs}`: `scene_themes` maps every scene id to a list of theme ids.

    Raises StructureError listing every problem: a repeated or empty id, a
    theme count outside THEME_RANGE, a scene tagged with an unknown theme, a
    scene left out or invented, a motif alias that isn't a listed mention,
    or one mention claimed by two motifs.
    """
    from .extract import _json_answer
    data = _json_answer(response, THEMES_SCHEMA)
    problems = []

    themes, theme_ids = [], set()
    for t in data['themes']:
        tid = t['id'].strip()
        if not tid or tid in theme_ids:
            problems.append(f'theme id {tid!r} is empty or repeated')
            continue
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

    mentions = {m for m, _ in motifs}
    claimed: dict[str, str] = {}
    out_motifs, motif_ids = [], set()
    for m in data['motifs']:
        mid = m['id'].strip()
        if not mid or mid in motif_ids:
            problems.append(f'motif id {mid!r} is empty or repeated')
            continue
        motif_ids.add(mid)
        aliases = []
        for a in m['aliases']:
            a = a.strip().lower()
            if a not in mentions:
                problems.append(f'motif {mid}\'s alias {a!r} is not one of the listed mentions')
            elif a in claimed and claimed[a] != mid:
                problems.append(f'mention {a!r} is claimed by both {claimed[a]} and {mid}')
            else:
                claimed[a] = mid
                aliases.append(a)
        if not aliases:
            problems.append(f'motif {mid} covers none of the listed mentions')
        out_motifs.append({'id': mid, 'name': ' '.join(m['name'].split()),
                           'aliases': list(dict.fromkeys(aliases)), 'tier': m['tier']})

    if problems:
        raise StructureError(problems)
    return {'themes': themes, 'scene_themes': tagged, 'motifs': out_motifs}
