"""Tests for ledger.dependents and ledger.changed_facts (Phase 4's re-check
set, docs/plans/2026-10-31-phase4-safe-revision-design.md §1-2)."""

from storyforge import ledger

ORDER = {'s1': 0, 's2': 1, 's3': 2, 's4': 3}


def _row(rid, scene, subject='hank', type_='physical', statement='x', **kw):
    r = {'id': rid, 'scene_id': scene, 'subject': subject, 'type': type_,
         'statement': statement, 'status': 'binding', 'supersedes': '', 'depends_on': '',
         'resolves': ''}
    r.update(kw)
    return r


def test_same_subject_and_type_later_is_a_dependent():
    rows = [_row('f', 's2'), _row('a', 's1'), _row('b', 's3'), _row('c', 's4', type_='trait'),
            _row('d', 's4', subject='maren')]
    assert ledger.dependents(rows, ['f'], ORDER) == ['s3']


def test_links_count_whatever_the_subject():
    rows = [_row('f', 's1'), _row('a', 's3', subject='x', supersedes='f'),
            _row('b', 's2', subject='y', type_='trait', depends_on='g;f')]
    assert ledger.dependents(rows, ['f'], ORDER) == ['s2', 's3']


def test_the_scene_that_ends_a_state_is_a_dependent():
    rows = [_row('f', 's1', subject='', resolves='s4')]
    assert ledger.dependents(rows, ['f'], ORDER) == ['s4']


def test_backstory_is_before_every_scene_and_unplaced_is_skipped():
    rows = [_row('f', ''), _row('a', 's1'), _row('u', 'gone-scene'), _row('b', 's2')]
    assert ledger.dependents(rows, ['f'], ORDER) == ['s1', 's2']
    assert ledger.dependents(rows, ['u'], ORDER) == []


def test_non_binding_rows_and_a_blank_subject_add_nothing():
    rows = [_row('f', 's1', subject=''), _row('a', 's2', subject=''),
            _row('b', 's3', status='rejected')]
    assert ledger.dependents(rows, ['f'], ORDER) == []
    rows = [_row('f', 's1'), _row('b', 's3', status='rejected')]
    assert ledger.dependents(rows, ['f'], ORDER) == []


def test_several_facts_union_in_reading_order():
    rows = [_row('f', 's1', subject='hank'), _row('g', 's2', subject='maren'),
            _row('a', 's4', subject='hank'), _row('b', 's3', subject='maren')]
    assert ledger.dependents(rows, {'f', 'g'}, ORDER) == ['s3', 's4']


def test_changed_facts_ignores_case_spacing_and_end_punctuation():
    old = [_row('o1', 's1', statement='Hank holds  the key.'), _row('o2', 's1', statement='gone')]
    new = [_row('n1', 's1', statement='hank holds the key'), _row('n2', 's1', statement='new')]
    assert ledger.changed_facts(old, new) == ['o2', 'n2']


def test_changed_facts_compares_subject_and_type():
    old = [_row('o1', 's1')]
    assert ledger.changed_facts(old, [_row('n1', 's1', subject='maren')]) == ['o1', 'n1']
    assert ledger.changed_facts(old, [_row('n1', 's1', type_='trait')]) == ['o1', 'n1']
    assert ledger.changed_facts(old, [_row('n1', 's1')]) == []
