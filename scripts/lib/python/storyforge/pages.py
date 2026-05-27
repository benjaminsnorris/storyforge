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


FRONTMATTER_RE = re.compile(r'\A---\n(.*?)\n---\n(.*)', re.DOTALL)

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
    has no YAML frontmatter."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        text = f.read()
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
    applied to fields in `_INTEGER_FIELDS`. Unknown scalars go into
    `extra`; unknown block lists go into `extra_lists`. This is a
    deliberate subset of YAML — we don't depend on PyYAML elsewhere and
    don't want to start here.
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
                pass

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

    Pages are matched by filename prefix via page_id_prefix_for_scene.
    This is the on-disk rule (prefix-based filenames) — not a match on
    the scene_id frontmatter field — so the convention stays consistent
    even if a page file's frontmatter scene_id drifts.
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
        if parsed is not None:
            matched.append(parsed)
    matched.sort(key=lambda p: p.get('page_within_scene', 0))
    return matched
