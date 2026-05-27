"""Per-page file (graphic-novel mode) parsing and validation.

GN projects can break scenes into per-page files at pages/<prefix>-pN.md.
Each file has YAML frontmatter and a markdown body. See issue #251 and
docs/superpowers/plans/2026-05-27-gn-per-page-files.md for the schema.

The scene file (scenes/<scene_id>.md) remains the creative source of
truth; page files are the atomic per-page working units consumed by
extract, script-package, and cleanup.
"""

import os
import re
from typing import Final, TypedDict


# Frontmatter: open with `---\n`, capture everything (possibly empty) up to
# the next `---\n` line, capture the body. `(?:\n|$)` allows the closing
# `---` to be followed by either a newline or EOF.
FRONTMATTER_RE = re.compile(r'\A---\n(.*?)---(?:\n|$)(.*)', re.DOTALL)

REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    'page_id', 'scene_id', 'page_within_scene',
    'total_pages_in_scene', 'panel_count',
)

RECOMMENDED_FIELDS: Final[tuple[str, ...]] = (
    'spread_position', 'characters_present', 'location', 'timeline',
)

_INTEGER_FIELDS: Final[set[str]] = {
    'page_within_scene', 'total_pages_in_scene', 'panel_count',
}

_LIST_FIELDS: Final[set[str]] = {'characters_present'}


class PageFile(TypedDict, total=False):
    path: str
    body: str
    page_id: str
    scene_id: str
    page_within_scene: int
    total_pages_in_scene: int
    panel_count: int
    spread_position: str
    characters_present: list[str]
    location: str
    timeline: str
    extra: dict[str, str]
    extra_lists: dict[str, list[str]]


def page_id_prefix_for_scene(scene_id: str) -> str:
    """Return the prefix that page files for a scene should use.

    Convention: if scene_id starts with `s` + digits + `-`, the prefix is
    the leading `s\\d+` token (so `s01-studio-finalization` -> `s01`).
    Otherwise the full scene_id is the prefix (`the-blank-page` ->
    `the-blank-page`). Keeps both naming conventions tractable.
    """
    m = re.match(r'^(s\d+)-', scene_id)
    return m.group(1) if m else scene_id


def page_filename_for(scene_id: str, page_num: int) -> str:
    """Return the page file basename (without directory)."""
    return f'{page_id_prefix_for_scene(scene_id)}-p{page_num}.md'


def parse_page_file(path: str) -> PageFile | None:
    """Parse a single page file. Returns None if the file is missing or
    has no YAML frontmatter.

    CRLF line endings are normalized to LF before regex matching — page
    files authored on Windows or pasted from a clipboard with CRLF would
    otherwise fail the frontmatter regex and surface as `no_frontmatter`
    even when the structure is correct.
    """
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        text = f.read()
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    page = _parse_frontmatter(m.group(1))
    page['path'] = path
    page['body'] = m.group(2)
    return page


def _parse_frontmatter(block: str) -> PageFile:
    """Parse a YAML-subset frontmatter block.

    Supports `key: value`, `key: [a, b, c]` inline lists, and block lists:

        key:
          - item
          - item

    Trailing `# comment` on list items is stripped. Integer coercion is
    applied to fields in `_INTEGER_FIELDS`; values that fail coercion are
    recorded in `extra['_bad_integer_fields']` so validate_page_file can
    surface them as findings (NOT silently stored as strings under an
    integer-typed key). Unknown scalars go into `extra`; unknown block
    lists go into `extra_lists`. This is a deliberate subset of YAML —
    we don't depend on PyYAML elsewhere and don't want to start here.

    Limitations: inline-list items must not contain unescaped commas
    (the parser splits on `,`). For multi-word list items, use the
    block form.
    """
    page: PageFile = {'extra': {}, 'extra_lists': {}}
    current_list_key: str | None = None

    for raw in block.splitlines():
        line = raw.rstrip()
        if not line:
            current_list_key = None
            continue

        if line.startswith('  - ') and current_list_key:
            item = line[4:].strip()
            if '#' in item:
                item = item.split('#', 1)[0].strip()
            if current_list_key in _LIST_FIELDS:
                page.setdefault(current_list_key, []).append(item)
            else:
                page['extra_lists'].setdefault(current_list_key, []).append(item)
            continue

        if line.startswith(' '):
            continue

        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()
        current_list_key = None

        if not value:
            current_list_key = key
            if key in _LIST_FIELDS:
                page[key] = []
            else:
                page['extra_lists'][key] = []
            continue

        if value.startswith('[') and value.endswith(']'):
            items = [x.strip() for x in value[1:-1].split(',') if x.strip()]
            if key in _LIST_FIELDS:
                page[key] = items
            else:
                page['extra_lists'][key] = items
            continue

        if key in _INTEGER_FIELDS:
            try:
                page[key] = int(value)
                continue
            except ValueError:
                # Don't silently stash a string under an integer-typed key:
                # downstream validators gate on isinstance(...int), so a
                # non-int value would defeat range checks. Track the bad
                # field so validate_page_file can surface it.
                page['extra'].setdefault('_bad_integer_fields', '')
                bad = page['extra']['_bad_integer_fields']
                page['extra']['_bad_integer_fields'] = (
                    f'{bad};{key}' if bad else key
                )
                continue

        if key in REQUIRED_FIELDS or key in RECOMMENDED_FIELDS:
            page[key] = value
        else:
            page['extra'][key] = value

    return page


def list_page_files(project_dir: str) -> list[str]:
    """Return sorted absolute paths of pages/*.md, or [] if no pages dir."""
    pages_dir = os.path.join(project_dir, 'pages')
    if not os.path.isdir(pages_dir):
        return []
    return sorted(
        os.path.join(pages_dir, f)
        for f in os.listdir(pages_dir)
        if f.endswith('.md') and not f.startswith('.')
    )


def pages_for_scene(project_dir: str, scene_id: str) -> list[PageFile]:
    """Return parsed PageFile dicts for a scene, sorted by page_within_scene.

    Pages are matched first by filename prefix via page_id_prefix_for_scene,
    then (when the page file's frontmatter carries a `scene_id`) by exact
    `scene_id` match. The double-filter guards against the sN-prefix
    collision case: if two scenes are `s01-alpha` and `s01-bravo`, both
    would share the `s01-` filename prefix; the frontmatter scene_id is
    what disambiguates them. Pages without a frontmatter scene_id are
    accepted on prefix alone (backwards-compatible with files that
    predate this guard).
    """
    prefix = page_id_prefix_for_scene(scene_id)
    pages_dir = os.path.join(project_dir, 'pages')
    if not os.path.isdir(pages_dir):
        return []
    matched: list[PageFile] = []
    name_re = re.compile(rf'^{re.escape(prefix)}-p\d+\.md$')
    for fname in sorted(os.listdir(pages_dir)):
        if not name_re.match(fname):
            continue
        parsed = parse_page_file(os.path.join(pages_dir, fname))
        if parsed is None:
            continue
        fm_scene_id = parsed.get('scene_id')
        if fm_scene_id and fm_scene_id != scene_id:
            continue
        matched.append(parsed)
    matched.sort(key=lambda p: p.get('page_within_scene', 0))
    return matched


class PageFinding(TypedDict, total=False):
    kind: str
    path: str
    field: str
    detail: str


def validate_page_file(path: str) -> list[PageFinding]:
    """Validate a single page file. Returns list of findings (empty when clean).

    Kinds:
      - missing_file: file does not exist
      - no_frontmatter: file has no YAML frontmatter
      - missing_field: a REQUIRED_FIELDS key is absent
      - bad_integer_field: an _INTEGER_FIELDS value failed int coercion
      - filename_page_id_mismatch: filename stem != page_id
      - page_within_scene_out_of_range: not in [1, total_pages_in_scene]
    """
    page = parse_page_file(path)
    if page is None:
        if not os.path.isfile(path):
            return [{'kind': 'missing_file', 'path': path}]
        return [{'kind': 'no_frontmatter', 'path': path}]

    findings: list[PageFinding] = []

    for field in REQUIRED_FIELDS:
        if field not in page:
            findings.append({
                'kind': 'missing_field', 'path': path, 'field': field,
                'detail': f'required frontmatter field {field!r} is missing',
            })

    # Surface integer-coercion failures captured by _parse_frontmatter — the
    # bad value is dropped from the page dict so validation would otherwise
    # report missing_field, hiding the real cause.
    bad_int = page.get('extra', {}).get('_bad_integer_fields', '')
    for field in (bad_int.split(';') if bad_int else []):
        if not field:
            continue
        findings.append({
            'kind': 'bad_integer_field', 'path': path, 'field': field,
            'detail': f'{field!r} value is not an integer',
        })

    stem = os.path.splitext(os.path.basename(path))[0]
    page_id = page.get('page_id')
    if page_id and stem != page_id:
        findings.append({
            'kind': 'filename_page_id_mismatch', 'path': path,
            'detail': f'filename stem {stem!r} does not match page_id {page_id!r}',
        })

    within = page.get('page_within_scene')
    total = page.get('total_pages_in_scene')
    if isinstance(within, int) and isinstance(total, int):
        if within < 1 or within > total:
            findings.append({
                'kind': 'page_within_scene_out_of_range', 'path': path,
                'detail': f'page_within_scene={within} not in [1, {total}]',
            })

    return findings


_PANEL_SCRIPT_HEADER = re.compile(
    r'^##\s+Panel script\s*$', re.MULTILINE | re.IGNORECASE,
)
# Match the NEXT page-file section (## Image-generation..., ## Page-specific
# notes, etc.) but NOT page-script headers (## Page N — LAYOUT), since
# those are part of the script and must remain inside the extracted body.
#
# Convention assumption: page headers use em-dash (U+2014). A regular
# hyphen or en-dash would NOT match the lookahead and would silently
# terminate extraction at the first page header — see CR-3/C-3 in the
# PR #255 review for context. Authors should standardize on em-dash;
# the lookahead also covers en-dash (U+2013) and hyphen-minus as a
# safety net.
_NEXT_SECTION_HEADER = re.compile(
    r'^##\s+(?!Page\s+\d+\s*[—–-])\S', re.MULTILINE,
)


def extract_panel_script(path: str) -> str:
    """Return the contents of the '## Panel script' section, or '' if absent.

    Used by script-package to assemble the artist bundle from page files.
    Output is the section body — strips the '## Panel script' heading
    itself but keeps everything until the next page-file section heading
    (e.g. '## Image-generation prompts' or '## Page-specific notes') or
    EOF. `## Page N — LAYOUT` headers are NOT treated as section
    boundaries; they are part of the script body and remain in the output
    so script-package's global page renumbering can find them.

    If multiple `## Panel script` headers are present, only the FIRST
    section is returned (current page-file convention assumes one
    script section per page).
    """
    page = parse_page_file(path)
    if page is None:
        return ''
    body = page.get('body', '')
    m = _PANEL_SCRIPT_HEADER.search(body)
    if not m:
        return ''
    start = m.end()
    rest = body[start:]
    next_m = _NEXT_SECTION_HEADER.search(rest)
    end = next_m.start() if next_m else len(rest)
    return rest[:end].strip('\n')
