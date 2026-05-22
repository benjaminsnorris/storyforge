"""Tests for scoring_gn: six deterministic GN craft scorers."""

import statistics
import pytest

from storyforge.script_format import parse_script
from storyforge.scoring_gn import (
    score_brief_fidelity,
    score_panel_density,
    score_dialogue_compression,
    score_layout_rhythm,
    score_caption_economy,
    score_panel_composition_depth,
    score_scene,
    score_project,
    SCORERS,
    PRINCIPLES,
    CAPTION_STRATEGY_TARGETS,
)


# ---------------------------------------------------------------------------
# Reusable sample scripts
# ---------------------------------------------------------------------------

# A well-formed 2-page script: balanced panels, short dialogue, good composition
GOOD_SCRIPT = """\
# Scene: test

**Target pages:** 2

---

## Page 1 — SPLASH

**Panel 1**
The cartographer at his desk in lamplit study. Blank parchment before him. Shadows along the bookshelves filling the room.

- CAPTION: *The map remained blank.*

---

## Page 2 — 4-GRID

**Panel 1**
Close on his trembling hand resting on the table edge.

- CAPTION: *Forty years of practice and still this fear.*

**Panel 2**
Brush touches paper with a faint quiver visible.

**Panel 3**
A single line appears across the white expanse.

- SFX: Scritch.

**Panel 4**
He stares at the line growing darker.

- CARTOGRAPHER: No.
"""

# A dense 1-page script with many panels for testing density edge cases
DENSE_ONE_PAGE = """\
## Page 1 — 10-GRID

**Panel 1**
A face.

**Panel 2**
An eye.

**Panel 3**
A mouth.

**Panel 4**
A hand.

**Panel 5**
A foot.

**Panel 6**
A door.

**Panel 7**
A window.

**Panel 8**
A clock.

**Panel 9**
A key.

**Panel 10**
Darkness.
"""

# A script with perfectly uniform panel counts (triggers layout_too_uniform)
UNIFORM_SCRIPT = """\
## Page 1 — 4-GRID

**Panel 1**
Scene establishing the market square in full afternoon light.

**Panel 2**
Two merchants arguing over a price near the spice stalls.

**Panel 3**
A child watches from the alley entrance beside a cart.

**Panel 4**
The cartographer moves through the crowd unnoticed by all.

---

## Page 2 — 4-GRID

**Panel 1**
Interior of the map shop with rolled charts on every shelf.

**Panel 2**
The owner behind the counter examining a newly arrived scroll.

**Panel 3**
Our cartographer leans over the glass case inspecting closely.

**Panel 4**
Close on the owner's suspicious eyes narrowing at the visitor.

---

## Page 3 — 4-GRID

**Panel 1**
Money exchanged across the worn wooden counter between them.

**Panel 2**
The scroll changes hands in the dim afternoon light.

**Panel 3**
Door swings open letting in a shaft of street noise.

**Panel 4**
The cartographer exits into the busy market without looking back.
"""

# A script with chaotic variation (triggers layout_too_chaotic)
CHAOTIC_SCRIPT = """\
## Page 1 — SPLASH

**Panel 1**
Wide establishing shot of the harbour at dawn with tall ships.

---

## Page 2 — 8-GRID

**Panel 1**
Face.

**Panel 2**
Hand.

**Panel 3**
Rope.

**Panel 4**
Anchor chain dropping.

**Panel 5**
Seagull.

**Panel 6**
Wave.

**Panel 7**
Boot on deck.

**Panel 8**
Bell swinging.

---

## Page 3 — SPLASH

**Panel 1**
The ship sails into fog, a lone figure at the bow.
"""

# A brief row for fidelity tests
GOOD_BRIEF = {
    'id': 'test-scene',
    'key_dialogue': 'No',
    'visual_keywords': 'trembling hand; blank parchment',
    'panel_breakdown': 'p1:splash; p2:4-grid',
    'page_turn_beats': '',
}


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------

def test_principles_tuple_has_six_items():
    assert len(PRINCIPLES) == 6
    assert 'brief_fidelity' in PRINCIPLES
    assert 'panel_density' in PRINCIPLES
    assert 'dialogue_compression' in PRINCIPLES
    assert 'layout_rhythm' in PRINCIPLES
    assert 'caption_economy' in PRINCIPLES
    assert 'panel_composition_depth' in PRINCIPLES


def test_scorers_dict_matches_principles():
    assert set(SCORERS.keys()) == set(PRINCIPLES)


# ---------------------------------------------------------------------------
# score_brief_fidelity
# ---------------------------------------------------------------------------

def test_brief_fidelity_passes_when_all_checks_met():
    # GOOD_SCRIPT has 'No' as dialogue, panel count p1:splash p2:4-grid matches,
    # and we include the visual keywords
    script = GOOD_SCRIPT.replace(
        'Close on his trembling hand resting on the table edge.',
        'Close on his trembling hand and the blank parchment before him.',
    )
    brief = dict(GOOD_BRIEF, visual_keywords='trembling hand; blank parchment')
    parsed = parse_script(script)
    result = score_brief_fidelity(parsed, brief, script)
    assert result['principle'] == 'brief_fidelity'
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_brief_fidelity_drops_score_for_missing_dialogue():
    brief = dict(GOOD_BRIEF, key_dialogue='A phrase that does not appear anywhere')
    parsed = parse_script(GOOD_SCRIPT)
    result = score_brief_fidelity(parsed, brief, GOOD_SCRIPT)
    assert result['score'] < 1.0
    assert any(f['kind'] == 'dialogue_missing' for f in result['findings'])


def test_brief_fidelity_score_formula_one_failure():
    # 1 failure out of 4 checks = score 0.75
    brief = {
        'id': 'test',
        'key_dialogue': 'This line is absolutely not in the script',
        'visual_keywords': '',
        'panel_breakdown': '',
        'page_turn_beats': '',
    }
    parsed = parse_script(GOOD_SCRIPT)
    result = score_brief_fidelity(parsed, brief, GOOD_SCRIPT)
    assert result['score'] == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# score_brief_fidelity — distinct-kinds math (regression: #2)
# ---------------------------------------------------------------------------

def test_brief_fidelity_multiple_same_kind_counts_as_one(monkeypatch):
    """2 missing dialogue lines (same kind) → 1 distinct kind → score 0.75."""
    import storyforge.scoring_gn as scoring_gn_mod
    monkeypatch.setattr(
        scoring_gn_mod, 'check_brief_fidelity',
        lambda brief_row, script_text: [
            {'kind': 'dialogue_missing', 'detail': 'line A', 'severity': 'high'},
            {'kind': 'dialogue_missing', 'detail': 'line B', 'severity': 'high'},
        ],
    )
    parsed = parse_script(GOOD_SCRIPT)
    result = scoring_gn_mod.score_brief_fidelity(parsed, GOOD_BRIEF, GOOD_SCRIPT)
    assert result['score'] == pytest.approx(0.75), (
        '2 missing-dialogue failures are 1 distinct kind → 1/4 penalty → score 0.75'
    )
    assert len(result['findings']) == 2, 'all raw findings should still be reported'


def test_brief_fidelity_two_distinct_kinds_score_half(monkeypatch):
    """2 missing dialogues + 1 missing visual = 2 distinct kinds → score 0.5."""
    import storyforge.scoring_gn as scoring_gn_mod
    monkeypatch.setattr(
        scoring_gn_mod, 'check_brief_fidelity',
        lambda brief_row, script_text: [
            {'kind': 'dialogue_missing', 'detail': 'line A', 'severity': 'high'},
            {'kind': 'dialogue_missing', 'detail': 'line B', 'severity': 'high'},
            {'kind': 'visual_keyword_missing', 'detail': 'kw C', 'severity': 'medium'},
        ],
    )
    parsed = parse_script(GOOD_SCRIPT)
    result = scoring_gn_mod.score_brief_fidelity(parsed, GOOD_BRIEF, GOOD_SCRIPT)
    assert result['score'] == pytest.approx(0.5), (
        '2 distinct kinds (dialogue_missing + visual_keyword_missing) → 2/4 penalty → 0.5'
    )


def test_brief_fidelity_all_four_distinct_kinds_score_zero(monkeypatch):
    """1 failure of each of the 4 kinds → score 0.0."""
    import storyforge.scoring_gn as scoring_gn_mod
    monkeypatch.setattr(
        scoring_gn_mod, 'check_brief_fidelity',
        lambda brief_row, script_text: [
            {'kind': 'dialogue_missing', 'detail': 'x', 'severity': 'high'},
            {'kind': 'visual_keyword_missing', 'detail': 'y', 'severity': 'medium'},
            {'kind': 'panel_count_mismatch', 'detail': 'z', 'severity': 'medium'},
            {'kind': 'page_turn_missing', 'detail': 'w', 'severity': 'high'},
        ],
    )
    parsed = parse_script(GOOD_SCRIPT)
    result = scoring_gn_mod.score_brief_fidelity(parsed, GOOD_BRIEF, GOOD_SCRIPT)
    assert result['score'] == pytest.approx(0.0), (
        '4 distinct kinds → 4/4 penalty → score 0.0'
    )


def test_brief_fidelity_zero_failures_score_one(monkeypatch):
    """0 failures → score 1.0."""
    import storyforge.scoring_gn as scoring_gn_mod
    monkeypatch.setattr(
        scoring_gn_mod, 'check_brief_fidelity',
        lambda brief_row, script_text: [],
    )
    parsed = parse_script(GOOD_SCRIPT)
    result = scoring_gn_mod.score_brief_fidelity(parsed, GOOD_BRIEF, GOOD_SCRIPT)
    assert result['score'] == pytest.approx(1.0)
    assert result['findings'] == []


# ---------------------------------------------------------------------------
# score_panel_density
# ---------------------------------------------------------------------------

def test_panel_density_result_structure():
    parsed = parse_script(GOOD_SCRIPT)
    result = score_panel_density(parsed)
    assert result['principle'] == 'panel_density'
    assert 'score' in result
    assert 'findings' in result
    assert 0.0 <= result['score'] <= 1.0


def test_panel_density_passes_on_balanced_script():
    # GOOD_SCRIPT: p1=1 panel, p2=4 panels → avg = 2.5
    # score = 1 - |2.5 - 5.5| / 5.5 = 1 - 3/5.5 ≈ 0.455
    parsed = parse_script(GOOD_SCRIPT)
    result = score_panel_density(parsed, None, GOOD_SCRIPT)
    expected_score = 1.0 - abs(2.5 - 5.5) / 5.5
    assert result['score'] == pytest.approx(expected_score)


def test_panel_density_empty_script_returns_perfect():
    parsed = parse_script('# Scene: empty\n')
    result = score_panel_density(parsed)
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_panel_density_flags_cramped_page():
    parsed = parse_script(DENSE_ONE_PAGE)
    result = score_panel_density(parsed)
    # 10 panels on 1 page → avg=10, distance=4.5, score=1-4.5/5.5≈0.18
    assert result['score'] < 0.5
    assert any(f['kind'] == 'panel_density_high' for f in result['findings'])


def test_panel_density_sweet_spot_scores_near_one():
    # Build a 1-page script with 6 panels (close to 5.5 sweet spot)
    panels = '\n\n'.join(
        f'**Panel {i}**\n'
        f'A figure moves through the shadowed corridor with purpose and direction here.'
        for i in range(1, 7)
    )
    script = f'## Page 1 — 6-GRID\n\n{panels}\n'
    parsed = parse_script(script)
    result = score_panel_density(parsed)
    # avg=6, distance=0.5, score=1-0.5/5.5≈0.909
    assert result['score'] > 0.85


# ---------------------------------------------------------------------------
# score_dialogue_compression
# ---------------------------------------------------------------------------

def test_dialogue_compression_passes_on_short_lines():
    parsed = parse_script(GOOD_SCRIPT)
    result = score_dialogue_compression(parsed)
    assert result['principle'] == 'dialogue_compression'
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_dialogue_compression_empty_dialogue_is_perfect():
    # Script with no dialogue lines at all
    script = (
        '## Page 1 — SPLASH\n\n'
        '**Panel 1**\n'
        'Wide shot of the empty coastline at dusk with fading light.\n'
    )
    parsed = parse_script(script)
    result = score_dialogue_compression(parsed)
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_dialogue_compression_flags_long_balloon():
    # Build a 26-word dialogue line
    long_line = 'word ' * 26
    script = (
        '## Page 1 — SPLASH\n\n'
        '**Panel 1**\n'
        'The speaker addresses the crowd.\n\n'
        f'- SPEAKER: {long_line.strip()}\n'
    )
    parsed = parse_script(script)
    result = score_dialogue_compression(parsed)
    assert result['score'] < 1.0
    assert any(f['kind'] == 'balloon_too_long' for f in result['findings'])


def test_dialogue_compression_sfx_not_counted():
    # SFX lines should be excluded from scoring
    script = (
        '## Page 1 — SPLASH\n\n'
        '**Panel 1**\n'
        'A door slams in the hallway.\n\n'
        '- SFX: ' + 'BANG ' * 30 + '\n'
    )
    parsed = parse_script(script)
    result = score_dialogue_compression(parsed)
    # SFX excluded → no balloons counted → score 1.0
    assert result['score'] == 1.0


def test_dialogue_compression_mixed_severity():
    # 35-word line → medium; 45-word line → high
    line_35 = 'word ' * 35
    line_45 = 'word ' * 45
    script = (
        '## Page 1 — 2-GRID\n\n'
        '**Panel 1**\n'
        'First scene.\n\n'
        f'- CHARACTER: {line_35.strip()}\n\n'
        '**Panel 2**\n'
        'Second scene.\n\n'
        f'- CHARACTER: {line_45.strip()}\n'
    )
    parsed = parse_script(script)
    result = score_dialogue_compression(parsed)
    severities = {f['severity'] for f in result['findings']}
    assert 'medium' in severities
    assert 'high' in severities


# ---------------------------------------------------------------------------
# score_layout_rhythm
# ---------------------------------------------------------------------------

def test_layout_rhythm_single_page_is_perfect():
    parsed = parse_script(GOOD_SCRIPT.split('---')[0] + GOOD_SCRIPT.split('---')[1])
    # Force single-page by building minimal script
    script = '## Page 1 — SPLASH\n\n**Panel 1**\nSingle page scene.\n'
    parsed = parse_script(script)
    result = score_layout_rhythm(parsed)
    assert result['principle'] == 'layout_rhythm'
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_layout_rhythm_uniform_pages_flagged():
    parsed = parse_script(UNIFORM_SCRIPT)
    result = score_layout_rhythm(parsed)
    # 3 pages each with 4 panels → stdev = 0.0
    assert result['score'] == pytest.approx(0.0)
    assert any(f['kind'] == 'layout_too_uniform' for f in result['findings'])


def test_layout_rhythm_chaotic_pages_flagged():
    # CHAOTIC_SCRIPT: p1=1 panel, p2=8 panels, p3=1 panel
    parsed = parse_script(CHAOTIC_SCRIPT)
    densities = [len(p['panels']) for p in parsed['pages']]
    stdev = statistics.stdev(densities)
    result = score_layout_rhythm(parsed)
    assert stdev >= 3.0, f'expected chaotic stdev, got {stdev}'
    assert any(f['kind'] == 'layout_too_chaotic' for f in result['findings'])


def test_layout_rhythm_sweet_spot_scores_well():
    # Build script where stdev ≈ 1.5 (peak score = 1.0)
    # Pages with 4, 6 panels → stdev ≈ 1.41
    script = (
        '## Page 1 — 4-GRID\n\n'
        '**Panel 1**\nScene A with good composition detail here.\n'
        '**Panel 2**\nScene B with good composition detail here.\n'
        '**Panel 3**\nScene C with good composition detail here.\n'
        '**Panel 4**\nScene D with good composition detail here.\n\n'
        '---\n\n'
        '## Page 2 — 6-GRID\n\n'
        '**Panel 1**\nScene E.\n'
        '**Panel 2**\nScene F.\n'
        '**Panel 3**\nScene G.\n'
        '**Panel 4**\nScene H.\n'
        '**Panel 5**\nScene I.\n'
        '**Panel 6**\nScene J.\n'
    )
    parsed = parse_script(script)
    result = score_layout_rhythm(parsed)
    assert result['score'] > 0.8


# ---------------------------------------------------------------------------
# score_caption_economy
# ---------------------------------------------------------------------------

def test_caption_economy_minimal_strategy_one_caption_passes():
    # minimal → target=1; 1 caption per page → within target
    brief = {'caption_strategy': 'minimal'}
    parsed = parse_script(GOOD_SCRIPT)
    result = score_caption_economy(parsed, brief)
    assert result['principle'] == 'caption_economy'
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_caption_economy_none_strategy_any_caption_fails():
    brief = {'caption_strategy': 'none'}
    parsed = parse_script(GOOD_SCRIPT)  # has CAPTION lines
    result = score_caption_economy(parsed, brief)
    assert result['score'] < 1.0
    assert any(f['kind'] == 'caption_when_none' for f in result['findings'])


def test_caption_economy_unknown_strategy_defaults_to_target_2():
    brief = {'caption_strategy': 'unknown-strategy'}
    # Build a page with 4 captions (exceeds default target=2, even with +1 buffer)
    panels = ''.join(
        f'**Panel {i}**\nScene.\n\n- CAPTION: *Line {i}.*\n\n'
        for i in range(1, 5)
    )
    script = f'## Page 1 — 4-GRID\n\n{panels}'
    parsed = parse_script(script)
    result = score_caption_economy(parsed, brief)
    # 4 captions > target(2) + 1 = 3 → excess finding
    assert any(f['kind'] == 'caption_excess' for f in result['findings'])


def test_caption_economy_empty_pages_returns_perfect():
    brief = {'caption_strategy': 'minimal'}
    parsed = parse_script('# Scene: empty\n')
    result = score_caption_economy(parsed, brief)
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_caption_economy_journal_voiceover_target():
    # journal-voiceover → target=3; 3 captions allowed
    brief = {'caption_strategy': 'journal-voiceover'}
    panels = ''.join(
        f'**Panel {i}**\nScene.\n\n- CAPTION: *Line {i}.*\n\n'
        for i in range(1, 4)
    )
    script = f'## Page 1 — 3-GRID\n\n{panels}'
    parsed = parse_script(script)
    result = score_caption_economy(parsed, brief)
    # 3 captions == target → within target → score 1.0
    assert result['score'] == 1.0
    assert result['findings'] == []


# ---------------------------------------------------------------------------
# score_panel_composition_depth
# ---------------------------------------------------------------------------

def test_panel_composition_depth_sweet_spot_scores_one():
    # Build a panel with ~20 words of composition (in the 15-50 range)
    composition = (
        'The cartographer stands at his desk examining the blank parchment '
        'with trembling hands in the lamplight.'
    )
    script = f'## Page 1 — SPLASH\n\n**Panel 1**\n{composition}\n'
    parsed = parse_script(script)
    word_count = len(parsed['pages'][0]['panels'][0]['composition'].split())
    assert 15 <= word_count <= 50, f'expected 15-50 words, got {word_count}'
    result = score_panel_composition_depth(parsed)
    assert result['principle'] == 'panel_composition_depth'
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_panel_composition_depth_too_sparse_flagged():
    # 5-word composition → below MIN=15
    script = '## Page 1 — SPLASH\n\n**Panel 1**\nA figure in darkness.\n'
    parsed = parse_script(script)
    result = score_panel_composition_depth(parsed)
    assert result['score'] < 1.0
    assert any(f['kind'] == 'composition_too_sparse' for f in result['findings'])


def test_panel_composition_depth_too_dense_flagged():
    # 60-word composition → above MAX=50
    dense = ' '.join(['word'] * 60)
    script = f'## Page 1 — SPLASH\n\n**Panel 1**\n{dense}\n'
    parsed = parse_script(script)
    result = score_panel_composition_depth(parsed)
    assert result['score'] < 1.0
    assert any(f['kind'] == 'composition_too_dense' for f in result['findings'])


def test_panel_composition_depth_empty_script_returns_perfect():
    parsed = parse_script('# Scene: empty\n')
    result = score_panel_composition_depth(parsed)
    assert result['score'] == 1.0
    assert result['findings'] == []


def test_panel_composition_depth_boundary_at_exactly_15_words():
    # Exactly 15 words → exactly at MIN → within sweet spot
    composition = ' '.join(['word'] * 15)
    script = f'## Page 1 — SPLASH\n\n**Panel 1**\n{composition}\n'
    parsed = parse_script(script)
    result = score_panel_composition_depth(parsed)
    assert result['score'] == 1.0


def test_panel_composition_depth_boundary_at_exactly_50_words():
    # Exactly 50 words → exactly at MAX → within sweet spot
    composition = ' '.join(['word'] * 50)
    script = f'## Page 1 — SPLASH\n\n**Panel 1**\n{composition}\n'
    parsed = parse_script(script)
    result = score_panel_composition_depth(parsed)
    assert result['score'] == 1.0


# ---------------------------------------------------------------------------
# score_scene aggregator
# ---------------------------------------------------------------------------

def test_score_scene_returns_all_principles():
    parsed = parse_script(GOOD_SCRIPT)
    results = score_scene('test-scene', parsed, GOOD_BRIEF, GOOD_SCRIPT)
    assert set(results.keys()) == set(PRINCIPLES)
    for principle, result in results.items():
        assert result['principle'] == principle
        assert 0.0 <= result['score'] <= 1.0
        assert 'findings' in result


# ---------------------------------------------------------------------------
# score_project contract
# ---------------------------------------------------------------------------

def test_score_project_skips_non_gn(fixture_dir):
    """Novel-mode project returns skipped=True."""
    result = score_project(fixture_dir)
    assert result.get('skipped') is True
    assert 'reason' in result


def test_score_project_returns_principles_for_gn(fixture_dir_gn):
    """GN project returns the principles list."""
    result = score_project(fixture_dir_gn)
    assert result.get('skipped') is not True
    assert 'principles' in result
    assert set(result['principles']) == set(PRINCIPLES)
