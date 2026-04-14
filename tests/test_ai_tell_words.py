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
