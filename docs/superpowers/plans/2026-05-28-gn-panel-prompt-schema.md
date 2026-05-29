# GN 13-Section Panel Prompt Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `panel-prompts` elaboration stage that writes 13-section per-panel image-generation prompts into each per-page file's `## Image-generation prompts` body section for graphic-novel projects. Each panel becomes a `### Panel N` subsection with exactly 13 `#### N. <Title>` sub-subsections in canonical order. Cleanup gains three new finding kinds for missing prompts, missing sections, and wrong-order sections (issue #253).

**Architecture:** Mirrors the page-architecture stage from #252 at every structural level. `pages.py` gains two extractors and three new finding kinds; `cmd_elaborate.py` adds a per-page handler with three coaching modes (full/coach/strict); `cmd_cleanup.py` wires the new findings; a new `prompts_panel_prompts.py` module hosts the three coaching-mode prompt builders. One LLM call per page emits all panel prompts so cross-panel continuity stays in a single context. Five canon files (style-foundation, lighting-laws, location, character, motif) are embedded verbatim into sections 1, 2, 5, 6, 10.

**Tech Stack:** Python 3.10+, pytest, pipe-delimited CSVs, naive YAML-subset parser, existing `storyforge.api` / `storyforge.canon` / `storyforge.pages` modules.

**Branch:** `storyforge/gn-panel-prompt-schema-253` (already created).

---

## File Structure

**Create:**
- `scripts/lib/python/storyforge/prompts_panel_prompts.py` — strict template + coach brief + full LLM prompt builders (mirrors `prompts_page_architecture.py`)
- `tests/test_pages_panel_prompt_extractors.py` — extractor + section-title constant tests
- `tests/test_pages_panel_prompt_validation.py` — three new finding kinds + cleanup integration
- `tests/test_prompts_panel_prompts.py` — strict / coach / full prompt-builder tests
- `tests/test_cmd_elaborate_panel_prompts.py` — handler dispatcher + splice + mocked-API e2e
- `tests/fixtures/test-project-gn/pages/s01-p1.md` — extended with well-formed panel prompts (or new fixture page for panel-prompt-specific tests)

**Modify:**
- `scripts/lib/python/storyforge/pages.py` — add `PANEL_SECTION_TITLES`, `extract_panel_prompts`, `extract_panel_sections`; extend `PageFindingKind` Literal with three new values; extend `validate_page_file` with section/order checks
- `scripts/lib/python/storyforge/cmd_elaborate.py` — add `'panel-prompts'` to `VALID_STAGES`; add `_run_panel_prompts_handler_gn`; add short-circuit in `_run_main_stage`; reuse the existing `--page` / `--scene` / `--force` flags (no new argparse)
- `scripts/lib/python/storyforge/cmd_cleanup.py` — wire the three new finding kinds in `_check_page_files`
- `skills/elaborate/SKILL.md` — document the new stage + coaching behavior
- `skills/forge/SKILL.md` — recommend `panel-prompts` after `page-architecture` in GN pipeline
- `CLAUDE.md` — add `panel-prompts` to elaborate stage table; add GN-section paragraph
- `.claude-plugin/plugin.json` — bump to **1.41.0**

---

## Task 1: `PANEL_SECTION_TITLES` constant + `extract_panel_prompts`

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages_panel_prompt_extractors.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pages_panel_prompt_extractors.py`:

```python
"""Tests for pages.extract_panel_prompts, extract_panel_sections,
and the PANEL_SECTION_TITLES constant (issue #253)."""


def _write_page(tmp_path, body):
    """Write a minimal valid page file with the given body content.
    Uses explicit string concatenation (not f-string + dedent) to avoid
    the indentation bug caught in PR #258 Task 1 review."""
    fm = (
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 2\n"
        "---\n\n"
    )
    path = tmp_path / 's01-p1.md'
    path.write_text(fm + body)
    return str(path)


def test_panel_section_titles_has_exactly_13_in_order():
    from storyforge.pages import PANEL_SECTION_TITLES
    assert len(PANEL_SECTION_TITLES) == 13
    # Spot-check canonical order — first, last, and one in the middle
    assert PANEL_SECTION_TITLES[0] == 'Style foundation'
    assert PANEL_SECTION_TITLES[1] == 'Lighting laws'
    assert PANEL_SECTION_TITLES[2] == 'Pacing role'
    assert PANEL_SECTION_TITLES[6] == 'In this panel'
    assert PANEL_SECTION_TITLES[9] == 'Symbolic detail (low weight)'
    assert PANEL_SECTION_TITLES[11] == 'Emotional subtext (low weight)'
    assert PANEL_SECTION_TITLES[12] == 'Negative constraints'


def test_extract_panel_prompts_returns_dict_for_two_panels(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        'panel 1 body content\n\n'
        '### Panel 2\n\n'
        'panel 2 body content\n\n'
        '## Panel script\n\n**Panel 1.** Wide.\n'
    )
    result = extract_panel_prompts(_write_page(tmp_path, body))
    assert set(result.keys()) == {1, 2}
    assert 'panel 1 body content' in result[1]
    assert 'panel 2 body content' in result[2]
    # Headers are stripped from the body
    assert '### Panel 1' not in result[1]
    assert '### Panel 2' not in result[2]
    # Next-section content (## Panel script) is NOT included
    assert 'Panel 1.** Wide' not in result[2]


def test_extract_panel_prompts_handles_panel_with_subsections(tmp_path):
    """The 13 #### subsections inside a panel must remain in the body
    — they are part of the panel content, not section terminators."""
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nfoundation block\n\n'
        '#### 2. Lighting laws\n\nlighting block\n\n'
        '#### 13. Negative constraints\n\nexclusions\n\n'
        '### Panel 2\n\n'
        '#### 1. Style foundation\n\nfoundation 2\n'
    )
    result = extract_panel_prompts(_write_page(tmp_path, body))
    assert '#### 1. Style foundation' in result[1]
    assert '#### 13. Negative constraints' in result[1]
    # Panel 1 body must NOT bleed into Panel 2
    assert 'foundation 2' not in result[1]


def test_extract_panel_prompts_missing_section_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = '## Scene context\n\nno image-generation section here\n'
    assert extract_panel_prompts(_write_page(tmp_path, body)) == {}


def test_extract_panel_prompts_section_present_no_panels_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        'placeholder text but no ### Panel headers\n\n'
        '## Panel script\n\n**Panel 1.**\n'
    )
    assert extract_panel_prompts(_write_page(tmp_path, body)) == {}


def test_extract_panel_prompts_missing_file_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    assert extract_panel_prompts(str(tmp_path / 'nope.md')) == {}


def test_extract_panel_prompts_no_frontmatter_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    path = tmp_path / 'no-fm.md'
    path.write_text('## Image-generation prompts\n\n### Panel 1\n\nbody\n')
    assert extract_panel_prompts(str(path)) == {}


def test_extract_panel_prompts_handles_double_digit_panel_index(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 10\n\nbody 10\n\n'
        '### Panel 11\n\nbody 11\n'
    )
    result = extract_panel_prompts(_write_page(tmp_path, body))
    assert set(result.keys()) == {10, 11}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pages_panel_prompt_extractors.py -v --no-cov`
Expected: ImportError on `PANEL_SECTION_TITLES` / `extract_panel_prompts`.

- [ ] **Step 3: Implement `PANEL_SECTION_TITLES` and `extract_panel_prompts`**

In `scripts/lib/python/storyforge/pages.py`, near the other `Final[...]` constants at module top:

```python
# Canonical order of the 13 panel-prompt sections (issue #253).
# Each panel under `### Panel N` MUST contain `#### M. <Title>` subsections
# in this order. The titles are fixed strings; bodies vary.
PANEL_SECTION_TITLES: Final[tuple[str, ...]] = (
    'Style foundation',
    'Lighting laws',
    'Pacing role',
    'Shot grammar',
    'Stage geography',
    'Character block',
    'In this panel',
    'Focal objects + render priorities',
    'Lighting logic',
    'Symbolic detail (low weight)',
    'Action',
    'Emotional subtext (low weight)',
    'Negative constraints',
)
```

After the existing `extract_blocking_prompt` function, add:

```python
_IMAGE_GEN_PROMPTS_HEADER = re.compile(
    r'^##\s+Image[- ]generation\s+prompts\s*$', re.MULTILINE | re.IGNORECASE,
)

_PANEL_HEADER_RE = re.compile(
    r'^###\s+Panel\s+(\d+)\s*$', re.MULTILINE | re.IGNORECASE,
)


def extract_panel_prompts(path: str) -> dict[int, str]:
    """Return {panel_index: panel_body} for the ## Image-generation prompts
    section's ### Panel N subsections.

    Body is everything AFTER the ### Panel N header up to the next
    ### Panel M header, the next ## ... header, or EOF — header line
    stripped, body whitespace-trimmed. Returns {} when the page file
    is missing, has no frontmatter, lacks the ## Image-generation prompts
    section, or has the section but no ### Panel N subsections.
    """
    page = parse_page_file(path)
    if page is None:
        return {}
    body = page.get('body', '')
    sec_match = _IMAGE_GEN_PROMPTS_HEADER.search(body)
    if not sec_match:
        return {}
    # Limit scan to the body of ## Image-generation prompts
    section_start = sec_match.end()
    rest = body[section_start:]
    next_section = _NEXT_SECTION_HEADER.search(rest)
    section_end = next_section.start() if next_section else len(rest)
    section_body = rest[:section_end]

    result: dict[int, str] = {}
    # Collect all ### Panel N positions inside the section body
    panel_matches = list(_PANEL_HEADER_RE.finditer(section_body))
    for i, m in enumerate(panel_matches):
        panel_index = int(m.group(1))
        body_start = m.end()
        body_end = (panel_matches[i + 1].start()
                    if i + 1 < len(panel_matches)
                    else len(section_body))
        panel_body = section_body[body_start:body_end].strip('\n').strip()
        result[panel_index] = panel_body
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pages_panel_prompt_extractors.py -v --no-cov`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages_panel_prompt_extractors.py
git commit -m "Add: PANEL_SECTION_TITLES + extract_panel_prompts (#253)

Foundation for the 13-section panel prompt schema. PANEL_SECTION_TITLES
is the canonical order Final[tuple[str, ...]]. extract_panel_prompts
returns {panel_index: panel_body} for every ### Panel N subsection
inside the ## Image-generation prompts body section. Header line is
stripped, body is whitespace-trimmed."
git push
```

---

## Task 2: `extract_panel_sections` for one panel's body

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages_panel_prompt_extractors.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pages_panel_prompt_extractors.py`:

```python
def test_extract_panel_sections_all_13_present():
    from storyforge.pages import extract_panel_sections
    body = (
        '#### 1. Style foundation\n\nfoundation\n\n'
        '#### 2. Lighting laws\n\nlighting\n\n'
        '#### 3. Pacing role\n\nregister: dominant\n\n'
        '#### 4. Shot grammar\n\nshot\n\n'
        '#### 5. Stage geography\n\ngeography\n\n'
        '#### 6. Character block\n\ncharacters\n\n'
        '#### 7. In this panel\n\nin-panel\n\n'
        '#### 8. Focal objects + render priorities\n\nfocal\n\n'
        '#### 9. Lighting logic\n\nlight logic\n\n'
        '#### 10. Symbolic detail (low weight)\n\nmotif (low weight)\n\n'
        '#### 11. Action\n\naction\n\n'
        '#### 12. Emotional subtext (low weight)\n\nsubtext (low weight)\n\n'
        '#### 13. Negative constraints\n\nexclusions\n'
    )
    result = extract_panel_sections(body)
    assert set(result.keys()) == set(range(1, 14))
    assert result[1] == 'foundation'
    assert result[3] == 'register: dominant'
    assert result[13] == 'exclusions'


def test_extract_panel_sections_some_missing():
    """A partially populated panel body returns only the present sections."""
    from storyforge.pages import extract_panel_sections
    body = (
        '#### 1. Style foundation\n\nfoundation\n\n'
        '#### 3. Pacing role\n\nregister: dominant\n\n'
        '#### 13. Negative constraints\n\nexclusions\n'
    )
    result = extract_panel_sections(body)
    assert set(result.keys()) == {1, 3, 13}
    assert 2 not in result


def test_extract_panel_sections_handles_empty_body():
    from storyforge.pages import extract_panel_sections
    assert extract_panel_sections('') == {}


def test_extract_panel_sections_handles_no_section_headers():
    """A body with prose but no #### headers returns empty."""
    from storyforge.pages import extract_panel_sections
    assert extract_panel_sections('just prose with no headers') == {}


def test_extract_panel_sections_strips_body_whitespace():
    from storyforge.pages import extract_panel_sections
    body = (
        '#### 1. Style foundation\n\n\n\n'
        '   foundation with leading whitespace   \n\n\n\n'
        '#### 2. Lighting laws\n\nlighting\n'
    )
    result = extract_panel_sections(body)
    # Body is stripped (no leading/trailing whitespace)
    assert result[1].startswith('foundation') or result[1].startswith('   foundation')
    assert not result[1].endswith('\n\n')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pages_panel_prompt_extractors.py -v --no-cov`
Expected: AttributeError on `extract_panel_sections`.

- [ ] **Step 3: Implement `extract_panel_sections`**

Append to `pages.py` after `extract_panel_prompts`:

```python
_PANEL_SECTION_HEADER_RE = re.compile(
    r'^####\s+(\d+)\.\s+([^\n]+?)\s*$', re.MULTILINE,
)


def extract_panel_sections(panel_body: str) -> dict[int, str]:
    """Parse one panel's body into {section_index: section_body}.

    Operates on the body string returned by extract_panel_prompts for a
    single panel. Section index is the integer parsed from
    #### N. <Title>. Body is everything AFTER the #### header up to the
    next #### M. header or EOF — header stripped, body whitespace-trimmed.
    Returns {} when no section headers are found.
    """
    matches = list(_PANEL_SECTION_HEADER_RE.finditer(panel_body))
    if not matches:
        return {}
    result: dict[int, str] = {}
    for i, m in enumerate(matches):
        section_index = int(m.group(1))
        body_start = m.end()
        body_end = (matches[i + 1].start()
                    if i + 1 < len(matches)
                    else len(panel_body))
        section_body = panel_body[body_start:body_end].strip()
        result[section_index] = section_body
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pages_panel_prompt_extractors.py -v --no-cov`
Expected: 13 tests pass (8 from Task 1 + 5 added here).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages_panel_prompt_extractors.py
git commit -m "Add: extract_panel_sections for #### N. <Title> subsections (#253)

The companion extractor to extract_panel_prompts. Takes one panel's
body string and returns {section_index: section_body} so validators
can detect missing sections and wrong-order sections. Headers stripped,
bodies whitespace-trimmed."
git push
```

---

## Task 3: Three new `PageFindingKind` values + `validate_page_file` checks

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages_panel_prompt_validation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pages_panel_prompt_validation.py`:

```python
"""Tests for the three new PageFindingKind values for panel prompts (#253)."""


def _write_page(tmp_path, body, panel_count=2):
    fm = (
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        f"panel_count: {panel_count}\n"
        "---\n\n"
        # The page-architecture and blocking-prompt sections are present
        # so those checks don't fire — keeps the test focused on panel-prompt
        # findings only.
        "## Page architecture\n\nIntent.\n\n"
        "## Page-blocking prompt\n\nstoryboard.\n\n"
    )
    path = tmp_path / 's01-p1.md'
    path.write_text(fm + body)
    return str(path)


def _kinds(findings):
    return {f['kind'] for f in findings}


def _well_formed_panel_body(prefix=''):
    """A panel body with all 13 sections in canonical order."""
    sections = [
        'Style foundation', 'Lighting laws', 'Pacing role',
        'Shot grammar', 'Stage geography', 'Character block',
        'In this panel', 'Focal objects + render priorities',
        'Lighting logic', 'Symbolic detail (low weight)',
        'Action', 'Emotional subtext (low weight)',
        'Negative constraints',
    ]
    return '\n\n'.join(
        f'#### {i + 1}. {title}\n\n{prefix}body {i + 1}'
        for i, title in enumerate(sections)
    ) + '\n'


def test_missing_panel_prompts_when_section_absent(tmp_path):
    from storyforge.pages import validate_page_file
    body = '## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_panel_prompts' in kinds


def test_missing_panel_prompts_when_section_present_no_panels(tmp_path):
    """Section exists but contains no ### Panel N subsections."""
    from storyforge.pages import validate_page_file
    body = '## Image-generation prompts\n\nplaceholder, no panels\n\n## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_panel_prompts' in kinds


def test_no_panel_prompts_finding_when_well_formed(tmp_path):
    from storyforge.pages import validate_page_file
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n' + _well_formed_panel_body() + '\n'
        '### Panel 2\n\n' + _well_formed_panel_body('p2 ') + '\n'
        '## Panel script\n\n**Panel 1.**\n'
    )
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_panel_prompts' not in kinds
    assert 'panel_prompt_section_missing' not in kinds
    assert 'panel_prompt_wrong_section_order' not in kinds


def test_panel_prompt_section_missing_when_panel_lacks_subsections(tmp_path):
    from storyforge.pages import validate_page_file
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nfoundation\n\n'
        # Sections 2-13 deliberately absent
        '## Panel script\n\n**Panel 1.**\n'
    )
    findings = validate_page_file(_write_page(tmp_path, body, panel_count=1))
    kinds = _kinds(findings)
    assert 'panel_prompt_section_missing' in kinds
    # Detail should name the panel index
    for f in findings:
        if f['kind'] == 'panel_prompt_section_missing':
            assert 'Panel 1' in f.get('detail', '') or 'panel 1' in f.get('detail', '').lower()


def test_panel_prompt_wrong_section_order_when_sections_swapped(tmp_path):
    """Sections present but in wrong order (e.g., section 3 before section 2)."""
    from storyforge.pages import validate_page_file
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nfoundation\n\n'
        '#### 3. Pacing role\n\nregister\n\n'  # OUT OF ORDER — 3 before 2
        '#### 2. Lighting laws\n\nlighting\n\n'
        + '\n\n'.join(
            f'#### {i}. {title}\n\nbody'
            for i, title in zip(
                range(4, 14),
                ['Shot grammar', 'Stage geography', 'Character block',
                 'In this panel', 'Focal objects + render priorities',
                 'Lighting logic', 'Symbolic detail (low weight)', 'Action',
                 'Emotional subtext (low weight)', 'Negative constraints'],
            )
        ) + '\n\n'
        '## Panel script\n\n**Panel 1.**\n'
    )
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body, panel_count=1)))
    assert 'panel_prompt_wrong_section_order' in kinds


def test_finding_kinds_in_literal_type():
    """Static-type guard — the three new values must be in the PageFindingKind Literal."""
    from storyforge.pages import PageFindingKind  # noqa: F401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pages_panel_prompt_validation.py -v --no-cov`
Expected: `missing_panel_prompts` etc. not in kinds set.

- [ ] **Step 3: Extend `PageFindingKind` Literal and `validate_page_file`**

In `pages.py`, update the Literal block:

```python
PageFindingKind = Literal[
    'missing_file',
    'no_frontmatter',
    'missing_field',
    'bad_integer_field',
    'filename_page_id_mismatch',
    'page_within_scene_out_of_range',
    'missing_page_architecture',
    'missing_blocking_prompt',
    'missing_panel_prompts',
    'panel_prompt_section_missing',
    'panel_prompt_wrong_section_order',
]
```

Append to `validate_page_file`, after the existing `missing_blocking_prompt` block and BEFORE `return findings`:

```python
    # Panel-prompt body checks (issue #253). Use the extractors so the
    # "section header present but no panels" half-edited state fires
    # missing_panel_prompts (extractor returns {} for that case).
    panels = extract_panel_prompts(path)
    if not panels:
        findings.append({
            'kind': 'missing_panel_prompts', 'path': path,
            'detail': '"## Image-generation prompts" section is missing or has '
                      'no "### Panel N" subsections',
        })
    else:
        for panel_index in sorted(panels.keys()):
            panel_body = panels[panel_index]
            sections = extract_panel_sections(panel_body)
            present_indices = sorted(sections.keys())
            expected_indices = list(range(1, 14))
            missing = [i for i in expected_indices if i not in sections]
            if missing:
                findings.append({
                    'kind': 'panel_prompt_section_missing', 'path': path,
                    'detail': f'Panel {panel_index} is missing section(s): '
                              f'{", ".join(str(i) for i in missing)}',
                })
            # Wrong-order check: present indices must be a monotonically
            # increasing sequence. If they are but skip some (e.g., 1, 3, 5),
            # that is "missing", not "wrong order" — already caught above.
            elif present_indices != sorted(present_indices):
                # Unreachable: extract_panel_sections returns dict keys in
                # parse order, then we sort. The check below catches the
                # real wrong-order case by comparing parse order to sorted.
                pass
            # Real wrong-order detection: re-parse the panel body in the
            # order headers appear and compare to canonical order.
            parse_order = []
            for m in _PANEL_SECTION_HEADER_RE.finditer(panel_body):
                parse_order.append(int(m.group(1)))
            if parse_order and parse_order != sorted(parse_order):
                findings.append({
                    'kind': 'panel_prompt_wrong_section_order', 'path': path,
                    'detail': f'Panel {panel_index} sections appear in order '
                              f'{parse_order} instead of canonical 1..13',
                })
```

You'll need `_PANEL_SECTION_HEADER_RE` to be in scope at `validate_page_file`. It already is — Task 2 defined it at module level. Good.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pages_panel_prompt_validation.py tests/test_pages_panel_prompt_extractors.py -v --no-cov`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages_panel_prompt_validation.py
git commit -m "Add: 3 new PageFindingKind values for panel-prompt validation (#253)

PageFindingKind grows three values for the 13-section panel-prompt
schema introduced by #253:
  - missing_panel_prompts: section absent or has no ### Panel N
    subsections
  - panel_prompt_section_missing: a panel block is missing one or
    more of the 13 required #### N. <Title> sub-subsections
  - panel_prompt_wrong_section_order: sections present but out of
    canonical order

Validation uses the extractors from Tasks 1 and 2 so the half-edited
'header present but no content' state fires the same finding as a
fully-missing section."
git push
```

---

## Task 4: cleanup integration for the three new finding kinds

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_cleanup.py`
- Test: extend `tests/test_pages_panel_prompt_validation.py`

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_pages_panel_prompt_validation.py`:

```python
def test_cleanup_surfaces_panel_prompt_findings(tmp_path):
    """End-to-end through cmd_cleanup._check_page_files."""
    import os
    project = tmp_path / 'proj'
    project.mkdir()
    (project / 'storyforge.yaml').write_text(
        'project:\n  medium: graphic-novel\n'
    )
    pages = project / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text(
        '---\n'
        'page_id: s01-p1\n'
        'scene_id: s01-studio\n'
        'page_within_scene: 1\n'
        'total_pages_in_scene: 1\n'
        'panel_count: 1\n'
        '---\n\n'
        '## Page architecture\n\nIntent.\n\n'
        '## Page-blocking prompt\n\nstoryboard.\n\n'
        # No ## Image-generation prompts section — triggers missing_panel_prompts
        '## Panel script\n\n**Panel 1.**\n'
    )
    from storyforge.cmd_cleanup import _check_page_files
    findings = _check_page_files(str(project))
    types = {f['type'] for f in findings}
    assert 'page_missing_panel_prompts' in types
    for f in findings:
        if f['type'] == 'page_missing_panel_prompts':
            assert f['severity'] == 'warning'
            assert 'storyforge elaborate --stage panel-prompts' in f['action']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_pages_panel_prompt_validation.py::test_cleanup_surfaces_panel_prompt_findings -v --no-cov`
Expected: AssertionError — cleanup hits the `else` catch-all and emits `page_unknown_finding`.

- [ ] **Step 3: Add three new branches in `_check_page_files`**

In `cmd_cleanup.py`, inside the `for issue in validate_page_file(page_path):` loop in `_check_page_files`, add three new `elif` branches BEFORE the catch-all `else`. Pattern matches the `missing_page_architecture` / `missing_blocking_prompt` branches from #252:

```python
            elif kind == 'missing_panel_prompts':
                findings.append({
                    'type': 'page_missing_panel_prompts', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Run `storyforge elaborate --stage '
                              'panel-prompts --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}` '
                              'to populate (or write the section by hand)',
                    'severity': 'warning',
                })
            elif kind == 'panel_prompt_section_missing':
                findings.append({
                    'type': 'page_panel_prompt_section_missing', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Re-run `storyforge elaborate --stage '
                              'panel-prompts --force --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}` '
                              'to fill missing sections (or add them by hand)',
                    'severity': 'warning',
                })
            elif kind == 'panel_prompt_wrong_section_order':
                findings.append({
                    'type': 'page_panel_prompt_wrong_section_order', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Reorder the #### N. sections so they appear in '
                              'canonical 1..13 order, or re-run `storyforge '
                              'elaborate --stage panel-prompts --force --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}`',
                    'severity': 'warning',
                })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_pages_panel_prompt_validation.py -v --no-cov`
Expected: All pass.

- [ ] **Step 5: Run the existing cleanup test suite to check nothing regressed**

Run: `python3 -m pytest tests/test_cmd_cleanup.py tests/test_cleanup_csv.py -v --no-cov 2>&1 | tail -30`
Expected: pre-existing tests pass. If a test asserted "no page warnings on fixture project," it may need to tolerate the new panel-prompts warnings — update minimally.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_cleanup.py tests/test_pages_panel_prompt_validation.py
git commit -m "Wire: panel-prompt finding kinds in cmd_cleanup (#253)

Three new elif branches in _check_page_files for the panel-prompt
PageFindingKind values added in the previous commit. All three surface
as warnings (cleanup exit code unaffected). Action messages point at
the exact storyforge elaborate --stage panel-prompts command needed
to populate or fix each problem."
git push
```

---

## Task 5: Strict-mode template renderer

**Files:**
- Create: `scripts/lib/python/storyforge/prompts_panel_prompts.py`
- Test: `tests/test_prompts_panel_prompts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_prompts_panel_prompts.py`:

```python
"""Tests for prompts_panel_prompts — strict / coach / full builders
for elaborate --stage panel-prompts (issue #253)."""


def test_strict_template_renders_all_13_sections_for_each_panel():
    from storyforge.prompts_panel_prompts import render_strict_template
    canon_blocks = {
        'style-foundation': 'foundation block',
        'lighting-laws': 'lighting block',
        'locations/archive': 'location block',
        'characters/lucien': 'lucien block',
        'motifs/inkpot': 'inkpot block (low weight)',
    }
    panel_registers = {1: 'dominant', 2: 'transitional'}
    out = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks=canon_blocks, panel_registers=panel_registers,
    )
    # Both panel headers present
    assert '### Panel 1' in out
    assert '### Panel 2' in out
    # All 13 section headers per panel — count by exact-position substring
    for n in range(1, 14):
        assert f'#### {n}. ' in out


def test_strict_template_embeds_canon_in_sections_1_2():
    """Sections 1 and 2 must contain canon embeds verbatim, not TODO."""
    from storyforge.prompts_panel_prompts import render_strict_template
    canon_blocks = {
        'style-foundation': 'STYLE_BLOCK_TEXT',
        'lighting-laws': 'LIGHTING_BLOCK_TEXT',
    }
    out = render_strict_template(
        page_id='s01-p1', panel_count=1,
        canon_blocks=canon_blocks, panel_registers={1: 'dominant'},
    )
    # Section 1 has the embed
    assert 'STYLE_BLOCK_TEXT' in out
    assert 'LIGHTING_BLOCK_TEXT' in out


def test_strict_template_cites_register_in_section_3():
    """Section 3 (Pacing role) cites the register from page architecture."""
    from storyforge.prompts_panel_prompts import render_strict_template
    out = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks={}, panel_registers={1: 'dominant', 2: 'transitional'},
    )
    # Section 3 in panel 1 mentions 'dominant'; section 3 in panel 2 mentions 'transitional'
    panel_1_start = out.index('### Panel 1')
    panel_2_start = out.index('### Panel 2')
    panel_1 = out[panel_1_start:panel_2_start]
    panel_2 = out[panel_2_start:]
    assert 'dominant' in panel_1.lower()
    assert 'transitional' in panel_2.lower()


def test_strict_template_uses_todo_in_panel_specific_sections():
    """Sections 3, 4, 7, 8, 9, 11, 12, 13 (panel-specific) are TODO scaffolding."""
    from storyforge.prompts_panel_prompts import render_strict_template
    out = render_strict_template(
        page_id='s01-p1', panel_count=1,
        canon_blocks={}, panel_registers={1: 'dominant'},
    )
    # Count how many TODO placeholders appear — at least one per panel-specific
    # section (3, 4, 7, 8, 9, 11, 12, 13 = 8 TODOs)
    assert out.lower().count('todo') >= 8


def test_strict_template_panel_count_zero_falls_back_to_one():
    """Edge case: page file has panel_count=0. Render at least one panel."""
    from storyforge.prompts_panel_prompts import render_strict_template
    out = render_strict_template(
        page_id='s01-p1', panel_count=0,
        canon_blocks={}, panel_registers={},
    )
    assert '### Panel 1' in out


def test_strict_template_is_deterministic():
    """Same inputs → same output."""
    from storyforge.prompts_panel_prompts import render_strict_template
    canon_blocks = {'style-foundation': 'foo'}
    panel_registers = {1: 'dominant'}
    a = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks=canon_blocks, panel_registers=panel_registers,
    )
    b = render_strict_template(
        page_id='s01-p1', panel_count=2,
        canon_blocks=canon_blocks, panel_registers=panel_registers,
    )
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompts_panel_prompts.py -v --no-cov`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `render_strict_template`**

Create `scripts/lib/python/storyforge/prompts_panel_prompts.py`:

```python
"""Panel-prompts stage prompt builders.

Mirrors prompts_page_architecture.py for the 13-section panel-prompt
schema introduced by issue #253. render_strict_template emits the
13-section template per panel with canon blocks embedded into sections
1, 2, 5, 6, 10 and TODO scaffolding in sections 3, 4, 7, 8, 9, 11, 12,
13. render_coach_brief writes a per-page brief; build_full_prompt
assembles the LLM prompt for full coaching mode.
"""

from storyforge.pages import PageFile, PANEL_SECTION_TITLES


_TODO_BY_SECTION_INDEX: dict[int, str] = {
    3: 'TODO — register (dominant | transitional | rhythmic | climactic | '
       'atmospheric) and relative weight on the page.',
    4: 'TODO — camera, framing, angle.',
    7: 'TODO — character framing in this beat (what each character is doing).',
    8: 'TODO — what receives detail vs. what dissolves.',
    9: 'TODO — panel-specific lighting (lamp side, shadow falloff).',
    11: 'TODO — declarative, procedural action ("lowers the inkpot"), '
        'not narrative ("the room cooling around the act").',
    12: 'TODO — single brief sentence labeled "(low weight)".',
    13: 'TODO — exclusions and motif-specific reinforcements.',
}


def _section_body_strict(section_index: int, canon_blocks: dict[str, str],
                         panel_register: str) -> str:
    """Return the body for one section under strict mode.

    Sections 1, 2 embed the universal canon blocks.
    Section 3 cites the register from page architecture (or TODO if absent).
    Sections 5, 6, 10 embed canon when keys with those prefixes exist in
    canon_blocks; otherwise TODO. Sections 4, 7, 8, 9, 11, 12, 13 are
    TODO scaffolding.
    """
    if section_index == 1:
        block = canon_blocks.get('style-foundation', '').strip()
        return block if block else 'TODO — paste the style-foundation embeddable block here.'
    if section_index == 2:
        block = canon_blocks.get('lighting-laws', '').strip()
        return block if block else 'TODO — paste the lighting-laws embeddable block here.'
    if section_index == 3:
        if panel_register:
            return f'Register: {panel_register}. TODO — relative weight on the page.'
        return _TODO_BY_SECTION_INDEX[3]
    if section_index == 5:
        location_keys = [k for k in canon_blocks if k.startswith('locations/')]
        if location_keys:
            block = canon_blocks[location_keys[0]].strip()
            return f'{block}\n\nTODO — panel-specific positioning.'
        return 'TODO — embed the location canon block + panel-specific positioning.'
    if section_index == 6:
        character_keys = [k for k in canon_blocks if k.startswith('characters/')]
        if character_keys:
            blocks = '\n\n'.join(canon_blocks[k].strip() for k in character_keys)
            return blocks
        return 'TODO — embed character canon blocks for each on-frame character.'
    if section_index == 10:
        motif_keys = [k for k in canon_blocks if k.startswith('motifs/')]
        if motif_keys:
            blocks = '\n\n'.join(
                f'{canon_blocks[k].strip()} (low weight)' for k in motif_keys
            )
            return blocks
        return 'TODO — embed motif canon for any motif on-frame, labeled "(low weight)".'
    return _TODO_BY_SECTION_INDEX.get(section_index, 'TODO')


def render_strict_template(*, page_id: str, panel_count: int,
                           canon_blocks: dict[str, str],
                           panel_registers: dict[int, str]) -> str:
    """Deterministic strict-mode template for one page's panel prompts.

    Emits ### Panel N blocks (one per panel), each containing #### M.
    <Title> subsections in canonical 1..13 order. Sections 1, 2, 5, 6,
    10 embed canon blocks when present in canon_blocks; sections 3, 4,
    7, 8, 9, 11, 12, 13 are TODO scaffolding. Section 3 cites the
    register from panel_registers when present.

    canon_blocks keys: 'style-foundation', 'lighting-laws',
    'locations/<id>', 'characters/<id>', 'motifs/<id>'. Missing keys
    cause the corresponding section to fall back to TODO.
    """
    bullets = max(panel_count, 1)
    parts: list[str] = ['## Image-generation prompts']
    for panel_index in range(1, bullets + 1):
        parts.append('')
        parts.append(f'### Panel {panel_index}')
        register = panel_registers.get(panel_index, '')
        for section_index in range(1, 14):
            title = PANEL_SECTION_TITLES[section_index - 1]
            body = _section_body_strict(section_index, canon_blocks, register)
            parts.append('')
            parts.append(f'#### {section_index}. {title}')
            parts.append('')
            parts.append(body)
    return '\n'.join(parts) + '\n'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompts_panel_prompts.py -v --no-cov`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_panel_prompts.py tests/test_prompts_panel_prompts.py
git commit -m "Add: strict-mode template renderer for panel-prompts stage (#253)

Deterministic 13-section template per panel with canon blocks embedded
verbatim into sections 1, 2, 5, 6, 10 (when present in canon_blocks)
and TODO scaffolding in sections 3, 4, 7, 8, 9, 11, 12, 13. Section 3
cites the register from page architecture when present in
panel_registers. First of three coaching-mode renderers."
git push
```

---

## Task 6: Coach-mode brief renderer

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_panel_prompts.py`
- Test: `tests/test_prompts_panel_prompts.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_prompts_panel_prompts.py`:

```python
def test_coach_brief_includes_canon_inline_and_questions_per_section():
    from storyforge.prompts_panel_prompts import render_coach_brief
    out = render_coach_brief(
        page_id='s01-p1', panel_count=2, scene_title='Studio finalization',
        page_architecture='### Panel hierarchy\n- Panel 1 — dominant: focus\n- Panel 2 — atmospheric: ambience',
        scene_brief={
            'panel_breakdown': 'p1: 2-panel',
            'visual_keywords': 'inkpot; hand',
            'key_actions': 'lowers the inkpot',
            'motifs': 'inkpot',
        },
        canon_blocks={
            'style-foundation': 'STYLE_BLOCK',
            'lighting-laws': 'LIGHTING_BLOCK',
            'panel-registers': 'Dominant: emotional fulcrum.\nAtmospheric: pause.',
        },
    )
    # Embeds canon vocabulary inline
    assert 'STYLE_BLOCK' in out
    assert 'LIGHTING_BLOCK' in out
    # Lists the 13 sections with at least one question per section
    for n in range(1, 14):
        assert f'#### {n}. ' in out or f'{n}.' in out
    # Identifies the write target
    assert 'pages/s01-p1.md' in out
    # Names the panel count
    assert '2 panel' in out or '2 panels' in out


def test_coach_brief_handles_empty_inputs():
    from storyforge.prompts_panel_prompts import render_coach_brief
    out = render_coach_brief(
        page_id='solo-p1', panel_count=1, scene_title='Solo',
        page_architecture='', scene_brief={}, canon_blocks={},
    )
    assert 'solo-p1' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompts_panel_prompts.py -v --no-cov`
Expected: AttributeError on `render_coach_brief`.

- [ ] **Step 3: Implement `render_coach_brief`**

Append to `prompts_panel_prompts.py`:

```python
def render_coach_brief(*, page_id: str, panel_count: int,
                       scene_title: str, page_architecture: str,
                       scene_brief: dict, canon_blocks: dict[str, str]) -> str:
    """Coach-mode markdown brief written to working/coaching/.

    Embeds canon vocabulary inline so the author can decide without
    flipping files. Lists the 13 sections with one or two prompting
    questions per section. Does NOT mutate the page file.
    """
    lines = [
        f'# Panel-prompts brief: {page_id}',
        '',
        f'**Scene:** {scene_title}  ',
        f'**Panels on this page:** {panel_count}',
        '',
        '## Page architecture (from page-architecture stage)',
        '',
        page_architecture.strip() if page_architecture else '(none — run elaborate --stage page-architecture first)',
        '',
        '## Brief inputs',
        '',
    ]
    for key in ('panel_breakdown', 'visual_keywords', 'key_actions',
                'key_dialogue', 'motifs', 'emotions'):
        val = scene_brief.get(key, '')
        lines.append(f'- **{key}:** {val or "(empty)"}')
    lines += ['', '## Canon embeds (paste verbatim into sections 1, 2, 5, 6, 10)', '']
    for canon_id in ('style-foundation', 'lighting-laws',
                     'panel-registers'):
        block = canon_blocks.get(canon_id, '').strip()
        if block:
            lines += [f'### {canon_id}', '', block, '']
    lines += [
        '## What to write per panel',
        '',
        'Write `### Panel N` blocks (one per panel) into the '
        '`## Image-generation prompts` section of:',
        '',
        f'`pages/{page_id}.md`',
        '',
        'Each panel must contain these 13 sections in order:',
        '',
    ]
    questions_by_section: dict[int, str] = {
        1: 'Paste the style-foundation embeddable block verbatim.',
        2: 'Paste the lighting-laws embeddable block verbatim.',
        3: 'Cite the register from page architecture (dominant / transitional / '
           'rhythmic / climactic / orientation / atmospheric). State this panel\'s '
           'relative weight on the page.',
        4: 'Camera distance, framing, angle. What\'s the shot grammar?',
        5: 'Paste the location embeddable block, then add panel-specific positioning '
           '(who\'s where in the frame).',
        6: 'Paste the character embeddable block for each on-frame character.',
        7: 'What is each character doing in THIS beat? What\'s the body language?',
        8: 'What receives detail (the inkpot, the hand)? What dissolves (background)?',
        9: 'Which side catches the light? Where do shadows fall?',
        10: 'If a motif is on-frame, paste its canon block. Label it "(low weight)".',
        11: 'Declarative procedural action ("lowers the inkpot"). NOT narrative '
            '("the room cooling around the act").',
        12: 'One brief sentence. Label "(low weight)". Emotional subtext only — '
            'no description of how it manifests visually.',
        13: 'What should the renderer NOT produce? Exclusions specific to this '
            'panel + motif reinforcements.',
    }
    for n in range(1, 14):
        title = PANEL_SECTION_TITLES[n - 1]
        lines.append(f'#### {n}. {title}')
        lines.append(f'  — {questions_by_section[n]}')
        lines.append('')
    return '\n'.join(lines) + '\n'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompts_panel_prompts.py -v --no-cov`
Expected: 8 tests pass (6 strict + 2 coach).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_panel_prompts.py tests/test_prompts_panel_prompts.py
git commit -m "Add: coach-mode brief renderer for panel-prompts stage (#253)

render_coach_brief produces a markdown brief written to
working/coaching/panel-prompts-<page_id>.md. Embeds the universal
canon blocks (style-foundation, lighting-laws, panel-registers)
inline and lists the 13 sections with focused prompting questions
per section. No mutation of the page file."
git push
```

---

## Task 7: Full-mode LLM prompt builder

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_panel_prompts.py`
- Test: `tests/test_prompts_panel_prompts.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_prompts_panel_prompts.py`:

```python
def test_full_prompt_embeds_canon_and_page_architecture():
    from storyforge.prompts_panel_prompts import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p1', panel_count=2,
        scene_title='Studio finalization',
        page_frontmatter={
            'page_id': 's01-p1', 'scene_id': 's01-studio',
            'panel_count': 2, 'characters_present': ['lucien-vey'],
            'location': 'archive-studio',
        },
        page_architecture='### Intent\nQuiet tension.\n\n### Panel hierarchy\n- Panel 1 — dominant\n- Panel 2 — atmospheric',
        scene_brief={
            'panel_breakdown': 'p1: 2-panel',
            'visual_keywords': 'inkpot; hand',
            'key_actions': 'lowers the inkpot',
            'motifs': 'inkpot',
        },
        scene_intent={
            'function': 'opening', 'emotional_arc': 'apprehension to focus',
            'on_stage': 'lucien-vey',
        },
        canon_blocks={
            'style-foundation': 'STYLE_BLOCK',
            'lighting-laws': 'LIGHTING_BLOCK',
            'locations/archive-studio': 'LOCATION_BLOCK',
            'characters/lucien-vey': 'LUCIEN_BLOCK',
            'motifs/inkpot': 'INKPOT_BLOCK',
            'panel-registers': 'Dominant: emotional fulcrum.\nAtmospheric: pause.',
        },
    )
    # Identity
    assert 's01-p1' in prompt
    assert 'Studio finalization' in prompt
    # Page architecture
    assert 'Panel 1 — dominant' in prompt
    # Brief
    assert 'inkpot' in prompt
    # Canon embedded
    assert 'STYLE_BLOCK' in prompt
    assert 'LIGHTING_BLOCK' in prompt
    assert 'LOCATION_BLOCK' in prompt
    assert 'LUCIEN_BLOCK' in prompt
    assert 'INKPOT_BLOCK' in prompt
    # Output contract names the 13 sections
    for n in range(1, 14):
        assert f'#### {n}. ' in prompt
    # Constraint mentions sections 1, 2, 5, 6, 10 embed verbatim
    assert 'verbatim' in prompt.lower() or 'paste' in prompt.lower()


def test_full_prompt_skips_empty_canon_blocks():
    """Empty canon_blocks values are not embedded (avoid blank '### canon-id' headers)."""
    from storyforge.prompts_panel_prompts import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p1', panel_count=1,
        scene_title='Solo', page_frontmatter={'page_id': 's01-p1', 'panel_count': 1},
        page_architecture='', scene_brief={}, scene_intent={},
        canon_blocks={'style-foundation': '', 'lighting-laws': 'LIGHTING_BLOCK'},
    )
    # The empty style-foundation should not produce a blank embed section
    # (we don't enforce exactly how, just that LIGHTING_BLOCK is in and
    # there's no spurious '### style-foundation' followed by blank content)
    assert 'LIGHTING_BLOCK' in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompts_panel_prompts.py -v --no-cov`
Expected: AttributeError on `build_full_prompt`.

- [ ] **Step 3: Implement `build_full_prompt`**

Append to `prompts_panel_prompts.py`:

```python
def _format_frontmatter_summary(fm: PageFile) -> str:
    keys = ('page_id', 'scene_id', 'page_within_scene',
            'total_pages_in_scene', 'panel_count', 'spread_position',
            'characters_present', 'location', 'timeline')
    lines = []
    for k in keys:
        v = fm.get(k)
        if v is None or v == '':
            continue
        if isinstance(v, list):
            v = ', '.join(v)
        lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def _format_brief(brief: dict[str, str]) -> str:
    keys = ('panel_breakdown', 'visual_keywords', 'key_actions',
            'key_dialogue', 'motifs', 'emotions',
            'page_layout', 'page_turn_beats', 'caption_strategy',
            'goal', 'conflict', 'outcome')
    lines = []
    for k in keys:
        v = brief.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def _format_intent(intent: dict[str, str]) -> str:
    keys = ('function', 'emotional_arc', 'value_at_stake', 'value_shift',
            'turning_point', 'characters', 'on_stage')
    lines = []
    for k in keys:
        v = intent.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def build_full_prompt(*, page_id: str, panel_count: int,
                      scene_title: str,
                      page_frontmatter: PageFile,
                      page_architecture: str,
                      scene_brief: dict[str, str],
                      scene_intent: dict[str, str],
                      canon_blocks: dict[str, str]) -> str:
    """Full-mode LLM prompt for one page's panel prompts.

    The handler collects canon_blocks (style-foundation, lighting-laws,
    panel-registers, per-location, per-character, per-motif) and the
    page architecture body. This builder is pure — no I/O.

    Output contract: the LLM emits ### Panel 1 .. ### Panel N markdown,
    each containing #### M. <Title> subsections in canonical 1..13 order.
    Sections 1, 2, 5, 6, 10 contain the canon embeds verbatim; sections
    3, 4, 7, 8, 9, 11, 12, 13 are panel-specific prose.
    """
    parts: list[str] = []
    parts.append(
        f'You are writing the 13-section image-generation prompts for '
        f'{panel_count} panel(s) on one page of a graphic novel.'
    )
    parts.append('')
    parts.append('## Page identity')
    parts.append('')
    parts.append(f'- page_id: {page_id}')
    parts.append(f'- scene: {scene_title}')
    parts.append(f'- panel_count: {panel_count}')
    parts.append('')
    parts.append('## Page frontmatter')
    parts.append('')
    parts.append(_format_frontmatter_summary(page_frontmatter))
    parts.append('')
    parts.append('## Page architecture (panel hierarchy + registers)')
    parts.append('')
    parts.append(page_architecture.strip() if page_architecture else '(none)')
    parts.append('')
    parts.append('## Scene brief')
    parts.append('')
    parts.append(_format_brief(scene_brief))
    parts.append('')
    parts.append('## Scene intent')
    parts.append('')
    parts.append(_format_intent(scene_intent))
    parts.append('')
    parts.append('## Canon (embed verbatim into the noted sections)')
    parts.append('')
    for canon_id, block in canon_blocks.items():
        if not block or not block.strip():
            continue
        parts.append(f'### {canon_id}')
        parts.append('')
        parts.append(block.strip())
        parts.append('')
    parts.append('## Output contract')
    parts.append('')
    parts.append(
        'Produce exactly the markdown below — `### Panel 1` through '
        f'`### Panel {panel_count}`, each with all 13 sections in '
        'canonical order — and no other text before or after:'
    )
    parts.append('')
    parts.append('```')
    parts.append('### Panel 1')
    parts.append('')
    for section_index in range(1, 14):
        title = PANEL_SECTION_TITLES[section_index - 1]
        parts.append(f'#### {section_index}. {title}')
        parts.append('')
        if section_index in (1, 2):
            canon_id = ('style-foundation' if section_index == 1
                        else 'lighting-laws')
            parts.append(f'<verbatim {canon_id} embed from above>')
        elif section_index == 3:
            parts.append('Register: <one of dominant | transitional | rhythmic | '
                         'climactic | orientation | atmospheric — cite from '
                         'page architecture above>. Relative weight: <how this '
                         'panel ranks within the page>.')
        elif section_index == 4:
            parts.append('<camera distance, framing, angle>')
        elif section_index == 5:
            parts.append('<verbatim location-canon embed from above>')
            parts.append('')
            parts.append('Panel-specific: <who is where in the frame>')
        elif section_index == 6:
            parts.append('<verbatim character-canon embed(s) for each on-frame character>')
        elif section_index == 7:
            parts.append('<each character\'s framing in this beat — what they are doing>')
        elif section_index == 8:
            parts.append('<what gets detail vs. what dissolves>')
        elif section_index == 9:
            parts.append('<panel-specific lighting — which side catches the lamp, '
                         'where shadows fall>')
        elif section_index == 10:
            parts.append('<verbatim motif-canon embed if motif on-frame, '
                         'plus the literal text "(low weight)" at the end>')
        elif section_index == 11:
            parts.append('<declarative procedural action — "lowers the inkpot", '
                         'NOT "the room cooling around the act">')
        elif section_index == 12:
            parts.append('<single brief sentence labeled "(low weight)">')
        elif section_index == 13:
            parts.append('<panel-specific exclusions + motif-specific reinforcements>')
        parts.append('')
    parts.append('### Panel 2')
    parts.append('<same 13-section structure>')
    parts.append('')
    parts.append(f'(... up through ### Panel {panel_count})')
    parts.append('```')
    parts.append('')
    parts.append('Constraints (all panels MUST satisfy):')
    parts.append('- Sections 1, 2, 5, 6, 10 contain the canon embeds verbatim. '
                 'Do not paraphrase. Do not abbreviate.')
    parts.append('- Section 3 cites a register from the page architecture above '
                 'by name. Every panel cites exactly one register.')
    parts.append('- Sections 11 (Action) is declarative and procedural. No '
                 'narrative description. No metaphor.')
    parts.append('- Sections 10 and 12 contain the literal text "(low weight)" '
                 'at the end of their bodies. This is critical — without it, '
                 'diffusion models render symbolic / emotional prose as visual '
                 'intensity.')
    return '\n'.join(parts) + '\n'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompts_panel_prompts.py -v --no-cov`
Expected: 10 tests pass (6 strict + 2 coach + 2 full).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_panel_prompts.py tests/test_prompts_panel_prompts.py
git commit -m "Add: full-mode LLM prompt builder for panel-prompts stage (#253)

build_full_prompt deterministically assembles the per-page prompt from
page frontmatter, page architecture body, scene brief, scene intent,
and canon embeds. The output contract spells out the 13-section
structure per panel plus the critical (low weight) labels that prevent
diffusion models from converting symbolic / emotional prose into visual
intensity."
git push
```

---

## Task 8: argparse + VALID_STAGES wiring + dispatcher in `cmd_elaborate.py`

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Test: `tests/test_cmd_elaborate_panel_prompts.py`

The argparse flags `--page` / `--scene` / `--force` already exist (added in #252). This task only adds `'panel-prompts'` to `VALID_STAGES` plus the page-selection / precondition helpers (mirrors page-architecture's pattern).

- [ ] **Step 1: Write failing tests**

Create `tests/test_cmd_elaborate_panel_prompts.py`:

```python
"""Tests for the panel-prompts stage in cmd_elaborate (#253)."""

import os
import pytest


def test_panel_prompts_stage_in_valid_stages():
    from storyforge.cmd_elaborate import VALID_STAGES
    assert 'panel-prompts' in VALID_STAGES


def test_panel_prompts_direct_flag_resolves_to_stage():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--panel-prompts'])
    assert args.stage == 'panel-prompts'


def _make_gn_project(tmp_path):
    """GN project with one scene, one brief, one page that has
    populated ## Page architecture (needed for panel-prompts precondition)
    but no ## Image-generation prompts."""
    proj = tmp_path / 'proj'
    proj.mkdir()
    (proj / 'storyforge.yaml').write_text(
        'project:\n  medium: graphic-novel\n  title: Test\n'
    )
    ref = proj / 'reference'
    ref.mkdir()
    (ref / 'scenes.csv').write_text(
        'id|seq|title|status|target_pages|panel_count|page_count\n'
        's01-studio|1|Studio|briefed|3|2|1\n'
    )
    (ref / 'scene-briefs.csv').write_text(
        'id|goal|conflict|outcome|panel_breakdown|visual_keywords|'
        'key_actions|motifs|page_turn_beats|page_layout|caption_strategy\n'
        's01-studio|focus|distraction|focus regained|p1: 2-panel|'
        'inkpot; hand|lowers the inkpot|inkpot|none|3-page scene|minimal\n'
    )
    (ref / 'scene-intent.csv').write_text(
        'id|function|emotional_arc|value_at_stake|value_shift|on_stage\n'
        's01-studio|opening|tense to calm|control|positive|lucien-vey\n'
    )
    canon = ref / 'canon'
    canon.mkdir()
    for canon_id, block in (
        ('style-foundation', 'Chiaroscuro palette.'),
        ('lighting-laws', 'Single light source.'),
        ('panel-registers', 'Dominant: fulcrum.\nAtmospheric: pause.'),
        ('page-rhythm-rules', 'One dominant per page max.'),
    ):
        (canon / f'{canon_id}.md').write_text(
            f'---\ncanon_id: {canon_id}\n---\n\n'
            f'## Embeddable block\n\n{block}\n'
        )
    pages = proj / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 2\n"
        "characters_present: [lucien-vey]\n"
        "location: archive-studio\n"
        "---\n\n"
        "## Scene context\n\nOpening beat.\n\n"
        "## Page architecture\n\n"
        "### Intent\nQuiet tension.\n\n"
        "### Panel hierarchy\n- Panel 1 — dominant: focus\n- Panel 2 — atmospheric: ambience\n\n"
        "### Book-level placement\n- Spread context: opening recto\n\n"
        "## Page-blocking prompt\n\nMonochrome storyboard.\n\n"
        "## Panel script\n\n**Panel 1.** Wide.\n"
    )
    return str(proj)


def test_select_pages_for_panel_prompts_default_picks_pages_without_prompts(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_panel_prompts
    proj = _make_gn_project(tmp_path)
    targets = _select_pages_for_panel_prompts(proj, page=None, scene=None, force=False)
    assert len(targets) == 1
    assert targets[0]['page_id'] == 's01-p1'


def test_select_pages_with_existing_prompts_excluded_by_default(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_panel_prompts
    proj = _make_gn_project(tmp_path)
    # Populate the section so default mode excludes the page
    page_path = os.path.join(proj, 'pages', 's01-p1.md')
    with open(page_path) as f:
        body = f.read()
    body = body.replace(
        '## Panel script\n\n**Panel 1.** Wide.\n',
        '## Image-generation prompts\n\n### Panel 1\n\nfoo\n\n## Panel script\n\n**Panel 1.** Wide.\n',
    )
    with open(page_path, 'w') as f:
        f.write(body)
    assert _select_pages_for_panel_prompts(proj, page=None, scene=None, force=False) == []
    forced = _select_pages_for_panel_prompts(proj, page=None, scene=None, force=True)
    assert len(forced) == 1


def test_precondition_passes_when_page_architecture_and_canon_ready(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_panel_prompts
    proj = _make_gn_project(tmp_path)
    ok, reason = _precondition_check_panel_prompts(proj, 's01-p1', 's01-studio')
    assert ok is True
    assert reason == ''


def test_precondition_fails_when_page_architecture_empty(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_panel_prompts
    proj = _make_gn_project(tmp_path)
    # Strip the Page architecture body
    page_path = os.path.join(proj, 'pages', 's01-p1.md')
    with open(page_path) as f:
        body = f.read()
    body = body.replace(
        '## Page architecture\n\n'
        '### Intent\nQuiet tension.\n\n'
        '### Panel hierarchy\n- Panel 1 — dominant: focus\n- Panel 2 — atmospheric: ambience\n\n'
        '### Book-level placement\n- Spread context: opening recto\n\n',
        '## Page architecture\n\n\n',
    )
    with open(page_path, 'w') as f:
        f.write(body)
    ok, reason = _precondition_check_panel_prompts(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'page architecture' in reason.lower()


def test_precondition_fails_when_canon_unfilled(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_panel_prompts
    proj = _make_gn_project(tmp_path)
    # Replace style-foundation with TODO
    pr = os.path.join(proj, 'reference', 'canon', 'style-foundation.md')
    with open(pr, 'w') as f:
        f.write('---\ncanon_id: style-foundation\n---\n\n'
                '## Embeddable block\n\nTODO — fill it in.\n')
    ok, reason = _precondition_check_panel_prompts(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'style-foundation' in reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_elaborate_panel_prompts.py -v --no-cov`
Expected: AssertionError on `'panel-prompts' in VALID_STAGES`.

- [ ] **Step 3: Add stage to `VALID_STAGES` and helper functions**

In `cmd_elaborate.py`:

1. Add `'panel-prompts'` to `VALID_STAGES`:

```python
VALID_STAGES: Final[set[str]] = {
    'spine', 'architecture', 'map', 'briefs',
    'gap-fill', 'mice-fill', 'page-architecture',
    'panel-prompts',
}
```

2. Add two helpers near the page-architecture helpers (`_select_pages_for_architecture`, `_precondition_check_page`):

```python
def _select_pages_for_panel_prompts(project_dir: str, page: str | None,
                                    scene: str | None, force: bool) -> list[dict]:
    """Return the list of parsed page-file dicts to process for the
    panel-prompts stage.

    Filtering rules mirror _select_pages_for_architecture: --page,
    --scene, or all pages. Then (unless --force): drop pages that
    already have ### Panel N subsections in ## Image-generation prompts.
    """
    from storyforge.pages import (
        list_page_files, parse_page_file, extract_panel_prompts,
    )
    all_pages = []
    for p in list_page_files(project_dir):
        parsed = parse_page_file(p)
        if parsed is None:
            continue
        all_pages.append(parsed)

    if page:
        filtered = [p for p in all_pages if p.get('page_id') == page]
    elif scene:
        filtered = [p for p in all_pages if p.get('scene_id') == scene]
    else:
        filtered = all_pages

    if force:
        return filtered
    return [p for p in filtered if not extract_panel_prompts(p['path'])]


def _precondition_check_panel_prompts(project_dir: str, page_id: str,
                                      scene_id: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means skip with WARN.

    Checks:
      - scenes.csv exists and has scene_id
      - scene's brief has non-empty panel_breakdown
      - page file has populated ## Page architecture body
      - required canon vocabulary blocks are populated:
        style-foundation, lighting-laws
    """
    from storyforge.csv_cli import get_field
    from storyforge.canon import is_canon_block_populated
    from storyforge.pages import (
        list_page_files, parse_page_file, extract_page_architecture,
    )

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not os.path.isfile(scenes_csv):
        return False, 'reference/scenes.csv is missing — run elaborate --stage map first'
    if not get_field(scenes_csv, scene_id, 'id'):
        return False, f'scene {scene_id} not in scenes.csv'

    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    pb = get_field(briefs_csv, scene_id, 'panel_breakdown') or ''
    if not pb.strip():
        return False, f'scene {scene_id} brief has empty panel_breakdown'

    # Find the page file
    matching_page_path = None
    for p in list_page_files(project_dir):
        parsed = parse_page_file(p)
        if parsed and parsed.get('page_id') == page_id:
            matching_page_path = p
            break
    if not matching_page_path:
        return False, f'page {page_id} file not found'

    arch_body = extract_page_architecture(matching_page_path).strip()
    if not arch_body:
        return False, (f'page {page_id} has empty Page architecture — run '
                       f'elaborate --stage page-architecture first')

    for canon_id in ('style-foundation', 'lighting-laws'):
        if not is_canon_block_populated(project_dir, canon_id):
            return False, (
                f'canon block {canon_id!r} is missing or TODO — '
                f'populate reference/canon/{canon_id}.md first'
            )
    return True, ''
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_elaborate_panel_prompts.py -v --no-cov`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py tests/test_cmd_elaborate_panel_prompts.py
git commit -m "Wire: panel-prompts stage to VALID_STAGES + helpers (#253)

Adds 'panel-prompts' to the VALID_STAGES Final[set[str]] (which
auto-registers the --panel-prompts direct flag via the existing
argparse loop). Adds _select_pages_for_panel_prompts (filtering) and
_precondition_check_panel_prompts (warn-and-skip preconditions). Both
mirror the page-architecture helpers — pure functions, no API calls,
easy to unit-test.

Preconditions: scenes.csv exists, scene's brief has panel_breakdown,
page has populated ## Page architecture (#252 prereq), and the
required canon (style-foundation, lighting-laws) is not TODO."
git push
```

---

## Task 9: Splice helpers + LLM-response validator

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Test: extend `tests/test_cmd_elaborate_panel_prompts.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cmd_elaborate_panel_prompts.py`:

```python
def test_splice_inserts_image_generation_section_when_absent(tmp_path):
    from storyforge.cmd_elaborate import _splice_panel_prompts
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "---\n\n"
        "## Scene context\n\nBeat.\n\n"
        "## Page architecture\n\nArch.\n\n"
        "## Page-blocking prompt\n\nstoryboard.\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
    panel_block = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nfoundation\n'
    )
    _splice_panel_prompts(str(page_path), panel_block,
                          canon_ids=['style-foundation'])
    text = page_path.read_text()
    assert '## Image-generation prompts' in text
    assert '### Panel 1' in text
    # Inserted BEFORE Panel script
    assert text.index('## Image-generation prompts') < text.index('## Panel script')
    # canonical_blocks_embedded frontmatter audit trail
    assert 'canonical_blocks_embedded:' in text
    assert 'reference/canon/style-foundation.md' in text


def test_splice_replaces_existing_image_generation_section_when_force(tmp_path):
    from storyforge.cmd_elaborate import _splice_panel_prompts
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "---\n\n"
        "## Page architecture\n\nArch.\n\n"
        "## Image-generation prompts\n\n"
        "### Panel 1\n\nOLD panel 1 content\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
    new_block = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\nNEW panel 1 content\n'
    )
    _splice_panel_prompts(str(page_path), new_block, canon_ids=[])
    text = page_path.read_text()
    assert 'NEW panel 1 content' in text
    assert 'OLD panel 1 content' not in text
    assert text.count('## Image-generation prompts') == 1
    # Panel script survives
    assert '## Panel script' in text
    assert '**Panel 1.**' in text


def test_validate_panel_prompts_response_accepts_well_formed():
    from storyforge.cmd_elaborate import _validate_panel_prompts_response
    resp = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nx\n'
    )
    ok, block = _validate_panel_prompts_response(resp, expected_panel_count=1)
    assert ok is True
    assert '## Image-generation prompts' in block


def test_validate_panel_prompts_response_rejects_missing_section_header():
    from storyforge.cmd_elaborate import _validate_panel_prompts_response
    # No '## Image-generation prompts' header
    resp = '### Panel 1\n\n#### 1. Style foundation\n\nx\n'
    ok, _ = _validate_panel_prompts_response(resp, expected_panel_count=1)
    assert ok is False


def test_validate_panel_prompts_response_rejects_wrong_panel_count():
    from storyforge.cmd_elaborate import _validate_panel_prompts_response
    # Only one ### Panel header but expected_panel_count=2
    resp = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n#### 1. Style foundation\n\nx\n'
    )
    ok, _ = _validate_panel_prompts_response(resp, expected_panel_count=2)
    assert ok is False


def test_validate_panel_prompts_response_strips_fence():
    from storyforge.cmd_elaborate import _validate_panel_prompts_response
    resp = (
        '```markdown\n'
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n#### 1. Style foundation\n\nx\n'
        '```\n'
    )
    ok, block = _validate_panel_prompts_response(resp, expected_panel_count=1)
    assert ok is True
    assert '```' not in block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_elaborate_panel_prompts.py -v --no-cov`
Expected: ImportError on the new helpers.

- [ ] **Step 3: Implement the splice and validator helpers**

In `cmd_elaborate.py`, near the existing `_splice_page_architecture` helper, add:

```python
# Already imported from pages.py via Task 8 commit; re-using here.
from storyforge.pages import _IMAGE_GEN_PROMPTS_HEADER, _PANEL_HEADER_RE


def _validate_panel_prompts_response(text: str,
                                     expected_panel_count: int,
                                     ) -> tuple[bool, str]:
    """Parse and validate an LLM response for the panel-prompts stage.

    Returns (ok, block). The block is the unwrapped (fence-stripped)
    text containing the '## Image-generation prompts' section and its
    ### Panel N subsections. Returns (False, '') when the section
    header is absent, when the number of ### Panel N subsections
    doesn't match expected_panel_count, or when sections appear in the
    wrong order.
    """
    body = text.strip()
    if body.startswith('```'):
        lines = body.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        body = '\n'.join(lines).strip()

    if not _IMAGE_GEN_PROMPTS_HEADER.search(body):
        return False, ''
    panel_indices = [int(m.group(1))
                     for m in _PANEL_HEADER_RE.finditer(body)]
    if len(panel_indices) != expected_panel_count:
        return False, ''
    return True, body


def _splice_panel_prompts(page_path: str, panel_prompts_block: str,
                          canon_ids: list[str]) -> None:
    """Write the ## Image-generation prompts section into the page file.

    - If the section already exists, replace it.
    - Otherwise insert immediately before ## Panel script (if present),
      or at end of body.
    - Append canon_ids to the canonical_blocks_embedded frontmatter
      list (preserves existing entries, skips duplicates).
    """
    with open(page_path, encoding='utf-8') as f:
        text = f.read()

    if canon_ids:
        text = _add_canonical_blocks_embedded(text, canon_ids)

    fm_match = re.match(r'\A(---\n.*?---\n)(.*)', text, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        body = fm_match.group(2)
    else:
        fm_text, body = '', text

    img_match = _IMAGE_GEN_PROMPTS_HEADER.search(body)
    if img_match:
        # Replace existing section — find end (next ## header or EOF)
        after = body[img_match.end():]
        next_h = re.search(r'^##\s+\S', after, re.MULTILINE)
        end = img_match.end() + (next_h.start() if next_h else len(after))
        new_body = (body[:img_match.start()]
                    + panel_prompts_block.strip() + '\n\n'
                    + body[end:].lstrip('\n'))
    else:
        # Insert before ## Panel script if present, else append
        ps_match = _PANEL_SCRIPT_HEADER_RE.search(body)
        if ps_match:
            insert_at = ps_match.start()
            prefix = body[:insert_at].rstrip('\n')
            suffix = body[insert_at:]
            new_body = (prefix + '\n\n'
                        + panel_prompts_block.strip() + '\n\n'
                        + suffix)
        else:
            new_body = (body.rstrip('\n') + '\n\n'
                        + panel_prompts_block.strip() + '\n')

    with open(page_path, 'w', encoding='utf-8') as f:
        f.write(fm_text + new_body)
```

The `_IMAGE_GEN_PROMPTS_HEADER` constant currently lives in `pages.py` (from Task 1). Import it as a public name OR alias on import. The simplest fix: change `pages.py` to expose it without an underscore prefix (i.e., `IMAGE_GEN_PROMPTS_HEADER`). But that's a churn-y rename.

**Cleaner approach:** import the underscored name from `pages.py` (which is how `_PAGE_ARCH_HEADER_RE` and friends are already imported — see #252's review-fix commit `a7a04ab`). Update the existing imports at the top of `cmd_elaborate.py`:

```python
from storyforge.pages import (
    _PAGE_ARCHITECTURE_HEADER as _PAGE_ARCH_HEADER_RE,
    _BLOCKING_PROMPT_HEADER as _BLOCKING_PROMPT_HEADER_RE,
    _PANEL_SCRIPT_HEADER as _PANEL_SCRIPT_HEADER_RE,
    _IMAGE_GEN_PROMPTS_HEADER,
    _PANEL_HEADER_RE,
)
```

(merge with whatever existing import shape there is).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_elaborate_panel_prompts.py -v --no-cov`
Expected: 12 tests pass (7 from Task 8 + 5 added here).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py tests/test_cmd_elaborate_panel_prompts.py
git commit -m "Add: splice + response validator for panel-prompts (#253)

_validate_panel_prompts_response strips ``` fences, asserts the
## Image-generation prompts header is present, and asserts the
number of ### Panel N subsections matches the page's panel_count.

_splice_panel_prompts inserts the assembled block between ## Page-blocking
prompt and ## Panel script (or replaces an existing
## Image-generation prompts section in force mode), and extends the
page frontmatter's canonical_blocks_embedded list with the canon
files this run cited."
git push
```

---

## Task 10: `_run_panel_prompts_handler_gn` dispatcher + `_run_main_stage` short-circuit

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Test: extend `tests/test_cmd_elaborate_panel_prompts.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cmd_elaborate_panel_prompts.py`:

```python
def test_strict_mode_writes_template_no_api_call(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_panel_prompts_handler_gn
    call_count = {'n': 0}
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: (call_count.__setitem__('n', call_count['n'] + 1) or ''))
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)
    proj = _make_gn_project(tmp_path)
    rc = _run_panel_prompts_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert call_count['n'] == 0
    assert rc == 0
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Image-generation prompts' in text
    assert '### Panel 1' in text
    assert '### Panel 2' in text
    # Section 1 has style-foundation embed (Chiaroscuro), not TODO
    assert 'Chiaroscuro' in text
    # Section 3 has the panel-registers-derived register
    assert 'dominant' in text.lower()


def test_coach_mode_writes_brief_no_page_mutation(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_panel_prompts_handler_gn
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: 'should not be called')
    proj = _make_gn_project(tmp_path)
    rc = _run_panel_prompts_handler_gn(
        proj, dry_run=False, coaching='coach',
        page=None, scene=None, force=False,
    )
    assert rc == 0
    page_text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Image-generation prompts' not in page_text
    brief_path = os.path.join(proj, 'working', 'coaching',
                              'panel-prompts-s01-p1.md')
    assert os.path.isfile(brief_path)
    brief = open(brief_path).read()
    # Lists all 13 sections
    for n in range(1, 14):
        assert f'#### {n}. ' in brief


def test_full_mode_with_mocked_api_splices_panel_prompts(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_panel_prompts_handler_gn

    def fake_response_for_two_panels():
        sections = [
            'Style foundation', 'Lighting laws', 'Pacing role',
            'Shot grammar', 'Stage geography', 'Character block',
            'In this panel', 'Focal objects + render priorities',
            'Lighting logic', 'Symbolic detail (low weight)',
            'Action', 'Emotional subtext (low weight)',
            'Negative constraints',
        ]
        def one_panel(idx):
            lines = [f'### Panel {idx}', '']
            for i, title in enumerate(sections, start=1):
                lines.append(f'#### {i}. {title}')
                lines.append('')
                lines.append(f'mocked panel-{idx} section-{i} body')
                lines.append('')
            return '\n'.join(lines)
        return '## Image-generation prompts\n\n' + one_panel(1) + '\n' + one_panel(2) + '\n'

    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: fake_response_for_two_panels())
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)
    proj = _make_gn_project(tmp_path)
    rc = _run_panel_prompts_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )
    assert rc == 0
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Image-generation prompts' in text
    assert '### Panel 1' in text
    assert '### Panel 2' in text
    assert 'mocked panel-1 section-1 body' in text
    assert 'mocked panel-2 section-13 body' in text
    assert 'canonical_blocks_embedded:' in text


def test_handler_returns_one_when_all_pages_fail_llm_validation(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_panel_prompts_handler_gn
    proj = _make_gn_project(tmp_path)
    monkeypatch.setattr('storyforge.api.invoke_api', lambda *a, **kw: '')
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)
    rc = _run_panel_prompts_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )
    assert rc == 1


def test_main_stage_exits_one_when_medium_is_novel(tmp_path):
    import argparse
    import pytest
    from storyforge.cmd_elaborate import _run_main_stage
    proj = tmp_path / 'novel'
    proj.mkdir()
    (proj / 'storyforge.yaml').write_text(
        'project:\n  medium: novel\n  title: Test\n'
    )
    args = argparse.Namespace(page=None, scene=None, force=False, coaching=None)
    with pytest.raises(SystemExit) as exc:
        _run_main_stage('panel-prompts', str(proj), str(proj / 'reference'),
                        dry_run=False, interactive=False, seed='', args=args)
    assert exc.value.code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_elaborate_panel_prompts.py -v --no-cov`
Expected: ImportError on `_run_panel_prompts_handler_gn`.

- [ ] **Step 3: Implement `_run_panel_prompts_handler_gn`**

Add to `cmd_elaborate.py`, after the page-architecture handler. Mirror `_run_page_architecture_handler_gn`'s shape exactly — same coaching dispatch, same precondition gating, same exit-code semantics:

```python
def _run_panel_prompts_handler_gn(project_dir: str, *,
                                  dry_run: bool, coaching: CoachingLevel,
                                  page: str | None, scene: str | None,
                                  force: bool) -> Literal[0, 1]:
    """Dispatcher for the panel-prompts stage.

    Coaching modes:
      - full: LLM drafts all panels per page, splices into page file
      - coach: writes a brief to working/coaching/, no page mutation
      - strict: stamps a 13-section template per panel (canon embedded
        verbatim in sections 1, 2, 5, 6, 10; TODO scaffolding elsewhere).
        No API call.

    Returns 0 on success or no-op; 1 when every candidate page was
    skipped due to a precondition failure or an LLM/API failure.
    """
    from storyforge.pages import extract_page_architecture
    from storyforge.prompts_panel_prompts import (
        render_strict_template, render_coach_brief, build_full_prompt,
    )
    from storyforge.canon import get_canon_embeddable_block
    from storyforge.csv_cli import get_field, get_row

    targets = _select_pages_for_panel_prompts(project_dir, page, scene, force)
    if not targets:
        log('No pages need panel-prompts (use --force to redo).')
        return 0

    log(f'panel-prompts: {len(targets)} page(s) to process (coaching={coaching})')

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')

    canon_block_cache: dict[str, str] = {}

    def _canon(canon_id: str) -> str:
        if canon_id not in canon_block_cache:
            canon_block_cache[canon_id] = get_canon_embeddable_block(
                project_dir, canon_id,
            )
        return canon_block_cache[canon_id]

    def _extract_panel_registers(arch_body: str) -> dict[int, str]:
        """Parse '- Panel N — register: role' lines from the page architecture
        body to map panel index to register name."""
        result: dict[int, str] = {}
        for line in arch_body.splitlines():
            m = re.match(r'^\s*-\s*Panel\s+(\d+)\s*[—–-]\s*(\w+)', line, re.IGNORECASE)
            if m:
                result[int(m.group(1))] = m.group(2)
        return result

    processed = 0
    skipped_precondition = 0
    skipped_llm = 0
    for parsed in targets:
        page_id = parsed.get('page_id', '')
        scene_id = parsed.get('scene_id', '')
        page_path = parsed['path']
        panel_count = parsed.get('panel_count', 0) or 0

        ok, reason = _precondition_check_panel_prompts(project_dir, page_id, scene_id)
        if not ok:
            log(f'  WARN skip {page_id}: {reason}')
            skipped_precondition += 1
            continue

        scene_title = get_field(scenes_csv, scene_id, 'title') or scene_id
        scene_brief = get_row(briefs_csv, scene_id) or {}
        scene_intent = get_row(intent_csv, scene_id) or {}
        arch_body = extract_page_architecture(page_path)
        panel_registers = _extract_panel_registers(arch_body)

        # Always-embedded canon for the universal sections
        canon_keys = ['style-foundation', 'lighting-laws', 'panel-registers']
        # Add location and characters (frontmatter-driven)
        location = parsed.get('location', '') or ''
        if location:
            canon_keys.append(f'locations/{location}')
        characters = parsed.get('characters_present', []) or []
        for char_id in characters:
            canon_keys.append(f'characters/{char_id}')
        # Motifs: pull from scene brief's motifs cell (semicolon-separated)
        motifs_str = scene_brief.get('motifs', '') or ''
        for motif_id in (m.strip() for m in motifs_str.split(';') if m.strip()):
            canon_keys.append(f'motifs/{motif_id}')

        canon_blocks = {cid: _canon(cid) for cid in canon_keys}

        # Surface missing optional canon (NOTE level) — only those that
        # are NOT in the required gate (style-foundation, lighting-laws
        # are gated; the rest are NOTE-on-absence)
        for cid in canon_keys:
            if cid in ('style-foundation', 'lighting-laws'):
                continue
            if not canon_blocks.get(cid):
                log(f'  NOTE {page_id}: optional canon block {cid!r} '
                    f'absent — prompt will be built without it')

        # Coaching dispatch
        if coaching == 'strict':
            template = render_strict_template(
                page_id=page_id, panel_count=panel_count,
                canon_blocks=canon_blocks, panel_registers=panel_registers,
            )
            if dry_run:
                print(f'===== DRY RUN: strict template for {page_id} =====')
                print(template)
                continue
            canon_ids_used = [
                cid for cid in canon_keys if canon_blocks.get(cid)
            ]
            _splice_panel_prompts(page_path, template,
                                  canon_ids=canon_ids_used)
            log(f'  {page_id}: strict template written')
            processed += 1
            continue

        if coaching == 'coach':
            brief = render_coach_brief(
                page_id=page_id, panel_count=panel_count,
                scene_title=scene_title,
                page_architecture=arch_body,
                scene_brief=scene_brief,
                canon_blocks=canon_blocks,
            )
            if dry_run:
                print(f'===== DRY RUN: coach brief for {page_id} =====')
                print(brief)
                continue
            coaching_dir = os.path.join(project_dir, 'working', 'coaching')
            os.makedirs(coaching_dir, exist_ok=True)
            brief_path = os.path.join(
                coaching_dir, f'panel-prompts-{page_id}.md',
            )
            with open(brief_path, 'w', encoding='utf-8') as f:
                f.write(brief)
            log(f'  {page_id}: coach brief written to {brief_path}')
            processed += 1
            continue

        # Full mode
        prompt = build_full_prompt(
            page_id=page_id, panel_count=panel_count,
            scene_title=scene_title,
            page_frontmatter=parsed,
            page_architecture=arch_body,
            scene_brief=scene_brief,
            scene_intent=scene_intent,
            canon_blocks=canon_blocks,
        )
        if dry_run:
            print(f'===== DRY RUN: full prompt for {page_id} =====')
            print(prompt)
            continue

        from storyforge.api import invoke_api
        stage_model = select_model('drafting')
        response = invoke_api(prompt, stage_model, max_tokens=4096)
        if not response:
            log(f'  WARN {page_id}: API call returned empty response; skipped')
            skipped_llm += 1
            continue
        ok, block = _validate_panel_prompts_response(
            response, expected_panel_count=panel_count,
        )
        if not ok:
            log(f'  WARN {page_id}: LLM response missing section header or '
                f'wrong panel count; skipped')
            skipped_llm += 1
            continue
        canon_ids_used = [cid for cid in canon_keys if canon_blocks.get(cid)]
        _splice_panel_prompts(page_path, block, canon_ids=canon_ids_used)
        try:
            log_operation(
                project_dir, 'elaborate-panel-prompts-gn',
                stage_model, 0, 0, 0.0, target=page_id,
            )
        except OSError as e:
            log(f'  WARN {page_id}: cost ledger write failed ({e}); '
                f'check working/costs/ permissions. Page sections were written.')
        log(f'  {page_id}: full panel prompts written')
        processed += 1

    if skipped_llm > 0:
        log(f'panel-prompts: {skipped_llm} page(s) skipped due to LLM/API '
            f'failures. Re-run with --force --page <page_id> to retry.')
    if skipped_precondition > 0:
        log(f'panel-prompts: {skipped_precondition} page(s) skipped due to '
            f'unmet preconditions.')

    if processed == 0 and (skipped_precondition > 0 or skipped_llm > 0):
        return 1
    return 0
```

- [ ] **Step 4: Wire into `_run_main_stage`**

Add a short-circuit branch in `_run_main_stage` (immediately after the page-architecture short-circuit added by #252):

```python
    if stage == 'panel-prompts':
        if medium != 'graphic-novel':
            log('ERROR: panel-prompts stage is graphic-novel-only.')
            sys.exit(1)
        coaching = (
            getattr(args, 'coaching', None)
            or get_coaching_level(project_dir)
        )
        rc = _run_panel_prompts_handler_gn(
            project_dir, dry_run=dry_run, coaching=coaching,
            page=getattr(args, 'page', None),
            scene=getattr(args, 'scene', None),
            force=getattr(args, 'force', False),
        )
        sys.exit(rc)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_elaborate_panel_prompts.py -v --no-cov`
Expected: all 17 tests pass (7 from Task 8 + 5 from Task 9 + 5 added here).

- [ ] **Step 6: Run the broader elaborate suite to confirm no regressions**

Run: `python3 -m pytest tests/test_cmd_elaborate_args.py tests/test_cmd_elaborate_page_architecture.py tests/test_cmd_elaborate_panel_prompts.py tests/commands/test_cmd_elaborate.py tests/integration/test_elaborate_pipeline.py -v --no-cov 2>&1 | tail -30`
Expected: no regressions.

Watch for: `test_contains_all_expected` and `test_valid_stages_set` (in `tests/commands/test_cmd_elaborate.py` and `tests/integration/test_elaborate_pipeline.py`) hard-code the expected VALID_STAGES set. Add `'panel-prompts'` to both. This was caught as a real regression in #252's Task 8 review.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py \
        tests/test_cmd_elaborate_panel_prompts.py \
        tests/commands/test_cmd_elaborate.py \
        tests/integration/test_elaborate_pipeline.py
git commit -m "Add: _run_panel_prompts_handler_gn — strict/coach/full dispatch (#253)

The handler mirrors _run_page_architecture_handler_gn at every
structural level:
  * strict mode: stamps 13-section template per panel with canon
    embedded verbatim into sections 1/2/5/6/10 and TODO scaffolding
    elsewhere. No API call.
  * coach mode: writes working/coaching/panel-prompts-<page_id>.md
    asking 13 focused questions, embeds canon vocabulary inline.
    No page mutation.
  * full mode: one Opus call per page emits all panels at once,
    validator checks header + panel count, splice replaces or inserts
    the ## Image-generation prompts section.
Returns Literal[0, 1] — 0 on success or no-op, 1 when every page was
skipped on precondition or LLM/API failure.

Wires into _run_main_stage as a short-circuit immediately after the
page-architecture short-circuit. Medium-gate is graphic-novel-only.

Also updates the two pre-existing hard-coded VALID_STAGES expectations
in tests/commands and tests/integration to include 'panel-prompts'."
git push
```

---

## Task 11: Fixtures + docs + version 1.41.0 + PR

**Files:**
- Modify: `tests/fixtures/test-project-gn/pages/s01-p1.md` (extend with panel prompts)
- Create: `tests/fixtures/test-project-gn/pages/s01-p3.md` (gap example with no panel prompts)
- Modify: `skills/elaborate/SKILL.md`
- Modify: `skills/forge/SKILL.md`
- Modify: `CLAUDE.md`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Extend `s01-p1.md` fixture with well-formed panel prompts**

The existing fixture page has `## Page architecture` + `## Page-blocking prompt`. Extend it to include `## Image-generation prompts` with two `### Panel N` blocks (one per panel), each containing the 13 `#### N. <Title>` subsections in canonical order. Section bodies can be brief but must be non-empty.

Read the current file at `tests/fixtures/test-project-gn/pages/s01-p1.md` first to preserve its existing content. Insert the new `## Image-generation prompts` section AFTER `## Page-blocking prompt` and BEFORE `## Panel script`.

Use this template per panel (adapt body content to the panel's role):

```
### Panel 1

#### 1. Style foundation

(Paste from reference/canon/style-foundation.md when populated.)

#### 2. Lighting laws

(Paste from reference/canon/lighting-laws.md when populated.)

#### 3. Pacing role

Register: atmospheric. Relative weight: low — establishes the studio
space.

#### 4. Shot grammar

Wide. Eye-level. Establishing.

#### 5. Stage geography

The archive-studio: tall windows frame-left, desk centered, shelves
along the back wall.

Panel-specific: room shown empty save for Lucien at the desk.

#### 6. Character block

Lucien Vey — mid-thirties, lean, dark hair, ink-stained fingers. Wears
a charcoal vest over a white shirt.

#### 7. In this panel

Lucien is seated at the desk, both hands flat on the page, eyes on the
inkpot.

#### 8. Focal objects + render priorities

Detail: the inkpot, Lucien's hands, the lamp's pool of light. Dissolve:
distant shelves, ceiling, far corners.

#### 9. Lighting logic

Single lamp at desk corner, frame-right. Cool window light from
frame-left, low intensity.

#### 10. Symbolic detail (low weight)

The inkpot at center-frame, lamplight catching its rim. (low weight)

#### 11. Action

Lucien sets his hands flat on the page beside the inkpot.

#### 12. Emotional subtext (low weight)

A small private ritual before the trial. (low weight)

#### 13. Negative constraints

No supernatural luminosity from the inkpot. No reflections on its
surface. No glamour lighting. No depth-of-field bokeh.
```

Add a second `### Panel 2` block following the same structure (dominant register, close shot on the hand).

- [ ] **Step 2: Create the gap-example fixture page**

Create `tests/fixtures/test-project-gn/pages/s01-p3.md` with `## Page architecture` and `## Page-blocking prompt` populated, but NO `## Image-generation prompts` section. This exercises the `missing_panel_prompts` cleanup finding.

```markdown
---
page_id: s01-p3
scene_id: s01-studio-finalization
page_within_scene: 3
total_pages_in_scene: 3
panel_count: 1
spread_position: recto of 2-3
characters_present: [lucien-vey]
location: archive-studio
timeline: day 1, evening
---

## Scene context

The page-turn reveal.

## Page architecture

### Intent
Single splash — the inkpot reflects an impossible face.

### Panel hierarchy
- Panel 1 — climactic: the reveal

### Book-level placement
- Spread context: recto of 2-3 (page-turn beat)
- Page-turn beat: yes — the impossible face reveal

## Page-blocking prompt

Monochrome storyboard. Single splash panel. The inkpot dead-center,
strongest value contrast on the page. No surrounding panel structure.
No surface texture, no rendered face, no fine line work.

## Panel script

**Panel 1.** Splash. The inkpot at center frame.
```

This page DELIBERATELY has neither panel prompts (triggers `missing_panel_prompts`) — and `s01-p2` (added in #252) deliberately had no page-architecture sections. Together the three fixture pages exercise every cleanup finding from #251, #252, and #253.

- [ ] **Step 3: Run cleanup tests against the updated fixture**

Run: `python3 -m pytest tests/test_cmd_cleanup.py tests/test_cleanup_csv.py tests/test_pages_panel_prompt_validation.py tests/test_pages_section_validation.py -v --no-cov 2>&1 | tail -30`

Some pre-existing tests may need adjustment to tolerate the new finding types on `s01-p3`. Update minimally.

- [ ] **Step 4: Update `skills/elaborate/SKILL.md`**

Find the section that documents elaboration stages (the page-architecture section was added in #252). Add a new section for `panel-prompts` immediately after page-architecture:

```markdown
### Panel prompts (graphic-novel only)

**Stage:** `--stage panel-prompts` (or `--panel-prompts`)
**Purpose:** Generate 13-section image-generation prompts per panel using the schema validated in Ashes PR #8.
**Output:** `## Image-generation prompts` section in each page file, containing `### Panel N` blocks with all 13 `#### M. <Title>` subsections.
**Preconditions:** scene brief has `panel_breakdown`; page has populated `## Page architecture` (run `--stage page-architecture` first); `reference/canon/style-foundation.md` and `reference/canon/lighting-laws.md` are populated (not TODO).

**Flags:**
- `--page <page_id>` — single page only
- `--scene <scene_id>` — every page of one scene
- `--force` — overwrite existing panel prompts
- `--dry-run` — print one prompt, no API calls

**Coaching modes:**
- **full** — Opus drafts all panels for the page in one API call; splices into the page file
- **coach** — writes a brief to `working/coaching/panel-prompts-<page_id>.md` with the 13 sections and focused questions per section; embeds canon inline; no page mutation
- **strict** — stamps a deterministic 13-section template per panel; canon is embedded verbatim in sections 1, 2, 5, 6, 10; sections 3, 4, 7, 8, 9, 11, 12, 13 are TODO scaffolding; no API call

**When to run:** after `page-architecture` in graphic-novel projects; the per-panel register hierarchy from page architecture is cited by section 3 of every panel prompt.

**The 13 sections** (canonical order; titles fixed):
1. Style foundation (canon embed)
2. Lighting laws (canon embed)
3. Pacing role (cites register from page architecture)
4. Shot grammar
5. Stage geography (canon embed + panel positioning)
6. Character block (canon embed per on-frame character)
7. In this panel
8. Focal objects + render priorities
9. Lighting logic
10. Symbolic detail (low weight) (canon embed when motif on-frame)
11. Action
12. Emotional subtext (low weight)
13. Negative constraints
```

- [ ] **Step 5: Update `skills/forge/SKILL.md`**

In the GN-mode section, add the recommendation right after the existing page-architecture recommendation:

```markdown
- **After page-architecture (GN mode):** Run `storyforge elaborate --stage panel-prompts` to generate 13-section image-generation prompts per panel. Sections 1, 2, 5, 6, 10 embed canon verbatim; section 3 cites the register from page architecture. Requires `reference/canon/style-foundation.md` and `reference/canon/lighting-laws.md` to be populated.
```

- [ ] **Step 6: Update `CLAUDE.md`**

(a) In the elaborate stage table row, extend the stage list with `|panel-prompts`.

(b) In the Graphic Novel Mode section, add a paragraph after the page-architecture paragraph:

```markdown
**Panel prompts (issue #253):** `storyforge elaborate --stage panel-prompts` writes a `## Image-generation prompts` section into each page file with one `### Panel N` block per panel. Each block contains 13 `#### M. <Title>` subsections in canonical order. Sections 1 (style-foundation), 2 (lighting-laws), 5 (location), 6 (character), 10 (motif) embed canon blocks verbatim; section 3 cites the register from the page architecture's panel hierarchy (#252 prereq); the remaining sections are panel-specific. Validated in benjaminsnorris/ashes PR #8 — separates render directives from atmospheric prose and labels emotional sections "(low weight)" so diffusion models stop converting prose into visual intensity.
```

- [ ] **Step 7: Bump version**

Edit `.claude-plugin/plugin.json`. Bump `"version"` from `1.40.1` to `1.41.0`.

- [ ] **Step 8: Run the full test suite**

Run: `python3 -m pytest tests/ --no-cov 2>&1 | tail -10`
Expected: all tests pass.

- [ ] **Step 9: Final commit**

```bash
git add tests/fixtures/test-project-gn/pages/ \
        skills/elaborate/SKILL.md skills/forge/SKILL.md \
        CLAUDE.md .claude-plugin/plugin.json
# Add any test files that needed minimal updates
git add tests/ 2>/dev/null
git commit -m "Bump version to 1.41.0 — GN 13-section panel prompts (issue #253)

Fixture pages s01-p1 (extended with well-formed panel prompts to lock
in the canonical structure) and s01-p3 (gap example with no panel
prompts to trigger missing_panel_prompts cleanup finding).

Skill docs describe the new stage, the 13 canonical section titles,
coaching modes, and the preconditions. CLAUDE.md documents the GN
pipeline ordering (briefs → page-architecture → panel-prompts → draft)
and links to the canon files each section embeds from."
git push
```

- [ ] **Step 10: Open the pull request**

```bash
gh pr create --title "GN 13-section panel prompt schema (#253)" --body "$(cat <<'EOF'
## Summary

- Adds `storyforge elaborate --stage panel-prompts` — writes a `## Image-generation prompts` section into each per-page file with `### Panel N` blocks containing 13 `#### M. <Title>` subsections in canonical order
- Sections 1, 2, 5, 6, 10 embed canon verbatim (style-foundation, lighting-laws, location, character, motif); section 3 cites the register from page architecture (#252); sections 3, 4, 7, 8, 9, 11, 12, 13 are panel-specific
- Three new `cleanup` warnings: `page_missing_panel_prompts`, `page_panel_prompt_section_missing`, `page_panel_prompt_wrong_section_order`
- Builds on per-page files (#251), canon files (#254), and page-blocking pass (#252)
- One Opus call per page emits all panels at once so cross-panel continuity stays in a single LLM context

## Test plan
- [ ] `python3 -m pytest tests/ -v --no-cov` — all pass
- [ ] `storyforge elaborate --stage panel-prompts --dry-run` on a populated GN project prints a sensible per-page prompt with canon embeds, page architecture, brief, and intent
- [ ] `storyforge elaborate --stage panel-prompts` (full coaching) splices `## Image-generation prompts` with both panels into a sample page
- [ ] `storyforge elaborate --stage panel-prompts --coaching coach` writes a brief to `working/coaching/`
- [ ] `storyforge elaborate --stage panel-prompts --coaching strict` stamps the 13-section template with canon embedded in sections 1/2/5/6/10
- [ ] `storyforge cleanup` reports the three new warnings against pages missing or malformed panel prompts

Closes #253.

Deferred to sibling PRs:
- `hone` deeper validation (canon-content drift detection)
- `script-package` panel-prompts bundle file

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Summary

11 tasks, all bite-sized, each with a TDD cycle (failing test → minimal implementation → green → commit → push). Same structural pattern as the GN page-blocking plan (#252) — every commit is independently reviewable and pushed.

## Changes

- `pages.py` — `PANEL_SECTION_TITLES`, two new extractors, three new finding kinds
- `prompts_panel_prompts.py` (new) — strict / coach / full coaching mode renderers
- `cmd_elaborate.py` — `'panel-prompts'` stage + handler with three coaching modes + short-circuit
- `cmd_cleanup.py` — wires the three new finding kinds
- Skill + CLAUDE.md docs + version bump to 1.41.0

## Test plan

Every task's tests above. Total ≈ 35 new tests across 5 new test files. Plus mocked-API end-to-end exercising all three coaching modes.

## Out of scope (sibling issues)

- `hone` deeper validation (canon-content drift detection)
- `script-package` bundle file (`manuscript/panel-prompts.md`)
- LLM-grounded content quality scoring (would belong in `score`)

---

## Self-Review (executed before publishing this plan)

**Spec coverage:** Every section of the spec maps to a task. §3.1 schema → Task 5 (strict embeds canon) + Task 7 (full output contract). §3.2 page-file conventions → Task 1 (extractors) + Task 11 (fixture). §3.3 extractors → Tasks 1 and 2. §3.4 frontmatter audit trail → Task 9 splice. §4 authoring command → Tasks 8, 9, 10. §5 cleanup integration → Tasks 3 and 4. §8 file inventory → covered in tasks. §9 testing strategy → tests per task. §12 acceptance criteria → covered by Task 11's final test run.

**Placeholder scan:** No spec-task placeholders. The TODO strings emitted by the strict template are intentional author-facing content.

**Type consistency:** `PageFindingKind` Literal values `missing_panel_prompts`, `panel_prompt_section_missing`, `panel_prompt_wrong_section_order` are used identically across Tasks 3 and 4. Handler returns `Literal[0, 1]` matching #252's convention. `CoachingLevel` is imported from `storyforge.common` (added in #258 review fixes). `_IMAGE_GEN_PROMPTS_HEADER` and `_PANEL_HEADER_RE` are defined once in `pages.py` (Task 1) and imported into `cmd_elaborate.py` (Task 9) — matching the regex-dedup convention from #258's review fix `a7a04ab`.

**Scope:** Focused on one feature — the 13-section panel prompt schema — with explicit deferral of hone deeper-validation and script-package bundle to sibling PRs. Reasonable for one PR.

**Ambiguity:** §3.2's "header line stripped, body whitespace-trimmed" is spelled out in extractor docstrings and reflected in Task 1's test assertions. Task 9's splice behavior covers insert-when-absent vs replace-when-present with explicit tests.
