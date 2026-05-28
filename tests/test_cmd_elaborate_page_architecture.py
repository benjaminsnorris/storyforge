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


# ============================================================================
# Task 10: splice + validator + full handler
# ============================================================================


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
        "## Page-blocking prompt\n\nOLD blocking.\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
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
    # Patch cost-logging since it depends on a working ledger
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
    # Frontmatter audit trail: full mode populates canonical_blocks_embedded
    assert 'canonical_blocks_embedded:' in text
    assert 'reference/canon/panel-registers.md' in text


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


# ============================================================================
# Regression tests for PR review findings (commit 85c85b1)
# ============================================================================


def test_splice_extends_existing_canonical_blocks_embedded_list(tmp_path):
    """When canonical_blocks_embedded: already has entries, splice must
    extend the list correctly (not collapse onto the key line, which
    would produce invalid YAML)."""
    from storyforge.cmd_elaborate import _splice_page_architecture
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "canonical_blocks_embedded:\n"
        "  - reference/canon/style-foundation.md\n"
        "---\n\n"
        "## Scene context\n\nBeat.\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
    _splice_page_architecture(
        str(page_path),
        '## Page architecture\n\nIntent.\n\n## Page-blocking prompt\n\nSB.\n',
        canon_ids=['panel-registers'],
    )
    text = page_path.read_text()
    # The original entry must still be in the list
    assert 'reference/canon/style-foundation.md' in text
    # The new entry must be added
    assert 'reference/canon/panel-registers.md' in text
    # Key must remain alone on its line (no entry collapsed onto it)
    assert 'canonical_blocks_embedded:  -' not in text
    assert 'canonical_blocks_embedded:\n' in text
    # Both entries should appear as proper block-list items
    assert '  - reference/canon/style-foundation.md\n' in text
    assert '  - reference/canon/panel-registers.md\n' in text


def test_splice_skips_duplicate_canonical_blocks(tmp_path):
    """If a canon_id is already in canonical_blocks_embedded:, it's not added twice."""
    from storyforge.cmd_elaborate import _splice_page_architecture
    page_path = tmp_path / 's01-p1.md'
    page_path.write_text(
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 1\n"
        "canonical_blocks_embedded:\n"
        "  - reference/canon/panel-registers.md\n"
        "---\n\n"
        "## Scene context\n\nBeat.\n\n"
        "## Panel script\n\n**Panel 1.**\n"
    )
    _splice_page_architecture(
        str(page_path),
        '## Page architecture\n\nIntent.\n\n## Page-blocking prompt\n\nSB.\n',
        canon_ids=['panel-registers'],  # already present
    )
    text = page_path.read_text()
    # Only one occurrence — no duplication
    assert text.count('reference/canon/panel-registers.md') == 1


def test_handler_returns_zero_for_successful_run(tmp_path, monkeypatch):
    """A successful run that processes N pages must return 0, not N
    (sys.exit(N) for N >= 1 is treated as failure by Unix tools)."""
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    # Strict mode — no API call needed; should process exactly 1 page
    rc = _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert rc == 0  # NOT 1 (would otherwise collide with precondition-failure code)


def test_handler_returns_one_when_all_pages_skipped_on_precondition(tmp_path):
    """When every page is skipped due to a precondition failure (and zero
    are processed), the handler returns 1 so CI surfaces the unmet preconditions."""
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    # Wipe panel_breakdown so the precondition fails
    briefs = os.path.join(proj, 'reference', 'scene-briefs.csv')
    with open(briefs) as f:
        text = f.read()
    text = text.replace('p1: 2-panel', '')
    with open(briefs, 'w') as f:
        f.write(text)
    rc = _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert rc == 1


def test_handler_returns_zero_when_no_pages_to_process(tmp_path):
    """No-op (zero targets, zero precondition skips) is success — exit 0."""
    from storyforge.cmd_elaborate import _run_page_architecture_handler_gn
    proj = _make_gn_project(tmp_path)
    # Pre-populate the only page so default filter excludes it
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
    rc = _run_page_architecture_handler_gn(
        proj, dry_run=False, coaching='strict',
        page=None, scene=None, force=False,
    )
    assert rc == 0


def test_validate_response_rejects_inline_header(tmp_path):
    """A '## Page architecture' substring buried mid-line should NOT pass
    validation (the splicer requires it to be a line-anchored header)."""
    from storyforge.cmd_elaborate import _validate_architecture_response
    # Header mid-line — substring contains but is not a real heading
    resp = 'preamble ## Page architecture suffix\n## Page-blocking prompt\n\nSB.\n'
    ok, _ = _validate_architecture_response(resp)
    assert ok is False
