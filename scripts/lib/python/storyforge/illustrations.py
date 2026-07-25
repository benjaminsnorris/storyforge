"""Interior illustration plan, markers, and resolution.

Prose books can carry interior illustrations. This module owns the data and
mechanics behind them:

  - ``reference/illustration-plan.csv`` — one row per illustration, holding
    the narrative justification, the art-direction fields, and (after ingest)
    the file digest and dimensions.
  - The scene marker ``![[illus:{id}]]`` — a single line in ``scenes/{id}.md``
    marking where the illustration lands in the prose.
  - Resolution — one marker, three output targets (epub/PDF, web book,
    Bookshelf publish manifest), each rendering it its own way.

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
from html.parser import HTMLParser
from typing import Callable, TypedDict

DELIMITER = '|'
ARRAY_DELIMITER = ';'

PLAN_FILENAME = 'illustration-plan.csv'

PLAN_COLUMNS: list[str] = [
    'id', 'scene_id', 'anchor', 'placement', 'beat', 'rationale',
    'subject', 'composition', 'palette', 'mood', 'motifs', 'canon_refs',
    'status', 'asset_file', 'prompt_file', 'sha256', 'width', 'height',
]

# Placement is relative to the *paragraph* containing the anchor, not to the
# anchor's character offset — an illustration never splits a paragraph.
VALID_PLACEMENTS = frozenset({
    'before_anchor', 'after_anchor', 'scene_open', 'scene_close',
})

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

_ID_RE = re.compile(r'\A[a-z0-9][a-z0-9-]*\Z')

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


# ============================================================================
# Paths
# ============================================================================

def plan_path(project_dir: str) -> str:
    """Path to the illustration plan CSV."""
    return os.path.join(project_dir, 'reference', PLAN_FILENAME)


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
        clean = {k: (v if v is not None else '') for k, v in row.items()
                 if k is not None}
        if (clean.get('id') or '').strip():
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


def write_plan(project_dir: str, rows: list[dict[str, str]]) -> str:
    """Write the illustration plan, preserving PLAN_COLUMNS order."""
    path = plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS,
                                delimiter=DELIMITER, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, '') for col in PLAN_COLUMNS})
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
    by_id = {r['id'].strip(): dict(r) for r in existing if r.get('id', '').strip()}
    order = [r['id'].strip() for r in existing if r.get('id', '').strip()]
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


def has_marker(text: str, illus_id: str) -> bool:
    """True when *text* already carries the marker for *illus_id*."""
    return illus_id in marker_ids(text)


def strip_markers(text: str) -> str:
    """Remove every illustration marker from *text*.

    Own-line markers are removed with their line; inline markers are removed
    in place. Runs of blank lines left behind collapse back to one, so the
    stripped text is what the prose would have been before the marker landed.

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
    return out


def count_prose_words(text: str) -> int:
    """Word count for scene text, excluding illustration markers."""
    return len(strip_markers(text).split())


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

    body = scene_text.rstrip('\n')

    if placement == 'scene_open':
        return {'text': f'{marker}\n\n{body}\n', 'changed': True, 'error': ''}
    if placement == 'scene_close':
        return {'text': f'{body}\n\n{marker}\n', 'changed': True, 'error': ''}

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
    return {'text': '\n\n'.join(parts) + '\n', 'changed': True, 'error': ''}


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

    return MARKER_LINE_RE.sub(repl, scene_text)


def resolve_for_local(project_dir: str, scene_text: str,
                      relative_to: str | None = None) -> str:
    """Resolve markers to on-disk image paths for epub/PDF assembly.

    Only rows whose file actually exists resolve; a planned-but-unrendered
    illustration drops out, so assembly of an in-flight book still succeeds.
    """
    plan = read_plan_as_map(project_dir)
    if not plan:
        return strip_markers(scene_text)

    def path_for(illus_id: str, row: dict[str, str]) -> str | None:
        abs_path = asset_path(project_dir, row)
        if not abs_path or not os.path.isfile(abs_path):
            return None
        if relative_to:
            return os.path.relpath(abs_path, relative_to)
        return abs_path

    return resolve_to_markdown(scene_text, plan, path_for)


class ScenePlacement(TypedDict):
    """An illustration's position inside one scene's converted HTML."""
    key: str
    after_paragraph: int


class _TopLevelParagraphCounter(HTMLParser):
    """Count ``<p>`` elements at the top level of a fragment.

    Nesting depth is tracked so a paragraph inside a ``<blockquote>`` does not
    count. That matches how the reader composes: it walks the scene
    container's direct children and inserts a figure after the Nth top-level
    paragraph, so a nested paragraph is not a placement boundary there either.
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

    This is the contract the Bookshelf reader consumes
    (benjaminsnorris/bookshelf#12): place the figure after the Nth top-level
    paragraph of the scene, counting from zero.
    """
    placements: list[ScenePlacement] = []
    for hit in find_markers(scene_md):
        prefix = strip_markers(scene_md[:hit['start']])
        if not prefix.strip():
            placements.append({'key': hit['id'], 'after_paragraph': 0})
            continue
        placements.append({
            'key': hit['id'],
            'after_paragraph': count_top_level_paragraphs(md_to_html(prefix)),
        })
    return placements


class ManifestAsset(TypedDict, total=False):
    """One asset entry for the Bookshelf publish manifest."""
    key: str
    role: str
    sha256: str
    extension: str
    width: int
    height: int
    alt_text: str


def manifest_assets(project_dir: str,
                    used_keys: set[str] | None = None) -> list[ManifestAsset]:
    """Build the manifest ``assets`` array from ingested plan rows.

    Metadata only — no bytes. Rows without a digest are skipped: the publish
    contract is content-addressed, so an asset with no sha256 has nowhere to
    live (see benjaminsnorris/bookshelf#11).
    """
    assets: list[ManifestAsset] = []
    for row in read_plan(project_dir):
        key = row['id'].strip()
        if used_keys is not None and key not in used_keys:
            continue
        if row.get('status', '').strip() != 'ingested':
            continue
        digest = (row.get('sha256') or '').strip()
        if not digest:
            continue
        rel = (row.get('asset_file') or '').strip()
        ext = os.path.splitext(rel)[1].lstrip('.').lower() or 'png'
        asset: ManifestAsset = {
            'key': key, 'role': 'illustration',
            'sha256': digest, 'extension': ext,
        }
        for field in ('width', 'height'):
            val = (row.get(field) or '').strip()
            if val.isdigit():
                asset[field] = int(val)  # type: ignore[literal-required]
        alt = (row.get('beat') or '').strip()
        if alt:
            asset['alt_text'] = alt
        assets.append(asset)
    return assets


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
        bits = int.from_bytes(data[1:5], 'little')
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return (w, h)
    return None


def is_supported_image(path: str) -> bool:
    """True when the extension is one the publish pipeline accepts."""
    return os.path.splitext(path)[1].lower() in VALID_IMAGE_EXTENSIONS


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
        'next_unrendered': awaiting[0] if awaiting else '',
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
# Validation
# ============================================================================

class IllustrationFinding(TypedDict, total=False):
    """One problem with the illustration plan or its markers."""
    kind: str
    id: str
    scene_id: str
    detail: str
    file: str


# Findings that make the plan incoherent — the book cannot be published or
# assembled correctly while they stand, so `validate` fails on them.
BLOCKING_FINDINGS: frozenset[str] = frozenset({
    'duplicate_id', 'invalid_id', 'invalid_status', 'invalid_placement',
    'missing_scene', 'unknown_scene', 'missing_file', 'missing_digest',
    'duplicate_marker', 'orphan_marker',
})

# Findings that need author attention but leave a valid book. An anchor that
# drifted after a revision is normal in-flight state; a file nobody claims is
# usually a rename in progress.
WARNING_FINDINGS: frozenset[str] = frozenset({
    'anchor_drift', 'anchor_ambiguous', 'orphan_file',
})


def severity_of(kind: str) -> str:
    """Return 'error' or 'warning' for a finding kind."""
    return 'warning' if kind in WARNING_FINDINGS else 'error'


def validate_plan(project_dir: str) -> list[IllustrationFinding]:
    """Check the plan, the markers, and the files against each other.

    A planned-but-unrendered row is valid in-flight state, not a finding —
    the same posture as GN page renders (#261). What is reported is genuine
    incoherence: a marker with no row, a row claiming a file that isn't
    there, a file no row claims, an anchor that no longer matches the prose,
    and a marker repeated in one scene.
    """
    findings: list[IllustrationFinding] = []
    rows = read_plan(project_dir)
    if not rows and not os.path.isdir(illustrations_dir(project_dir)):
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
        seen_ids.add(rid)

        if not _ID_RE.match(rid):
            findings.append({'kind': 'invalid_id', 'id': rid,
                             'detail': f'id {rid!r} is not a lowercase kebab-case slug'})

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
            ids = marker_ids(text)
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

    return findings


# ============================================================================
# Selection pre-pass
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
