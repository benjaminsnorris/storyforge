"""Tests for script_format parser and brief-fidelity check."""

import pytest

from storyforge.script_format import (
    parse_script, count_pages, count_panels,
    detect_page_turn_pages, check_brief_fidelity,
    check_layout_anti_patterns,
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


# ---------------------------------------------------------------------------
# Layout anti-pattern detectors
# ---------------------------------------------------------------------------

def test_layout_anti_patterns_clean_script_has_no_findings():
    """A well-formed script with no anti-patterns produces no
    findings."""
    failures = check_layout_anti_patterns(SAMPLE_SCRIPT)
    assert failures == []


def test_layout_anti_patterns_flags_page_one_page_turn():
    """A page-turn marker on page 1 is impossible (no preceding page
    to turn from). Fires page_turn_on_page_one at high severity."""
    bad_script = """\
# Scene: opens-with-turn

## Page 1 — SPLASH ⟵ PAGE-TURN REVEAL

**Panel 1** (full bleed)
A reveal panel.
"""
    failures = check_layout_anti_patterns(bad_script)
    pt = [f for f in failures if f['kind'] == 'page_turn_on_page_one']
    assert len(pt) == 1
    assert pt[0]['severity'] == 'high'
    assert pt[0]['page'] == 1
    assert 'no preceding page' in pt[0]['detail']


def test_layout_anti_patterns_page_turn_on_later_page_is_ok():
    """A page-turn marker on page 2+ is the normal use case — fires no
    finding."""
    failures = check_layout_anti_patterns(SAMPLE_SCRIPT)
    # SAMPLE_SCRIPT has the marker on page 2, which is correct.
    pt = [f for f in failures if f['kind'] == 'page_turn_on_page_one']
    assert pt == []


def test_layout_anti_patterns_flags_excessive_density():
    """A page with ≥13 panels fires panel_density_excessive (legibility
    crisis threshold per references/gn-layout-vocabulary.md)."""
    panels_block = '\n\n'.join(
        f'**Panel {i}** (irregular)\nBeat {i}.'
        for i in range(1, 14)  # 13 panels — at threshold
    )
    bad_script = f"""\
# Scene: too-dense

## Page 1 — IRREGULAR

{panels_block}
"""
    failures = check_layout_anti_patterns(bad_script)
    density = [f for f in failures if f['kind'] == 'panel_density_excessive']
    assert len(density) == 1
    assert density[0]['severity'] == 'medium'
    assert density[0]['page'] == 1
    assert '13 panels' in density[0]['detail']


def test_layout_anti_patterns_density_below_threshold_is_ok():
    """12 panels is at the upper end of legibility but acceptable —
    no finding."""
    panels_block = '\n\n'.join(
        f'**Panel {i}** (irregular)\nBeat {i}.'
        for i in range(1, 13)  # 12 panels — under threshold
    )
    script_12 = f"""\
# Scene: dense-but-ok

## Page 1 — IRREGULAR

{panels_block}
"""
    failures = check_layout_anti_patterns(script_12)
    density = [f for f in failures if f['kind'] == 'panel_density_excessive']
    assert density == []


def test_layout_anti_patterns_flags_tier_with_one_panel():
    """A page declared `tier` in the brief but rendered with only 1
    panel is mis-labeled (a 1-panel tier is a splash). Fires
    tier_panel_count_unconventional at low severity."""
    script = """\
# Scene: tier-mislabel

## Page 1 — TIER

**Panel 1** (full width)
A single full-width panel.
"""
    brief_row = {'panel_breakdown': 'p1:tier'}
    failures = check_layout_anti_patterns(script, brief_row)
    tier_findings = [
        f for f in failures
        if f['kind'] == 'tier_panel_count_unconventional'
    ]
    assert len(tier_findings) == 1
    assert tier_findings[0]['severity'] == 'low'
    assert tier_findings[0]['page'] == 1
    assert '1 panels' in tier_findings[0]['detail']


def test_layout_anti_patterns_flags_tier_with_five_panels():
    """5 panels in a tier is mis-labeled (likely an N-grid). Fires
    tier_panel_count_unconventional."""
    panels = '\n\n'.join(
        f'**Panel {i}** (tier slot {i})\nBeat {i}.'
        for i in range(1, 6)
    )
    script = f"""\
# Scene: tier-too-many

## Page 1 — TIER

{panels}
"""
    brief_row = {'panel_breakdown': 'p1:tier'}
    failures = check_layout_anti_patterns(script, brief_row)
    tier_findings = [
        f for f in failures
        if f['kind'] == 'tier_panel_count_unconventional'
    ]
    assert len(tier_findings) == 1


def test_layout_anti_patterns_tier_with_three_panels_is_ok():
    """3 panels on a tier-declared page is canonical — no finding."""
    script = """\
# Scene: tier-canonical

## Page 1 — TIER

**Panel 1** (left)
Left beat.

**Panel 2** (center)
Center beat.

**Panel 3** (right)
Right beat.
"""
    brief_row = {'panel_breakdown': 'p1:tier'}
    failures = check_layout_anti_patterns(script, brief_row)
    tier_findings = [
        f for f in failures
        if f['kind'] == 'tier_panel_count_unconventional'
    ]
    assert tier_findings == []


def test_layout_anti_patterns_tier_two_and_four_panels_are_ok():
    """2 and 4 panels are also within the tier convention band."""
    for n in (2, 4):
        panels = '\n\n'.join(
            f'**Panel {i}**\nBeat {i}.' for i in range(1, n + 1)
        )
        script = f"""\
# Scene: tier-{n}

## Page 1 — TIER

{panels}
"""
        brief_row = {'panel_breakdown': 'p1:tier'}
        failures = check_layout_anti_patterns(script, brief_row)
        tier_findings = [
            f for f in failures
            if f['kind'] == 'tier_panel_count_unconventional'
        ]
        assert tier_findings == [], (
            f'{n} panels should be acceptable on a tier page'
        )


def test_layout_anti_patterns_skips_tier_check_without_brief():
    """When no brief is provided, tier-panel-count check is skipped
    (we can't know what the author intended)."""
    script = """\
# Scene: no-brief

## Page 1 — TIER

**Panel 1** (full)
A single panel.
"""
    failures = check_layout_anti_patterns(script)  # no brief_row
    tier_findings = [
        f for f in failures
        if f['kind'] == 'tier_panel_count_unconventional'
    ]
    assert tier_findings == []


def test_layout_anti_patterns_tier_check_skips_non_tier_pages():
    """A page declared as `splash` or `6-grid` doesn't trigger tier
    check even when its panel count is outside {2,3,4}."""
    script = """\
# Scene: splash-page

## Page 1 — SPLASH

**Panel 1** (full bleed)
A single splash panel.
"""
    brief_row = {'panel_breakdown': 'p1:splash'}
    failures = check_layout_anti_patterns(script, brief_row)
    # No tier finding — splash is supposed to be 1 panel.
    tier_findings = [
        f for f in failures
        if f['kind'] == 'tier_panel_count_unconventional'
    ]
    assert tier_findings == []


def test_layout_anti_patterns_multiple_findings_on_different_pages():
    """Multiple anti-patterns across pages all surface independently."""
    # Page 1: page-turn marker (impossible) AND 13 panels (excessive)
    # Page 2: tier with 1 panel (mis-labeled)
    panels_p1 = '\n\n'.join(
        f'**Panel {i}**\nBeat {i}.' for i in range(1, 14)
    )
    script = f"""\
# Scene: multi-violation

## Page 1 — IRREGULAR ⟵ PAGE-TURN REVEAL

{panels_p1}

## Page 2 — TIER

**Panel 1** (full)
Single panel.
"""
    brief_row = {'panel_breakdown': 'p1:irregular; p2:tier'}
    failures = check_layout_anti_patterns(script, brief_row)
    kinds = {f['kind'] for f in failures}
    assert 'page_turn_on_page_one' in kinds
    assert 'panel_density_excessive' in kinds
    assert 'tier_panel_count_unconventional' in kinds


# ---------------------------------------------------------------------------
# Test gaps closed in the PR review pass
# ---------------------------------------------------------------------------

def test_layout_anti_patterns_flags_unparseable_script():
    """Non-empty script text that produces zero parsed pages fires
    `script_unparseable` at high severity. Without this guard, an
    encoding regression or header-format violation would let a
    broken script pass with no findings — the silent-failure class
    SF-2 caught in PR #250 review."""
    bad = "This is text but it has no `## Page N` headers anywhere."
    failures = check_layout_anti_patterns(bad)
    unparseable = [f for f in failures if f['kind'] == 'script_unparseable']
    assert len(unparseable) == 1
    assert unparseable[0]['severity'] == 'high'
    assert 'page header format' in unparseable[0]['detail']


def test_layout_anti_patterns_empty_script_silent():
    """Truly empty input (script_text == '') is silent — no
    unparseable finding fires. The detector only flags non-empty
    inputs that fail to parse."""
    failures = check_layout_anti_patterns('')
    assert failures == []
    failures = check_layout_anti_patterns('   \n\n  ')
    assert failures == []


def test_layout_anti_patterns_tier_token_with_plus_modifier():
    """`pN:tier+2` token (combined modifier in panel_breakdown)
    parses to 'tier' after the +-split, and the tier check still
    fires when panel count is outside the {2,3,4} band. (PR #250
    review T-3.)"""
    script = """\
# Scene: tier-plus

## Page 1 — TIER

**Panel 1** (full)
Single panel.
"""
    brief_row = {'panel_breakdown': 'p1:tier+2'}
    failures = check_layout_anti_patterns(script, brief_row)
    tier_findings = [
        f for f in failures
        if f['kind'] == 'tier_panel_count_unconventional'
    ]
    assert len(tier_findings) == 1


def test_layout_anti_patterns_empty_panel_breakdown_skips_tier_check():
    """When brief_row is provided but panel_breakdown is empty
    string, the tier check no-ops (no declared tier pages exist).
    No tier finding fires regardless of script content. (PR #250
    review T-5.)"""
    script = """\
# Scene: no-breakdown

## Page 1 — TIER

**Panel 1** (full)
Single panel.
"""
    for empty_value in ('', None):
        brief_row = {'panel_breakdown': empty_value}
        failures = check_layout_anti_patterns(script, brief_row)
        tier_findings = [
            f for f in failures
            if f['kind'] == 'tier_panel_count_unconventional'
        ]
        assert tier_findings == [], (
            f'empty panel_breakdown should skip tier check; '
            f'got {tier_findings}'
        )


def test_layout_anti_patterns_zero_panel_page_fires_tier_check():
    """A tier-declared page with zero panels parsed (the panels list
    is empty) fires tier_panel_count_unconventional — 0 is outside
    the {2,3,4} band. Documents the contract for an edge case the
    parser can produce. (PR #250 review T-7.)"""
    script = """\
# Scene: empty-tier

## Page 1 — TIER
"""
    brief_row = {'panel_breakdown': 'p1:tier'}
    failures = check_layout_anti_patterns(script, brief_row)
    tier_findings = [
        f for f in failures
        if f['kind'] == 'tier_panel_count_unconventional'
    ]
    assert len(tier_findings) == 1
    assert '0 panels' in tier_findings[0]['detail']


def test_layout_anti_patterns_cofires_with_page_turn_missing():
    """page_turn_missing (from check_brief_fidelity) and
    page_turn_on_page_one (from check_layout_anti_patterns) can
    fire on the same script: brief specifies page-turn beats AND
    page 1 has the marker AND no later page does. Both validators
    are independent; both findings flow to the revision prompt.
    (PR #250 review T-4.)"""
    from storyforge.script_format import check_brief_fidelity
    bad_script = """\
# Scene: cofire

## Page 1 — SPLASH ⟵ PAGE-TURN REVEAL

**Panel 1** (full bleed)
A reveal panel.
"""
    brief_row = {
        'panel_breakdown': 'p1:splash',
        'page_turn_beats': 'reveal on p1 — wrong',
    }
    fidelity_failures = check_brief_fidelity(brief_row, bad_script)
    layout_failures = check_layout_anti_patterns(bad_script, brief_row)
    fidelity_kinds = {f['kind'] for f in fidelity_failures}
    layout_kinds = {f['kind'] for f in layout_failures}
    # The brief says page-turn beats exist; the script's marker is on
    # page 1 (impossible). Both findings apply.
    assert 'page_turn_on_page_one' in layout_kinds
    # page_turn_missing fires ONLY when no page has the marker; here
    # page 1 has it, so check_brief_fidelity considers the existence
    # check satisfied. Document that with an explicit assert.
    assert 'page_turn_missing' not in fidelity_kinds, (
        'page_turn_missing should not fire when SOME page carries '
        'the marker, even if that page is page 1'
    )


def test_panels_per_token_returns_none_for_tier():
    """_panels_per_token('tier') returns None so check_brief_fidelity
    skips the count check for tier tokens — the tier-range case is
    owned by check_layout_anti_patterns. Without this dedupe both
    validators would fire on the same offense. (PR #250 review
    CR-2.)"""
    from storyforge.script_format import _panels_per_token
    assert _panels_per_token('tier') is None
    assert _panels_per_token('Tier') is None
    assert _panels_per_token(' tier ') is None
    # The other tokens keep their existing behavior.
    assert _panels_per_token('splash') == 1
    assert _panels_per_token('double-spread') == 1
    assert _panels_per_token('6-grid') == 6
    assert _panels_per_token('irregular') is None


def test_density_limit_matches_reference_doc():
    """The deterministic threshold (_PANEL_DENSITY_LIMIT = 13) must
    match what references/gn-layout-vocabulary.md cites. Without this
    test, a future contributor tuning the threshold would silently
    drift the doc out of sync with the code. (PR #250 review CR-3 +
    TD-6 — doc-binding regression test.)"""
    import os as _os
    from storyforge.script_format import (
        _PANEL_DENSITY_LIMIT, _TIER_PANEL_RANGE,
    )
    repo_root = _os.path.abspath(
        _os.path.join(_os.path.dirname(__file__), '..')
    )
    doc_path = _os.path.join(
        repo_root, 'references', 'gn-layout-vocabulary.md',
    )
    with open(doc_path, encoding='utf-8') as f:
        body = f.read()
    # Density section must cite the constant value verbatim.
    assert f'≥ {_PANEL_DENSITY_LIMIT}' in body, (
        f'references/gn-layout-vocabulary.md must cite the density '
        f'threshold {_PANEL_DENSITY_LIMIT}; either update the constant '
        'or update the doc'
    )
    # Tier range must appear as low-high in the prose.
    low, high = _TIER_PANEL_RANGE
    assert f'{low}-{high}' in body, (
        f'references/gn-layout-vocabulary.md must cite the tier-panel '
        f'range {low}-{high}; either update the constant or the doc'
    )


def test_gn_prompt_contains_critical_layout_reminders():
    """The GN prompts must continue to carry the load-bearing layout
    reminders. A future "tighten prompts" refactor that silently
    strips these would regress the behavior the deterministic
    detectors then fire on after the fact. (PR #250 review T-2.)"""
    from storyforge.prompts_elaborate_gn import BRIEFS_GN_PREAMBLE
    from storyforge.prompts_gn import build_drafting_prompt
    # The briefs preamble must reference the layout-vocabulary doc +
    # the page-1 page-turn ban + the splash logic.
    assert 'gn-layout-vocabulary.md' in BRIEFS_GN_PREAMBLE
    assert ('NEVER' in BRIEFS_GN_PREAMBLE
            and 'page 1' in BRIEFS_GN_PREAMBLE.lower())
    assert 'splash' in BRIEFS_GN_PREAMBLE.lower()
    # The drafting prompt is built as an f-string in build_drafting_prompt.
    # Build a sample with minimum data and inspect the result.
    prompt = build_drafting_prompt(
        project_dir='/tmp/test',
        scene_id='test-scene',
        scene_row={'target_pages': '3', 'title': 'Test', 'pov': ''},
        intent_row={},
        brief_row={
            'goal': '', 'conflict': '', 'outcome': '',
            'crisis': '', 'decision': '',
            'key_actions': '', 'key_dialogue': '',
            'emotions': '', 'motifs': '', 'subtext': '',
            'page_layout': '', 'panel_breakdown': '',
            'visual_keywords': '', 'page_turn_beats': '',
            'caption_strategy': '',
        },
        character_visuals='',
        location_visuals='',
        voice_profile_text='',
    )
    # The drafting prompt must reference the layout vocabulary doc
    # + the page-1 page-turn ban.
    assert 'gn-layout-vocabulary.md' in prompt
    assert ('NEVER' in prompt and 'page 1' in prompt.lower())
    # Plus the density ceiling reminder.
    assert ('panel_density_excessive' in prompt
            or 'legibility crisis' in prompt
            or '≥13' in prompt)
