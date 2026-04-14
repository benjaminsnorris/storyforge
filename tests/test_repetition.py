import os


def test_tokenize_scene():
    """Tokenizer strips punctuation and lowercases."""
    from storyforge.repetition import tokenize_scene
    tokens = tokenize_scene('He looked at the sky. "Hello," she said.')
    assert tokens == ['he', 'looked', 'at', 'the', 'sky', 'hello', 'she', 'said']


def test_tokenize_preserves_contractions():
    """Contractions stay as single tokens."""
    from storyforge.repetition import tokenize_scene
    tokens = tokenize_scene("She couldn't believe it wasn't real.")
    assert "couldn't" in tokens
    assert "wasn't" in tokens


def test_tokenize_handles_em_dashes():
    """Em dashes are treated as word separators."""
    from storyforge.repetition import tokenize_scene
    tokens = tokenize_scene('The sky\u2014dark and cold\u2014pressed down.')
    assert 'sky' in tokens
    assert 'dark' in tokens
    assert all('\u2014' not in t for t in tokens)


def test_extract_ngrams():
    """N-gram extraction produces correct windows."""
    from storyforge.repetition import tokenize_scene, extract_ngrams
    # Two scenes with the same phrase — should record both scene IDs.
    tokens_a = tokenize_scene('the cat sat on the mat')
    tokens_b = tokenize_scene('the cat sat on the rug')
    ngrams_a = extract_ngrams(tokens_a, 4, 'scene-1')
    ngrams_b = extract_ngrams(tokens_b, 4, 'scene-2')
    # Merge ngrams like scan_scenes does.
    merged: dict[tuple, list[str]] = {}
    for gram, ids in list(ngrams_a.items()) + list(ngrams_b.items()):
        merged.setdefault(gram, []).extend(ids)
    key = ('the', 'cat', 'sat', 'on')
    assert key in merged
    assert len(merged[key]) == 2
    assert 'scene-1' in merged[key]
    assert 'scene-2' in merged[key]


def test_stop_word_only_ngrams_dropped():
    """N-grams consisting entirely of stop words are filtered out."""
    from storyforge.repetition import scan_scenes
    scenes = {
        's1': 'it was in the and it was in the end of all things good',
        's2': 'it was in the and it was in the end of all things good',
    }
    findings = scan_scenes(scenes)
    phrases = [f['phrase'] for f in findings]
    assert 'it was in the' not in phrases


def test_subphrase_suppression():
    """Longer phrases suppress contained shorter phrases."""
    from storyforge.repetition import suppress_subphrases
    findings = [
        {'phrase': 'the back of his', 'count': 5, 'category': 'character_tell'},
        {'phrase': 'back of his', 'count': 5, 'category': 'character_tell'},
        {'phrase': 'the back of his neck', 'count': 4, 'category': 'character_tell'},
    ]
    result = suppress_subphrases(findings)
    phrases = [f['phrase'] for f in result]
    assert 'the back of his neck' in phrases
    assert 'the back of his' not in phrases


def test_categorize_simile():
    """Phrases with 'like' are categorized as simile."""
    from storyforge.repetition import categorize_finding
    cat = categorize_finding('eyes like broken glass')
    assert cat == 'simile'


def test_categorize_blocking_tic():
    """Phrases with blocking verbs are categorized as blocking_tic."""
    from storyforge.repetition import categorize_finding
    cat = categorize_finding('she turned to look')
    assert cat == 'blocking_tic'


def test_categorize_character_tell():
    """Phrases with body part vocabulary are character_tell."""
    from storyforge.repetition import categorize_finding
    cat = categorize_finding('the back of his neck')
    assert cat == 'character_tell'


def test_repetition_scores_for_scene(tmp_path):
    """score_scene_repetition produces per-scene marker scores."""
    from storyforge.repetition import score_scene_repetition

    findings = [
        {'phrase': 'eyes like broken glass', 'category': 'simile',
         'severity': 'high', 'count': 4, 'scene_ids': ['s1', 's2', 's3', 's4']},
        {'phrase': 'turned to look at', 'category': 'blocking_tic',
         'severity': 'high', 'count': 5, 'scene_ids': ['s1', 's2', 's3', 's4', 's5']},
        {'phrase': 'for the first time', 'category': 'structural',
         'severity': 'high', 'count': 6, 'scene_ids': ['s1', 's2', 's3', 's4', 's5', 's6']},
    ]

    scores = score_scene_repetition('s1', findings)
    assert scores['pr-1'] == 1  # simile hit
    assert scores['pr-2'] == 1  # blocking tic hit
    assert scores['pr-3'] == 1  # structural hit
    assert scores['pr-4'] == 0  # no signature phrase hit

    scores2 = score_scene_repetition('s99', findings)
    assert scores2['pr-1'] == 0
    assert scores2['pr-2'] == 0
    assert scores2['pr-3'] == 0
    assert scores2['pr-4'] == 0


def test_full_scan_with_fixtures(project_dir):
    """Full scan runs on fixture scenes and returns findings."""
    from storyforge.repetition import scan_manuscript
    findings = scan_manuscript(project_dir)
    assert isinstance(findings, list)
    for f in findings:
        assert 'phrase' in f
        assert 'category' in f
        assert 'severity' in f
        assert 'count' in f
        assert 'scene_ids' in f
