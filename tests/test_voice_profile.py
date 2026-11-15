"""voice-profile.csv: a graphic novel's script still has one (and
`validate_voice_profile` checks it); a prose book's isn't read any more (the
voice is reference/voice/, ready-to-draft plan 2026-11-14)."""

import os

PROFILE = (
    'character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|'
    'dialogue_style\n'
    '_project||journey;beacon|||literary;restrained|\n'
    'dorren-hayle|calibrated;systematic||cartography|short declarative||clipped\n'
    'tessa-merrin|gritty;rough||weather|longer sensory runs||casual\n'
)


def _profile(project_dir):
    path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(PROFILE)
    return path


def test_validate_voice_profile_valid(project_dir):
    """validate_voice_profile passes on a well-formed file."""
    from storyforge.schema import validate_voice_profile
    _profile(project_dir)
    result = validate_voice_profile(project_dir)
    assert result['errors'] == []
    assert result['has_project_row'] is True
    assert result['character_count'] >= 2


def test_validate_voice_profile_missing_project_row(tmp_path):
    """validate_voice_profile flags missing _project row."""
    from storyforge.schema import validate_voice_profile
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    vp = ref_dir / 'voice-profile.csv'
    vp.write_text(
        'character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style\n'
        'some-char|word1;word2||metaphor1|||casual\n'
    )
    result = validate_voice_profile(str(tmp_path))
    assert result['has_project_row'] is False
    assert any('_project' in e['message'] for e in result['errors'])


def test_validate_voice_profile_bad_header(tmp_path):
    """validate_voice_profile flags wrong columns."""
    from storyforge.schema import validate_voice_profile
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    vp = ref_dir / 'voice-profile.csv'
    vp.write_text('character|wrong_col\n_project|\n')
    result = validate_voice_profile(str(tmp_path))
    assert any('column' in e['message'].lower() or 'missing' in e['message'].lower()
               for e in result['errors'])


def test_validate_voice_profile_duplicate_character(tmp_path):
    """validate_voice_profile flags duplicate character rows."""
    from storyforge.schema import validate_voice_profile
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    vp = ref_dir / 'voice-profile.csv'
    vp.write_text(
        'character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style\n'
        '_project||banned1|||literary|\n'
        'char-a|word1||meta1|||casual\n'
        'char-a|word2||meta2|||formal\n'
    )
    result = validate_voice_profile(str(tmp_path))
    assert any('duplicate' in e['message'].lower() for e in result['errors'])


def test_validate_voice_profile_missing_file(tmp_path):
    """validate_voice_profile returns gracefully when file missing."""
    from storyforge.schema import validate_voice_profile
    result = validate_voice_profile(str(tmp_path))
    assert result['errors'] == []
    assert result['has_project_row'] is False
    assert result['character_count'] == 0




# --- a prose book: the profile is no longer read ---

def test_drafting_prompts_leave_out_a_left_over_profile(project_dir, plugin_dir):
    from storyforge.prompts import build_scene_prompt, build_scene_prompt_from_briefs
    _profile(project_dir)
    for prompt in (build_scene_prompt('act1-sc01', project_dir, api_mode=True),
                   build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)):
        assert 'CHARACTER VOICE' not in prompt and 'PROSE REGISTER' not in prompt
        assert 'calibrated' not in prompt and 'journey' not in prompt


def test_naturalness_and_polish_leave_out_a_left_over_profile(project_dir):
    from storyforge.cmd_revise import _build_naturalness_pass3_guidance, _generate_polish_plan
    _profile(project_dir)
    assert 'journey' not in _build_naturalness_pass3_guidance()
    rows = _generate_polish_plan('', write=False)
    assert 'journey' not in rows[0]['guidance']

