"""Tests for storyforge.checker: the gate's tool-using check of one scene.
The model is mocked at `api._api_request`; the tools run for real."""

import json
from unittest.mock import patch

import pytest

from storyforge import checker
from storyforge.checker import CheckError, check_scene

SCENE = 'act1-sc02'
# Words in act1-sc02 and act1-sc01 (the fixture project)
HERE = "population four hundred and twelve at last census"
THERE = 'Dorren Hayle pressed the brass calipers against the vellum'


def _answer(findings=(), kept=()):
    return {'stop_reason': 'end_turn', 'model': 'claude-opus-5-5',
            'content': [{'type': 'text', 'text': json.dumps(
                {'findings': list(findings), 'kept': list(kept)})}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _tool_call(name, args):
    return {'stop_reason': 'tool_use', 'model': 'claude-opus-5-5',
            'content': [{'type': 'tool_use', 'id': 'tu1', 'name': name, 'input': args}],
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _finding(**over):
    f = {'kind': 'contradiction', 'code': 'TIM', 'scene_quote': HERE,
         'established_scene': 'act1-sc01', 'established_quote': THERE,
         'fact_id': '', 'explanation': 'why'}
    f.update(over)
    return f


def _run(project_dir, replies, **kw):
    bodies = []

    def fake(path, body, **k):
        bodies.append(json.loads(json.dumps(body)))
        return replies.pop(0)
    with patch('storyforge.api._api_request', side_effect=fake):
        result = check_scene(project_dir, SCENE, model='claude-opus-5-5', **kw)
    return result, bodies


class TestVerification:
    def test_a_finding_whose_quotes_hold_up_is_a_finding(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding()])])
        assert [f.code for f in result.findings] == ['TIM']
        assert result.unverified == []

    @pytest.mark.parametrize('over, why', [
        ({'scene_quote': 'words the scene never says'}, 'scene quote is not in the scene'),
        ({'established_quote': 'words act1-sc01 never says'}, 'not in act1-sc01'),
        ({'established_scene': 'nowhere'}, "'nowhere' is not a scene"),
        ({'established_scene': '', 'fact_id': 'no-such-fact'}, 'not a binding ledger fact'),
        ({'scene_quote': ''}, 'no scene quote'),
    ])
    def test_a_finding_that_does_not_hold_up_is_kept_apart(self, project_dir, over, why):
        result, _ = _run(project_dir, [_answer([_finding(**over)])])
        assert result.findings == []
        assert why in result.unverified[0].problem

    def test_a_ledger_fact_with_no_scene_verifies_by_id(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='', fact_id='village-vanished', established_quote='x')])])
        assert len(result.findings) == 1

    def test_quotes_match_across_line_breaks_spacing_and_end_punctuation(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            scene_quote='population  four hundred and\ntwelve at last census.')])])
        assert len(result.findings) == 1


class TestFailsLoud:
    def test_a_cut_off_reply_raises(self, project_dir):
        reply = _answer()
        reply['stop_reason'] = 'max_tokens'
        with pytest.raises(CheckError, match='cut off'):
            _run(project_dir, [reply])

    def test_an_off_schema_reply_raises(self, project_dir):
        reply = _answer()
        reply['content'][0]['text'] = 'not json'
        with pytest.raises(CheckError, match='not the schema'):
            _run(project_dir, [reply])

    def test_a_refusal_raises(self, project_dir):
        with pytest.raises(CheckError, match='refused'):
            _run(project_dir, [{'stop_reason': 'refusal', 'content': [], 'usage': {}}])

    def test_an_unknown_scene_raises(self, project_dir):
        with pytest.raises(CheckError, match='not a scene'):
            check_scene(project_dir, 'nope', model='m')


class TestTools:
    def test_search_finds_other_scenes_and_says_where(self, project_dir):
        book = checker.Book.load(project_dir, SCENE)
        out = checker._search(book, SCENE, {'query': 'brass calipers'})
        assert '[act1-sc01, earlier]' in out
        assert SCENE + ',' not in out   # never the scene being checked

    def test_search_with_no_words_is_an_input_error(self, project_dir):
        from storyforge.api import ToolInputError
        book = checker.Book.load(project_dir, SCENE)
        with pytest.raises(ToolInputError):
            checker._search(book, SCENE, {'query': ' ? '})

    def test_query_ledger_filters_and_labels(self, project_dir):
        book = checker.Book.load(project_dir, SCENE)
        out = checker._query_ledger(book, SCENE, {'subject': '', 'type': 'knowledge',
                                                  'text': 'village'})
        assert 'village-vanished [knowledge, state, registry' in out

    def test_a_tool_error_goes_back_to_the_model(self, project_dir):
        result, bodies = _run(project_dir, [_tool_call('read_scene', {'scene_id': 'nope'}),
                                            _answer()])
        sent = bodies[1]['messages'][2]['content'][0]
        assert sent['is_error'] and 'no scene' in sent['content']
        assert result.findings == []


class TestPromises:
    def test_the_brief_is_in_the_prompt_only_with_promises(self, project_dir):
        _, bodies = _run(project_dir, [_answer()], promises=False)
        assert "brief's promises" not in bodies[0]['messages'][0]['content']
        _, bodies = _run(project_dir, [_answer()])
        assert "brief's promises" in bodies[0]['messages'][0]['content']

    def test_kept_needs_a_promised_id_and_a_real_quote(self, project_dir):
        from storyforge.elaborate import get_scene
        scene = get_scene(SCENE, f'{project_dir}/reference')
        promised = scene['knowledge_out'].split(';')[0].strip()
        result, _ = _run(project_dir, [_answer(kept=[
            {'fact_id': promised, 'quote': HERE},
            {'fact_id': promised, 'quote': 'not in the scene'},
            {'fact_id': 'archive-erasure-not-promised', 'quote': HERE}])])
        assert result.kept == [(promised, HERE)]
        assert [why for _, _, why in result.kept_unverified] == [
            'the quote is not in the scene', 'not a fact the brief promises']


class TestReview439:
    """Fixes from #439's review."""

    def test_the_ledger_tool_says_where_a_state_ends_and_what_superseded_it(
            self, project_dir):
        from storyforge import ledger
        rows = ledger.load(project_dir)
        base = dict({c: '' for c in ledger.COLUMNS}, type='physical', origin='prose',
                    status='binding', mutable='state', introduced_by='draft', subject='tessa')
        rows += [dict(base, id='cut', statement='Tessa is cut', scene_id='act1-sc01',
                      resolves=SCENE),
                 dict(base, id='scar', statement='Tessa has a scar', scene_id='act1-sc01',
                      supersedes='cut')]
        book = checker.Book.load(project_dir, SCENE, rows=rows)
        out = checker._query_ledger(book, SCENE, {'subject': 'tessa', 'type': 'physical',
                                                  'text': ''})
        assert f'ends {SCENE}, this scene, superseded by scar' in out

    def test_entering_facts_are_not_promises(self, project_dir):
        book = checker.Book.load(project_dir, SCENE)
        brief = checker._brief(book, project_dir, SCENE)
        entering, promises = brief.text.split("## The brief's promises")
        assert 'map-anomaly-exists' in entering and 'must not contradict' in entering
        assert 'village-vanished' in promises and 'map-anomaly-exists' not in promises
        assert set(brief.promised) == {'village-vanished', 'archive-erasure',
                                       'archive-key-dorren', 'exhaustion-tessa'}

    @pytest.mark.parametrize('over, ok', [
        ({'fact_id': 'village-vanished'}, True),
        ({'fact_id': 'map-anomaly-exists'}, False),     # entering, not promised
        ({'fact_id': 'invented'}, False),
        ({'fact_id': 'outcome', 'established_quote': 'not the outcome at all'}, False),
    ])
    def test_a_broken_promise_must_name_a_promise_of_the_brief(self, project_dir, over, ok):
        f = _finding(**{'kind': 'broken-promise', 'established_scene': '', 'scene_quote': '',
                        'established_quote': '', **over})
        result, _ = _run(project_dir, [_answer([f])])
        assert bool(result.findings) is ok and bool(result.unverified) is not ok

    def test_a_broken_promise_quoting_its_field_verifies(self, project_dir):
        from storyforge.elaborate import get_scene
        outcome = get_scene(SCENE, f'{project_dir}/reference')['outcome']
        f = _finding(kind='broken-promise', established_scene='', scene_quote='',
                     fact_id='outcome', established_quote=outcome)
        result, _ = _run(project_dir, [_answer([f])])
        assert len(result.findings) == 1

    def test_a_short_kept_quote_is_not_evidence(self, project_dir):
        result, _ = _run(project_dir, [_answer(kept=[
            {'fact_id': 'village-vanished', 'quote': 'last census'}])])
        assert result.kept == []
        assert result.kept_unverified[0][2] == 'fewer than 4 words'

    def test_a_rejected_registry_fact_is_not_a_promise(self, project_dir):
        from storyforge import ledger
        rows = ledger.load(project_dir)
        next(r for r in rows if r['id'] == 'village-vanished')['status'] = 'rejected'
        ledger.save(project_dir, rows, command='test')
        book = checker.Book.load(project_dir, SCENE)
        brief = checker._brief(book, project_dir, SCENE)
        assert 'village-vanished' not in brief.promised
        assert 'knowledge_out: village-vanished' in brief.unknown

    def test_an_api_failure_is_a_check_error(self, project_dir):
        def boom(path, body, **k):
            raise RuntimeError('API returned HTTP 500')
        with patch('storyforge.api._api_request', side_effect=boom), \
                pytest.raises(CheckError, match='HTTP 500'):
            check_scene(project_dir, SCENE, model='m')


class TestBriefItemsInWords:
    """E4 at v1.101.0: 8 of 11 broken promises were physical_state_out items
    the brief writes in words ("no sleep 36h"), which no ledger fact names
    and the checker never checked. They are promises in words now."""

    def _words(self, project_dir):
        from storyforge.csv_cli import update_field
        update_field(f'{project_dir}/reference/scene-briefs.csv', SCENE,
                     'physical_state_out', 'archive-key-dorren;no sleep 36h')

    def test_a_promise_in_words_is_listed_and_checkable(self, project_dir):
        self._words(project_dir)
        book = checker.Book.load(project_dir, SCENE)
        brief = checker._brief(book, project_dir, SCENE)
        promises = brief.text.split("## The brief's promises")[1]
        assert '"no sleep 36h" (in words; no ledger fact names it)' in promises
        assert brief.fields['physical_state_out'] == 'no sleep 36h'
        assert 'archive-key-dorren' in brief.promised

    def test_a_broken_promise_in_words_verifies(self, project_dir):
        self._words(project_dir)
        f = _finding(**{'kind': 'broken-promise', 'established_scene': '', 'scene_quote': '',
                        'fact_id': 'physical_state_out',
                        'established_quote': 'no sleep 36h'})
        result, _ = _run(project_dir, [_answer([f])])
        assert len(result.findings) == 1 and result.unverified == []
