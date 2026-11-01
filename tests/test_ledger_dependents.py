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


def test_same_subject_later_is_a_dependent_in_any_type():
    """#473: a timeline fact about Tessa was contradicted in a scene with
    only her physical and knowledge facts."""
    rows = [_row('f', 's2'), _row('a', 's1'), _row('b', 's3', type_='timeline'),
            _row('d', 's4', subject='maren')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == ['s3']


def test_links_count_whatever_the_subject():
    rows = [_row('f', 's1'), _row('a', 's3', subject='x', supersedes='f'),
            _row('b', 's2', subject='y', type_='trait', depends_on='g;f')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == ['s2', 's3']


def test_the_scene_that_ends_a_state_is_a_dependent():
    rows = [_row('f', 's1', subject='', resolves='s4')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == ['s4']


def test_backstory_is_before_every_scene_and_unplaced_is_skipped():
    rows = [_row('f', ''), _row('a', 's1'), _row('u', 'gone-scene'), _row('b', 's2')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == ['s1', 's2']
    found = ledger.dependents(rows, ['u'], ORDER)
    assert found.scenes == [] and 'not in scenes.csv' in found.unrelated['u']


def test_non_binding_rows_add_nothing():
    rows = [_row('f', 's1', subject='', type_='world'), _row('b', 's3', status='rejected',
                                                             type_='world')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == []
    rows = [_row('f', 's1'), _row('b', 's3', status='rejected')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == []


def test_a_blank_subject_reaches_every_later_fact_of_its_type_and_is_still_said():
    """#473: world rules with no subject were contradicted later and
    traced to nothing."""
    rows = [_row('f', 's1', subject='', type_='world'), _row('a', 's2', subject='ivra',
                                                              type_='world'),
            _row('b', 's3', subject='ivra', type_='physical')]
    found = ledger.dependents(rows, ['f'], ORDER)
    assert found.scenes == ['s2']
    assert found.unrelated['f'] == 'no subject: every later scene with a world fact is listed'


def test_a_later_statement_naming_the_subject_is_a_dependent():
    """#473: Wick's state, contradicted by Nora's knowledge that she sat
    in Wick's house."""
    rows = [_row('f', 's1', subject='wick'),
            _row('a', 's2', subject='nora', type_='knowledge',
                 statement="Nora sat in Wick's house yesterday"),
            _row('b', 's3', subject='nora', statement='Nora is wickedly tired')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == ['s2']


def test_a_later_subject_the_statement_names_is_a_dependent():
    """#473: the Lamp's rule, contradicted in what the Keeper told Nora."""
    rows = [_row('f', 's1', subject='the-great-lamp', type_='world',
                 statement="The Folk's lanterns and the Keeper's flame share one fire"),
            _row('a', 's3', subject='keeper', type_='knowledge', statement='x')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == ['s3']


def test_registry_names_and_aliases_match_and_short_ones_dont():
    names = {'hank-voigt': {'hank voigt', 'hank', 'hv'}, 'maren-cole': {'the cole woman'}}
    rows = [_row('f', 's1', subject='hank-voigt'),
            _row('a', 's2', subject='claire', statement='Claire calls Hank'),
            _row('b', 's3', subject='claire', statement='HV is on the form'),
            _row('g', 's1', subject='maren-cole'),
            _row('c', 's4', subject='x', statement='Cole woman leaves')]
    assert ledger.dependents(rows, ['f'], ORDER, names=names).scenes == ['s2']
    assert ledger.dependents(rows, ['f'], ORDER).scenes == []    # ids only without names
    assert ledger.dependents(rows, ['g'], ORDER, names=names).scenes == ['s4']   # "the" dropped


def test_subject_names_reads_characters_and_locations(project_dir):
    names = ledger.subject_names(project_dir)
    assert {'dorren hayle', 'dorren', 'hayle'} <= names['dorren-hayle']
    assert 'the study' in names['private-study']


def test_several_facts_union_in_reading_order():
    rows = [_row('f', 's1', subject='hank'), _row('g', 's2', subject='maren'),
            _row('a', 's4', subject='hank'), _row('b', 's3', subject='maren')]
    assert ledger.dependents(rows, {'f', 'g'}, ORDER).scenes == ['s3', 's4']


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
    found = ledger.dependents([_row('f', 's1')], ['f', 'gone'], ORDER)
    assert found.unrelated == {'gone': 'not in the ledger rows given'}


def test_a_blank_subject_is_said_even_when_linked():
    rows = [_row('f', 's1', subject=''), _row('a', 's2', subject='', type_='trait',
                                               supersedes='f')]
    found = ledger.dependents(rows, ['f'], ORDER)
    assert found.scenes == ['s2'] and 'no subject' in found.unrelated['f']


def test_subjects_match_in_any_case():
    rows = [_row('f', 's1', subject='Hank'), _row('a', 's2', subject='hank')]
    assert ledger.dependents(rows, ['f'], ORDER).scenes == ['s2']


def test_a_knowledge_fact_reaches_scenes_about_who_knows_it():
    rows = [_row('f', 's1', subject='', type_='knowledge', known_by='maren;hank'),
            _row('a', 's2', subject='maren', type_='physical'),
            _row('b', 's3', subject='claire', type_='knowledge')]
    found = ledger.dependents(rows, ['f'], ORDER)
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
