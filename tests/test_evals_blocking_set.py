"""The blocking set (#646): its loader, validation, matching and scoring, and
the suite end to end, on small synthetic sets written here (the real set is
private prose and never enters this repo). The API is faked at
`api._live_request`, so the cassette path is the real one."""

import json
import os
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import blocking_set  # noqa: E402
import harness  # noqa: E402
from blocking_set import runner  # noqa: E402

SUITE_FILE = PLUGIN_DIR / 'evals' / 'suites' / 'blocking_set.py'

# A tiny invented book: one scene with two slips, one clean scene
SLIPS = ('Tom held the lamp in his right hand and the rope in his left. '
         'He waved with his free hand to the boat. '
         'Ann sat on the step. Ann sat down beside him. '
         'The candle had gone out, and in the candlelight he read the letter.')
CLEAN = ('Ann stood at the door and looked out at the rain. She put on her coat, '
         'took the lantern from its hook and went down the path to the gate.')
FREE_HAND = 'He waved with his free hand to the boat.'
HOLDS_BOTH = 'Tom held the lamp in his right hand and the rope in his left.'
SAT_AGAIN = 'Ann sat down beside him.'
CANDLE = 'in the candlelight he read the letter'
COAT = 'She put on her coat'


def _case(cid, scene='harbour', category='hands', quotes=(FREE_HAND, HOLDS_BOTH),
          verdict='fixed', scope='scene', found_by='readers', **extra):
    return {'id': cid, 'book': 'tale', 'scene': scene, 'category': category,
            'scope': scope, 'verdict': verdict, 'quotes': list(quotes),
            'summary': 'invented', 'fix': '', 'found_by': found_by, 'kind': '', **extra}


CASES = [
    _case('tale-001'),
    _case('tale-002', category='posture', quotes=(SAT_AGAIN,), found_by='storyforge gate'),
    _case('tale-003', category='light', quotes=(CANDLE,)),
    _case('tale-004', scene='rain', category='worn', quotes=(COAT,), verdict='left'),
    _case('tale-005', category='position', quotes=(HOLDS_BOTH,), scope='book'),
]
SCENES = [
    {'book': 'tale', 'scene': 'harbour', 'pov': 'Tom', 'role': 'case', 'commit': 'abc1234'},
    {'book': 'tale', 'scene': 'rain', 'pov': 'Ann', 'role': 'clean', 'commit': 'abc1234'},
]
TEXTS = {'harbour': SLIPS, 'rain': CLEAN}


def _write_set(root, cases=CASES, scenes=SCENES, texts=TEXTS):
    path = root / blocking_set.SET_NAME
    (path / 'scenes' / 'tale').mkdir(parents=True)
    (path / 'cases.json').write_text(json.dumps({'cases': cases}))
    (path / 'scenes.json').write_text(json.dumps(scenes))
    for sid, text in texts.items():
        (path / 'scenes' / 'tale' / f'{sid}.md').write_text(text)
    return str(path)


def _loaded(tmp_path, **kw):
    return blocking_set.load(_write_set(tmp_path, **kw))


def _flag(*quotes, verified=True):
    return {'quotes': list(quotes), 'verified': verified}


class TestWhereTheSetLives:
    def test_missing_set_says_where_to_put_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))
        with pytest.raises(blocking_set.SetMissing, match='storyforge-evals') as e:
            blocking_set.set_dir()
        assert blocking_set.PRIVATE_ENV in str(e.value)

    def test_env_names_the_checkout(self, tmp_path, monkeypatch):
        path = _write_set(tmp_path)
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))
        assert blocking_set.set_dir() == path
        assert blocking_set.cassettes_dir('blocking-set') == os.path.join(
            path, 'cassettes', 'blocking-set')

    def test_default_is_the_evals_clone(self, monkeypatch):
        monkeypatch.delenv(blocking_set.PRIVATE_ENV, raising=False)
        assert blocking_set.private_dir() == os.path.expanduser('~/Developer/evals')

    def test_the_suite_records_beside_the_set_never_in_this_repo(self, tmp_path, monkeypatch):
        """A recording holds the request, and the request holds the scene: the
        suite's cassettes must not land in evals/fixtures/cassettes (#646)."""
        suite = next(s for s in harness.discover(str(SUITE_FILE.parent)) if s.name == 'blocking-set')
        assert suite.cassettes is not None
        _write_set(tmp_path)
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))
        assert suite.cassettes('').startswith(str(tmp_path))
        assert suite.cassettes('run2') == os.path.join(
            str(tmp_path), 'blocking-set', 'cassettes', 'run2', 'blocking-set')
        assert not (PLUGIN_DIR / 'evals' / 'fixtures' / 'cassettes' / 'blocking-set').exists()


class TestValidate:
    def test_a_sound_set_has_no_problems(self, tmp_path):
        assert blocking_set.validate(*_loaded(tmp_path)) == []

    def test_a_quote_not_in_its_scene_is_named_by_id_never_quoted(self, tmp_path):
        bad = [_case('tale-001', quotes=('He waved with both hands to the boat.',))]
        problems = blocking_set.validate(*_loaded(tmp_path, cases=bad))
        assert problems == ['tale-001: quote 1 is not in its scene']

    def test_fix_quotes_are_checked_too(self, tmp_path):
        bad = [_case('tale-001', fix_quotes=['words that are nowhere'])]
        assert blocking_set.validate(*_loaded(tmp_path, cases=bad)) == [
            'tale-001: quote 3 is not in its scene']

    @pytest.mark.parametrize('field,value,expected', [
        ('category', 'elbows', 'category must be one of'),
        ('verdict', 'maybe', 'verdict must be one of'),
        ('scope', 'series', 'scope must be one of'),
        ('scene', 'nowhere', 'its scene is not in scenes.json'),
        ('quotes', [], 'no quotes'),
        ('fix_quotes', 'a string', 'fix_quotes must be a list'),
        ('kind', 'odd', 'kind must be one of'),
        ('found_by', 'Readers', 'found_by must open with one of'),
        ('found_by', 'readership', 'found_by must open with one of'),
        ('id', '', 'case 1: no id'),
    ])
    def test_malformed_case(self, tmp_path, field, value, expected):
        case = _case('tale-001')
        case[field] = value
        # a second case keeps the harbour scene from being a case scene with none
        other = _case('tale-002', quotes=(SAT_AGAIN,))
        problems = blocking_set.validate(*_loaded(tmp_path, cases=[case, other]))
        assert len(problems) == 1 and expected in problems[0], problems

    def test_a_case_with_no_id_is_named_not_a_crash(self, tmp_path):
        case = _case('x')
        del case['id']
        problems = blocking_set.validate(*_loaded(tmp_path, cases=[case]))
        assert problems == ['case 1: no id']

    @pytest.mark.parametrize('found_by,subset', [
        ('readers', 'readers'), ('readers (open question)', 'readers'),
        ("author (Ben's note)", 'readers'), ('storyforge gate, blocking read', 'tool'),
        ('storyforge check --blocking (abc)', 'tool'), ('Readers', None), ('reader', None)])
    def test_who_found_a_case_is_an_explicit_subset(self, found_by, subset):
        assert blocking_set.finder({'found_by': found_by}) == subset

    def test_a_fixed_slip_in_a_clean_scene_is_a_problem(self, tmp_path):
        bad = [_case('tale-001', scene='rain', quotes=(COAT,))]
        problems = blocking_set.validate(*_loaded(tmp_path, cases=bad))
        assert any('role is not case' in p for p in problems)

    def test_a_case_scene_with_no_case_is_a_problem(self, tmp_path):
        problems = blocking_set.validate(*_loaded(tmp_path, cases=[CASES[3]]))
        assert problems == ['scene tale/harbour: role case, but no case is in it']

    def test_an_empty_set_is_a_problem_not_a_measurement(self, tmp_path):
        problems = blocking_set.validate(*_loaded(tmp_path, cases=[]))
        assert 'the set has no cases' in problems

    def test_a_quote_at_two_places_is_a_problem(self, tmp_path):
        """A quote that falls twice would let a finding at either place
        catch the case (#670 review: a 6-character fix quote fell at 9)."""
        bad = [_case('tale-001', quotes=('Ann sat',))]
        problems = blocking_set.validate(*_loaded(tmp_path, cases=bad))
        assert problems == ['tale-001: quote 1 falls at 2 places in its scene; '
                            'quote enough to name one']

    @pytest.mark.parametrize('scene,expected', [
        ({'book': 'Tale', 'scene': 'harbour', 'role': 'case'}, 'book and scene must be slugs'),
        ({'book': 'tale', 'scene': 'harbour', 'role': 'case'}, 'listed twice'),
        ({'book': 'tale', 'scene': 'harbour', 'role': 'draft'}, 'role must be one of'),
    ])
    def test_malformed_scene(self, tmp_path, scene, expected):
        scenes = SCENES + [scene] if expected != 'role must be one of' else [scene, SCENES[1]]
        problems = blocking_set.validate(*_loaded(tmp_path, scenes=scenes))
        assert any(expected in p for p in problems), problems

    def test_duplicate_ids_and_missing_prose(self, tmp_path):
        cases, scenes = _loaded(tmp_path, cases=[_case('tale-001'), _case('tale-001')],
                                texts={'harbour': SLIPS})
        problems = blocking_set.validate(cases, scenes)
        assert 'tale-001: id used 2 times' in problems
        assert any('scene tale/rain: no prose' in p for p in problems)


class TestMatching:
    def test_same_words_match_through_quote_and_case_differences(self):
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        a = blocking_set.spans(prose, '“He waved with his FREE hand”')
        b = blocking_set.spans(prose, 'his free hand to the boat')
        assert a and blocking_set.overlaps(a, b)

    def test_different_places_do_not_match(self):
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        assert not blocking_set.overlaps(blocking_set.spans(prose, FREE_HAND),
                                         blocking_set.spans(prose, SAT_AGAIN))

    def test_an_elided_quote_has_each_part_placed(self):
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        parts = blocking_set.spans(prose, 'Tom held the lamp ... with his free hand')
        assert len(parts) == 2
        assert blocking_set.overlaps(parts, blocking_set.spans(prose, FREE_HAND))

    def test_a_quote_not_in_the_prose_has_no_place(self):
        from storyforge.quotes import normalize
        assert blocking_set.spans(normalize(SLIPS), 'the moon rose') == []

    def test_a_part_inside_a_longer_word_is_no_place(self):
        """Whole words, as quote_in matches: 'he' is not inside 'the' or
        'held' (#670 review: a short part fell at every 'he')."""
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        places = blocking_set.places(prose, 'he')
        assert len(places) == 2                     # 'He waved', 'he read'
        assert not blocking_set.overlaps(blocking_set.spans(prose, 'he'),
                                         blocking_set.spans(prose, HOLDS_BOTH))

    def test_an_elided_quote_needs_its_parts_in_order(self):
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        assert blocking_set.spans(prose, 'with his free hand ... Tom held the lamp') == []

    def test_an_elided_quotes_parts_are_one_place_not_every_occurrence(self):
        """'Ann sat ... him' is the run that quote_in accepts, not every
        'him' or 'Ann sat' anywhere in the scene."""
        from storyforge.quotes import normalize
        prose = normalize(SLIPS + ' Later Ann sat alone.')
        places = blocking_set.places(prose, 'Ann sat ... him')
        assert len(places) == 2                     # each 'Ann sat' with the next 'him'
        assert all(len(p) == 2 for p in places)
        assert not blocking_set.overlaps(blocking_set.spans(prose, 'Ann sat ... him'),
                                         blocking_set.spans(prose, 'Later Ann sat alone'))


class TestMatch:
    """Each finding catches at most one case; each case is caught once."""

    def test_one_finding_on_a_shared_line_catches_one_case(self):
        """Two slips set against the same line: one finding set against it
        is one catch, not two (#670 review)."""
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        cases = [{'quotes': [FREE_HAND, HOLDS_BOTH]}, {'quotes': [SAT_AGAIN, HOLDS_BOTH]}]
        caught_by, landed = blocking_set.match(prose, [_flag(FREE_HAND, HOLDS_BOTH)], cases)
        assert caught_by == {0: 0} and landed == {0}

    def test_the_findings_own_slip_quote_wins_over_its_reference_line(self):
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        cases = [{'quotes': [HOLDS_BOTH]}, {'quotes': [SAT_AGAIN]}]
        caught_by, _ = blocking_set.match(prose, [_flag(SAT_AGAIN, HOLDS_BOTH)], cases)
        assert caught_by == {1: 0}

    def test_as_many_cases_as_the_findings_allow(self):
        """A greedy pick would give finding 0 case 0 and leave finding 1
        nothing; the matching moves finding 0 to case 1."""
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        cases = [{'quotes': [FREE_HAND]}, {'quotes': [SAT_AGAIN]}]
        findings = [_flag(FREE_HAND, SAT_AGAIN), _flag(FREE_HAND)]
        caught_by, landed = blocking_set.match(prose, findings, cases)
        assert caught_by == {0: 1, 1: 0} and landed == {0, 1}

    def test_a_second_reading_of_a_caught_slip_still_landed(self):
        from storyforge.quotes import normalize
        prose = normalize(SLIPS)
        caught_by, landed = blocking_set.match(prose, [_flag(FREE_HAND), _flag(FREE_HAND)],
                                               [{'quotes': [FREE_HAND]}])
        assert caught_by == {0: 0} and landed == {0, 1}


class TestScore:
    def _score(self, tmp_path, flags):
        cases, scenes = _loaded(tmp_path)
        return blocking_set.score(cases, scenes, flags)

    def test_recall_by_category_book_and_subset(self, tmp_path):
        # Catches the free hand (by its other side) and the second sitting
        metrics, outcomes = self._score(tmp_path, {
            ('tale', 'harbour'): [_flag(HOLDS_BOTH), _flag(SAT_AGAIN, 'Ann sat on the step.')],
            ('tale', 'rain'): []})
        assert metrics['cases'] == 3                    # fixed, scene scope
        assert metrics['caught'] == 2 and metrics['recall'] == 0.6667
        assert metrics['recall_hands'] == 1.0 and metrics['recall_posture'] == 1.0
        assert metrics['recall_light'] == 0.0
        assert 'recall_worn' not in metrics             # only a `left` case
        assert metrics['recall_book_tale'] == 0.6667
        assert metrics['recall_found_by_readers'] == 0.5   # tale-001 yes, tale-003 no
        assert metrics['recall_found_by_tool'] == 1.0
        assert {o['id']: o['caught'] for o in outcomes}['tale-003'] is False

    def test_book_scope_cases_are_reported_apart(self, tmp_path):
        # Two readings of the line both cases quote: one catch each
        metrics, _ = self._score(tmp_path, {('tale', 'harbour'): [_flag(HOLDS_BOTH), _flag(HOLDS_BOTH)],
                                            ('tale', 'rain'): []})
        assert metrics['book_scope_cases'] == 1 and metrics['book_scope_caught'] == 1
        assert metrics['cases'] == 3

    def test_one_finding_is_one_catch(self, tmp_path):
        metrics, outcomes = self._score(tmp_path, {('tale', 'harbour'): [_flag(HOLDS_BOTH)],
                                                   ('tale', 'rain'): []})
        assert metrics['caught'] + metrics['book_scope_caught'] == 1
        assert sum(o['caught'] for o in outcomes) == 1

    def test_an_outcome_names_its_finding_by_its_place_in_flags(self, tmp_path):
        _, outcomes = self._score(tmp_path, {
            ('tale', 'harbour'): [_flag('not in it', verified=False), _flag(SAT_AGAIN)],
            ('tale', 'rain'): []})
        assert {o['id']: o['findings'] for o in outcomes}['tale-002'] == [1]

    def test_false_alarms_per_10k_words_of_clean_prose(self, tmp_path):
        metrics, _ = self._score(tmp_path, {
            ('tale', 'harbour'): [],
            ('tale', 'rain'): [_flag(COAT), _flag('a quote not in it', verified=False)]})
        words = len(CLEAN.split())
        assert metrics['clean_words'] == words and metrics['clean_flags'] == 2
        assert metrics['false_alarms_per_10k'] == round(2 * 10000 / words, 2)
        assert metrics['left_flagged'] == 1            # COAT is a reading left as plausible
        assert metrics['unverified_flags'] == 1 and metrics['flags'] == 2

    def test_an_unverified_finding_catches_nothing(self, tmp_path):
        metrics, _ = self._score(tmp_path, {('tale', 'harbour'): [_flag(FREE_HAND, verified=False)],
                                            ('tale', 'rain'): []})
        assert metrics['caught'] == 0

    def test_unlabelled_flags_on_case_scenes_are_counted_not_scored(self, tmp_path):
        metrics, _ = self._score(tmp_path, {
            ('tale', 'harbour'): [_flag('The candle had gone out'), _flag(SAT_AGAIN)],
            ('tale', 'rain'): []})
        # 'The candle had gone out' is beside the light slip's quote, not on it
        assert metrics['unlabelled_flags'] == 1
        assert metrics['unlabelled_per_10k'] == round(10000 / len(SLIPS.split()), 2)
        assert metrics['false_alarms_per_10k'] == 0.0

    def test_a_scene_with_no_result_raises(self, tmp_path):
        with pytest.raises(ValueError, match='1 scene'):
            self._score(tmp_path, {('tale', 'harbour'): []})


# ----------------------------------------------------------------------------
# The suite end to end: real cassette, fake API, synthetic private set
# ----------------------------------------------------------------------------

def _reply(findings):
    return {'stop_reason': 'end_turn', 'model': 'claude-opus-5-5',
            'content': [{'type': 'text', 'text': json.dumps({'findings': findings})}],
            'usage': {'input_tokens': 1000, 'output_tokens': 100}}


def _fake_api(calls):
    """The blocking read's reply per scene: the free hand in the harbour,
    a false alarm on the coat in the rain."""
    def live(*args):
        body = json.dumps(args)
        calls.append(body)
        if 'Scene: harbour' in body:
            return _reply([{'kind': 'contradiction', 'scene_quote': FREE_HAND,
                            'other_quote': HOLDS_BOTH, 'explanation': 'both hands full'}])
        return _reply([{'kind': 'impossible', 'scene_quote': COAT, 'other_quote': '',
                        'explanation': 'a coat over the lantern'}])
    return live


@pytest.fixture
def private_set(tmp_path, monkeypatch):
    root = tmp_path / 'private'
    path = _write_set(root)
    monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(root))
    monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
    monkeypatch.setenv('STORYFORGE_PARALLEL', '1')
    return path


def _suite():
    return next(s for s in harness.discover(str(SUITE_FILE.parent)) if s.name == 'blocking-set')


def _with_floors(monkeypatch, suite, **floors):
    monkeypatch.setitem(suite.run.__globals__, 'FLOORS', dict(floors))


def _record(suite, root):
    """The suite is frozen: record it as run.py does for --suite NAME --runs 3."""
    return harness.run_suite(suite, 'record', root, record_frozen=True)


class TestSuite:
    def test_records_beside_the_set_then_replays_free(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        calls = []
        monkeypatch.setattr(api, '_live_request', _fake_api(calls))
        suite = _suite()
        assert suite.frozen
        result = _record(suite, str(tmp_path / 'public-cassettes'))
        assert len(calls) == 4                          # two scenes, two readings each
        assert result['metrics']['caught'] == 1 and result['metrics']['left_flagged'] == 1
        assert os.path.isdir(os.path.join(private_set, 'cassettes', 'blocking-set'))
        assert not (tmp_path / 'public-cassettes').exists()
        assert result['status'] == 'fail'               # FLOORS not recorded yet
        assert any('no floor recorded' in n for n in result['notes'])

        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        replayed = harness.run_suite(suite, 'replay', str(tmp_path / 'public-cassettes'))
        assert replayed['metrics'] == result['metrics']
        assert replayed['cost']['usd_spent'] == 0 and replayed['cost']['replayed_calls'] == 4

    def test_the_report_carries_no_prose(self, private_set, tmp_path, monkeypatch):
        """Metrics and notes reach evals/baseline.json, which is public: no
        quote, finding or explanation may be in them (#646)."""
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_api([]))
        result = _record(_suite(), str(tmp_path / 'c'))
        text = json.dumps({k: result[k] for k in ('metrics', 'gates', 'notes', 'error')})
        for words in (FREE_HAND, HOLDS_BOTH, COAT, 'both hands full', 'harbour', 'rain'):
            assert words.lower() not in text.lower(), words
        assert 'tale-002' in text                       # missed cases are named by id

    def test_outcomes_and_findings_go_to_the_private_set(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_api([]))
        _record(_suite(), str(tmp_path / 'c'))
        with open(os.path.join(private_set, 'results', 'latest.json')) as f:
            data = json.load(f)
        by_id = {c['id']: c for c in data['cases']}
        assert by_id['tale-001']['caught'] and not by_id['tale-002']['caught']
        assert data['findings']['tale/harbour'][0]['quotes'][0] == FREE_HAND

    def test_passes_when_the_run_matches_its_floors(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_api([]))
        suite = _suite()
        _with_floors(monkeypatch, suite, recall=0.3333, recall_hands=1.0, recall_posture=0.0,
                     recall_light=0.0, false_alarms_per_10k=round(10000 / len(CLEAN.split()), 2),
                     left_flagged=1, flags=2)
        monkeypatch.setitem(suite.run.__globals__, 'MIN_CASES', 3)
        result = _record(suite, str(tmp_path / 'c'))
        assert result['status'] == 'pass', result['gates']

    def test_a_drop_below_a_floor_fails(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_api([]))
        suite = _suite()
        _with_floors(monkeypatch, suite, recall=0.6667)
        result = _record(suite, str(tmp_path / 'c'))
        assert result['status'] == 'fail'
        assert any('moving the floor is a decision' in n for n in result['notes'])

    @pytest.mark.parametrize('mode', ['replay', 'auto', 'record'])
    def test_no_recording_is_stale_and_never_goes_live(self, private_set, tmp_path,
                                                       monkeypatch, mode):
        """Frozen (#645): a miss is stale, in any mode not asked by name."""
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        result = harness.run_suite(_suite(), mode, str(tmp_path / 'c'))
        assert result['status'] == 'stale', result.get('error')
        assert all(f.startswith('CassetteMiss') for f in result['cassette_failures'])

    def test_a_miss_carries_no_prose(self, private_set, tmp_path, monkeypatch):
        """A miss names the prompt's opening, which for a private suite could be
        the prose: it is withheld (#670 review)."""
        from storyforge import blocking
        monkeypatch.setattr(blocking, 'PROMPT', '{prose}' + blocking.PROMPT)
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        text = json.dumps(result)
        assert 'withheld' in text
        for words in (SLIPS[:40], CLEAN[:40], 'Tom held the lamp', 'looked out at the rain'):
            assert words.lower() not in text.lower(), words
        assert 'STORYFORGE_CASSETTE_PRIVATE' not in os.environ

    def test_a_malformed_set_errors_without_quoting_it(self, tmp_path, monkeypatch):
        root = tmp_path / 'private'
        _write_set(root, cases=[_case('tale-001', quotes=('not in the scene at all',))])
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(root))
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error'
        assert 'tale-001: quote 1 is not in its scene' in result['error']
        assert 'not in the scene at all' not in result['error']

    def test_no_private_set_is_unavailable_naming_where_it_goes(self, tmp_path, monkeypatch):
        """A clone without storyforge-evals (CI, every public one) isn't turned
        red: the suite is stale, unavailable, with where to put the set."""
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path / 'nowhere'))
        monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'stale' and result['unavailable'] is True
        assert result['error'] is None
        assert 'storyforge-evals' in result['stale'] and blocking_set.PRIVATE_ENV in result['stale']
        assert 'STORYFORGE_CASSETTE' not in os.environ

    def test_a_set_with_no_scenes_json_is_missing(self, tmp_path, monkeypatch):
        root = tmp_path / 'private'
        path = _write_set(root)
        os.remove(os.path.join(path, 'scenes.json'))
        with pytest.raises(blocking_set.SetMissing, match='scenes.json'):
            blocking_set.set_dir(str(root))

    @pytest.mark.parametrize('cases_json,scenes_json', [
        ({'case': []}, SCENES), ([], SCENES), ({'cases': {}}, SCENES),
        ({'cases': CASES}, {'scenes': SCENES})])
    def test_a_misshapen_file_raises_not_an_empty_set(self, tmp_path, cases_json, scenes_json):
        path = _write_set(tmp_path)
        with open(os.path.join(path, 'cases.json'), 'w') as f:
            json.dump(cases_json, f)
        with open(os.path.join(path, 'scenes.json'), 'w') as f:
            json.dump(scenes_json, f)
        with pytest.raises(ValueError):
            blocking_set.load(path)

    def test_a_scene_the_read_cannot_finish_errors_the_suite(self, private_set, tmp_path,
                                                             monkeypatch):
        from storyforge import blocking
        def check(project_dir, scene_id, **kw):
            if scene_id == 'rain':
                raise blocking.BlockingError('refused')
            return blocking.BlockingResult(scene_id)
        monkeypatch.setattr(blocking, 'check_blocking', check)
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error'
        assert 'did not finish on 1 scene(s): tale/rain' in result['error']
        # the exception's message can carry the reply's quotes: type only
        assert 'refused' not in result['error']
        assert 'refused' not in result.get('traceback', '')

    def test_the_pov_reaches_the_prompt(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        calls = []
        monkeypatch.setattr(api, '_live_request', _fake_api(calls))
        _record(_suite(), str(tmp_path / 'c'))
        assert any('Point of view: Tom' in c for c in calls)


def _floor_gates(suite, metrics):
    """The suite's gates on `metrics` against its FLOORS (as its run sets them)."""
    return runner.floor_gates(metrics, suite.run.__globals__['FLOORS'])


class TestFloorGates:
    """The shipped FLOORS keys, on the path before the baseline (all None)
    and after (#670 review: an absent metric passed as -1 == -1)."""

    def _metrics(self, suite):
        return {name: 0.5 for name in suite.run.__globals__['FLOORS']}

    def test_every_shipped_floor_unset_fails_and_says_what_to_write(self):
        suite = _suite()
        gates, notes = _floor_gates(suite, self._metrics(suite))
        assert gates and not any(g.passed for g in gates)
        assert all('no floor recorded' in n for n in notes)

    @pytest.mark.parametrize('floor', [None, 0.5])
    def test_an_absent_metric_fails_with_or_without_a_floor(self, monkeypatch, floor):
        suite = _suite()
        floors = {k: 0.5 for k in suite.run.__globals__['FLOORS']}
        floors['recall_other'] = floor
        _with_floors(monkeypatch, suite, **floors)
        metrics = self._metrics(suite)
        del metrics['recall_other']
        gates, notes = _floor_gates(suite, metrics)
        by_name = {g.name: g for g in gates}
        assert not by_name['recall_other'].passed
        assert all(g.passed for n, g in by_name.items() if n != 'recall_other')
        assert notes == [f'recall_other: the run has no such metric (no in-scene fixed case of '
                         f'it in the set?); FLOORS has {floor}']

    @pytest.mark.parametrize('name,value,word', [
        ('recall', 0.6, 'a gain'), ('recall', 0.4, 'a loss'),
        ('false_alarms_per_10k', 0.4, 'a gain'), ('false_alarms_per_10k', 0.6, 'a loss')])
    def test_a_gain_is_a_rise_for_recall_and_a_fall_for_false_alarms(self, monkeypatch, name,
                                                                     value, word):
        suite = _suite()
        _with_floors(monkeypatch, suite, **{name: 0.5})
        _, notes = _floor_gates(suite, {name: value})
        assert notes[0].startswith(f'{name} {value}, FLOORS 0.5: {word}')

    def test_the_independent_and_per_book_numbers_are_gated(self):
        floors = _suite().run.__globals__['FLOORS']
        for name in ('recall_found_by_readers', 'recall_found_by_tool',
                     'recall_book_gawain', 'recall_book_wrath'):
            assert name in floors


# ----------------------------------------------------------------------------
# The stage sheet on the same set (#647), and side by side
# ----------------------------------------------------------------------------

def _sheet_reply(payload):
    return {'stop_reason': 'end_turn', 'model': 'claude-haiku-5-5',
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 1000, 'output_tokens': 300}}


def _ev(quote, who, field, to, frm='', item=''):
    return {'quote': quote, 'who': who, 'field': field, 'item': item, 'from': frm, 'to': to}


def _fake_sheet_api(calls):
    """The stage sheet's extraction per scene: the harbour's hands and the
    second sitting down (two slips), and the rain's coat, clean."""
    def live(*args):
        body = json.dumps(args)
        calls.append(body)
        if '"answers"' in body:
            return _sheet_reply({'answers': []})
        if 'Scene: harbour' in body:
            return _sheet_reply({'cast': ['Tom', 'Ann'], 'questions': [], 'events': [
                _ev('Tom held the lamp in his right hand', 'Tom', 'hand_right', 'lamp'),
                _ev('the rope in his left', 'Tom', 'hand_left', 'rope'),
                _ev(FREE_HAND, 'Tom', 'hand_either', 'empty', frm='empty'),
                _ev('Ann sat on the step', 'Ann', 'posture', 'sitting'),
                _ev(SAT_AGAIN, 'Ann', 'posture', 'sitting', frm='standing')]})
        return _sheet_reply({'cast': ['Ann'], 'questions': [], 'events': [
            _ev(COAT, 'Ann', 'worn', 'on', frm='off', item='coat')]})
    return live


def _sheet_suite():
    return next(s for s in harness.discover(str(SUITE_FILE.parent))
                if s.name == 'blocking-set-sheet')


class TestSheetSuite:
    def test_records_beside_the_set_then_replays_free(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        calls = []
        monkeypatch.setattr(api, '_live_request', _fake_sheet_api(calls))
        suite = _sheet_suite()
        result = _record(suite, str(tmp_path / 'public-cassettes'))
        assert len(calls) == 2                          # one extraction a scene, no questions
        m = result['metrics']
        assert m['caught'] == 2 and m['recall_hands'] == 1.0 and m['recall_posture'] == 1.0
        assert m['left_flagged'] == 0 and m['false_alarms_per_10k'] == 0.0
        assert m['events'] == 6 and m['questions_asked'] == 0
        assert os.path.isdir(os.path.join(private_set, 'cassettes', 'blocking-set-sheet'))
        assert not (tmp_path / 'public-cassettes').exists()

        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        replayed = harness.run_suite(suite, 'replay', str(tmp_path / 'public-cassettes'))
        assert replayed['metrics'] == result['metrics']
        assert replayed['cost']['usd_spent'] == 0

    def test_the_report_carries_no_prose(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_sheet_api([]))
        result = _record(_sheet_suite(), str(tmp_path / 'c'))
        text = json.dumps({k: result[k] for k in ('metrics', 'gates', 'notes', 'error')})
        for words in (FREE_HAND, HOLDS_BOTH, COAT, SAT_AGAIN, 'harbour', 'rain', 'lamp'):
            assert words.lower() not in text.lower(), words

    def test_outcomes_go_to_their_own_private_file(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_sheet_api([]))
        _record(_sheet_suite(), str(tmp_path / 'c'))
        assert not os.path.exists(os.path.join(private_set, 'results', 'latest.json'))
        with open(os.path.join(private_set, 'results', 'latest-stage-sheet.json')) as f:
            data = json.load(f)
        # tale-005 shares tale-001's line: the one hands finding catches only
        # one of them (#670's matching)
        assert {c['id'] for c in data['cases'] if c['caught']} == {'tale-001', 'tale-002'}

    def test_without_a_read_run_the_comparison_says_so(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_sheet_api([]))
        result = _record(_sheet_suite(), str(tmp_path / 'c'))
        assert any(n.startswith('side by side: no read run to compare with')
                   for n in result['notes'])

    def test_side_by_side_with_the_read(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_api([]))
        _record(_suite(), str(tmp_path / 'c'))
        monkeypatch.setattr(api, '_live_request', _fake_sheet_api([]))
        result = _record(_sheet_suite(), str(tmp_path / 'c'))
        notes = result['notes']
        assert ('side by side with the read (its last run): caught by both 1, only here 1, '
                'only by the read 0, of 3') in notes
        assert 'only this caught: tale-002' in notes
        assert 'left readings flagged: here 0, by the read 1' in notes

    def test_a_scene_the_sheet_cannot_finish_errors_the_suite(self, private_set, tmp_path,
                                                              monkeypatch):
        from storyforge import stage_sheet

        def check(project_dir, scene_id, **kw):
            raise stage_sheet.StageSheetError('the reply quoted: secret words')
        monkeypatch.setattr(stage_sheet, 'check_stage_sheet', check)
        result = harness.run_suite(_sheet_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error'
        assert 'stage sheet did not finish on 2 scene(s): tale/harbour, tale/rain' in result['error']
        assert 'secret words' not in result['error']

    def test_frozen_a_miss_is_stale_and_never_goes_live(self, private_set, tmp_path,
                                                        monkeypatch):
        """Frozen like the read (#645, ported from #670): auto replays it."""
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        suite = _sheet_suite()
        assert suite.frozen
        result = harness.run_suite(suite, 'auto', str(tmp_path / 'c'))
        assert result['status'] == 'stale', result.get('error')

    def test_no_private_set_is_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path / 'nowhere'))
        result = harness.run_suite(_sheet_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'stale' and result['unavailable'] is True
        assert result['error'] is None
        assert 'storyforge-evals' in result['stale']

    def test_each_run_of_runs_n_records_on_its_own(self, tmp_path, monkeypatch):
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))
        _write_set(tmp_path)
        suite = _sheet_suite()
        assert suite.cassettes('') == os.path.join(str(tmp_path), 'blocking-set', 'cassettes',
                                                   'blocking-set-sheet')
        assert suite.cassettes('run2') == os.path.join(str(tmp_path), 'blocking-set',
                                                       'cassettes', 'run2', 'blocking-set-sheet')

    def test_it_gates_the_same_metrics_as_the_read(self):
        """The per-book and per-finder numbers are gated on the sheet too."""
        assert (set(_sheet_suite().run.__globals__['FLOORS'])
                == set(_suite().run.__globals__['FLOORS']))
