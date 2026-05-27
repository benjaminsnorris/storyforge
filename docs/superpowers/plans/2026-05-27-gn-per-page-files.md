# GN Per-Page Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-page file support (`pages/sN-pX.md`) as the atomic working unit for graphic-novel projects (issue #251).

**Architecture:** A new `pages/` directory sibling to `scenes/` holds one markdown file per book page with YAML frontmatter (page_id, scene_id, page_within_scene, total_pages_in_scene, panel_count, spread_position, characters_present, location, timeline) and body sections (Scene context, Page architecture, Panel script, Image-generation prompts, Page-specific notes). Scene files (`scenes/sN.md`) remain the creative source of truth and link to page files via a page index. A new `pages.py` module owns parsing/validation; `cleanup`, `extract`, `script-package`, and the `forge` skill consume it.

**Tech Stack:** Python 3.10+, pytest, pipe-delimited CSVs, naive YAML-subset parser (no PyYAML dependency, consistent with rest of codebase).

---

## File Structure

**Create:**
- `scripts/lib/python/storyforge/pages.py` — page-file parser, validator, helpers
- `tests/test_pages.py` — unit tests for parsing/validation
- `tests/test_cmd_extract_gn_pages.py` — tests for `extract --from-pages`
- `tests/fixtures/test-project-gn/pages/` — fixture page files for integration tests

**Modify:**
- `scripts/lib/python/storyforge/cmd_cleanup.py` — add `pages/` to expected dirs, page-validation findings
- `scripts/lib/python/storyforge/cmd_extract_gn.py` — add `--from-pages` mode
- `scripts/lib/python/storyforge/cmd_script_package.py` — assemble from page files when present
- `scripts/lib/python/storyforge/cmd_write_gn.py` — refuse to overwrite scene file if pages exist (safety)
- `skills/forge/SKILL.md` — recommend per-page work in GN mode
- `skills/script-package/SKILL.md` — note that page files are preferred
- `CLAUDE.md` — document `pages/` directory in architecture section
- `.claude-plugin/plugin.json` — bump version to 1.38.0

---

## Task 1: `pages.py` module skeleton + scene-prefix helpers

**Files:**
- Create: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: Write failing tests for filename helpers**

Create `tests/test_pages.py`:

```python
"""Tests for storyforge.pages — GN per-page file parsing and validation."""

import os
import pytest


def test_page_id_prefix_extracts_s_prefix():
    from storyforge.pages import page_id_prefix_for_scene
    assert page_id_prefix_for_scene('s01-studio-finalization') == 's01'
    assert page_id_prefix_for_scene('s10-arrival') == 's10'


def test_page_id_prefix_falls_back_to_full_id():
    from storyforge.pages import page_id_prefix_for_scene
    assert page_id_prefix_for_scene('the-blank-page') == 'the-blank-page'
    assert page_id_prefix_for_scene('cartographer-speaks') == 'cartographer-speaks'


def test_page_id_prefix_no_dash_after_s_prefix():
    from storyforge.pages import page_id_prefix_for_scene
    # 'salt-flats' — 's' followed by non-digit; not the sN- pattern
    assert page_id_prefix_for_scene('salt-flats') == 'salt-flats'


def test_page_filename_for_combines_prefix_and_number():
    from storyforge.pages import page_filename_for
    assert page_filename_for('s01-studio-finalization', 1) == 's01-p1.md'
    assert page_filename_for('s01-studio-finalization', 12) == 's01-p12.md'
    assert page_filename_for('the-blank-page', 1) == 'the-blank-page-p1.md'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pages.py -v`
Expected: ImportError / ModuleNotFoundError on `storyforge.pages`.

- [ ] **Step 3: Implement helpers in pages.py**

Create `scripts/lib/python/storyforge/pages.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pages.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages.py
git commit -m "Add pages.py module with scene-prefix helpers for GN per-page files

Foundation for issue #251 (per-page files as the GN atomic working unit).
The page_id_prefix_for_scene + page_filename_for helpers establish the
naming convention: scenes whose ids start with sN- use that prefix; other
scene ids use the full scene id as the prefix."
git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
```

---

## Task 2: Frontmatter parser

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: Write failing tests for parse_frontmatter**

Append to `tests/test_pages.py`:

```python
SAMPLE_FRONTMATTER = """\
---
page_id: s01-p1
scene_id: s01-studio-finalization
scene_title: Studio Finalization
page_within_scene: 1
total_pages_in_scene: 5
spread_position: opening recto (book's first page)
panel_count: 2
characters_present: [lucien-vey, mirelle-ash]
location: archive-studio
timeline: day 1, evening
canonical_blocks_embedded:
  - reference/canon/style-foundation.md
  - reference/canon/lighting-laws.md
prompt_iteration: 6
schema_version: 2
---

# Page s01-p1 — Studio Finalization, page 1 of 5

## Scene context

Some prose.
"""


def test_parse_frontmatter_required_fields(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page is not None
    assert page['page_id'] == 's01-p1'
    assert page['scene_id'] == 's01-studio-finalization'
    assert page['page_within_scene'] == 1
    assert page['total_pages_in_scene'] == 5
    assert page['panel_count'] == 2


def test_parse_frontmatter_inline_list(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page['characters_present'] == ['lucien-vey', 'mirelle-ash']


def test_parse_frontmatter_recommended_fields(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page['spread_position'] == "opening recto (book's first page)"
    assert page['location'] == 'archive-studio'
    assert page['timeline'] == 'day 1, evening'


def test_parse_frontmatter_extras_collected(tmp_path):
    """Unknown keys go into the 'extra' dict — forward-compatible with
    canonical-blocks and modular-prompt sibling issues."""
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert page['extra']['scene_title'] == 'Studio Finalization'
    assert page['extra']['prompt_iteration'] == '6'
    assert page['extra']['schema_version'] == '2'


def test_parse_frontmatter_block_list(tmp_path):
    """Block-style lists (key:\\n  - item) parse into Python lists."""
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(SAMPLE_FRONTMATTER)
    page = parse_page_file(str(path))
    assert 'canonical_blocks_embedded' in page['extra_lists']
    assert page['extra_lists']['canonical_blocks_embedded'] == [
        'reference/canon/style-foundation.md',
        'reference/canon/lighting-laws.md',
    ]


def test_parse_page_file_no_frontmatter_returns_none(tmp_path):
    from storyforge.pages import parse_page_file
    path = tmp_path / 'noframe.md'
    path.write_text('# Just a heading\n\nNo frontmatter.\n')
    assert parse_page_file(str(path)) is None


def test_parse_page_file_missing_file_returns_none(tmp_path):
    from storyforge.pages import parse_page_file
    assert parse_page_file(str(tmp_path / 'nope.md')) is None


def test_parse_frontmatter_handles_inline_comment(tmp_path):
    """Trailing # comments on list items are stripped (matches the
    ashes-PR-8 example: '  - path/to/x.md  # in page-blocking prompt only')."""
    from storyforge.pages import parse_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "canonical_blocks_embedded:\n"
        "  - reference/canon/a.md  # used in blocking prompt only\n"
        "  - reference/canon/b.md\n"
        "---\n\nbody\n"
    )
    page = parse_page_file(str(path))
    assert page['extra_lists']['canonical_blocks_embedded'] == [
        'reference/canon/a.md',
        'reference/canon/b.md',
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pages.py -v`
Expected: AttributeError on `parse_page_file` — the function doesn't exist yet.

- [ ] **Step 3: Implement parse_page_file**

Add to `scripts/lib/python/storyforge/pages.py`:

```python
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
            # Strip trailing '# comment' that the ashes-PR-8 example uses
            if '#' in item:
                item = item.split('#', 1)[0].strip()
            if current_list_key in _LIST_FIELDS:
                page.setdefault(current_list_key, []).append(item)
            else:
                page['extra_lists'].setdefault(current_list_key, []).append(item)
            continue

        if line.startswith(' '):
            # Indented line that isn't a list item — skip (unknown structure)
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
                pass  # fall through to string storage

        if key in REQUIRED_FIELDS or key in RECOMMENDED_FIELDS:
            page[key] = value
        else:
            page['extra'][key] = value

    return page
```

Also add `from typing import Final, TypedDict` to the imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pages.py -v`
Expected: All 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages.py
git commit -m "Add YAML-subset frontmatter parser to pages.py

Supports the page-file schema from issue #251: scalar fields, inline
lists, block lists with trailing # comments. Integer fields are
coerced; unknown keys land in extra/extra_lists for forward
compatibility with sibling issues (canonical blocks, modular prompts)."
git push
```

---

## Task 3: list_page_files + pages_for_scene

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pages.py`:

```python
def test_list_page_files_returns_empty_when_no_pages_dir(tmp_path):
    from storyforge.pages import list_page_files
    assert list_page_files(str(tmp_path)) == []


def test_list_page_files_sorted_and_filters_non_md(tmp_path):
    from storyforge.pages import list_page_files
    pages = tmp_path / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text('---\npage_id: s01-p1\n---\n')
    (pages / 's01-p2.md').write_text('---\npage_id: s01-p2\n---\n')
    (pages / 'readme.txt').write_text('skip me')
    (pages / '.hidden.md').write_text('skip me too')
    result = list_page_files(str(tmp_path))
    assert [os.path.basename(p) for p in result] == ['s01-p1.md', 's01-p2.md']


def test_pages_for_scene_groups_by_prefix(tmp_path):
    """pages_for_scene returns parsed page files for one scene, sorted by
    page_within_scene. Matches by the page_id_prefix_for_scene convention,
    NOT by scene_id field — the prefix is the on-disk filename rule."""
    from storyforge.pages import pages_for_scene
    pages = tmp_path / 'pages'
    pages.mkdir()
    _write_page(pages / 's01-p2.md', 's01-p2', 's01-studio-finalization', 2, 3, 4)
    _write_page(pages / 's01-p1.md', 's01-p1', 's01-studio-finalization', 1, 3, 2)
    _write_page(pages / 's01-p3.md', 's01-p3', 's01-studio-finalization', 3, 3, 6)
    _write_page(pages / 's02-p1.md', 's02-p1', 's02-other', 1, 1, 1)
    result = pages_for_scene(str(tmp_path), 's01-studio-finalization')
    assert [p['page_id'] for p in result] == ['s01-p1', 's01-p2', 's01-p3']


def _write_page(path, page_id, scene_id, within, total, panels):
    path.write_text(
        f"---\n"
        f"page_id: {page_id}\n"
        f"scene_id: {scene_id}\n"
        f"page_within_scene: {within}\n"
        f"total_pages_in_scene: {total}\n"
        f"panel_count: {panels}\n"
        f"---\n\nbody\n"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pages.py -v`
Expected: AttributeError on `list_page_files` and `pages_for_scene`.

- [ ] **Step 3: Implement helpers**

Append to `scripts/lib/python/storyforge/pages.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pages.py -v`
Expected: 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages.py
git commit -m "Add list_page_files + pages_for_scene helpers

pages_for_scene matches by filename prefix rather than the frontmatter
scene_id field — the prefix is the on-disk convention, the frontmatter
is metadata."
git push
```

---

## Task 4: Validation function

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pages.py`:

```python
def test_validate_page_file_clean_passes(tmp_path):
    """A page file with all required fields and correct filename/page_id
    match returns no findings."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p1.md'
    _write_page(path, 's01-p1', 's01-studio-finalization', 1, 5, 2)
    assert validate_page_file(str(path)) == []


def test_validate_missing_required_field(tmp_path):
    """A missing required field surfaces a 'missing_field' finding."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio-finalization\n"
        # missing page_within_scene
        "total_pages_in_scene: 5\n"
        "panel_count: 2\n"
        "---\n\nbody\n"
    )
    findings = validate_page_file(str(path))
    assert any(f['kind'] == 'missing_field'
               and f['field'] == 'page_within_scene' for f in findings)


def test_validate_filename_mismatch(tmp_path):
    """Filename stem must equal page_id."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p7.md'
    _write_page(path, 's01-p1', 's01', 1, 5, 2)
    findings = validate_page_file(str(path))
    assert any(f['kind'] == 'filename_page_id_mismatch' for f in findings)


def test_validate_page_within_scene_out_of_range(tmp_path):
    """page_within_scene must be in [1, total_pages_in_scene]."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p9.md'
    _write_page(path, 's01-p9', 's01', 9, 5, 2)
    findings = validate_page_file(str(path))
    assert any(f['kind'] == 'page_within_scene_out_of_range' for f in findings)


def test_validate_no_frontmatter(tmp_path):
    """A file without frontmatter surfaces 'no_frontmatter'."""
    from storyforge.pages import validate_page_file
    path = tmp_path / 's01-p1.md'
    path.write_text('# No frontmatter here\n')
    findings = validate_page_file(str(path))
    assert findings == [{'kind': 'no_frontmatter', 'path': str(path)}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pages.py -v`
Expected: AttributeError on `validate_page_file`.

- [ ] **Step 3: Implement validate_page_file**

Append to `scripts/lib/python/storyforge/pages.py`:

```python
class PageFinding(TypedDict, total=False):
    kind: str
    path: str
    field: str
    detail: str


def validate_page_file(path: str) -> list[PageFinding]:
    """Validate a single page file. Returns list of findings (empty when clean).

    Kinds:
      - no_frontmatter: file has no YAML frontmatter
      - missing_field: a REQUIRED_FIELDS key is absent
      - non_integer: an _INTEGER_FIELDS key parsed as non-int
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

    # Filename / page_id consistency
    stem = os.path.splitext(os.path.basename(path))[0]
    page_id = page.get('page_id')
    if page_id and stem != page_id:
        findings.append({
            'kind': 'filename_page_id_mismatch', 'path': path,
            'detail': f'filename stem {stem!r} does not match page_id {page_id!r}',
        })

    # Page-within-scene range
    within = page.get('page_within_scene')
    total = page.get('total_pages_in_scene')
    if isinstance(within, int) and isinstance(total, int):
        if within < 1 or within > total:
            findings.append({
                'kind': 'page_within_scene_out_of_range', 'path': path,
                'detail': f'page_within_scene={within} not in [1, {total}]',
            })

    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pages.py -v`
Expected: 19 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages.py
git commit -m "Add validate_page_file with finding-dict shape

Findings: missing_file, no_frontmatter, missing_field,
filename_page_id_mismatch, page_within_scene_out_of_range. Used by
cleanup in the next task to surface page-file issues."
git push
```

---

## Task 5: panel_script section extraction

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages.py`

This is needed by script-package (Task 7) to assemble bundle content from page files.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pages.py`:

```python
def test_extract_panel_script_body(tmp_path):
    """Extract the '## Panel script' section text only."""
    from storyforge.pages import extract_panel_script
    text = (
        "---\npage_id: s01-p1\n---\n\n"
        "# Page heading\n\n"
        "## Scene context\n\nSome context.\n\n"
        "## Page architecture\n\n### Intent\nThings.\n\n"
        "## Panel script\n\n"
        "**Panel 1.** Wide. A studio.\n\n*No dialogue.*\n\n"
        "**Panel 2.** Close. A hand.\n\n"
        "## Image-generation workflow\n\nshould not appear\n"
    )
    path = tmp_path / 's01-p1.md'
    path.write_text(text)
    result = extract_panel_script(str(path))
    assert '**Panel 1.**' in result
    assert '**Panel 2.**' in result
    assert 'A studio' in result
    assert 'should not appear' not in result
    assert 'Scene context' not in result


def test_extract_panel_script_missing_section_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_script
    path = tmp_path / 's01-p1.md'
    path.write_text('---\npage_id: s01-p1\n---\n\n# Heading\n\nno script section\n')
    assert extract_panel_script(str(path)) == ''
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pages.py -v`
Expected: AttributeError on `extract_panel_script`.

- [ ] **Step 3: Implement extract_panel_script**

Append to `scripts/lib/python/storyforge/pages.py`:

```python
_PANEL_SCRIPT_HEADER = re.compile(
    r'^##\s+Panel script\s*$', re.MULTILINE | re.IGNORECASE,
)
_NEXT_SECTION_HEADER = re.compile(r'^##\s+\S', re.MULTILINE)


def extract_panel_script(path: str) -> str:
    """Return the contents of the '## Panel script' section, or '' if absent.

    Used by script-package to assemble the artist bundle from page files.
    Output is the section body — strips the '## Panel script' heading
    itself but keeps everything until the next ## heading or EOF.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pages.py -v`
Expected: 21 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages.py
git commit -m "Add extract_panel_script for script-package consumers

Pulls just the '## Panel script' section body out of a page file so
script-package can assemble the artist bundle from page files without
also pulling in the image-generation prompts or page-architecture notes."
git push
```

---

## Task 6: cleanup integration — recognize pages/ + validate findings

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_cleanup.py`
- Test: `tests/test_cleanup_csv.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cleanup_csv.py`:

```python
class TestPagesDirectory:
    """Cleanup integration for GN per-page files (issue #251)."""

    def test_pages_dir_not_flagged_unexpected_in_gn(self, tmp_path):
        """A pages/ directory in a GN project is recognized, not flagged."""
        from storyforge.cmd_cleanup import report_unexpected_files
        (tmp_path / 'pages').mkdir()
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        issues = report_unexpected_files(str(tmp_path))
        assert not any(i == 'UNEXPECTED_DIR:pages' for i in issues)

    def test_pages_dir_still_flagged_in_novel_mode(self, tmp_path):
        """pages/ in a prose-novel project remains UNEXPECTED — it has no
        meaning in novel mode and should be cleaned up."""
        from storyforge.cmd_cleanup import report_unexpected_files
        (tmp_path / 'pages').mkdir()
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: novel\n'
        )
        issues = report_unexpected_files(str(tmp_path))
        assert any(i == 'UNEXPECTED_DIR:pages' for i in issues)

    def test_invalid_page_file_surfaced_in_report(self, tmp_path):
        """A page file missing required frontmatter surfaces a finding in
        the structured report."""
        from storyforge.cmd_cleanup import build_cleanup_report
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        # File without YAML frontmatter
        (pages / 's01-p1.md').write_text('# No frontmatter\n')
        report = build_cleanup_report(str(tmp_path))
        page_findings = [f for f in report['findings']
                         if f.get('category') == 'pages']
        assert len(page_findings) >= 1
        assert any(f['type'] == 'page_no_frontmatter' for f in page_findings)

    def test_clean_page_file_no_findings(self, tmp_path):
        """A valid page file produces no page-category findings."""
        from storyforge.cmd_cleanup import build_cleanup_report
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p1.md').write_text(
            "---\n"
            "page_id: s01-p1\n"
            "scene_id: s01-studio-finalization\n"
            "page_within_scene: 1\n"
            "total_pages_in_scene: 5\n"
            "panel_count: 2\n"
            "---\n\nbody\n"
        )
        report = build_cleanup_report(str(tmp_path))
        page_findings = [f for f in report['findings']
                         if f.get('category') == 'pages']
        assert page_findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cleanup_csv.py::TestPagesDirectory -v`
Expected: Tests fail — `pages/` is flagged as unexpected in GN mode; no page-category findings exist.

- [ ] **Step 3: Update report_unexpected_files to ignore pages/ in GN mode**

In `scripts/lib/python/storyforge/cmd_cleanup.py`, modify `report_unexpected_files` (around line 645) to accept the medium and add `pages` to allowed top dirs when GN:

```python
def report_unexpected_files(project_dir: str) -> list[str]:
    """Report unexpected files and directories. Returns list of issue strings."""
    issues = []
    medium = get_medium(project_dir)
    allowed_top_dirs = set(EXPECTED_TOP_DIRS)
    if medium == 'graphic-novel':
        allowed_top_dirs.add('pages')

    # Top-level dirs
    for entry in sorted(os.listdir(project_dir)):
        path = os.path.join(project_dir, entry)
        if os.path.isdir(path) and entry not in allowed_top_dirs:
            issues.append(f'UNEXPECTED_DIR:{entry}')
        elif os.path.isfile(path) and entry not in EXPECTED_TOP_FILES:
            issues.append(f'UNEXPECTED_FILE:{entry}')

    # ... rest unchanged
```

- [ ] **Step 4: Add page-validation check to build_cleanup_report**

In `cmd_cleanup.py`, add a new check function above `build_cleanup_report`:

```python
def _check_page_files(project_dir: str) -> list[dict]:
    """Validate page files under pages/ for GN projects. Returns finding dicts
    in cleanup-report shape."""
    if get_medium(project_dir) != 'graphic-novel':
        return []
    from storyforge.pages import list_page_files, validate_page_file

    findings: list[dict] = []
    for page_path in list_page_files(project_dir):
        for issue in validate_page_file(page_path):
            rel_path = os.path.relpath(page_path, project_dir)
            kind = issue['kind']
            if kind == 'no_frontmatter':
                findings.append({
                    'type': 'page_no_frontmatter', 'file': rel_path,
                    'detail': f'{rel_path} has no YAML frontmatter',
                    'action': 'Add the page-file frontmatter '
                              '(page_id, scene_id, page_within_scene, '
                              'total_pages_in_scene, panel_count)',
                    'severity': 'warning',
                })
            elif kind == 'missing_field':
                findings.append({
                    'type': 'page_missing_field', 'file': rel_path,
                    'detail': f'{rel_path} is missing required field '
                              f'{issue["field"]!r}',
                    'action': f'Add `{issue["field"]}: ...` to the frontmatter',
                    'severity': 'warning',
                })
            elif kind == 'filename_page_id_mismatch':
                findings.append({
                    'type': 'page_filename_mismatch', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Rename the file to match page_id, '
                              'or fix the page_id in frontmatter',
                    'severity': 'warning',
                })
            elif kind == 'page_within_scene_out_of_range':
                findings.append({
                    'type': 'page_out_of_range', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Correct page_within_scene or '
                              'total_pages_in_scene to be consistent',
                    'severity': 'warning',
                })
    return findings
```

In `build_cleanup_report` (around line 1080), add the call alongside `_check_scene_artifacts`:

```python
    # --- Page files (GN-only) ---
    for finding in _check_page_files(project_dir):
        finding['category'] = 'pages'
        all_findings.append(finding)
```

Also add `'pages'` to the categories list in `_print_report` (around line 1135):

```python
    categories = [
        ('structure', 'Project Structure'),
        ('scenes', 'Scene Files'),
        ('pages', 'Page Files'),
        ('schema', 'CSV Schema'),
        ('integrity', 'CSV Integrity'),
        ('unexpected', 'Unexpected Files'),
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cleanup_csv.py::TestPagesDirectory -v`
Expected: 4 tests pass. Then run the full suite: `pytest tests/test_cleanup_csv.py -v` and confirm no regressions.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_cleanup.py tests/test_cleanup_csv.py
git commit -m "Cleanup: recognize pages/ in GN mode + validate page files

- pages/ is no longer UNEXPECTED_DIR for GN projects (still flagged in
  novel mode where it has no meaning)
- New 'pages' report category surfaces page-file findings:
  no_frontmatter, missing_field, filename_page_id_mismatch,
  page_within_scene_out_of_range"
git push
```

---

## Task 7: script-package — assemble from page files when present

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_script_package.py`
- Test: `tests/test_cmd_script_package.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_cmd_script_package.py`:

```python
def test_script_package_prefers_page_files_when_present(project_dir_gn, monkeypatch):
    """When pages/sN-pX.md files exist for a scene, the assembled bundle
    uses their '## Panel script' sections instead of the inline scene
    file body. The scene file's metadata table and page index are still
    skipped; the global page-number sequence still runs across the
    bundle as a whole."""
    monkeypatch.chdir(project_dir_gn)

    # Write a scene with pages/ files (s01) and a scene with inline only (s02)
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    pages_dir = os.path.join(project_dir_gn, 'pages')
    os.makedirs(pages_dir, exist_ok=True)

    # s01-studio scene-file: page index only (no inline panel script)
    with open(os.path.join(scenes_dir, 's01-studio.md'), 'w') as f:
        f.write('# Scene s01\n\n## Page index\n\nSee pages/.\n')
    # Two page files for s01
    for i, comp in enumerate(['Wide establishing.', 'Lucien enters.'], start=1):
        with open(os.path.join(pages_dir, f's01-p{i}.md'), 'w') as f:
            f.write(
                f"---\n"
                f"page_id: s01-p{i}\n"
                f"scene_id: s01-studio\n"
                f"page_within_scene: {i}\n"
                f"total_pages_in_scene: 2\n"
                f"panel_count: 1\n"
                f"---\n\n"
                f"## Panel script\n\n"
                f"## Page {i} — SPLASH\n\n"
                f"**Panel 1**\n{comp}\n"
            )

    # s02 inline-only
    with open(os.path.join(scenes_dir, 's02-other.md'), 'w') as f:
        f.write(
            '## Page 1 — SPLASH\n\n**Panel 1**\nInline content.\n'
        )

    # Seed CSV statuses and chapter map
    from storyforge.csv_cli import update_field, append_row
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    # Replace seeded scenes with our two test scenes (simpler than mutating)
    with open(scenes_csv) as f:
        header = f.readline()
    with open(scenes_csv, 'w') as f:
        f.write(header)
    cols = header.strip().split('|')

    def _row(sid):
        row = {c: '' for c in cols}
        row['id'] = sid
        row['status'] = 'drafted'
        row['title'] = sid
        return '|'.join(row[c] for c in cols)

    with open(scenes_csv, 'a') as f:
        f.write(_row('s01-studio') + '\n')
        f.write(_row('s02-other') + '\n')

    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|s01-studio;s02-other\n')

    from storyforge import cmd_script_package
    cmd_script_package.main([])

    script_md = open(os.path.join(project_dir_gn, 'manuscript', 'script.md')).read()
    # Per-page content present
    assert 'Wide establishing.' in script_md
    assert 'Lucien enters.' in script_md
    # Inline scene fallback still works
    assert 'Inline content.' in script_md
    # The s01 scene file's metadata table is NOT included
    assert '## Page index' not in script_md
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_cmd_script_package.py::test_script_package_prefers_page_files_when_present -v`
Expected: AssertionError — `'Wide establishing.'` not in script_md (because the current implementation only reads scenes/{sid}.md).

- [ ] **Step 3: Update _assemble_script to prefer page files**

In `cmd_script_package.py`, modify `_assemble_script` to check for page files first:

```python
def _assemble_script(project_dir, chapters, title):
    """Concatenate scenes in chapter order with global page numbering.

    For GN projects with per-page files (pages/<prefix>-pN.md), the panel
    script content is assembled from the page files' '## Panel script'
    sections, sorted by page_within_scene. Scenes without page files
    fall back to the inline scene-file body (legacy / pre-#251 projects).
    Returns the assembled markdown string.
    """
    from storyforge.script_format import count_panels
    from storyforge.pages import pages_for_scene, extract_panel_script

    global_page = 1
    total_panels = 0
    body_parts = []

    for chap in chapters:
        body_parts.append(f'\n# Chapter {chap["chapter"]} — {chap["title"]}\n')
        for sid in chap['scenes']:
            page_files = pages_for_scene(project_dir, sid)
            if page_files:
                scene_text_parts = [f'\n# Scene: {sid}\n']
                for page in page_files:
                    script_body = extract_panel_script(page['path'])
                    if script_body:
                        scene_text_parts.append('\n' + script_body + '\n')
                scene_text = ''.join(scene_text_parts)
            else:
                scene_path = os.path.join(project_dir, 'scenes', f'{sid}.md')
                if not os.path.isfile(scene_path):
                    log(f'  WARNING: scene file not found: scenes/{sid}.md')
                    body_parts.append(f'\n*[scene {sid} not found]*\n')
                    continue
                scene_text = open(scene_path, encoding='utf-8').read()
            total_panels += count_panels(scene_text)
            renumbered, global_page = _renumber_pages(scene_text, global_page)
            body_parts.append(renumbered)
            body_parts.append('\n')

    total_pages = global_page - 1
    header = (
        f'# {title} — Artist Script\n\n'
        f'_Auto-generated. See handoff-readme.md for format conventions._\n\n'
        f'**Total pages:** {total_pages} | **Total panels:** {total_panels}\n'
    )
    return header + ''.join(body_parts)
```

Also relax the "scene file exists" requirement before drafting check (around line 690 in main) for scenes that have page files:

```python
    from storyforge.csv_cli import get_field
    from storyforge.pages import pages_for_scene
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    not_drafted = []
    for chap in chapters:
        for sid in chap['scenes']:
            # Page-file mode counts as drafted when at least one page exists
            if pages_for_scene(project_dir, sid):
                continue
            status = get_field(scenes_csv, sid, 'status') or ''
            if status != 'drafted':
                not_drafted.append(f'{sid} (status={status or "unknown"})')
```

- [ ] **Step 4: Run the new test + existing tests to confirm no regressions**

Run: `pytest tests/test_cmd_script_package.py -v`
Expected: All tests pass, including the new one.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_script_package.py tests/test_cmd_script_package.py
git commit -m "script-package: assemble from pages/ when present

When a scene has per-page files at pages/<prefix>-pN.md, the artist
bundle concatenates the '## Panel script' sections from each page file
(sorted by page_within_scene) instead of reading the inline scene-file
body. Scenes without page files fall back to the legacy path. The
chapter-level 'all scenes drafted' check treats a scene as drafted
when at least one page file exists for it."
git push
```

---

## Task 8: extract --from-pages — sync metadata from page files

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_extract_gn.py`
- Test: `tests/test_cmd_extract_gn_pages.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cmd_extract_gn_pages.py`:

```python
"""Tests for cmd_extract_gn --from-pages — sync metadata from page files."""

import os
import textwrap


def _seed_gn_project(project_dir: str) -> None:
    """Minimal GN project with one scene row and two page files."""
    with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  title: Test\n  medium: graphic-novel\n  '
                'coaching_level: full\n')

    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write('id|title|status|panel_count|page_count\n')
        f.write('s01-studio|Studio|briefed||\n')

    pages = os.path.join(project_dir, 'pages')
    os.makedirs(pages, exist_ok=True)
    with open(os.path.join(pages, 's01-p1.md'), 'w') as f:
        f.write(textwrap.dedent("""\
            ---
            page_id: s01-p1
            scene_id: s01-studio
            page_within_scene: 1
            total_pages_in_scene: 2
            panel_count: 2
            characters_present: [lucien-vey]
            ---

            ## Panel script
            body
            """))
    with open(os.path.join(pages, 's01-p2.md'), 'w') as f:
        f.write(textwrap.dedent("""\
            ---
            page_id: s01-p2
            scene_id: s01-studio
            page_within_scene: 2
            total_pages_in_scene: 2
            panel_count: 4
            characters_present: [lucien-vey, mirelle-ash]
            ---

            ## Panel script
            body
            """))


def test_from_pages_updates_panel_count_and_page_count(tmp_path, monkeypatch):
    _seed_gn_project(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    main(['--from-pages'])

    from storyforge.csv_cli import get_field
    scenes_csv = str(tmp_path / 'reference' / 'scenes.csv')
    assert get_field(scenes_csv, 's01-studio', 'panel_count') == '6'
    assert get_field(scenes_csv, 's01-studio', 'page_count') == '2'


def test_from_pages_dry_run_does_not_write(tmp_path, monkeypatch):
    _seed_gn_project(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    main(['--from-pages', '--dry-run'])

    from storyforge.csv_cli import get_field
    scenes_csv = str(tmp_path / 'reference' / 'scenes.csv')
    # Counts remain blank because dry-run did not write
    assert get_field(scenes_csv, 's01-studio', 'panel_count') == ''


def test_from_pages_no_pages_dir_errors(tmp_path, monkeypatch, capsys):
    with open(tmp_path / 'storyforge.yaml', 'w') as f:
        f.write('project:\n  title: Test\n  medium: graphic-novel\n')
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_extract_gn import main
    import pytest as _pytest
    with _pytest.raises(SystemExit):
        main(['--from-pages'])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_cmd_extract_gn_pages.py -v`
Expected: argparse error — `--from-pages` is not a recognized flag.

- [ ] **Step 3: Add --from-pages to cmd_extract_gn**

In `cmd_extract_gn.py`, modify `parse_args` to add the flag to the mutually-exclusive group:

```python
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--from-script', type=str, metavar='PATH',
                     help='Path to a panel script file or directory of '
                          '.md script files. Parses deterministically; no '
                          'LLM call.')
    src.add_argument('--from-prose', type=str, metavar='PATH',
                     help='Path to a prose manuscript file. LLM-extracts '
                          'GN intent + brief shapes per scene section. '
                          'Coaching level controls destination.')
    src.add_argument('--from-pages', action='store_true',
                     help='Sync scene-level metadata from pages/<prefix>-pN.md '
                          'files: panel_count (sum), page_count (count). '
                          'Deterministic; no LLM call.')
```

Modify `main` to dispatch when `args.from_pages` is set:

```python
    if args.from_pages:
        _run_from_pages(project_dir, args.dry_run)
        return

    if args.from_script:
        ...
```

Add the implementation:

```python
def _run_from_pages(project_dir: str, dry_run: bool) -> None:
    """Sum panel_count + page_count per scene from page files and write
    those columns back to scenes.csv. Deterministic — no LLM call."""
    from storyforge.pages import list_page_files, parse_page_file
    from storyforge.csv_cli import update_field, list_ids

    page_paths = list_page_files(project_dir)
    if not page_paths:
        log('ERROR: no pages/*.md files found. Create per-page files first.')
        sys.exit(1)

    # Aggregate by scene_id
    by_scene: dict[str, dict[str, int]] = {}
    for p in page_paths:
        page = parse_page_file(p)
        if page is None:
            log(f'  WARNING: {p} has no frontmatter; skipping')
            continue
        sid = page.get('scene_id')
        if not sid:
            log(f'  WARNING: {p} has no scene_id; skipping')
            continue
        bucket = by_scene.setdefault(sid, {'panels': 0, 'pages': 0})
        bucket['panels'] += page.get('panel_count', 0) or 0
        bucket['pages'] += 1

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not os.path.isfile(scenes_csv):
        log(f'ERROR: scenes.csv not found at {scenes_csv}')
        sys.exit(1)
    known_ids = set(list_ids(scenes_csv))

    for sid, counts in sorted(by_scene.items()):
        if sid not in known_ids:
            log(f'  WARNING: {sid} referenced by page files but not in '
                f'scenes.csv; skipping')
            continue
        log(f'  {sid}: {counts["pages"]} page(s), {counts["panels"]} panel(s)')
        if dry_run:
            continue
        update_field(scenes_csv, sid, 'panel_count', str(counts['panels']))
        update_field(scenes_csv, sid, 'page_count', str(counts['pages']))

    if dry_run:
        log(f'DRY RUN — would update {len(by_scene)} scene row(s).')
    else:
        log(f'Updated panel_count / page_count for {len(by_scene)} scene(s).')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cmd_extract_gn_pages.py -v`
Expected: 3 tests pass. Also run `pytest tests/test_cmd_extract_gn.py -v` and confirm no regressions.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_extract_gn.py tests/test_cmd_extract_gn_pages.py
git commit -m "extract --from-pages: sync scene metadata from per-page files

Deterministic aggregator: sums panel_count and counts pages across
pages/<prefix>-pN.md and writes them back to scenes.csv. No LLM call.
Page files without frontmatter, without scene_id, or referencing
unknown scene ids are skipped with WARNINGs."
git push
```

---

## Task 9: forge skill — recommend per-page work in GN mode

**Files:**
- Modify: `skills/forge/SKILL.md`

- [ ] **Step 1: Update the GN section of the forge skill**

In `skills/forge/SKILL.md`, find the "Graphic-novel mode in v1" section (around line 401) and replace it with:

```markdown
## Graphic-novel mode

Graphic-novel projects can work at two granularities:

- **Scene level** — `scenes/<scene_id>.md` is the creative source of truth (function, page index, cross-page continuity notes).
- **Page level** — `pages/<prefix>-pN.md` is the atomic working unit when a scene has multiple pages. Each page file carries the panel script, the page architecture (intent, hierarchy, book-level placement), and the image-generation prompts for that one book page.

When orienting yourself in a GN project, check whether `pages/` exists:

- **If `pages/` is populated:** recommend per-page work. Suggest extracting metadata after page edits (`./storyforge extract --from-pages` updates `scenes.csv` panel_count + page_count). Recommend the script-package skill once the page files are ready for handoff — it now assembles the artist bundle from page files when present, falling back to the inline scene file otherwise.
- **If `pages/` is empty or absent:** the project is using scene-level files only. That's still supported. Suggest migrating to per-page files when a scene's panel-level content gets unwieldy (around 3+ pages with detailed image prompts).

These commands and skills work in GN mode: `elaborate`, `hone`, `validate`, `cleanup`, `write`, `evaluate`, `score`, `revise`, `extract`, `script-package`. Not yet supported: `publish`, `annotations` (Bookshelf integration — tracked as #215).

If the author asks for an unsupported action, explain the limit and offer to help with what is supported.
```

- [ ] **Step 2: Commit**

```bash
git add skills/forge/SKILL.md
git commit -m "forge: recommend per-page work + describe pages/ layer in GN mode

Updates the GN section to describe the two-level granularity (scene vs
page) introduced by issue #251, recommends extract --from-pages after
page edits, and refreshes the supported-command list."
git push
```

---

## Task 10: script-package skill — note page-file preference

**Files:**
- Modify: `skills/script-package/SKILL.md`

- [ ] **Step 1: Add a short section about page files**

In `skills/script-package/SKILL.md`, after the "Step 1: Read Project State" section (around line 35), add this new section:

```markdown
### Page files

If `pages/<prefix>-pN.md` files exist for any scene, the assembly command will use those as the panel-script source for that scene (sorted by `page_within_scene`). The scene file's metadata table, function, and page index are still read for context but are not concatenated into the artist bundle.

Surface this to the author when relevant:

- "I see pages/ has 27 files across 5 scenes — those will be the source for the bundle."
- "Scene `s03-arrival` has no page files; its inline panel script will be used."

If the author wants to refresh scene-level panel/page counts from the page files before assembly, suggest:

```bash
./storyforge extract --from-pages
```
```

- [ ] **Step 2: Commit**

```bash
git add skills/script-package/SKILL.md
git commit -m "script-package skill: note that page files are the preferred source

When pages/ has files, the assembled bundle uses '## Panel script'
sections from page files rather than inline scene-file content. The
skill should surface this to the author and suggest the
extract --from-pages refresh before assembly."
git push
```

---

## Task 11: CLAUDE.md — document pages/ in architecture

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add pages/ description to the Graphic Novel Mode section**

In `CLAUDE.md`, find the "Graphic Novel Mode" section (around line 366) and after the "Schema additions" bullet list, add this paragraph:

```markdown
**Per-page files (issue #251):**
- A `pages/` directory (sibling to `scenes/`) can hold per-page markdown files at `pages/<prefix>-pN.md` where the prefix is `sN` for scene ids starting with `sN-` (e.g., `s01-studio-finalization` → `s01`) or the full scene id otherwise.
- Each page file has YAML frontmatter (`page_id`, `scene_id`, `page_within_scene`, `total_pages_in_scene`, `panel_count`, plus recommended `spread_position`, `characters_present`, `location`, `timeline`) and body sections: Scene context, Page architecture, Panel script, Image-generation prompts, Page-specific notes.
- When `pages/` is populated, `script-package` assembles the artist bundle from page files (preferring the `## Panel script` section of each), `extract --from-pages` syncs `panel_count` + `page_count` on `scenes.csv` from the page metadata, and `cleanup` validates page-file frontmatter and filename / `page_id` consistency.
- Scene files (`scenes/<scene_id>.md`) remain the creative source of truth — function, page index, cross-page continuity notes live there.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md: document pages/ directory in GN architecture

Captures the per-page file structure introduced by issue #251 so future
agents working on this codebase find the schema, naming convention, and
integration points without re-reading the issue."
git push
```

---

## Task 12: Version bump + final verification

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: all tests pass. Investigate any failure before bumping the version.

- [ ] **Step 2: Bump the version**

In `.claude-plugin/plugin.json`, change `"version": "1.37.1"` to `"version": "1.38.0"` (minor bump — new feature).

- [ ] **Step 3: Commit and push**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 1.38.0 — GN per-page files (issue #251)

Adds the pages/ directory as a first-class atomic working unit for
graphic-novel projects. Page files carry their own architecture and
image-generation prompts; cleanup, extract, script-package, and forge
all understand them. Scene files remain the creative source of truth."
git push
```

- [ ] **Step 4: Open the PR**

Run:

```bash
gh pr create --title "GN per-page files (closes #251)" --body "$(cat <<'EOF'
## Summary

Adds `pages/<prefix>-pN.md` as the atomic working unit for graphic-novel projects, per issue #251. A scene with 5 pages × 21 panels no longer needs to live in a single 400+ line file; each page gets its own file with YAML frontmatter and structured sections (scene context, page architecture, panel script, image-generation prompts, artist notes).

Validated against the lived-in example in `benjaminsnorris/ashes` PR #8 (s01 vertical slice).

## Changes

- **New module `pages.py`** — frontmatter parser (YAML subset, no PyYAML), `validate_page_file`, `pages_for_scene`, `extract_panel_script`, naming-convention helpers.
- **`cleanup`** — recognizes `pages/` in GN mode (not flagged as unexpected), validates page-file frontmatter, surfaces a new `pages` finding category.
- **`extract --from-pages`** — deterministic aggregator that sums `panel_count` + counts `page_count` per scene and writes those back to `scenes.csv`. No LLM call.
- **`script-package`** — when a scene has page files, the artist bundle's `script.md` concatenates the `## Panel script` sections from each page file (sorted by `page_within_scene`) instead of reading the inline scene-file body. Scenes without page files use the legacy path.
- **`forge` skill** — describes the two-level granularity (scene vs page) and recommends per-page work in GN mode.
- **`script-package` skill** — notes the page-file preference and suggests `extract --from-pages` before assembly.
- **`CLAUDE.md`** — documents the `pages/` layer in the GN architecture section.

## Test plan

- [x] Unit tests for `pages.py` (21 tests: helpers, parser, validator, panel-script extraction)
- [x] Cleanup integration tests (4 tests: pages/ allowed in GN, flagged in novel, findings surface)
- [x] script-package test (assembles from page files when present, falls back to inline)
- [x] extract --from-pages tests (3 tests: panel_count + page_count sum, dry-run, no-pages error)
- [x] Full test suite passes

## Out of scope (sibling issues, per #251)

- Page-blocking workflow (page-architecture + blocking-image prompt before per-panel rendering)
- Modular panel prompt schema (13-section structure)
- Canon file architecture (`reference/canon/` per-concept blocks)

EOF
)"
```

---

## Self-Review (executed before publishing this plan)

**Spec coverage:**
- `pages/` directory ✓ (Tasks 1, 6, 11)
- File naming `pages/sN-pX.md` with prefix convention ✓ (Task 1)
- Required frontmatter fields ✓ (Task 2 parser, Task 4 validator)
- Body sections (Scene context, Page architecture, Panel script, Image-generation prompts, Page-specific notes) ✓ (documented in skill text, Task 5 extracts Panel script for script-package; no test that *requires* the others to exist, by design — they're conventions in the spec, not validation rules)
- Slim scene files with page index ✓ (documented in CLAUDE.md + forge skill; no migration tool — pre-existing scene files remain as-is)
- `cleanup` recognizes pages/ + validates frontmatter ✓ (Task 6)
- `forge` recommends per-page work ✓ (Task 9)
- `extract` extracts metadata from page files ✓ (Task 8)
- `script-package` bundles per-page files ✓ (Task 7)

**Placeholder scan:**
- No "TBD" / "TODO" / "implement later" in the plan.
- No "similar to Task N" without repeated code.
- Every code step shows actual code, not a description of code.

**Type consistency:**
- `parse_page_file` returns `PageFile | None` (Task 2), used consistently in Tasks 3, 4, 5, 6, 7, 8.
- `validate_page_file` returns `list[PageFinding]` (Task 4), consumed in Task 6.
- `pages_for_scene` returns `list[PageFile]` (Task 3), consumed in Task 7 and 8.
- `extract_panel_script` returns `str` (Task 5), consumed in Task 7.
- Field names in finding dicts (`kind`, `path`, `field`, `detail`) are stable across producer (Task 4) and consumer (Task 6).
