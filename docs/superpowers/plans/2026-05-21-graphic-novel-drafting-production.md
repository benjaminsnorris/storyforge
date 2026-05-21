# Graphic Novel Mode — Drafting & Production (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the drafting and artist-handoff half of graphic-novel mode. Authors can now draft scenes (`./storyforge write` produces a panel-by-panel script per scene) and assemble the artist deliverable (`./storyforge assemble` produces a handoff bundle: script.md, visual-references.md, chapter-map.md, handoff-readme.md, optionally PDF).

**Architecture:** Three new code modules sit alongside their novel-mode counterparts. `script_format.py` is the foundation — it parses the panel-script markdown structure and runs brief-fidelity checks. `prompts_gn.py` builds drafting prompts. `cmd_write_gn.py` orchestrates per-scene drafting with parallel waves. `cmd_script_package.py` assembles the artist bundle. The dispatcher in `__main__.py` routes `write` and `assemble` to the GN versions when `project.medium == 'graphic-novel'`.

**Tech Stack:** Python 3, pytest, the existing storyforge package layout, the Anthropic API via `storyforge.api`.

**Companion spec:** `docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md` (Plan 2 scope is in "Drafting" and "Production" sections; "Out of scope for v1" still excludes evaluation/scoring/revise/publish/annotations).

**Issue:** [#208](https://github.com/benjaminsnorris/storyforge/issues/208)

**Branch:** Stay on `storyforge/graphic-novel-drafting-production-{timestamp}`. Per CLAUDE.md, every task ends with `git add -A && git commit -m "..." && git push`.

---

## File Structure

### Created files

| Path | Purpose |
|---|---|
| `scripts/lib/python/storyforge/script_format.py` | Panel-script parser (pages, panels, page-turn markers, prefix vocab) + brief-fidelity check |
| `scripts/lib/python/storyforge/prompts_gn.py` | Drafting prompt builder for GN scenes |
| `scripts/lib/python/storyforge/cmd_write_gn.py` | GN scene drafting command |
| `scripts/lib/python/storyforge/cmd_script_package.py` | GN artist-handoff bundle assembler |
| `skills/script-package/SKILL.md` | Interactive production skill for GN projects |
| `tests/test_script_format.py` | Unit tests for the script-format parser |
| `tests/test_cmd_write_gn.py` | Unit tests for GN drafting (API mocked) |
| `tests/test_cmd_script_package.py` | Unit tests for the production bundle |
| `tests/test_pipeline_gn.py` | Integration test: full GN pipeline on the fixture |

### Modified files

| Path | Change |
|---|---|
| `scripts/lib/python/storyforge/__main__.py` | Remove `write` and `assemble` from `GN_UNSUPPORTED_COMMANDS`; add medium-aware routing that dispatches `write` to `cmd_write_gn` and `assemble` to `cmd_script_package` when `project.medium == 'graphic-novel'` |
| `tests/test_medium.py` | Update `test_dispatcher_blocks_unsupported_commands_in_gn_mode` parametrize list (remove `write` and `assemble`); add tests that `write` and `assemble` route to the GN modules |
| `tests/fixtures/test-project-gn/reference/scenes.csv` | One scene's `status` should be `briefed` rather than `drafted` so the drafting test has work to do — verify current state; adjust only if needed |
| `.claude-plugin/plugin.json` | Bump minor version (new feature: drafting + production for GN) |
| `CLAUDE.md` | Update "Supported in current version" to include drafting and production; move `write`/`assemble` from "Not yet supported" to "Supported"; remove issue #208 reference from followups |

---

## Phase 1 — `script_format.py`: foundation parser

### Task 1: Script-format parser and brief-fidelity check

**Files:**
- Create: `scripts/lib/python/storyforge/script_format.py`
- Create: `tests/test_script_format.py`

The parser turns a panel-script markdown file into structured data and runs brief-fidelity checks.

#### Script format reminder

```markdown
# Scene: scene-id

**Target pages:** 4 | **Layout intent:** Splash p1, 6-panel p2-3, splash p4

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
The cartographer at his desk...

- CAPTION: *The map remained blank.*
- CARTOGRAPHER: It always begins this way.

---

## Page 4 — SPLASH ⟵ PAGE-TURN REVEAL

**Panel 1** (full bleed)
...
```

#### Public API (target)

```python
def parse_script(text: str) -> dict:
    """Return {'pages': [...], 'total_panels': int, 'page_count': int}.

    Each page dict: {'number': int, 'layout': str, 'is_page_turn': bool,
                     'panels': [{'number': int, 'size_hint': str|None,
                                 'composition': str, 'dialogue': [...]}]}
    Each dialogue entry: {'prefix': str, 'speaker': str|None, 'text': str}.
    """


def count_pages(text: str) -> int: ...
def count_panels(text: str) -> int: ...
def detect_page_turn_pages(text: str) -> list[int]: ...


def check_brief_fidelity(brief_row: dict, script_text: str) -> list[dict]:
    """Verify a drafted script matches its brief.

    Checks:
      - Every entry in brief['key_dialogue'] appears (substring match,
        case-insensitive) in a dialogue line.
      - Every entry in brief['visual_keywords'] (semicolon-split) appears
        in some panel's composition prose.
      - The script's actual per-page panel structure matches
        brief['panel_breakdown'] (e.g., "p1:splash; p2:6-grid"). Tokens
        recognized: 'splash', 'N-grid' where N is a positive integer,
        'double-spread', 'tier', 'irregular'.
      - Every entry in brief['page_turn_beats'] lands on a page whose
        first panel was marked with the page-turn marker.

    Returns a list of failure dicts: [{'kind': str, 'detail': str,
                                       'expected': str, 'severity': str}]
    Empty list = full fidelity.
    """
```

#### Implementation notes

- Use the `re` module. Patterns:
  - Page header: `^## Page (\d+) — ([A-Z][A-Z0-9 \-]+?)(?:\s+(⟵ PAGE-TURN REVEAL))?$`
  - Panel block: `^\*\*Panel (\d+)\*\*(?:\s+\(([^)]+)\))?` followed by prose lines until next `**Panel`, `---`, or `## Page`.
  - Dialogue line: `^- ([A-Z][A-Z\-]*(?:\s+[A-Z][A-Z\-]*)*):\s*(.*)` — captures `PREFIX` (one or more uppercase tokens, may include `OFF-PANEL`) plus content. Use known-prefix detection: `CAPTION`, `SFX`, `WHISPER`, `THOUGHT`, `OFF-PANEL` are atomic; anything else with this shape is treated as a character name.
- Panel structure tokens for fidelity: `splash → 1 panel`, `N-grid → N panels`, `double-spread → 1 panel (or sometimes 2, but the brief abstraction is 1 panel block)`, `tier → 3 panels (heuristic)`, `irregular → no count check`.
- For fidelity, parse `brief['panel_breakdown']` by semicolon then by `p<digit>:<tokens>`. Compare per-page actual panel count against expected.

#### TDD steps

- [ ] **Step 1: Write failing tests for the parser**

Create `tests/test_script_format.py`:

```python
"""Tests for script_format parser and brief-fidelity check."""

import pytest

from storyforge.script_format import (
    parse_script, count_pages, count_panels,
    detect_page_turn_pages, check_brief_fidelity,
)


SAMPLE_SCRIPT = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** Splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
The cartographer at his desk. Blank parchment.

- CAPTION: *The map remained blank.*
- CARTOGRAPHER: It always begins this way.

---

## Page 2 — 4-GRID ⟵ PAGE-TURN REVEAL

**Panel 1** (top-left)
Close on his hand.

- CAPTION: *Forty years of practice.*

**Panel 2** (top-right)
The pen touches paper.

**Panel 3** (bottom-left)
A line appears.

- SFX: Scritch.

**Panel 4** (bottom-right)
He stares.

- CARTOGRAPHER: No.
"""


def test_count_pages():
    assert count_pages(SAMPLE_SCRIPT) == 2


def test_count_panels():
    assert count_panels(SAMPLE_SCRIPT) == 5  # 1 + 4


def test_detect_page_turn_pages():
    assert detect_page_turn_pages(SAMPLE_SCRIPT) == [2]


def test_parse_script_returns_pages():
    result = parse_script(SAMPLE_SCRIPT)
    assert result['page_count'] == 2
    assert result['total_panels'] == 5
    assert len(result['pages']) == 2

    p1 = result['pages'][0]
    assert p1['number'] == 1
    assert p1['layout'] == 'SPLASH'
    assert p1['is_page_turn'] is False
    assert len(p1['panels']) == 1
    assert p1['panels'][0]['number'] == 1
    assert 'full bleed' in p1['panels'][0]['size_hint']
    assert 'cartographer' in p1['panels'][0]['composition'].lower()
    # Dialogue
    dialogues = p1['panels'][0]['dialogue']
    assert any(d['prefix'] == 'CAPTION' for d in dialogues)
    assert any(d['prefix'] == 'CARTOGRAPHER' and 'always begins' in d['text'] for d in dialogues)

    p2 = result['pages'][1]
    assert p2['number'] == 2
    assert p2['layout'] == '4-GRID'
    assert p2['is_page_turn'] is True
    assert len(p2['panels']) == 4
    # SFX recognized as its own prefix
    p2_dialogues = [d for panel in p2['panels'] for d in panel['dialogue']]
    assert any(d['prefix'] == 'SFX' for d in p2_dialogues)


def test_parse_empty_script_is_safe():
    result = parse_script('# Scene: empty\n\nNothing yet.\n')
    assert result['page_count'] == 0
    assert result['total_panels'] == 0
    assert result['pages'] == []


# --- Brief fidelity ---


SAMPLE_BRIEF = {
    'id': 'the-blank-page',
    'key_dialogue': 'It always begins this way',
    'visual_keywords': 'blank parchment; trembling hand',
    'panel_breakdown': 'p1:splash; p2:4-grid',
    'page_turn_beats': 'p2 reveal of first line',
}


def test_fidelity_passes_on_matching_script():
    # Replace 'trembling hand' so the keyword appears
    script = SAMPLE_SCRIPT.replace(
        'Close on his hand.', 'Close on his trembling hand.',
    ).replace(
        'Blank parchment.', 'Blank parchment seen close.',
    )
    failures = check_brief_fidelity(SAMPLE_BRIEF, script)
    assert failures == [], f'expected no failures, got {failures}'


def test_fidelity_flags_missing_dialogue():
    script_no_quote = SAMPLE_SCRIPT.replace(
        "It always begins this way",
        "Something completely different",
    )
    failures = check_brief_fidelity(SAMPLE_BRIEF, script_no_quote)
    assert any(f['kind'] == 'dialogue_missing' for f in failures)


def test_fidelity_flags_missing_visual_keyword():
    failures = check_brief_fidelity(SAMPLE_BRIEF, SAMPLE_SCRIPT)
    # 'trembling hand' is not in the sample — should be flagged
    assert any(f['kind'] == 'visual_keyword_missing' and 'trembling' in f['detail'].lower()
               for f in failures)


def test_fidelity_flags_panel_count_mismatch():
    bad_brief = dict(SAMPLE_BRIEF, panel_breakdown='p1:splash; p2:6-grid')
    failures = check_brief_fidelity(bad_brief, SAMPLE_SCRIPT)
    assert any(f['kind'] == 'panel_count_mismatch' for f in failures)


def test_fidelity_flags_missing_page_turn():
    # Remove the page-turn marker from page 2
    script_no_turn = SAMPLE_SCRIPT.replace(' ⟵ PAGE-TURN REVEAL', '')
    failures = check_brief_fidelity(SAMPLE_BRIEF, script_no_turn)
    assert any(f['kind'] == 'page_turn_missing' for f in failures)
```

- [ ] **Step 2: Run to confirm failure**

Run: `python3 -m pytest tests/test_script_format.py -v`
Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Implement `script_format.py`**

Create `scripts/lib/python/storyforge/script_format.py`. Aim for a clean module under 250 lines:

```python
"""Panel-script format parser and brief-fidelity checker.

Parses scene markdown files produced by cmd_write_gn into structured data
and verifies that the drafted script matches the brief's contract:
dialogue lines, visual keywords, panel breakdown, page-turn beats.

Script format reference: docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md
"""

import re

# --- Regex patterns ---

PAGE_HEADER = re.compile(
    r'^## Page (\d+)\s+—\s+([A-Z][A-Z0-9 \-]+?)'
    r'(?:\s+(⟵ PAGE-TURN REVEAL))?\s*$',
    re.MULTILINE,
)
PANEL_HEADER = re.compile(
    r'^\*\*Panel (\d+)\*\*(?:\s+\(([^)]+)\))?\s*$',
    re.MULTILINE,
)
DIALOGUE_LINE = re.compile(
    r'^- ([A-Z][A-Z\-]*(?:\s+[A-Z][A-Z\-]*)*)\s*:\s*(.*)$',
)

KNOWN_PREFIXES = {'CAPTION', 'SFX', 'WHISPER', 'THOUGHT', 'OFF-PANEL'}


def _split_pages(text):
    """Yield (header_match, body_text) tuples for each page."""
    matches = list(PAGE_HEADER.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        yield m, text[start:end]


def _split_panels(page_body):
    """Yield (header_match, body_text) tuples for each panel within a page."""
    matches = list(PANEL_HEADER.finditer(page_body))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(page_body)
        yield m, page_body[start:end]


def _parse_panel(panel_body):
    """Return {'composition': str, 'dialogue': [{'prefix', 'speaker', 'text'}]}.

    Composition is the prose narration of the panel (everything between
    the panel header and the first dialogue line). Dialogue captures every
    line matching the prefix-name pattern.
    """
    lines = panel_body.split('\n')
    composition_lines = []
    dialogue = []
    in_dialogue = False
    for raw in lines:
        line = raw.rstrip()
        m = DIALOGUE_LINE.match(line)
        if m:
            in_dialogue = True
            prefix = m.group(1).strip()
            text = m.group(2).strip()
            # Strip surrounding emphasis like *...* on caption lines
            if text.startswith('*') and text.endswith('*'):
                text = text[1:-1].strip()
            speaker = None if prefix in KNOWN_PREFIXES else prefix
            dialogue.append({'prefix': prefix, 'speaker': speaker, 'text': text})
        elif not in_dialogue and line:
            composition_lines.append(line)
        # blank lines between sections are ignored
    composition = ' '.join(composition_lines).strip()
    return {'composition': composition, 'dialogue': dialogue}


def parse_script(text):
    """Parse a panel-script markdown into structured data.

    Returns:
        {
          'pages': [
            {'number': int, 'layout': str, 'is_page_turn': bool,
             'panels': [{'number': int, 'size_hint': str|None,
                         'composition': str, 'dialogue': [...]}]},
            ...
          ],
          'page_count': int,
          'total_panels': int,
        }
    """
    pages = []
    total_panels = 0
    for page_match, page_body in _split_pages(text):
        page_num = int(page_match.group(1))
        layout = page_match.group(2).strip()
        is_page_turn = bool(page_match.group(3))
        panels = []
        for panel_match, panel_body in _split_panels(page_body):
            panel_num = int(panel_match.group(1))
            size_hint = panel_match.group(2)
            parsed = _parse_panel(panel_body)
            panels.append({
                'number': panel_num,
                'size_hint': size_hint,
                **parsed,
            })
            total_panels += 1
        pages.append({
            'number': page_num,
            'layout': layout,
            'is_page_turn': is_page_turn,
            'panels': panels,
        })
    return {
        'pages': pages,
        'page_count': len(pages),
        'total_panels': total_panels,
    }


def count_pages(text):
    return len(PAGE_HEADER.findall(text))


def count_panels(text):
    return len(PANEL_HEADER.findall(text))


def detect_page_turn_pages(text):
    return [int(m.group(1)) for m in PAGE_HEADER.finditer(text) if m.group(3)]


# --- Brief fidelity ---

PANEL_TOKEN = re.compile(r'^\s*(splash|double-spread|tier|irregular|(\d+)-grid)\s*$', re.IGNORECASE)


def _panels_per_token(token):
    """Return expected panel count for a brief panel-breakdown token, or None
    when the token is 'irregular' (no count check)."""
    token = token.strip().lower()
    m = PANEL_TOKEN.match(token)
    if not m:
        return None
    if m.group(2):  # N-grid
        return int(m.group(2))
    label = m.group(1).lower()
    if label == 'splash':
        return 1
    if label == 'double-spread':
        return 1
    if label == 'tier':
        return 3
    return None  # irregular


def _parse_panel_breakdown(breakdown):
    """Parse 'p1:splash; p2:6-grid' into {1: 'splash', 2: '6-grid'}."""
    result = {}
    if not breakdown:
        return result
    for chunk in breakdown.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ':' not in chunk:
            continue
        page_part, tokens_part = chunk.split(':', 1)
        page_part = page_part.strip().lower()
        if not page_part.startswith('p'):
            continue
        try:
            page_num = int(page_part[1:])
        except ValueError:
            continue
        # Take the first token if multiple
        first_token = tokens_part.split('+')[0].strip()
        result[page_num] = first_token
    return result


def check_brief_fidelity(brief_row, script_text):
    """Return list of failure dicts, empty when the script honors the brief.

    Failure kind values: 'dialogue_missing', 'visual_keyword_missing',
    'panel_count_mismatch', 'page_turn_missing'.
    """
    failures = []
    parsed = parse_script(script_text)
    pages = parsed['pages']
    script_lower = script_text.lower()

    # 1. Dialogue contract: each non-empty segment of key_dialogue must
    # appear somewhere in the script. We use substring matching on the
    # full text since punctuation/formatting normalization is hard.
    key_dialogue = (brief_row.get('key_dialogue') or '').strip()
    if key_dialogue:
        # Split on semicolons; each chunk is a separate quote
        for chunk in key_dialogue.split(';'):
            quote = chunk.strip().strip('"').strip()
            if not quote:
                continue
            if quote.lower() not in script_lower:
                failures.append({
                    'kind': 'dialogue_missing',
                    'detail': quote,
                    'expected': quote,
                    'severity': 'high',
                })

    # 2. Visual keywords: each must appear in some panel's composition prose
    visual_kws = (brief_row.get('visual_keywords') or '').strip()
    if visual_kws:
        all_composition = ' '.join(
            panel['composition'] for page in pages for panel in page['panels']
        ).lower()
        for chunk in visual_kws.split(';'):
            kw = chunk.strip()
            if not kw:
                continue
            if kw.lower() not in all_composition:
                failures.append({
                    'kind': 'visual_keyword_missing',
                    'detail': kw,
                    'expected': kw,
                    'severity': 'medium',
                })

    # 3. Panel count per page must match brief panel_breakdown
    breakdown_map = _parse_panel_breakdown(brief_row.get('panel_breakdown') or '')
    for page in pages:
        expected_token = breakdown_map.get(page['number'])
        if not expected_token:
            continue
        expected_count = _panels_per_token(expected_token)
        if expected_count is None:
            continue  # irregular or unknown — skip count check
        actual_count = len(page['panels'])
        if actual_count != expected_count:
            failures.append({
                'kind': 'panel_count_mismatch',
                'detail': f"page {page['number']}: expected {expected_count} panels ({expected_token}), got {actual_count}",
                'expected': str(expected_count),
                'severity': 'medium',
            })

    # 4. Page-turn beats: each brief page_turn_beats entry must land on a page
    # whose first panel was tagged with the page-turn marker. We use a
    # lightweight heuristic: any brief page_turn_beats text means SOME page
    # in the script must carry the page-turn marker.
    page_turn_beats = (brief_row.get('page_turn_beats') or '').strip()
    if page_turn_beats:
        turn_pages = detect_page_turn_pages(script_text)
        if not turn_pages:
            failures.append({
                'kind': 'page_turn_missing',
                'detail': 'brief specifies page-turn beats but no page in the script carries the ⟵ PAGE-TURN REVEAL marker',
                'expected': page_turn_beats,
                'severity': 'high',
            })

    return failures
```

- [ ] **Step 4: Run tests to verify passing**

Run: `python3 -m pytest tests/test_script_format.py -v`
Expected: all tests pass.

Run: `python3 -m pytest tests/`
Expected: full suite still green.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/script_format.py tests/test_script_format.py
git commit -m "Add script_format parser and brief-fidelity checker"
git push
```

---

## Phase 2 — `prompts_gn.py`: drafting prompt builder

### Task 2: GN drafting prompt

**Files:**
- Create: `scripts/lib/python/storyforge/prompts_gn.py`
- Modify: `tests/test_medium.py` (add prompt tests)

The drafting prompt takes a scene's brief + intent + visual references + voice profile and produces a system prompt that teaches the model the script format and the brief contract.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_medium.py`:

```python
def test_prompts_gn_imports():
    from storyforge import prompts_gn
    assert hasattr(prompts_gn, 'build_drafting_prompt')


def test_drafting_prompt_includes_brief_columns():
    from storyforge.prompts_gn import build_drafting_prompt
    prompt = build_drafting_prompt(
        project_dir='/tmp/fake',
        scene_id='scene-a',
        scene_row={'id': 'scene-a', 'title': 'Test', 'target_pages': '4', 'pov': 'lucien'},
        intent_row={'function': 'setup', 'characters': 'lucien', 'on_stage': 'lucien'},
        brief_row={
            'goal': 'find the page',
            'conflict': 'the page is blank',
            'outcome': 'no-and',
            'key_dialogue': 'It always begins this way',
            'visual_keywords': 'blank parchment; trembling hand',
            'page_layout': 'splash p1, 4-grid p2',
            'panel_breakdown': 'p1:splash; p2:4-grid',
            'page_turn_beats': 'p2 reveal',
            'caption_strategy': 'journal voiceover',
        },
        character_visuals='Lucien: tall, stoop-shouldered, wire spectacles.',
        location_visuals='The Archive: amber lamplight, tall shelves.',
        voice_profile_text='caption_voice: journal-voiceover; lettering_style: loose-natural',
    )
    # Brief contract surfaces in the prompt
    assert 'find the page' in prompt
    assert 'the page is blank' in prompt
    assert 'It always begins this way' in prompt
    assert 'blank parchment' in prompt
    # Script format conventions are taught
    assert '## Page' in prompt
    assert '**Panel' in prompt
    assert 'CAPTION' in prompt
    # Target pages anchors output length
    assert '4' in prompt  # target pages
    # Visual references are present
    assert 'wire spectacles' in prompt or 'Wire spectacles' in prompt
    assert 'amber lamplight' in prompt
    # Caption strategy and voice are present
    assert 'journal voiceover' in prompt or 'journal-voiceover' in prompt
```

- [ ] **Step 2: Confirm failure**

Run: `python3 -m pytest tests/test_medium.py -v -k prompts_gn`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `prompts_gn.py`**

Create the module. Keep it under 200 lines. The prompt must:
- Teach the script format (## Page N — LAYOUT, **Panel N**, prefix vocabulary, ⟵ PAGE-TURN REVEAL marker)
- Surface the brief contract (goal/conflict/outcome, key_dialogue must appear as word balloons, visual_keywords must appear in panel composition, panel_breakdown determines the layout, page_turn_beats determine which pages carry the marker)
- Include character visual references and location visuals
- Include voice profile (caption_voice and lettering_style)
- Ask for the exact target_pages count

```python
"""Drafting prompts for graphic-novel mode.

Builds the per-scene system prompt that teaches the model to produce a
panel-by-panel script that honors the brief's contract.
"""


SCRIPT_FORMAT_INSTRUCTIONS = """\
Output format — required, strict:

  # Scene: {scene-id}

  **Target pages:** {N} | **Layout intent:** {brief.page_layout}

  ---

  ## Page 1 — LAYOUT-TAG

  **Panel 1** (size hint)
  Composition prose (1-3 sentences describing what the artist draws).

  - CAPTION: *Italicized caption text.*
  - CHARACTER-NAME: Spoken dialogue.

  **Panel 2** (size hint)
  ...

  ---

  ## Page 2 — LAYOUT-TAG
  ...

Rules:
  - Every page header is `## Page N — LAYOUT` where LAYOUT is one of:
    SPLASH, 6-PANEL GRID, 9-PANEL GRID, DOUBLE-SPREAD, TIER, IRREGULAR
    (or matching the brief's panel_breakdown tokens).
  - Every panel block starts with `**Panel N**` and an optional size hint.
  - Composition is 1-3 sentences of prose describing what the artist draws
    (Marvel-style for art, Full Script for layout).
  - Dialogue and captions use this fixed prefix vocabulary:
    CAPTION, {CHARACTER}, SFX, WHISPER, THOUGHT, OFF-PANEL
    where {CHARACTER} is the uppercase name from the on_stage list.
  - Pages tagged in the brief's page_turn_beats must include the marker
    ` ⟵ PAGE-TURN REVEAL` on the page header line.
  - Separate pages with `---` blank line dividers.
  - Output exactly the number of pages in target_pages.
"""


def _format_brief(brief_row):
    """Render the brief contract as a readable summary inside the prompt."""
    lines = []
    for key in ('goal', 'conflict', 'outcome', 'crisis', 'decision'):
        value = brief_row.get(key, '')
        if value:
            lines.append(f"- {key}: {value}")
    for key in ('key_dialogue', 'key_actions', 'visual_keywords',
                'page_layout', 'panel_breakdown', 'page_turn_beats',
                'caption_strategy', 'emotions', 'motifs', 'subtext'):
        value = brief_row.get(key, '')
        if value:
            lines.append(f"- {key}: {value}")
    return '\n'.join(lines)


def build_drafting_prompt(project_dir, scene_id, scene_row, intent_row,
                          brief_row, character_visuals, location_visuals,
                          voice_profile_text):
    """Build the system prompt that asks the model to draft a GN scene."""
    target_pages = scene_row.get('target_pages', '?')
    title = scene_row.get('title', scene_id)
    pov = scene_row.get('pov', '')
    location = scene_row.get('location', '')

    intent_summary = '\n'.join(
        f"- {k}: {v}" for k, v in intent_row.items() if v
    )
    brief_summary = _format_brief(brief_row)

    return f"""\
You are drafting a graphic-novel scene as a panel-by-panel script for an
artist to illustrate.

# Scene context

- id: {scene_id}
- title: {title}
- target_pages: {target_pages}  ← produce exactly this many pages
- pov: {pov}
- location: {location}

# Scene intent

{intent_summary}

# Scene brief — every column is a contract you must honor

{brief_summary}

Specifically:
  - Every entry in `key_dialogue` MUST appear verbatim (or near-verbatim)
    as a word-balloon line in the script.
  - Every entry in `visual_keywords` (semicolon-separated) MUST appear
    in some panel's composition prose.
  - The script's per-page panel structure MUST match `panel_breakdown`.
  - Pages tagged in `page_turn_beats` MUST carry the ⟵ PAGE-TURN REVEAL
    marker on their page header.
  - `caption_strategy` determines how narration is used (minimal,
    journal voiceover, omniscient, none, or as specified).

# Character visual references

{character_visuals or '(none provided)'}

# Location visual references

{location_visuals or '(none provided)'}

# Voice profile

{voice_profile_text or '(default)'}

{SCRIPT_FORMAT_INSTRUCTIONS}

Now write the script for scene `{scene_id}`. Produce exactly {target_pages}
pages. Begin with the H1 header `# Scene: {scene_id}` and follow the format
rules above. Do not write any commentary outside the script itself.
"""
```

- [ ] **Step 4: Verify**

Run: `python3 -m pytest tests/test_medium.py -v -k prompts_gn`
Expected: PASS.

Run: `python3 -m pytest tests/`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_gn.py tests/test_medium.py
git commit -m "Add prompts_gn drafting prompt builder"
git push
```

---

## Phase 3 — `cmd_write_gn.py`: drafting command

### Task 3: GN scene drafting command

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_write_gn.py`
- Create: `tests/test_cmd_write_gn.py`
- Modify: `tests/fixtures/test-project-gn/reference/scenes.csv` (set one scene's status to `briefed` instead of `briefed` — verify; if already `briefed`, no change)

Mirrors `cmd_write.py` for GN mode. Same CLI surface (positional scene IDs, `--scenes`, `--act`, `--from-seq`, `--dry-run`, `--parallel`, `--coaching`, `--interactive`, `--direct`). Same parallel wave drafting via `run_parallel`. Same scene-status lifecycle (briefed → drafted). Same brief-fidelity check after drafting.

- [ ] **Step 1: Inspect `cmd_write.py`**

Read `scripts/lib/python/storyforge/cmd_write.py` to understand the command's structure, parallel-execution pattern, and how it updates CSVs after drafting. Mirror its architecture.

- [ ] **Step 2: Write failing tests**

Create `tests/test_cmd_write_gn.py`:

```python
"""Tests for cmd_write_gn — GN scene drafting."""

import json
import os
import pytest

from storyforge.csv_cli import get_field


# A complete fake response: a 2-page script that honors a minimal brief
FAKE_SCRIPT = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
The cartographer at his desk. Blank parchment seen close, lamp glow.

- CAPTION: *The map remained blank.*
- CARTOGRAPHER: It always begins this way.

---

## Page 2 — 4-GRID ⟵ PAGE-TURN REVEAL

**Panel 1** (top-left)
Close on his trembling hand.

- CAPTION: *Forty years of practice.*

**Panel 2** (top-right)
The pen touches paper.

**Panel 3** (bottom-left)
A line appears.

- SFX: Scritch.

**Panel 4** (bottom-right)
He stares.

- CARTOGRAPHER: No.
"""


def _mock_invoke_to_file(prompt, model, log_file, **kwargs):
    """Drop-in replacement for api.invoke_to_file that writes a fake response."""
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    response = {
        'content': [{'type': 'text', 'text': FAKE_SCRIPT}],
        'usage': {
            'input_tokens': 200, 'output_tokens': 600,
            'cache_read_input_tokens': 0,
            'cache_creation_input_tokens': 0,
        },
    }
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def test_cmd_write_gn_drafts_a_scene(project_dir_gn, monkeypatch):
    """Running cmd_write_gn on a briefed scene drafts the script and updates CSVs."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import api, cmd_write_gn
    monkeypatch.setattr(api, 'invoke_to_file', _mock_invoke_to_file)

    cmd_write_gn.main(['the-blank-page', '--direct'])

    # Scene file was written
    scene_path = os.path.join(project_dir_gn, 'scenes', 'the-blank-page.md')
    assert os.path.isfile(scene_path), 'scene file should be written'
    content = open(scene_path).read()
    assert '## Page 1 — SPLASH' in content
    assert '## Page 2 — 4-GRID' in content
    assert '**Panel 1**' in content

    # CSV was updated: status, panel_count, page_count
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'drafted'
    assert get_field(scenes_csv, 'the-blank-page', 'panel_count') == '5'
    assert get_field(scenes_csv, 'the-blank-page', 'page_count') == '2'


def test_cmd_write_gn_dry_run_does_not_call_api(project_dir_gn, monkeypatch):
    """--dry-run prints the prompt without invoking the API."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import api
    calls = []

    def fail_on_call(*args, **kwargs):
        calls.append(args)
        raise AssertionError('API should not be called in dry-run')

    monkeypatch.setattr(api, 'invoke_to_file', fail_on_call)
    from storyforge import cmd_write_gn
    cmd_write_gn.main(['the-blank-page', '--dry-run'])
    assert calls == []


def test_cmd_write_gn_skips_already_drafted_scenes(project_dir_gn, monkeypatch):
    """Scenes with status='drafted' are skipped unless --force is set."""
    # Set the scene to drafted
    from storyforge.csv_cli import update_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'the-blank-page', 'status', 'drafted')

    monkeypatch.chdir(project_dir_gn)
    from storyforge import api, cmd_write_gn
    calls = []

    def track_call(*args, **kwargs):
        calls.append(args)
        return _mock_invoke_to_file(*args, **kwargs)

    monkeypatch.setattr(api, 'invoke_to_file', track_call)
    cmd_write_gn.main(['the-blank-page', '--direct'])
    assert calls == [], 'should not draft an already-drafted scene without --force'
```

- [ ] **Step 3: Confirm failure**

Run: `python3 -m pytest tests/test_cmd_write_gn.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement `cmd_write_gn.py`**

Mirror `cmd_write.py`. Key parts:

```python
"""storyforge write (graphic-novel mode) — Autonomous panel-script drafting.

Drafts panel scripts per scene. Same CLI as the novel mode `write` command
but routed to here when project.medium == 'graphic-novel'. Output goes to
scenes/{id}.md as a structured panel script.

Usage (identical to novel-mode write):
    storyforge write
    storyforge write act1-sc01
    storyforge write --scenes a,b,c
    storyforge write --act 2
    storyforge write --dry-run scene-id
"""

import argparse
import os
import sys

from storyforge.common import (
    detect_project_root, log, set_log_file, select_model,
    install_signal_handlers, get_medium,
)
from storyforge.runner import run_parallel
from storyforge.csv_cli import get_field, get_row, list_ids, update_field
from storyforge.scene_filter import build_scene_list, apply_scene_filter
from storyforge.script_format import (
    count_pages, count_panels, check_brief_fidelity,
)
from storyforge.api import invoke_to_file, extract_text_from_file
from storyforge.costs import log_operation
from storyforge.prompts_gn import build_drafting_prompt


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='storyforge write (gn)')
    parser.add_argument('positional', nargs='*', default=[])
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--direct', action='store_true')
    parser.add_argument('--scenes', type=str, default=None)
    parser.add_argument('--act', '--part', type=str, default=None)
    parser.add_argument('--from-seq', type=str, default=None)
    parser.add_argument('--parallel', type=int, default=1)
    return parser.parse_args(argv)


def _build_visual_refs(project_dir, character_ids, location):
    """Pull character bible Visual sections and world bible visual notes."""
    # Minimal MVP: read the bible files and include their full content. A
    # later iteration can extract just the relevant sections.
    ref_dir = os.path.join(project_dir, 'reference')
    chars_path = os.path.join(ref_dir, 'character-bible.md')
    world_path = os.path.join(ref_dir, 'world-bible.md')
    chars = open(chars_path).read() if os.path.isfile(chars_path) else ''
    world = open(world_path).read() if os.path.isfile(world_path) else ''
    return chars, world


def _draft_one_scene(args_tuple):
    """Worker: draft one scene. Returns (scene_id, result_dict)."""
    scene_id, project_dir, force, dry_run, direct, model = args_tuple
    ref_dir = os.path.join(project_dir, 'reference')
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')

    if not force:
        status = get_field(scenes_csv, scene_id, 'status')
        if status == 'drafted':
            return scene_id, {'skipped': True, 'reason': 'already drafted'}

    scene_row = get_row(scenes_csv, scene_id)
    intent_row = get_row(os.path.join(ref_dir, 'scene-intent.csv'), scene_id)
    brief_row = get_row(os.path.join(ref_dir, 'scene-briefs.csv'), scene_id)
    if not scene_row or not brief_row:
        return scene_id, {'error': 'missing scene or brief'}

    char_visuals, loc_visuals = _build_visual_refs(
        project_dir, intent_row.get('on_stage', ''), scene_row.get('location', ''),
    )
    voice_path = os.path.join(ref_dir, 'voice-profile.csv')
    voice_text = open(voice_path).read() if os.path.isfile(voice_path) else ''

    prompt = build_drafting_prompt(
        project_dir, scene_id, scene_row, intent_row, brief_row,
        char_visuals, loc_visuals, voice_text,
    )

    if dry_run:
        return scene_id, {'dry_run': True, 'prompt': prompt}

    log_dir = os.path.join(project_dir, 'working', 'logs', 'write-gn')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'{scene_id}.json')

    try:
        invoke_to_file(prompt, model, log_file, max_tokens=8192)
    except Exception as e:
        return scene_id, {'error': f'API call failed: {e}'}

    script_text = extract_text_from_file(log_file)
    if not script_text:
        return scene_id, {'error': 'empty API response'}

    # Write the scene file
    scene_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    os.makedirs(os.path.dirname(scene_path), exist_ok=True)
    with open(scene_path, 'w') as f:
        f.write(script_text)

    # Update CSV
    pages = count_pages(script_text)
    panels = count_panels(script_text)
    update_field(scenes_csv, scene_id, 'page_count', str(pages))
    update_field(scenes_csv, scene_id, 'panel_count', str(panels))
    update_field(scenes_csv, scene_id, 'status', 'drafted')

    # Brief-fidelity check
    failures = check_brief_fidelity(brief_row, script_text)
    if failures:
        log(f"  {scene_id}: drafted with {len(failures)} fidelity warnings")
        for f in failures:
            log(f"    [{f['severity']}] {f['kind']}: {f['detail']}")

    # Cost tracking
    log_operation(project_dir, 'write-gn', model, scene_id=scene_id)

    return scene_id, {
        'drafted': True, 'pages': pages, 'panels': panels,
        'fidelity_failures': len(failures),
    }


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()

    project_dir = detect_project_root()
    if get_medium(project_dir) != 'graphic-novel':
        log("ERROR: cmd_write_gn invoked on a non-graphic-novel project.")
        sys.exit(1)

    ref_dir = os.path.join(project_dir, 'reference')
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')

    log_dir = os.path.join(project_dir, 'working', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    set_log_file(os.path.join(log_dir, 'write-gn-log.txt'))

    # Resolve scene IDs
    all_ids = build_scene_list(scenes_csv)
    if args.positional:
        ids = args.positional
    elif args.scenes:
        ids = [s.strip() for s in args.scenes.split(',') if s.strip()]
    elif args.act:
        ids = apply_scene_filter(scenes_csv, all_ids, 'act', args.act)
    elif args.from_seq:
        ids = apply_scene_filter(scenes_csv, all_ids, 'from-seq', args.from_seq)
    else:
        ids = all_ids

    if not ids:
        log("No scenes to draft.")
        return

    model = select_model('drafting')
    log(f"Drafting {len(ids)} GN scenes with model {model}")

    work = [(sid, project_dir, args.force, args.dry_run, args.direct, model)
            for sid in ids]

    if args.parallel > 1 and not args.dry_run:
        results = run_parallel(work, _draft_one_scene, max_workers=args.parallel,
                               label='scene')
    else:
        results = [_draft_one_scene(item) for item in work]

    # Report
    for sid, result in results:
        if args.dry_run and result.get('dry_run'):
            print(f"===== DRY RUN: {sid} =====")
            print(result['prompt'])
            print(f"===== END DRY RUN: {sid} =====")
        elif result.get('skipped'):
            log(f"{sid}: skipped ({result['reason']})")
        elif result.get('error'):
            log(f"{sid}: ERROR — {result['error']}")
        elif result.get('drafted'):
            log(f"{sid}: drafted {result['pages']} pages, {result['panels']} panels"
                + (f", {result['fidelity_failures']} fidelity warnings"
                   if result['fidelity_failures'] else ''))


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Verify**

Run: `python3 -m pytest tests/test_cmd_write_gn.py -v`
Expected: all passing.

Run: `python3 -m pytest tests/`
Expected: full suite green.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_write_gn.py tests/test_cmd_write_gn.py
git commit -m "Add cmd_write_gn for graphic-novel scene drafting"
git push
```

---

## Phase 4 — `cmd_script_package.py`: production bundle

### Task 4: GN artist handoff command

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_script_package.py`
- Create: `tests/test_cmd_script_package.py`

Assembles all drafted GN scenes into the artist deliverable. Mirrors `cmd_assemble.py` for the chapter-mapping concept but produces different output.

#### Output bundle

```
manuscript/
├── script.md              — assembled script with global page numbering
├── visual-references.md   — character + location refs extracted from bibles
├── chapter-map.md         — readable chapter/issue breakdown
└── handoff-readme.md      — auto-generated overview of script conventions
```

PDF is optional (skip if weasyprint/pandoc not available; just produce markdown).

- [ ] **Step 1: Write failing tests**

Create `tests/test_cmd_script_package.py`:

```python
"""Tests for cmd_script_package — GN artist handoff bundle."""

import os
import pytest


SAMPLE_SCRIPT_A = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1**
Comp.

- CAPTION: *Cap A.*

---

## Page 2 — 4-GRID

**Panel 1**
Comp.
"""

SAMPLE_SCRIPT_B = """\
# Scene: shadows-arrive

**Target pages:** 1 | **Layout intent:** 6-grid p1

---

## Page 1 — 6-GRID

**Panel 1**
Comp.

- CAPTION: *Cap B.*
"""


def _setup_drafted_scenes(project_dir_gn):
    """Write fake drafted scenes and update CSV statuses."""
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'the-blank-page.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_A)
    with open(os.path.join(scenes_dir, 'shadows-arrive.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_B)
    from storyforge.csv_cli import update_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'the-blank-page', 'status', 'drafted')
    update_field(scenes_csv, 'shadows-arrive', 'status', 'drafted')


def _setup_chapter_map(project_dir_gn):
    """Write a minimal chapter-map.csv mapping scenes 1-2 into chapter 1."""
    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|the-blank-page;shadows-arrive\n')


def test_script_package_produces_bundle(project_dir_gn, monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    bundle = os.path.join(project_dir_gn, 'manuscript')
    assert os.path.isfile(os.path.join(bundle, 'script.md'))
    assert os.path.isfile(os.path.join(bundle, 'visual-references.md'))
    assert os.path.isfile(os.path.join(bundle, 'chapter-map.md'))
    assert os.path.isfile(os.path.join(bundle, 'handoff-readme.md'))


def test_script_package_global_page_numbering(project_dir_gn, monkeypatch):
    """The assembled script renumbers pages globally across scenes."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    script_md = open(os.path.join(project_dir_gn, 'manuscript', 'script.md')).read()
    # Scene A has 2 pages, scene B has 1. Globally renumbered: A pages 1-2, B page 3.
    assert '## Page 1 —' in script_md
    assert '## Page 2 —' in script_md
    assert '## Page 3 —' in script_md


def test_script_package_visual_references_extracted(project_dir_gn, monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    refs = open(os.path.join(project_dir_gn, 'manuscript', 'visual-references.md')).read()
    # Cartographer Visual section content from the fixture
    assert 'Cartographer' in refs
    assert 'spectacles' in refs.lower() or 'silhouette' in refs.lower()
    # World bible content
    assert 'study' in refs.lower() or 'lamplight' in refs.lower()


def test_script_package_fails_when_no_chapter_map(project_dir_gn, monkeypatch):
    """Missing chapter-map.csv is a clear error."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    # Note: no chapter map
    from storyforge import cmd_script_package
    with pytest.raises(SystemExit) as exc_info:
        cmd_script_package.main([])
    assert exc_info.value.code != 0
```

- [ ] **Step 2: Confirm failure**

Run: `python3 -m pytest tests/test_cmd_script_package.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `cmd_script_package.py`**

Key responsibilities:
- Read chapter-map.csv (require it; clear error if missing)
- Read scenes.csv to validate every scene in the map is `drafted`
- Concatenate scene markdown files in chapter order
- Globally renumber `## Page N` references so they restart from 1 at the start of the assembled script
- Extract character "Visual" sections from character-bible.md and visual notes from world-bible.md into visual-references.md
- Render the chapter map as readable chapter-map.md
- Auto-generate handoff-readme.md explaining the script format

```python
"""storyforge assemble (graphic-novel mode) — Artist handoff bundle.

Produces manuscript/{script.md,visual-references.md,chapter-map.md,handoff-readme.md}.
"""

import argparse
import os
import re
import sys

from storyforge.common import detect_project_root, log, install_signal_handlers, get_medium


def parse_args(argv):
    p = argparse.ArgumentParser(prog='storyforge assemble (gn)')
    p.add_argument('--format', default='markdown',
                   help='Output format: markdown (default), pdf, all')
    return p.parse_args(argv)


def _read_chapter_map(path):
    """Return list of {chapter, title, heading, scenes:[id,...]}."""
    if not os.path.isfile(path):
        return None
    chapters = []
    with open(path) as f:
        header = next(f).strip().split('|')
        for line in f:
            fields = line.rstrip('\n').split('|')
            row = dict(zip(header, fields))
            row['scenes'] = [s.strip() for s in row.get('scenes', '').split(';') if s.strip()]
            chapters.append(row)
    return chapters


PAGE_HEADER_RE = re.compile(r'^## Page (\d+)\s+—\s+', re.MULTILINE)


def _renumber_pages(scene_text, start):
    """Renumber `## Page N` headers to start from `start`.

    Returns (renumbered_text, next_start).
    """
    counter = [start]
    def repl(m):
        new_num = counter[0]
        counter[0] += 1
        return m.group(0).replace(f'Page {m.group(1)}', f'Page {new_num}', 1)
    new_text = PAGE_HEADER_RE.sub(repl, scene_text)
    return new_text, counter[0]


def _assemble_script(project_dir, chapters, title):
    """Concatenate scenes in chapter order with global page numbering."""
    out = [f"# {title} — Artist Script\n"]
    out.append("_Auto-generated. See handoff-readme.md for format conventions._\n\n")

    global_page = 1
    total_panels = 0
    for chap in chapters:
        out.append(f"\n# Chapter {chap['chapter']} — {chap['title']}\n")
        for sid in chap['scenes']:
            scene_path = os.path.join(project_dir, 'scenes', f'{sid}.md')
            if not os.path.isfile(scene_path):
                out.append(f"\n*[scene {sid} not found]*\n")
                continue
            text = open(scene_path).read()
            renumbered, global_page = _renumber_pages(text, global_page)
            out.append(renumbered)
            out.append('\n')
            from storyforge.script_format import count_panels
            total_panels += count_panels(text)

    summary = (
        f"# {title} — Artist Script\n\n"
        f"**Total pages:** {global_page - 1} | **Total panels:** {total_panels}\n\n"
    )
    return summary + '\n'.join(out[1:])


def _extract_visual_references(project_dir, title):
    """Pull character Visual sections + world-bible visual notes."""
    parts = [f"# {title} — Visual References\n",
             "_For the artist. Pin to your drawing table._\n"]

    ref_dir = os.path.join(project_dir, 'reference')
    char_path = os.path.join(ref_dir, 'character-bible.md')
    if os.path.isfile(char_path):
        parts.append('\n## Characters\n')
        content = open(char_path).read()
        # Extract per-character sections that contain a "### Visual" subsection
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        for sec in sections[1:]:
            if '### Visual' in sec or '### visual' in sec.lower():
                parts.append('## ' + sec.strip() + '\n')

    world_path = os.path.join(ref_dir, 'world-bible.md')
    if os.path.isfile(world_path):
        parts.append('\n## Settings\n')
        content = open(world_path).read()
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        for sec in sections[1:]:
            if '### Visual' in sec or '### visual' in sec.lower():
                parts.append('## ' + sec.strip() + '\n')

    return '\n'.join(parts)


def _render_chapter_map(chapters, title):
    out = [f"# {title} — Chapter Map\n"]
    for chap in chapters:
        out.append(f"\n## Chapter {chap['chapter']} — {chap['title']}\n")
        out.append(f"Scenes: {', '.join(chap['scenes'])}\n")
    return '\n'.join(out)


HANDOFF_README = """\
# Artist Handoff — {title}

This bundle contains everything you need to illustrate the graphic novel.

## Files

- `script.md` — The complete panel-by-panel script. Pages are globally numbered.
- `visual-references.md` — Character and location reference notes. Pin these up.
- `chapter-map.md` — How scenes group into chapters/issues.

## Script format

Each scene begins with `# Scene: {{scene-id}}`.

Each page begins with `## Page N — LAYOUT` where LAYOUT is one of:
- `SPLASH` — full-page single panel
- `6-PANEL GRID`, `9-PANEL GRID`, etc. — grid layouts
- `DOUBLE-SPREAD` — two-page spread
- `TIER` — horizontal strip
- `IRREGULAR` — non-grid layout (artist's discretion)

Each panel block starts with `**Panel N**` and may include a size hint in parens.

Panel composition is described in 1-3 sentences of prose. Interpret freely
for art direction; layout and panel count are authorial.

## Dialogue prefix vocabulary

- `CAPTION:` — Narration or omniscient caption box
- `{{CHARACTER NAME}}:` — Spoken word balloon
- `SFX:` — Sound effect (lettered as part of the art)
- `WHISPER:` — Whispered dialogue (smaller, italic balloon)
- `THOUGHT:` — Thought bubble
- `OFF-PANEL:` — Speaker not visible in the panel

## Page-turn beats

Any page header ending with ` ⟵ PAGE-TURN REVEAL` marks a beat that should
land as a recto-to-verso reveal. Try to ensure the prior page is on the
left (verso), so the reader physically turns the page into the moment.

## Questions

Reach out to the author with any questions about the script.
"""


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    install_signal_handlers()

    project_dir = detect_project_root()
    if get_medium(project_dir) != 'graphic-novel':
        log("ERROR: cmd_script_package invoked on a non-graphic-novel project.")
        sys.exit(1)

    chapter_map_path = os.path.join(project_dir, 'reference', 'chapter-map.csv')
    chapters = _read_chapter_map(chapter_map_path)
    if not chapters:
        log("ERROR: No reference/chapter-map.csv. Run the script-package skill "
            "to map scenes to chapters before assembling.")
        sys.exit(1)

    # Read project title
    from storyforge.common import read_yaml_field
    title = read_yaml_field('project.title', project_dir) or 'Untitled'

    bundle_dir = os.path.join(project_dir, 'manuscript')
    os.makedirs(bundle_dir, exist_ok=True)

    # script.md
    script_md = _assemble_script(project_dir, chapters, title)
    with open(os.path.join(bundle_dir, 'script.md'), 'w') as f:
        f.write(script_md)
    log(f"  manuscript/script.md")

    # visual-references.md
    refs = _extract_visual_references(project_dir, title)
    with open(os.path.join(bundle_dir, 'visual-references.md'), 'w') as f:
        f.write(refs)
    log(f"  manuscript/visual-references.md")

    # chapter-map.md
    cm = _render_chapter_map(chapters, title)
    with open(os.path.join(bundle_dir, 'chapter-map.md'), 'w') as f:
        f.write(cm)
    log(f"  manuscript/chapter-map.md")

    # handoff-readme.md
    readme = HANDOFF_README.format(title=title)
    with open(os.path.join(bundle_dir, 'handoff-readme.md'), 'w') as f:
        f.write(readme)
    log(f"  manuscript/handoff-readme.md")

    log("Script package complete.")


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Verify**

Run: `python3 -m pytest tests/test_cmd_script_package.py -v`
Expected: all passing.

Run: `python3 -m pytest tests/`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_script_package.py tests/test_cmd_script_package.py
git commit -m "Add cmd_script_package for GN artist handoff bundle"
git push
```

---

## Phase 5 — `script-package` skill

### Task 5: Interactive script-package skill

**Files:**
- Create: `skills/script-package/SKILL.md`

Mirror the `produce` skill but for GN mode. Walk the author through:
1. Confirming chapter/issue structure (reuses `reference/chapter-map.csv`)
2. Optional production settings under `storyforge.yaml:script_package` (artist_name, trim_size, page_format)
3. Calling `./storyforge assemble`

- [ ] **Step 1: Read the existing `produce` skill for structure**

Read `skills/produce/SKILL.md` to mirror its structure. Adapt:
- Title and description
- Chapter-mapping logic (same as novel — `chapter|title|heading|scenes`)
- Production settings (different key: `script_package` instead of `production`)
- Final command: `./storyforge assemble` (the dispatcher routes to cmd_script_package in GN mode)

- [ ] **Step 2: Write the skill**

Create `skills/script-package/SKILL.md` with frontmatter:

```yaml
---
name: script-package
description: Assemble a graphic-novel project into an artist handoff bundle — panel script with global page numbering, visual references, chapter map, and a readme. Use when the GN author wants to package the book for an illustrator (human or AI).
---
```

Write the full skill body (~150-250 lines) covering:
- Locating the plugin (standard preamble)
- Reading project state (storyforge.yaml, scenes.csv, chapter-map.csv if present)
- Asserting `project.medium == 'graphic-novel'` (otherwise redirect to the `produce` skill)
- First-time mode: propose chapter mapping based on scene seq/part/POV groupings, ask for confirmation
- Update mode: modify an existing chapter map
- Assembly mode: invoke `./storyforge assemble`
- Coaching level adaptation (full=propose chapter structure; coach=ask guiding questions; strict=just collect the author's groupings)
- Commit and push after every deliverable

- [ ] **Step 3: Commit**

```bash
git add skills/script-package/SKILL.md
git commit -m "Add script-package skill for GN artist handoff"
git push
```

---

## Phase 6 — Dispatcher routing

### Task 6: Route `write` and `assemble` to GN versions

**Files:**
- Modify: `scripts/lib/python/storyforge/__main__.py`
- Modify: `tests/test_medium.py`

Remove `write` and `assemble` from `GN_UNSUPPORTED_COMMANDS`. Add medium-aware routing so that the right module is picked.

- [ ] **Step 1: Update the dispatcher**

In `scripts/lib/python/storyforge/__main__.py`:

```python
# Before:
GN_UNSUPPORTED_COMMANDS = frozenset({
    'write', 'evaluate', 'score', 'revise', 'assemble',
    'publish', 'annotations', 'extract', 'repetition', 'enrich',
})

# After:
GN_UNSUPPORTED_COMMANDS = frozenset({
    'evaluate', 'score', 'revise',
    'publish', 'annotations', 'extract', 'repetition', 'enrich',
})

# Commands that route to a different module based on project.medium
GN_ROUTED_COMMANDS = {
    'write': 'storyforge.cmd_write_gn',
    'assemble': 'storyforge.cmd_script_package',
}
```

In the dispatcher, after the GN-unsupported check, add:

```python
# Route certain commands to GN-specific modules
if cmd in GN_ROUTED_COMMANDS:
    try:
        from storyforge.common import detect_project_root, get_medium
        project_dir = detect_project_root()
        if get_medium(project_dir) == 'graphic-novel':
            module_path = GN_ROUTED_COMMANDS[cmd]
            sys.argv = [f'storyforge {cmd}'] + sys.argv[2:]
            module = importlib.import_module(module_path)
            module.main(sys.argv[1:])
            return
    except (FileNotFoundError, OSError):
        pass  # Not in a project, fall through to normal dispatch
```

- [ ] **Step 2: Update test parametrization**

In `tests/test_medium.py`, the `test_dispatcher_blocks_unsupported_commands_in_gn_mode` parametrize list currently includes `write` and `assemble`. Remove them.

Add new tests that verify routing:

```python
def test_dispatcher_routes_write_to_gn_in_gn_mode(project_dir_gn, monkeypatch):
    """In GN mode, `./storyforge write` invokes cmd_write_gn."""
    monkeypatch.chdir(project_dir_gn)
    monkeypatch.setattr('sys.argv', ['storyforge', 'write', '--dry-run',
                                      'the-blank-page'])
    # Stub API
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file',
                        lambda *a, **kw: pytest.fail('should not be called in dry-run'))

    called = []
    from storyforge import cmd_write_gn
    real_main = cmd_write_gn.main
    def track(*args, **kwargs):
        called.append(True)
        return real_main(*args, **kwargs)
    monkeypatch.setattr(cmd_write_gn, 'main', track)

    from storyforge.__main__ import main
    main()
    assert called, 'cmd_write_gn.main should be called for write in GN mode'


def test_dispatcher_routes_assemble_to_script_package_in_gn_mode(project_dir_gn, monkeypatch):
    """In GN mode, `./storyforge assemble` invokes cmd_script_package."""
    monkeypatch.chdir(project_dir_gn)
    monkeypatch.setattr('sys.argv', ['storyforge', 'assemble', '--format', 'markdown'])

    called = []
    from storyforge import cmd_script_package
    real_main = cmd_script_package.main
    def track(*args, **kwargs):
        called.append(True)
        # Don't actually run — just verify routing
        raise SystemExit(0)
    monkeypatch.setattr(cmd_script_package, 'main', track)

    from storyforge.__main__ import main
    with pytest.raises(SystemExit):
        main()
    assert called, 'cmd_script_package.main should be called for assemble in GN mode'


def test_dispatcher_routes_write_to_novel_in_novel_mode(project_dir, monkeypatch):
    """In novel mode, `./storyforge write` invokes cmd_write (not cmd_write_gn)."""
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr('sys.argv', ['storyforge', 'write', '--help'])

    called = {'novel': False, 'gn': False}
    from storyforge import cmd_write, cmd_write_gn
    monkeypatch.setattr(cmd_write, 'main',
                        lambda *a, **kw: (called.update(novel=True), sys.exit(0))[-1])
    monkeypatch.setattr(cmd_write_gn, 'main',
                        lambda *a, **kw: called.update(gn=True))

    from storyforge.__main__ import main
    try:
        main()
    except SystemExit:
        pass
    assert called['novel'] and not called['gn']
```

- [ ] **Step 3: Verify**

Run: `python3 -m pytest tests/test_medium.py -v -k "dispatcher"`
Expected: all passing (including the updated parametrize list).

Run: `python3 -m pytest tests/`
Expected: full suite green.

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/__main__.py tests/test_medium.py
git commit -m "Route write and assemble to GN modules when medium is graphic-novel"
git push
```

---

## Phase 7 — Integration test, version bump, CLAUDE.md update

### Task 7: End-to-end integration test

**Files:**
- Create: `tests/test_pipeline_gn.py`

Test the full pipeline on the GN fixture: starting from briefed scenes, run `write`, then `assemble` (with a chapter map), then verify the bundle output. All API calls mocked.

- [ ] **Step 1: Write the integration test**

```python
"""Integration test: full GN pipeline from briefs → write → script-package."""

import json
import os

import pytest


PIPELINE_SCRIPTS = {
    'the-blank-page': """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1**
Cartographer at desk. Blank parchment.

- CAPTION: *The map remained blank.*

---

## Page 2 — 4-GRID

**Panel 1**
Hand.

**Panel 2**
Pen.

**Panel 3**
Line.

**Panel 4**
Stare.
""",
    'shadows-arrive': """\
# Scene: shadows-arrive

**Target pages:** 1 | **Layout intent:** 6-grid

---

## Page 1 — 6-GRID

**Panel 1**
Door.

**Panel 2**
Shadow.

**Panel 3**
Lamp.

**Panel 4**
Cartographer turns.

**Panel 5**
Listens.

**Panel 6**
Stands.
""",
    'the-first-mark': """\
# Scene: the-first-mark

**Target pages:** 1 | **Layout intent:** 3-tier

---

## Page 1 — 3-TIER

**Panel 1**
Returns to desk.

**Panel 2**
Sees filled page.

**Panel 3**
Reaches.
""",
}


def _fake_invoke_to_file_for_pipeline(prompt, model, log_file, **kwargs):
    """Return a script that matches whichever scene is currently being drafted.

    We sniff the scene id from the prompt's 'id:' line.
    """
    scene_id = 'the-blank-page'  # default
    for sid in PIPELINE_SCRIPTS:
        if f'id: {sid}' in prompt:
            scene_id = sid
            break
    text = PIPELINE_SCRIPTS[scene_id]
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    response = {
        'content': [{'type': 'text', 'text': text}],
        'usage': {'input_tokens': 100, 'output_tokens': 300,
                  'cache_read_input_tokens': 0,
                  'cache_creation_input_tokens': 0},
    }
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def test_full_gn_pipeline(project_dir_gn, monkeypatch):
    """Run write → assemble on the GN fixture and verify the bundle."""
    monkeypatch.chdir(project_dir_gn)

    # Stub the API
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', _fake_invoke_to_file_for_pipeline)

    # Write a chapter map
    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|the-blank-page;shadows-arrive;the-first-mark\n')

    # Run write (via the dispatcher to ensure routing works)
    monkeypatch.setattr('sys.argv', ['storyforge', 'write', '--direct'])
    from storyforge.__main__ import main as dispatcher_main
    dispatcher_main()

    # Verify all 3 scenes drafted
    from storyforge.csv_cli import get_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    for sid in PIPELINE_SCRIPTS:
        assert get_field(scenes_csv, sid, 'status') == 'drafted', f'{sid} not drafted'
        scene_path = os.path.join(project_dir_gn, 'scenes', f'{sid}.md')
        assert os.path.isfile(scene_path), f'{sid} script not written'

    # Run assemble
    monkeypatch.setattr('sys.argv', ['storyforge', 'assemble'])
    dispatcher_main()

    # Verify bundle
    bundle = os.path.join(project_dir_gn, 'manuscript')
    for filename in ('script.md', 'visual-references.md', 'chapter-map.md',
                     'handoff-readme.md'):
        path = os.path.join(bundle, filename)
        assert os.path.isfile(path), f'bundle missing {filename}'

    # script.md should have global page numbering: 2 + 1 + 1 = 4 pages
    script = open(os.path.join(bundle, 'script.md')).read()
    assert '## Page 1 —' in script
    assert '## Page 4 —' in script
```

- [ ] **Step 2: Run**

Run: `python3 -m pytest tests/test_pipeline_gn.py -v`
Expected: passes.

Run: `python3 -m pytest tests/`
Expected: full suite green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_gn.py
git commit -m "Add integration test for full GN pipeline (write + assemble)"
git push
```

### Task 8: Version bump and CLAUDE.md update

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Bump minor version**

Read `.claude-plugin/plugin.json`. Bump the minor version (1.19.0 → 1.20.0).

- [ ] **Step 2: Update CLAUDE.md**

In the "Graphic Novel Mode" section:
- Move `write` and `assemble` from "Not yet supported" to "Supported"
- Update text to reflect that drafting and production now work for GN projects

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json CLAUDE.md
git commit -m "Bump version to 1.20.0 — GN drafting + production live"
git push
```

### Task 9: Open the PR

- [ ] **Step 1: Open draft PR**

```bash
gh pr create --draft --title "GN drafting and artist handoff (Plan 2)" --body "$(cat <<'EOF'
## Summary

Implements Plan 2 of graphic-novel-mode support. Adds drafting (panel
scripts), production (artist handoff bundle), and routes `./storyforge
write` and `./storyforge assemble` to the GN modules in GN mode.

Closes #208.

## Design

- Spec: `docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md`
- Plan: `docs/superpowers/plans/2026-05-21-graphic-novel-drafting-production.md`

## What's new

- `script_format.py` — panel-script parser and brief-fidelity check
- `prompts_gn.py` — drafting prompt builder
- `cmd_write_gn.py` — autonomous GN drafting (parallel waves, fidelity check)
- `cmd_script_package.py` — artist handoff bundle (script.md + visual refs + chapter map + readme)
- `skills/script-package/SKILL.md` — interactive production skill
- Dispatcher now routes `write` and `assemble` by medium

## Tests

- `tests/test_script_format.py` — parser and fidelity check
- `tests/test_cmd_write_gn.py` — drafting (API mocked)
- `tests/test_cmd_script_package.py` — bundle generation
- `tests/test_pipeline_gn.py` — full integration test

## Test plan

- [x] `python3 -m pytest tests/` — all passing
- [x] Integration test exercises full pipeline (write → assemble) end-to-end

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** Every item in issue #208 has a task: script_format (Task 1), prompts_gn (Task 2), cmd_write_gn (Task 3), cmd_script_package (Task 4), script-package skill (Task 5), dispatcher routing (Task 6), integration test (Task 7), version + docs (Task 8), PR (Task 9).
- **Type/name consistency:** `parse_script` returns dict with `pages`, `page_count`, `total_panels`. `check_brief_fidelity` returns list of dicts with keys `kind`, `detail`, `expected`, `severity`. `_draft_one_scene` returns `(scene_id, result_dict)`. The handoff bundle is at `manuscript/`.
- **Sequencing:** Task 1 (script_format) is foundational; Tasks 2-4 depend on it. Task 6 (dispatcher) depends on Tasks 3-4. Task 7 (integration) depends on all earlier code tasks. Task 8 happens last along with the PR.
- **Out of scope (followups already tracked):** GN evaluation/scoring/revision (#209), canonical layout research (#210), style guide doc (#211), AI ref thumbnails (#212), GN extraction (#213), GN cover (#214), GN publish/annotations (#215), medium migration (#216).
