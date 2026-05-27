"""Canon file parsing and validation for graphic-novel projects.

Canon files live under `reference/canon/` and document the canonical
visual blocks that get embedded inline into per-panel prompts. Each file
has YAML frontmatter (canon_id, canon_type, etc.) and four required H2
body sections: Embeddable block, Clauses, Related canon, Iteration
history. See issue #254 for the full spec.

This is the deterministic foundation. The following remain deferred
until per-page files (#251) land:

- Drift detection between canonical source and inline copies in pages/
- Hone canon-id normalization against registries
- script-package bundling of canon into the artist handoff
"""

import os
import re

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


def _parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """Extract YAML-style frontmatter as a flat dict.

    Returns (None, '') if the file does not start with `---`. Only flat
    `key: value` lines are supported — canon files do not use nested
    structures.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
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


def parse_canon_file(path: str) -> dict:
    """Read a canon file from disk and return a parsed representation.

    Returns:
        {
          'path': absolute file path,
          'exists': bool,
          'frontmatter': dict | None,   # None if missing
          'sections': set[str],          # H2 headings found in the body
          'body': str,                   # text after the frontmatter
        }
    """
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


def _read_registry_ids(project_dir: str, registry_filename: str) -> set[str] | None:
    """Read the `id` column of a registry CSV; None if the file is absent."""
    csv_path = os.path.join(project_dir, 'reference', registry_filename)
    if not os.path.isfile(csv_path):
        return None
    ids: set[str] = set()
    with open(csv_path, encoding='utf-8') as f:
        header = f.readline().rstrip('\n')
        if not header:
            return ids
        cols = header.split('|')
        try:
            id_idx = cols.index('id')
        except ValueError:
            return ids
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
             type_: str, severity: str = 'warning') -> dict:
    return {
        'type': type_,
        'file': file_rel,
        'detail': detail,
        'action': action,
        'severity': severity,
    }


def validate_canon_file(path: str, project_root: str) -> list[dict]:
    """Validate a single canon file. Returns a list of finding dicts.

    Findings are returned with paths relative to project_root so they
    display the way authors think about files. Subdir-based rules
    (canon_type must be 'character' under characters/, etc.) are applied
    here so that misfiled canon is caught.
    """
    rel = os.path.relpath(path, project_root)
    parsed = parse_canon_file(path)
    findings: list[dict] = []

    if not parsed['exists']:
        return findings  # callers handle missing files at the directory level

    fm = parsed['frontmatter']
    if fm is None:
        findings.append(_finding(
            rel,
            'canon file is missing YAML frontmatter',
            'Add a --- delimited YAML block with canon_id, canon_type, '
            'canon_updated, appears_in, embeds_as, first_appearance',
            'canon_missing_frontmatter',
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
        findings.append(_finding(
            rel,
            f'canon_id `{canon_id}` does not match filename slug `{expected_id}`',
            f'Set canon_id to `{expected_id}` or rename the file',
            'canon_id_mismatch',
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


def _registry_findings(project_dir: str, files: list[str]) -> list[dict]:
    """Cross-reference canon files in characters/, locations/, motifs/ subdirs
    against their corresponding registry CSVs.

    A character canon file at characters/foo.md is expected to have a
    matching `id` row in reference/characters.csv. When the registry CSV
    is missing entirely we skip the check rather than spam findings —
    novel-style registry files are optional in graphic-novel mode.
    """
    canon_dir_abs = os.path.join(project_dir, CANON_DIR)
    findings: list[dict] = []
    registry_cache: dict[str, set[str] | None] = {}

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
            continue  # registry not present; skip silently
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


def validate_canon_directory(project_dir: str) -> list[dict]:
    """Validate every canon file under reference/canon/.

    Returns an empty list if the canon directory does not exist (no
    finding) — projects without canon are not necessarily broken, this
    foundation is opt-in. Callers in cleanup decide whether absence is
    itself a finding (it currently is not — see report_canon_files).
    """
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if not os.path.isdir(canon_dir):
        return []

    findings: list[dict] = []
    files = _walk_canon_files(canon_dir)
    for path in files:
        findings.extend(validate_canon_file(path, project_dir))
    findings.extend(_registry_findings(project_dir, files))
    return findings
