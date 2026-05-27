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
walks every page file under `pages/` and compares each embed to its
source canon's `## Embeddable block` section.
"""

import os
import re
from typing import Literal, TypedDict

# Severity is part of the cleanup-report contract — build_cleanup_report
# filters action items by != 'info' and counts errors/warnings/info. A
# typo on either side silently demotes a finding.
Severity = Literal['info', 'warning', 'error']


class _CanonFindingRequired(TypedDict):
    type: str
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

CANON_TYPES = ('foundation', 'vocabulary', 'rules', 'character', 'location', 'motif')

REQUIRED_FRONTMATTER_KEYS = (
    'canon_id',
    'canon_type',
    'canon_updated',
    'appears_in',
    'embeds_as',
    'first_appearance',
)

REQUIRED_SECTIONS = (
    'Embeddable block',
    'Clauses',
    'Related canon',
    'Iteration history',
)

SUBDIR_TYPE = {
    'characters': 'character',
    'locations': 'location',
    'motifs': 'motif',
}

SUBDIR_REGISTRY = {
    'characters': 'characters.csv',
    'locations': 'locations.csv',
    'motifs': 'motif-taxonomy.csv',
}

ROOT_TYPES = {'foundation', 'vocabulary', 'rules'}

_FRONTMATTER_RE = re.compile(r'\A---\s*\n(.*?\n)---\s*(?:\n|$)', re.DOTALL)
_SECTION_RE = re.compile(r'^##\s+(.+?)\s*$', re.MULTILINE)
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')

# Canon-embed markers: opener carries the canon_id, closer is fixed text.
_CANON_EMBED_RE = re.compile(
    r'<!--\s*canon-embed:\s*([a-z0-9][a-z0-9-]*)\s*-->'
    r'(.*?)'
    r'<!--\s*/canon-embed\s*-->',
    re.DOTALL,
)


class CanonEmbed(TypedDict):
    """One canon-embed block found in a page file body."""
    canon_id: str
    text: str          # raw text between the markers (with outer whitespace)
    normalized: str    # whitespace-normalized text, used for drift comparison


def _normalize_for_drift(text: str) -> str:
    """Normalize text for drift comparison. Trims outer whitespace and
    collapses internal blank-line runs so that cosmetic whitespace shifts
    (a stray blank line, trailing-space drift) don't surface as drift."""
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln:
            if not blank:
                out.append('')
            blank = True
        else:
            out.append(ln)
            blank = False
    return '\n'.join(out)


def find_canon_embeds(text: str) -> list[CanonEmbed]:
    """Return every canon-embed block found in `text`, in source order."""
    embeds: list[CanonEmbed] = []
    for match in _CANON_EMBED_RE.finditer(text):
        canon_id = match.group(1)
        raw = match.group(2)
        embeds.append({
            'canon_id': canon_id,
            'text': raw,
            'normalized': _normalize_for_drift(raw),
        })
    return embeds


_EMBEDDABLE_BLOCK_RE = re.compile(
    r'^##\s+Embeddable block\s*\n(.*?)(?=^##\s|\Z)',
    re.MULTILINE | re.DOTALL,
)


def _embeddable_block_text(canon_path: str) -> str | None:
    """Return the verbatim text of a canon file's `## Embeddable block`
    section. None if the file is missing or has no such section.
    """
    parsed = parse_canon_file(canon_path)
    if not parsed['exists']:
        return None
    body = parsed['body']
    match = _EMBEDDABLE_BLOCK_RE.search(body)
    if not match:
        return None
    return match.group(1)


_TRUNCATED = object()


def _parse_frontmatter(text: str) -> tuple[dict[str, str] | None | object, str]:
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


_REGISTRY_MALFORMED = 'malformed'


def _read_registry_ids(project_dir: str, registry_filename: str
                       ) -> set[str] | None | str:
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
             type_: str, severity: Severity = 'warning') -> CanonFinding:
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
    if fm is None:
        # 'error' severity: a file without frontmatter can't be resolved by
        # canon_id; embedders rely on the YAML block.
        findings.append(_finding(
            rel,
            'canon file is missing YAML frontmatter',
            'Add a --- delimited YAML block with canon_id, canon_type, '
            'canon_updated, appears_in, embeds_as, first_appearance',
            'canon_missing_frontmatter',
            severity='error',
        ))
        return findings  # nothing else to check without frontmatter

    for key in REQUIRED_FRONTMATTER_KEYS:
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
    registry_cache: dict[str, set[str] | None | str] = {}
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


def _resolve_canon_path(project_dir: str, canon_id: str,
                        index: dict[str, str]) -> str | None:
    """Return the absolute path of a canon file by canon_id. Builds the
    index lazily — caller maintains a single dict across one drift run."""
    if canon_id in index:
        return index[canon_id]
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return None
    for path in _walk_canon_files(canon_dir):
        slug = os.path.splitext(os.path.basename(path))[0]
        index[slug] = path
    return index.get(canon_id)


def check_canon_drift(project_dir: str) -> list[CanonFinding]:
    """Walk pages/*.md and compare each canon-embed to its source canon's
    `## Embeddable block`. Emits two finding types:

    - canon_drift (warning): the embed text differs from the source after
      whitespace normalization. Author should re-embed.
    - canon_embed_orphan (error): the embed cites a canon_id that does
      not resolve to any canon file. The prompt is structurally broken.

    Returns [] if there's no pages/ directory or no canon directory. Page
    files without frontmatter are still scanned for embeds — the embed
    convention works even outside the page-file schema.
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
    source_cache: dict[str, str | None] = {}

    for page_path in pages:
        with open(page_path, encoding='utf-8') as f:
            page_text = f.read()
        embeds = find_canon_embeds(page_text)
        rel_page = os.path.relpath(page_path, project_dir)
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
            if cid not in source_cache:
                source_cache[cid] = _embeddable_block_text(canon_path)
            source = source_cache[cid]
            if source is None:
                rel_canon = os.path.relpath(canon_path, project_dir)
                findings.append(_finding(
                    rel_canon,
                    'canon file has no `## Embeddable block` section to '
                    'compare embeds against',
                    'Add a `## Embeddable block` section with the verbatim '
                    'canonical text',
                    'canon_missing_section',
                ))
                continue
            if _normalize_for_drift(source) != embed['normalized']:
                findings.append(_finding(
                    rel_page,
                    f'canon-embed `{cid}` has drifted from '
                    f'reference/canon/.../{cid}.md',
                    f'Re-embed from the source canon file',
                    'canon_drift',
                ))
    return findings


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
