import os
import csv

def test_ai_tell_words_schema(plugin_dir):
    """Every row has required fields, valid category and severity."""
    path = os.path.join(plugin_dir, 'references', 'ai-tell-words.csv')
    assert os.path.isfile(path), f'Missing {path}'

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    assert len(lines) >= 2, 'Need header + at least one entry'

    header = lines[0].split('|')
    assert header == ['word', 'category', 'severity', 'replacement_hint'], \
        f'Unexpected header: {header}'

    valid_categories = {'vocabulary', 'hedging', 'structural'}
    valid_severities = {'high', 'medium'}
    seen_words = set()

    for i, line in enumerate(lines[1:], start=2):
        fields = line.split('|')
        assert len(fields) == 4, f'Line {i}: expected 4 fields, got {len(fields)}'
        word, category, severity, hint = fields
        assert word.strip(), f'Line {i}: empty word'
        assert category in valid_categories, \
            f'Line {i}: invalid category "{category}"'
        assert severity in valid_severities, \
            f'Line {i}: invalid severity "{severity}"'
        assert word not in seen_words, f'Line {i}: duplicate word "{word}"'
        seen_words.add(word)


def test_ai_tell_words_minimum_count(plugin_dir):
    """Sanity check: list should have at least 50 entries."""
    path = os.path.join(plugin_dir, 'references', 'ai-tell-words.csv')
    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    assert len(lines) - 1 >= 50, f'Expected 50+ entries, got {len(lines) - 1}'


def test_load_ai_tell_words(plugin_dir):
    """load_ai_tell_words returns parsed list from CSV."""
    from storyforge.prompts import load_ai_tell_words
    words = load_ai_tell_words(plugin_dir)
    assert len(words) >= 50
    entry = words[0]
    assert 'word' in entry
    assert 'category' in entry
    assert 'severity' in entry
    assert 'replacement_hint' in entry


def test_ai_tell_constraint_block(plugin_dir):
    """build_ai_tell_constraint returns formatted block of high-severity words."""
    from storyforge.prompts import load_ai_tell_words, build_ai_tell_constraint
    words = load_ai_tell_words(plugin_dir)
    block = build_ai_tell_constraint(words)
    assert 'delve' in block
    assert 'tapestry' in block
    assert 'facilitate' in block


def test_drafting_prompt_includes_ai_tell_words(project_dir, plugin_dir):
    """build_scene_prompt includes AI-tell constraint when word list exists."""
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    assert 'delve' in prompt


def test_briefs_prompt_includes_ai_tell_words(project_dir, plugin_dir):
    """build_scene_prompt_from_briefs includes AI-tell constraint."""
    from storyforge.prompts import build_scene_prompt_from_briefs
    prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
    # Should contain vocabulary constraints
    assert 'VOCABULARY CONSTRAINT' in prompt or 'delve' in prompt


def test_naturalness_plan_loads_word_list(tmp_path, plugin_dir):
    """The naturalness plan Pass 3 guidance should include words from CSV."""
    from storyforge.prompts import load_ai_tell_words
    words = load_ai_tell_words(plugin_dir)
    vocab_words = [w['word'] for w in words if w['category'] == 'vocabulary']
    assert 'nuanced' in vocab_words
    assert 'multifaceted' in vocab_words
    assert 'tapestry' in vocab_words
    assert 'palpable' in vocab_words
    assert 'delve' in vocab_words
    assert 'beacon' in vocab_words
