"""5b's token budget grows with the book (Middlemarch was cut off under the flat 12,000)."""

from storyforge.extract_describe import THEMES_MAX_TOKENS, themes_max_tokens


def test_a_short_book_keeps_the_floor():
    assert themes_max_tokens([{}] * 40, [('s', 'm')] * 293) == THEMES_MAX_TOKENS


def test_a_long_book_gets_room_for_every_scene_and_mention():
    # Middlemarch: 341 scenes, 2,174 motif mentions; its reply was cut off at
    # 312 scenes with 12,000 for the answer
    budget = themes_max_tokens([{}] * 341, [('s', 'm')] * 2174)
    assert budget >= 28_000
    assert themes_max_tokens([{}] * 342, [('s', 'm')] * 2174) > budget


def test_the_themes_step_passes_the_scaled_budget(monkeypatch, tmp_path):
    from storyforge import extract_describe as ed
    seen = {}

    def fake_ask(run, label, prompt_for, parse, schema, max_tokens):
        seen['max_tokens'] = max_tokens
        raise ed.DescribeFailed('stop here')
    monkeypatch.setattr(ed, '_ask', fake_ask)
    monkeypatch.setattr(ed, '_gate', lambda *a, **k: True)
    scenes = [{'id': f's{i}', 'motif_details': 'a lamp;the fog'} for i in range(300)]
    try:
        ed.run_themes(None, {}, scenes)
    except (ed.DescribeFailed, TypeError):
        pass
    assert seen.get('max_tokens') == themes_max_tokens(scenes, ed.motif_mentions(scenes))
