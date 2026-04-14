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


def test_load_voice_profile(fixture_dir):
    """load_voice_profile returns project and character data."""
    from storyforge.prompts import load_voice_profile
    project, characters = load_voice_profile(fixture_dir)

    # Project-level data
    assert 'banned_words' in project
    assert 'journey' in project['banned_words']
    assert 'register' in project
    assert 'literary' in project['register']

    # Character data
    assert 'dorren-hayle' in characters
    assert 'tessa-merrin' in characters
    assert 'calibrated' in characters['dorren-hayle']['preferred_words']
    assert 'gritty' in characters['tessa-merrin']['preferred_words']


def test_load_voice_profile_missing_file(tmp_path):
    """load_voice_profile returns empty dicts when file missing."""
    from storyforge.prompts import load_voice_profile
    project, characters = load_voice_profile(str(tmp_path))
    assert project == {}
    assert characters == {}


def test_merge_banned_words(fixture_dir, plugin_dir):
    """Merged banned words include project + universal AI-tell list."""
    from storyforge.prompts import load_voice_profile, load_ai_tell_words, merge_banned_words
    project, _ = load_voice_profile(fixture_dir)
    ai_words = load_ai_tell_words(plugin_dir)
    merged = merge_banned_words(project, ai_words)

    # From project voice profile
    assert 'journey' in merged
    assert 'beacon' in merged
    # From universal AI-tell list (high severity)
    assert 'delve' in merged
    assert 'facilitate' in merged


def test_drafting_prompt_includes_voice_profile(project_dir, plugin_dir):
    """build_scene_prompt includes character voice constraints when profile exists."""
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    # The prompt should contain the project-level banned words merged with universal list
    assert 'journey' in prompt or 'VOCABULARY CONSTRAINT' in prompt


def test_drafting_prompt_includes_character_voice(project_dir, plugin_dir):
    """build_scene_prompt includes character-specific voice constraints."""
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    # act1-sc01 has POV "Dorren Hayle" -> voice profile key "dorren-hayle"
    assert 'CHARACTER VOICE' in prompt
    assert 'calibrated' in prompt  # dorren-hayle preferred word
    assert 'cartography' in prompt  # dorren-hayle metaphor family


def test_drafting_prompt_includes_register(project_dir, plugin_dir):
    """build_scene_prompt includes project register from voice profile."""
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    assert 'PROSE REGISTER' in prompt
    assert 'literary' in prompt


def test_drafting_prompt_merged_banned_words(project_dir, plugin_dir):
    """build_scene_prompt merges project banned words with AI-tell list."""
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    # Project banned word
    assert 'journey' in prompt
    # AI-tell word (high severity)
    assert 'delve' in prompt


def test_briefs_prompt_includes_voice_profile(project_dir, plugin_dir):
    """build_scene_prompt_from_briefs includes merged banned words."""
    from storyforge.prompts import build_scene_prompt_from_briefs
    prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
    assert 'journey' in prompt or 'VOCABULARY CONSTRAINT' in prompt


def test_briefs_prompt_includes_character_voice(project_dir, plugin_dir):
    """build_scene_prompt_from_briefs includes character voice constraints."""
    from storyforge.prompts import build_scene_prompt_from_briefs
    prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
    # act1-sc01 has POV "Dorren Hayle" -> voice profile key "dorren-hayle"
    assert 'CHARACTER VOICE' in prompt
    assert 'calibrated' in prompt  # dorren-hayle preferred word


def test_briefs_prompt_includes_register(project_dir, plugin_dir):
    """build_scene_prompt_from_briefs includes project register."""
    from storyforge.prompts import build_scene_prompt_from_briefs
    prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
    assert 'PROSE REGISTER' in prompt
    assert 'literary' in prompt


def test_naturalness_pass3_uses_project_banned_words(project_dir, plugin_dir):
    """Pass 3 guidance merges project banned words with universal list."""
    import os
    profile_path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    with open(profile_path, 'w') as f:
        f.write('character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style\n')
        f.write('_project||realm;visceral|||gritty;noir|\n')

    from storyforge.prompts import load_voice_profile, load_ai_tell_words, merge_banned_words
    project, _ = load_voice_profile(project_dir)
    ai_words = load_ai_tell_words(plugin_dir)
    merged = merge_banned_words(project, ai_words)

    assert 'realm' in merged
    assert 'visceral' in merged
    assert 'delve' in merged
