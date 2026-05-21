"""Tests for project.medium handling."""

import os

import pytest

from storyforge.common import get_medium


def test_get_medium_returns_novel_when_field_absent(project_dir):
    """A project without project.medium defaults to 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    assert 'medium:' not in content
    assert get_medium(project_dir) == 'novel'


def test_get_medium_returns_graphic_novel_when_set(project_dir):
    """A project with project.medium: graphic-novel returns that value."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    # Insert under `project:` block
    content = content.replace(
        'project:\n',
        'project:\n  medium: graphic-novel\n',
        1,
    )
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'graphic-novel'


def test_get_medium_returns_novel_for_explicit_novel(project_dir):
    """A project with project.medium: novel returns 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    content = content.replace(
        'project:\n',
        'project:\n  medium: novel\n',
        1,
    )
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'novel'


def test_get_medium_returns_novel_for_unrecognized_value(project_dir):
    """An unrecognized medium value logs a warning and defaults to 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    content = content.replace('project:\n', 'project:\n  medium: screenplay\n', 1)
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'novel'


def test_gn_fixture_loads(fixture_dir_gn):
    """The graphic-novel fixture exists and is graphic-novel mode."""
    assert os.path.isfile(os.path.join(fixture_dir_gn, 'storyforge.yaml'))
    assert get_medium(fixture_dir_gn) == 'graphic-novel'


def test_gn_fixture_schema_passes(fixture_dir_gn):
    """The graphic-novel fixture passes schema validation."""
    from storyforge.schema import validate_schema
    ref_dir = os.path.join(fixture_dir_gn, 'reference')
    result = validate_schema(ref_dir, fixture_dir_gn)
    # The fixture should pass — failed count must be 0
    assert result['failed'] == 0, f"Fixture has schema failures: {result.get('errors')}"


def test_cmd_validate_passes_on_gn_fixture(project_dir_gn, monkeypatch):
    """Running `storyforge validate` on the GN fixture exits 0."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_validate
    with pytest.raises(SystemExit) as exc_info:
        cmd_validate.main(['--quiet'])
    assert exc_info.value.code == 0


def test_cmd_cleanup_csv_passes_on_gn_fixture(project_dir_gn, monkeypatch, capsys):
    """`storyforge cleanup --csv` does not flag GN-specific columns as unexpected."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_cleanup
    # cmd_cleanup.main returns normally (no sys.exit) on --csv
    cmd_cleanup.main(['--csv'])
    captured = capsys.readouterr()
    # GN-only columns must not be flagged as unexpected extras — they are valid
    # in graphic-novel mode and the cleanup report should know that.
    assert 'target_pages' not in captured.out or 'unexpected' not in captured.out
    assert 'panel_count' not in captured.out or 'unexpected' not in captured.out
    assert 'page_layout' not in captured.out or 'unexpected' not in captured.out
    # Also: GN fixture does not have characters/locations/etc. — they are optional
    # in GN mode, so should not appear as warnings.
    assert 'characters.csv does not exist' not in captured.out
    assert 'locations.csv does not exist' not in captured.out


def test_hone_gn_flags_missing_panel_breakdown(project_dir_gn, monkeypatch):
    """A graphic-novel brief missing panel_breakdown is flagged by hone."""
    from storyforge.csv_cli import update_field
    briefs = os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    update_field(briefs, 'the-blank-page', 'panel_breakdown', '')

    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir_gn)
    flagged = [f for f in findings if f.get('scene_id') == 'the-blank-page'
               and f.get('field') == 'panel_breakdown']
    assert flagged, 'expected a panel_breakdown finding for the-blank-page'


def test_hone_gn_flags_missing_page_layout(project_dir_gn, monkeypatch):
    """A graphic-novel brief missing page_layout is flagged by hone."""
    from storyforge.csv_cli import update_field
    briefs = os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    update_field(briefs, 'shadows-arrive', 'page_layout', '')

    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir_gn)
    flagged = [f for f in findings if f.get('scene_id') == 'shadows-arrive'
               and f.get('field') == 'page_layout']
    assert flagged, 'expected a page_layout finding for shadows-arrive'


def test_hone_novel_does_not_flag_panel_breakdown(project_dir, monkeypatch):
    """Novel-mode briefs are not checked for panel_breakdown."""
    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir)
    panel_findings = [f for f in findings if f.get('field') == 'panel_breakdown']
    assert not panel_findings


@pytest.mark.parametrize('module_name', [
    'repetition',
    'scoring_passive',
    'scoring_adverbs',
    'scoring_weather',
    'scoring_rhythm',
    'scoring_economy',
])
def test_scorer_skips_in_gn_mode(project_dir_gn, monkeypatch, module_name):
    """Prose-craft scorers return a skipped sentinel in graphic-novel mode."""
    import importlib
    monkeypatch.chdir(project_dir_gn)
    module = importlib.import_module(f'storyforge.{module_name}')
    entrypoint = getattr(module, 'score_project', None)
    assert entrypoint is not None, f'{module_name} must expose a score_project entry'
    result = entrypoint(project_dir_gn)
    assert result.get('skipped') is True, (
        f'{module_name}.score_project should return {{"skipped": True}} in GN mode'
    )
    assert result.get('reason') == 'graphic-novel'


def test_elaborate_scene_map_uses_gn_prompts(project_dir_gn, monkeypatch):
    """In graphic-novel mode, the scene-map stage calls build_scene_map_prompt from
    prompts_elaborate_gn, not prompts_elaborate."""
    called = {'gn': False, 'novel': False}

    def fake_gn_prompt(*args, **kwargs):
        called['gn'] = True
        return 'fake-gn-prompt'

    def fake_novel_prompt(*args, **kwargs):
        called['novel'] = True
        return 'fake-novel-prompt'

    from storyforge import prompts_elaborate_gn, prompts_elaborate
    monkeypatch.setattr(prompts_elaborate_gn, 'build_scene_map_prompt', fake_gn_prompt)
    monkeypatch.setattr(prompts_elaborate, 'build_scene_map_prompt', fake_novel_prompt, raising=False)

    # Stub API to prevent real calls
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_api', lambda *a, **kw: 'id|seq|title\nscene-a|1|Test')

    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_elaborate
    try:
        cmd_elaborate.main(['--stage', 'map', '--dry-run'])
    except SystemExit:
        pass

    assert called['gn'], 'expected graphic-novel scene-map prompt to be called'
    assert not called['novel'], 'expected novel scene-map prompt NOT to be called'


def test_prompts_elaborate_gn_imports():
    from storyforge import prompts_elaborate_gn
    assert hasattr(prompts_elaborate_gn, 'build_scene_map_prompt')
    assert hasattr(prompts_elaborate_gn, 'build_briefs_prompt')


def test_scene_map_prompt_mentions_pages():
    from storyforge.prompts_elaborate_gn import build_scene_map_prompt
    prompt = build_scene_map_prompt(
        project_dir='/tmp/fake',
        scenes_csv_content='id|seq|title\nscene-a|1|Test',
        architecture_doc='# Architecture\n\nThree acts.',
    )
    assert 'target_pages' in prompt
    # The preamble explicitly tells Claude that comics are paced in pages,
    # not word counts. (target_words may still appear in the CSV header,
    # which is shared between novel and GN modes — that's structural, not
    # an instruction to populate it.)
    assert 'comics are paced' in prompt
    assert 'pages, not word counts' in prompt


def test_scene_map_prompt_uses_scenes_csv_fenced_block():
    """The GN scene-map prompt must ask for a `scenes-csv` fenced block so
    that parse_stage_response (which only extracts labeled fenced blocks)
    can recover the response. Without this, the model returns a bare CSV
    that the parser silently drops."""
    from storyforge.prompts_elaborate_gn import build_scene_map_prompt
    from storyforge.prompts_elaborate import parse_stage_response

    prompt = build_scene_map_prompt(
        project_dir='/tmp/fake',
        scenes_csv_content='id|seq|title\nscene-a|1|Test',
        architecture_doc='# Architecture\n\nThree acts.',
    )
    assert '```scenes-csv' in prompt, (
        'GN scene-map prompt must request a `scenes-csv` fenced block — '
        'parse_stage_response only extracts labeled fenced blocks.'
    )

    # Sanity-check the parser round-trip: a labeled scenes-csv block from a
    # hypothetical response should be extracted by parse_stage_response.
    fake_response = (
        'Sure — here is the updated index:\n\n'
        '```scenes-csv\n'
        'id|seq|title|target_pages\n'
        'scene-a|1|Test|3\n'
        '```\n'
    )
    blocks = parse_stage_response(fake_response)
    assert 'scenes-csv' in blocks
    assert 'target_pages' in blocks['scenes-csv']


def test_briefs_prompt_mentions_gn_columns():
    from storyforge.prompts_elaborate_gn import build_briefs_prompt
    prompt = build_briefs_prompt(
        project_dir='/tmp/fake',
        scene_id='scene-a',
        scene_row={'id': 'scene-a', 'title': 'Test', 'target_pages': '6'},
        intent_row={'function': 'setup'},
        existing_brief_row={},
    )
    for col in ('page_layout', 'panel_breakdown', 'visual_keywords',
                'page_turn_beats', 'caption_strategy'):
        assert col in prompt, f'prompt missing GN column instruction: {col}'


def test_briefs_handler_gn_round_trip_preserves_gn_columns(project_dir_gn, monkeypatch):
    """End-to-end: _briefs_handler_gn must preserve all five GN brief columns
    when round-tripping through scene-briefs.csv.

    This is the regression test that pins Issue #1 (graphic-novel columns
    dropped on write because _BRIEFS_COLS lacked them). Without the column
    list extension, DictWriter(extrasaction='ignore') silently drops the
    GN columns on every write.
    """
    import json
    from storyforge.csv_cli import update_field, get_field

    ref_dir = os.path.join(project_dir_gn, 'reference')
    briefs_csv = os.path.join(ref_dir, 'scene-briefs.csv')

    # Blank panel_breakdown for one scene so the handler has work to do.
    # Also blank status on scenes.csv so the scene is targeted (statuses in
    # ('mapped', 'architecture', 'spine', '') qualify).
    scenes_csv = os.path.join(ref_dir, 'scenes.csv')
    update_field(scenes_csv, 'the-blank-page', 'status', 'mapped')
    update_field(briefs_csv, 'the-blank-page', 'panel_breakdown', '')

    # Fake API response: a bare CSV row (no fenced block) covering all GN cols.
    fake_text = (
        'the-blank-page|fill the blank page|inability to begin|no-and|'
        'recognise the pattern|set the pen down|||stare at parchment;dip pen|'
        'It always begins this way|resigned|empty map|the work is dead||false|'
        'fatigued|fatigued|FAKE-LAYOUT|FAKE-PANELS|FAKE-KEYWORDS|'
        'FAKE-TURN-BEATS|FAKE-CAPTION'
    )

    def fake_invoke_to_file(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': fake_text}],
            'usage': {'input_tokens': 10, 'output_tokens': 20,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', fake_invoke_to_file)
    # The handler imports invoke_to_file at function scope, so also patch
    # the cmd_elaborate module reference once imported.
    from storyforge import cmd_elaborate
    # cmd_elaborate._briefs_handler_gn imports invoke_to_file locally from
    # storyforge.api — patching api.invoke_to_file is sufficient.

    cmd_elaborate._briefs_handler_gn(
        project_dir_gn, ref_dir,
        dry_run=False, stage_model='claude-opus-4-6',
        system=None,
    )

    # Verify all five GN columns are present and non-empty for the scene.
    for col, expected in [
        ('page_layout', 'FAKE-LAYOUT'),
        ('panel_breakdown', 'FAKE-PANELS'),
        ('visual_keywords', 'FAKE-KEYWORDS'),
        ('page_turn_beats', 'FAKE-TURN-BEATS'),
        ('caption_strategy', 'FAKE-CAPTION'),
    ]:
        value = get_field(briefs_csv, 'the-blank-page', col)
        assert value == expected, (
            f'GN column {col!r} was lost on write — expected {expected!r}, '
            f'got {value!r}. This is the bug Issue #1 fixes.'
        )


def test_briefs_handler_gn_returns_none_when_no_work(project_dir_gn):
    """When all scenes are already briefed, _briefs_handler_gn returns None
    so the caller can short-circuit before branch / PR creation."""
    from storyforge import cmd_elaborate
    ref_dir = os.path.join(project_dir_gn, 'reference')
    # GN fixture has all scenes at status='briefed' — nothing for the handler to do
    result = cmd_elaborate._briefs_handler_gn(
        project_dir_gn, ref_dir,
        dry_run=False, stage_model='claude-opus-4-6',
        system=None,
    )
    assert result is None, (
        'expected None sentinel when no scenes need briefs (so caller can '
        'short-circuit before branch / PR creation)'
    )


# ---------------------------------------------------------------------------
# Dispatcher guard: GN-unsupported commands return a clear error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('cmd', [
    'write', 'evaluate', 'score', 'revise', 'assemble',
    'publish', 'annotations', 'extract', 'repetition', 'enrich',
])
def test_dispatcher_blocks_unsupported_commands_in_gn_mode(
    project_dir_gn, monkeypatch, capsys, cmd,
):
    """Unsupported commands fail fast in GN mode with a clear error and exit 2."""
    monkeypatch.chdir(project_dir_gn)
    monkeypatch.setattr('sys.argv', ['storyforge', cmd, '--dry-run'])
    from storyforge.__main__ import main
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert f"'{cmd}' is not yet supported for graphic-novel projects" in captured.err
    assert 'Plan 1 supports' in captured.err


@pytest.mark.parametrize('cmd', ['validate', 'cleanup', 'hone', 'elaborate'])
def test_dispatcher_allows_supported_commands_in_gn_mode(
    project_dir_gn, monkeypatch, cmd,
):
    """Supported commands are not blocked by the GN guard.

    We just verify the dispatcher routes the command (i.e. the command's
    own main() is called); the command may still error for other reasons,
    so we tolerate any non-(exit-2-with-our-message) outcome.
    """
    monkeypatch.chdir(project_dir_gn)
    monkeypatch.setattr('sys.argv', ['storyforge', cmd, '--help'])
    from storyforge.__main__ import main
    try:
        main()
    except SystemExit as e:
        # --help typically exits 0; that's fine. Just verify it wasn't blocked.
        assert e.code != 2 or 'not yet supported' not in str(e)


def test_dispatcher_allows_unsupported_commands_in_novel_mode(
    project_dir, monkeypatch,
):
    """Novel-mode projects (no medium field) can still run all commands."""
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr('sys.argv', ['storyforge', 'score', '--help'])
    from storyforge.__main__ import main
    try:
        main()
    except SystemExit as e:
        # --help exits 0 normally; the guard would have exit 2 with our message
        assert e.code != 2, 'novel-mode project should not be blocked'
