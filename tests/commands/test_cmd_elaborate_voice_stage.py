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
