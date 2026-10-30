"""Epigraph detection for scene boundaries (F-120)."""

import os

from storyforge.scenes import is_epigraph_block, keep_epigraph_with_opening

_FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'scenes-setup',
                        'middlemarch-ch57-opening.md')


def _ch57():
    with open(_FIXTURE) as f:
        return f.read()


class TestIsEpigraphBlock:
    def test_flattened_verse_without_attribution(self):
        # Middlemarch Chapter LVII: verse whose line breaks were joined.
        lines = _ch57().splitlines()
        assert is_epigraph_block('\n'.join(lines[:4]))

    def test_verse_with_line_breaks_and_dash_attribution(self):
        assert is_epigraph_block(
            '# Chapter 9\n\nBreathes there the man, with soul so dead,\n'
            'Who never to himself hath said,\nThis is my own, my native land!\n'
            '\n—Scott\n')

    def test_quote_with_inline_caps_attribution(self):
        assert is_epigraph_block(
            'Since I can do no good because a woman, Reach constantly at '
            'something that is near it. —_The Maid’s Tragedy:_ BEAUMONT AND '
            'FLETCHER.\n')

    def test_caps_attribution_line(self):
        assert is_epigraph_block(
            '“Our deeds still travel with us from afar,\nAnd what we have '
            'been makes us what we are.”\n\nSIR WALTER SCOTT\n')

    def test_epigraph_then_prose_is_not_only_an_epigraph(self):
        lines = _ch57().splitlines()
        assert not is_epigraph_block('\n'.join(lines[:5]))

    def test_short_prose_is_not_an_epigraph(self):
        assert not is_epigraph_block(
            '# Chapter 3\n\nThe carriage came for them at nine, and Elizabeth '
            'went down to it alone.\n')

    def test_prose_ending_in_dash_and_speech_is_not_attribution(self):
        assert not is_epigraph_block(
            '“I cannot say who told me—Fred said so, I think.”\n')

    def test_speech_broken_off_at_a_name_is_not_attribution(self):
        assert not is_epigraph_block('“I tell you I will not go, — Fred!”\n')
        assert not is_epigraph_block('He stopped at the door. —Rosamond.”\n')

    def test_short_dialogue_is_not_an_epigraph(self):
        assert not is_epigraph_block(
            '“Is he married or single?”\n\n“Oh! single, my dear, to be sure!”\n')

    def test_italic_title_attribution(self):
        assert is_epigraph_block(
            '’Tis one thing to be tempted, Escalus, Another thing to fall. '
            '—_Measure for Measure_.\n')

    def test_speech_quoted_from_a_play(self):
        assert is_epigraph_block(
            '1_st Gent_. Where lies the power, there let the blame lie too.\n')

    def test_diary_entry_is_not_a_speech_from_a_play(self):
        assert not is_epigraph_block('_Monday_. It rained all day, and I stayed in.\n')

    def test_letter_signed_in_capitals_is_not_an_epigraph(self):
        # The Plastic Age: a scene that ends with a letter signed "BERT MORSE."
        assert not is_epigraph_block(
            'He never caught Carl in a confidential mood again.\n\n'
            'Dear Hugh [he read]. You\'ve been awfully good to me but I can\'t '
            'stand it. I\'m going home to-day.\n\nBERT MORSE.\n')
        assert not is_epigraph_block(
            'Dear Hugh [he read]. You\'ve been awfully good to me but I can\'t '
            'stand it.\n\nBERT MORSE.\n')

    def test_empty_or_heading_only_is_not_an_epigraph(self):
        assert not is_epigraph_block('')
        assert not is_epigraph_block('# Chapter LVII\n\n')


class TestKeepEpigraphWithOpening:
    def test_merges_epigraph_into_next_scene(self):
        splits = [{'line': 1, 'slug': 'chapter-epigraph-scott-childhood-verse'},
                  {'line': 5, 'slug': 'fred-confronted-by-mrs-garth'}]
        kept, refused = keep_epigraph_with_opening(_ch57(), splits)
        assert kept == [{'line': 1, 'slug': 'fred-confronted-by-mrs-garth'}]
        assert [r['slug'] for r in refused] == ['chapter-epigraph-scott-childhood-verse']

    def test_leaves_real_split_alone(self):
        text = _ch57()
        splits = [{'line': 1, 'slug': 'fred-confronted-by-mrs-garth'},
                  {'line': 7, 'slug': 'garth-family-in-orchard'}]
        kept, refused = keep_epigraph_with_opening(text, splits)
        assert kept == splits and refused == []

    def test_single_scene_untouched(self):
        splits = [{'line': 1, 'slug': 'x'}]
        assert keep_epigraph_with_opening(_ch57(), splits) == (splits, [])
