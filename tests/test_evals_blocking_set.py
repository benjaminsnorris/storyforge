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
        assert suite.cassettes().startswith(str(tmp_path))
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
    ])
    def test_malformed_case(self, tmp_path, field, value, expected):
        case = _case('tale-001')
        case[field] = value
        problems = blocking_set.validate(*_loaded(tmp_path, cases=[case]))
        assert len(problems) == 1 and expected in problems[0]

    def test_a_fixed_slip_in_a_clean_scene_is_a_problem(self, tmp_path):
        bad = [_case('tale-001', scene='rain', quotes=(COAT,))]
        assert 'role is not case' in blocking_set.validate(*_loaded(tmp_path, cases=bad))[0]

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
        metrics, _ = self._score(tmp_path, {('tale', 'harbour'): [_flag(HOLDS_BOTH)],
                                            ('tale', 'rain'): []})
        assert metrics['book_scope_cases'] == 1 and metrics['book_scope_caught'] == 1
        assert metrics['cases'] == 3

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


class TestSuite:
    def test_records_beside_the_set_then_replays_free(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        calls = []
        monkeypatch.setattr(api, '_live_request', _fake_api(calls))
        suite = _suite()
        result = harness.run_suite(suite, 'record', str(tmp_path / 'public-cassettes'))
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
        result = harness.run_suite(_suite(), 'record', str(tmp_path / 'c'))
        text = json.dumps({k: result[k] for k in ('metrics', 'gates', 'notes', 'error')})
        for words in (FREE_HAND, HOLDS_BOTH, COAT, 'both hands full', 'harbour', 'rain'):
            assert words.lower() not in text.lower(), words
        assert 'tale-002' in text                       # missed cases are named by id

    def test_outcomes_and_findings_go_to_the_private_set(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_api([]))
        harness.run_suite(_suite(), 'record', str(tmp_path / 'c'))
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
        result = harness.run_suite(suite, 'record', str(tmp_path / 'c'))
        assert result['status'] == 'pass', result['gates']

    def test_a_drop_below_a_floor_fails(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', _fake_api([]))
        suite = _suite()
        _with_floors(monkeypatch, suite, recall=0.6667)
        result = harness.run_suite(suite, 'record', str(tmp_path / 'c'))
        assert result['status'] == 'fail'
        assert any('moving the floor is a decision' in n for n in result['notes'])

    def test_replay_with_no_recording_errors_and_never_goes_live(self, private_set, tmp_path,
                                                                 monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error'
        assert all(f.startswith('CassetteMiss') for f in result['cassette_failures'])

    def test_a_malformed_set_errors_without_quoting_it(self, tmp_path, monkeypatch):
        root = tmp_path / 'private'
        _write_set(root, cases=[_case('tale-001', quotes=('not in the scene at all',))])
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(root))
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error'
        assert 'tale-001: quote 1 is not in its scene' in result['error']
        assert 'not in the scene at all' not in result['error']

    def test_no_private_set_is_an_error_naming_where_it_goes(self, tmp_path, monkeypatch):
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path / 'nowhere'))
        monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error' and 'SetMissing' in result['error']
        assert 'STORYFORGE_CASSETTE' not in os.environ

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
        assert 'did not finish on 1 scene' in result['error']

    def test_the_pov_reaches_the_prompt(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        calls = []
        monkeypatch.setattr(api, '_live_request', _fake_api(calls))
        harness.run_suite(_suite(), 'record', str(tmp_path / 'c'))
        assert any('Point of view: Tom' in c for c in calls)
