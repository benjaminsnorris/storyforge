# GN Page-Blocking Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `page-architecture` elaboration stage that writes two new body sections (`## Page architecture` and `## Page-blocking prompt`) into each per-page file for graphic-novel projects, plus a `manuscript/page-blocking-prompts.md` artifact in the artist handoff bundle. Locks page-level rhythm and panel geometry before any per-panel image rendering (issue #252).

**Architecture:** A new stage `page-architecture` is added to `cmd_elaborate.py`'s `VALID_STAGES` and routes to a GN-only handler `_page_architecture_handler_gn` that iterates page files (in parallel), checks preconditions (scene-brief populated, canon vocabulary defined), and either drafts both sections with an LLM (full mode), produces a coaching brief at `working/coaching/page-architecture-<page_id>.md` (coach mode), or stamps a TODO-template directly into the page file (strict mode). `pages.py` gains two new extractors and two new validation finding kinds; `cmd_cleanup.py` surfaces those as warnings; `cmd_script_package.py` concatenates the blocking prompts into a new bundle file.

**Tech Stack:** Python 3.10+, pytest, pipe-delimited CSVs, naive YAML-subset parser (no PyYAML), existing `storyforge.api` + `storyforge.canon` + `storyforge.pages` modules.

**Branch:** `storyforge/gn-page-blocking-252` (already created).

---

## File Structure

**Create:**
- `scripts/lib/python/storyforge/prompts_page_architecture.py` — full-mode LLM prompt builder + coach-mode brief renderer + strict-mode template renderer (all three live together so the three coaching modes can share helpers like the canon-block loader and the neighbor-page formatter)
- `tests/test_pages_extractors.py` — unit tests for the two new section extractors
- `tests/test_pages_section_validation.py` — unit tests for the two new finding kinds
- `tests/test_prompts_page_architecture.py` — unit tests for strict / coach / full prompt builders
- `tests/test_cmd_elaborate_page_architecture.py` — stage end-to-end (mocked API) tests
- `tests/test_cmd_script_package_blocking.py` — script-package's new bundle file tests
- `tests/fixtures/test-project-gn/pages/s01-p1.md` — fixture page with both new sections populated
- `tests/fixtures/test-project-gn/pages/s01-p2.md` — fixture page with both new sections absent

**Modify:**
- `scripts/lib/python/storyforge/pages.py` — add `extract_page_architecture()`, `extract_blocking_prompt()`; extend `PageFindingKind` Literal with `missing_page_architecture` and `missing_blocking_prompt`; extend `validate_page_file` to detect both
- `scripts/lib/python/storyforge/canon.py` — add public `is_canon_block_populated(project_dir, canon_id) -> bool` wrapping the existing private helpers
- `scripts/lib/python/storyforge/cmd_cleanup.py` — handle the two new finding kinds in `_check_page_files`
- `scripts/lib/python/storyforge/cmd_elaborate.py` — add `'page-architecture'` to `VALID_STAGES`; add `--page`, `--scene`, `--force` flags; add `_page_architecture_handler_gn` per-page dispatcher; wire it into `_run_main_stage`
- `scripts/lib/python/storyforge/cmd_script_package.py` — assemble `manuscript/page-blocking-prompts.md`; extend `HANDOFF_README` template with the generation-order paragraph (conditional)
- `skills/elaborate/SKILL.md` — document the new stage, preconditions, coaching behavior
- `skills/forge/SKILL.md` — recommend `page-architecture` after briefs in GN mode
- `CLAUDE.md` — add `page-architecture` to the elaborate stage table; note the new bundle file in the GN section
- `.claude-plugin/plugin.json` — bump to **1.40.0**

---

## Task 1: Section extractors in `pages.py`

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages_extractors.py`

- [ ] **Step 1: Write failing tests for extract_page_architecture and extract_blocking_prompt**

Create `tests/test_pages_extractors.py`:

```python
"""Tests for pages.extract_page_architecture and pages.extract_blocking_prompt."""

import textwrap


def _write_page(tmp_path, body):
    """Write a minimal valid page file with the given body content."""
    text = textwrap.dedent(f"""\
        ---
        page_id: s01-p1
        scene_id: s01-studio
        page_within_scene: 1
        total_pages_in_scene: 1
        panel_count: 2
        ---

        {body}
        """)
    path = tmp_path / 's01-p1.md'
    path.write_text(text)
    return str(path)


def test_extract_page_architecture_basic(tmp_path):
    from storyforge.pages import extract_page_architecture
    body = textwrap.dedent("""\
        ## Scene context

        Some context.

        ## Page architecture

        ### Intent
        Open the scene with quiet tension.

        ### Panel hierarchy
        - Panel 1 — atmospheric: establishing
        - Panel 2 — dominant: the inkpot

        ### Book-level placement
        - Spread context: opening recto
        - Page-turn beat: no

        ## Page-blocking prompt

        Monochrome storyboard.

        ## Panel script

        **Panel 1.** Wide.
        """)
    result = extract_page_architecture(_write_page(tmp_path, body))
    assert '### Intent' in result
    assert 'Panel 1 — atmospheric' in result
    assert '### Book-level placement' in result
    assert 'Monochrome storyboard' not in result  # belongs to next section
    assert 'Panel 1.** Wide' not in result


def test_extract_blocking_prompt_basic(tmp_path):
    from storyforge.pages import extract_blocking_prompt
    body = textwrap.dedent("""\
        ## Page architecture

        Intent stuff.

        ## Page-blocking prompt

        Monochrome storyboard. Two panels.
        Top: wide establishing — atmospheric register.
        Bottom: dominant — the inkpot.

        ## Panel script

        **Panel 1.** Wide.
        """)
    result = extract_blocking_prompt(_write_page(tmp_path, body))
    assert 'Monochrome storyboard' in result
    assert 'atmospheric register' in result
    assert 'Intent stuff' not in result
    assert 'Panel 1.** Wide' not in result


def test_extract_page_architecture_missing_section(tmp_path):
    from storyforge.pages import extract_page_architecture
    body = '## Scene context\n\nNo architecture.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    assert extract_page_architecture(_write_page(tmp_path, body)) == ''


def test_extract_blocking_prompt_missing_section(tmp_path):
    from storyforge.pages import extract_blocking_prompt
    body = '## Page architecture\n\nIntent.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    assert extract_blocking_prompt(_write_page(tmp_path, body)) == ''


def test_extract_handles_page_n_em_dash_subheader(tmp_path):
    """The `## Page N — LAYOUT` headers used in panel scripts must NOT be
    treated as section terminators when they appear AFTER our target
    sections — but the lookahead in pages.py only kicks in for terminators
    that follow the target section, so the panel-script `## Page N —`
    headers can't accidentally extend the page-architecture extraction.
    Sanity-check that em-dash content inside the page-architecture body
    parses correctly when no `##` follows."""
    from storyforge.pages import extract_page_architecture
    body = '## Page architecture\n\n### Intent\nLine — with em-dash.\n'
    result = extract_page_architecture(_write_page(tmp_path, body))
    assert 'Line — with em-dash.' in result


def test_extract_missing_file_returns_empty(tmp_path):
    from storyforge.pages import extract_page_architecture, extract_blocking_prompt
    assert extract_page_architecture(str(tmp_path / 'nope.md')) == ''
    assert extract_blocking_prompt(str(tmp_path / 'nope.md')) == ''


def test_extract_no_frontmatter_returns_empty(tmp_path):
    from storyforge.pages import extract_page_architecture, extract_blocking_prompt
    path = tmp_path / 'no-fm.md'
    path.write_text('## Page architecture\n\nBody.\n')
    assert extract_page_architecture(str(path)) == ''
    assert extract_blocking_prompt(str(path)) == ''
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pages_extractors.py -v`
Expected: ImportError on `extract_page_architecture` / `extract_blocking_prompt`.

- [ ] **Step 3: Implement extractors in pages.py**

Append to `scripts/lib/python/storyforge/pages.py` (after `extract_panel_script`):

```python
_PAGE_ARCHITECTURE_HEADER = re.compile(
    r'^##\s+Page\s+architecture\s*$', re.MULTILINE | re.IGNORECASE,
)

_BLOCKING_PROMPT_HEADER = re.compile(
    r'^##\s+Page[- ]blocking\s+prompt\s*$', re.MULTILINE | re.IGNORECASE,
)


def _extract_section(path: str, header_re: re.Pattern) -> str:
    """Shared implementation for body-section extractors.

    Returns the body of the section (header stripped) up to the next
    page-file section heading (`## ...`, but not `## Page N — …` page
    headers, which are part of the panel-script body). Returns '' when
    the page file is missing, has no frontmatter, or lacks the section.
    """
    page = parse_page_file(path)
    if page is None:
        return ''
    body = page.get('body', '')
    m = header_re.search(body)
    if not m:
        return ''
    start = m.end()
    rest = body[start:]
    next_m = _NEXT_SECTION_HEADER.search(rest)
    end = next_m.start() if next_m else len(rest)
    return rest[:end].strip('\n')


def extract_page_architecture(path: str) -> str:
    """Return the contents of the '## Page architecture' section, or ''."""
    return _extract_section(path, _PAGE_ARCHITECTURE_HEADER)


def extract_blocking_prompt(path: str) -> str:
    """Return the contents of the '## Page-blocking prompt' section, or ''.

    The header regex accepts both 'Page-blocking prompt' (preferred) and
    'Page blocking prompt' (space variant) so authors who type the
    non-hyphenated form get the same extraction behavior.
    """
    return _extract_section(path, _BLOCKING_PROMPT_HEADER)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pages_extractors.py -v`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages_extractors.py
git commit -m "Add: page-architecture and blocking-prompt section extractors (#252)

Two new extractors on pages.py mirror extract_panel_script for the new
body sections introduced by the page-blocking pass. Both reuse the
shared _NEXT_SECTION_HEADER lookahead that treats '## Page N — …' page
headers as panel-script content rather than section terminators."
git push
```

---

## Task 2: New finding kinds + body validation in `pages.py`

**Files:**
- Modify: `scripts/lib/python/storyforge/pages.py`
- Test: `tests/test_pages_section_validation.py`

- [ ] **Step 1: Write failing tests for the new finding kinds**

Create `tests/test_pages_section_validation.py`:

```python
"""Tests for the missing_page_architecture and missing_blocking_prompt
PageFindingKind values added by issue #252."""

import textwrap


def _write_page(tmp_path, body):
    text = textwrap.dedent(f"""\
        ---
        page_id: s01-p1
        scene_id: s01-studio
        page_within_scene: 1
        total_pages_in_scene: 1
        panel_count: 2
        ---

        {body}
        """)
    path = tmp_path / 's01-p1.md'
    path.write_text(text)
    return str(path)


def _kinds(findings):
    return {f['kind'] for f in findings}


def test_both_findings_when_sections_absent(tmp_path):
    from storyforge.pages import validate_page_file
    body = '## Scene context\n\nContext.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' in kinds
    assert 'missing_blocking_prompt' in kinds


def test_neither_finding_when_sections_populated(tmp_path):
    from storyforge.pages import validate_page_file
    body = textwrap.dedent("""\
        ## Page architecture

        ### Intent
        Quiet tension.

        ## Page-blocking prompt

        Monochrome storyboard.

        ## Panel script

        **Panel 1.** Wide.
        """)
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' not in kinds
    assert 'missing_blocking_prompt' not in kinds


def test_finding_fires_when_header_present_but_body_empty(tmp_path):
    """Author deleted the body but left the header — half-edited state."""
    from storyforge.pages import validate_page_file
    body = '## Page architecture\n\n   \n\n## Page-blocking prompt\n\n\n\n## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' in kinds
    assert 'missing_blocking_prompt' in kinds


def test_finding_does_not_fire_for_strict_mode_TODO_body(tmp_path):
    """Strict mode populates the sections with TODO scaffolding; that
    is non-empty content and must NOT fire the finding."""
    from storyforge.pages import validate_page_file
    body = textwrap.dedent("""\
        ## Page architecture

        ### Intent
        TODO — narrative purpose.

        ## Page-blocking prompt

        TODO — monochrome storyboard.

        ## Panel script

        **Panel 1.** Wide.
        """)
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' not in kinds
    assert 'missing_blocking_prompt' not in kinds


def test_only_one_finding_when_one_section_present_one_missing(tmp_path):
    from storyforge.pages import validate_page_file
    body = '## Page architecture\n\nIntent.\n\n## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' not in kinds
    assert 'missing_blocking_prompt' in kinds


def test_finding_kinds_are_in_literal_type():
    """The PageFindingKind Literal must list both new values so a kind
    typo elsewhere is caught statically. We can't introspect the Literal
    at runtime portably, but we can confirm the strings are accepted by
    a function that takes a PageFindingKind and exercises both branches."""
    from storyforge.pages import PageFindingKind  # noqa: F401
    # Existence of the import is the assertion; type-check happens at
    # mypy / pyright time, not runtime.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pages_section_validation.py -v`
Expected: AssertionError on first test — `missing_page_architecture` not in kinds.

- [ ] **Step 3: Extend PageFindingKind and validate_page_file**

In `scripts/lib/python/storyforge/pages.py`, update the Literal:

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
]
```

Append the body-section checks to `validate_page_file`, after the existing `page_within_scene_out_of_range` block and BEFORE the `return findings` line:

```python
    # Body-section checks (issue #252). Use the extractors so the
    # "header present but body empty" half-edited state fires the same
    # finding as a fully-missing section — both signal a gap the
    # author should fill via `elaborate --stage page-architecture`.
    if not extract_page_architecture(path).strip():
        findings.append({
            'kind': 'missing_page_architecture', 'path': path,
            'detail': '"## Page architecture" section is missing or empty',
        })
    if not extract_blocking_prompt(path).strip():
        findings.append({
            'kind': 'missing_blocking_prompt', 'path': path,
            'detail': '"## Page-blocking prompt" section is missing or empty',
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pages_section_validation.py tests/test_pages_extractors.py -v`
Expected: All pass (6 new tests in this file, plus the 7 from Task 1).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/pages.py tests/test_pages_section_validation.py
git commit -m "Add: missing_page_architecture and missing_blocking_prompt findings (#252)

PageFindingKind Literal grows two values for the new body sections
introduced by the page-blocking pass. validate_page_file emits each
finding when the section header is absent OR present-with-empty-body
(the half-edited state). Strict-mode TODO scaffolding counts as
non-empty content and does NOT fire either finding — by design."
git push
```

---

## Task 3: cleanup integration for the two new findings

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_cleanup.py`
- Test: extend `tests/test_pages_section_validation.py` (cleanup-level integration)

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_pages_section_validation.py`:

```python
def test_cleanup_check_page_files_surfaces_new_findings(tmp_path, monkeypatch):
    """End-to-end through cmd_cleanup._check_page_files."""
    import os
    import shutil
    # Set up a minimal GN-mode project
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
        '## Scene context\n\nContext only — no architecture, no blocking.\n'
    )
    from storyforge.cmd_cleanup import _check_page_files
    findings = _check_page_files(str(project))
    types = {f['type'] for f in findings}
    assert 'page_missing_page_architecture' in types
    assert 'page_missing_blocking_prompt' in types
    # Both are warnings (cleanup remains exit-0 over these)
    for f in findings:
        if f['type'] in ('page_missing_page_architecture',
                         'page_missing_blocking_prompt'):
            assert f['severity'] == 'warning'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_pages_section_validation.py::test_cleanup_check_page_files_surfaces_new_findings -v`
Expected: AssertionError — `page_missing_page_architecture` not in types (cleanup hits the `else` branch and emits `page_unknown_finding`).

- [ ] **Step 3: Add branches in `_check_page_files`**

In `scripts/lib/python/storyforge/cmd_cleanup.py`, inside the `for issue in validate_page_file(page_path):` loop in `_check_page_files`, add two new `elif` branches BEFORE the catch-all `else`:

```python
            elif kind == 'missing_page_architecture':
                findings.append({
                    'type': 'page_missing_page_architecture', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Run `storyforge elaborate --stage '
                              'page-architecture --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}` '
                              'to populate (or write the section by hand)',
                    'severity': 'warning',
                })
            elif kind == 'missing_blocking_prompt':
                findings.append({
                    'type': 'page_missing_blocking_prompt', 'file': rel_path,
                    'detail': issue['detail'],
                    'action': 'Run `storyforge elaborate --stage '
                              'page-architecture --page '
                              f'{os.path.splitext(os.path.basename(page_path))[0]}` '
                              'to populate (or write the section by hand)',
                    'severity': 'warning',
                })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_pages_section_validation.py -v`
Expected: All pass.

- [ ] **Step 5: Run the existing cleanup test suite to check nothing regressed**

Run: `python3 -m pytest tests/test_cmd_cleanup.py -v`
Expected: All pre-existing cleanup tests still pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_cleanup.py tests/test_pages_section_validation.py
git commit -m "Wire: page_missing_page_architecture and _blocking_prompt findings in cleanup (#252)

cmd_cleanup._check_page_files handles the two new PageFindingKind values
introduced in the previous commit. Both surface as warnings (cleanup
exit code unaffected) and the action message points the author at the
exact command to populate the missing section."
git push
```

---

## Task 4: `is_canon_block_populated` public helper

**Files:**
- Modify: `scripts/lib/python/storyforge/canon.py`
- Test: `tests/test_canon_is_block_populated.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_canon_is_block_populated.py`:

```python
"""Tests for canon.is_canon_block_populated — the precondition helper
used by elaborate --stage page-architecture."""

import textwrap


def _write_canon(project_dir, canon_id, body):
    import os
    canon_dir = os.path.join(str(project_dir), 'reference', 'canon')
    os.makedirs(canon_dir, exist_ok=True)
    path = os.path.join(canon_dir, f'{canon_id}.md')
    with open(path, 'w') as f:
        f.write(body)
    return path


def test_populated_block_returns_true(tmp_path):
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Embeddable block

        Dominant panel: the page's emotional fulcrum.
        Transitional panel: a rhythmic beat between dominants.
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is True


def test_unpopulated_block_returns_false(tmp_path):
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Embeddable block

        TODO — fill in the panel-register vocabulary.
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is False


def test_missing_canon_file_returns_false(tmp_path):
    from storyforge.canon import is_canon_block_populated
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is False


def test_missing_embeddable_block_returns_false(tmp_path):
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Clauses

        - dominant
        - transitional
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_canon_is_block_populated.py -v`
Expected: ImportError on `is_canon_block_populated`.

- [ ] **Step 3: Add public helper to canon.py**

Append to `scripts/lib/python/storyforge/canon.py`:

```python
def is_canon_block_populated(project_dir: str, canon_id: str) -> bool:
    """Return True if reference/canon/<canon_id>.md exists, has an
    "## Embeddable block" section, and that section's body is NOT
    placeholder TODO text.

    Used by elaborate --stage page-architecture as a precondition:
    if the canon vocabulary the prompt depends on (panel-registers,
    page-rhythm-rules) is still TODO, the LLM can't reliably cite
    the registers, so the stage refuses to run.
    """
    import os
    path = os.path.join(project_dir, 'reference', 'canon', f'{canon_id}.md')
    if not os.path.isfile(path):
        return False
    block_text = _embeddable_block_text(path)
    if block_text is None:
        return False
    return not _section_body_is_placeholder(block_text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_canon_is_block_populated.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/canon.py tests/test_canon_is_block_populated.py
git commit -m "Add: is_canon_block_populated public helper to canon module (#252)

Public wrapper around the existing _embeddable_block_text and
_section_body_is_placeholder helpers. Used by elaborate --stage
page-architecture as a precondition check: the stage refuses to run
when its canon vocabulary inputs (panel-registers, page-rhythm-rules)
are still TODO placeholders."
git push
```

---

## Task 5: Strict-mode template renderer

**Files:**
- Create: `scripts/lib/python/storyforge/prompts_page_architecture.py`
- Test: `tests/test_prompts_page_architecture.py`

- [ ] **Step 1: Write failing tests for the strict template renderer**

Create `tests/test_prompts_page_architecture.py`:

```python
"""Tests for prompts_page_architecture — strict / coach / full builders
used by elaborate --stage page-architecture."""

import textwrap


def test_strict_template_renders_panel_hierarchy_for_each_panel():
    from storyforge.prompts_page_architecture import render_strict_template
    out = render_strict_template(page_id='s01-p1', panel_count=3)
    # Both new sections present
    assert '## Page architecture' in out
    assert '## Page-blocking prompt' in out
    # Panel hierarchy enumerates each panel (panel_count=3 → 3 bullets)
    assert out.count('TODO register: TODO role') == 3
    # Required intent / placement / blocking constraints documented
    assert '### Intent' in out
    assert '### Book-level placement' in out
    assert 'panel-registers.md' in out
    assert 'monochrome' in out.lower()


def test_strict_template_panel_count_one():
    from storyforge.prompts_page_architecture import render_strict_template
    out = render_strict_template(page_id='s01-p1', panel_count=1)
    assert out.count('TODO register: TODO role') == 1


def test_strict_template_panel_count_zero_falls_back_to_one_placeholder():
    """Edge case: page file has panel_count=0 (unknown). Render at least
    one placeholder so the author has something to fill in."""
    from storyforge.prompts_page_architecture import render_strict_template
    out = render_strict_template(page_id='s01-p1', panel_count=0)
    assert out.count('TODO register: TODO role') >= 1


def test_strict_template_is_deterministic():
    """Same inputs → same output (no timestamps, no random IDs)."""
    from storyforge.prompts_page_architecture import render_strict_template
    a = render_strict_template(page_id='s01-p1', panel_count=2)
    b = render_strict_template(page_id='s01-p1', panel_count=2)
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompts_page_architecture.py -v`
Expected: ModuleNotFoundError on `storyforge.prompts_page_architecture`.

- [ ] **Step 3: Implement the strict renderer**

Create `scripts/lib/python/storyforge/prompts_page_architecture.py`:

```python
"""Page-architecture stage prompt builders.

Three coaching modes share this module so they can reuse helpers
(panel-hierarchy formatting, neighbor-page rendering, canon-block
loaders). render_strict_template emits a TODO scaffold with no LLM
call. render_coach_brief writes a question-driven brief for the
author. build_full_prompt assembles the full LLM prompt with canon
embeds + scene brief + neighbor pages.
"""


_STRICT_TEMPLATE_HEADER = """\
## Page architecture

### Intent
TODO — narrative purpose, emotional arc, visual rhythm, dominant motif.

### Panel hierarchy
"""

_STRICT_TEMPLATE_TAIL = """\

### Book-level placement
- Spread context: TODO (verso of N–N+1 | recto of N–1–N | opening recto | closing verso)
- Page-turn beat: TODO (yes/no — what reveals on the turn)

## Page-blocking prompt

TODO — monochrome storyboard thumbnail. Must:
- Cite panel registers by name (dominant | transitional | rhythmic |
  climactic | atmospheric — see reference/canon/panel-registers.md)
- Specify panel geometry (grid? splash? irregular? tier count?)
- Specify eye flow (left-to-right, Z, F, vertical)
- Be pure compositional blocking — no surface texture, no faces,
  no fine line work
"""


def render_strict_template(*, page_id: str, panel_count: int) -> str:
    """Deterministic strict-mode template. No LLM call.

    Emits both new body sections with TODO scaffolding. The panel
    hierarchy enumerates one bullet per panel (using panel_count from
    the page-file frontmatter). When panel_count is 0 (unknown) we
    still render one bullet so the author has a starting point.
    """
    bullets = max(panel_count, 1)
    hierarchy = '\n'.join(
        f'- Panel {i}: TODO register: TODO role'
        for i in range(1, bullets + 1)
    ) + '\n'
    return _STRICT_TEMPLATE_HEADER + hierarchy + _STRICT_TEMPLATE_TAIL
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompts_page_architecture.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_page_architecture.py tests/test_prompts_page_architecture.py
git commit -m "Add: strict-mode template renderer for page-architecture stage (#252)

Deterministic TODO-scaffold renderer with no LLM call. Emits both new
body sections (## Page architecture and ## Page-blocking prompt) with
per-panel hierarchy bullets keyed off the page file's panel_count.
First of three coaching-mode renderers; coach and full follow."
git push
```

---

## Task 6: Coach-mode brief renderer

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_page_architecture.py`
- Test: `tests/test_prompts_page_architecture.py`

- [ ] **Step 1: Write failing tests for the coach-mode renderer**

Append to `tests/test_prompts_page_architecture.py`:

```python
def test_coach_brief_includes_decision_prompts():
    from storyforge.prompts_page_architecture import render_coach_brief
    out = render_coach_brief(
        page_id='s01-p1',
        scene_title='Studio finalization',
        panel_count=3,
        scene_brief={
            'panel_breakdown': 'p1: 3-panel tier',
            'visual_keywords': 'inkpot; trembling hand',
            'page_turn_beats': '',
        },
        prev_page=None,
        next_page={'page_id': 's01-p2', 'spread_position': 'verso'},
        canon_blocks={
            'panel-registers': 'Dominant: emotional fulcrum.\nTransitional: rhythmic bridge.',
            'page-rhythm-rules': 'One dominant per page maximum.',
        },
    )
    # Asks the author the right questions
    assert 'Which panel' in out and 'dominant' in out
    # Includes canon vocabulary inline so author doesn't need to flip files
    assert 'emotional fulcrum' in out
    assert 'One dominant per page' in out
    # References sibling page for spread context
    assert 's01-p2' in out
    # Points at where to write
    assert 'pages/s01-p1.md' in out


def test_coach_brief_handles_missing_neighbor_pages():
    from storyforge.prompts_page_architecture import render_coach_brief
    out = render_coach_brief(
        page_id='s01-p1', scene_title='Open', panel_count=1,
        scene_brief={}, prev_page=None, next_page=None, canon_blocks={},
    )
    # Doesn't crash; mentions absence
    assert 's01-p1' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompts_page_architecture.py -v`
Expected: AttributeError on `render_coach_brief`.

- [ ] **Step 3: Implement render_coach_brief**

Append to `scripts/lib/python/storyforge/prompts_page_architecture.py`:

```python
def _format_neighbor(label: str, page: dict | None) -> str:
    if not page:
        return f'- {label}: (none — this page is at the scene edge)'
    pid = page.get('page_id', '?')
    spread = page.get('spread_position', '?')
    return f'- {label}: {pid} (spread_position: {spread})'


def render_coach_brief(*,
                       page_id: str,
                       scene_title: str,
                       panel_count: int,
                       scene_brief: dict,
                       prev_page: dict | None,
                       next_page: dict | None,
                       canon_blocks: dict) -> str:
    """Coach-mode markdown brief written to working/coaching/.

    No file mutation of the page file. The brief asks the right
    questions and embeds the canon vocabulary inline so the author
    can decide without flipping files.
    """
    lines = [
        f'# Page architecture brief: {page_id}',
        '',
        f'**Scene:** {scene_title}  ',
        f'**Panels on this page:** {panel_count}',
        '',
        '## What you need to decide',
        '',
        '- Which panel is this page\'s emotional fulcrum (the dominant register)?',
        '- Which panels are transitional / rhythmic / atmospheric?',
        '- Is there a page-turn beat? What reveals on the turn?',
        '- What\'s the spread context (this page\'s relationship to its facing page)?',
        '- Dominant motif on this page (cite from motif canon)?',
        '',
        '## Canon vocabulary to use',
        '',
    ]
    for canon_id in ('panel-registers', 'page-rhythm-rules'):
        block = canon_blocks.get(canon_id, '').strip()
        if block:
            lines += [f'### {canon_id}', '', block, '']
    lines += ['## Brief inputs', '']
    for key in ('panel_breakdown', 'visual_keywords', 'page_turn_beats',
                'page_layout', 'caption_strategy'):
        val = scene_brief.get(key, '')
        lines.append(f'- **{key}:** {val or "(empty)"}')
    lines += ['', '## Sibling pages', '']
    lines.append(_format_neighbor('Previous page', prev_page))
    lines.append(_format_neighbor('Next page', next_page))
    lines += [
        '',
        '## Write your sections into the page file at:',
        '',
        f'`pages/{page_id}.md` — insert both sections between '
        '`## Scene context` and `## Panel script`.',
        '',
        'Section headers:',
        '',
        '```',
        '## Page architecture',
        '',
        '### Intent',
        '...',
        '',
        '### Panel hierarchy',
        '- Panel 1 — <register>: <one-line role>',
        '...',
        '',
        '### Book-level placement',
        '- Spread context: ...',
        '- Page-turn beat: ...',
        '',
        '## Page-blocking prompt',
        '',
        '<monochrome storyboard thumbnail; cite registers by name;',
        ' specify geometry, eye flow; no surface texture, no faces>',
        '```',
    ]
    return '\n'.join(lines) + '\n'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompts_page_architecture.py -v`
Expected: All pass (4 strict tests + 2 coach tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_page_architecture.py tests/test_prompts_page_architecture.py
git commit -m "Add: coach-mode brief renderer for page-architecture stage (#252)

render_coach_brief produces a markdown brief written to
working/coaching/page-architecture-<page_id>.md. Asks the author the
right questions (which panel dominates? page-turn beat? spread
context?), embeds panel-registers + page-rhythm-rules canon vocabulary
inline, and shows the exact section skeleton to paste into the page
file. No mutation of the page file itself — coach mode never writes
creative prose on the author's behalf."
git push
```

---

## Task 7: Full-mode LLM prompt builder

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts_page_architecture.py`
- Test: `tests/test_prompts_page_architecture.py`

- [ ] **Step 1: Write failing tests for the full-mode builder**

Append to `tests/test_prompts_page_architecture.py`:

```python
def test_full_prompt_embeds_canon_and_brief():
    from storyforge.prompts_page_architecture import build_full_prompt
    prompt = build_full_prompt(
        page_id='s01-p1',
        page_frontmatter={
            'page_id': 's01-p1', 'scene_id': 's01-studio',
            'page_within_scene': 1, 'total_pages_in_scene': 3,
            'panel_count': 2, 'spread_position': 'opening recto',
            'characters_present': ['lucien-vey'], 'location': 'archive',
            'timeline': 'day 1, evening',
        },
        scene_title='Studio finalization',
        scene_brief={
            'panel_breakdown': 'p1: 2-panel; p2: 3-panel; p3: splash',
            'visual_keywords': 'inkpot; trembling hand',
            'page_turn_beats': 'p3 reveal',
            'page_layout': '3-page scene; splash on p3',
            'caption_strategy': 'minimal',
        },
        scene_intent={
            'function': 'opening', 'emotional_arc': 'apprehension to focus',
            'value_at_stake': 'control', 'value_shift': 'positive',
        },
        prev_page=None,
        next_page={'page_id': 's01-p2', 'spread_position': 'verso'},
        canon_blocks={
            'panel-registers': 'Dominant: emotional fulcrum.',
            'page-rhythm-rules': 'One dominant per page maximum.',
            'style-foundation': 'Chiaroscuro; muted palette.',
            'lighting-laws': 'Single source; no supernatural luminosity.',
        },
    )
    # Page identity
    assert 's01-p1' in prompt
    assert 'Studio finalization' in prompt
    # Brief context
    assert '2-panel; p2: 3-panel' in prompt or 'panel_breakdown' in prompt
    assert 'inkpot' in prompt
    # Intent context
    assert 'apprehension to focus' in prompt
    # Canon embedded inline
    assert 'emotional fulcrum' in prompt
    assert 'One dominant per page' in prompt
    assert 'Chiaroscuro' in prompt
    # Neighbor for spread context
    assert 's01-p2' in prompt
    # Output contract: both section headers requested
    assert '## Page architecture' in prompt
    assert '## Page-blocking prompt' in prompt
    # Constraint: blocking prompt must cite registers + be monochrome
    assert 'monochrome' in prompt.lower()
    assert 'cite' in prompt.lower() and 'register' in prompt.lower()


def test_full_prompt_when_no_neighbor_pages():
    from storyforge.prompts_page_architecture import build_full_prompt
    prompt = build_full_prompt(
        page_id='solo-p1',
        page_frontmatter={'page_id': 'solo-p1', 'panel_count': 1},
        scene_title='Solo', scene_brief={}, scene_intent={},
        prev_page=None, next_page=None,
        canon_blocks={'panel-registers': 'Dominant: emotional fulcrum.'},
    )
    # Doesn't crash; mentions absence of neighbors so the LLM knows
    assert 'solo-p1' in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_prompts_page_architecture.py -v`
Expected: AttributeError on `build_full_prompt`.

- [ ] **Step 3: Implement build_full_prompt**

Append to `scripts/lib/python/storyforge/prompts_page_architecture.py`:

```python
def _format_frontmatter_summary(fm: dict) -> str:
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


def _format_brief(brief: dict) -> str:
    keys = ('page_layout', 'panel_breakdown', 'visual_keywords',
            'page_turn_beats', 'caption_strategy', 'goal', 'conflict',
            'outcome', 'emotions', 'motifs')
    lines = []
    for k in keys:
        v = brief.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def _format_intent(intent: dict) -> str:
    keys = ('function', 'emotional_arc', 'value_at_stake', 'value_shift',
            'turning_point', 'characters', 'on_stage')
    lines = []
    for k in keys:
        v = intent.get(k, '')
        if v:
            lines.append(f'- {k}: {v}')
    return '\n'.join(lines) if lines else '(empty)'


def build_full_prompt(*,
                      page_id: str,
                      page_frontmatter: dict,
                      scene_title: str,
                      scene_brief: dict,
                      scene_intent: dict,
                      prev_page: dict | None,
                      next_page: dict | None,
                      canon_blocks: dict) -> str:
    """Full-mode LLM prompt for one page.

    The handler is responsible for collecting canon_blocks (panel-registers,
    page-rhythm-rules, style-foundation, lighting-laws, plus per-character
    and per-location blocks) and the neighbor pages. This builder just
    assembles the prompt deterministically — no I/O.

    Output contract for the LLM: a single markdown block containing
    exactly two top-level sections — `## Page architecture` and
    `## Page-blocking prompt` — and nothing else. The handler parses
    that block, asserts both headers are present, and splices it
    into the page file.
    """
    parts: list[str] = []
    parts.append(
        f'You are writing the page architecture and page-blocking prompt '
        f'for one page of a graphic novel.'
    )
    parts.append('')
    parts.append(f'## Page identity')
    parts.append('')
    parts.append(f'- page_id: {page_id}')
    parts.append(f'- scene: {scene_title}')
    parts.append('')
    parts.append('## Page frontmatter')
    parts.append('')
    parts.append(_format_frontmatter_summary(page_frontmatter))
    parts.append('')
    parts.append('## Scene brief')
    parts.append('')
    parts.append(_format_brief(scene_brief))
    parts.append('')
    parts.append('## Scene intent')
    parts.append('')
    parts.append(_format_intent(scene_intent))
    parts.append('')
    parts.append('## Sibling pages (for spread context)')
    parts.append('')
    parts.append(_format_neighbor('Previous page', prev_page))
    parts.append(_format_neighbor('Next page', next_page))
    parts.append('')
    parts.append('## Canon vocabulary (embed verbatim — cite by name)')
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
        'Produce exactly two markdown sections, in this order, with no '
        'other text before or after:'
    )
    parts.append('')
    parts.append('```')
    parts.append('## Page architecture')
    parts.append('')
    parts.append('### Intent')
    parts.append('<narrative purpose, emotional arc, visual rhythm, dominant motif>')
    parts.append('')
    parts.append('### Panel hierarchy')
    parts.append('- Panel 1 — <register>: <one-line role>')
    parts.append('- Panel 2 — <register>: <one-line role>')
    parts.append('  (one bullet per panel; every panel MUST cite a register '
                 'from panel-registers above)')
    parts.append('')
    parts.append('### Book-level placement')
    parts.append('- Spread context: <verso of N–N+1 | recto of N–1–N | '
                 'opening recto | closing verso>')
    parts.append('- Page-turn beat: <yes/no — what reveals on the turn>')
    parts.append('')
    parts.append('## Page-blocking prompt')
    parts.append('')
    parts.append('<monochrome storyboard thumbnail prompt — locks panel '
                 'geometry, panel weights, eye flow. Cite registers by '
                 'name. Specify geometry (grid/splash/irregular/tier) and '
                 'eye flow. Pure compositional blocking — no surface '
                 'texture, no rendered detail, no faces, no fine line '
                 'work.>')
    parts.append('```')
    parts.append('')
    parts.append(
        'Constraints (the page-blocking prompt MUST satisfy):'
    )
    parts.append('- Cite at least one register by name from panel-registers')
    parts.append('- Specify panel geometry explicitly')
    parts.append('- Describe eye flow (e.g. left-to-right, Z-pattern, vertical)')
    parts.append('- Be monochrome / storyboard-style only — no rendered detail')
    return '\n'.join(parts) + '\n'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_prompts_page_architecture.py -v`
Expected: All pass (8 total).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_page_architecture.py tests/test_prompts_page_architecture.py
git commit -m "Add: full-mode LLM prompt builder for page-architecture stage (#252)

build_full_prompt deterministically assembles a per-page prompt from
page frontmatter, scene brief, scene intent, sibling-page frontmatter,
and pre-loaded canon blocks (the handler is responsible for the I/O).
The output contract asks the LLM to emit exactly two top-level
sections so the handler can parse and splice them deterministically."
git push
```

---

## Task 8: argparse + VALID_STAGES wiring in `cmd_elaborate.py`

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Test: extend `tests/test_cmd_elaborate.py` (or create `tests/test_cmd_elaborate_args.py` if the existing file doesn't cover args)

- [ ] **Step 1: Write failing tests for the new flags**

Create `tests/test_cmd_elaborate_args.py`:

```python
"""Tests for cmd_elaborate argument parsing — covers the page-architecture
stage addition and its --page / --scene / --force flags."""

import pytest


def test_page_architecture_stage_recognized():
    from storyforge.cmd_elaborate import parse_args, VALID_STAGES
    assert 'page-architecture' in VALID_STAGES
    args = parse_args(['--stage', 'page-architecture'])
    assert args.stage == 'page-architecture'


def test_page_architecture_direct_flag():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--page-architecture'])
    assert args.stage == 'page-architecture'


def test_page_flag_passed_through():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--stage', 'page-architecture', '--page', 's01-p1'])
    assert args.page == 's01-p1'


def test_scene_flag_passed_through():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--stage', 'page-architecture', '--scene', 's01-studio'])
    assert args.scene == 's01-studio'


def test_force_flag_passed_through():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--stage', 'page-architecture', '--force'])
    assert args.force is True


def test_page_and_scene_mutually_exclusive():
    from storyforge.cmd_elaborate import parse_args
    with pytest.raises(SystemExit):
        parse_args(['--stage', 'page-architecture',
                    '--page', 's01-p1', '--scene', 's01-studio'])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_elaborate_args.py -v`
Expected: AssertionError on `'page-architecture' in VALID_STAGES`.

- [ ] **Step 3: Add stage and flags to parse_args**

In `scripts/lib/python/storyforge/cmd_elaborate.py`:

Update `VALID_STAGES` (line 46):

```python
VALID_STAGES = {'spine', 'architecture', 'map', 'briefs',
                'gap-fill', 'mice-fill', 'page-architecture'}
```

Update the `--stage` help text (line 59):

```python
    parser.add_argument('--stage', type=str, default=None,
                        help='Which elaboration stage to run '
                             '(spine|architecture|map|briefs|gap-fill|'
                             'mice-fill|page-architecture)')
```

Add three new arguments inside `parse_args`, after the existing `--coaching` argument and BEFORE `args = parser.parse_args(argv)`:

```python
    # --- page-architecture stage flags (issue #252) ---
    # --page and --scene are mutually exclusive scope filters; argparse
    # enforces this via a mutually_exclusive_group so a misuse fails
    # before the handler is invoked.
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--page', type=str, default=None,
                       help='Run page-architecture for a single page (by page_id)')
    scope.add_argument('--scene', type=str, default=None,
                       help='Run page-architecture for every page of one scene (by scene_id)')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing page-architecture / blocking-prompt sections')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_elaborate_args.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Run the existing elaborate test suite to confirm no regressions**

Run: `python3 -m pytest tests/test_cmd_elaborate.py -v 2>&1 | tail -30`
Expected: All pre-existing tests still pass (the new flags are additive).

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py tests/test_cmd_elaborate_args.py
git commit -m "Wire: page-architecture stage + --page/--scene/--force flags in cmd_elaborate (#252)

Adds 'page-architecture' to VALID_STAGES and three new flags scoped to
that stage: --page (single page by page_id), --scene (all pages of a
scene, by scene_id), --force (overwrite existing sections). --page and
--scene are mutually exclusive via argparse — invalid combos fail
before the handler is reached. Handler implementation follows in the
next commits."
git push
```

---

## Task 9: `_page_architecture_handler_gn` — preconditions + per-page dispatcher

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Test: `tests/test_cmd_elaborate_page_architecture.py`

- [ ] **Step 1: Write failing tests for the handler dispatcher and preconditions**

Create `tests/test_cmd_elaborate_page_architecture.py`:

```python
"""Tests for cmd_elaborate's _page_architecture_handler_gn — focuses on
the dispatcher (page selection, precondition gating, dry-run output).
The splice-and-write end-to-end behavior is covered separately."""

import os
import textwrap


def _make_gn_project(tmp_path):
    """Build a minimal GN project with one scene, one brief, one page,
    and populated canon files."""
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
        'page_turn_beats|page_layout|caption_strategy\n'
        's01-studio|focus|distraction|focus regained|p1: 2-panel|'
        'inkpot; hand|none|3-page scene|minimal\n'
    )
    (ref / 'scene-intent.csv').write_text(
        'id|function|emotional_arc|value_at_stake|value_shift\n'
        's01-studio|opening|tense to calm|control|positive\n'
    )
    canon = ref / 'canon'
    canon.mkdir()
    (canon / 'panel-registers.md').write_text(
        '---\ncanon_id: panel-registers\n---\n\n'
        '## Embeddable block\n\nDominant: emotional fulcrum.\n'
    )
    (canon / 'page-rhythm-rules.md').write_text(
        '---\ncanon_id: page-rhythm-rules\n---\n\n'
        '## Embeddable block\n\nOne dominant per page maximum.\n'
    )
    (canon / 'style-foundation.md').write_text(
        '---\ncanon_id: style-foundation\n---\n\n'
        '## Embeddable block\n\nChiaroscuro palette.\n'
    )
    (canon / 'lighting-laws.md').write_text(
        '---\ncanon_id: lighting-laws\n---\n\n'
        '## Embeddable block\n\nSingle light source.\n'
    )
    pages = proj / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text(textwrap.dedent("""\
        ---
        page_id: s01-p1
        scene_id: s01-studio
        page_within_scene: 1
        total_pages_in_scene: 1
        panel_count: 2
        ---

        ## Scene context

        Opening beat.

        ## Panel script

        **Panel 1.** Wide.
        """))
    return str(proj)


def test_default_targets_pages_without_architecture(tmp_path):
    """No --page / --scene → process every page missing the section."""
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
    targets = _select_pages_for_architecture(proj, page=None, scene=None, force=False)
    assert len(targets) == 1
    assert targets[0]['page_id'] == 's01-p1'


def test_force_includes_pages_with_architecture(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
    # Pre-populate the section so default mode would skip it
    page_path = os.path.join(proj, 'pages', 's01-p1.md')
    with open(page_path) as f:
        body = f.read()
    body = body.replace(
        '## Scene context\n\nOpening beat.\n\n',
        '## Scene context\n\nOpening beat.\n\n'
        '## Page architecture\n\nintent.\n\n'
        '## Page-blocking prompt\n\nstoryboard.\n\n',
    )
    with open(page_path, 'w') as f:
        f.write(body)
    assert _select_pages_for_architecture(proj, page=None, scene=None, force=False) == []
    forced = _select_pages_for_architecture(proj, page=None, scene=None, force=True)
    assert len(forced) == 1


def test_scene_filter_limits_to_one_scenes_pages(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
    # Add a second scene's page
    (os.path.join(proj, 'pages', 's02-p1.md'))
    other = os.path.join(proj, 'pages', 's02-p1.md')
    with open(other, 'w') as f:
        f.write(textwrap.dedent("""\
            ---
            page_id: s02-p1
            scene_id: s02-other
            page_within_scene: 1
            total_pages_in_scene: 1
            panel_count: 1
            ---

            ## Panel script

            **Panel 1.**
            """))
    targets = _select_pages_for_architecture(
        proj, page=None, scene='s01-studio', force=False,
    )
    assert [t['page_id'] for t in targets] == ['s01-p1']


def test_page_filter_limits_to_one_page(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
    targets = _select_pages_for_architecture(
        proj, page='s01-p1', scene=None, force=False,
    )
    assert [t['page_id'] for t in targets] == ['s01-p1']


def test_page_filter_with_unknown_page_returns_empty(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
    targets = _select_pages_for_architecture(
        proj, page='nope-p99', scene=None, force=False,
    )
    assert targets == []


def test_precondition_missing_brief_skips_page(tmp_path, capsys):
    """A page whose scene brief lacks panel_breakdown is skipped with WARN."""
    from storyforge.cmd_elaborate import _precondition_check_page
    proj = _make_gn_project(tmp_path)
    # Wipe panel_breakdown from the brief
    briefs = os.path.join(proj, 'reference', 'scene-briefs.csv')
    with open(briefs) as f:
        text = f.read()
    text = text.replace('p1: 2-panel', '')
    with open(briefs, 'w') as f:
        f.write(text)
    ok, reason = _precondition_check_page(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'panel_breakdown' in reason


def test_precondition_unfilled_canon_skips_page(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_page
    proj = _make_gn_project(tmp_path)
    # Replace panel-registers with TODO content
    pr = os.path.join(proj, 'reference', 'canon', 'panel-registers.md')
    with open(pr, 'w') as f:
        f.write('---\ncanon_id: panel-registers\n---\n\n'
                '## Embeddable block\n\nTODO — fill in vocabulary.\n')
    ok, reason = _precondition_check_page(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'panel-registers' in reason


def test_precondition_passes_when_brief_and_canon_ready(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_page
    proj = _make_gn_project(tmp_path)
    ok, reason = _precondition_check_page(proj, 's01-p1', 's01-studio')
    assert ok is True
    assert reason == ''
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_elaborate_page_architecture.py -v`
Expected: ImportError on `_select_pages_for_architecture` / `_precondition_check_page`.

- [ ] **Step 3: Implement the dispatcher and precondition helpers**

In `scripts/lib/python/storyforge/cmd_elaborate.py`, add these helpers BEFORE `_run_main_stage` (near the other handler helpers):

```python
def _select_pages_for_architecture(project_dir: str, page: str | None,
                                   scene: str | None, force: bool) -> list[dict]:
    """Return the list of parsed page-file dicts to process this run.

    Filtering rules (applied in order):
      1. --page <page_id> → exactly that page (or empty if not found)
      2. --scene <scene_id> → all pages whose scene_id matches
      3. neither → every page file in pages/
    Then (unless --force): drop pages that already have a non-empty
    `## Page architecture` section.

    Returns parsed page dicts (with 'path' key set) so callers can
    inspect frontmatter without re-parsing.
    """
    from storyforge.pages import (
        list_page_files, parse_page_file, extract_page_architecture,
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
    return [p for p in filtered
            if not extract_page_architecture(p['path']).strip()]


def _precondition_check_page(project_dir: str, page_id: str,
                             scene_id: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means skip with WARN.

    Checks:
      - scene_id exists in scenes.csv
      - scene's brief has non-empty panel_breakdown
      - canon vocabulary blocks are populated (not TODO):
        panel-registers, page-rhythm-rules
    """
    from storyforge.csv_cli import get_field
    from storyforge.canon import is_canon_block_populated

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    if not get_field(scenes_csv, scene_id, 'id'):
        return False, f'scene {scene_id} not in scenes.csv'

    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    pb = get_field(briefs_csv, scene_id, 'panel_breakdown') or ''
    if not pb.strip():
        return False, f'scene {scene_id} brief has empty panel_breakdown'

    for canon_id in ('panel-registers', 'page-rhythm-rules'):
        if not is_canon_block_populated(project_dir, canon_id):
            return False, (
                f'canon block {canon_id!r} is missing or TODO — '
                f'populate reference/canon/{canon_id}.md first'
            )
    return True, ''
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_elaborate_page_architecture.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py tests/test_cmd_elaborate_page_architecture.py
git commit -m "Add: page-architecture dispatcher + precondition helpers (#252)

_select_pages_for_architecture applies --page / --scene / --force
filtering and (by default) drops pages that already have the section
populated. _precondition_check_page returns (ok, reason) so the
handler can WARN-and-skip a page whose scene brief is incomplete or
whose canon vocabulary is still TODO. Both are pure helpers — no
side effects, no API calls — so they're cheap to unit-test."
git push
```

---

## Task 10: `_page_architecture_handler_gn` — splice + canonical_blocks_embedded

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Test: extend `tests/test_cmd_elaborate_page_architecture.py`

- [ ] **Step 1: Write failing tests for the splice and the full handler**

Append to `tests/test_cmd_elaborate_page_architecture.py`:

```python
def test_splice_inserts_between_scene_context_and_panel_script(tmp_path):
    from storyforge.cmd_elaborate import _splice_page_architecture
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(textwrap.dedent("""\
        ---
        page_id: s01-p1
        scene_id: s01
        page_within_scene: 1
        total_pages_in_scene: 1
        panel_count: 1
        ---

        ## Scene context

        Beat.

        ## Panel script

        **Panel 1.**
        """))
    sections = (
        '## Page architecture\n\n### Intent\nQuiet.\n\n'
        '## Page-blocking prompt\n\nMonochrome storyboard.\n'
    )
    _splice_page_architecture(str(page_path), sections, canon_ids=[
        'panel-registers', 'page-rhythm-rules',
    ])
    text = page_path.read_text()
    # Both sections present
    assert '## Page architecture' in text
    assert '## Page-blocking prompt' in text
    # Inserted BEFORE the panel script
    assert text.index('## Page architecture') < text.index('## Panel script')
    # AFTER scene context
    assert text.index('## Scene context') < text.index('## Page architecture')
    # canonical_blocks_embedded appended to frontmatter
    assert 'canonical_blocks_embedded:' in text
    assert 'reference/canon/panel-registers.md' in text


def test_splice_replaces_existing_sections_when_force(tmp_path):
    from storyforge.cmd_elaborate import _splice_page_architecture
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(textwrap.dedent("""\
        ---
        page_id: s01-p1
        scene_id: s01
        page_within_scene: 1
        total_pages_in_scene: 1
        panel_count: 1
        ---

        ## Scene context

        Beat.

        ## Page architecture

        OLD architecture.

        ## Page-blocking prompt

        OLD blocking.

        ## Panel script

        **Panel 1.**
        """))
    new_sections = (
        '## Page architecture\n\nNEW arch.\n\n'
        '## Page-blocking prompt\n\nNEW blocking.\n'
    )
    _splice_page_architecture(str(page_path), new_sections, canon_ids=[])
    text = page_path.read_text()
    assert 'NEW arch' in text
    assert 'OLD architecture' not in text
    assert 'NEW blocking' in text
    assert 'OLD blocking' not in text
    # Only ONE occurrence of each header (no duplication)
    assert text.count('## Page architecture') == 1
    assert text.count('## Page-blocking prompt') == 1


def test_validate_llm_response_accepts_well_formed(tmp_path):
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = (
        '## Page architecture\n\n### Intent\nQuiet.\n\n'
        '## Page-blocking prompt\n\nStoryboard.\n'
    )
    ok, sections = _validate_architecture_response(resp)
    assert ok is True
    assert '## Page architecture' in sections
    assert '## Page-blocking prompt' in sections


def test_validate_llm_response_rejects_missing_header():
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = '## Page architecture\n\nintent only.\n'
    ok, _ = _validate_architecture_response(resp)
    assert ok is False


def test_validate_llm_response_strips_fence_wrapper():
    """LLMs sometimes wrap output in ```markdown fences. The validator
    should tolerate this and unwrap before checking."""
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = (
        '```markdown\n'
        '## Page architecture\n\nIntent.\n\n'
        '## Page-blocking prompt\n\nStoryboard.\n'
        '```\n'
    )
    ok, sections = _validate_architecture_response(resp)
    assert ok is True
    assert '```' not in sections


def test_run_page_architecture_end_to_end_with_mocked_api(tmp_path, monkeypatch):
    """Full handler run with the API call mocked. Verifies one page
    file gets both sections spliced and the cost ledger gets a row."""
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn

    canned_response = (
        '## Page architecture\n\n### Intent\nMocked intent.\n\n'
        '### Panel hierarchy\n- Panel 1 — dominant: focus\n- Panel 2 — atmospheric: ambience\n\n'
        '### Book-level placement\n- Spread context: opening recto\n- Page-turn beat: no\n\n'
        '## Page-blocking prompt\n\nMonochrome storyboard. Two panels. dominant top.\n'
    )

    def fake_invoke(prompt, model, max_tokens=4096, system=None):
        return canned_response

    monkeypatch.setattr('storyforge.api.invoke_api', fake_invoke)
    # Also patch the cost-logging entry point so we don't require a
    # working ledger file in the fixture project
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)

    proj = _make_gn_project(tmp_path)
    _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )

    page_path = os.path.join(proj, 'pages', 's01-p1.md')
    text = open(page_path).read()
    assert '## Page architecture' in text
    assert 'Mocked intent' in text
    assert '## Page-blocking prompt' in text
    assert 'Monochrome storyboard' in text


def test_dry_run_prints_prompt_and_does_not_write(tmp_path, capsys):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    _run_page_architecture_handler_gn(
        proj, dry_run=True, coaching='full',
        page=None, scene=None, force=False,
    )
    captured = capsys.readouterr()
    assert 'Page architecture' in captured.out
    # Page file unchanged
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Page architecture' not in text


def test_strict_mode_writes_template_no_api_call(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    call_count = {'n': 0}

    def fake_invoke(*a, **kw):
        call_count['n'] += 1
        return ''

    monkeypatch.setattr('storyforge.api.invoke_api', fake_invoke)
    proj = _make_gn_project(tmp_path)
    _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert call_count['n'] == 0  # strict mode never invokes the API
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Page architecture' in text
    assert 'TODO register: TODO role' in text


def test_coach_mode_writes_brief_to_coaching_dir_no_page_mutation(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn

    # Coach mode embeds canon blocks; provide a stub for the inline embed
    monkeypatch.setattr(
        'storyforge.api.invoke_api',
        lambda *a, **kw: 'should not be called',
    )

    proj = _make_gn_project(tmp_path)
    _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='coach',
        page=None, scene=None, force=False,
    )
    # Page file untouched
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Page architecture' not in text
    # Brief written
    brief_path = os.path.join(proj, 'working', 'coaching',
                              'page-architecture-s01-p1.md')
    assert os.path.isfile(brief_path)
    brief = open(brief_path).read()
    assert 'Which panel' in brief
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_elaborate_page_architecture.py -v`
Expected: ImportError on `_splice_page_architecture` / `_validate_architecture_response` / `_run_page_architecture_handler_gn`.

- [ ] **Step 3: Implement splice + validator + full handler**

Add these to `scripts/lib/python/storyforge/cmd_elaborate.py` (after the helpers from Task 9):

```python
def _validate_architecture_response(text: str) -> tuple[bool, str]:
    """Parse and validate an LLM response for the page-architecture stage.

    Returns (ok, sections_block). The sections_block is the unwrapped
    text with any ```markdown fence stripped; suitable to splice
    directly into a page file. Returns (False, '') when the response
    lacks either required top-level header.
    """
    body = text.strip()
    # Strip optional ```markdown fence
    if body.startswith('```'):
        # Remove first fence line and any closing fence
        lines = body.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        body = '\n'.join(lines).strip()

    if '## Page architecture' not in body:
        return False, ''
    if '## Page-blocking prompt' not in body:
        return False, ''
    return True, body


_PAGE_ARCH_HEADER_RE = re.compile(
    r'^##\s+Page\s+architecture\s*$', re.MULTILINE | re.IGNORECASE,
)
_BLOCKING_PROMPT_HEADER_RE = re.compile(
    r'^##\s+Page[- ]blocking\s+prompt\s*$', re.MULTILINE | re.IGNORECASE,
)
_PANEL_SCRIPT_HEADER_RE = re.compile(
    r'^##\s+Panel\s+script\s*$', re.MULTILINE | re.IGNORECASE,
)


def _splice_page_architecture(page_path: str, sections_block: str,
                              canon_ids: list[str]) -> None:
    """Write the two new sections into the page file.

    - If both sections already exist, replace them (force mode).
    - Otherwise insert between '## Scene context' (if present) and
      '## Panel script' (if present), or at the end of the body.
    - Append a `canonical_blocks_embedded:` block-list to the
      frontmatter listing reference/canon/<canon_id>.md for each
      canon_id (skipping any that are already listed).
    """
    import re as _re
    with open(page_path, encoding='utf-8') as f:
        text = f.read()

    # 1. Update frontmatter to record canonical_blocks_embedded
    if canon_ids:
        text = _add_canonical_blocks_embedded(text, canon_ids)

    # 2. Splice the sections into the body
    fm_match = _re.match(r'\A(---\n.*?---\n)(.*)', text, _re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        body = fm_match.group(2)
    else:
        fm_text, body = '', text

    arch_match = _PAGE_ARCH_HEADER_RE.search(body)
    block_match = _BLOCKING_PROMPT_HEADER_RE.search(body)
    if arch_match and block_match:
        # Replace existing sections — find end of blocking-prompt section
        # by scanning for the next ## header after it
        after_block = body[block_match.end():]
        next_h = _re.search(r'^##\s+\S', after_block, _re.MULTILINE)
        end = block_match.end() + (next_h.start() if next_h else len(after_block))
        new_body = body[:arch_match.start()] + sections_block.strip() + '\n\n' + body[end:].lstrip('\n')
    else:
        # Insert: prefer between Scene context and Panel script
        ps_match = _PANEL_SCRIPT_HEADER_RE.search(body)
        if ps_match:
            insert_at = ps_match.start()
            prefix = body[:insert_at].rstrip('\n')
            suffix = body[insert_at:]
            new_body = prefix + '\n\n' + sections_block.strip() + '\n\n' + suffix
        else:
            new_body = body.rstrip('\n') + '\n\n' + sections_block.strip() + '\n'

    with open(page_path, 'w', encoding='utf-8') as f:
        f.write(fm_text + new_body)


def _add_canonical_blocks_embedded(text: str, canon_ids: list[str]) -> str:
    """Add or extend the canonical_blocks_embedded block-list in
    the frontmatter. Preserves any existing entries; appends new ones
    that aren't already present.
    """
    import re as _re
    fm_match = _re.match(r'\A---\n(.*?)---\n(.*)', text, _re.DOTALL)
    if not fm_match:
        return text
    fm = fm_match.group(1)
    body = fm_match.group(2)

    new_items = [f'reference/canon/{cid}.md' for cid in canon_ids]

    # If the key exists, find and extend its block list
    key_re = _re.compile(r'^canonical_blocks_embedded:\s*$', _re.MULTILINE)
    km = key_re.search(fm)
    if km:
        # Collect existing items immediately after the key
        after = fm[km.end():]
        existing = []
        consumed = 0
        for line in after.splitlines(keepends=True):
            if line.startswith('  - '):
                existing.append(line[4:].split('#', 1)[0].strip())
                consumed += len(line)
            else:
                break
        existing_set = set(existing)
        to_add = [n for n in new_items if n not in existing_set]
        if not to_add:
            return text
        block_end = km.end() + consumed
        addition = ''.join(f'  - {n}\n' for n in to_add)
        new_fm = fm[:block_end] + addition + fm[block_end:]
    else:
        # Append the key + list at end of frontmatter
        addition = 'canonical_blocks_embedded:\n' + \
                   ''.join(f'  - {n}\n' for n in new_items)
        new_fm = fm.rstrip('\n') + '\n' + addition

    return f'---\n{new_fm}---\n{body}'


def _run_page_architecture_handler_gn(project_dir: str, *,
                                      dry_run: bool, coaching: str,
                                      page: str | None, scene: str | None,
                                      force: bool) -> int:
    """Dispatcher for the page-architecture stage.

    Coaching modes:
      - full: LLM drafts both sections, splices into page file
      - coach: writes a brief to working/coaching/, no page mutation
      - strict: stamps a TODO template into the page file, no API call

    Returns the number of pages successfully processed. The caller
    can use this to decide exit code (0 for success or no-op, 1 for
    zero-processed-due-to-precondition-failure).
    """
    from storyforge.pages import (
        pages_for_scene as _pages_for_scene,  # used for neighbor lookup
    )
    from storyforge.prompts_page_architecture import (
        render_strict_template, render_coach_brief, build_full_prompt,
    )
    from storyforge.canon import _embeddable_block_text as _block_text
    from storyforge.csv_cli import get_field, get_row

    targets = _select_pages_for_architecture(project_dir, page, scene, force)
    if not targets:
        log('No pages need page-architecture (use --force to redo).')
        return 0

    log(f'page-architecture: {len(targets)} page(s) to process '
        f'(coaching={coaching})')

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')

    canon_block_cache: dict[str, str] = {}

    def _canon(canon_id: str) -> str:
        if canon_id not in canon_block_cache:
            path = os.path.join(project_dir, 'reference', 'canon',
                                f'{canon_id}.md')
            text = _block_text(path) if os.path.isfile(path) else None
            canon_block_cache[canon_id] = (text or '').strip()
        return canon_block_cache[canon_id]

    processed = 0
    skipped_precondition = 0
    for parsed in targets:
        page_id = parsed.get('page_id', '')
        scene_id = parsed.get('scene_id', '')
        page_path = parsed['path']

        ok, reason = _precondition_check_page(project_dir, page_id, scene_id)
        if not ok:
            log(f'  WARN skip {page_id}: {reason}')
            skipped_precondition += 1
            continue

        scene_title = get_field(scenes_csv, scene_id, 'title') or scene_id
        scene_brief = get_row(briefs_csv, scene_id) or {}
        scene_intent = get_row(intent_csv, scene_id) or {}

        # Neighbors (for spread context)
        siblings = _pages_for_scene(project_dir, scene_id)
        prev_page = next_page = None
        for i, sib in enumerate(siblings):
            if sib.get('page_id') == page_id:
                if i > 0:
                    prev_page = siblings[i - 1]
                if i + 1 < len(siblings):
                    next_page = siblings[i + 1]
                break

        # Coaching dispatch
        if coaching == 'strict':
            template = render_strict_template(
                page_id=page_id,
                panel_count=parsed.get('panel_count', 0) or 0,
            )
            if dry_run:
                print(f'===== DRY RUN: strict template for {page_id} =====')
                print(template)
                continue
            _splice_page_architecture(page_path, template, canon_ids=[])
            log(f'  {page_id}: strict template written')
            processed += 1
            continue

        canon_blocks = {
            cid: _canon(cid)
            for cid in ('panel-registers', 'page-rhythm-rules',
                        'style-foundation', 'lighting-laws')
        }

        if coaching == 'coach':
            brief = render_coach_brief(
                page_id=page_id, scene_title=scene_title,
                panel_count=parsed.get('panel_count', 0) or 0,
                scene_brief=scene_brief,
                prev_page=prev_page, next_page=next_page,
                canon_blocks=canon_blocks,
            )
            if dry_run:
                print(f'===== DRY RUN: coach brief for {page_id} =====')
                print(brief)
                continue
            coaching_dir = os.path.join(project_dir, 'working', 'coaching')
            os.makedirs(coaching_dir, exist_ok=True)
            brief_path = os.path.join(
                coaching_dir, f'page-architecture-{page_id}.md',
            )
            with open(brief_path, 'w', encoding='utf-8') as f:
                f.write(brief)
            log(f'  {page_id}: coach brief written to {brief_path}')
            processed += 1
            continue

        # Full mode
        prompt = build_full_prompt(
            page_id=page_id, page_frontmatter=parsed,
            scene_title=scene_title, scene_brief=scene_brief,
            scene_intent=scene_intent,
            prev_page=prev_page, next_page=next_page,
            canon_blocks=canon_blocks,
        )
        if dry_run:
            print(f'===== DRY RUN: full prompt for {page_id} =====')
            print(prompt)
            continue

        from storyforge.api import invoke_api
        stage_model = select_model('drafting')
        response = invoke_api(prompt, stage_model, max_tokens=2048)
        ok, sections = _validate_architecture_response(response)
        if not ok:
            log(f'  WARN {page_id}: LLM response missing required headers; '
                f'skipped')
            continue
        canon_ids_used = [
            cid for cid in ('panel-registers', 'page-rhythm-rules',
                            'style-foundation', 'lighting-laws')
            if canon_blocks.get(cid)
        ]
        _splice_page_architecture(page_path, sections, canon_ids_used)
        try:
            log_operation(
                project_dir, 'elaborate-page-architecture-gn',
                stage_model, 0, 0, 0.0, target=page_id,
            )
        except Exception:
            pass
        log(f'  {page_id}: full sections written')
        processed += 1

    if processed == 0 and skipped_precondition > 0:
        return 1
    return processed
```

Add the imports needed at the top of `cmd_elaborate.py` (locate the existing `from storyforge.costs import log_operation` import — it's used inside `_briefs_handler_gn`; ensure it's hoisted to module scope if not already):

```python
# Near the top imports (group with existing storyforge imports)
from storyforge.costs import log_operation
```

If `log_operation` is already imported at module scope, skip this; if it's only imported lazily inside helpers, hoist it (the new handler references it at the top level).

- [ ] **Step 4: Wire the handler into `_run_main_stage`**

In `_run_main_stage` (around line 690 where stages are dispatched), add a branch BEFORE the existing `elif stage == 'spine':` block (so the page-architecture stage short-circuits with its own scaffolding, like the GN briefs handler does):

```python
    if stage == 'page-architecture':
        if medium != 'graphic-novel':
            log('ERROR: page-architecture stage is graphic-novel-only.')
            sys.exit(1)
        coaching = (
            getattr(args, 'coaching', None)
            or get_coaching_level(project_dir)
        )
        rc = _run_page_architecture_handler_gn(
            project_dir, dry_run=dry_run, coaching=coaching,
            page=getattr(args, 'page', None),
            scene=getattr(args, 'scene', None),
            force=getattr(args, 'force', False),
        )
        sys.exit(rc)
```

Look at the `_run_main_stage` signature — it accepts `dry_run, interactive, seed`. The `args` object isn't passed in today. We need to thread the new args through. Two options:

**Option A (recommended for this PR):** pass `args` directly into `_run_main_stage`.

Update the function signature:

```python
def _run_main_stage(stage: str, project_dir: str, ref_dir: str,
                    dry_run: bool, interactive: bool, seed: str,
                    args=None,
                    session_start: str | None = None) -> None:
```

And update the caller in `main` (search for `_run_main_stage(`) to pass `args=args`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_elaborate_page_architecture.py -v`
Expected: all 16 tests pass (8 from Task 9 + 8 added here).

- [ ] **Step 6: Run the full elaborate test suite**

Run: `python3 -m pytest tests/test_cmd_elaborate.py tests/test_cmd_elaborate_args.py tests/test_cmd_elaborate_page_architecture.py -v 2>&1 | tail -40`
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py tests/test_cmd_elaborate_page_architecture.py
git commit -m "Add: _page_architecture_handler_gn — splice, validate, dispatch (#252)

The handler:
  * full mode: invokes Opus, validates the response contains both
    required section headers (tolerates ```markdown fence wrapping),
    splices both sections into the page file between Scene context
    and Panel script, and appends canonical_blocks_embedded to the
    frontmatter as an audit trail
  * coach mode: writes working/coaching/page-architecture-<page_id>.md
    asking the right questions with canon vocabulary embedded inline;
    does NOT mutate the page file
  * strict mode: stamps a deterministic TODO template into the page
    file with per-panel hierarchy bullets; no API call
Exit code 1 when zero pages were processed AND at least one was
skipped due to a precondition failure (so CI / scripted runs surface
the unmet preconditions); 0 otherwise."
git push
```

---

## Task 11: `script-package` — emit `page-blocking-prompts.md`

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_script_package.py`
- Test: `tests/test_cmd_script_package_blocking.py`

- [ ] **Step 1: Write failing tests for the new bundle file**

Create `tests/test_cmd_script_package_blocking.py`:

```python
"""Tests for cmd_script_package's manuscript/page-blocking-prompts.md
output (issue #252)."""

import os
import textwrap


def _write_page(pages_dir, page_id, scene_id, within, total, body):
    text = textwrap.dedent(f"""\
        ---
        page_id: {page_id}
        scene_id: {scene_id}
        page_within_scene: {within}
        total_pages_in_scene: {total}
        panel_count: 2
        ---

        {body}
        """)
    with open(os.path.join(pages_dir, f'{page_id}.md'), 'w') as f:
        f.write(text)


def test_assemble_blocking_prompts_concatenates_in_global_page_order(tmp_path):
    from storyforge.cmd_script_package import _assemble_blocking_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 2,
                '## Page-blocking prompt\n\nFIRST blocking.\n\n'
                '## Panel script\n\n**Panel 1.**\n')
    _write_page(str(pages_dir), 's01-p2', 's01-studio', 2, 2,
                '## Page-blocking prompt\n\nSECOND blocking.\n\n'
                '## Panel script\n\n**Panel 1.**\n')
    chapters = [{
        'chapter': 1, 'title': 'One', 'heading': 'One',
        'scenes': ['s01-studio'],
    }]
    # Stub scene title lookup via a tiny scenes.csv
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    (ref_dir / 'scenes.csv').write_text(
        'id|seq|title\ns01-studio|1|Studio\n'
    )
    out = _assemble_blocking_prompts(str(tmp_path), chapters)
    # Both prompts present in global page order
    assert 'FIRST blocking' in out
    assert 'SECOND blocking' in out
    assert out.index('FIRST blocking') < out.index('SECOND blocking')
    # Global page numbering (page 1, page 2)
    assert 'Global page 1' in out
    assert 'Global page 2' in out
    # Page ids in headers
    assert 's01-p1' in out
    assert 's01-p2' in out


def test_assemble_blocking_prompts_omits_pages_without_blocking_section(tmp_path):
    from storyforge.cmd_script_package import _assemble_blocking_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 2,
                '## Page-blocking prompt\n\nONLY blocking.\n\n## Panel script\n\n**Panel 1.**\n')
    _write_page(str(pages_dir), 's01-p2', 's01-studio', 2, 2,
                '## Panel script\n\n**Panel 1.**\n')  # no blocking prompt
    chapters = [{
        'chapter': 1, 'title': 'One', 'heading': 'One',
        'scenes': ['s01-studio'],
    }]
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    (ref_dir / 'scenes.csv').write_text(
        'id|seq|title\ns01-studio|1|Studio\n'
    )
    out = _assemble_blocking_prompts(str(tmp_path), chapters)
    assert 'ONLY blocking' in out
    # The page without a blocking prompt does NOT appear as a header
    assert 's01-p2' not in out


def test_assemble_blocking_prompts_returns_empty_when_no_prompts(tmp_path):
    from storyforge.cmd_script_package import _assemble_blocking_prompts
    pages_dir = tmp_path / 'pages'
    pages_dir.mkdir()
    _write_page(str(pages_dir), 's01-p1', 's01-studio', 1, 1,
                '## Panel script\n\n**Panel 1.**\n')
    chapters = [{
        'chapter': 1, 'title': 'One', 'heading': 'One',
        'scenes': ['s01-studio'],
    }]
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    (ref_dir / 'scenes.csv').write_text(
        'id|seq|title\ns01-studio|1|Studio\n'
    )
    out = _assemble_blocking_prompts(str(tmp_path), chapters)
    assert out == ''


def test_handoff_readme_includes_generation_order_when_file_emitted():
    from storyforge.cmd_script_package import HANDOFF_README
    # The template must be parameterizable on a 'blocking_line' field that
    # the main function fills in conditionally.
    rendered = HANDOFF_README.format(
        title='Test', canon_line='',
        blocking_line='\n- `page-blocking-prompts.md` — render these first.',
    )
    assert 'page-blocking-prompts.md' in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cmd_script_package_blocking.py -v`
Expected: ImportError on `_assemble_blocking_prompts` and KeyError on `blocking_line` template field.

- [ ] **Step 3: Add `_assemble_blocking_prompts`**

In `scripts/lib/python/storyforge/cmd_script_package.py`, add this helper near the existing `_assemble_script`:

```python
def _assemble_blocking_prompts(project_dir: str, chapters: list[dict]) -> str:
    """Concatenate per-page blocking prompts in global page order.

    Iterates chapters → scenes → page files (sorted by page_within_scene),
    pulls the `## Page-blocking prompt` section out of each, and emits
    a per-page header carrying the same global page number that
    _assemble_script's renumberer assigns.

    Returns '' when no page in the bundle has a blocking-prompt
    section (so the caller can skip writing the file entirely).
    """
    from storyforge.pages import pages_for_scene, extract_blocking_prompt
    from storyforge.csv_cli import get_field

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    sections: list[str] = []
    global_page = 0
    for chap in chapters:
        for sid in chap['scenes']:
            scene_title = get_field(scenes_csv, sid, 'title') or sid
            siblings = pages_for_scene(project_dir, sid)
            total = len(siblings)
            for i, page in enumerate(siblings, start=1):
                global_page += 1
                body = extract_blocking_prompt(page['path']).strip()
                if not body:
                    continue
                page_id = page.get('page_id', '?')
                sections.append(
                    f'## Global page {global_page} ({page_id}) — '
                    f'{scene_title}, page {i}/{total}\n\n{body}\n'
                )
    return '\n'.join(sections)
```

- [ ] **Step 4: Update `HANDOFF_README` template and `main` to emit the file**

Locate the `HANDOFF_README` constant in `cmd_script_package.py`. Add a `{blocking_line}` placeholder in the same position the existing `{canon_line}` placeholder occupies — for example, immediately after the canon line in the bundle inventory:

```python
HANDOFF_README = """\
# {title} — Artist Handoff Bundle
...existing content...
{canon_line}{blocking_line}
...
"""
```

(Inspect the existing template; place `{blocking_line}` as a sibling of `{canon_line}`.)

Add a paragraph describing generation order — to be injected when there are blocking prompts. Define it as a module-level constant near `HANDOFF_README`:

```python
_BLOCKING_PROMPTS_INVENTORY_LINE = (
    '\n- `page-blocking-prompts.md` — Page-level blocking prompts to '
    'render BEFORE per-panel art. Each prompt locks panel geometry, '
    'panel weights, and eye flow as a monochrome storyboard thumbnail. '
    'Render the blocking image for each page first, then iterate on '
    'per-panel prompts against the locked geometry. This prevents the '
    '"every panel is a feature image" failure mode that uniform '
    'per-panel rendering produces.'
)
```

In `main`, after the `canon_copied = _copy_canon_into_bundle(...)` block and BEFORE the `handoff-readme.md` write, add:

```python
    # page-blocking-prompts.md (issue #252) — emit only when any page
    # in the bundle has a blocking prompt
    blocking_md = _assemble_blocking_prompts(project_dir, chapters)
    blocking_line = ''
    if blocking_md:
        blocking_path = os.path.join(bundle_dir, 'page-blocking-prompts.md')
        with open(blocking_path, 'w', encoding='utf-8') as f:
            f.write(blocking_md)
        log('  manuscript/page-blocking-prompts.md')
        blocking_line = _BLOCKING_PROMPTS_INVENTORY_LINE
```

Update the existing `HANDOFF_README.format(...)` call to pass `blocking_line=blocking_line`:

```python
    readme = HANDOFF_README.format(
        title=title, canon_line=canon_line, blocking_line=blocking_line,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_cmd_script_package_blocking.py -v`
Expected: 4 tests pass.

- [ ] **Step 6: Run the full script-package test suite**

Run: `python3 -m pytest tests/test_cmd_script_package.py tests/test_cmd_script_package_blocking.py -v 2>&1 | tail -30`
Expected: existing tests pass. If any existing test breaks because `HANDOFF_README.format(...)` now requires `blocking_line`, update those tests to pass `blocking_line=''`.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_script_package.py tests/test_cmd_script_package_blocking.py
git commit -m "Add: manuscript/page-blocking-prompts.md output to script-package (#252)

_assemble_blocking_prompts iterates chapters → scenes → pages (sorted
by page_within_scene), pulls each page's ## Page-blocking prompt
section, and concatenates them in global page order with the same
page numbering script-package already uses for script.md. The bundle
file is only written when at least one page has a blocking prompt;
otherwise the file is omitted and handoff-readme.md does not reference
it. The README's generation-order paragraph explains the
'render blocking first, panels against locked geometry' workflow."
git push
```

---

## Task 12: Fixtures, docs, version bump, final verification

**Files:**
- Create: `tests/fixtures/test-project-gn/pages/s01-p1.md` (populated example)
- Create: `tests/fixtures/test-project-gn/pages/s01-p2.md` (gaps example)
- Modify: `skills/elaborate/SKILL.md`
- Modify: `skills/forge/SKILL.md`
- Modify: `CLAUDE.md`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Create the fixture page files**

Create `tests/fixtures/test-project-gn/pages/s01-p1.md`:

```markdown
---
page_id: s01-p1
scene_id: s01-studio-finalization
page_within_scene: 1
total_pages_in_scene: 2
panel_count: 2
spread_position: opening recto
characters_present: [lucien-vey]
location: archive-studio
timeline: day 1, evening
canonical_blocks_embedded:
  - reference/canon/panel-registers.md
  - reference/canon/page-rhythm-rules.md
---

## Scene context

Lucien finalizes the inkpot recipe before the trial.

## Page architecture

### Intent
Open with quiet, controlled tension. Establish the studio space and
Lucien's focus on the inkpot.

### Panel hierarchy
- Panel 1 — atmospheric: wide establishing of the studio
- Panel 2 — dominant: close on Lucien's hand with the inkpot

### Book-level placement
- Spread context: opening recto (book's first page)
- Page-turn beat: no — the page-turn beat lands on p2

## Page-blocking prompt

Monochrome storyboard thumbnail. Two-panel page, vertical stack.
Top panel (atmospheric register): wide establishing — studio space
in low-key value range, no character detail, eye flow established
left-to-right. Bottom panel (dominant register): close on a hand
holding a small object — strongest value contrast on the page,
draws the eye on the descent. Pure compositional blocking — no
surface texture, no rendered faces, no fine line work.

## Panel script

**Panel 1.** Wide. The studio.

**Panel 2.** Close. Lucien's hand with the inkpot.

## Image-generation prompts

(per-panel prompts here in the real workflow)
```

Create `tests/fixtures/test-project-gn/pages/s01-p2.md`:

```markdown
---
page_id: s01-p2
scene_id: s01-studio-finalization
page_within_scene: 2
total_pages_in_scene: 2
panel_count: 1
spread_position: verso of 2-3
characters_present: [lucien-vey]
location: archive-studio
timeline: day 1, evening
---

## Scene context

The page-turn reveal.

## Panel script

**Panel 1.** Splash. The inkpot reflects an impossible face.
```

(Note: s01-p2 has both new sections ABSENT — exercises the cleanup findings.)

- [ ] **Step 2: Run the cleanup test against the updated fixture**

Run: `python3 -m pytest tests/test_cmd_cleanup.py -v -k 'page' 2>&1 | tail -20`
Expected: any pre-existing fixture tests still pass; if a test asserted "no page warnings on the fixture project," it now needs to either accept the new warnings on `s01-p2` or be updated. Make minimal updates to existing tests so they tolerate the two new warning kinds on `s01-p2` (e.g., filter them out, or assert their presence).

- [ ] **Step 3: Update `skills/elaborate/SKILL.md`**

Find the section that lists elaboration stages. Add a new stage entry for `page-architecture`:

````markdown
### Page architecture (graphic-novel only)

**Stage:** `--stage page-architecture` (or `--page-architecture`)
**Purpose:** Lock page-level rhythm and panel geometry before any per-panel image rendering.
**Output:** `## Page architecture` + `## Page-blocking prompt` sections in each page file under `pages/`.
**Preconditions:** scene brief has `panel_breakdown`; `reference/canon/panel-registers.md` and `reference/canon/page-rhythm-rules.md` are populated (not TODO).

**Flags:**
- `--page <page_id>` — single page only
- `--scene <scene_id>` — every page of one scene
- `--force` — overwrite existing sections
- `--dry-run` — print one prompt, no API calls

**Coaching modes:**
- **full** — LLM drafts both sections directly into the page file
- **coach** — writes a markdown brief to `working/coaching/page-architecture-<page_id>.md` asking the right questions; no mutation of the page file
- **strict** — stamps a deterministic TODO template into the page file; no API call

**When to run:** after `briefs` in graphic-novel projects, before drafting per-panel image prompts.
````

- [ ] **Step 4: Update `skills/forge/SKILL.md`**

Find the GN-mode section that describes the pipeline ordering. Add `page-architecture` between `briefs` and per-panel work. Make the recommendation conditional on canon files being populated:

```markdown
- **After briefs (GN mode):** Run `storyforge elaborate --stage page-architecture` to lock page-level rhythm and panel geometry before per-panel rendering. Requires `reference/canon/panel-registers.md` and `reference/canon/page-rhythm-rules.md` to be populated.
```

(Insert at the appropriate spot in the existing GN pipeline recommendations.)

- [ ] **Step 5: Update `CLAUDE.md`**

In the elaborate stage table (look for the `| storyforge elaborate |` row), append `|page-architecture` to the stages list in the Purpose column. Add a new sentence describing the page-architecture stage.

In the Graphic Novel Mode section, add a paragraph:

```markdown
**Page architecture (issue #252):** `storyforge elaborate --stage page-architecture` writes `## Page architecture` and `## Page-blocking prompt` sections into each page file in `pages/`. Locks page-level rhythm + panel geometry before per-panel rendering. Requires `reference/canon/panel-registers.md` and `reference/canon/page-rhythm-rules.md` to be populated. `script-package` aggregates the blocking prompts into `manuscript/page-blocking-prompts.md` in the artist handoff bundle.
```

- [ ] **Step 6: Bump version**

Edit `.claude-plugin/plugin.json`. Find the `"version"` field and bump it to `"1.40.0"`.

- [ ] **Step 7: Run the full test suite**

Run: `python3 -m pytest tests/ -v 2>&1 | tail -40`
Expected: all tests pass.

- [ ] **Step 8: Final commit**

```bash
git add tests/fixtures/test-project-gn/pages/ \
        skills/elaborate/SKILL.md skills/forge/SKILL.md \
        CLAUDE.md .claude-plugin/plugin.json
git commit -m "Bump version to 1.40.0 — GN page-blocking pass (issue #252)

Fixture pages exercise both the populated path (s01-p1 with both new
sections + canonical_blocks_embedded frontmatter) and the gap path
(s01-p2 missing both sections, which triggers the new cleanup
warnings). Skill docs describe the new stage + coaching modes;
CLAUDE.md documents the GN pipeline ordering and the new bundle file."
git push
```

- [ ] **Step 9: Open the pull request**

```bash
gh pr create --title "GN page-blocking pass — page architecture + blocking prompt (#252)" --body "$(cat <<'EOF'
## Summary

- Adds `storyforge elaborate --stage page-architecture` — writes `## Page architecture` and `## Page-blocking prompt` sections into each per-page file for graphic-novel projects
- Adds `manuscript/page-blocking-prompts.md` to the artist handoff bundle, concatenated in global page order
- Two new `cleanup` warnings (`page_missing_page_architecture`, `page_missing_blocking_prompt`) surface gaps as informational findings
- Builds on per-page files (#251) and the canon files (#254 — `panel-registers.md`, `page-rhythm-rules.md`)
- Sets the foundation for the 13-section panel prompt schema (#253)

## Test plan
- [ ] `python3 -m pytest tests/ -v` — all pass
- [ ] `storyforge elaborate --stage page-architecture --dry-run` on a populated GN project prints a sensible prompt with canon embeds + scene brief + neighbor pages
- [ ] `storyforge elaborate --stage page-architecture` (full coaching) splices both sections into a sample page
- [ ] `storyforge elaborate --stage page-architecture --coaching coach` writes a brief to `working/coaching/`
- [ ] `storyforge elaborate --stage page-architecture --coaching strict` stamps the TODO template
- [ ] `storyforge cleanup` reports the two new warnings against pages missing the sections
- [ ] `storyforge script-package` includes `manuscript/page-blocking-prompts.md` when blocking prompts exist; `handoff-readme.md` describes the generation order

Closes #252.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Summary

12 tasks, all bite-sized, each with a TDD cycle (failing test → minimal implementation → green → commit → push). Each commit is independently reviewable and the branch stays push-after-every-change per project convention.

## Changes

- `pages.py` — two new extractors, two new finding kinds, validation extension
- `canon.py` — `is_canon_block_populated` public helper
- `prompts_page_architecture.py` (new) — strict / coach / full mode renderers
- `cmd_elaborate.py` — `page-architecture` stage + `--page` / `--scene` / `--force` flags + handler with precondition gating
- `cmd_cleanup.py` — surface the two new finding kinds
- `cmd_script_package.py` — emit `manuscript/page-blocking-prompts.md`; update README template
- Skill + CLAUDE.md docs; version bump to 1.40.0

## Test plan

Every task's tests above. Total ≈ 40 new tests across 6 new test files. Plus mocked-API end-to-end in `test_cmd_elaborate_page_architecture.py` exercising all three coaching modes.

## Out of scope (sibling issues, per #252)

- 13-section modular panel-prompt schema → #253
- Deeper blocking-prompt structural validation (clause presence, register citation, geometry specificity) → #253
- Visual reference thumbnail rendering → #212
- Bookshelf publish for GN → #215

---

## Self-Review (executed before publishing this plan)

**Spec coverage:**
- §3.1 page-file body additions → Task 1 (extractors), Task 10 (splice), Task 12 (fixture pages)
- §3.2 extractors in pages.py → Task 1 ✓
- §3.3 no frontmatter changes; canonical_blocks_embedded audit trail → Task 10 (`_add_canonical_blocks_embedded`) ✓
- §4 authoring command (stage registration, flags, preconditions, LLM context, model, cost tracking) → Tasks 8, 9, 10 ✓
- §5 coaching modes (full / coach / strict) → Tasks 5, 6, 7, 10 ✓
- §6 cleanup integration (two new finding kinds with strict-mode-TODO exception) → Tasks 2, 3 ✓
- §7 script-package integration (`page-blocking-prompts.md`, conditional README paragraph) → Task 11 ✓
- §8 file-by-file inventory → all files touched in tasks above
- §9 testing strategy (unit + integration coverage, finding-kind trigger tests) → tests in each task ✓
- §12 acceptance criteria → covered by combined test runs in Tasks 10, 11, 12

**Placeholder scan:** No "TBD" / "TODO" / vague phrases at the spec-task level. The strict template's TODO content is intentional output content (author-facing, not a spec gap).

**Type consistency:** `PageFindingKind` values `missing_page_architecture` and `missing_blocking_prompt` are used identically across Tasks 2, 3. The handler exports `_select_pages_for_architecture`, `_precondition_check_page`, `_validate_architecture_response`, `_splice_page_architecture`, `_add_canonical_blocks_embedded`, `_run_page_architecture_handler_gn` — all referenced consistently. `_assemble_blocking_prompts` in Task 11 matches its test imports. `HANDOFF_README` gains a `{blocking_line}` field; the test in Task 11 verifies it.

**Scope:** Focused on one feature — page-blocking pass — with no scope creep into the 13-section schema (#253) or visual-reference rendering (#212). Reasonable for one PR.

**Ambiguity:** One spot needed tightening — `_run_main_stage` doesn't currently accept `args`. Task 10 Step 4 spells out the signature change and the caller update so the implementer doesn't have to guess.
