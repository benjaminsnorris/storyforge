"""#551: `elaborate --stage voice` (Gawain G-017: the voice guide and
profile were written by hand), and stages set the artifact flags they fill
(Beowulf B-017: every artifact read exists: false after architecture)."""

import os

import pytest

from storyforge.cmd_elaborate import VALID_STAGES, main

VOICE_REPLY = (
    '```voice-guide\n# Voice Guide\n\nPlain, cold, exact.\n```\n'
    '```voice-profile-csv\n'
    'character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style\n'
    '_project||suddenly;very|||spare;cold|\n'
    'dorren-hayle|map;grid|||short||clipped\n'
    '```\n'
)


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


def test_the_voice_stage_writes_the_guide_and_profile(novel, mock_api):
    phase_before = [l for l in _read(novel, 'storyforge.yaml').splitlines()
                    if l.startswith('phase:')]
    _run(mock_api, 'voice', VOICE_REPLY)
    assert 'Plain, cold, exact.' in _read(novel, 'reference/voice-guide.md')
    profile = _read(novel, 'reference/voice-profile.csv')
    assert profile.splitlines()[2] == 'dorren-hayle|map;grid|||short||clipped'
    assert [l for l in _read(novel, 'storyforge.yaml').splitlines()
            if l.startswith('phase:')] == phase_before


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
