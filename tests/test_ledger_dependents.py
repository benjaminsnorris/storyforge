"""Tests for ledger.dependents and ledger.changed_facts (Phase 4's re-check
set, docs/plans/2026-10-31-phase4-safe-revision-design.md §1-2)."""

import os

import pytest

from storyforge import ledger

ORDER = {'s1': 0, 's2': 1, 's3': 2, 's4': 3}


def _deps(rows, ids, names=None):
    return ledger.dependents(rows, ids, ORDER, names=names or {})


def _row(rid, scene, subject='hank', type_='physical', statement='x', **kw):
    r = {'id': rid, 'scene_id': scene, 'subject': subject, 'type': type_,
         'statement': statement, 'status': 'binding', 'supersedes': '', 'depends_on': '',
         'resolves': ''}
    r.update(kw)
    return r


def test_same_subject_later_is_a_dependent_in_any_type():
    """#473: a timeline fact about Tessa was contradicted in a scene with
    only her physical and knowledge facts."""
    rows = [_row('f', 's2'), _row('a', 's1'), _row('b', 's3', type_='timeline'),
            _row('d', 's4', subject='maren')]
    assert _deps(rows, ['f']).scenes == ['s3']


def test_links_count_whatever_the_subject():
    rows = [_row('f', 's1'), _row('a', 's3', subject='x', supersedes='f'),
            _row('b', 's2', subject='y', type_='trait', depends_on='g;f')]
    assert _deps(rows, ['f']).scenes == ['s2', 's3']


def test_the_scene_that_ends_a_state_is_a_dependent():
    rows = [_row('f', 's1', subject='', resolves='s4')]
    assert _deps(rows, ['f']).scenes == ['s4']


def test_backstory_is_before_every_scene_and_unplaced_is_skipped():
    rows = [_row('f', ''), _row('a', 's1'), _row('u', 'gone-scene'), _row('b', 's2')]
    assert _deps(rows, ['f']).scenes == ['s1', 's2']
    found = _deps(rows, ['u'])
    assert found.scenes == [] and 'not in scenes.csv' in found.unrelated['u']


def test_non_binding_rows_add_nothing():
    rows = [_row('f', 's1', subject='', type_='world'), _row('b', 's3', status='rejected',
                                                             type_='world')]
    assert _deps(rows, ['f']).scenes == []
    rows = [_row('f', 's1'), _row('b', 's3', status='rejected')]
    assert _deps(rows, ['f']).scenes == []


def test_a_blank_subject_reaches_every_later_fact_of_its_type_and_is_still_said():
    """#473: world rules with no subject were contradicted later and
    traced to nothing."""
    rows = [_row('f', 's1', subject='', type_='world'), _row('a', 's2', subject='ivra',
                                                              type_='world'),
            _row('b', 's3', subject='ivra', type_='physical')]
    found = _deps(rows, ['f'])
    assert found.scenes == ['s2']
    assert found.unrelated['f'] == ('no subject: every later scene with a binding world fact is taken as '
                                  'depending on it')


def test_a_later_statement_naming_the_subject_is_a_dependent():
    """#473: Wick's state, contradicted by Nora's knowledge that she sat
    in Wick's house."""
    rows = [_row('f', 's1', subject='wick'),
            _row('a', 's2', subject='nora', type_='knowledge',
                 statement="Nora sat in Wick's house yesterday"),
            _row('b', 's3', subject='nora', statement='Nora is wickedly tired')]
    assert _deps(rows, ['f']).scenes == ['s2']


def test_a_later_subject_the_statement_names_is_a_dependent():
    """#473: the Lamp's rule, contradicted in what the Keeper told Nora."""
    rows = [_row('f', 's1', subject='the-great-lamp', type_='world',
                 statement="The Folk's lanterns and the Keeper's flame share one fire"),
            _row('a', 's3', subject='keeper', type_='knowledge', statement='x')]
    assert _deps(rows, ['f']).scenes == ['s3']


def test_registry_names_and_aliases_match_and_short_ones_dont():
    names = {'hank voigt': {'hank voigt', 'hank', 'hv'}, 'maren cole': {'the cole woman'}}
    rows = [_row('f', 's1', subject='hank-voigt'),
            _row('a', 's2', subject='claire', statement='Claire calls Hank'),
            _row('b', 's3', subject='claire', statement='HV is on the form'),
            _row('g', 's1', subject='maren-cole'),
            _row('c', 's4', subject='x', statement='Cole woman leaves')]
    assert _deps(rows, ['f'], names).scenes == ['s2']
    assert _deps(rows, ['f']).scenes == []          # {}: ids only
    assert _deps(rows, ['g'], names).scenes == ['s4']   # "the" dropped


@pytest.mark.parametrize('statement, alias, found', [
    ('Mr. K arrives', 'mr. k', True),              # punctuation inside
    ('the j.r. said so', 'j.r.', True),            # ends in punctuation
    ('A (b) left', 'a (b)', True),                 # regex metacharacters
    ('kai waits', 'kai', True),                    # exactly three characters
    ('THE STRASSE', 'strasse', True),              # case folded (ß folds to ss)
    ('ox is here', 'the ox', False),               # under three once "the" goes
    ('kaiser waits', 'kai', False),                # whole words only
])
def test_mention_match_edges(statement, alias, found):
    rows = [_row('f', 's1', subject='zed'), _row('a', 's2', subject='y', statement=statement)]
    assert _deps(rows, ['f'], {'zed': {alias}}).scenes == (['s2'] if found else [])


def test_an_unregistered_hyphenated_id_matches_as_written_and_spaced():
    rows = [_row('f', 's1', subject='north-gate', type_='world'),
            _row('a', 's2', subject='y', statement='The north-gate is sealed'),
            _row('b', 's3', subject='y', statement='The North Gate stands')]
    assert _deps(rows, ['f']).scenes == ['s2', 's3']


def test_subject_names_reads_characters_and_locations(project_dir):
    names, notes = ledger.subject_names(project_dir)
    assert {'dorren hayle', 'dorren', 'hayle', 'dr. hayle'} <= names['dorren hayle']
    assert 'the study' in names['private study'] and notes == []


def test_subject_names_keeps_a_shared_alias_for_both(project_dir):
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    with open(path, 'a') as f:
        f.write('ana-hayle|Ana Hayle|Hayle|supporting|\n')
    names, _ = ledger.subject_names(project_dir)
    assert 'hayle' in names['dorren hayle'] and 'hayle' in names['ana hayle']


@pytest.mark.parametrize('content, fragment', [
    (None, 'missing or empty'),
    ('name|aliases\nDorren|D\n', 'no id column'),
])
def test_subject_names_says_what_narrows_the_match(project_dir, content, fragment):
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    os.remove(path)
    if content:
        with open(path, 'w') as f:
            f.write(content)
    names, notes = ledger.subject_names(project_dir)
    assert any('characters.csv' in n and fragment in n for n in notes)
    assert 'private study' in names        # the other registry still read


def test_several_facts_union_in_reading_order():
    rows = [_row('f', 's1', subject='hank'), _row('g', 's2', subject='maren'),
            _row('a', 's4', subject='hank'), _row('b', 's3', subject='maren')]
    assert _deps(rows, {'f', 'g'}).scenes == ['s3', 's4']


def test_changed_facts_ignores_case_spacing_and_end_punctuation():
    old = [_row('o1', 's1', statement='Hank holds  the key.'), _row('o2', 's1', statement='gone')]
    new = [_row('n1', 's1', statement='hank holds the key'), _row('n2', 's1', statement='new')]
    assert ledger.changed_facts(old, new) == ['o2', 'n2']


def test_changed_facts_compares_subject_and_type():
    old = [_row('o1', 's1')]
    assert ledger.changed_facts(old, [_row('n1', 's1', subject='maren')]) == ['o1', 'n1']
    assert ledger.changed_facts(old, [_row('n1', 's1', type_='trait')]) == ['o1', 'n1']
    assert ledger.changed_facts(old, [_row('n1', 's1')]) == []


def test_a_fact_not_in_the_rows_is_said():
    found = _deps([_row('f', 's1')], ['f', 'gone'])
    assert found.unrelated == {'gone': 'not in the ledger rows given'}


def test_a_blank_subject_is_said_even_when_linked():
    rows = [_row('f', 's1', subject=''), _row('a', 's2', subject='', type_='trait',
                                               supersedes='f')]
    found = _deps(rows, ['f'])
    assert found.scenes == ['s2'] and 'no subject' in found.unrelated['f']


def test_subjects_match_in_any_case():
    rows = [_row('f', 's1', subject='Hank'), _row('a', 's2', subject='hank')]
    assert _deps(rows, ['f']).scenes == ['s2']


def test_a_knowledge_fact_reaches_scenes_about_who_knows_it():
    rows = [_row('f', 's1', subject='', type_='knowledge', known_by='maren;hank'),
            _row('a', 's2', subject='maren', type_='physical'),
            _row('b', 's3', subject='claire', type_='knowledge')]
    found = _deps(rows, ['f'])
    assert found.scenes == ['s2'] and found.unrelated == {}   # known_by: no type fallback


def test_a_state_that_lost_its_later_end_is_changed():
    old = [_row('o1', 's1', resolves='s3')]
    assert ledger.changed_facts(old, [_row('n1', 's1')]) == ['o1', 'n1']
    assert ledger.changed_facts(old, [_row('n1', 's1', resolves='s3')]) == []
    # an end in its own scene, or never, is no link to another scene
    assert ledger.changed_facts([_row('o1', 's1', resolves='s1')],
                                [_row('n1', 's1', resolves='never')]) == []


def test_ended_by_names_other_scenes_rows_only():
    rows = [_row('a', 's1', resolves='s3'), _row('b', 's3', resolves='s3'),
            _row('c', 's2', resolves='s4')]
    assert ledger.ended_by(rows, 's3') == {'a'}
