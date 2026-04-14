import os


def test_voice_profile_fixture_exists(fixture_dir):
    """Test fixture includes a voice profile."""
    path = os.path.join(fixture_dir, 'reference', 'voice-profile.csv')
    assert os.path.isfile(path)


def test_voice_profile_schema(fixture_dir):
    """Voice profile has correct columns."""
    path = os.path.join(fixture_dir, 'reference', 'voice-profile.csv')
    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    header = lines[0].split('|')
    assert header == [
        'character', 'preferred_words', 'banned_words', 'metaphor_families',
        'rhythm_preference', 'register', 'dialogue_style',
    ]


def test_voice_profile_has_project_row(fixture_dir):
    """Voice profile has a _project row."""
    path = os.path.join(fixture_dir, 'reference', 'voice-profile.csv')
    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    characters = [l.split('|')[0] for l in lines[1:]]
    assert '_project' in characters


def test_validate_voice_profile_valid(fixture_dir):
    """validate_voice_profile passes on a well-formed file."""
    from storyforge.schema import validate_voice_profile
    result = validate_voice_profile(fixture_dir)
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
