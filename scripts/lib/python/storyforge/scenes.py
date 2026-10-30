"""Scene setup utilities — parsing, splitting, renaming, CSV generation.

Replaces the data-heavy functions from ``scripts/storyforge-scenes-setup``
(1307 lines, 33 sed calls) with clean Python equivalents. The bash script
handles file operations, git, and Claude invocations; this module provides
the parsing and data-transformation layer.
"""

import json
import os
import re
import sys


# ============================================================================
# Slug generation
# ============================================================================

def generate_slug(title: str) -> str:
    """Convert a scene title to a filename-safe slug.

    Matches the bash ``slugify()`` function exactly:
    lowercase, spaces to hyphens, strip special chars, collapse hyphens,
    strip leading ``the-``, truncate to 50 chars.

    Args:
        title: Human-readable scene title.

    Returns:
        A slug suitable for use as a scene filename (without extension).
    """
    slug = title.lower()

    # Replace em-dashes, en-dashes with hyphens; remove ellipses
    slug = slug.replace('\u2014', '-').replace('\u2013', '-')
    slug = slug.replace('...', '')

    # Remove special chars: quotes, colons, parentheses, commas, periods,
    # semicolons, exclamation, question marks, backticks
    slug = re.sub(r'''["'`():;,.!?]''', '', slug)

    # Replace spaces, underscores, and slashes with hyphens
    slug = re.sub(r'[\s_/]', '-', slug)

    # Remove any remaining non-alphanumeric chars except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)

    # Collapse multiple hyphens
    slug = re.sub(r'-{2,}', '-', slug)

    # Strip leading/trailing hyphens
    slug = slug.strip('-')

    # Strip leading "the-"
    if slug.startswith('the-'):
        slug = slug[4:]

    # Truncate to 50 chars and strip any trailing hyphen after truncation
    slug = slug[:50].rstrip('-')

    return slug


# The scene-id rule, shared by the schema, validation and every prompt that
# mints ids. An id is permanent; order lives in seq.
SCENE_ID_RULE = (
    "A scene id is a 3-5 word lowercase hyphenated slug naming the scene's core "
    "event (e.g., gatsby-reunites-with-daisy). It is permanent: never encode the "
    "scene's position (no act1-sc03, scene-12, ch3-2), and never rename an id when "
    "a scene moves or its title changes. Order lives in seq."
)

_POSITION_WORDS = frozenset('act part ch chapter sc scene s book'.split())
_NUMERAL = re.compile(r'^(\d+|[ivxlc]+)$')
_POSITIONAL_TOKEN = re.compile(r'^(act|part|ch|chapter|sc|scene|s|book)\d+$')


def scene_id_problems(scene_id: str) -> list[str]:
    """Ways a scene id breaks SCENE_ID_RULE; empty if it follows it."""
    tokens = [t for t in scene_id.lower().split('-') if t]
    problems = []
    positional = any(_POSITIONAL_TOKEN.match(t) for t in tokens) or any(
        a in _POSITION_WORDS and _NUMERAL.match(b) for a, b in zip(tokens, tokens[1:]))
    if positional or (tokens and all(_NUMERAL.match(t) or t in _POSITION_WORDS for t in tokens)):
        problems.append('positional')
    if not 3 <= len(tokens) <= 5:
        problems.append(f'{len(tokens)} words (want 3-5)')
    return problems


# A scene-break line: three or more of one break character, optionally
# spaced ("***", "* * *", "# # #", "~~~", and the long dash rules of
# Project Gutenberg texts). Markdown headings are excluded by requiring the
# whole line to be break characters.
_BREAK_MARKER = re.compile(r'^\s*([*\-_#~•·—])(\s*\1){2,}\s*$')


def is_break_marker(line: str) -> bool:
    """True if the line is a scene-break marker."""
    return bool(_BREAK_MARKER.match(line))


_TRAILING_STOPWORDS = frozenset(
    'a an and as at by for from in into of on or the to while with'.split())


def scene_id_slug(text: str, max_words: int = 5) -> str:
    """Slug for a scene id: at most max_words words naming the scene's event.

    Scene ids are permanent and describe what happens, never where the scene
    sits: order lives in seq, so a scene can move without its id lying.
    """
    words = [w for w in generate_slug(text).split('-') if w][:max_words]
    # Truncation can strand a function word ("gatsby-is-shot-in-the")
    while len(words) > 1 and words[-1] in _TRAILING_STOPWORDS:
        words.pop()
    return '-'.join(words)


def _one_word_apart(a: list[str], b: list[str]) -> bool:
    """True if word lists *a* and *b* differ by one word changed, added or
    dropped. A changed word counts only in ids of four words or more: in three
    it is a third of the id ("laura-visits-ladyship" is not "laura-visits-lady")."""
    if len(a) == len(b):
        return len(a) >= 4 and sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    if len(long_) - len(short) != 1:
        return False
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def match_scene_id(reply_id: str, ids) -> str | None:
    """The scene id in *ids* a model's *reply_id* means, or None.

    An exact id wins. Otherwise the one id the reply extends or cuts short
    at a hyphen, else the one id a word apart (changed, added or dropped):
    Gatsby's "tom-drives-accident" for "tom-drives-toward-accident". A reply
    that could mean two scenes matches neither.
    """
    if reply_id in ids:
        return reply_id
    prefix = [i for i in ids if reply_id.startswith(i + '-') or i.startswith(reply_id + '-')]
    if prefix:
        return prefix[0] if len(prefix) == 1 else None
    words = reply_id.split('-')
    near = [i for i in ids if _one_word_apart(words, i.split('-'))]
    return near[0] if len(near) == 1 else None


def unique_slug(base_slug: str, used: set[str]) -> str:
    """Return a unique slug, appending ``-2``, ``-3``, etc. if needed.

    The *used* set is updated in-place with the returned slug.

    Args:
        base_slug: The desired slug.
        used: Set of slugs already in use.

    Returns:
        A slug guaranteed not to collide with *used*.
    """
    candidate = base_slug
    counter = 2
    while candidate in used:
        candidate = f'{base_slug}-{counter}'
        counter += 1
    used.add(candidate)
    return candidate


# ============================================================================
# Scene boundary response parsing
# ============================================================================

def parse_scene_boundaries(response: str) -> list[dict]:
    """Parse Claude's scene-boundary detection response.

    Expects lines of the form::

        SCENE: <line_number> | <suggested_title> | <brief_reason>

    The parser is forgiving of whitespace and minor formatting variations
    (e.g. missing reason, extra spaces around pipes).

    Args:
        response: The full text response from Claude.

    Returns:
        List of dicts with keys ``line_number`` (int), ``title`` (str),
        and ``description`` (str).  Sorted by line_number ascending.
    """
    scenes: list[dict] = []

    for line in response.splitlines():
        line = line.strip()
        if not line.upper().startswith('SCENE:'):
            continue

        # Strip the SCENE: prefix (case-insensitive)
        raw = re.sub(r'^SCENE:\s*', '', line, flags=re.IGNORECASE)
        parts = raw.split('|')

        line_num_str = parts[0].strip() if parts else ''
        # Accept only valid integers
        if not re.fullmatch(r'\d+', line_num_str):
            continue

        title = parts[1].strip() if len(parts) > 1 else ''
        description = '|'.join(parts[2:]).strip() if len(parts) > 2 else ''

        scenes.append({
            'line_number': int(line_num_str),
            'title': title,
            'description': description,
        })

    scenes.sort(key=lambda s: s['line_number'])
    return scenes


# ============================================================================
# Epigraphs
# ============================================================================

# An epigraph is short: Middlemarch's longest runs to about 120 words.
_EPIGRAPH_MAX_WORDS = 200
_EPIGRAPH_MAX_PARAGRAPHS = 4

# Words that open a verse line but, capitalized after a lowercase word or a
# comma, almost never occur mid-sentence in prose. Joined verse ("a name Rose
# on their souls ... there As thrill the buds ... frame At penetration") is
# full of them; "I" and names are left out because prose has those too.
_VERSE_LINE_OPENERS = frozenset('''
    a an and as at but by for from had has have he her his how if in into is it
    its like my nor not now o of oh on or our she so than that the thee their
    them then there these they thine this those thou thy till to toward towards
    upon was we were what when where which while who whose why with ye yet you
    your
'''.split())
_VERSE_LINE_OPENER_RE = re.compile(r"[a-z,;]\s+([A-Z][a-z]*)\b")
_MIN_VERSE_OPENERS = 3

# An attribution after a dash at the end of the epigraph: "—Scott",
# "—_The Maid’s Tragedy:_ BEAUMONT AND FLETCHER.", "—_Purgatorio_, vii."
_DASH_ATTRIBUTION_RE = re.compile(r'(?:^|[\s.,;:!?"”’\'_*)\]])[—―–]+\s*([^—―–]{1,80})$')
_NAME_PARTICLES = frozenset('of the and for de da di du la le van von in a an on to'.split())
# A numbered speaker tag opening a quotation from a play: "1_st Gent_.",
# "2_d Gent_." (a bare "_Monday_." could open a diary entry, so it doesn't count).
_SPEAKER_TAG_RE = re.compile(r'^[“"]?\d_[a-z]{1,2} [A-Z][^_\n]{0,20}_\.\s')
# An italic title cited after a dash, with at most a book or canto number:
# "—_Measure for Measure_.", "—_Purgatorio_, vii."
_ITALIC_TITLE_RE = re.compile(r'^([_*])[A-Z][^_*\n]*\1[\s.,;:]*(?:[ivxlcdm]+|\d+)?[.,;:]?$',
                              re.IGNORECASE)
# A letter, not an epigraph: "Dear Hugh", "My dear Sir,", "Madam,".
_SALUTATION_RE = re.compile(r'^[“"]?(?:my\s+)?(?:dear(?:est)?\b|sir\b|madam\b|gentlemen\b)',
                            re.IGNORECASE)
# A document's italic head, not an epigraph: "_Telegram, Van Helsing, to
# Seward._", "_Letter from Mina to Lucy._", "_3 May. Bistritz._", "_Journal._"
_DOCUMENT_HEAD_RE = re.compile(
    r'^[“"]?[_*](?:[^_*\n]*\d|(?:letter|telegram|note|memorandum|memo|diary|journal'
    r'|postscript|enclosure|card|cablegram|wire|dispatch|despatch|report)\b)',
    re.IGNORECASE)
# A signature of initials only: "J.", "J. M.", "J.M.W."
_INITIALS_RE = re.compile(r'^(?:[A-Z]\.\s*)+$')


def _is_attribution(tail: str) -> bool:
    """Whether ``tail`` reads as a source's name rather than prose: an
    italic title, every word capitalized (bar particles such as "of" and
    "the"), or an all-caps name somewhere in it."""
    tail = tail.strip()
    if _ITALIC_TITLE_RE.match(tail) and tail[1].isupper():
        return True
    # Speech cut off at a name ends in a quote mark or "!"/"?"; a source
    # cited after the quotation doesn't.
    if re.search(r'[”"’!?]$', tail):
        return False
    # A note signed with an initial: "—J."
    if _INITIALS_RE.match(tail):
        return False
    words = re.findall(r"[^\W\d_][\w’'.-]*", tail)
    if not words or len(words) > 12 or words[0].lower().startswith('your'):
        return False
    if any(len(w) >= 3 and w.isupper() for w in words):
        return True
    return all(w[0].isupper() or w.lower() in _NAME_PARTICLES for w in words)


def _dash_attribution(paragraph: str) -> bool:
    m = _DASH_ATTRIBUTION_RE.search(paragraph.strip())
    return bool(m) and _is_attribution(m.group(1))


def _caps_line(paragraph: str) -> bool:
    """A paragraph that is one line of capitals: "SIR WALTER SCOTT"."""
    text = paragraph.strip()
    letters = re.sub(r'[^A-Za-z]', '', text)
    return ('\n' not in text and len(letters) >= 3 and letters.isupper()
            and len(text.split()) <= 8)


def _is_verse(paragraph: str) -> bool:
    """Verse lines kept as lines, or verse whose line breaks were joined
    into one paragraph (Project Gutenberg texts often are)."""
    lines = [ln.strip() for ln in paragraph.strip().splitlines() if ln.strip()]
    # Verse lines: short, each opening on a capital, and at least one running
    # on past its line end (hard-wrapped prose opens lines in lower case;
    # one sentence per line ends each in a full stop).
    # A dateline or a list of names ("Netherfield Park / Hertfordshire /
    # Thursday") has short capitalized lines too, but no punctuation in them.
    if (len(lines) >= 2 and all(len(ln) <= 60 for ln in lines)
            and all(re.match(r'[^\w]*[A-Z]', ln) for ln in lines)
            and any(re.search(r'[\w,;:]$', ln) for ln in lines[:-1])
            and re.search(r'[,;:!?]', paragraph)):
        return True
    openers = [w for w in _VERSE_LINE_OPENER_RE.findall(paragraph)
               if w.lower() in _VERSE_LINE_OPENERS]
    return len(openers) >= _MIN_VERSE_OPENERS


def is_epigraph_block(text: str) -> bool:
    """Whether ``text`` holds nothing but an epigraph (plus any heading).

    An epigraph is a short block before a chapter's first prose paragraph:
    a quotation closed by a dash attribution ("—Scott"), verse over a line
    of capitals ("SIR WALTER SCOTT"), a speech quoted from a play
    ("1_st Gent_. ..."), or verse with no attribution at all.

    Not one: short prose or dialogue; an epigraph followed by prose; a
    letter that opens with a salutation ("Dear Hugh"); a document under an
    italic head ("_Telegram, ... to Seward._", "_3 May. Bistritz._"); a
    note signed with initials ("—J."); prose over a line of capitals (a
    signed telegram); a dateline or list of names. Verse a character recites
    with no attribution still reads as an epigraph: a known trade-off.
    Letters with no salutation and no head are not recognized.
    """
    body = [ln for ln in text.splitlines()
            if not ln.strip().startswith('#') and not is_break_marker(ln.strip())]
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', '\n'.join(body)) if p.strip()]
    if not paragraphs or len(paragraphs) > _EPIGRAPH_MAX_PARAGRAPHS:
        return False
    if sum(len(p.split()) for p in paragraphs) > _EPIGRAPH_MAX_WORDS:
        return False
    if _SALUTATION_RE.match(paragraphs[0]) or _DOCUMENT_HEAD_RE.match(paragraphs[0]):
        return False
    *quote, last = paragraphs
    if _dash_attribution(last):
        # A signature on a paragraph of its own under prose is a signed
        # message; an epigraph's source there sits under verse.
        if quote and _DASH_ATTRIBUTION_RE.fullmatch(last):
            return len(quote) <= 2 and all(_is_verse(p) for p in quote)
        return len(quote) <= 2
    if _caps_line(last) and quote:
        return all(_is_verse(p) for p in quote)
    if _SPEAKER_TAG_RE.match(paragraphs[0]) and len(paragraphs) <= 2:
        return True
    return all(_is_verse(p) for p in paragraphs)


def keep_epigraph_with_opening(chapter_text: str,
                               splits: list[dict]) -> tuple[list[dict], list[dict]]:
    """Refuse a boundary that leaves a chapter's first scene as nothing but
    its epigraph: the epigraph joins the scene that opens the chapter, which
    keeps its own name.

    Args:
        chapter_text: The chapter's full text.
        splits: Scene starts, sorted, as dicts with a 1-based ``line``.

    Returns:
        ``(splits, refused)``: the splits to write, and the epigraph-only
        splits that were folded into the next scene (for the caller to name
        in a WARNING).
    """
    lines = chapter_text.splitlines()
    kept = list(splits)
    refused = []
    while len(kept) > 1:
        first = '\n'.join(lines[kept[0]['line'] - 1:kept[1]['line'] - 1])
        if not is_epigraph_block(first):
            break
        refused.append(kept[0])
        kept[1] = dict(kept[1], line=kept[0]['line'])
        kept.pop(0)
    return kept, refused


# ============================================================================
# CSV generation
# ============================================================================

def _schema_header(name: str) -> str:
    # elaborate._FILE_MAP is the one column list every writer uses; imported
    # here, not at module top, to keep this module's import light
    from .elaborate import _FILE_MAP
    return '|'.join(_FILE_MAP[name])


_SCENES_HEADER = _schema_header('scenes.csv')
_INTENT_HEADER = _schema_header('scene-intent.csv')


def generate_scenes_rows(scenes: list[dict],
                         part_num: int | None = None,
                         seq_start: int = 1) -> list[str]:
    """Generate pipe-delimited CSV rows for ``scenes.csv``.

    Each row uses ``_SCENES_HEADER``'s order (elaborate._FILE_MAP's).

    The scene dicts must have at least ``title`` (str).  They may
    optionally include ``word_count`` (int) and ``slug`` (str).  If
    ``slug`` is absent it is derived from ``title`` via
    :func:`generate_slug`.

    Args:
        scenes: Scene dicts as returned by :func:`parse_scene_boundaries`
            (or any list of dicts with a ``title`` key).
        part_num: Optional book part number to fill the ``part`` column.
            ``act`` is left empty — acts are assigned by extract/elaborate.
        seq_start: Starting sequence number (default 1).

    Returns:
        List of pipe-delimited row strings (no header row included).
    """
    rows: list[str] = []
    used_slugs: set[str] = set()

    for i, scene in enumerate(scenes):
        title = scene.get('title', '')
        slug = scene.get('slug', '') or generate_slug(title)
        if not slug:
            slug = f'scene-{seq_start + i}'
        slug = unique_slug(slug, used_slugs)

        seq = seq_start + i
        part = str(part_num) if part_num is not None else ''
        word_count = str(scene.get('word_count', ''))

        values = {'id': slug, 'seq': str(seq), 'title': title, 'part': part,
                  'word_count': word_count}
        rows.append('|'.join(values.get(col, '') for col in _SCENES_HEADER.split('|')))

    return rows


def generate_intent_rows(scenes: list[dict]) -> list[str]:
    """Generate pipe-delimited CSV rows for ``scene-intent.csv``.

    Each row uses ``_INTENT_HEADER``'s order (elaborate._FILE_MAP's).

    Args:
        scenes: Scene dicts (must have at least ``title``; ``slug`` is
            optional and derived if absent).

    Returns:
        List of pipe-delimited row strings (no header row included).
    """
    rows: list[str] = []
    used_slugs: set[str] = set()

    for scene in scenes:
        title = scene.get('title', '')
        slug = scene.get('slug', '') or generate_slug(title)
        if not slug:
            slug = f'scene-unknown'
        slug = unique_slug(slug, used_slugs)

        rows.append('|'.join([slug] + [''] * (len(_INTENT_HEADER.split('|')) - 1)))

    return rows


def scenes_header() -> str:
    """Return the canonical scenes CSV header line."""
    return _SCENES_HEADER


def intent_header() -> str:
    """Return the canonical intent CSV header line."""
    return _INTENT_HEADER


# ============================================================================
# Manuscript / chapter splitting
# ============================================================================

def split_by_scene_markers(text: str,
                           markers: list[dict]) -> dict[str, str]:
    """Split full text into scene content by boundary markers.

    Args:
        text: The full chapter or manuscript text.
        markers: List of dicts with ``line_number`` (int, 1-indexed) and
            ``title`` (str).  Must be sorted by ``line_number``.

    Returns:
        Ordered dict of ``scene_slug -> prose`` for each marker.
        Scene break decoration lines (``***``, ``---``, ``# # #``,
        ``* * *``) are stripped from the prose.
    """
    lines = text.splitlines(keepends=True)
    total = len(lines)
    result: dict[str, str] = {}
    used_slugs: set[str] = set()

    # Sort markers by line_number to be safe
    sorted_markers = sorted(markers, key=lambda m: m['line_number'])

    for i, marker in enumerate(sorted_markers):
        start = marker['line_number'] - 1  # 0-indexed
        if start < 0:
            start = 0
        if start >= total:
            start = total - 1

        if i + 1 < len(sorted_markers):
            end = sorted_markers[i + 1]['line_number'] - 1  # exclusive
        else:
            end = total

        segment_lines = lines[start:end]

        # Strip scene break markers
        cleaned = []
        for ln in segment_lines:
            stripped = ln.strip()
            if is_break_marker(stripped):
                continue
            cleaned.append(ln)

        # Trim leading blank lines
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)

        prose = ''.join(cleaned).rstrip('\n') + '\n'

        title = marker.get('title', '') or f'scene-{i + 1}'
        slug = generate_slug(title)
        if not slug:
            slug = f'scene-{i + 1}'
        slug = unique_slug(slug, used_slugs)

        result[slug] = prose

    return result


# ============================================================================
# File rename planning
# ============================================================================

def generate_rename_plan(scenes_dir: str,
                         metadata_csv: str) -> list[tuple[str, str]]:
    """Compare scene filenames against metadata CSV and plan renames.

    Reads the metadata CSV to find the ``title`` for each scene ID, then
    generates a slug from that title.  If the slug differs from the
    current filename (the ``id`` column), a rename entry is produced.

    Handles numeric-to-slug conversion (e.g. ``001.md`` -> ``finest-cartographer.md``).

    Args:
        scenes_dir: Path to the ``scenes/`` directory.
        metadata_csv: Path to ``reference/scenes.csv``.

    Returns:
        List of ``(old_path, new_path)`` tuples for files that need
        renaming.  Paths are absolute.
    """
    if not os.path.isfile(metadata_csv):
        return []

    # Read the CSV (strip \r for CRLF safety)
    with open(metadata_csv, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    csv_lines = [l for l in raw.splitlines() if l.strip()]

    if not csv_lines:
        return []

    header = csv_lines[0].split('|')
    try:
        id_idx = header.index('id')
        title_idx = header.index('title')
    except ValueError:
        return []

    # Build id -> title map from CSV
    id_title: dict[str, str] = {}
    for line in csv_lines[1:]:
        cols = line.split('|')
        if len(cols) > max(id_idx, title_idx):
            scene_id = cols[id_idx]
            title = cols[title_idx]
            if scene_id:
                id_title[scene_id] = title

    # Collect existing scene files
    if not os.path.isdir(scenes_dir):
        return []

    existing_files = sorted(
        f for f in os.listdir(scenes_dir) if f.endswith('.md')
    )

    renames: list[tuple[str, str]] = []
    used_slugs: set[str] = set()

    for filename in existing_files:
        old_id = filename[:-3]  # strip .md

        # Get title from CSV; fall back to extracting from file content
        title = id_title.get(old_id, '')
        if not title:
            # Try reading first heading from the file
            filepath = os.path.join(scenes_dir, filename)
            title = _title_from_file(filepath)

        new_slug = generate_slug(title) if title else generate_slug(old_id)
        if not new_slug:
            new_slug = old_id

        new_slug = unique_slug(new_slug, used_slugs)

        if old_id != new_slug:
            old_path = os.path.join(scenes_dir, f'{old_id}.md')
            new_path = os.path.join(scenes_dir, f'{new_slug}.md')
            renames.append((old_path, new_path))

    return renames


def _title_from_file(filepath: str) -> str:
    """Derive a title from the first heading or first non-empty line."""
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    return re.sub(r'^#+\s*', '', line)
                return line[:80]
    except OSError:
        pass
    return ''


# ============================================================================
# Scene boundary detection prompt
# ============================================================================

def build_boundary_prompt(chapter_text: str,
                          fixed_lines: list[int] | None = None) -> str:
    """Build a prompt for Claude to find scene boundaries and name each scene.

    Args:
        chapter_text: The full text of a chapter.
        fixed_lines: Boundaries already fixed by explicit break markers. The
            model then only names the scenes at those lines.

    Returns:
        The assembled prompt string.
    """
    # Number the lines: the model cannot reliably count them itself, and a
    # miscounted boundary shifts every scene's text away from its title.
    numbered = '\n'.join(
        f'{n}: {line}' for n, line in enumerate(chapter_text.splitlines(), 1)
    )
    if fixed_lines:
        task = ('The scene boundaries in this chapter are already fixed by break markers, '
                f'at lines {", ".join(str(n) for n in fixed_lines)}. Output exactly one '
                'SCENE line for each of these lines, in order. Do not add or remove boundaries.')
    else:
        task = ('Identify where each scene begins. For each scene boundary (including the '
                'very start of the chapter), output one line.')
    return f"""You are identifying scene boundaries in a chapter of a novel.

A scene is a continuous unit of action in one time and place. A new scene begins when there is a significant shift in:
- Time (hours or days pass)
- Setting/location (characters move to a new place)
- Point of view (the perspective character changes)
- Narrative focus (a distinct new dramatic situation begins)

Minor transitions within the same time/place/focus are NOT scene breaks.

## Chapter Text

Each line is prefixed with its line number and a colon.

{numbered}

## Instructions

{task}

SCENE: <line_number> | <scene_id> | <brief_reason>

Where line_number is the number prefixed to the line where this scene begins
(the first scene always starts at line 1), and scene_id is the scene's
permanent id: 3-5 lowercase words joined by hyphens naming the scene's core
event (e.g., gatsby-reunites-with-daisy). Describe what happens, never where
the scene falls: no chapter or scene numbers.

Output ONLY SCENE: lines, nothing else."""


# ============================================================================
# CLI interface
# ============================================================================

def main():
    """CLI entry point.

    Usage::

        python3 -m storyforge.scenes parse-boundaries <response_file>
        python3 -m storyforge.scenes generate-slug <title>
        python3 -m storyforge.scenes split-text <text_file> <markers_json> <output_dir>
        python3 -m storyforge.scenes rename-plan <scenes_dir> <metadata_csv>
        python3 -m storyforge.scenes metadata-rows <boundaries_json> [--part N] [--seq-start N]
        python3 -m storyforge.scenes intent-rows <boundaries_json>
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.scenes <command> [args]',
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'parse-boundaries':
        if len(sys.argv) < 3:
            print('Usage: parse-boundaries <response_file>',
                  file=sys.stderr)
            sys.exit(1)
        response_file = sys.argv[2]
        with open(response_file) as f:
            response = f.read()
        scenes = parse_scene_boundaries(response)
        print(json.dumps(scenes, indent=2))

    elif command == 'generate-slug':
        if len(sys.argv) < 3:
            print('Usage: generate-slug <title>', file=sys.stderr)
            sys.exit(1)
        title = ' '.join(sys.argv[2:])
        print(generate_slug(title))

    elif command == 'split-text':
        if len(sys.argv) < 5:
            print('Usage: split-text <text_file> <markers_json> <output_dir>',
                  file=sys.stderr)
            sys.exit(1)
        text_file = sys.argv[2]
        markers_file = sys.argv[3]
        output_dir = sys.argv[4]

        with open(text_file) as f:
            text = f.read()
        with open(markers_file) as f:
            markers = json.load(f)

        result = split_by_scene_markers(text, markers)

        os.makedirs(output_dir, exist_ok=True)
        for slug, prose in result.items():
            out_path = os.path.join(output_dir, f'{slug}.md')
            with open(out_path, 'w') as f:
                f.write(prose)
            print(f'{slug}.md ({len(prose.split())} words)')

    elif command == 'rename-plan':
        if len(sys.argv) < 4:
            print('Usage: rename-plan <scenes_dir> <metadata_csv>',
                  file=sys.stderr)
            sys.exit(1)
        scenes_dir = sys.argv[2]
        metadata_csv = sys.argv[3]
        plan = generate_rename_plan(scenes_dir, metadata_csv)
        for old_path, new_path in plan:
            old_name = os.path.basename(old_path)
            new_name = os.path.basename(new_path)
            print(f'{old_name} -> {new_name}')

    elif command == 'metadata-rows':
        if len(sys.argv) < 3:
            print('Usage: metadata-rows <boundaries_json> [--part N] [--seq-start N]',
                  file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            scenes = json.load(f)

        part_num = None
        seq_start = 1
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == '--part' and i + 1 < len(sys.argv):
                part_num = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == '--seq-start' and i + 1 < len(sys.argv):
                seq_start = int(sys.argv[i + 1])
                i += 2
            else:
                i += 1

        rows = generate_scenes_rows(scenes, part_num=part_num,
                                    seq_start=seq_start)
        for row in rows:
            print(row)

    elif command == 'intent-rows':
        if len(sys.argv) < 3:
            print('Usage: intent-rows <boundaries_json>', file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            scenes = json.load(f)
        rows = generate_intent_rows(scenes)
        for row in rows:
            print(row)

    elif command == 'build-boundary-prompt':
        # Build scene boundary detection prompt from chapter text
        # Usage: build-boundary-prompt <chapter_file>
        if len(sys.argv) < 3:
            print('Usage: build-boundary-prompt <chapter_file>',
                  file=sys.stderr)
            sys.exit(1)
        with open(sys.argv[2]) as f:
            chapter_text = f.read()
        print(build_boundary_prompt(chapter_text))

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
