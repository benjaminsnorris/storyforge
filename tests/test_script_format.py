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


def test_speaker_is_none_for_known_prefixes_and_set_for_characters():
    """KNOWN_PREFIXES entries have speaker=None; character names populate speaker."""
    result = parse_script(SAMPLE_SCRIPT)
    all_dialogue = [d for page in result['pages']
                    for panel in page['panels']
                    for d in panel['dialogue']]
    captions = [d for d in all_dialogue if d['prefix'] == 'CAPTION']
    sfx = [d for d in all_dialogue if d['prefix'] == 'SFX']
    chars = [d for d in all_dialogue if d['prefix'] == 'CARTOGRAPHER']
    assert captions and all(d['speaker'] is None for d in captions)
    assert sfx and all(d['speaker'] is None for d in sfx)
    assert chars and all(d['speaker'] == 'CARTOGRAPHER' for d in chars)


def test_dialogue_prefix_rejects_too_short_words():
    """Bullet lines starting with single-letter all-caps tokens are not parsed as dialogue."""
    script = (
        '## Page 1 — SPLASH\n\n'
        '**Panel 1**\n'
        'Something happens.\n\n'
        '- A: not dialogue\n'
        '- NOTE: also not a speaker (would be polluting if not for fix)\n'
    )
    result = parse_script(script)
    panel = result['pages'][0]['panels'][0]
    # After fix: 'A' rejected (single char), 'NOTE' accepted (≥2 chars).
    # The "NOTE" line still parses as dialogue under the relaxed contract,
    # because the regex only enforces character minimums, not prefix
    # whitelist. Document this and ensure 'A:' is filtered out.
    speakers = [d['prefix'] for d in panel['dialogue']]
    assert 'A' not in speakers, 'single-letter prefix should not match'
