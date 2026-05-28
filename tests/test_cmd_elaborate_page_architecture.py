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
    (pages / 's01-p1.md').write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 2\n"
        "---\n\n"
        "## Scene context\n\nOpening beat.\n\n"
        "## Panel script\n\n**Panel 1.** Wide.\n"
    )
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
    other = os.path.join(proj, 'pages', 's02-p1.md')
    with open(other, 'w') as f:
        f.write(
            "---\n"
            "page_id: s02-p1\n"
            "scene_id: s02-other\n"
            "page_within_scene: 1\n"
            "total_pages_in_scene: 1\n"
            "panel_count: 1\n"
            "---\n\n"
            "## Panel script\n\n**Panel 1.**\n"
        )
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


def test_precondition_missing_brief_skips_page(tmp_path):
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
