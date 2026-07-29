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
from typing import Literal, TypedDict

from storyforge.common import normalize_for_comparison

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
    'canon_unfilled_template',
    'canon_registry_unreadable',
    'canon_missing_registry_entry',
    'canon_embed_orphan',
    'canon_embed_unclosed',
    'canon_embed_invalid_id',
    'canon_page_unreadable',
    'canon_drift',
]


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
    frontmatter: dict[str, str] | None
    sections: set[str]
    body: str


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

REQUIRED_SECTIONS = (
    'Embeddable block',
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


class _Sentinel(enum.Enum):
    """Distinct sentinel values returned by parser helpers when the input
    is malformed in a way that the caller needs to distinguish from a
    normal result. Using an enum (rather than ad-hoc `object()` or string
    sentinels) gives both narrow Literal types and stable `is` identity.
    """
    TRUNCATED = enum.auto()
    REGISTRY_MALFORMED = enum.auto()


_TRUNCATED = _Sentinel.TRUNCATED
_REGISTRY_MALFORMED = _Sentinel.REGISTRY_MALFORMED

_FRONTMATTER_RE = re.compile(r'\A---\s*\n(.*?\n)---\s*(?:\n|$)', re.DOTALL)
_SECTION_RE = re.compile(r'^##\s+(.+?)\s*$', re.MULTILINE)
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


_EMBEDDABLE_BLOCK_RE = re.compile(
    r'^##\s+Embeddable block\s*\n(.*?)(?=^##\s|\Z)',
    re.MULTILINE | re.DOTALL,
)

_SECTION_BODY_RE = re.compile(
    r'^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)',
    re.MULTILINE | re.DOTALL,
)

# Lines that mark a section as unfilled scaffolding. Stripped of leading
# `<!--` HTML-comment fragments and surrounding whitespace, a section
# body that starts with one of these strings is considered placeholder.
_PLACEHOLDER_PREFIXES = ('TODO', 'TODO —', 'TODO -', 'TODO.', 'TODO:')

# A line wholly wrapped in markdown emphasis. The (now-retired)
# illustration-direction coach/strict templates emitted their instructions
# this way (`_(fill this in)_`, `_Required: describe the palette_`), so a
# section made of nothing but an emphasized line is boilerplate by
# construction. Ported verbatim from illustrations._EMPHASIZED_LINE_RE (Task
# 7 fix round 1, .superpowers/sdd/2026-07-28-illustration-canon-adoption/)
# rather than reinvented, so the same shapes stay recognized now that
# placeholder detection is shared here instead of duplicated per module.
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

    Strips leading HTML comments (the starter templates wrap orienting
    comments in `<!-- ... -->`) and checks whether the first non-blank line
    reads as scaffolding: a `TODO`-prefixed line (what every shipped
    template — GN canon, and formerly illustration-direction's own
    templates — actually emits), a line wholly wrapped in markdown emphasis
    (the retired illustration-direction coach/strict templates' shape for
    instructional text), or a bare TBD/n-a/fill-this-in an author might type
    by hand instead. False positives are unlikely: authors using one of
    these as an inline note typically place it mid-text, not as the first
    content line of a required section.

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
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in _PLACEHOLDER_PREFIXES):
            return True
        if _EMPHASIZED_LINE_RE.match(stripped):
            return True
        return bool(_BARE_PLACEHOLDER_RE.match(stripped))
    return False


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
        }
    with open(path, encoding='utf-8') as f:
        text = f.read()
    # Strip BOM so frontmatter parsing isn't disabled by editors that
    # auto-write one (Notion/Word/etc.).
    if text.startswith('﻿'):
        text = text.lstrip('﻿')
    frontmatter, body = _parse_frontmatter(text)
    sections = {m.group(1).strip() for m in _SECTION_RE.finditer(body)}
    return {
        'path': path,
        'exists': True,
        'frontmatter': frontmatter,
        'sections': sections,
        'body': body,
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


def validate_canon_file(path: str, project_root: str) -> list[CanonFinding]:
    """Validate one canon file. Finding paths are project-root-relative so
    they display the way authors think about files."""
    rel = os.path.relpath(path, project_root)
    parsed = parse_canon_file(path)
    findings: list[CanonFinding] = []

    if not parsed['exists']:
        return findings  # callers handle missing files at the directory level

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
