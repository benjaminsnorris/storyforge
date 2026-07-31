"""Canon file parsing and validation for graphic-novel projects.

Canon files live under `reference/canon/` and document the canonical
visual blocks that get embedded inline into per-panel prompts. Each
file has YAML frontmatter (canon_id, canon_type, etc.) and four
required H2 body sections: Embeddable block, Clauses, Related canon,
Iteration history.

## Inline-embed convention

Per-page panel prompts embed canon blocks verbatim, marked by HTML
comment delimiters that are inert in DALL-E/GPT inputs but easy to
find programmatically:

    ### Style Foundation
    <!-- canon-embed: style-foundation -->
    The verbatim Embeddable block text, copied from
    reference/canon/style-foundation.md.
    <!-- /canon-embed -->

`find_canon_embeds()` extracts these blocks; `check_canon_drift()`
validates them against their source canon files (see its docstring
for the emitted finding types).
"""

import enum
import os
import re
from typing import Literal, NamedTuple, TypedDict

from storyforge.common import csv_safe, log, normalize_for_comparison

# Severity is part of the cleanup-report contract — build_cleanup_report
# filters action items by != 'info' and counts errors/warnings/info. A
# typo on either side silently demotes a finding.
Severity = Literal['info', 'warning', 'error']

# Every distinct finding type this module (and report_canon_files) emits.
# Narrowing to a Literal catches typos in `_finding(type_=...)` call sites
# and in test assertions on f['type']. Same pattern as
# pages.PageFindingKind and script_format.LayoutAntiPatternKind.
CanonFindingKind = Literal[
    'canon_missing_frontmatter',
    'canon_truncated_frontmatter',
    'canon_missing_key',
    'canon_id_mismatch',
    'canon_id_invalid',
    'canon_type_invalid',
    'canon_type_wrong_location',
    'canon_unknown_subdir',
    'canon_unexpected_nesting',
    'canon_missing_section',
    'canon_truncated_embeddable_block',
    'canon_unfilled_template',
    'canon_registry_unreadable',
    'canon_missing_registry_entry',
    'canon_embed_orphan',
    'canon_embed_unclosed',
    'canon_embed_invalid_id',
    'canon_page_unreadable',
    'canon_drift',
]


class _Sentinel(enum.Enum):
    """Distinct sentinel values returned by parser helpers when the input
    is malformed in a way that the caller needs to distinguish from a
    normal result. Using an enum (rather than ad-hoc `object()` or string
    sentinels) gives both narrow Literal types and stable `is` identity.

    Declared up here rather than beside the parsers because
    `ParsedCanonFile.frontmatter` names `TRUNCATED` in its own type.
    """
    TRUNCATED = enum.auto()
    REGISTRY_MALFORMED = enum.auto()


_TRUNCATED = _Sentinel.TRUNCATED
_REGISTRY_MALFORMED = _Sentinel.REGISTRY_MALFORMED


class _CanonFindingRequired(TypedDict):
    type: CanonFindingKind
    file: str
    detail: str
    action: str
    severity: Severity


class CanonFinding(_CanonFindingRequired, total=False):
    # `category` is set by cmd_cleanup.report_canon_files after construction;
    # this module doesn't know about it. Future fields follow the same
    # Required+Optional pattern.
    category: Literal['canon']


class ParsedCanonFile(TypedDict):
    """One parsed canon .md file. When `exists` is False the other fields
    are zero-initialized so callers can read uniformly."""
    path: str
    exists: bool
    #: The sentinel is part of this type, not an implementation detail:
    #: `parse_canon_file` passes `_parse_frontmatter`'s result straight through,
    #: so an unclosed `---` block really does land here. Declaring only
    #: `dict | None` gave callers no reason to guard, while the value they would
    #: hit is neither (#294).
    frontmatter: dict[str, str] | None | Literal[_Sentinel.TRUNCATED]
    sections: set[str]
    body: str
    #: Lines consumed by the frontmatter, so a body-relative line number can
    #: be reported as the file line the author will actually look at. Body
    #: line N is file line `body_line_offset + N`.
    body_line_offset: int


CANON_DIR = os.path.join('reference', 'canon')

# Validated values authors write into the `canon_type` frontmatter field.
CanonType = Literal[
    'foundation', 'vocabulary', 'rules', 'character', 'location', 'motif',
]

CANON_TYPES: tuple[CanonType, ...] = (
    'foundation', 'vocabulary', 'rules', 'character', 'location', 'motif',
)

#: Keys every canon file needs regardless of medium.
ALWAYS_REQUIRED_FRONTMATTER_KEYS = (
    'canon_id',
    'canon_type',
    'canon_updated',
    'appears_in',
    'first_appearance',
)

#: `embeds_as` serves the inline-embed convention, which only the
#: graphic-novel page pipeline uses. Requiring it of a prose project would
#: make it write-only. Its long-term fate is decided by the
#: staleness-unification issue.
GN_ONLY_FRONTMATTER_KEYS = ('embeds_as',)

#: Retained for importers that predate the split.
REQUIRED_FRONTMATTER_KEYS = (
    ALWAYS_REQUIRED_FRONTMATTER_KEYS + GN_ONLY_FRONTMATTER_KEYS
)

#: The section carrying the anchor / embeddable prompt block. Defined here and
#: composed into `REQUIRED_SECTIONS` and `_EMBEDDABLE_BLOCK_RE` below, so the
#: name has one spelling: three independent copies could be renamed apart, and
#: a detector that no longer recognizes the extractor's heading would report
#: `[]` for every file forever with no test failing.
EMBEDDABLE_SECTION = 'Embeddable block'

REQUIRED_SECTIONS = (
    EMBEDDABLE_SECTION,
    'Clauses',
    'Related canon',
    'Iteration history',
)

SUBDIR_TYPE: dict[str, CanonType] = {
    'characters': 'character',
    'locations': 'location',
    'motifs': 'motif',
}

SUBDIR_REGISTRY = {
    'characters': 'characters.csv',
    'locations': 'locations.csv',
    'motifs': 'motif-taxonomy.csv',
}

ROOT_TYPES: frozenset[CanonType] = frozenset(
    {'foundation', 'vocabulary', 'rules'},
)

#: Canon types that describe one entity whose look must stay fixed. The
#: foundation/vocabulary/rules types describe the book, not a thing in it,
#: so they are house style rather than per-entity anchors.
ENTITY_CANON_TYPES: frozenset[CanonType] = frozenset(
    {'character', 'location', 'motif'})


_FRONTMATTER_RE = re.compile(r'\A---\s*\n(.*?\n)---\s*(?:\n|$)', re.DOTALL)

#: Separates `##` from its heading name. `[ \t]`, never `\s`: without DOTALL a
#: `.` cannot cross a newline, but `\s+` always could, so `##\nClauses` was read
#: as a heading *named* `Clauses`. That fabricated a section, and since
#: `parse_canon_file`'s `sections` set is what `canon_missing_section` checks
#: `REQUIRED_SECTIONS` against, a file with no `## Clauses` heading anywhere
#: reported none missing. It also split the extractor from the truncation
#: detector: a bare `##` above a line reading `Embeddable block` made
#: `_EMBEDDABLE_BLOCK_RE` report a block while the detector (matching per line)
#: never opened its window, so a real truncation below went unreported (#294).
#: A markdown heading is one line; all three consumers now say so.
_H2_GAP = r'[ \t]+'
_H2_TRAIL = r'[ \t]*'

_SECTION_RE = re.compile(rf'^##{_H2_GAP}(.+?){_H2_TRAIL}$', re.MULTILINE)
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')

# Canon-embed markers: opener captures a candidate id (permissive — we
# validate slug shape after extraction so a typo surfaces as a finding
# instead of silently disappearing). Closer is fixed text.
_CANON_EMBED_OPEN_RE = re.compile(r'<!--\s*canon-embed:\s*([^\s>]+)\s*-->')
_CANON_EMBED_CLOSE_RE = re.compile(r'<!--\s*/canon-embed\s*-->')


class CanonEmbed(TypedDict):
    """One canon-embed block found in a page file body."""
    canon_id: str
    text: str          # raw text between the markers (with outer whitespace)
    normalized: str    # whitespace-normalized text, used for drift comparison


class _UnclosedEmbed(TypedDict):
    """Opener with no following closer — needs an `unclosed` finding."""
    canon_id: str


class _InvalidIdEmbed(TypedDict):
    """Closed block whose id failed slug validation."""
    raw_id: str


def find_canon_embeds(
    text: str,
) -> tuple[list[CanonEmbed], list[_UnclosedEmbed], list[_InvalidIdEmbed]]:
    """Scan `text` for canon-embed blocks. Returns three lists:

    - successfully-parsed embeds (well-formed open+close, valid slug id),
      in source order
    - unclosed openers (no matching closer before end of file or before
      the next opener) — author forgot the closer
    - closed blocks whose id is not a valid slug (uppercase, underscore,
      etc.) — author typoed the id

    The opener regex is permissive (`[^\\s>]+`) so a typoed id is captured
    rather than skipped silently. Slug validation runs after extraction so
    failures surface as findings, not silent misses.
    """
    embeds: list[CanonEmbed] = []
    unclosed: list[_UnclosedEmbed] = []
    invalid: list[_InvalidIdEmbed] = []
    pos = 0
    while True:
        open_match = _CANON_EMBED_OPEN_RE.search(text, pos)
        if not open_match:
            break
        raw_id = open_match.group(1)
        block_start = open_match.end()
        # The next closer must come before the NEXT opener — otherwise
        # the inner opener proves the current one was never closed.
        next_open = _CANON_EMBED_OPEN_RE.search(text, block_start)
        next_close = _CANON_EMBED_CLOSE_RE.search(text, block_start)
        if next_close is None or (
            next_open is not None and next_open.start() < next_close.start()
        ):
            unclosed.append({'canon_id': raw_id})
            pos = block_start
            continue
        block_text = text[block_start:next_close.start()]
        if not _SLUG_RE.match(raw_id):
            invalid.append({'raw_id': raw_id})
        else:
            embeds.append({
                'canon_id': raw_id,
                'text': block_text,
                'normalized': normalize_for_comparison(block_text),
            })
        pos = next_close.end()
    return embeds, unclosed, invalid


#: What ends an H2 section: an `##` at line start followed by any whitespace.
#: Composed into all three consumers below rather than retyped in each, because
#: the truncation detector is only correct while it enumerates *exactly* the
#: headings the extractor stops at, and two hand-copied spellings of one
#: pattern are free to drift apart the moment either is edited. The comments
#: that used to argue the copies were identical are what motivated composing
#: them: an invariant defended in prose is an invariant nothing enforces.
_BLOCK_TERMINATOR = r'^##\s'

_EMBEDDABLE_BLOCK_RE = re.compile(
    rf'^##{_H2_GAP}{re.escape(EMBEDDABLE_SECTION)}{_H2_TRAIL}\n'
    rf'(.*?)(?={_BLOCK_TERMINATOR}|\Z)',
    re.MULTILINE | re.DOTALL,
)

_SECTION_BODY_RE = re.compile(
    rf'^##{_H2_GAP}(.+?){_H2_TRAIL}\n(.*?)(?={_BLOCK_TERMINATOR}|\Z)',
    re.MULTILINE | re.DOTALL,
)

#: The heading alternative of `_EMBEDDABLE_BLOCK_RE`'s lookahead — the other
#: alternative, `\Z`, is end-of-body and never an offending heading. So this
#: *enumerates* every heading the extractor stops at and no others;
#: `embeddable_block_truncations` then narrows that enumeration to the ones
#: inside the block, and therefore reports a strict subset.
#:
#: Deliberately NOT `_SECTION_RE`, which requires `##` plus a name. Matched
#: against the whole body rather than per line, because for a bare `##` line —
#: the case with no name, which nothing else reports — the `\s` is the line's
#: own newline, and `splitlines()` strips it. (In the ordinary case the `\s` is
#: just the space after `##`; the newline only carries it for a bare `##`.)
_BLOCK_TERMINATOR_RE = re.compile(_BLOCK_TERMINATOR, re.MULTILINE)

#: The required sections that legitimately *follow* the anchor, and so close
#: the truncation window. Deliberately not `REQUIRED_SECTIONS`, which contains
#: the section we are inside: `EMBEDDABLE_SECTION` is `REQUIRED_SECTIONS[0]`,
#: so breaking on the whole tuple made a *duplicated* `## Embeddable block`
#: read as a clean terminator. The extractor stops there too (`.search` takes
#: the first block), so the anchor was silently halved and `validate_canon_file`
#: returned zero findings — the exact failure class #289 exists to close,
#: reached through its own fix. `parsed['sections']` is a set, so no
#: duplicate-heading check catches it either. An author who sub-heads their
#: anchor and one who pastes the heading twice are making the same mistake.
_SECTIONS_AFTER_ANCHOR = tuple(
    s for s in REQUIRED_SECTIONS if s != EMBEDDABLE_SECTION
)


class BlockTruncation(NamedTuple):
    """One `##` heading that cuts the Embeddable block short.

    `body_line` is named for its units on purpose: it is *body*-relative, and
    the file-relative number a finding must show is
    `body_line + ParsedCanonFile['body_line_offset']`. Two quantities of type
    `int` that mean different things is a mix-up no annotation here would
    catch, so the field name is the only guard available — and the name also
    lands in pytest failure output, where `BlockTruncation(body_line=6,
    heading='## Wardrobe')` beats `(6, '## Wardrobe')` when the assertion that
    fails is a transposition. Unpacks like the tuple it replaces.
    """
    body_line: int
    heading: str


def embeddable_block_truncations(body: str) -> list[BlockTruncation]:
    """Every `##` heading that cuts the `## Embeddable block` short.

    Returns one `BlockTruncation` per offender, in source order, with trailing
    whitespace stripped from the quoted heading.

    `embeddable_block_text` reads to the next `##`, which is correct markdown
    and correct for the schema — the four `REQUIRED_SECTIONS` are what follows
    a real anchor. But an author who sub-heads the anchor itself
    (`## Wardrobe`) loses every word below that line, and the anchor is the
    string every prompt embeds verbatim, so the images then drift on whatever
    the dropped tail described. Widening the extractor instead would swallow
    whichever section actually followed and feed it to an image model as
    though it were description, so the truncation stays and is reported
    (issue #289).

    The window closes at the first `_SECTIONS_AFTER_ANCHOR` heading: past that
    point a non-schema heading is somebody's extra section, not lost anchor
    text. A second `## Embeddable block` is an offender like any other — see
    that constant for why it must not close the window.
    """
    offenders: list[BlockTruncation] = []
    started = False
    for match in _BLOCK_TERMINATOR_RE.finditer(body):
        start = match.start()
        eol = body.find('\n', start)
        # `eol == -1` is a heading on the last line with no trailing newline;
        # `body[start:eol]` would silently drop the body's final character and
        # report a heading the author cannot find by searching for it.
        line = (body[start:] if eol == -1 else body[start:eol]).rstrip()
        # Matched against the extracted LINE, never over the body: `_SECTION_RE`
        # has no DOTALL but its `\s+` crosses newlines, so over a body it reads
        # `##\nA grey coat.` as a heading named `A grey coat.`. Per line it
        # returns None for a bare `##`, and that empty name is exactly what
        # makes the bare-`##` case report. Collapsing this into one
        # `_SECTION_RE.finditer(body)` pass would break the case #289 is about.
        named = _SECTION_RE.match(line)
        name = named.group(1).strip() if named else ''
        if not started:
            started = name == EMBEDDABLE_SECTION
            continue
        if name in _SECTIONS_AFTER_ANCHOR:
            break
        offenders.append(BlockTruncation(body.count('\n', 0, start) + 1, line))
    return offenders

# Lines that mark a section as unfilled scaffolding. Stripped of leading
# `<!--` HTML-comment fragments and surrounding whitespace, a section
# body that starts with one of these strings is considered placeholder.
_PLACEHOLDER_PREFIXES = ('TODO', 'TODO —', 'TODO -', 'TODO.', 'TODO:')

# A line wholly wrapped in markdown emphasis. The (now-retired)
# illustration-direction coach/strict templates emitted their instructions
# this way (`_(fill this in)_`, `_Required: describe the palette_`), so a
# section made of nothing but emphasized lines is boilerplate by
# construction. Ported verbatim from illustrations._EMPHASIZED_LINE_RE (Task
# 7 fix round 1, .superpowers/sdd/2026-07-28-illustration-canon-adoption/)
# rather than reinvented, so the same shapes stay recognized now that
# placeholder detection is shared here instead of duplicated per module.
#
# NOTE: this regex also matches a *bold lead-in* line (`**Nora Vance**`,
# `_The lamp remembers._`), which is why it is only ever applied to a WHOLE
# body — see _section_body_is_placeholder. Applied to the first line alone it
# would call a filled anchor a scaffold.
_EMPHASIZED_LINE_RE = re.compile(r'\A[_*]{1,2}.*[_*]{1,2}\Z')

# Unemphasized placeholders an author might type by hand: TBD, n/a, "fill
# this in". Case-insensitive and broader than _PLACEHOLDER_PREFIXES (which
# only recognizes the exact-case TODO shapes the templates themselves emit).
# Also ported verbatim from illustrations._BARE_PLACEHOLDER_RE.
_BARE_PLACEHOLDER_RE = re.compile(
    r'\A\(?\s*(tbd|todo|n/?a|(you )?fill (this )?in)\b', re.IGNORECASE,
)


def _section_body_is_placeholder(body: str) -> bool:
    """Return True if the section body looks like an unfilled template.

    Leading HTML comments are stripped first (the starter templates wrap
    orienting comments in `<!-- ... -->`). Two independent rules then apply,
    and the distinction between them is load-bearing:

    - **First-line `TODO`** — if the first non-blank line starts with one of
      `_PLACEHOLDER_PREFIXES`, the body is a scaffold. Every shipped template
      (GN canon, and formerly illustration-direction's own) emits exactly
      that, and GN's `elaborate --stage page-architecture` gate has depended
      on this first-line rule since before the canon adoption — so it stays a
      first-line rule, unchanged.
    - **Whole-body emphasis / bare placeholder** — a body that consists of
      *nothing but* emphasized instruction lines (`_(fill this in)_`,
      `_Required: describe the palette_`), bare TBD/n-a/fill-this-in lines,
      and headings has nothing substantive in it, so it is a scaffold. This
      is the retired `illustrations._is_placeholder`'s semantics, restored
      verbatim: it was a whole-body test, and narrowing it to the first line
      classified real content as scaffolding. A continuity anchor opening
      with a bold name (`**Nora Vance**`, then the description) or an italic
      epigraph is filled prose — treating it as unfilled drops the anchor
      from `anchor_texts`, and every prompt for that entity then renders with
      no anchor at all, which is the exact drift anchors exist to prevent.
      On the GN side the same misclassification made a register vocabulary
      opening `**Dominant / transitional / rhythmic.**` fail the
      page-architecture gate.

    An empty body (nothing but blank lines) is deliberately NOT a
    placeholder here — see is_canon_block_populated's docstring for the
    rationale. A caller that wants an empty book-level Embeddable block to
    also count as unfilled (illustrations.missing_reference_sections does,
    because the retired illustration-direction reader treated an empty
    direction section that way) adds that check on its own side, on top of
    this function's result, rather than this function's behavior changing
    under every caller including GN's page-architecture gate.
    """
    text = re.sub(r'^\s*<!--.*?-->\s*', '', body, flags=re.DOTALL)
    lines = [line.strip() for line in text.splitlines()]
    content = [line for line in lines if line]
    if not content:
        return False  # empty body counts as populated — see the docstring
    if any(content[0].startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return True
    # Whole-body test: headings are not content either — an anchor heading
    # with no description under it is an unfilled anchor.
    substantive = [
        line for line in content
        if not line.startswith('#')
        and not _EMPHASIZED_LINE_RE.match(line)
        and not _BARE_PLACEHOLDER_RE.match(line)
    ]
    return not substantive


def embeddable_block_text(canon_path: str) -> str | None:
    """Return the verbatim text of a canon file's `## Embeddable block`.

    Verbatim is the whole point: an anchor works only because every prompt
    that uses it sends a byte-identical string. Never normalize here —
    normalization belongs at comparison time, in the caller.

    Returns None when the file or the section is absent.
    """
    parsed = parse_canon_file(canon_path)
    if not parsed['exists']:
        return None
    body = parsed['body']
    match = _EMBEDDABLE_BLOCK_RE.search(body)
    if not match:
        return None
    return match.group(1)


def _parse_frontmatter(
    text: str,
) -> tuple[dict[str, str] | None | Literal[_Sentinel.TRUNCATED], str]:
    """Extract YAML-style frontmatter as a flat dict.

    Returns:
        (dict, body) — frontmatter parsed
        (None, text) — file has no frontmatter at all
        (_TRUNCATED, text) — file starts with `---` but never closes
            the block; distinct from missing-frontmatter because the
            author's diagnostic and fix are different
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        if text.startswith('---'):
            return _TRUNCATED, text
        return None, text

    block = match.group(1)
    body = text[match.end():]
    data: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            val = val[1:-1]
        data[key] = val
    return data, body


def parse_canon_file(path: str) -> ParsedCanonFile:
    """Read a canon file from disk and return its parsed structure."""
    if not os.path.isfile(path):
        return {
            'path': path,
            'exists': False,
            'frontmatter': None,
            'sections': set(),
            'body': '',
            'body_line_offset': 0,
        }
    with open(path, encoding='utf-8') as f:
        text = f.read()
    # Strip BOM so frontmatter parsing isn't disabled by editors that
    # auto-write one (Notion/Word/etc.).
    if text.startswith('﻿'):
        text = text.lstrip('﻿')
    frontmatter, body = _parse_frontmatter(text)
    sections = {m.group(1).strip() for m in _SECTION_RE.finditer(body)}
    # `text` is prefix + body, so the prefix's line count is exactly the
    # difference in newlines. Counting that way rather than measuring the
    # frontmatter match holds for every branch: no frontmatter (body IS text),
    # a `_TRUNCATED` block (same), and `_FRONTMATTER_RE`'s trailing `\s*`
    # absorbing a variable number of blank lines, which a match-length
    # measurement would get wrong.
    return {
        'path': path,
        'exists': True,
        'frontmatter': frontmatter,
        'sections': sections,
        'body': body,
        'body_line_offset': text.count('\n') - body.count('\n'),
    }


def _is_template_file(filename: str) -> bool:
    """Starter templates aren't author canon and should not be validated."""
    if filename.startswith('.') or filename.startswith('_'):
        return True
    return False


def _expected_canon_id(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _read_registry_ids(
    project_dir: str, registry_filename: str,
) -> set[str] | None | Literal[_Sentinel.REGISTRY_MALFORMED]:
    """Read the `id` column of a registry CSV.

    Returns:
        None — file is absent (caller skips cross-ref silently)
        _REGISTRY_MALFORMED — file exists but has no readable `id` column
            (caller emits a project-level finding instead of flagging every
            canon file as orphan)
        set[str] — the `id` values in the CSV
    """
    csv_path = os.path.join(project_dir, 'reference', registry_filename)
    if not os.path.isfile(csv_path):
        return None
    ids: set[str] = set()
    with open(csv_path, encoding='utf-8') as f:
        header = f.readline().rstrip('\n')
        if not header:
            return _REGISTRY_MALFORMED
        cols = header.split('|')
        try:
            id_idx = cols.index('id')
        except ValueError:
            return _REGISTRY_MALFORMED
        for line in f:
            row = line.rstrip('\n')
            if not row:
                continue
            parts = row.split('|')
            if id_idx < len(parts):
                value = parts[id_idx].strip()
                if value:
                    ids.add(value)
    return ids


def _finding(file_rel: str, detail: str, action: str,
             type_: CanonFindingKind,
             severity: Severity = 'warning') -> CanonFinding:
    return {
        'type': type_,
        'file': file_rel,
        'detail': detail,
        'action': action,
        'severity': severity,
    }


#: Longest quoted heading in a `detail`, so one pathological line cannot make
#: a CSV cell unreadable. The line number is what the author navigates by; the
#: quote is only there to confirm they are looking at the right line.
_MAX_QUOTED_HEADING = 60


def _truncated_block_findings(
    rel: str, parsed: ParsedCanonFile,
) -> list[CanonFinding]:
    """The `canon_truncated_embeddable_block` finding, or nothing.

    'error' severity, the same class as `canon_id_mismatch`: both break prompt
    assembly at the point the anchor is consumed. The failure modes differ, and
    truncation's is the worse of the two — a `canon_id` mismatch fails the
    lookup and surfaces as an unanchored row that `_warn_unanchored_rows`
    announces, whereas a truncation hands every consumer a shorter string that
    they all accept, and once art exists the only repair is a re-render.

    Only `cleanup` surfaces this; nothing exits non-zero on it (see the
    follow-up in CLAUDE.md).
    """
    truncations = embeddable_block_truncations(parsed['body'])
    if not truncations:
        return []
    offset = parsed['body_line_offset']
    # csv_safe because the quoted heading is verbatim author markdown — a `|`
    # in it shifts every later column of the cleanup-report row, emptying the
    # trailing `status` cell that `forge` scans for `pending`. The finding
    # would then silence itself. Newlines are already impossible (the line is
    # cut at the first `\n` and rstripped), so `|` is the whole exposure.
    where = ', '.join(
        f'line {offset + body_line}: `{csv_safe(heading)[:_MAX_QUOTED_HEADING]}`'
        for body_line, heading in truncations
    )
    # One finding per file listing every offender, matching the adjacent
    # unfilled-template check: the author opens the file once and fixes them
    # together. Reporting only the first would make an error-severity finding
    # into an N-round loop on the file where several sub-heads are likeliest.
    return [_finding(
        rel,
        f'## {EMBEDDABLE_SECTION} is ended early by a `##` heading inside it '
        f'({where}; the anchor stops at the first). If that heading was meant '
        'to be part of the anchor, every word below it is missing from the '
        'string each prompt embeds',
        'Demote the heading to `###` so it stays inside the anchor; if it was '
        'meant to be its own section, move it below the four required '
        'sections; if it is a second `## Embeddable block`, merge it into the '
        'first. A `##` inside a fenced code block ends the section too',
        'canon_truncated_embeddable_block',
        severity='error',
    )]


def validate_canon_file(path: str, project_root: str) -> list[CanonFinding]:
    """Validate one canon file. Finding paths are project-root-relative so
    they display the way authors think about files."""
    rel = os.path.relpath(path, project_root)
    parsed = parse_canon_file(path)
    findings: list[CanonFinding] = []

    if not parsed['exists']:
        return findings  # callers handle missing files at the directory level

    # Runs BEFORE the two frontmatter early returns below, and must stay there.
    # It reads only `parsed['body']`, and so do the accessors that consume a
    # truncated anchor: `embeddable_block_text`, `get_canon_embeddable_block`,
    # `is_canon_block_populated`, and `prompts_illustrate.book_level_direction`
    # never look at frontmatter. Returning early past this check therefore
    # converted a reported truncation into an unreported one while the short
    # value was still being shipped to every prompt — a swallowed finding, not
    # deferred triage.
    findings.extend(_truncated_block_findings(rel, parsed))

    fm = parsed['frontmatter']
    if fm is _TRUNCATED:
        # 'error' severity: prompt-embedders can't read frontmatter from a
        # truncated file. Blocks downstream canon resolution.
        findings.append(_finding(
            rel,
            'canon file opens a frontmatter block with `---` but does not close it',
            'Close the frontmatter with a `---` line before the body',
            'canon_truncated_frontmatter',
            severity='error',
        ))
        return findings  # nothing else to check — frontmatter is unparseable
    from storyforge.common import get_medium
    required = ALWAYS_REQUIRED_FRONTMATTER_KEYS
    if get_medium(project_root) == 'graphic-novel':
        required = required + GN_ONLY_FRONTMATTER_KEYS

    if fm is None:
        # 'error' severity: a file without frontmatter can't be resolved by
        # canon_id; embedders rely on the YAML block. The key list in the
        # action text is medium-aware — `embeds_as` is GN-only
        # (GN_ONLY_FRONTMATTER_KEYS), so naming it here for a novel project
        # would tell the author to add a key nothing ever reads.
        findings.append(_finding(
            rel,
            'canon file is missing YAML frontmatter',
            'Add a --- delimited YAML block with ' + ', '.join(required),
            'canon_missing_frontmatter',
            severity='error',
        ))
        return findings  # nothing else to check without frontmatter

    for key in required:
        if not fm.get(key):
            findings.append(_finding(
                rel,
                f'missing required frontmatter key: {key}',
                f'Add `{key}: <value>` to the frontmatter',
                'canon_missing_key',
            ))

    canon_id = fm.get('canon_id', '')
    expected_id = _expected_canon_id(path)
    if canon_id and canon_id != expected_id:
        # 'error' severity: embedders resolve canon by canon_id; a mismatch
        # means lookups fail at prompt-assembly time.
        findings.append(_finding(
            rel,
            f'canon_id `{canon_id}` does not match filename slug `{expected_id}`',
            f'Set canon_id to `{expected_id}` or rename the file',
            'canon_id_mismatch',
            severity='error',
        ))
    if canon_id and not _SLUG_RE.match(canon_id):
        findings.append(_finding(
            rel,
            f'canon_id `{canon_id}` is not a valid slug '
            '(lowercase letters/digits/dashes only)',
            'Use lowercase letters, digits, and dashes only',
            'canon_id_invalid',
        ))

    canon_type = fm.get('canon_type', '')
    if canon_type and canon_type not in CANON_TYPES:
        findings.append(_finding(
            rel,
            f'canon_type `{canon_type}` is not one of: {", ".join(CANON_TYPES)}',
            f'Set canon_type to one of: {", ".join(CANON_TYPES)}',
            'canon_type_invalid',
        ))

    # Directory-vs-type rules: characters/foo.md must declare canon_type: character.
    canon_dir_abs = os.path.join(project_root, CANON_DIR)
    rel_to_canon = os.path.relpath(path, canon_dir_abs)
    parts = rel_to_canon.split(os.sep)
    if len(parts) == 1:
        if canon_type and canon_type not in ROOT_TYPES:
            findings.append(_finding(
                rel,
                f'canon_type `{canon_type}` is not allowed at the canon/ root '
                f'(must be one of: {", ".join(sorted(ROOT_TYPES))})',
                f'Move this file under canon/{canon_type}s/ or change the type',
                'canon_type_wrong_location',
            ))
    elif len(parts) == 2:
        subdir = parts[0]
        if subdir in SUBDIR_TYPE:
            expected_type = SUBDIR_TYPE[subdir]
            if canon_type and canon_type != expected_type:
                findings.append(_finding(
                    rel,
                    f'canon_type `{canon_type}` does not match subdir `{subdir}/` '
                    f'(expected `{expected_type}`)',
                    f'Set canon_type to `{expected_type}` or move the file',
                    'canon_type_wrong_location',
                ))
        else:
            findings.append(_finding(
                rel,
                f'unrecognized canon subdirectory: {subdir}/',
                f'Move the file to one of: {", ".join(sorted(SUBDIR_TYPE))} '
                'or to the canon/ root',
                'canon_unknown_subdir',
            ))
    else:
        # Depth ≥3 paths (e.g., canon/characters/lucien/portrait.md) bypass
        # the subdir-vs-type and registry checks. Flag rather than silently
        # accept — the canon schema only defines depth 1 (root) and depth 2
        # (subdir).
        findings.append(_finding(
            rel,
            f'canon file nested too deep ({len(parts)} levels under canon/)',
            'Move the file to canon/ or one of canon/characters/, '
            'canon/locations/, canon/motifs/',
            'canon_unexpected_nesting',
        ))

    for section in REQUIRED_SECTIONS:
        if section not in parsed['sections']:
            findings.append(_finding(
                rel,
                f'missing required H2 section: ## {section}',
                f'Add a `## {section}` section to the body',
                'canon_missing_section',
            ))

    # Unfilled-template check: scan section bodies for TODO placeholders
    # left over from the shipped starter templates. Surfaces as a single
    # finding per canon file (not per section) to keep the report
    # actionable — author opens the file and fills in the placeholders.
    placeholder_sections: list[str] = []
    for match in _SECTION_BODY_RE.finditer(parsed['body']):
        section_name = match.group(1).strip()
        body = match.group(2)
        if _section_body_is_placeholder(body):
            placeholder_sections.append(section_name)
    if placeholder_sections:
        sections_str = ', '.join(placeholder_sections)
        findings.append(_finding(
            rel,
            f'canon file has unfilled TODO placeholders in: {sections_str}',
            'Replace the TODO scaffolding with the actual canonical text',
            'canon_unfilled_template',
            severity='info',
        ))

    return findings


def _walk_canon_files(canon_dir: str) -> list[str]:
    """Return all author-managed canon .md files under canon_dir.

    Skips template files (`_template.md`, anything starting with `_` or `.`)
    and non-markdown files. Order is deterministic for stable reporting.
    """
    found: list[str] = []
    for root, _dirs, files in os.walk(canon_dir):
        for name in files:
            if not name.endswith('.md'):
                continue
            if _is_template_file(name):
                continue
            found.append(os.path.join(root, name))
    found.sort()
    return found


def _registry_findings(project_dir: str, files: list[str]) -> list[CanonFinding]:
    """Cross-reference canon files in characters/, locations/, motifs/ subdirs
    against their corresponding registry CSVs.

    A character canon file at characters/foo.md is expected to have a
    matching `id` row in reference/characters.csv. Absent CSVs are
    skipped silently — novel-style registry files are optional in
    graphic-novel mode. Malformed CSVs (no readable `id` column) emit
    one project-level finding rather than flagging every canon file as
    an orphan; the misdirection would point authors at the wrong fix.
    """
    canon_dir_abs = os.path.join(project_dir, CANON_DIR)
    findings: list[CanonFinding] = []
    registry_cache: dict[
        str, set[str] | None | Literal[_Sentinel.REGISTRY_MALFORMED],
    ] = {}
    malformed_reported: set[str] = set()

    for path in files:
        rel_to_canon = os.path.relpath(path, canon_dir_abs)
        parts = rel_to_canon.split(os.sep)
        if len(parts) != 2:
            continue
        subdir, filename = parts
        if subdir not in SUBDIR_REGISTRY:
            continue
        registry_file = SUBDIR_REGISTRY[subdir]
        if registry_file not in registry_cache:
            registry_cache[registry_file] = _read_registry_ids(
                project_dir, registry_file,
            )
        registry_ids = registry_cache[registry_file]
        if registry_ids is None:
            continue

        if registry_ids is _REGISTRY_MALFORMED:
            if registry_file not in malformed_reported:
                malformed_reported.add(registry_file)
                # 'error' severity: the registry is structurally broken;
                # canon validation can't run until it's repaired.
                findings.append(_finding(
                    os.path.join('reference', registry_file),
                    f'reference/{registry_file} is missing the `id` column '
                    f'(or is empty); canon cross-reference cannot run for '
                    f'canon/{subdir}/',
                    f'Repair reference/{registry_file} so the header includes '
                    '`id`',
                    'canon_registry_unreadable',
                    severity='error',
                ))
            continue
        slug = os.path.splitext(filename)[0]
        if slug not in registry_ids:
            rel = os.path.relpath(path, project_dir)
            findings.append(_finding(
                rel,
                f'canon id `{slug}` has no matching row in '
                f'reference/{registry_file}',
                f'Add an entry to reference/{registry_file} with id={slug}, '
                'or rename the canon file',
                'canon_missing_registry_entry',
            ))

    return findings


# Sentinel key used in the canon-path index to record that the directory
# has already been walked. Prevents re-walks on subsequent orphan lookups
# (which would otherwise re-iterate the entire canon tree once per
# unresolvable embed).
_INDEX_WALKED_SENTINEL = '__walked__'


def _resolve_canon_path(project_dir: str, canon_id: str,
                        index: dict[str, str]) -> str | None:
    """Return the absolute path of a canon file by canon_id. Builds the
    index lazily — caller maintains a single dict across one drift run.

    The full canon-dir walk runs at most once per drift run; subsequent
    lookups for unresolvable canon_ids return None from the populated
    index rather than re-walking.
    """
    if canon_id in index:
        return index[canon_id]
    if _INDEX_WALKED_SENTINEL in index:
        return None  # already walked; canon_id is genuinely orphan
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return None
    for path in _walk_canon_files(canon_dir):
        slug = os.path.splitext(os.path.basename(path))[0]
        index[slug] = path
    index[_INDEX_WALKED_SENTINEL] = ''
    return index.get(canon_id)


def resolve_canon_path(project_dir: str, canon_id: str) -> str | None:
    """Resolve a canon_id to its file path, root or subdirectory.

    Thin public wrapper over the cached internal resolver, for callers that
    look up one id and do not hold an index.
    """
    return _resolve_canon_path(project_dir, canon_id, {})


def canon_id_index(project_dir: str) -> dict[str, str]:
    """Map every canon file's declared `canon_id` (lowercased) to its path,
    relative to project_dir.

    This is deliberately NOT the same index `resolve_canon_path` builds:
    that one keys on the filename stem, which is only ever right when the
    file's `canon_id` matches its own filename — an assumption
    `canon_id_mismatch` and `canon_id_invalid` merely warn about rather than
    block. A caller that needs to know "does this id already exist
    anywhere" (an existence check before creating a new file, say) has to
    key on the id actually declared in frontmatter, or a mismatched or
    differently-cased stem lets a same-id file get written right past an
    existing one — silently truncating it in place on a case-insensitive
    filesystem, or shadowing it under a second path.

    Lowercased so a merely-differently-cased id still collides. On a
    genuine duplicate id, last-sorted-path wins — the same tie-break
    `anchor_texts` uses — so this index answers consistently with what
    `anchor_texts` would actually resolve for that id.
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return {}
    index: dict[str, str] = {}
    for path in _walk_canon_files(canon_dir):
        parsed = parse_canon_file(path)
        fm = parsed['frontmatter']
        if not isinstance(fm, dict):
            continue
        canon_id = (fm.get('canon_id') or '').strip().lower()
        if not canon_id:
            continue
        index[canon_id] = os.path.relpath(path, project_dir)
    return index


def check_canon_drift(project_dir: str) -> list[CanonFinding]:
    """Walk pages/*.md and compare each canon-embed to its source canon's
    `## Embeddable block`. Emits five finding types:

    - canon_drift (warning): embed text differs from the source after
      whitespace normalization. Author should re-embed.
    - canon_embed_orphan (error): the embed cites a canon_id that does
      not resolve to any canon file.
    - canon_embed_unclosed (error): an opener marker with no matching
      closer — the embed body is structurally invalid.
    - canon_embed_invalid_id (warning): the id captured by the opener
      isn't a valid slug (uppercase, underscore, etc.). The embed is
      not tracked for drift; author should fix the marker.
    - canon_page_unreadable (warning): the page file couldn't be read
      (binary content, broken encoding, permissions). The page is
      skipped for drift; author should investigate.

    Returns [] if there's no pages/ directory or no canon directory. The
    canon-source side does not re-emit canon_missing_section findings —
    validate_canon_file already covers that case, so a missing
    Embeddable block surfaces exactly once per affected canon file.
    """
    from storyforge.pages import list_page_files

    pages = list_page_files(project_dir)
    if not pages:
        return []
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return []

    findings: list[CanonFinding] = []
    canon_index: dict[str, str] = {}
    # Cache the NORMALIZED source text, not the raw source — avoids
    # re-running normalize_for_comparison on every embed-of-the-same-canon hit.
    normalized_source_cache: dict[str, str | None] = {}

    for page_path in pages:
        rel_page = os.path.relpath(page_path, project_dir)
        try:
            with open(page_path, encoding='utf-8') as f:
                page_text = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            # A single bad page file must not abort the cleanup pipeline.
            findings.append(_finding(
                rel_page,
                f'could not read page file for canon-drift check: {exc}',
                'Check the file for binary content, broken encoding, '
                'or permission issues',
                'canon_page_unreadable',
            ))
            continue
        embeds, unclosed, invalid = find_canon_embeds(page_text)
        for u in unclosed:
            findings.append(_finding(
                rel_page,
                f'canon-embed opener `{u["canon_id"]}` has no matching '
                '<!-- /canon-embed --> closer',
                'Close the embed block with a `<!-- /canon-embed -->` '
                'line before the next opener or end of file',
                'canon_embed_unclosed',
                severity='error',
            ))
        for inv in invalid:
            findings.append(_finding(
                rel_page,
                f'canon-embed id `{inv["raw_id"]}` is not a valid slug '
                '(lowercase letters/digits/dashes only)',
                'Fix the id in the canon-embed opener',
                'canon_embed_invalid_id',
            ))
        for embed in embeds:
            cid = embed['canon_id']
            canon_path = _resolve_canon_path(project_dir, cid, canon_index)
            if canon_path is None:
                findings.append(_finding(
                    rel_page,
                    f'canon-embed cites unknown canon_id `{cid}`',
                    f'Add reference/canon/.../{cid}.md or fix the embed',
                    'canon_embed_orphan',
                    severity='error',
                ))
                continue
            if cid not in normalized_source_cache:
                raw_source = embeddable_block_text(canon_path)
                normalized_source_cache[cid] = (
                    normalize_for_comparison(raw_source)
                    if raw_source is not None else None
                )
            normalized_source = normalized_source_cache[cid]
            if normalized_source is None:
                # validate_canon_file already emits canon_missing_section
                # for this case — skip silently to avoid duplicate findings.
                continue
            if normalized_source != embed['normalized']:
                findings.append(_finding(
                    rel_page,
                    f'canon-embed `{cid}` has drifted from '
                    f'reference/canon/.../{cid}.md',
                    f'Re-embed from the source canon file',
                    'canon_drift',
                ))
    return findings


def is_canon_block_populated(project_dir: str, canon_id: str) -> bool:
    """Return True if reference/canon/<canon_id>.md exists, has an
    "## Embeddable block" section, and that section's body is NOT
    placeholder TODO text.

    Used by elaborate --stage page-architecture as a precondition:
    if the canon vocabulary the prompt depends on (panel-registers,
    page-rhythm-rules) is still TODO, the LLM can't reliably cite
    the registers, so the stage refuses to run.

    Note: an empty embeddable-block body (the header exists but no content
    follows) is treated as populated, not placeholder. If an empty block
    causes problems, populate it or add a TODO line to trigger the
    canon_unfilled_template finding.
    """
    path = os.path.join(project_dir, 'reference', 'canon', f'{canon_id}.md')
    if not os.path.isfile(path):
        return False
    block_text = embeddable_block_text(path)
    if block_text is None:
        return False
    return not _section_body_is_placeholder(block_text)


def get_canon_embeddable_block(project_dir: str, canon_id: str) -> str:
    """Return the embeddable block text for canon_id, or '' if absent
    or unparseable.

    Used by elaborate --stage page-architecture and other consumers
    that need to embed canon blocks into LLM prompts. The returned
    string is stripped; '' indicates either the canon file does not
    exist, has no '## Embeddable block' section, or the section body
    is empty.

    See also: is_canon_block_populated, which is the precondition
    check that gates whether the block should be used.
    """
    path = os.path.join(project_dir, 'reference', 'canon', f'{canon_id}.md')
    if not os.path.isfile(path):
        return ''
    return (embeddable_block_text(path) or '').strip()


def anchor_texts(project_dir: str) -> dict[str, str]:
    """Map canon_id -> verbatim anchor text for every entity canon file.

    Skips files whose Embeddable block is missing or still placeholder text:
    a scaffold sent to an image model as though it were direction is worse
    than sending nothing, because it reads as a deliberate instruction.

    Walks via `_walk_canon_files` (not a hand-rolled `os.walk`) so this
    accessor shares two guarantees with every other reader of the canon
    tree: starter templates (`_template.md`) are excluded — their
    Embeddable block is instructional prose, not a TODO stub, so the
    placeholder check alone would not catch them — and traversal order is
    deterministic (sorted by full path) so a duplicate `canon_id` across
    directories resolves to the same winner on every machine.
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return {}

    anchors: dict[str, str] = {}
    for path in _walk_canon_files(canon_dir):
        parsed = parse_canon_file(path)
        fm = parsed['frontmatter']
        if not isinstance(fm, dict):
            continue
        if fm.get('canon_type') not in ENTITY_CANON_TYPES:
            continue
        canon_id = (fm.get('canon_id') or '').strip()
        if not canon_id:
            continue
        body = embeddable_block_text(path)
        if body is None or _section_body_is_placeholder(body):
            continue
        anchors[canon_id] = body.strip()
    return anchors


class CanonGate(TypedDict):
    """`validate`'s view of canon: what blocks, and what merely reports."""
    errors: list[CanonFinding]
    other: list[CanonFinding]


def canon_gate(project_dir: str) -> CanonGate:
    """Split canon findings into the blocking and the reportable.

    `error` severity on a canon finding used to mean nothing: `cleanup` was the
    only command that ran canon validation and it returns `None` on every path,
    so `canon_truncated_frontmatter`, `canon_id_mismatch` and
    `canon_registry_unreadable` all printed and blocked nothing. `cmd_validate`
    folds `errors` into its exit code, which puts canon where every other
    blocking check in this project already lives (#295).

    Only `error` blocks. `canon_unfilled_template` is `info` and warnings leave a
    working project, so a book mid-`--direction` still validates — gating on
    those would make the check impossible to adopt, which is how a gate gets
    turned off wholesale.

    A project with no `reference/canon/` yields nothing, matching
    `cmd_cleanup.report_canon_files`' own guard: never having run `--direction`
    is valid in-flight state, not a failure.
    """
    if not os.path.isdir(os.path.join(project_dir, CANON_DIR)):
        return {'errors': [], 'other': []}
    findings = validate_canon_directory(project_dir)
    return {
        'errors': [f for f in findings if f['severity'] == 'error'],
        'other': [f for f in findings if f['severity'] != 'error'],
    }


def truncated_anchor_ids(
    project_dir: str,
) -> dict[str, list[BlockTruncation]]:
    """Every canon file whose Embeddable block is cut short, keyed by canon_id.

    The shared source `illustrations.validate_plan`, `--prompts` and the packet
    all read, so a truncated anchor is diagnosed identically wherever it is
    caught. `validate_canon_file` reports the same condition per *file* for the
    cleanup report; this exists because that report gates nothing and the
    consumers that actually spend money on a short anchor needed something to
    check (#293).

    Entity anchors and the three book-level files both — a truncated
    `visual-vocabulary` ships partial house style to every prompt in the book,
    which is worse than one character's anchor being short. Keys are `canon_id`
    so a plan row's `canon_refs` matches directly, and traversal is
    `_walk_canon_files` so starter templates stay out and order is
    deterministic, exactly as in `anchor_texts`.
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return {}

    out: dict[str, list[BlockTruncation]] = {}
    for path in _walk_canon_files(canon_dir):
        parsed = parse_canon_file(path)
        fm = parsed['frontmatter']
        canon_id = (
            (fm.get('canon_id') or '').strip() if isinstance(fm, dict) else ''
        ) or os.path.splitext(os.path.basename(path))[0]
        truncations = embeddable_block_truncations(parsed['body'])
        if truncations:
            out[canon_id] = truncations
    return out


#: `canon_updated: YYYY-MM-DD`. ISO dates sort lexicographically, so the
#: newest one is just `max()` over the parseable values — no date arithmetic,
#: and nothing to get wrong across timezones.
_ISO_DATE_RE = re.compile(r'\A(\d{4})-(\d{2})-(\d{2})\Z')


def iso_date_or_empty(value: str) -> str:
    """Return the ISO date at the head of *value*, or '' if there isn't one.

    Accepts a bare date and a timestamp (the date part is taken), because a
    hand-written `canon_updated` or `ingested_at` may carry a time. Anything
    else returns '' — the caller decides what an unusable date means rather
    than comparing garbage.
    """
    head = (value or '').strip()[:10]
    return head if _ISO_DATE_RE.match(head) else ''


def predates_canon(*, when: str, cutoff: str) -> bool:
    """True when *when* is strictly older than the canon cutoff.

    The one comparison every staleness check **against the canon cutoff** makes,
    in one place: the ingested-render check in
    `illustrations.stale_render_reason` and the style-reference check in
    `cmd_illustrate.resolve_style_reference`. `packet._staging_postdates_render`
    is the same predicate against a *different* cutoff (`treatment_at` versus
    `ingested_at`) and still rolls its own, restating the same-day rule below —
    #281 will want both in its inventory.

    Keyword-only: the two arguments are both ISO date strings, they carry
    deliberately different unknown-value policies (see below), and swapping them
    inverts the result with no crash and no test failure at the call site.

    ISO dates sort lexicographically, so this is a string compare — no date
    arithmetic, nothing to get wrong across timezones.

    **Strictly** older: an artifact dated the *same day* the canon was last
    touched is not stale, because same-day is the ordinary incremental loop
    (write canon, render, ingest, prompt the next one) and date granularity
    cannot separate the two. Treating same-day as stale would empty the
    reference chain on every normal run.

    An unparseable or empty date on either side is **not** older. Callers
    disagree about what an unknown date means — an empty `ingested_at` counts
    as pre-canon because the column postdates the plan schema, while a file
    whose mtime cannot be read says nothing at all — so each states its own
    policy rather than inheriting one from here.
    """
    left = iso_date_or_empty(when)
    right = iso_date_or_empty(cutoff)
    return bool(left and right and left < right)


def newest_canon_updated(project_dir: str) -> str:
    """The most recent `canon_updated` date across the canon tree, or ''.

    This is the cutoff a consumer compares its own artifacts against: art
    rendered before the newest canon edit was directed by canon that no
    longer applies. Returns '' when there is no canon directory or no file
    carries a parseable date — with no governing date, nothing can be judged
    stale, and inventing a cutoff would silently discard every reference.

    An unparseable `canon_updated` is logged rather than skipped quietly: a
    file whose date cannot be read cannot raise the cutoff, so a canon edit
    can look older than it is.
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return ''

    newest = ''
    for path in _walk_canon_files(canon_dir):
        fm = parse_canon_file(path)['frontmatter']
        if not isinstance(fm, dict):
            continue
        raw = (fm.get('canon_updated') or '').strip()
        if not raw:
            continue
        parsed = iso_date_or_empty(raw)
        if not parsed:
            log(f'WARNING: {os.path.relpath(path, project_dir)} has '
                f'canon_updated={raw!r}, which is not an ISO date '
                f'(YYYY-MM-DD); it cannot count toward the canon cutoff that '
                f'decides whether earlier art is stale.')
            continue
        newest = max(newest, parsed)
    return newest


class AnchorLabel(TypedDict):
    """The human-readable name for one anchor, and where it came from.

    `source` is carried so a caller can report the fallback: an anchor
    labeled from its slug means no one ever wrote the entity's name down,
    which is worth a line in the log but is not an error.
    """
    label: str
    source: Literal['frontmatter', 'registry', 'slug']


#: Registry CSV per entity canon type. Composed from the two existing maps
#: rather than written out again, so a new entity type cannot be added to one
#: and forgotten in the other.
REGISTRY_BY_TYPE: dict[CanonType, str] = {
    SUBDIR_TYPE[subdir]: registry
    for subdir, registry in SUBDIR_REGISTRY.items()
}


def anchor_display_names(project_dir: str) -> dict[str, AnchorLabel]:
    """Map canon_id -> the display name to use when *rendering* that anchor.

    `canon_id` stays the matching key everywhere (plan `canon_refs`, the
    anchor dict from `anchor_texts`); this is only what a human-facing
    document should call the entity. A prompt that labels an anchor with its
    slug gets the slug echoed back in the model's prose ("kneeling are leo —
    ten, warm light-brown skin…"), which is text the author pastes into an
    image model.

    Resolution order, each step a deliberate authority:

    1. `display_name` in the canon file's frontmatter — the author said so.
    2. the `name` column of the matching registry row — already canonical,
       and the same source `--direction` names its stubs from.
    3. the humanized slug — `great-lamp` becomes `Great Lamp`.

    Keyed to match `anchor_texts`, walked the same way (so template files are
    excluded and duplicate ids resolve to the same winner). Unlike
    `anchor_texts` this does not skip placeholder Embeddable blocks: a name is
    a name whether or not the anchor text is written yet, and extra keys are
    harmless to callers that look labels up by anchor key.
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return {}

    registry_names: dict[str, dict[str, str]] = {}
    labels: dict[str, AnchorLabel] = {}
    for path in _walk_canon_files(canon_dir):
        fm = parse_canon_file(path)['frontmatter']
        if not isinstance(fm, dict):
            continue
        canon_type = fm.get('canon_type')
        if canon_type not in ENTITY_CANON_TYPES:
            continue
        canon_id = (fm.get('canon_id') or '').strip()
        if not canon_id:
            continue

        declared = (fm.get('display_name') or '').strip()
        if declared:
            labels[canon_id] = {'label': declared, 'source': 'frontmatter'}
            continue

        registry_file = REGISTRY_BY_TYPE.get(canon_type, '')
        if registry_file and registry_file not in registry_names:
            registry_names[registry_file] = _read_registry_names(
                project_dir, registry_file)
        from_registry = (registry_names.get(registry_file, {})
                         .get(canon_id.lower(), '').strip())
        if from_registry:
            labels[canon_id] = {'label': from_registry, 'source': 'registry'}
            continue

        labels[canon_id] = {'label': humanize_canon_id(canon_id),
                            'source': 'slug'}
    return labels


def humanize_canon_id(canon_id: str) -> str:
    """Title-case a canon slug into a readable label. `great-lamp` -> `Great Lamp`.

    The last-resort label. `str.title()` is deliberate over `capitalize()`:
    every word of a multi-word entity should read as a name.
    """
    words = (canon_id or '').replace('_', ' ').replace('-', ' ').split()
    return ' '.join(w[:1].upper() + w[1:] for w in words) or canon_id


def _read_registry_names(project_dir: str,
                         registry_filename: str) -> dict[str, str]:
    """Map lowercased registry `id` -> `name` for one registry CSV.

    Returns {} when the file is absent, has no header, or has no `id`/`name`
    columns — the caller falls back to the humanized slug, which is a
    cosmetic downgrade, not a failure. Kept separate from
    `_read_registry_ids`, whose malformed/absent distinction exists to drive
    findings this caller has no use for.
    """
    csv_path = os.path.join(project_dir, 'reference', registry_filename)
    if not os.path.isfile(csv_path):
        return {}
    names: dict[str, str] = {}
    with open(csv_path, encoding='utf-8') as f:
        header = f.readline().rstrip('\n')
        if not header:
            return {}
        cols = header.split('|')
        if 'id' not in cols or 'name' not in cols:
            return {}
        id_idx, name_idx = cols.index('id'), cols.index('name')
        for line in f:
            parts = line.rstrip('\n').split('|')
            if id_idx >= len(parts) or name_idx >= len(parts):
                continue
            key = parts[id_idx].strip().lower()
            value = parts[name_idx].strip()
            if key and value:
                names[key] = value
    return names


def validate_canon_directory(project_dir: str) -> list[CanonFinding]:
    """Validate every canon file under reference/canon/. Returns [] when
    the canon directory is absent; callers decide whether absence is itself
    a finding (cleanup's report_canon_files does for GN projects).

    Also runs drift detection against pages/*.md if both directories exist.
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return []

    findings: list[CanonFinding] = []
    files = _walk_canon_files(canon_dir)
    for path in files:
        findings.extend(validate_canon_file(path, project_dir))
    findings.extend(_registry_findings(project_dir, files))
    findings.extend(check_canon_drift(project_dir))
    return findings
