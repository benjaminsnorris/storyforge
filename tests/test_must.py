"""The `must:` marker on a brief beat (#642): one parser, and `keep_must`,
which every brief rewrite passes its reply through."""

import pytest

from storyforge import must


@pytest.mark.parametrize('item, text', [
    ('must: Priam kisses his hands', 'Priam kisses his hands'),
    ('MUST: Priam kisses his hands', 'Priam kisses his hands'),
    ('Must : Priam kisses his hands', 'Priam kisses his hands'),
    ('  must:Priam kisses his hands  ', 'Priam kisses his hands'),
    ('must:\tPriam kisses his hands', 'Priam kisses his hands'),
])
def test_the_marker_in_any_case_and_spacing(item, text):
    parsed = must.parse_item(item)
    assert parsed.must and parsed.text == text
    assert must.is_must(item)
    assert must.strip_marker(item) == text


@pytest.mark.parametrize('item', [
    'Priam kisses his hands',
    'Priam says he must: go',          # not at the start
    'mustering: the Myrmidons arm',    # another word
    'must Priam kiss his hands',       # no colon
    '',
])
def test_not_the_marker(item):
    parsed = must.parse_item(item)
    assert not parsed.must
    assert parsed.text == item.strip()


def test_an_item_that_is_only_the_marker_marks_nothing():
    parsed = must.parse_item(' must: ')
    assert parsed.must and parsed.text == ''
    assert must.must_items('must:; Hector runs') == []
    assert must.bare_markers('must:; Hector runs; MUST :') == 2


def test_items_and_must_items_of_a_cell():
    cell = 'Hector runs;must: Achilles chases him ; ; MUST: Athena tricks Hector'
    assert [i.text for i in must.items(cell)] == [
        'Hector runs', 'Achilles chases him', 'Athena tricks Hector']
    assert [i.raw for i in must.must_items(cell)] == [
        'must: Achilles chases him', 'MUST: Athena tricks Hector']


def test_a_quoted_labelled_line_keeps_its_label():
    parsed = must.parse_item('must: Priam: "I have kissed the hands"')
    assert parsed.text == 'Priam: "I have kissed the hands"'


class TestKeepMust:
    OLD = 'Hector runs; must: Achilles chases him three times round the walls; Athena lies'

    def test_a_rewrite_keeping_every_must_item_is_unchanged(self):
        new = 'Hector flees;must: Achilles chases him three times round the walls'
        kept = must.keep_must(self.OLD, new)
        assert kept.value == new and not kept.changed

    def test_a_dropped_must_item_is_put_back_at_its_place(self):
        kept = must.keep_must(self.OLD, 'Hector flees; Athena takes the shape of Deiphobus')
        assert kept.restored == ['must: Achilles chases him three times round the walls']
        assert kept.value == ('Hector flees; must: Achilles chases him three times round '
                              'the walls; Athena takes the shape of Deiphobus')

    def test_a_reworded_must_item_is_replaced_by_the_authors(self):
        kept = must.keep_must(self.OLD, 'Hector flees; must: Achilles pursues him round Troy')
        assert kept.dropped == ['must: Achilles pursues him round Troy']
        assert kept.restored == ['must: Achilles chases him three times round the walls']
        assert kept.value == 'Hector flees; must: Achilles chases him three times round the walls'

    def test_a_must_item_the_rewrite_made_up_is_left_out(self):
        kept = must.keep_must('Hector runs', 'must: Hector runs; Achilles follows')
        assert kept.dropped == ['must: Hector runs']
        assert kept.value == 'Achilles follows'

    def test_the_markers_spelling_and_spacing_do_not_count(self):
        new = 'Hector flees; MUST :  Achilles chases him three times round the walls'
        assert not must.keep_must(self.OLD, new).changed

    def test_a_beat_kept_without_its_marker_is_marked_again_in_place(self):
        new = 'Achilles chases him three times round the walls; Hector flees'
        kept = must.keep_must(self.OLD, new)
        assert kept.value == 'must: Achilles chases him three times round the walls; Hector flees'
        assert kept.restored and not kept.dropped

    def test_an_empty_rewrite_keeps_the_must_items(self):
        assert must.keep_must(self.OLD, '').value == (
            'must: Achilles chases him three times round the walls')

    def test_no_must_items_leaves_any_rewrite(self):
        assert must.keep_must('Hector runs', 'Hector flees').value == 'Hector flees'

    def test_fields(self):
        row = {'key_actions': self.OLD, 'key_dialogue': 'must: Hector: "Let me not die"',
               'goal': 'must: survive'}
        out, notes = must.keep_must_fields(row, {'key_actions': 'Hector flees',
                                                 'key_dialogue': 'must: Hector: "Let me not die"',
                                                 'goal': 'flee'})
        assert out['key_actions'] == ('Hector flees; must: Achilles chases him three times '
                                      'round the walls')
        assert out['goal'] == 'flee'          # only MUST_FIELDS carry the marker
        assert len(notes) == 1 and notes[0].startswith('key_actions: put back')
