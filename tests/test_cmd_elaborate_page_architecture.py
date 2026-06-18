"""Tests for cmd_elaborate's page-architecture handler — page selection,
precondition gating, dry-run output, and the splice/validate/full path.

Issue #260: page architecture is now a single `## Page architecture`
authoring-context section (the separate page-blocking prompt was removed).
"""

import os


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


# ---------------------------------------------------------------------------
# Page selection
# ---------------------------------------------------------------------------

def test_default_targets_pages_without_architecture(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
    targets = _select_pages_for_architecture(proj, page=None, scene=None, force=False)
    assert len(targets) == 1
    assert targets[0]['page_id'] == 's01-p1'


def test_force_includes_pages_with_architecture(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
    page_path = os.path.join(proj, 'pages', 's01-p1.md')
    with open(page_path) as f:
        body = f.read()
    body = body.replace(
        '## Scene context\n\nOpening beat.\n\n',
        '## Scene context\n\nOpening beat.\n\n'
        '## Page architecture\n\nintent.\n\n',
    )
    with open(page_path, 'w') as f:
        f.write(body)
    assert _select_pages_for_architecture(proj, page=None, scene=None, force=False) == []
    forced = _select_pages_for_architecture(proj, page=None, scene=None, force=True)
    assert len(forced) == 1


def test_scene_filter_limits_to_one_scenes_pages(tmp_path):
    from storyforge.cmd_elaborate import _select_pages_for_architecture
    proj = _make_gn_project(tmp_path)
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


# ---------------------------------------------------------------------------
# Precondition gating
# ---------------------------------------------------------------------------

def test_precondition_missing_brief_skips_page(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_page
    proj = _make_gn_project(tmp_path)
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


def test_precondition_better_message_when_scenes_csv_missing(tmp_path):
    from storyforge.cmd_elaborate import _precondition_check_page
    proj = _make_gn_project(tmp_path)
    os.remove(os.path.join(proj, 'reference', 'scenes.csv'))
    ok, reason = _precondition_check_page(proj, 's01-p1', 's01-studio')
    assert ok is False
    assert 'scenes.csv is missing' in reason
    assert 'elaborate --stage map' in reason


# ---------------------------------------------------------------------------
# Splice
# ---------------------------------------------------------------------------

def test_splice_inserts_between_scene_context_and_panel_script(tmp_path):
    from storyforge.cmd_elaborate import _splice_page_architecture
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
        "## Panel script\n\n**Panel 1.**\n"
    )
    section = '## Page architecture\n\n### Intent\nQuiet.\n'
    _splice_page_architecture(str(page_path), section, canon_ids=[
        'panel-registers', 'page-rhythm-rules',
    ])
    text = page_path.read_text()
    assert '## Page architecture' in text
    # Inserted BEFORE the panel script, AFTER scene context
    assert text.index('## Page architecture') < text.index('## Panel script')
    assert text.index('## Scene context') < text.index('## Page architecture')
    # canon_referenced appended to frontmatter
    assert 'canon_referenced:' in text
    assert 'reference/canon/panel-registers.md' in text


def test_splice_replaces_existing_section_when_force(tmp_path):
    from storyforge.cmd_elaborate import _splice_page_architecture
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
        "## Page architecture\n\nOLD architecture.\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
    _splice_page_architecture(
        str(page_path), '## Page architecture\n\nNEW arch.\n', canon_ids=[],
    )
    text = page_path.read_text()
    assert 'NEW arch' in text
    assert 'OLD architecture' not in text
    assert text.count('## Page architecture') == 1
    # Panel script survives the force-replace
    assert '## Panel script' in text
    assert '**Panel 1.**' in text


def test_splice_appends_to_end_when_no_panel_script_header(tmp_path):
    from storyforge.cmd_elaborate import _splice_page_architecture
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "---\n\n"
        "## Scene context\n\nBeat.\n"
    )
    _splice_page_architecture(
        str(page_path), '## Page architecture\n\n### Intent\nQuiet.\n',
        canon_ids=[],
    )
    text = page_path.read_text()
    assert '## Page architecture' in text
    assert '## Scene context' in text
    assert text.index('## Scene context') < text.index('## Page architecture')


def test_splice_extends_existing_canon_referenced_list(tmp_path):
    """When canon_referenced: already has entries, splice extends the list
    (not collapses onto the key line, which would be invalid YAML)."""
    from storyforge.cmd_elaborate import _splice_page_architecture
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "canon_referenced:\n"
        "  - reference/canon/style-foundation.md\n"
        "---\n\n"
        "## Scene context\n\nBeat.\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
    _splice_page_architecture(
        str(page_path), '## Page architecture\n\nIntent.\n',
        canon_ids=['panel-registers'],
    )
    text = page_path.read_text()
    assert 'reference/canon/style-foundation.md' in text
    assert 'reference/canon/panel-registers.md' in text
    assert 'canon_referenced:  -' not in text
    assert 'canon_referenced:\n' in text


def test_splice_skips_duplicate_canon_referenced(tmp_path):
    from storyforge.cmd_elaborate import _splice_page_architecture
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "canon_referenced:\n"
        "  - reference/canon/panel-registers.md\n"
        "---\n\n"
        "## Scene context\n\nBeat.\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
    _splice_page_architecture(
        str(page_path), '## Page architecture\n\nIntent.\n',
        canon_ids=['panel-registers'],
    )
    text = page_path.read_text()
    assert text.count('reference/canon/panel-registers.md') == 1


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def test_validate_llm_response_accepts_well_formed():
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = '## Page architecture\n\n### Intent\nQuiet.\n'
    ok, section = _validate_architecture_response(resp)
    assert ok is True
    assert '## Page architecture' in section


def test_validate_llm_response_accepts_parenthetical_header():
    """The v3 hand-authored '## Page architecture (authoring context)'
    must validate."""
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = '## Page architecture (authoring context)\n\n### Intent\nQuiet.\n'
    ok, _ = _validate_architecture_response(resp)
    assert ok is True


def test_validate_llm_response_rejects_missing_header():
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = 'Intent only, no header.\n'
    ok, _ = _validate_architecture_response(resp)
    assert ok is False


def test_validate_response_rejects_inline_header():
    """A '## Page architecture' substring buried mid-line should NOT pass."""
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = 'preamble ## Page architecture suffix\n'
    ok, _ = _validate_architecture_response(resp)
    assert ok is False


def test_validate_response_strips_plain_triple_backtick_fence():
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = '```\n## Page architecture\n\nIntent.\n```\n'
    ok, section = _validate_architecture_response(resp)
    assert ok is True
    assert '```' not in section


def test_validate_response_strips_markdown_fence():
    from storyforge.cmd_elaborate import _validate_architecture_response
    resp = '```markdown\n## Page architecture\n\nIntent.\n```\n'
    ok, section = _validate_architecture_response(resp)
    assert ok is True
    assert '```' not in section


# ---------------------------------------------------------------------------
# Full handler (mocked API)
# ---------------------------------------------------------------------------

def test_run_page_architecture_end_to_end_with_mocked_api(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn

    canned_response = (
        '## Page architecture\n\n### Intent\nMocked intent.\n\n'
        '### Panel hierarchy\n- Panel 1 — dominant: focus\n'
        '- Panel 2 — atmospheric: ambience\n\n'
        '### Layout\nTwo-row grid; eye flow left-to-right; opening recto.\n'
    )
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: canned_response)
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)

    proj = _make_gn_project(tmp_path)
    _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )

    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Page architecture' in text
    assert 'Mocked intent' in text
    assert 'Page-blocking prompt' not in text
    assert 'canon_referenced:' in text
    assert 'reference/canon/panel-registers.md' in text
    # Inserted before the panel script
    assert text.index('## Page architecture') < text.index('## Panel script')


def test_dry_run_prints_prompt_and_does_not_write(tmp_path, capsys):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    _run_page_architecture_handler_gn(
        proj, dry_run=True, coaching='full',
        page=None, scene=None, force=False,
    )
    captured = capsys.readouterr()
    assert 'Page architecture' in captured.out
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
    assert call_count['n'] == 0
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Page architecture' in text
    assert 'TODO register: TODO role' in text


def test_coach_mode_writes_brief_no_page_mutation(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: 'should not be called')
    proj = _make_gn_project(tmp_path)
    _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='coach',
        page=None, scene=None, force=False,
    )
    text = open(os.path.join(proj, 'pages', 's01-p1.md')).read()
    assert '## Page architecture' not in text
    brief_path = os.path.join(proj, 'working', 'coaching',
                              'page-architecture-s01-p1.md')
    assert os.path.isfile(brief_path)
    assert 'Which panel' in open(brief_path).read()


# ---------------------------------------------------------------------------
# Exit-code semantics
# ---------------------------------------------------------------------------

def test_handler_returns_zero_for_successful_run(tmp_path):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    rc = _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert rc == 0


def test_handler_returns_one_when_all_pages_skipped_on_precondition(tmp_path):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    briefs = os.path.join(proj, 'reference', 'scene-briefs.csv')
    with open(briefs) as f:
        text = f.read()
    with open(briefs, 'w') as f:
        f.write(text.replace('p1: 2-panel', ''))
    rc = _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert rc == 1


def test_handler_returns_one_when_all_pages_fail_llm_validation(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    monkeypatch.setattr('storyforge.api.invoke_api', lambda *a, **kw: '')
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)
    rc = _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )
    assert rc == 1


def test_full_mode_bad_llm_response_does_not_mutate_page(tmp_path, monkeypatch):
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    monkeypatch.setattr('storyforge.api.invoke_api',
                        lambda *a, **kw: 'malformed response')
    monkeypatch.setattr('storyforge.cmd_elaborate.log_operation',
                        lambda *a, **kw: None, raising=False)
    _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='full',
        page=None, scene=None, force=False,
    )
    assert '## Page architecture' not in open(
        os.path.join(proj, 'pages', 's01-p1.md')).read()


def test_page_architecture_stage_exits_on_novel_medium(tmp_path):
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
        _run_main_stage('page-architecture', str(proj), str(proj / 'reference'),
                        dry_run=False, interactive=False, seed='', args=args)
    assert exc.value.code == 1
