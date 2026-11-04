"""extract --phase 2 --casts-only: the cast prompt and the union merge (#523).

Casts extracted before #524 are thin; re-running phase 2 with --force would
replace every intent field and undo hand fixes, so this mode re-asks only
the cast and adds what the answer names, never removing an entry.
"""

import json

import pytest

from storyforge import extract_casts as casts
from storyforge.extract import (
    CAST_INSTRUCTIONS, CAST_SCHEMA, INTENT_SCHEMA, build_cast_prompt, build_intent_prompt,
    parse_cast_response,
)

ALIASES = {
    'eumaeus': 'eumaeus', 'the swineherd': 'eumaeus', 'eumaeus the swineherd': 'eumaeus',
    'ulysses': 'ulysses', 'odysseus': 'ulysses', 'minerva': 'minerva', 'athena': 'minerva',
}


class TestCastPrompt:
    def test_the_cast_prompt_shares_phase_2s_cast_instructions_word_for_word(self):
        args = ('s1', 'Eumaeus greets him.\n', {'major_threads': 'home'},
                {'title': 'Hut', 'pov': 'narrator'}, '## Canonical Registries\n- a (A)')
        intent, cast = build_intent_prompt(*args), build_cast_prompt(*args)
        assert CAST_INSTRUCTIONS in intent and CAST_INSTRUCTIONS in cast
        # the context, prose and registries are the intent prompt's own
        head = intent[intent.index('## Context'):intent.index('## Instructions')]
        assert head in cast
        # and nothing but the cast is asked for
        for other in ('function:', 'value_shift', 'mice_threads', 'confidence'):
            assert other not in cast

    def test_the_schema_is_the_intent_schemas_two_cast_lists(self):
        assert CAST_SCHEMA['required'] == ['characters', 'on_stage']
        for key in CAST_SCHEMA['required']:
            assert CAST_SCHEMA['properties'][key] == INTENT_SCHEMA['properties'][key]


class TestParseCastResponse:
    def test_ids_come_back_as_given_less_placeholders_and_parentheticals(self):
        reply = json.dumps({'characters': ['eumaeus', ' Ulysses (disguised) ', 'unknown',
                                           'none', '', 'a;b', 'x|y'],
                            'on_stage': ['eumaeus']})
        chars, on = parse_cast_response(reply)
        assert chars == ['eumaeus', 'Ulysses', 'a,b', 'x/y']
        assert on == ['eumaeus']

    @pytest.mark.parametrize('reply', [
        'not json', json.dumps({'characters': []}), json.dumps({'characters': 'a', 'on_stage': []}),
        json.dumps({'characters': [3], 'on_stage': []}),
    ])
    def test_an_unreadable_reply_raises(self, reply):
        with pytest.raises(ValueError):
            parse_cast_response(reply)


class TestMergeCast:
    def test_union_keeps_existing_entries_in_order_and_appends_new_ones(self):
        m = casts.merge_cast('narrator;ulysses', 'ulysses', ['eumaeus', 'ulysses', 'dogs'],
                             ['eumaeus'], ALIASES)
        assert m.characters == 'narrator;ulysses;eumaeus;dogs'
        assert m.on_stage == 'ulysses;eumaeus'
        assert m.added_characters == ['eumaeus', 'dogs']
        assert m.added_on_stage == ['eumaeus']

    def test_nothing_is_removed_when_the_answer_leaves_people_out(self):
        m = casts.merge_cast('narrator;ulysses;penelope', 'ulysses;penelope', [], [], ALIASES)
        assert (m.characters, m.on_stage) == ('narrator;ulysses;penelope', 'ulysses;penelope')
        assert not m.changed

    def test_an_id_added_to_on_stage_is_added_to_characters_too(self):
        m = casts.merge_cast('ulysses', 'ulysses', [], ['minerva'], ALIASES)
        assert m.on_stage == 'ulysses;minerva'
        assert m.characters == 'ulysses;minerva'

    def test_on_stage_already_outside_characters_is_brought_in(self):
        """An existing on_stage entry the characters cell lacks: the subset
        invariant holds after the merge, by adding, not removing."""
        m = casts.merge_cast('narrator', 'ulysses', [], [], ALIASES)
        assert m.characters == 'narrator;ulysses'
        assert m.on_stage == 'ulysses'
        assert m.added_characters == ['ulysses']

    def test_names_and_aliases_resolve_to_the_registry_id(self):
        m = casts.merge_cast('ulysses', 'ulysses', ['the swineherd', 'Odysseus', 'Athena'],
                             ['Eumaeus the Swineherd'], ALIASES)
        # Odysseus is ulysses: already there; the others written as their ids
        assert m.characters == 'ulysses;eumaeus;minerva'
        assert m.on_stage == 'ulysses;eumaeus'

    def test_existing_names_match_their_ids_and_are_kept_as_written(self):
        m = casts.merge_cast('Odysseus;Eumaeus', 'Odysseus', ['ulysses', 'eumaeus', 'minerva'],
                             ['ulysses'], ALIASES)
        assert m.characters == 'Odysseus;Eumaeus;minerva'
        assert m.on_stage == 'Odysseus'

    def test_new_ids_are_deduplicated_case_insensitively(self):
        m = casts.merge_cast('', '', ['Irus', 'irus', 'IRUS'], ['irus'], {})
        assert m.characters == 'Irus'
        assert m.on_stage == 'irus'

    def test_an_unchanged_cell_keeps_its_exact_text(self):
        m = casts.merge_cast(' ulysses ; eumaeus ', 'ulysses', ['eumaeus'], ['ulysses'], ALIASES)
        assert m.characters == ' ulysses ; eumaeus '
        assert not m.changed

    def test_a_trailing_separator_does_not_leave_an_empty_entry(self):
        m = casts.merge_cast('ulysses;', '', ['eumaeus'], [], ALIASES)
        assert m.characters == 'ulysses;eumaeus'

    @pytest.mark.parametrize('chars,on,new_chars,new_on', [
        ('a;b', 'b', ['c'], ['d', 'a']),
        ('', 'x', [], ['y']),
        ('Odysseus', '', ['minerva'], ['athena', 'the swineherd']),
    ])
    def test_on_stage_is_always_a_subset_of_characters(self, chars, on, new_chars, new_on):
        m = casts.merge_cast(chars, on, new_chars, new_on, ALIASES)
        key = lambda e: ALIASES.get(e.lower(), e).lower()   # noqa: E731
        assert ({key(e) for e in casts.split_ids(m.on_stage)}
                <= {key(e) for e in casts.split_ids(m.characters)})
        # and every original entry is still there, in order, at the front
        assert casts.split_ids(m.characters)[:len(casts.split_ids(chars))] == casts.split_ids(chars)
        assert casts.split_ids(m.on_stage)[:len(casts.split_ids(on))] == casts.split_ids(on)


HEADER = 'id|function|action_sequel|characters|on_stage|mice_threads|theme_threads'


def _intent(tmp_path, *rows):
    path = tmp_path / 'scene-intent.csv'
    path.write_text('\n'.join([HEADER, *rows]) + '\n')
    return path


class TestApplyCasts:
    def test_only_the_two_cells_of_rows_that_gain_someone_change(self, tmp_path):
        rows = ['hut|He arrives; "Ah," says the swineherd.|action|narrator;ulysses|ulysses|'
                '+home|hospitality',
                'other|Untouched "quoted" text.|sequel|penelope|penelope|home|grief',
                'third|Asked, gains nothing.|sequel|ulysses|ulysses||']
        path = _intent(tmp_path, *rows)
        merges = casts.apply_casts(str(path), {
            'hut': (['eumaeus'], ['eumaeus']), 'third': (['Odysseus'], [])}, ALIASES)
        lines = path.read_text().split('\n')
        assert lines[1] == ('hut|He arrives; "Ah," says the swineherd.|action|'
                            'narrator;ulysses;eumaeus|ulysses;eumaeus|+home|hospitality')
        assert lines[2] == rows[1]
        assert lines[3] == rows[2]
        assert merges['hut'].changed and not merges['third'].changed
        assert 'other' not in merges

    def test_a_file_nothing_is_added_to_is_not_rewritten(self, tmp_path):
        path = _intent(tmp_path, 'hut|f|action|ulysses|ulysses||')
        path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        before = path.read_bytes()
        casts.apply_casts(str(path), {'hut': (['ulysses'], [])}, ALIASES)
        assert path.read_bytes() == before

    def test_a_short_row_is_padded_to_hold_the_cast(self, tmp_path):
        path = _intent(tmp_path, 'hut|f|action')
        casts.apply_casts(str(path), {'hut': (['eumaeus'], [])}, ALIASES)
        assert path.read_text().split('\n')[1] == 'hut|f|action|eumaeus|'

    def test_a_scene_on_two_rows_is_left_alone(self, tmp_path):
        path = _intent(tmp_path, 'hut|a|action|ulysses|ulysses||', 'hut|b|action|x|x||')
        before = path.read_text()
        merges = casts.apply_casts(str(path), {'hut': (['eumaeus'], [])}, ALIASES)
        assert merges == {} and path.read_text() == before

    @pytest.mark.parametrize('content,problem', [
        (None, 'does not exist'), ('', 'is empty'), ('id|function\nhut|f\n', 'no characters, on_stage'),
    ])
    def test_a_file_that_cant_be_merged_into_raises(self, tmp_path, content, problem):
        path = tmp_path / 'scene-intent.csv'
        if content is not None:
            path.write_text(content)
        with pytest.raises(casts.CastFileError, match=problem):
            casts.apply_casts(str(path), {'hut': (['a'], [])}, {})

    def test_read_casts_lists_every_row_per_id(self, tmp_path):
        path = _intent(tmp_path, 'a|f|x|p;q|p||', 'b|f|x|||', 'a|g|x|r|r||')
        assert casts.read_casts(str(path)) == {'a': [('p;q', 'p'), ('r', 'r')], 'b': [('', '')]}


class TestReviewText:
    def _review(self, **over):
        kw = dict(selected=['hut', 'palace'],
                  before={'hut': [('narrator;ulysses', 'ulysses')], 'palace': [('alcinous', '')],
                          'far': [('Irus', 'Irus')]},
                  after={'hut': [('narrator;ulysses;eumaeus;argos', 'ulysses;eumaeus')],
                         'palace': [('alcinous', '')], 'far': [('irus', '')]},
                  names={'eumaeus': 'Eumaeus', 'ulysses': 'Ulysses', 'irus': 'Irus'},
                  alias_map={'irus': 'irus'}, not_merged={'gone': 'no row in scene-intent.csv'},
                  empty=['palace'], cost=0.42, forecast_cost=0.5, registry_note='hone added 1')
        kw.update(over)
        return casts.review_text(**kw)

    def test_lists_each_scenes_additions_with_names(self):
        text = self._review()
        assert '### hut\n- characters: eumaeus (Eumaeus), argos (not in characters.csv)\n' \
               '- on_stage: eumaeus (Eumaeus)\n' in text
        assert 'Ids added: 2 to characters, 1 to on_stage.' in text
        assert 'Cost: $0.42 (forecast $0.50).' in text
        assert '- gone: no row in scene-intent.csv' in text
        assert '## Answered with no one' in text and '- palace' in text
        assert 'Registry: hone added 1' in text

    def test_an_entry_the_registry_pass_dropped_is_listed_not_hidden(self):
        """A name hone rewrote as its id is the same entry; one it removed
        (an on_stage it decided wasn't a character) is named."""
        text = self._review()
        assert '- far: on_stage: Irus' in text
        assert 'far: characters' not in text

    def test_an_unknown_cost_is_said(self):
        assert 'Cost: not known' in self._review(cost=None)


class TestForecast:
    def test_priced_from_the_prompts_at_the_batch_price(self):
        from storyforge.costs import calculate_cost
        model = 'claude-sonnet-4-5'
        expected = calculate_cost(model, 2000, 2 * casts.OUTPUT_TOKENS_PER_SCENE, batch=True)
        assert casts.forecast(['x' * 4000, 'y' * 4000], model) == pytest.approx(expected)
