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
