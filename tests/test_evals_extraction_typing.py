"""Extraction typing (#788): matching labels to extracted facts and scoring
their `mutable`, on synthetic data. The suites' recordings measure the model."""

import json
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import extraction_typing as et  # noqa: E402
import harness  # noqa: E402

SCENE = {'id': 's', 'labels': [
    {'kind': 'worn', 'quote': 'in the gold armour his grandfather had worn'},
    {'kind': 'carried', 'quote': 'He carried a spear of ash'},
    {'kind': 'trait', 'quote': 'He was the last son of the house of Avel'},
    {'kind': 'held', 'quote': 'picked up the iron keys to the gate'},
]}


def _fact(quote, mutable, statement='st'):
    return {'quote': quote, 'mutable': mutable, 'statement': statement}


def test_a_label_matches_the_quote_sharing_most_words():
    found = [_fact('the gold coin', 'state'), _fact('gold armour his grandfather had', 'fixed')]
    assert et.match('in the gold armour his grandfather had worn', found) is found[1]


def test_too_few_shared_words_is_no_match():
    assert et.match('in the gold armour', [_fact('gold coins', 'state')]) is None


def test_function_words_never_match():
    """#790's review SF-3: "the", "on", "his" are in every quote."""
    assert et.match('the gold on his armour', [_fact('the dog on his bed', 'state')]) is None


def test_one_fact_is_scored_for_one_label_only():
    """#790's review TD-5: a fact merging gear with hair answers the label it
    shares the most with; the other label is missing, not scored on it."""
    labels = [{'kind': 'worn', 'quote': 'his crest is yellow above the helmet rim'},
              {'kind': 'trait', 'quote': 'and so is the yellow hair under the helmet rim'}]
    merged = _fact('his crest is yellow and so is the hair under the rim of his helmet',
                   'fixed')
    got = et.assign(labels, [merged])
    assert got.count(merged) == 1 and got.count(None) == 1


def test_score_counts_right_typing_and_missing():
    found = [_fact('the gold armour his grandfather had worn', 'fixed', 'Brannoc wears gold'),
             _fact('He carried a spear of ash with a point', 'state'),
             _fact('He was the last son of the house of Avel', 'fixed')]
    metrics, notes = et.score([SCENE], {'s': found})
    assert metrics == {'state_right': 0.5, 'fixed_right': 1.0, 'state_found': 2,
                       'fixed_found': 1, 'missing': 1}
    assert any('typed fixed, should be state ("Brannoc wears gold")' in n for n in notes)
    assert any('iron keys' in n and n.endswith('missing') for n in notes)


def test_a_private_sets_notes_never_quote_it():
    found = [_fact('the gold armour his grandfather had worn', 'fixed', 'Brannoc wears gold')]
    _, notes = et.score([SCENE], {'s': found}, quote_labels=False)
    assert notes and not any('armour' in n or 'Brannoc' in n for n in notes)
    assert 's: label 1 (worn): typed fixed, should be state' in notes


def test_an_unknown_kind_raises():
    with pytest.raises(ValueError, match='kind'):
        et.score([{'id': 's', 'labels': [{'kind': 'hat', 'quote': 'a b c'}]}], {})


def test_the_book_set_missing_is_unavailable(tmp_path):
    with pytest.raises(harness.SuiteUnavailable):
        et.set_dir(str(tmp_path))


def test_the_public_fixture_has_every_kind_and_no_mutable_given():
    """The kind says what the typing should be; nothing else in a label."""
    cases = json.loads((PLUGIN_DIR / 'evals' / 'fixtures' / 'extraction-typing' /
                        'cases.json').read_text())
    kinds = {lab['kind'] for s in cases['scenes'] for lab in s['labels']}
    assert kinds == set(et.KINDS)
    assert all(set(lab) == {'kind', 'quote'} for s in cases['scenes'] for lab in s['labels'])
    # each label's words are in its scene
    for s in cases['scenes']:
        for lab in s['labels']:
            assert lab['quote'] in s['prose'], lab['quote']
