"""Interior illustration plan, markers, and resolution.

Prose books can carry interior illustrations. This module owns the data and
mechanics behind them:

  - ``reference/illustration-plan.csv`` — one row per illustration, holding
    the narrative justification, the art-direction fields, and (after ingest)
    the file digest and dimensions.
  - ``reference/illustration-direction.md`` — the old book-level art-direction
    document, superseded by ``reference/canon/`` (see ``storyforge.canon`` and
    ``storyforge.prompts_illustrate.CANON_PLAN``). Kept readable here only for
    ``_direction_anchor_mismatches``, a one-time safety net for a project that
    still has a hand-edited copy lying around.
  - The scene marker ``![[illus:{id}]]`` — insertion at a whitespace-tolerant
    prose anchor, parsing, and stripping.
  - Resolution — one marker, three output targets (epub/PDF, web book,
    Bookshelf publish manifest), each rendering it its own way.
  - The selection pre-pass, the recommended render order, and plan validation.

The marker is deliberately *not* a markdown image. A raw ``![](path)`` would
resolve correctly for exactly one target and be wrong for the other two, and
it carries none of the plan metadata. Keeping an opaque marker means the
resolver decides per target, and prose stays free of build-time paths.

See benjaminsnorris/storyforge#278.
"""

import csv
import hashlib
import os
import re
import struct
import sys
from html.parser import HTMLParser
from typing import Callable, Literal, TypedDict

DELIMITER = '|'
ARRAY_DELIMITER = ';'

PLAN_FILENAME = 'illustration-plan.csv'
DIRECTION_FILENAME = 'illustration-direction.md'

PLAN_COLUMNS: list[str] = [
    'id', 'scene_id', 'anchor', 'placement', 'layout', 'beat', 'rationale',
    'subject', 'composition', 'palette', 'mood', 'motifs', 'canon_refs',
    'status', 'asset_file', 'prompt_file', 'sha256', 'width', 'height',
    'ingested_at', 'state_override', 'register', 'scene_digest', 'treatment',
    'treatment_at',
]

#: Columns added after the plan schema shipped. They are in PLAN_COLUMNS, so
#: every `write_plan` emits them and a plan upgrades its own header the first
#: time anything writes to it — but a plan CSV that predates them is legal and
#: must not be a validation error. A book with twenty ingested illustrations
#: and no `ingested_at` column is exactly the state this column was added to
#: cope with, and failing its schema check would block the very run that fixes
#: it. Empty is meaningful, not missing: `cmd_illustrate._references_for`
#: reads an empty `ingested_at` as "predates the current canon".
#:
#: `state_override`, `register`, and `scene_digest` join it for the same reason
#: (#278 phase 2): a plan written before the visual-state matrix existed is
#: legal, and the first write to it upgrades the header. `treatment` joins it in
#: phase 3 — a plan that predates the sequence pre-pass is legal, and an empty
#: `treatment` is exactly the state `--sequence` exists to fill. `treatment_at`
#: is the ISO date `--sequence` staged the row, and is what lets the packet
#: distinguish a treatment written *after* a render (the art does not follow it)
#: from one written before (nothing is wrong) instead of warning about both.
OPTIONAL_PLAN_COLUMNS: frozenset[str] = frozenset({
    'ingested_at', 'state_override', 'register', 'scene_digest', 'treatment',
    'treatment_at',
})

#: The book's lighting extremes, marked on the plan so the anchor batch can
#: bracket them. Optional — most illustrations are neither.
VALID_REGISTERS: frozenset[str] = frozenset({'darkest', 'brightest'})

# Placement is relative to the *paragraph* containing the anchor, not to the
# anchor's character offset — an illustration never splits a paragraph.
VALID_PLACEMENTS = frozenset({
    'before_anchor', 'after_anchor', 'scene_open', 'scene_close',
})

# Print page treatment. Orthogonal to `placement`: "full-page opener" is a
# layout of full_page at a placement of scene_open. A double-page spread is
# inherently landscape, which is why aspect derives from layout first.
VALID_LAYOUTS = frozenset({
    'full_page', 'half_page', 'double_page', 'inline',
})
DEFAULT_LAYOUT = 'full_page'

# Placements that need no anchor text.
ANCHORLESS_PLACEMENTS = frozenset({'scene_open', 'scene_close'})

VALID_PLAN_STATUSES = frozenset({
    'planned', 'prompted', 'rendered', 'ingested', 'superseded',
})

# Statuses that assert a file exists on disk.
FILED_STATUSES = frozenset({'ingested'})

ILLUSTRATIONS_SUBDIR = os.path.join('manuscript', 'assets', 'illustrations')
PROMPTS_SUBDIR = os.path.join(ILLUSTRATIONS_SUBDIR, 'prompts')

VALID_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')

#: In-memory marker for a row whose field count exceeded the header. Never
#: written back — write_plan's fieldnames come from PLAN_COLUMNS plus author
#: columns, and this key is filtered out explicitly.
_SHATTERED_FLAG = '_shattered'

# Ids must match exactly what the marker regex accepts, so that a plan row an
# author wrote by hand (`LF-01`) is never rejected by validation while its
# marker parses fine. Case is preserved in the plan and in prose; only the
# published asset key is normalized (see asset_key).
_ID_RE = re.compile(r'\A[A-Za-z0-9][A-Za-z0-9_-]*\Z')

# Marker on its own line — the canonical form, and what insert_marker writes.
MARKER_LINE_RE = re.compile(
    r'^[ \t]*!\[\[illus:([A-Za-z0-9][A-Za-z0-9_-]*)\]\][ \t]*$',
    re.MULTILINE,
)

# Marker anywhere, including mid-paragraph. Used only for stripping, so that a
# hand-placed inline marker still never reaches a prose scorer or a word count.
MARKER_ANY_RE = re.compile(r'!\[\[illus:([A-Za-z0-9][A-Za-z0-9_-]*)\]\]')


def marker_for(illus_id: str) -> str:
    """Return the scene marker for an illustration id."""
    return f'![[illus:{illus_id}]]'


# What Bookshelf accepts as an asset key, from its `isValidSlug` —
# `/^[a-z0-9][a-z0-9-]*$/`, max 128 characters.
#
# Narrower than `_ID_RE`, which also allows `_` because the marker regex does.
# So `LF_01` is a legal plan id and a legal marker, and `asset_key` lowercases
# it into `lf_01`, which the assets endpoint rejects with a 400. That went
# unnoticed until #284 made assets actually ship; `validate_plan` reports it
# now, because a publish is a poor place to discover a naming rule.
ASSET_KEY_RE = re.compile(r'\A[a-z0-9][a-z0-9-]*\Z')
ASSET_KEY_MAX_LENGTH = 128


def _publishable_asset_key(illus_id: str) -> bool:
    """Whether this id's asset key is one Bookshelf will accept."""
    key = asset_key(illus_id)
    return bool(ASSET_KEY_RE.match(key)) and len(key) <= ASSET_KEY_MAX_LENGTH


def asset_key(illus_id: str) -> str:
    """Normalize a plan id into its published asset key.

    Ids keep the author's casing in the plan and in the prose marker — `LF-01`
    reads better than `lf-01` in a production document. Storage keys are
    lowercased because they land in a content-addressed path and a database
    unique constraint, where two ids differing only in case would collide
    confusingly. Both the manifest's `assets` array and its per-scene
    `illustrations` placements go through here, so the two always agree.
    """
    return illus_id.strip().lower()


# ============================================================================
# Paths
# ============================================================================

def plan_path(project_dir: str) -> str:
    """Path to the illustration plan CSV."""
    return os.path.join(project_dir, 'reference', PLAN_FILENAME)


def direction_path(project_dir: str) -> str:
    """Path to the book-level illustration art-direction document."""
    return os.path.join(project_dir, 'reference', DIRECTION_FILENAME)


def illustrations_dir(project_dir: str) -> str:
    """Directory holding ingested illustration files."""
    return os.path.join(project_dir, ILLUSTRATIONS_SUBDIR)


def prompts_dir(project_dir: str) -> str:
    """Directory holding per-illustration art-direction prompt files."""
    return os.path.join(project_dir, PROMPTS_SUBDIR)


def asset_path(project_dir: str, row: dict[str, str]) -> str | None:
    """Absolute path to a plan row's ingested file, or None if unrecorded."""
    rel = (row.get('asset_file') or '').strip()
    if not rel:
        return None
    return os.path.join(project_dir, rel)


def default_asset_rel(illus_id: str, extension: str = '.png') -> str:
    """Canonical project-relative path for an illustration's file."""
    ext = extension if extension.startswith('.') else f'.{extension}'
    return os.path.join(ILLUSTRATIONS_SUBDIR, f'{illus_id}{ext}')


def default_prompt_rel(illus_id: str) -> str:
    """Canonical project-relative path for an illustration's prompt file."""
    return os.path.join(PROMPTS_SUBDIR, f'{illus_id}.md')


# ============================================================================
# Art-direction document
# ============================================================================

#: Sections the direction document used to be expected to carry. The
#: reference tier (`reference/canon/`) replaced this document as the source
#: of book-level direction and continuity anchors — `--direction` no longer
#: writes it, and `--prompts` no longer reads it. `_direction_anchor_mismatches`
#: (the hand-edit safety net) reads the document itself directly — via
#: `read_direction`/`find_section`/`ANCHORS_SECTION` — and never touches this
#: constant. Its only remaining reference is the assertion in
#: `tests/test_illustrations.py::test_read_direction_parses_every_section`;
#: it is test-only at this point, kept rather than deleted this round.
DIRECTION_SECTIONS: tuple[str, ...] = (
    'Format', 'Visual promise', 'Recurring visual language',
    'Content limits', 'Continuity anchors',
)

ANCHORS_SECTION = 'Continuity anchors'

_H2_RE = re.compile(r'^##[ \t]+(.+?)[ \t]*$', re.MULTILINE)


def read_direction(project_dir: str) -> dict[str, str]:
    """Parse the direction document into `{section heading: body}`.

    Returns {} when the document does not exist. Headings are kept verbatim so
    an author can add sections of their own and still have them reach the
    prompt builder — the document is theirs, not a fixed form.
    """
    path = direction_path(project_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        text = f.read().replace('\r\n', '\n').replace('\r', '')

    sections: dict[str, str] = {}
    matches = list(_H2_RE.finditer(text))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[match.end():end].strip()
    return sections


def find_section(sections: dict[str, str], wanted: str) -> str | None:
    """Return the heading in *sections* matching *wanted*, ignoring case.

    Section bodies are looked up by heading text, and a model asked to write
    ``## Continuity anchors`` will sometimes write ``## Continuity Anchors``. A
    case-sensitive lookup silently returned nothing, so the author's anchors
    were invisible to every prompt.
    """
    target = wanted.strip().lower()
    for name in sections:
        if name.strip().lower() == target:
            return name
    return None


def has_reference_tier(project_dir: str) -> bool:
    """True when every book-level canon file exists and is populated.

    The reference tier is what makes a book's images look like one book. A
    project without it can still be planned, but its prompts would carry no
    house style, which is why --prompts warns loudly rather than proceeding
    quietly.
    """
    return not missing_reference_sections(project_dir)


def missing_reference_sections(project_dir: str) -> list[str]:
    """Book-level canon ids that are absent, empty, or still placeholder text.

    Empty is checked here rather than in canon._section_body_is_placeholder:
    that shared function deliberately treats an empty Embeddable block as
    populated (see is_canon_block_populated's docstring — GN's
    page-architecture gate relies on that). An empty book-level direction
    section is still useless to a prompt, the same way the retired
    illustration-direction reader treated an empty section as missing, so
    the empty check is added on this side, composing with the shared
    placeholder detector rather than forking it.
    """
    from storyforge import canon
    from storyforge.prompts_illustrate import CANON_PLAN

    missing: list[str] = []
    for canon_id, _canon_type, _purpose in CANON_PLAN:
        path = canon.resolve_canon_path(project_dir, canon_id)
        if path is None:
            missing.append(canon_id)
            continue
        body = canon.embeddable_block_text(path)
        if (body is None or not body.strip()
                or canon._section_body_is_placeholder(body)):
            missing.append(canon_id)
    return missing


# ============================================================================
# Plan CSV I/O
# ============================================================================

def read_plan(project_dir: str) -> list[dict[str, str]]:
    """Read the illustration plan into a list of dicts.

    Returns an empty list when the plan does not exist. Missing cells are
    coerced to '' (csv.DictReader yields None for short rows), and CR
    characters are stripped so CRLF files never leak ``\\r`` downstream —
    matching elaborate._read_csv.
    """
    path = plan_path(project_dir)
    if not os.path.isfile(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    reader = csv.DictReader(raw.splitlines(), delimiter=DELIMITER)
    rows = []
    for row in reader:
        # A None key means the row had more fields than the header — an
        # unescaped `|` shattered it. Recorded so validate_plan can report the
        # row rather than letting it through with shifted columns.
        shattered = None in row
        clean = {k: (v if v is not None else '') for k, v in row.items()
                 if k is not None}
        if not (clean.get('id') or '').strip():
            continue
        if shattered:
            clean[_SHATTERED_FLAG] = '1'
        rows.append(clean)
    return rows


def read_plan_as_map(project_dir: str) -> dict[str, dict[str, str]]:
    """Read the plan keyed by illustration id.

    On a duplicate id the first row wins, so a malformed plan degrades to a
    consistent view rather than a randomly-ordered one. validate_plan reports
    the duplicate separately.
    """
    out: dict[str, dict[str, str]] = {}
    for row in read_plan(project_dir):
        out.setdefault(row['id'].strip(), row)
    return out


def sanitize_cell(value: str) -> str:
    """Make a value safe for a pipe-delimited, unquoted CSV.

    A stray ``|`` shatters the row on write and its overflow is then silently
    discarded on read, shifting every column after it. Newlines split one row
    into two. Sanitizing here rather than at each call site means no writer can
    forget — the project's CSV format has no quoting to fall back on.
    """
    if not isinstance(value, str):
        value = str(value)
    return value.replace('|', '/').replace('\n', ' ').replace('\r', '').strip()


def write_plan(project_dir: str, rows: list[dict[str, str]]) -> str:
    """Write the illustration plan, preserving PLAN_COLUMNS order.

    Columns the author added beyond PLAN_COLUMNS are preserved, appended after
    the known ones. The plan is a file authors are told to hand-edit, so
    silently dropping their column on the next ``--prompts`` run would be a
    data loss they never asked for — the same courtesy read_direction extends
    to author-added sections.
    """
    path = plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    extras = [col for row in rows for col in row
              if col not in PLAN_COLUMNS and col is not None
              and col != _SHATTERED_FLAG]
    fieldnames = PLAN_COLUMNS + list(dict.fromkeys(extras))

    with open(path, 'w', newline='', encoding='utf-8') as f:
        # QUOTE_NONE with no escapechar: the format is unquoted by definition,
        # so a value that still needs escaping after sanitize_cell must raise
        # rather than silently switch the file to RFC-4180 quoting.
        #
        # lineterminator='\n' because csv defaults to '\r\n', which turned
        # every one-field edit into a whole-file diff (LF -> CRLF on all 20
        # rows, hiding the real change in review) and produced exactly the
        # state `cleanup`'s own `crlf_line_endings` check flags. Opening with
        # newline='\n' does NOT fix this — the writer emits the terminator
        # itself and no translation is applied on write.
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                delimiter=DELIMITER, extrasaction='ignore',
                                quoting=csv.QUOTE_NONE, escapechar=None,
                                quotechar=None, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({col: sanitize_cell(row.get(col, ''))
                             for col in fieldnames})
    return path


def blank_row(illus_id: str) -> dict[str, str]:
    """Return an empty plan row with every column present."""
    row = {col: '' for col in PLAN_COLUMNS}
    row['id'] = illus_id
    row['status'] = 'planned'
    return row


def upsert_rows(existing: list[dict[str, str]],
                incoming: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge incoming rows into existing ones, keyed by id.

    Existing non-empty cells are preserved — a second planning pass extends
    the plan rather than overwriting author edits. Incoming values only fill
    blanks or land in columns the existing row left empty.
    """
    # One pass builds both structures, which is what keeps them agreeing. The
    # two comprehensions this replaced disagreed: the dict collapsed duplicate
    # ids (last wins) while the list did not, so the result held the same dict
    # object twice AND silently replaced the first row's cells with the
    # duplicate's — the exact overwrite this function promises not to do.
    # First row wins, matching read_plan_as_map.
    by_id: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for row in existing:
        rid = (row.get('id') or '').strip()
        if not rid or rid in by_id:
            continue
        by_id[rid] = dict(row)
        order.append(rid)

    for row in incoming:
        rid = (row.get('id') or '').strip()
        if not rid:
            continue
        if rid in by_id:
            for col, val in row.items():
                if col in PLAN_COLUMNS and val and not by_id[rid].get(col, '').strip():
                    by_id[rid][col] = val
        else:
            merged = blank_row(rid)
            merged.update({k: v for k, v in row.items() if k in PLAN_COLUMNS})
            by_id[rid] = merged
            order.append(rid)
    return [by_id[rid] for rid in order]


# ============================================================================
# Marker parsing and stripping
# ============================================================================

class MarkerHit(TypedDict):
    """A marker found in scene text."""
    id: str
    start: int
    end: int
    line: int


def find_markers(text: str) -> list[MarkerHit]:
    """Return every own-line marker in *text*, in document order."""
    hits: list[MarkerHit] = []
    for m in MARKER_LINE_RE.finditer(text):
        hits.append({
            'id': m.group(1),
            'start': m.start(),
            'end': m.end(),
            'line': text.count('\n', 0, m.start()) + 1,
        })
    return hits


def marker_ids(text: str) -> list[str]:
    """Return the illustration ids marked in *text*, in document order."""
    return [h['id'] for h in find_markers(text)]


def all_marker_ids(text: str) -> list[str]:
    """Every marked id in *text*, including markers placed mid-paragraph.

    ``marker_ids`` is deliberately line-only because an own-line marker is the
    canonical form that feeds paragraph placements. This is the wider view,
    used where *any* occurrence matters — idempotence checks and validation.
    """
    return [m.group(1) for m in MARKER_ANY_RE.finditer(text)]


def inline_marker_ids(text: str) -> list[str]:
    """Ids marked mid-paragraph rather than on their own line."""
    line_ids = marker_ids(text)
    inline = list(all_marker_ids(text))
    for illus_id in line_ids:
        if illus_id in inline:
            inline.remove(illus_id)
    return inline


def has_marker(text: str, illus_id: str) -> bool:
    """True when *text* already carries the marker for *illus_id*.

    Checks any position, not just own-line: a hand-placed inline marker must
    still make insertion a no-op, or ``--embed`` would add a second marker for
    the same illustration and the book would show it twice.
    """
    return illus_id in all_marker_ids(text)


def strip_markers(text: str) -> str:
    """Remove every illustration marker from *text*.

    Own-line markers are removed with their line; inline markers are removed
    in place. The result is byte-identical to the prose before the marker
    landed, for every placement.

    Every prose consumer — word counts, deterministic scorers, revision
    prompts — must go through this. A marker scored as a sentence perturbs
    rhythm variance, and a marker counted as a word inflates word_count.
    """
    if '![[illus:' not in text:
        return text

    lines = text.split('\n')
    kept = [ln for ln in lines if not MARKER_LINE_RE.fullmatch(ln)]
    out = '\n'.join(kept)
    out = MARKER_ANY_RE.sub('', out)
    out = re.sub(r'\n{3,}', '\n\n', out)

    # A marker removed from the very start or end leaves behind the blank line
    # that separated it from the prose, which shifted every character offset
    # the detectors report by two. Restoring the original's leading and
    # trailing newline counts makes the result byte-identical whatever the
    # placement — which is what the scorer-equality assertions depend on.
    leading = len(text) - len(text.lstrip('\n'))
    trailing = len(text) - len(text.rstrip('\n'))
    return '\n' * leading + out.strip('\n') + '\n' * trailing


def count_prose_words(text: str) -> int:
    """Word count for scene text, excluding illustration markers."""
    return len(strip_markers(text).split())


def prose_digest(text: str) -> str:
    """A digest of scene prose, stable under cosmetic whitespace edits.

    Markers come out first (a marker is not prose, and embedding one must not
    read as a revision), then `normalize_for_comparison`, so a reflow or a
    trailing-space change does not surface as staleness while a real rewrite
    does. This is what `illustration-plan.csv:scene_digest` records at ingest and
    what the audit's provenance file records per scene it read.
    """
    from storyforge.common import normalize_for_comparison
    normalized = normalize_for_comparison(strip_markers(text))
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def scene_prose_digest(project_dir: str, scene_id: str) -> str:
    """`prose_digest` of a scene on disk, or '' when the scene has no file."""
    text = _read_scene(project_dir, scene_id)
    return prose_digest(text) if text is not None else ''


# ============================================================================
# Anchor matching
# ============================================================================

def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace, returning the normalized text and an offset map.

    ``offsets[i]`` is the index in the original text of normalized character
    ``i``, so a match found in normalized space maps back to real offsets.
    Anchors are quoted prose, and prose gets re-wrapped — matching on
    normalized whitespace is what makes an anchor survive reflow.
    """
    norm_chars: list[str] = []
    offsets: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space and norm_chars:
                norm_chars.append(' ')
                offsets.append(i)
            prev_space = True
        else:
            norm_chars.append(ch)
            offsets.append(i)
            prev_space = False
    return ''.join(norm_chars), offsets


class AnchorMatch(TypedDict):
    """Where an anchor landed in scene text."""
    start: int
    end: int
    count: int


def _blank_markers(text: str) -> str:
    """Replace markers with equal-length whitespace, preserving offsets.

    Anchors are matched against prose, and a marker sitting inside the
    candidate span would break the match. Blanking rather than deleting keeps
    every character offset in the returned string identical to the original,
    so a match maps straight back onto the real text.
    """
    return MARKER_ANY_RE.sub(lambda m: ' ' * len(m.group(0)), text)


def find_anchor(text: str, anchor: str) -> AnchorMatch | None:
    """Locate *anchor* in *text*, ignoring whitespace differences.

    Returns None when the anchor is absent. ``count`` reports how many times
    it occurs, so callers can refuse to act on an ambiguous anchor rather than
    silently taking the first hit.
    """
    needle = ' '.join((anchor or '').split())
    if not needle:
        return None
    haystack, offsets = _normalize_with_map(_blank_markers(text))
    if not haystack:
        return None

    count = haystack.count(needle)
    if count == 0:
        return None

    pos = haystack.find(needle)
    return {
        'start': offsets[pos],
        'end': offsets[pos + len(needle) - 1] + 1,
        'count': count,
    }


def _paragraph_blocks(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character spans of blank-line-separated blocks."""
    blocks: list[tuple[int, int]] = []
    pos = 0
    for chunk in re.split(r'(\n[ \t]*\n)', text):
        if not chunk:
            continue
        if re.fullmatch(r'\n[ \t]*\n', chunk):
            pos += len(chunk)
            continue
        if chunk.strip():
            blocks.append((pos, pos + len(chunk)))
        pos += len(chunk)
    return blocks


def _block_containing(text: str, offset: int) -> tuple[int, int] | None:
    """Return the block span containing *offset*."""
    for start, end in _paragraph_blocks(text):
        if start <= offset < end:
            return (start, end)
    return None


# ============================================================================
# Marker insertion
# ============================================================================

class InsertResult(TypedDict):
    """Outcome of an insert_marker call."""
    text: str
    changed: bool
    error: str


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split leading YAML frontmatter from the prose after it.

    Returns ``(frontmatter_including_trailing_blank_line, body)``, or
    ``('', text)`` when there is none. Scene files are documented as having no
    frontmatter, but older projects still do, and a marker inserted above it
    breaks every ``startswith('---')`` stripper downstream.
    """
    if not text.startswith('---'):
        return '', text
    match = re.match(r'\A---[ \t]*\n.*?\n---[ \t]*\n', text, re.DOTALL)
    if not match:
        return '', text
    return match.group(0), text[match.end():].lstrip('\n')


def insert_marker(scene_text: str, row: dict[str, str]) -> InsertResult:
    """Insert a plan row's marker into scene text at its anchor.

    Idempotent: a scene that already carries the marker comes back unchanged
    with no error. On a failed or ambiguous anchor match nothing is inserted
    and ``error`` explains why — placing an illustration at a guessed offset
    is worse than not placing it, because the wrong beat reads as a mistake
    the author never made.
    """
    illus_id = (row.get('id') or '').strip()
    if not illus_id:
        return {'text': scene_text, 'changed': False,
                'error': 'plan row has no id'}

    marker = marker_for(illus_id)
    if has_marker(scene_text, illus_id):
        return {'text': scene_text, 'changed': False, 'error': ''}

    placement = (row.get('placement') or 'after_anchor').strip() or 'after_anchor'
    if placement not in VALID_PLACEMENTS:
        return {'text': scene_text, 'changed': False,
                'error': f'invalid placement {placement!r}'}

    # Legacy scene files can still carry YAML frontmatter. Inserting above it
    # would make the file no longer *start* with `---`, and every frontmatter
    # stripper in the pipeline tests exactly that — so the whole YAML block
    # would land in the epub and inflate word_count.
    frontmatter, body = _split_frontmatter(scene_text.rstrip('\n'))

    if placement == 'scene_open':
        return {'text': f'{frontmatter}{marker}\n\n{body}\n',
                'changed': True, 'error': ''}
    if placement == 'scene_close':
        return {'text': f'{frontmatter}{body}\n\n{marker}\n',
                'changed': True, 'error': ''}

    anchor = (row.get('anchor') or '').strip()
    if not anchor:
        return {'text': scene_text, 'changed': False,
                'error': f'placement {placement} requires an anchor'}

    match = find_anchor(body, anchor)
    if match is None:
        return {'text': scene_text, 'changed': False,
                'error': 'anchor not found in scene — prose may have been revised'}
    if match['count'] > 1:
        return {'text': scene_text, 'changed': False,
                'error': f'anchor is ambiguous — appears {match["count"]} times; '
                         f'lengthen it to a unique phrase'}

    block = _block_containing(body, match['start'])
    if block is None:
        return {'text': scene_text, 'changed': False,
                'error': 'could not resolve the paragraph containing the anchor'}

    start, end = block
    if placement == 'before_anchor':
        head, tail = body[:start].rstrip(), body[start:].lstrip()
    else:
        head, tail = body[:end].rstrip(), body[end:].lstrip()

    # A marker at the very start or very end of a scene has prose on one side
    # only; joining unconditionally would leave leading or trailing blanks.
    parts = [p for p in (head, marker, tail) if p]
    return {'text': frontmatter + '\n\n'.join(parts) + '\n',
            'changed': True, 'error': ''}


class PreserveResult(TypedDict):
    """Outcome of restoring markers a rewrite dropped."""
    text: str
    restored: list[str]
    lost: list[str]


def preserve_markers(project_dir: str, original: str,
                     rewritten: str) -> PreserveResult:
    """Restore markers present in *original* but missing from *rewritten*.

    A revision or re-draft pass sends prose to a model and writes the response
    over the scene file. The model has no reason to reproduce a marker, so the
    illustration silently disappears — and nothing downstream notices, because
    an unembedded plan row is indistinguishable from one that was never
    embedded. Restoring here means a polish pass cannot cost the author an
    illustration.

    ``lost`` names markers that could not be restored because the row's anchor
    no longer matches the rewritten prose; those need author attention.
    """
    was_marked = dict.fromkeys(all_marker_ids(original))
    if not was_marked:
        return {'text': rewritten, 'restored': [], 'lost': []}

    plan = read_plan_as_map(project_dir)
    text = rewritten
    restored: list[str] = []
    lost: list[str] = []
    for illus_id in was_marked:
        if has_marker(text, illus_id):
            continue
        row = plan.get(illus_id)
        if row is None:
            lost.append(illus_id)
            continue
        result = insert_marker(text, row)
        if result['changed']:
            text = result['text']
            restored.append(illus_id)
        else:
            lost.append(illus_id)
    return {'text': text, 'restored': restored, 'lost': lost}


def remove_marker(scene_text: str, illus_id: str) -> tuple[str, bool]:
    """Remove one illustration's marker from scene text.

    Returns (text, changed). Used when a plan row is superseded.
    """
    pattern = re.compile(
        r'^[ \t]*!\[\[illus:' + re.escape(illus_id) + r'\]\][ \t]*$\n?',
        re.MULTILINE,
    )
    new = pattern.sub('', scene_text)
    if new == scene_text:
        return scene_text, False
    return re.sub(r'\n{3,}', '\n\n', new), True


# ============================================================================
# Resolution — one marker, three targets
# ============================================================================

def resolve_to_markdown(scene_text: str, plan: dict[str, dict[str, str]],
                        path_for: Callable[[str, dict[str, str]], str | None],
                        ) -> str:
    """Replace markers with markdown image syntax for pandoc-based targets.

    ``path_for(illus_id, row)`` returns the image path to emit, or None to
    drop the marker. Dropping (rather than leaving the marker in place) is
    deliberate: a literal ``![[illus:x]]`` in an epub is a visible defect,
    whereas a missing illustration is merely a missing illustration.
    """
    def repl(m: re.Match) -> str:
        illus_id = m.group(1)
        row = plan.get(illus_id)
        if row is None:
            return ''
        path = path_for(illus_id, row)
        if not path:
            return ''
        alt = (row.get('beat') or row.get('subject') or illus_id).strip()
        alt = alt.replace('[', '(').replace(']', ')')
        return f'![{alt}]({path})'

    resolved = MARKER_LINE_RE.sub(repl, scene_text)
    # Own-line markers become images; anything left is a marker placed
    # mid-paragraph, where a block image cannot go. Strip it rather than let it
    # through — the docstring's rule is that no marker syntax reaches an output
    # artifact, and MARKER_LINE_RE alone left inline ones as literal text.
    return MARKER_ANY_RE.sub('', resolved)


def resolve_for_local(project_dir: str, scene_text: str,
                      relative_to: str | None = None,
                      dropped: list[str] | None = None) -> str:
    """Resolve markers to on-disk image paths for epub/PDF assembly.

    Only rows whose file actually exists resolve; a planned-but-unrendered
    illustration drops out, so assembly of an in-flight book still succeeds.

    Pass ``dropped`` to collect the ids that did not resolve — an author who
    planned eight illustrations and got five should be told which three, rather
    than counting images in the finished epub.
    """
    plan = read_plan_as_map(project_dir)
    if not plan:
        if dropped is not None:
            dropped.extend(dict.fromkeys(all_marker_ids(scene_text)))
        return strip_markers(scene_text)

    def path_for(illus_id: str, row: dict[str, str]) -> str | None:
        result = _local_path_for(illus_id, row)
        if result is None and dropped is not None:
            dropped.append(illus_id)
        return result

    def _local_path_for(illus_id: str, row: dict[str, str]) -> str | None:
        # A superseded illustration must not render. Filtering on file
        # existence alone shipped retired art in the epub while
        # manifest_assets correctly excluded it, so the two targets disagreed —
        # which is the whole thing the single-marker design exists to prevent.
        if (row.get('status') or '').strip() == 'superseded':
            return None
        abs_path = asset_path(project_dir, row)
        if not abs_path or not os.path.isfile(abs_path):
            return None
        if relative_to:
            return os.path.relpath(abs_path, relative_to)
        return abs_path

    resolved = resolve_to_markdown(scene_text, plan, path_for)
    if dropped is not None:
        # Markers with no plan row at all never reach path_for.
        known = set(plan)
        dropped.extend(i for i in dict.fromkeys(all_marker_ids(scene_text))
                       if i not in known)
    return resolved


class ScenePlacement(TypedDict):
    """An illustration's position inside one scene's converted HTML."""
    key: str            #: normalized via asset_key — never a raw plan id
    after_paragraph: int


class _TopLevelParagraphCounter(HTMLParser):
    """Count ``<p>`` elements at the top level of a fragment.

    Nesting depth is tracked so a paragraph inside a ``<blockquote>`` does not
    count. This is the producer half of a contract with the Bookshelf reader
    (benjaminsnorris/bookshelf#12, not yet implemented): the reader must walk
    the scene container's direct children, so a nested paragraph must not be a
    placement boundary on either side. If that repo counts descendants instead,
    this class is wrong and every ``after_paragraph`` shifts.
    """

    #: Elements that never nest and so never open a level.
    VOID = frozenset({
        'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr',
        'area', 'base', 'col', 'embed', 'param', 'track',
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.count = 0
        self._depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.VOID:
            return
        if tag == 'p':
            if self._depth == 0:
                self.count += 1
            # <p> is implicitly closed by the next block element in malformed
            # HTML, so don't track it as an open level.
            return
        self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID or tag == 'p':
            return
        self._depth = max(0, self._depth - 1)


def count_top_level_paragraphs(html: str) -> int:
    """Number of top-level ``<p>`` elements in an HTML fragment."""
    parser = _TopLevelParagraphCounter()
    parser.feed(html)
    parser.close()
    return parser.count


def scene_placements(scene_md: str,
                     md_to_html: Callable[[str], str],
                     ) -> list[ScenePlacement]:
    """Compute each marker's paragraph offset in the converted HTML.

    ``after_paragraph`` is the number of **top-level** ``<p>`` elements that
    precede the marker once the scene is converted. Measured in HTML rather
    than in markdown blocks because that is the unit the reader composes
    against — a markdown block can be a heading, a blockquote, or a scene
    divider, none of which is a ``<p>``.

    This is the contract ``after_paragraph`` defines for the Bookshelf reader
    (benjaminsnorris/bookshelf#12, not yet built): the value is the *count* of
    top-level paragraphs preceding the marker, so a figure with
    ``after_paragraph: 1`` renders after the first one.
    """
    placements: list[ScenePlacement] = []
    for hit in find_markers(scene_md):
        prefix = strip_markers(scene_md[:hit['start']])
        if not prefix.strip():
            placements.append({'key': asset_key(hit['id']),
                               'after_paragraph': 0})
            continue
        placements.append({
            'key': asset_key(hit['id']),
            'after_paragraph': count_top_level_paragraphs(md_to_html(prefix)),
        })
    return placements


#: Roles the publish manifest's `assets` array can carry.
#:
#: A growing set, deliberately. `illustration` came first; `cover` joined it
#: when the cover stopped riding the deprecated `cover_base64` field
#: (benjaminsnorris/storyforge#284), and a later phase may add a packet or
#: reference role. The asset *transport* never branches on this value — see
#: `storyforge.bookshelf.sync_assets` — so widening it is a one-line change
#: here plus whatever produces the new rows.
AssetRole = Literal['illustration', 'cover']


def normalize_asset_extension(extension: str) -> str:
    """Normalize a file extension to the form the asset bucket stores.

    Collapses ``jpg`` onto ``jpeg``, matching bookshelf's own
    ``normalizeExtension``. The storage path is ``{digest}.{extension}``, so
    leaving both spellings in play lets one image occupy two paths — which
    quietly undoes content addressing and makes the digest diff re-upload bytes
    that are already in the bucket. Both sides normalizing means the client's
    idea of an object is identical to the server's.
    """
    ext = extension.strip().lstrip('.').lower()
    return 'jpeg' if ext == 'jpg' else ext


class _ManifestAssetRequired(TypedDict):
    """Fields every published asset carries."""
    key: str          #: normalized via asset_key — never a raw plan id
    role: AssetRole
    sha256: str
    extension: str


class ManifestAsset(_ManifestAssetRequired, total=False):
    """One asset entry for the Bookshelf publish manifest."""
    width: int
    height: int
    byte_size: int
    alt_text: str


def manifest_assets(project_dir: str,
                    used_keys: set[str] | None = None) -> list[ManifestAsset]:
    """Build the manifest ``assets`` array from ingested plan rows.

    Metadata only — no bytes. Rows without a digest are skipped: the publish
    contract is content-addressed, so an asset with no sha256 has nowhere to
    live (see benjaminsnorris/bookshelf#11).
    """
    # Normalize defensively: asset_key is idempotent, and a caller passing plan
    # ids (author casing) would otherwise silently get zero assets — and then a
    # misleading "not ingested" warning from generate_publish_manifest.
    wanted = None if used_keys is None else {asset_key(k) for k in used_keys}

    assets: list[ManifestAsset] = []
    for row in read_plan(project_dir):
        key = asset_key(row['id'])
        if wanted is not None and key not in wanted:
            continue
        if row.get('status', '').strip() != 'ingested':
            continue
        digest = (row.get('sha256') or '').strip()
        if not digest:
            continue
        rel = (row.get('asset_file') or '').strip()
        ext = normalize_asset_extension(os.path.splitext(rel)[1]) or 'png'
        asset: ManifestAsset = {
            'key': key, 'role': 'illustration',
            'sha256': digest, 'extension': ext,
        }
        # Assigned individually rather than in a loop: a TypedDict subscript
        # needs a literal key, and the loop form only compiled behind a
        # `# type: ignore[literal-required]` that nothing in this repo can
        # verify is still needed.
        width = (row.get('width') or '').strip()
        if width.isdigit():
            asset['width'] = int(width)
        height = (row.get('height') or '').strip()
        if height.isdigit():
            asset['height'] = int(height)
        alt = (row.get('beat') or '').strip()
        if alt:
            asset['alt_text'] = alt
        assets.append(asset)
    return assets


def manifest_asset_sources(project_dir: str) -> dict[str, str]:
    """Map each ingested plan row's digest to its project-relative file.

    The publish transport uploads bytes by digest and never reads the plan
    itself (see ``storyforge.bookshelf.sync_assets``), so this is the
    illustration half of the mapping its caller assembles — the cover
    contributes the other half.

    Rows without a digest or a recorded file are omitted; they cannot be
    published either, so ``manifest_assets`` skips them too.
    """
    sources: dict[str, str] = {}
    for row in read_plan(project_dir):
        if row.get('status', '').strip() != 'ingested':
            continue
        digest = (row.get('sha256') or '').strip()
        rel = (row.get('asset_file') or '').strip()
        if digest and rel:
            sources.setdefault(digest, rel)
    return sources


# ============================================================================
# File inspection — digest and dimensions
# ============================================================================

def sha256_of(path: str) -> str:
    """Hex sha256 of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


class ImageProbe(TypedDict):
    """Result of inspecting an image file."""
    dimensions: tuple[int, int] | None
    reason: str


def probe_image(path: str) -> ImageProbe:
    """Read an image's dimensions, naming the failure when it cannot.

    `image_dimensions` collapses "unreadable", "unrecognized format",
    "truncated", and "WebP variant this parser does not cover" into one None,
    and ingest rendered all of them as "not a readable PNG, JPEG, or WebP" —
    which tells an author with a perfectly valid progressive JPEG that their
    file is broken. They re-export, see the same message, and conclude the tool
    is broken.
    """
    ext = os.path.splitext(path)[1].lower()
    if not os.path.exists(path):
        return {'dimensions': None, 'reason': 'the file does not exist'}
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return {'dimensions': None,
                'reason': f'could not be read ({exc.strerror or exc})'}
    if size == 0:
        return {'dimensions': None, 'reason': 'the file is empty'}
    if ext not in VALID_IMAGE_EXTENSIONS:
        return {'dimensions': None,
                'reason': f'{ext or "no extension"} is not a supported format '
                          f'(expected one of '
                          f'{", ".join(VALID_IMAGE_EXTENSIONS)})'}

    dims = image_dimensions(path)
    if dims is not None:
        return {'dimensions': dims, 'reason': ''}

    try:
        with open(path, 'rb') as f:
            head = f.read(16)
    except OSError as exc:
        return {'dimensions': None,
                'reason': f'could not be read ({exc.strerror or exc})'}

    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        raw_fourcc = head[12:16]
        fourcc = raw_fourcc.decode('latin-1').strip()
        if raw_fourcc in (b'VP8 ', b'VP8L', b'VP8X'):
            # A chunk we do read, so the payload is malformed rather than the
            # variant being unsupported. Saying "unsupported" would send the
            # author to re-export a file that is simply incomplete.
            return {'dimensions': None,
                    'reason': f'is a WebP whose {fourcc} chunk is malformed or '
                              f'truncated ({size} bytes) — re-download it'}
        return {'dimensions': None,
                'reason': f'is a WebP whose {fourcc!r} chunk this parser does '
                          f'not read (VP8, VP8L, and VP8X only). The file may '
                          f'be valid — re-export it as PNG'}
    if head[:2] == b'\xff\xd8':
        return {'dimensions': None,
                'reason': f'is a JPEG whose data ends before a start-of-frame '
                          f'marker ({size} bytes) — it looks truncated'}
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return {'dimensions': None,
                'reason': f'is a PNG with an unreadable header ({size} bytes)'}
    return {'dimensions': None,
            'reason': f'does not begin with PNG, JPEG, or WebP magic bytes '
                      f'despite its {ext} extension'}


def image_dimensions(path: str) -> tuple[int, int] | None:
    """Return (width, height) for a PNG, JPEG, or WebP file.

    Header parsing rather than an imaging library — the plugin has no
    third-party runtime dependencies, and dimensions are only needed to
    reserve layout space in the reader. Returns None for anything
    unrecognized or truncated.
    """
    try:
        with open(path, 'rb') as f:
            head = f.read(32)
            if head[:8] == b'\x89PNG\r\n\x1a\n':
                if len(head) < 24 or head[12:16] != b'IHDR':
                    return None
                w, h = struct.unpack('>II', head[16:24])
                return (w, h)
            if head[:2] == b'\xff\xd8':
                return _jpeg_dimensions(f)
            if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
                return _webp_dimensions(f, head)
    except (OSError, struct.error):
        return None
    return None


# JPEG markers that carry no payload length and must be skipped by 2 bytes.
_JPEG_STANDALONE = frozenset(range(0xD0, 0xDA)) | {0x01}
# Start-of-frame markers whose payload holds the dimensions. DC4 (0xC4),
# DNL (0xC8), and DAC (0xCC) sit in the same numeric range but are not SOF.
_JPEG_SOF = frozenset(
    set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
)


def _jpeg_dimensions(f) -> tuple[int, int] | None:
    """Walk JPEG segments to the first SOF marker."""
    f.seek(2)
    while True:
        byte = f.read(1)
        while byte == b'\xff':
            byte = f.read(1)
        if not byte:
            return None
        marker = byte[0]
        if marker in _JPEG_STANDALONE:
            continue
        length_bytes = f.read(2)
        if len(length_bytes) < 2:
            return None
        length = struct.unpack('>H', length_bytes)[0]
        if marker in _JPEG_SOF:
            payload = f.read(5)
            if len(payload) < 5:
                return None
            height, width = struct.unpack('>HH', payload[1:5])
            return (width, height)
        if length < 2:
            return None
        f.seek(length - 2, os.SEEK_CUR)


def _webp_dimensions(f, head: bytes) -> tuple[int, int] | None:
    """Read dimensions from a VP8, VP8L, or VP8X WebP chunk."""
    f.seek(12)
    chunk = f.read(8)
    if len(chunk) < 8:
        return None
    fourcc = chunk[:4]
    if fourcc == b'VP8X':
        data = f.read(10)
        if len(data) < 10:
            return None
        w = 1 + int.from_bytes(data[4:7], 'little')
        h = 1 + int.from_bytes(data[7:10], 'little')
        return (w, h)
    if fourcc == b'VP8 ':
        data = f.read(10)
        if len(data) < 10 or data[3:6] != b'\x9d\x01\x2a':
            return None
        w = int.from_bytes(data[6:8], 'little') & 0x3FFF
        h = int.from_bytes(data[8:10], 'little') & 0x3FFF
        return (w, h)
    if fourcc == b'VP8L':
        data = f.read(5)
        if len(data) < 5:
            return None
        # Without this check a truncated VP8L of all-zero bytes reads as a
        # valid 1x1 image, and those dimensions get written to the plan and
        # published as the reader's layout hint.
        if data[0] != 0x2F:
            return None
        bits = int.from_bytes(data[1:5], 'little')
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return (w, h)
    return None


def is_supported_image(path: str) -> bool:
    """True when the extension is one the publish pipeline accepts."""
    return os.path.splitext(path)[1].lower() in VALID_IMAGE_EXTENSIONS


#: Trailing bytes that prove a container closed properly, by magic prefix.
#: A header-valid but truncated file — what an aborted download leaves — passes
#: every dimension check, so the end of the container is the only thing that
#: distinguishes a complete render from a fragment.
_CONTAINER_END = (
    (b'\x89PNG\r\n\x1a\n', b'IEND\xaeB`\x82', 'PNG', 'an IEND chunk'),
    (b'\xff\xd8', b'\xff\xd9', 'JPEG', 'an EOI marker'),
)


def incomplete_image_reason(path: str) -> str | None:
    """Return why an image looks truncated, or None when it looks complete.

    Guards the one path that overwrites an existing render. `image_dimensions`
    reads 32 bytes and returns, so a 33-byte PNG stub reports plausible
    dimensions — and ingest would then record its digest and replace good art
    with the fragment, which is the failure commit 33487b7 fixed for the cover.
    """
    try:
        size = os.path.getsize(path)
        if size == 0:
            return 'the file is empty'
        with open(path, 'rb') as f:
            head = f.read(12)
            for magic, tail, label, what in _CONTAINER_END:
                if not head.startswith(magic):
                    continue
                if size < len(magic) + len(tail):
                    return f'{label} data is only {size} bytes — truncated'
                f.seek(-len(tail), os.SEEK_END)
                if f.read(len(tail)) != tail:
                    return (f'{label} data ends without {what} '
                            f'({size} bytes) — the file is truncated')
                return None
    except OSError as exc:
        return f'could not be read ({exc.strerror or exc})'
    # WebP carries its payload length in the RIFF header rather than a
    # terminator; dimension parsing already validates the chunk it needs.
    return None


def replace_file(src: str, dest: str) -> None:
    """Copy *src* over *dest* without ever leaving *dest* half-written.

    Copies to a sibling temp file first, then renames. A `shutil.copy2`
    straight onto the destination truncates it on open, so an interrupted copy
    destroys the previous render rather than leaving it intact.
    """
    import shutil
    import tempfile

    dest_dir = os.path.dirname(os.path.abspath(dest)) or '.'
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest_dir, suffix='.part')
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ============================================================================
# Reporting
# ============================================================================

class IllustrationReport(TypedDict):
    """Plan state at a glance."""
    total: int
    by_status: dict[str, int]
    ingested: list[str]
    awaiting_render: list[str]
    next_unrendered: str
    embedded: list[str]
    unembedded: list[str]


def plan_report(project_dir: str) -> IllustrationReport:
    """Summarize plan state, in scene reading order where available."""
    rows = read_plan(project_dir)
    by_status: dict[str, int] = {}
    ingested: list[str] = []
    awaiting: list[str] = []
    for row in rows:
        status = (row.get('status') or 'planned').strip() or 'planned'
        by_status[status] = by_status.get(status, 0) + 1
        if status == 'ingested':
            ingested.append(row['id'].strip())
        elif status != 'superseded':
            awaiting.append(row['id'].strip())

    embedded, unembedded = [], []
    for row in rows:
        if (row.get('status') or '').strip() == 'superseded':
            continue
        rid = row['id'].strip()
        scene_text = _read_scene(project_dir, (row.get('scene_id') or '').strip())
        if scene_text is not None and has_marker(scene_text, rid):
            embedded.append(rid)
        else:
            unembedded.append(rid)

    return {
        'total': len(rows), 'by_status': by_status, 'ingested': ingested,
        'awaiting_render': awaiting,
        # Follows the recommended render order (visual key first), not plan
        # order — the point of the order is that it is what to render next.
        'next_unrendered': next_to_render(project_dir),
        'embedded': embedded, 'unembedded': unembedded,
    }


def _read_scene(project_dir: str, scene_id: str) -> str | None:
    """Read a scene file's text, or None when it doesn't exist."""
    if not scene_id:
        return None
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        return f.read()


# ============================================================================
# Render order
# ============================================================================

def _read_ref_csv(project_dir: str, filename: str) -> list[dict[str, str]]:
    """Read a pipe-delimited CSV from reference/, or [] when absent."""
    path = os.path.join(project_dir, 'reference', filename)
    if not os.path.isfile(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    reader = csv.DictReader(raw.splitlines(), delimiter=DELIMITER)
    return [{k: (v if v is not None else '') for k, v in row.items()
             if k is not None} for row in reader]


def _split_array(value: str) -> list[str]:
    """Split a ``;``-delimited array cell."""
    return [p.strip() for p in (value or '').split(ARRAY_DELIMITER) if p.strip()]


#: Sort key for a scene with no known position — missing from the chapter map,
#: or a scenes.csv row whose `seq` cell is not a number. Both mean "after
#: everything known", never a real position.
_SORTS_LAST = sys.maxsize


def _chapter_sort_key(row: dict[str, str]) -> tuple[int, str]:
    """Order a chapter-map row by its chapter number.

    Falls back to `seq` (the alternate key column assembly supports) and then
    to sorting last, so a malformed row cannot silently reorder the book.
    """
    for column in ('chapter', 'seq', 'number'):
        raw = (row.get(column) or '').strip()
        if raw.isdigit():
            return (int(raw), raw)
    return (_SORTS_LAST, str(row.get('scenes', '')))


def _scene_order(project_dir: str) -> dict[str, int]:
    """Map scene id → reading position, from the chapter map then scenes.csv.

    The chapter map is preferred because it is the production order the book
    actually ships in; scenes.csv `seq` is the fallback for a project that has
    not been chaptered yet.
    """
    order: dict[str, int] = {}
    position = 0

    # Sort by chapter number, not by physical row order. Every other consumer
    # addresses chapters by number — assembly looks up str(chapter_num) and
    # loops range(1, total + 1) — so the book's reading order is numeric
    # regardless of how the rows sit in the file. Trusting row order put the
    # visual key in chapter 3 on an out-of-order map.
    chapter_rows = _read_ref_csv(project_dir, 'chapter-map.csv')
    for row in sorted(chapter_rows, key=_chapter_sort_key):
        for scene_id in _split_array(row.get('scenes', '')):
            if scene_id not in order:
                order[scene_id] = position
                position += 1
    if order:
        return order

    rows = _read_ref_csv(project_dir, 'scenes.csv')
    def seq_of(row: dict[str, str]) -> int:
        raw = (row.get('seq') or '').strip()
        return int(raw) if raw.isdigit() else _SORTS_LAST
    for pos, row in enumerate(sorted(rows, key=seq_of)):
        scene_id = (row.get('id') or '').strip()
        if scene_id:
            order.setdefault(scene_id, pos)
    return order


#: The visual key is picked from the first 1/Nth of the sequence, so that most
#: illustrations can reference it. A short plan still gets a real choice.
VISUAL_KEY_HORIZON_DIVISOR = 3
VISUAL_KEY_MIN_CANDIDATES = 3


def visual_key_horizon(row_count: int) -> int:
    """How many early illustrations the visual key is chosen from.

    Extracted so `packet.anchor_batch` can *name* the horizon when no early row
    fills it. The batch used to report "no illustration names a continuity
    anchor in `canon_refs`" for that shape, which is false whenever a later row
    does — and the horizon, not the plan, is why the slot is empty (#290).
    """
    return max(VISUAL_KEY_MIN_CANDIDATES,
               row_count // VISUAL_KEY_HORIZON_DIVISOR)


PlanStatus = Literal['planned', 'prompted', 'rendered', 'ingested',
                     'superseded']


class RenderStep(TypedDict):
    """One illustration's position in the recommended render order."""
    id: str
    scene_id: str
    is_visual_key: bool
    locks: list[str]
    status: PlanStatus


def render_order(project_dir: str) -> list[RenderStep]:
    """Return the recommended render order, visual key first.

    Two rules, both from how illustrated books are actually produced:

    1. **The visual key renders first.** One early illustration establishes the
       most shared vocabulary at once — the cast, the central location, the
       scale relationship, the palette. Rendering it first means every later
       image has something real to reference instead of a description.
    2. **Everything else goes in story order**, which automatically means each
       entity's design is locked by the earliest image it appears in.

    `locks` names the anchors an illustration is the first to show, so the
    author knows which renders they cannot afford to get wrong.
    """
    rows = [r for r in read_plan(project_dir)
            if (r.get('status') or '').strip() != 'superseded']
    if not rows:
        return []

    order = _scene_order(project_dir)

    def position(row: dict[str, str]) -> int:
        return order.get((row.get('scene_id') or '').strip(),
                         _SORTS_LAST)

    in_story_order = sorted(rows, key=lambda r: (position(r), r['id'].strip()))

    # The visual key is the biggest establisher among the *early*
    # illustrations, not the biggest establisher overall. The climax usually
    # names the most entities — it is where everyone converges — but rendering
    # the payoff first is backwards: the key exists so that everything after it
    # has something real to reference, which only works if most illustrations
    # come after it. Ties break earlier.
    def establishes(row: dict[str, str]) -> int:
        return len(_split_array(row.get('canon_refs', '')))

    candidates = in_story_order[:visual_key_horizon(len(in_story_order))]

    key_id = ''
    if any(establishes(r) for r in candidates):
        key_row = max(candidates, key=lambda r: (establishes(r), -position(r)))
        key_id = key_row['id'].strip()

    sequence = ([r for r in in_story_order if r['id'].strip() == key_id]
                + [r for r in in_story_order if r['id'].strip() != key_id])

    seen: set[str] = set()
    steps: list[RenderStep] = []
    for row in sequence:
        anchors = _split_array(row.get('canon_refs', ''))
        locks = [a for a in anchors if a.lower() not in seen]
        seen.update(a.lower() for a in anchors)
        steps.append({
            'id': row['id'].strip(),
            'scene_id': (row.get('scene_id') or '').strip(),
            'is_visual_key': row['id'].strip() == key_id,
            'locks': locks,
            'status': (row.get('status') or 'planned').strip() or 'planned',
        })
    return steps


def next_to_render(project_dir: str) -> str:
    """The next illustration to render, following the recommended order."""
    for step in render_order(project_dir):
        if step['status'] != 'ingested':
            return step['id']
    return ''


def stale_render_reason(row: dict[str, str], canon_cutoff: str) -> str:
    """Why this row's finished art predates the canon now governing it, or ''.

    **The one staleness predicate for a plan row's own art**, so the parts of a
    run that decide whether art *counts* cannot disagree about it. They did, in
    the same `--package` run: `cmd_illustrate._references_for` excluded all
    twenty of a book's ingested renders as pre-canon and logged twenty WARNING
    lines saying so, while the anchor batch marked four of the same images
    `Rendered: yes` and the packet's README declared phase 1 complete. A session
    working that packet top to bottom would have skipped the anchor batch
    entirely and run the churn against a cover-only reference list — the exact
    failure the two-phase order exists to prevent (#300). Three callers now:
    `_references_for`, `packet.needs_render`, and `packet._entry_for`.

    Reported as a *reason* rather than a bool because the whole point is that it
    is said out loud. An author whose only signal is "needs a re-render" reaches
    for the workaround this replaced — demoting `status` to `prompted`, which
    makes the packet honest and simultaneously drops the row out of the epub,
    the PDF, the web book, and Bookshelf, since `FILED_STATUSES` is what those
    gate on.

    Only `ingested` rows: `rendered` means a file exists that Storyforge has
    never seen, so it carries no `ingested_at` and there is no date to judge —
    the same gate `packet._staging_postdates_render` uses, and for the same
    reason. With no parseable `canon_updated` anywhere, `canon_cutoff` is '' and
    nothing can be judged stale at all.

    Empty and unparseable `ingested_at` are both treated as pre-canon, which is
    the opposite of `resolve_style_reference`'s policy for an unreadable mtime
    and deliberately so: `ingested_at` postdates the plan schema, so "unknown"
    means the render predates even the bookkeeping. The same-day-is-not-stale
    rule lives in `canon.predates_canon`, not here.
    """
    from storyforge import canon
    if not canon_cutoff:
        return ''
    if (row.get('status') or '').strip() != 'ingested':
        return ''
    raw = (row.get('ingested_at') or '').strip()
    if not raw:
        return (f'its `ingested_at` is empty, so it predates ingest '
                f'timestamps and therefore the canon last updated '
                f'{canon_cutoff}')
    ingested = canon.iso_date_or_empty(raw)
    if not ingested:
        return (f'its `ingested_at` ({raw!r}) is not an ISO date, so it '
                f'cannot be shown to postdate the canon last updated '
                f'{canon_cutoff}')
    if canon.predates_canon(when=ingested, cutoff=canon_cutoff):
        return (f'it was ingested {ingested}, before the canon was last '
                f'updated {canon_cutoff}')
    return ''


# ============================================================================
# Validation
# ============================================================================

#: Closed set of finding kinds. Literal + Required split per pages.PageFinding:
#: a typo at an emit site would otherwise become a *blocking* finding, because
#: severity_of defaults anything unrecognized to 'error', and its remediation
#: text in cmd_cleanup would silently fall back to a generic one.
IllustrationFindingKind = Literal[
    'duplicate_id', 'invalid_id', 'unpublishable_id', 'invalid_status',
    'invalid_placement',
    'invalid_layout', 'missing_scene', 'unknown_scene', 'missing_file',
    'missing_digest', 'duplicate_marker', 'orphan_marker', 'marker_lost',
    'anchor_drift', 'anchor_ambiguous', 'orphan_file', 'inline_marker',
    'unembedded_ingested', 'shattered_row', 'direction_anchor_mismatch',
    # The visual-state matrix and the contradiction audit (#278 phase 2).
    # Bare, like every kind above: cmd_cleanup renders `illus_{kind}`.
    'state_unknown_scene', 'state_unmapped_scene', 'evidence_not_found',
    'state_unspecified', 'prose_changed', 'audit_stale',
    # The handoff packet (#278 phase 3).
    'packet_stale', 'anchor_copy_drift',
    # A canon Embeddable block cut short by a `##` heading inside it (#293).
    # Blocking: canon.validate_canon_file reports the same condition per file,
    # but only `cleanup` runs that and `cleanup` gates nothing, so the consumers
    # that actually spend money on a half anchor had nothing to check.
    'canon_anchor_truncated',
]


class _IllustrationFindingRequired(TypedDict):
    """Keys every finding carries. Consumers read both unconditionally."""
    kind: IllustrationFindingKind
    detail: str


class IllustrationFinding(_IllustrationFindingRequired, total=False):
    """One problem with the illustration plan or its markers."""
    id: str        #: every finding except orphan_file
    scene_id: str  #: set when the finding is locatable in a scene
    #: The file the fix belongs in, when that is not the plan CSV or the scene:
    #: orphan_file, missing_file, direction_anchor_mismatch, and the
    #: visual-state kinds, whose fix is an edit to reference/visual-state.csv
    #: even though the finding is *about* a scene.
    file: str


# Findings that make the plan incoherent — the book cannot be published or
# assembled correctly while they stand, so `validate` fails on them.
BLOCKING_FINDINGS: frozenset[IllustrationFindingKind] = frozenset({
    'duplicate_id', 'invalid_id', 'unpublishable_id', 'invalid_status',
    'invalid_placement',
    'invalid_layout', 'missing_scene', 'unknown_scene', 'missing_file',
    'missing_digest', 'duplicate_marker', 'orphan_marker', 'marker_lost',
    # A transition keyed to a scene that no longer exists silently stops
    # applying, and every scene downstream of it resolves to the wrong state.
    # This is the one failure a dense grid could not have, and the price the
    # sparse log pays — so it blocks. Note its sibling `state_unmapped_scene`
    # is only a warning: a scene the chapter map omits still exists, so the
    # transition row is fine and the map is what needs fixing.
    'state_unknown_scene',
    # A half anchor is worse than a missing one: `_warn_unanchored_rows` is loud
    # about an absent anchor, while a truncated one is present, real prose, and
    # silently short — so every prompt accepts it and the set drifts on whatever
    # the dropped tail described. Once art exists the only repair is a
    # re-render, which is what earns a block rather than a warning (#293).
    'canon_anchor_truncated',
})

# Findings that need author attention but leave a valid book. An anchor that
# drifted after a revision is normal in-flight state; a file nobody claims is
# usually a rename in progress.
WARNING_FINDINGS: frozenset[IllustrationFindingKind] = frozenset({
    'anchor_drift', 'anchor_ambiguous', 'orphan_file', 'inline_marker',
    'unembedded_ingested', 'shattered_row', 'direction_anchor_mismatch',
    # Visual state (#278 phase 2). All five leave a publishable book: a
    # transition the chapter map cannot position yet, an evidence quote that
    # drifted, an entity nobody stated, prose revised under a render, and an
    # audit older than the prose are each information the author acts on before
    # paying for art, not a broken manuscript.
    'state_unmapped_scene', 'evidence_not_found', 'state_unspecified',
    'prose_changed', 'audit_stale',
    # The packet (#278 phase 3) is a render, so neither of these leaves a
    # broken book: a stale packet and a hand-edited anchor copy are both one
    # `--package` away. They are still worth reporting, because a stale packet
    # looks exactly like a fresh one to the author working through it, and an
    # anchor copy that no longer matches its canon file quietly breaks the
    # likeness continuity the anchor exists to hold.
    'packet_stale', 'anchor_copy_drift',
})

Severity = Literal['error', 'warning']


def severity_of(kind: IllustrationFindingKind) -> Severity:
    """Return 'error' or 'warning' for a finding kind.

    Anything not explicitly a warning is an error — a kind nobody triaged
    should block rather than pass silently. BLOCKING_FINDINGS is the documented
    other half of the partition; it is kept honest by the partition test rather
    than read here, because reading both would let an unclassified kind fall
    through to neither.
    """
    return 'warning' if kind in WARNING_FINDINGS else 'error'


def truncated_anchor_findings(project_dir: str) -> list[IllustrationFinding]:
    """One `canon_anchor_truncated` finding per canon file with a short block.

    Reported for the whole canon tree rather than only for ids some plan row
    names in `canon_refs`, for two reasons: the three book-level files are never
    named by a row and a truncated `visual-vocabulary` costs every prompt in the
    book, and `_relevant_anchors`' full-set fallback means a row with empty
    `canon_refs` can still receive any anchor.

    Deterministic order (`sorted`) so the cleanup report and `--diagnose` do not
    reshuffle between runs over unchanged canon.
    """
    from storyforge import canon

    findings: list[IllustrationFinding] = []
    for canon_id, truncations in sorted(
            canon.truncated_anchor_ids(project_dir).items()):
        where = ', '.join(
            _csv_safe(t.heading) for t in truncations)
        findings.append({
            'kind': 'canon_anchor_truncated', 'id': canon_id,
            'detail': f'canon `{canon_id}` has a `##` heading inside its '
                      f'Embeddable block ({where}), so the anchor stops above '
                      f'it — every prompt embedding it gets a shorter string '
                      f'than the file appears to hold',
        })
    return findings


def validate_plan(project_dir: str) -> list[IllustrationFinding]:
    """Check the plan, the markers, and the files against each other.

    A planned-but-unrendered row is valid in-flight state, not a finding —
    the same posture as GN page renders (#261). What is reported is genuine
    incoherence: a marker with no row, a row claiming a file that isn't
    there, a file no row claims, an anchor that no longer matches the prose,
    and a marker repeated in one scene.

    Also folds in `visual_state.prepass`, whose findings are about the
    transition log: a transition keyed to a scene that no longer exists, an
    evidence quote the prose no longer contains, and an illustration naming an
    entity whose visible state nobody stated at that point — plus
    `visual_state.digest_drift`, for prose that moved after the audit read it or
    after an illustration was rendered from it.

    And the packet's two checks (#278 phase 3): a packet older than the plan,
    the transition log, or any canon file, and an anchor copy in the written
    packet that no longer matches its canon source. Both return [] when no
    packet has been built, so a project that never runs `--package` sees
    nothing new.
    """
    from storyforge import packet
    from storyforge import visual_state

    findings: list[IllustrationFinding] = []

    # The visual-state pre-pass runs first and unconditionally: two of its three
    # checks are about the transition log alone, and a log can be wrong before a
    # single illustration has been planned.
    findings.extend(visual_state.prepass(project_dir)['findings'])
    findings.extend(visual_state.digest_drift(project_dir))
    findings.extend(packet.packet_stale(project_dir))
    findings.extend(packet.anchor_copy_drift(project_dir))
    # Before the early return below: a truncated anchor matters whether or not
    # a single illustration has been planned yet, and fixing it before the plan
    # exists is the cheapest moment there is.
    findings.extend(truncated_anchor_findings(project_dir))

    rows = read_plan(project_dir)
    if not rows and not os.path.isdir(illustrations_dir(project_dir)):
        # No plan and no ingested files — but the hand-edit safety net still
        # needs to run: a direction document can exist (and drift from
        # canon) before a single illustration has ever been planned.
        findings.extend(_direction_anchor_mismatches(project_dir))
        return findings

    seen_ids: set[str] = set()
    referenced_files: set[str] = set()

    for row in rows:
        rid = (row.get('id') or '').strip()
        scene_id = (row.get('scene_id') or '').strip()

        if rid in seen_ids:
            findings.append({'kind': 'duplicate_id', 'id': rid,
                             'detail': f'illustration id {rid!r} appears more than once'})
            continue
        if asset_key(rid) in {asset_key(s) for s in seen_ids}:
            findings.append({
                'kind': 'duplicate_id', 'id': rid,
                'detail': f'illustration id {rid!r} differs from an earlier row '
                          f'only in case; both would publish as '
                          f'{asset_key(rid)!r}',
            })
            continue
        seen_ids.add(rid)

        if not _ID_RE.match(rid):
            findings.append({'kind': 'invalid_id', 'id': rid,
                             'detail': f'id {rid!r} must start with a letter or digit '
                                       f'and contain only letters, digits, '
                                       f'hyphens, and underscores'})
        elif not _publishable_asset_key(rid):
            findings.append({
                'kind': 'unpublishable_id', 'id': rid,
                'detail': f'id {rid!r} publishes as the asset key '
                          f'{asset_key(rid)!r}, which Bookshelf rejects — a key '
                          f'must start with a lowercase letter or digit and '
                          f'contain only lowercase letters, digits, and hyphens '
                          f'(max {ASSET_KEY_MAX_LENGTH} characters). Rename the '
                          f'row and its scene marker, using hyphens instead of '
                          f'underscores.',
            })

        status = (row.get('status') or '').strip()
        if status and status not in VALID_PLAN_STATUSES:
            findings.append({'kind': 'invalid_status', 'id': rid,
                             'detail': f'status {status!r} is not one of '
                                       f'{sorted(VALID_PLAN_STATUSES)}'})

        placement = (row.get('placement') or '').strip()
        if placement and placement not in VALID_PLACEMENTS:
            findings.append({'kind': 'invalid_placement', 'id': rid,
                             'detail': f'placement {placement!r} is not one of '
                                       f'{sorted(VALID_PLACEMENTS)}'})

        layout = (row.get('layout') or '').strip()
        if layout and layout not in VALID_LAYOUTS:
            findings.append({'kind': 'invalid_layout', 'id': rid,
                             'detail': f'layout {layout!r} is not one of '
                                       f'{sorted(VALID_LAYOUTS)}'})

        if not scene_id:
            findings.append({'kind': 'missing_scene', 'id': rid,
                             'detail': 'no scene_id — the illustration has nowhere to land'})
            continue

        scene_text = _read_scene(project_dir, scene_id)
        if scene_text is None:
            findings.append({'kind': 'unknown_scene', 'id': rid, 'scene_id': scene_id,
                             'detail': f'scene {scene_id!r} has no file in scenes/'})
            continue

        if status == 'superseded':
            continue

        rel = (row.get('asset_file') or '').strip()
        if rel:
            referenced_files.add(os.path.normpath(rel))
        if status in FILED_STATUSES:
            abs_path = asset_path(project_dir, row)
            if not rel:
                findings.append({'kind': 'missing_file', 'id': rid,
                                 'detail': 'status is ingested but asset_file is empty'})
            elif not abs_path or not os.path.isfile(abs_path):
                findings.append({'kind': 'missing_file', 'id': rid, 'file': rel,
                                 'detail': f'status is ingested but {rel} is not on disk'})
            elif not (row.get('sha256') or '').strip():
                findings.append({'kind': 'missing_digest', 'id': rid, 'file': rel,
                                 'detail': 'ingested row has no sha256 — publish needs it'})

        if row.get(_SHATTERED_FLAG):
            findings.append({
                'kind': 'shattered_row', 'id': rid,
                'detail': 'row has more fields than the header — an unescaped '
                          '"|" split it, so columns after that point are '
                          'shifted. Replace the pipe with "/"',
            })

        # An ingested illustration with no marker anywhere is not in-flight
        # state: the art exists and the plan points at it, so the marker was
        # either never embedded or was dropped by a rewrite. Either way the
        # illustration will not appear in the book.
        if status == 'ingested' and rel and not has_marker(scene_text, rid):
            findings.append({
                'kind': 'unembedded_ingested', 'id': rid, 'scene_id': scene_id,
                'detail': f'{rid!r} is ingested but has no marker in '
                          f'{scene_id} — it will not appear in the book. Run '
                          f'`storyforge illustrate --embed`',
            })

        anchor = (row.get('anchor') or '').strip()
        if placement not in ANCHORLESS_PLACEMENTS and anchor:
            match = find_anchor(scene_text, anchor)
            if match is None:
                findings.append({'kind': 'anchor_drift', 'id': rid, 'scene_id': scene_id,
                                 'detail': f'anchor no longer matches scene {scene_id} — '
                                           f'prose was revised; re-anchor the plan row'})
            elif match['count'] > 1:
                findings.append({'kind': 'anchor_ambiguous', 'id': rid, 'scene_id': scene_id,
                                 'detail': f'anchor matches {match["count"]} places in '
                                           f'{scene_id}; lengthen it to a unique phrase'})

    # Markers with no plan row, and repeated markers within one scene.
    scenes_dir = os.path.join(project_dir, 'scenes')
    if os.path.isdir(scenes_dir):
        for name in sorted(os.listdir(scenes_dir)):
            if not name.endswith('.md'):
                continue
            with open(os.path.join(scenes_dir, name), encoding='utf-8') as f:
                text = f.read()
            for mid in sorted(set(inline_marker_ids(text))):
                findings.append({
                    'kind': 'inline_marker', 'id': mid, 'scene_id': name[:-3],
                    'detail': f'marker for {mid!r} in {name} is mid-paragraph, '
                              f'not on its own line. Illustrations land at '
                              f'paragraph boundaries, so it is dropped from '
                              f'every output — run --embed instead of placing '
                              f'it by hand',
                })

            ids = all_marker_ids(text)
            for mid in sorted(set(ids)):
                if ids.count(mid) > 1:
                    findings.append({
                        'kind': 'duplicate_marker', 'id': mid,
                        'scene_id': name[:-3],
                        'detail': f'marker for {mid!r} appears {ids.count(mid)} '
                                  f'times in {name}',
                    })
                if mid not in seen_ids:
                    findings.append({
                        'kind': 'orphan_marker', 'id': mid, 'scene_id': name[:-3],
                        'detail': f'{name} marks {mid!r} but the plan has no such row',
                    })

    # Files no plan row claims.
    ill_dir = illustrations_dir(project_dir)
    if os.path.isdir(ill_dir):
        for name in sorted(os.listdir(ill_dir)):
            path = os.path.join(ill_dir, name)
            if not os.path.isfile(path) or not is_supported_image(path):
                continue
            rel = os.path.normpath(os.path.join(ILLUSTRATIONS_SUBDIR, name))
            if rel not in referenced_files:
                findings.append({
                    'kind': 'orphan_file', 'file': rel,
                    'detail': f'{rel} is not referenced by any plan row',
                })

    findings.extend(_direction_anchor_mismatches(project_dir))

    return findings


def _direction_anchor_mismatches(project_dir: str) -> list[IllustrationFinding]:
    """Compare canon anchors against a still-present direction document.

    A one-time safety net for the hand-edit off illustration-direction.md.
    The unrecoverable mistake is an anchor whose text changed: every
    illustration already rendered from the old string is invalidated, and
    nothing else in the pipeline would notice. Goes silent once the old
    document is deleted, which is the intended end state.

    The direction document's anchors are `### Name` subsections written by a
    human (e.g. "Great Lamp"); canon ids are slugs (e.g. "great-lamp"). An
    exact-key lookup between the two would match nothing, so the heading is
    slugified with the same function `append_anchor_stubs` uses to derive a
    canon id from a proposed anchor name — one slug function, not two.
    """
    from storyforge import canon
    from storyforge.common import normalize_for_comparison
    from storyforge.prompts_illustrate import _slugify

    if not os.path.isfile(direction_path(project_dir)):
        return []
    sections = read_direction(project_dir)
    anchors_heading = find_section(sections, ANCHORS_SECTION)
    anchors_body = sections.get(anchors_heading, '') if anchors_heading else ''
    if not anchors_body:
        return []

    old: dict[str, str] = {}
    current_name: str | None = None
    buffer: list[str] = []
    for line in anchors_body.splitlines():
        heading = re.match(r'^###\s+(.+?)\s*$', line)
        if heading:
            if current_name is not None:
                old[current_name] = '\n'.join(buffer).strip()
            current_name = heading.group(1).strip()
            buffer = []
        elif current_name is not None:
            buffer.append(line)
    if current_name is not None:
        old[current_name] = '\n'.join(buffer).strip()

    findings: list[IllustrationFinding] = []
    new = canon.anchor_texts(project_dir)
    for name, old_text in sorted(old.items()):
        canon_id = _slugify(name)
        # No matching canon id — including a canon file that exists but is
        # still a placeholder, which anchor_texts already excludes — is
        # skipped, not reported. Mid-hand-edit is normal in-flight state,
        # and the author decides which anchors survive.
        new_text = new.get(canon_id)
        if new_text is None:
            continue
        if normalize_for_comparison(old_text) != normalize_for_comparison(new_text):
            # cmd_cleanup._write_report emits findings as unquoted
            # pipe-delimited CSV, one row per newline — the same reason
            # 'shattered_row' exists as a finding kind for the plan CSV
            # itself. old_text/new_text are author-written anchor prose and
            # may contain either character, so both must be flattened to a
            # single physical line with no '|' before they reach `detail`.
            old_flat = _csv_safe(old_text)
            new_flat = _csv_safe(new_text)
            findings.append({
                'kind': 'direction_anchor_mismatch',
                'id': canon_id,
                'file': f'reference/{DIRECTION_FILENAME}',
                'detail': (
                    f'canon anchor for `{canon_id}` differs from the '
                    f'### {_csv_safe(name)} section in '
                    f'reference/{DIRECTION_FILENAME} — direction doc: '
                    f'"{old_flat}" / canon file: "{new_flat}" — every '
                    f'illustration already rendered from the old text is '
                    f'invalidated if this change was unintentional'
                ),
            })
    return findings


def _csv_safe(text: str) -> str:
    """Collapse *text* onto one physical line with no `|`.

    Retained as the illustration-side name for `common.csv_safe`, which is
    where the implementation now lives so `canon` can reach it too (see that
    docstring for why a stray `|` silences the finding it appears in).
    """
    from storyforge.common import csv_safe
    return csv_safe(text)


# ============================================================================
# Selection pre-pass
# ============================================================================

class PrepassFindings(TypedDict):
    """Deterministic candidates and gaps, computed before any LLM call."""
    planned_count: int
    scene_count: int
    chapter_count: int
    recommended_count: int
    uncovered_spine_events: list[dict[str, str]]
    turning_point_scenes: list[dict[str, str]]
    motif_payoffs: list[dict[str, str]]
    motif_singletons: list[str]
    uncovered_chapters: list[str]
    clustered_chapters: list[str]
    covered_scenes: list[str]


def selection_prepass(project_dir: str) -> PrepassFindings:
    """Compute illustration candidates and coverage gaps deterministically.

    Everything here is cheap and repeatable. The LLM pass receives these
    findings and argues against them, which is what keeps a proposed
    illustration list anchored to the story's actual structure instead of
    whichever scenes happened to read vividly.
    """
    plan = read_plan(project_dir)
    covered_scenes = {(r.get('scene_id') or '').strip() for r in plan
                      if (r.get('status') or '').strip() != 'superseded'}
    covered_scenes.discard('')

    scenes = _read_ref_csv(project_dir, 'scenes.csv')
    architecture = _read_ref_csv(project_dir, 'architecture.csv')
    spine = _read_ref_csv(project_dir, 'spine.csv')
    intent = _read_ref_csv(project_dir, 'scene-intent.csv')
    motifs = _read_ref_csv(project_dir, 'motif-taxonomy.csv')
    chapter_map = _read_ref_csv(project_dir, 'chapter-map.csv')

    arch_by_id = {r.get('id', '').strip(): r for r in architecture}
    scene_to_arch = {r.get('id', '').strip(): (r.get('architecture_scene') or '').strip()
                     for r in scenes}

    # Spine events with no illustrated scene tracing back to them.
    covered_spine: set[str] = set()
    for scene_id in covered_scenes:
        arch_id = scene_to_arch.get(scene_id, '')
        event = (arch_by_id.get(arch_id, {}).get('spine_event') or '').strip()
        if event:
            covered_spine.add(event)
    uncovered_spine = [
        {'id': r.get('id', '').strip(), 'title': r.get('title', '').strip(),
         'summary': r.get('summary', '').strip()}
        for r in spine
        if r.get('id', '').strip() and r.get('id', '').strip() not in covered_spine
    ]

    # Architecture rows carrying a turning point or a value shift.
    turning = []
    for r in architecture:
        tp = (r.get('turning_point') or '').strip()
        shift = (r.get('value_shift') or '').strip()
        if not tp and not shift:
            continue
        turning.append({
            'architecture_scene': r.get('id', '').strip(),
            'title': r.get('title', '').strip(),
            'turning_point': tp, 'value_shift': shift,
            'summary': r.get('summary', '').strip(),
        })

    # Motif appearances across scenes, from scene-intent theme/motif threads
    # plus scene-briefs motifs.
    briefs = _read_ref_csv(project_dir, 'scene-briefs.csv')
    motif_scenes: dict[str, list[str]] = {}
    for r in briefs:
        sid = r.get('id', '').strip()
        for motif in _split_array(r.get('motifs', '')):
            motif_scenes.setdefault(motif.lower(), []).append(sid)

    known_motifs = {(r.get('name') or r.get('id') or '').strip().lower()
                    for r in motifs}
    known_motifs.discard('')

    motif_payoffs = []
    motif_singletons = []
    for motif, sids in sorted(motif_scenes.items()):
        if len(sids) == 1:
            motif_singletons.append(motif)
        elif len(sids) >= 3:
            # The third and later appearance is where a motif pays off; an
            # illustration there lands on accumulated meaning.
            motif_payoffs.append({
                'motif': motif, 'appearances': str(len(sids)),
                'payoff_scene': sids[2],
                'all_scenes': ARRAY_DELIMITER.join(sids),
            })
    for motif in sorted(known_motifs - set(motif_scenes)):
        motif_singletons.append(motif)

    # Chapter distribution.
    chapter_of: dict[str, str] = {}
    for r in chapter_map:
        chapter = (r.get('chapter') or r.get('number') or '').strip()
        for sid in _split_array(r.get('scenes', '')):
            chapter_of[sid] = chapter
    per_chapter: dict[str, int] = {}
    for sid in covered_scenes:
        chapter = chapter_of.get(sid, '')
        if chapter:
            per_chapter[chapter] = per_chapter.get(chapter, 0) + 1
    all_chapters = [c for c in dict.fromkeys(chapter_of.values()) if c]
    uncovered_chapters = [c for c in all_chapters if not per_chapter.get(c)]
    clustered = [c for c, n in sorted(per_chapter.items()) if n >= 3]

    chapter_count = len(all_chapters)
    scene_count = len([r for r in scenes if r.get('id', '').strip()])
    recommended = _recommend_count(chapter_count, len(spine), scene_count)

    # Largest emotional swings, as a tiebreaker signal for the LLM.
    intent_by_id = {r.get('id', '').strip(): r for r in intent}
    for row in turning:
        arch_id = row['architecture_scene']
        for sid, mapped in scene_to_arch.items():
            if mapped == arch_id and sid in intent_by_id:
                row['emotional_arc'] = (
                    intent_by_id[sid].get('emotional_arc') or '').strip()
                row['scene_id'] = sid
                break

    return {
        'planned_count': len([r for r in plan
                              if (r.get('status') or '').strip() != 'superseded']),
        'scene_count': scene_count,
        'chapter_count': chapter_count,
        'recommended_count': recommended,
        'uncovered_spine_events': uncovered_spine,
        'turning_point_scenes': turning,
        'motif_payoffs': motif_payoffs,
        'motif_singletons': motif_singletons,
        'uncovered_chapters': uncovered_chapters,
        'clustered_chapters': clustered,
        'covered_scenes': sorted(covered_scenes),
    }


def _recommend_count(chapter_count: int, spine_count: int,
                     scene_count: int) -> int:
    """Recommend how many illustrations a book of this size supports.

    Roughly one every two or three chapters, floored at the spine's own
    event count when the book is short, and capped so the art stays an
    accent rather than a parallel narrative.
    """
    if chapter_count <= 0 and scene_count <= 0:
        return 0
    from_chapters = round(chapter_count / 2.5) if chapter_count else 0
    baseline = max(from_chapters, min(spine_count, 8), 3)
    ceiling = max(3, chapter_count) if chapter_count else 12
    return int(min(baseline, ceiling, 30))


def prepass_is_empty(findings: PrepassFindings) -> bool:
    """True when the pre-pass surfaced nothing worth spending a call on."""
    return not any((
        findings['uncovered_spine_events'],
        findings['turning_point_scenes'],
        findings['motif_payoffs'],
        findings['uncovered_chapters'],
    ))
