"""Tests for cmd_elaborate's prompts-stage handler (issue #260) — page
selection, precondition gating, the page-prompt response validator, the
workflow splice, and the strict/coach/full coaching paths."""

import os


def _make_gn_project(tmp_path, *, with_arch=True, with_script=True,
                     references=True):
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
        'id|goal|conflict|outcome|panel_breakdown|visual_keywords|motifs|'
        'caption_strategy\n'
        's01-studio|focus|distraction|focus regained|p1: 2-panel|'
        'inkpot; hand|candle|minimal\n'
    )
    (ref / 'scene-intent.csv').write_text(
        'id|function|emotional_arc|value_at_stake|value_shift\n'
        's01-studio|opening|tense to calm|control|positive\n'
    )
    canon = ref / 'canon'
    canon.mkdir()
    (canon / 'style-foundation.md').write_text(
        '---\ncanon_id: style-foundation\n---\n\n'
        '## Embeddable block\n\nChiaroscuro; muted palette.\n'
    )
    (canon / 'lighting-laws.md').write_text(
        '---\ncanon_id: lighting-laws\n---\n\n'
        '## Embeddable block\n\nSingle warm source.\n'
    )
    pages = proj / 'pages'
    pages.mkdir()
    fm_refs = (
        'references_required:\n'
        '  - reference/visual/char.png\n'
        '  - reference/visual/tone.png\n'
    ) if references else ''
    body = '## Scene context\n\nOpening beat.\n\n'
    if with_arch:
        body += ('## Page architecture\n\n### Intent\nThe work begins.\n\n'
                 '### Layout\nTwo-row grid.\n\n')
    if with_script:
        body += '## Panel script\n\n### Panel 1\nMid shot of Lucien.\n'
    (pages / 's01-p1.md').write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 2\n"
        + fm_refs +
        "---\n\n"
        + body
    )
    return str(proj)


_GOOD_BODY = (
    '**Page 1 — graphic novel page (2 panels).**\n\n'
    '**Scene:** A studio at dusk.\n\n'
    '**Subject:** Lucien. **Character anchor (use this exact description in '
    'every panel showing him):** "tall, lean." See attached character '
    'reference image.\n\n'
    '**Important details:** muted palette, candle amber accent.\n\n'
    '**Use case:** A single page, 2 panels in a 2x1 grid.\n\n'
    '**Panels:**\n\n'
    '1. Mid shot of Lucien.\n'
    '2. Close on the hand.\n\n'
    '**Constraints:** Keep layout exactly; positive constraints only.'
)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def test_default_targets_pages_without_workflow(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_prompts
    proj = _make_gn_project(tmp_path)
    targets = _select_pages_for_prompts(proj, page=None, scene=None, force=False)
    assert [t['page_id'] for t in targets] == ['s01-p1']


def test_force_includes_pages_with_workflow(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_prompts
    proj = _make_gn_project(tmp_path)
    page_path = os.path.join(proj, 'pages', 's01-p1.md')
    with open(page_path, 'a') as f:
        f.write('\n## Image-generation workflow\n\n**Approach:** done.\n')
    assert _select_pages_for_prompts(proj, page=None, scene=None, force=False) == []
    assert len(_select_pages_for_prompts(proj, page=None, scene=None, force=True)) == 1


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def test_precondition_passes_when_arch_and_script_present(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_prompts
    proj = _make_gn_project(tmp_path)
    ok, reason = _precondition_check_prompts(proj, 's01-p1', 's01-studio')
    assert ok is True
    assert reason == ''


def test_precondition_fails_without_page_architecture(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_prompts
    proj = _make_gn_project(tmp_path, with_arch=False)
    ok, reason = _precondition_check_prompts(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'Page architecture' in reason
    assert 'page-architecture' in reason


def test_precondition_fails_without_panel_script(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_prompts
    proj = _make_gn_project(tmp_path, with_script=False)
    ok, reason = _precondition_check_prompts(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'Panel script' in reason


def test_precondition_does_not_gate_on_canon(tmp_path):
    """Canon only informs the prompt — absent canon must NOT block."""
    from storyforge.cmd_elaborate import _precondition_check_prompts
    proj = _make_gn_project(tmp_path)
    import shutil
    shutil.rmtree(os.path.join(proj, 'reference', 'canon'))
    ok, reason = _precondition_check_prompts(proj, 's01-p1', 's01-studio')
    assert ok is True, reason


def test_precondition_fails_when_panel_breakdown_empty(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_prompts
    proj = _make_gn_project(tmp_path)
    briefs = os.path.join(proj, 'reference', 'scene-briefs.csv')
    with open(briefs) as f:
        text = f.read()
    with open(briefs, 'w') as f:
        f.write(text.replace('p1: 2-panel', ''))
    ok, reason = _precondition_check_prompts(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'panel_breakdown' in reason


# ---------------------------------------------------------------------------
# Response validator
# ---------------------------------------------------------------------------

def test_validate_accepts_well_formed_body():
    from storyforge.cmd_elaborate import _validate_page_prompt_response
    ok, body = _validate_page_prompt_response(_GOOD_BODY, expected_panel_count=2)
    assert ok is True
    assert '**Scene:**' in body


def test_validate_rejects_wrong_panel_count():
    from storyforge.cmd_elaborate import _validate_page_prompt_response
    ok, _ = _validate_page_prompt_response(_GOOD_BODY, expected_panel_count=3)
    assert ok is False


def test_validate_rejects_missing_label():
    from storyforge.cmd_elaborate import _validate_page_prompt_response
    bad = _GOOD_BODY.replace('**Constraints:**', '**Limits:**')
    ok, _ = _validate_page_prompt_response(bad, expected_panel_count=2)
    assert ok is False


def test_validate_rejects_missing_panels_list():
    from storyforge.cmd_elaborate import _validate_page_prompt_response
    bad = _GOOD_BODY.replace('**Panels:**', '**Beats:**')
    ok, _ = _validate_page_prompt_response(bad, expected_panel_count=2)
    assert ok is False


def test_validate_strips_code_fence():
    from storyforge.cmd_elaborate import _validate_page_prompt_response
    ok, body = _validate_page_prompt_response(
        '```markdown\n' + _GOOD_BODY + '\n```', expected_panel_count=2)
    assert ok is True
    assert '```' not in body


# ---------------------------------------------------------------------------
# Splice
# ---------------------------------------------------------------------------

def test_splice_inserts_before_page_specific_notes(tmp_path):
    from storyforge.cmd_elaborate import _splice_image_workflow
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\npage_id: s01-p1\nscene_id: s01\npage_within_scene: 1\n"
        "total_pages_in_scene: 1\npanel_count: 1\n---\n\n"
        "## Panel script\n\n### Panel 1\nMid.\n\n"
        "## Page-specific notes for the artist\n\n- note\n"
    )
    _splice_image_workflow(
        str(page_path),
        '## Image-generation workflow\n\n**Approach:** x.\n',
        canon_ids=['style-foundation'],
    )
    text = page_path.read_text()
    assert text.index('## Panel script') < text.index('## Image-generation workflow')
    assert text.index('## Image-generation workflow') < text.index('## Page-specific notes')
    assert 'canon_referenced:' in text
    assert 'reference/canon/style-foundation.md' in text


def test_splice_replaces_existing_workflow(tmp_path):
    from storyforge.cmd_elaborate import _splice_image_workflow
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\npage_id: s01-p1\nscene_id: s01\npage_within_scene: 1\n"
        "total_pages_in_scene: 1\npanel_count: 1\n---\n\n"
        "## Image-generation workflow\n\nOLD.\n"
    )
    _splice_image_workflow(
        str(page_path), '## Image-generation workflow\n\nNEW.\n', canon_ids=[],
    )
    text = page_path.read_text()
    assert 'NEW.' in text
    assert 'OLD.' not in text
    assert text.count('## Image-generation workflow') == 1


# ---------------------------------------------------------------------------
# Handler — coaching paths
# ---------------------------------------------------------------------------

def test_strict_mode_writes_template_no_api_call(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_prompt_handler_gn
    calls = {'n': 0}
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: calls.__setitem__('n', calls['n'] + 1) or '')
    proj = _make_gn_project(tmp_path)
    rc = _run_page_prompt_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert rc == 0
    assert calls['n'] == 0
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Image-generation workflow' in text
    assert '**Scene:**' in text


def test_coach_mode_writes_brief_no_page_mutation(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_prompt_handler_gn
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: 'should not be called')
    proj = _make_gn_project(tmp_path)
    _run_page_prompt_handler_gn(
        proj, dry_run=False, coaching='coach',
        page=None, scene=None, force=False,
    )
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Image-generation workflow' not in text
    brief_path = os.path.join(proj, 'working', 'coaching', 'prompts-s01-p1.md')
    assert os.path.isfile(brief_path)
    assert 'GPT Image 2' in open(brief_path).read()


def test_full_mode_with_mocked_api_splices_workflow(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_prompt_handler_gn
    monkeypatch.setattr('storyforge.api.invoke_api', lambda *a, **kw: _GOOD_BODY)
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)
    proj = _make_gn_project(tmp_path)
    rc = _run_page_prompt_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )
    assert rc == 0
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Image-generation workflow' in text
    # The page-prompt body is blockquoted under ### Page prompt
    assert '> **Scene:** A studio at dusk.' in text
    # References from frontmatter rendered into the section
    assert 'reference/visual/char.png' in text


def test_full_mode_bad_response_does_not_mutate(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_prompt_handler_gn
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: 'Sorry, I cannot help with that.')
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)
    proj = _make_gn_project(tmp_path)
    rc = _run_page_prompt_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )
    assert rc == 1
    assert '## Image-generation workflow' not in open(
        os.path.join(proj, 'pages', 's01-p1.md')).read()


def test_handler_notes_missing_references(tmp_path, monkeypatch, capsys):
    from storyforge.cmd_elaborate import _run_page_prompt_handler_gn
    proj = _make_gn_project(tmp_path, references=False)
    _run_page_prompt_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    output = capsys.readouterr().out + capsys.readouterr().err
    # Strict still writes, but a NOTE warns references are recommended
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Image-generation workflow' in text


def test_prompts_stage_exits_on_novel_medium(tmp_path):
    import pytest
    import argparse
    from storyforge.cmd_elaborate import _run_main_stage
    proj = tmp_path / 'novel'
    proj.mkdir()
    (proj / 'storyforge.yaml').write_text(
        'project:\n  medium: novel\n  title: Test\n'
    )
    args = argparse.Namespace(page=None, scene=None, force=False, coaching=None)
    with pytest.raises(SystemExit) as exc:
        _run_main_stage('prompts', str(proj), str(proj / 'reference'),
                        dry_run=False, interactive=False, seed='', args=args)
    assert exc.value.code == 1


def test_parse_args_accepts_prompts_stage():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--stage', 'prompts'])
    assert args.stage == 'prompts'
