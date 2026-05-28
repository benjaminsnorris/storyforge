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
