"""Per-page file (graphic-novel mode) parsing and validation.

GN projects can break scenes into per-page files at pages/<prefix>-pN.md.
Each file has YAML frontmatter and a markdown body. See issue #251 and
docs/superpowers/plans/2026-05-27-gn-per-page-files.md for the schema.

The scene file (scenes/<scene_id>.md) remains the creative source of
truth; page files are the atomic per-page working units consumed by
other storyforge commands.
"""

import os
import re
from typing import Final, Literal, TypedDict


# Frontmatter: open with `---\n`, capture everything (possibly empty) up to
# the next `---\n` line, capture the body. `(?:\n|$)` allows the closing
# `---` to be followed by either a newline or EOF.
FRONTMATTER_RE = re.compile(r'\A---\n(.*?)---(?:\n|$)(.*)', re.DOTALL)

# Current page-file schema version (issue #260). v3 is the GPT Image 2
# paradigm: a single whole-page image-generation prompt (OpenAI's
# 5-section template) anchored by reference images, replacing v2's
# per-panel blocking + 13-section panel schema.
SCHEMA_VERSION: Final[int] = 3

REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    'page_id', 'scene_id', 'page_within_scene',
    'total_pages_in_scene', 'panel_count',
)

RECOMMENDED_FIELDS: Final[tuple[str, ...]] = (
    'spread_position', 'characters_present', 'location', 'timeline',
)

# v3 frontmatter additions (issue #260). Recognized as typed page-dict
# keys rather than dumped into `extra` so callers can read them directly.
# `references_required` is the labeled list of reference images uploaded
# alongside the page prompt; `target_model` records the image model the
# prompt is tuned for (e.g. gpt-image-2).
_OPTIONAL_SCALAR_FIELDS: Final[tuple[str, ...]] = (
    'scene_title', 'target_model',
)

_INTEGER_FIELDS: Final[set[str]] = {
    'page_within_scene', 'total_pages_in_scene', 'panel_count',
    'schema_version', 'prompt_iteration',
}

# `references_required` and `canon_referenced` are block lists in the
# frontmatter. canon_referenced supersedes v2's canonical_blocks_embedded:
# in the GPT Image 2 paradigm canon *informs* the prompt but is no longer
# embedded inline, so the field name reflects "referenced, not embedded".
_LIST_FIELDS: Final[set[str]] = {
    'characters_present', 'references_required', 'canon_referenced',
}


# A successful parse always populates path/body/extra/extra_lists; the
# frontmatter fields are optional because validation, not parsing,
# enforces required-ness. Required+Optional split per the codebase
# convention (see script_format.py::LayoutAntiPattern).
class _PageFileRequired(TypedDict):
    path: str
    body: str
    extra: dict[str, str]
    extra_lists: dict[str, list[str]]


class PageFile(_PageFileRequired, total=False):
    page_id: str
    scene_id: str
    page_within_scene: int
    total_pages_in_scene: int
    panel_count: int
    spread_position: str
    characters_present: list[str]
    location: str
    timeline: str
    # v3 (issue #260)
    scene_title: str
    target_model: str
    schema_version: int
    prompt_iteration: int
    references_required: list[str]
    canon_referenced: list[str]


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

        # A comment-only value (`key:  # note`) is treated as no value, so
        # block-list keys like `references_required:  # upload these` still
        # open a list rather than capturing the comment as a scalar.
        if value.startswith('#'):
            value = ''

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

        if (key in REQUIRED_FIELDS or key in RECOMMENDED_FIELDS
                or key in _OPTIONAL_SCALAR_FIELDS):
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


# Closed set of validation finding kinds. Using a Literal+Required split
# (see script_format.py::LayoutAntiPatternKind for the pattern) so a
# `kind` typo in cmd_cleanup.py's elif chain is caught statically rather
# than silently dropping the finding.
PageFindingKind = Literal[
    'missing_file',
    'no_frontmatter',
    'missing_field',
    'bad_integer_field',
    'filename_page_id_mismatch',
    'page_within_scene_out_of_range',
    'missing_page_architecture',
    'missing_image_workflow',
]


class _PageFindingRequired(TypedDict):
    kind: PageFindingKind
    path: str


class PageFinding(_PageFindingRequired, total=False):
    field: str   # set for missing_field and bad_integer_field
    detail: str  # set on all kinds except missing_file / no_frontmatter


def validate_page_file(path: str) -> list[PageFinding]:
    """Validate a single page file. Returns list of findings (empty when clean).

    Kinds:
      - missing_file: file does not exist
      - no_frontmatter: file has no YAML frontmatter
      - missing_field: a REQUIRED_FIELDS key is absent
      - bad_integer_field: an _INTEGER_FIELDS value failed int coercion
      - filename_page_id_mismatch: filename stem != page_id
      - page_within_scene_out_of_range: not in [1, total_pages_in_scene]
      - missing_page_architecture: "## Page architecture" section is missing or empty
      - missing_image_workflow: "## Image-generation workflow" section is missing or empty
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

    # Body-section checks (issues #252, #260). Use _extract_section_from_body
    # with the already-parsed body so the file is not read a second time.
    # The "header present but body empty" half-edited state fires the same
    # finding as a fully-missing section — both signal a gap the author
    # should fill via the corresponding elaborate stage. The blocking-prompt
    # and per-panel checks were removed in v3: GPT Image 2 generates the
    # whole page from a single prompt, so the workflow section replaces them.
    body = page.get('body', '')
    if not _extract_section_from_body(body, _PAGE_ARCHITECTURE_HEADER).strip():
        findings.append({
            'kind': 'missing_page_architecture', 'path': path,
            'detail': '"## Page architecture" section is missing or empty',
        })
    if not _extract_section_from_body(body, _IMAGE_GEN_WORKFLOW_HEADER).strip():
        findings.append({
            'kind': 'missing_image_workflow', 'path': path,
            'detail': '"## Image-generation workflow" section is missing or empty',
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


# Tolerates a trailing parenthetical so both `## Page architecture` (what
# storyforge generates) and `## Page architecture (authoring context)`
# (hand-authored v3 convention) match.
_PAGE_ARCHITECTURE_HEADER = re.compile(
    r'^##\s+Page\s+architecture\b.*$', re.MULTILINE | re.IGNORECASE,
)


def _extract_section_from_body(body: str, header_re: re.Pattern) -> str:
    """Extract a section from an already-parsed body string.

    Returns the body of the section (header stripped) up to the next
    page-file section heading (`## ...`, but not `## Page N — …` page
    headers, which are part of the panel-script body). Returns '' when
    the section is absent.
    """
    m = header_re.search(body)
    if not m:
        return ''
    start = m.end()
    rest = body[start:]
    next_m = _NEXT_SECTION_HEADER.search(rest)
    end = next_m.start() if next_m else len(rest)
    return rest[:end].strip('\n')


def _extract_section(path: str, header_re: re.Pattern) -> str:
    """Shared implementation for body-section extractors.

    Parses the page file at *path* then delegates to
    `_extract_section_from_body`. Returns '' when the page file is
    missing, has no frontmatter, or lacks the section.
    """
    page = parse_page_file(path)
    if page is None:
        return ''
    return _extract_section_from_body(page.get('body', ''), header_re)


def extract_page_architecture(path: str) -> str:
    """Return the contents of the '## Page architecture' section, or ''."""
    return _extract_section(path, _PAGE_ARCHITECTURE_HEADER)


# Tolerates both 'Image-generation workflow' (hyphen) and 'Image generation
# workflow' (space). This is the v3 (issue #260) section that holds the
# single whole-page prompt + reference-image list, replacing v2's
# '## Image-generation prompts' (per-panel) section.
_IMAGE_GEN_WORKFLOW_HEADER = re.compile(
    r'^##\s+Image[- ]generation\s+workflow\s*$', re.MULTILINE | re.IGNORECASE,
)


def extract_image_workflow(path: str) -> str:
    """Return the contents of the '## Image-generation workflow' section, or ''.

    This section (issue #260) holds the whole-page image-generation prompt
    (OpenAI's 5-section template), the labeled reference-image list, and the
    approach note. Used by script-package to assemble the artist bundle's
    per-page prompts.
    """
    return _extract_section(path, _IMAGE_GEN_WORKFLOW_HEADER)


def extract_panel_script(path: str) -> str:
    """Return the contents of the '## Panel script' section, or '' if absent.

    Used by script-package to assemble the artist bundle from page files.
    Output is the section body — strips the '## Panel script' heading
    itself but keeps everything until the next page-file section heading
    (e.g. '## Image-generation workflow' or '## Page-specific notes') or
    EOF. '## Page N — LAYOUT' headers are NOT treated as section
    boundaries; they are part of the script body and remain in the output
    so script-package's global page renumbering can find them.

    If multiple '## Panel script' headers are present, only the FIRST
    section is returned (current page-file convention assumes one
    script section per page).
    """
    return _extract_section(path, _PANEL_SCRIPT_HEADER)
