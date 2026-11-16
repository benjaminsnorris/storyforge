"""#551 and the ready-to-draft plan (2026-11-14): `elaborate --stage voice`
sets up a prose book's reference/voice/ (no model writes the voice), and
stages set the artifact flags they fill (Beowulf B-017: every artifact read
exists: false after architecture)."""

import os

import pytest

from storyforge.cmd_elaborate import VALID_STAGES, main

@pytest.fixture
def novel(project_dir, monkeypatch, mock_git, mock_costs):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    return project_dir


def _run(mock_api, stage, reply):
    mock_api.set_response(reply)
    try:
        main(['--stage', stage])
    except SystemExit:
        pass


def _read(proj, rel):
    with open(os.path.join(proj, rel), encoding='utf-8') as f:
        return f.read()


def test_voice_is_a_stage():
    assert 'voice' in VALID_STAGES


def test_the_voice_stage_sets_up_the_folder_and_calls_no_model(novel, mock_api, mock_git,
                                                             capsys):
    import shutil
    shutil.rmtree(os.path.join(novel, 'reference', 'voice'))
    phase_before = [l for l in _read(novel, 'storyforge.yaml').splitlines()
                    if l.startswith('phase:')]
    _run(mock_api, 'voice', 'unused')
    assert mock_api.calls == []
    assert 'What the voice does' in _read(novel, 'reference/voice/book.md')
    assert os.path.isfile(os.path.join(novel, 'reference', 'voice', 'checks.md'))
    assert os.path.isdir(os.path.join(novel, 'reference', 'voice', 'anchors'))
    assert not os.path.exists(os.path.join(novel, 'reference', 'voice-guide.md'))
    out = capsys.readouterr().out
    assert "The voice isn't ready: reference/voice/book.md is still init's template" in out
    commits = [c for c in mock_git.calls if c[0] == 'commit_and_push']
    assert commits and 'reference/voice/book.md' in commits[-1][2]
    assert [l for l in _read(novel, 'storyforge.yaml').splitlines()
            if l.startswith('phase:')] == phase_before


def test_the_voice_stage_never_writes_over_the_authors_voice(novel, mock_api, mock_git,
                                                             capsys):
    before = _read(novel, 'reference/voice/book.md')
    _run(mock_api, 'voice', 'unused')
    assert _read(novel, 'reference/voice/book.md') == before
    assert 'The voice is ready: reference/voice' in capsys.readouterr().out
    assert not [c for c in mock_git.calls if c[0] == 'commit_and_push']


def _solid_map(monkeypatch, state='solid'):
    from storyforge import status
    monkeypatch.setattr(status, 'ladder_states', lambda pd, medium='novel', floors=None: [
        {'level': lvl, 'name': name, 'state': state if lvl == 5 else 'solid', 'detail': ''}
        for lvl, name in status.LEVEL_NAMES.items()])


def test_the_voice_stage_runs_the_check_after_the_map(novel, mock_api, capsys, monkeypatch):
    # #656: the fixture's map has Kael Maren as a POV; book.md names Dorren
    # and Tessa only
    _solid_map(monkeypatch)
    _run(mock_api, 'voice', 'unused')
    out = capsys.readouterr().out
    assert ('The voice check after the map: reference/voice/book.md says nothing of 1 '
            'POV(s): Kael Maren') in out
    with open(os.path.join(novel, 'reference', 'voice', 'book.md'), 'a') as f:
        f.write('\n- **Kael** speaks in the archive\'s hush.\n')
    _run(mock_api, 'voice', 'unused')
    # SF-3: a clean check is said, not silent
    assert ('The voice check after the map: reference/voice/book.md names every POV of '
            'the map.') in capsys.readouterr().out
    assert mock_api.calls == []


def test_the_voice_stage_waits_for_the_map_to_run_the_check(novel, mock_api, capsys,
                                                           monkeypatch):
    # SF-3/C-5: no check on a partial map; it says when the check comes
    _solid_map(monkeypatch, 'thin')
    _run(mock_api, 'voice', 'unused')
    out = capsys.readouterr().out
    assert 'The voice check after the map runs once the map is done (the scene map is thin)' \
        in out
    assert 'says nothing of' not in out


def test_the_voice_stage_on_a_characters_csv_it_cant_read_is_an_error(novel, mock_api, capsys,
                                                                     monkeypatch):
    # SF-5: a bad byte was a traceback
    _solid_map(monkeypatch)
    with open(os.path.join(novel, 'reference', 'characters.csv'), 'wb') as f:
        f.write(b'id|name|aliases\n\xff|x|\n')
    with pytest.raises(SystemExit) as e:
        main(['--stage', 'voice'])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert 'ERROR:' in out and 'characters.csv' in out and "can't run" in out


def test_the_voice_stage_before_the_map_names_the_moment_rounds(novel, mock_api, capsys):
    import shutil
    shutil.rmtree(os.path.join(novel, 'reference', 'voice'))
    os.remove(os.path.join(novel, 'reference', 'scenes.csv'))
    _run(mock_api, 'voice', 'unused')
    out = capsys.readouterr().out
    assert '--moment "..."` before the scene map' in out
    assert 'The voice check after the map' not in out


def test_the_voice_stage_notes_old_voice_files(novel, mock_api, capsys):
    with open(os.path.join(novel, 'reference', 'voice-guide.md'), 'w') as f:
        f.write('# Old\n')
    _run(mock_api, 'voice', 'unused')
    assert 'NOTE: reference/voice-guide.md is no longer read' in capsys.readouterr().out
    assert os.path.isfile(os.path.join(novel, 'reference', 'voice-guide.md'))


def _artifact(proj, name):
    lines = _read(proj, 'storyforge.yaml').splitlines()
    i = lines.index(f'  {name}:')
    return {l.split(':', 1)[0].strip(): l.split(':', 1)[1].strip() for l in lines[i + 1:i + 4]}


ARCH_REPLY = (
    '```scenes-csv\n'
    'id|seq|title|summary|act|pov|spine_event|status\n'
    'act1-sc01|1|The Game|A game.|1|Dorren Hayle|act1-sc01|architecture\n'
    '```\n'
    '```story-architecture\n# Story Architecture\n\nThree acts.\n```\n'
)


def test_a_stage_sets_the_flags_of_what_it_wrote(novel, mock_api):
    assert _artifact(novel, 'story_architecture')['exists'] == 'false'
    _run(mock_api, 'architecture', ARCH_REPLY)
    entry = _artifact(novel, 'story_architecture')
    assert entry['exists'] == 'true' and entry['updated']
    assert _artifact(novel, 'systems_bible')['exists'] == 'false'


# --- #656: the narrator stance the voice settles feeds the POVs ---

@pytest.mark.parametrize('build', ['build_architecture_prompt', 'build_map_prompt'])
@pytest.mark.parametrize('system_context', [False, True])
def test_the_voice_feeds_the_povs_of_the_architecture_and_map(project_dir, build,
                                                             system_context):
    import shutil
    from storyforge import prompts_elaborate as pe
    plugin = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    voiced = getattr(pe, build)(project_dir, plugin, system_context=system_context)
    assert pe.VOICE_POV_RULE in voiced
    # without the author's book.md the prompt is as it was (the eval
    # recordings replay): the rule line is all that differs
    shutil.rmtree(os.path.join(project_dir, 'reference', 'voice'))
    from storyforge import voice_book
    voice_book.scaffold(project_dir)   # init's template is no voice
    plain = getattr(pe, build)(project_dir, plugin, system_context=system_context)
    assert pe.VOICE_POV_RULE not in plain
    if system_context:   # book.md is in the shared context, not the prompt
        assert voiced.replace(f'\n- {pe.VOICE_POV_RULE}', '') == plain


def test_a_graphic_novel_gets_no_voice_pov_rule(project_dir):
    from storyforge import prompts_elaborate as pe
    with open(os.path.join(project_dir, 'storyforge.yaml'), encoding='utf-8') as f:
        text = f.read()
    with open(os.path.join(project_dir, 'storyforge.yaml'), 'w', encoding='utf-8') as f:
        f.write(text.replace('project:\n', 'project:\n  medium: graphic-novel\n', 1))
    from storyforge.common import get_medium
    assert get_medium(project_dir) == 'graphic-novel'
    assert pe.voice_pov_rule(project_dir) == ''


def test_the_voice_stage_says_when_the_author_repo_has_no_book_md_text(novel, mock_api, capsys,
                                                                       monkeypatch):
    # SF-L: the POV rule and the check read book.md alone
    from storyforge import voice_book
    os.remove(os.path.join(novel, 'reference', 'voice', 'book.md'))
    monkeypatch.setattr(voice_book, 'resolve', lambda p: voice_book.DocState(
        'ok', 'reference/voice', 'reference/voice', 'THE AUTHOR VOICE', ()))
    monkeypatch.setattr(voice_book, 'scaffold', lambda p, dry_run=False: [])
    _solid_map(monkeypatch, 'thin')
    _run(mock_api, 'voice', 'unused')
    assert 'NOTE: the voice comes from the author repo, but reference/voice/book.md has no ' \
        'text yet' in capsys.readouterr().out
