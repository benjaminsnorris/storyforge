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
        assert brief.stale == ['knowledge_out: village-vanished (village-vanished is rejected)']
        assert 'village-vanished' not in brief.fields.get('knowledge_out', '')

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


def test_a_broken_promise_under_a_made_up_id_verifies_by_its_words(project_dir):
    """E4 run 2: the checker named a word item 'gravel-abrasions-claire'
    and the finding was rejected as unverified, stopping the gate."""
    TestBriefItemsInWords()._words(project_dir)
    f = _finding(**{'kind': 'broken-promise', 'established_scene': '', 'scene_quote': '',
                    'fact_id': 'sleepless-dorren', 'established_quote': 'no sleep 36h'})
    result, _ = _run(project_dir, [_answer([f])])
    assert [x.fact_id for x in result.findings] == ['physical_state_out']


class TestReview450:
    """Fixes from #450's review."""

    @pytest.mark.parametrize('quote', ['no', 'sleep', 'no sleep'])
    def test_a_short_quote_under_a_made_up_id_does_not_verify(self, project_dir, quote):
        TestBriefItemsInWords()._words(project_dir)
        f = _finding(**{'kind': 'broken-promise', 'established_scene': '', 'scene_quote': '',
                        'fact_id': 'invented-thing', 'established_quote': quote})
        result, _ = _run(project_dir, [_answer([f])])
        assert result.findings == [] and len(result.unverified) == 1

    def test_an_entering_item_in_words_can_be_contradicted(self, project_dir):
        from storyforge.csv_cli import update_field
        update_field(f'{project_dir}/reference/scene-briefs.csv', SCENE,
                     'physical_state_in', 'left arm in a sling')
        f = _finding(established_scene='', fact_id='physical_state_in',
                     established_quote='left arm in a sling')
        result, _ = _run(project_dir, [_answer([f])])
        assert len(result.findings) == 1

    def test_without_disputes_the_schema_is_unchanged(self, project_dir):
        _, bodies = _run(project_dir, [_answer()])
        schema = bodies[0]['output_config']['format']['schema']
        assert 'cleared' not in schema['properties']
        assert 'may change' not in bodies[0]['messages'][0]['content']


def test_a_word_or_two_of_a_named_field_does_not_verify(project_dir):
    f = _finding(**{'kind': 'broken-promise', 'established_scene': '', 'scene_quote': '',
                    'fact_id': 'outcome', 'established_quote': 'no'})
    result, _ = _run(project_dir, [_answer([f])])
    assert result.findings == [] and 'whole item' in result.unverified[0].problem


class TestReference:
    """The bibles are in the checker's system prompt, and a finding against
    one verifies against its text (the E4 blind spot: a fact only a bible
    holds)."""
    BIBLE_QUOTE = 'Her mentor disappeared investigating a similar anomaly fifteen years ago'

    def test_the_bibles_are_the_system_prompt(self, project_dir):
        _, bodies = _run(project_dir, [_answer()])
        system = bodies[0]['system'][0]['text']
        assert '<reference file="character-bible.md">' in system
        assert self.BIBLE_QUOTE in system
        assert 'character-bible.md) also establishes facts' in bodies[0]['messages'][0]['content']

    def test_a_finding_against_a_bible_verifies_by_its_text(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='character-bible.md', established_quote=self.BIBLE_QUOTE)])])
        assert len(result.findings) == 1
        assert 'contradicts character-bible.md' in result.findings[0].message()

    def test_a_quote_not_in_the_bible_is_unverified(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='character-bible.md', established_quote='a sister named Marie')])])
        assert result.findings == []
        assert 'not in character-bible.md' in result.unverified[0].problem

    def test_a_template_bible_is_left_out_and_the_prompt_says_so(self, project_dir):
        import os
        import shutil
        from storyforge.common import get_plugin_dir
        shutil.copy(os.path.join(get_plugin_dir(), 'templates', 'reference', 'character-bible.md'),
                    os.path.join(project_dir, 'reference', 'character-bible.md'))
        _, bodies = _run(project_dir, [_answer()])
        assert '<reference' not in ''.join(b['text'] for b in bodies[0]['system'])
        assert 'no reference material' in bodies[0]['messages'][0]['content']
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='character-bible.md', established_quote='Role')])])
        assert result.findings == [] and 'not given to the checker' in result.unverified[0].problem

    def test_reference_docs_skips_missing_and_blank(self, project_dir):
        import os
        with open(os.path.join(project_dir, 'reference', 'world-bible.md'), 'w') as f:
            f.write('  \n')
        assert list(checker.reference_docs(project_dir)) == ['character-bible.md']

    def test_the_system_prompt_is_cached_and_the_same_for_every_scene(self, project_dir):
        _, first = _run(project_dir, [_answer()])
        with patch('storyforge.api._api_request', side_effect=[_answer()]) as api:
            check_scene(project_dir, 'act1-sc01', model='claude-opus-5-5')
        other = api.call_args[0][1]
        assert first[0]['system'][0] == other['system'][0]
        assert first[0]['system'][0]['cache_control'] == {'type': 'ephemeral'}

    def test_a_bible_that_is_not_utf8_is_a_check_error(self, project_dir):
        import os
        with open(os.path.join(project_dir, 'reference', 'world-bible.md'), 'wb') as f:
            f.write('caf\xe9'.encode('latin-1'))
        with pytest.raises(CheckError, match='world-bible.md'):
            _run(project_dir, [_answer()])

    def test_a_byte_order_mark_is_dropped(self, project_dir):
        import os
        path = os.path.join(project_dir, 'reference', 'world-bible.md')
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write('The river runs north.')
        assert checker.reference_docs(project_dir)['world-bible.md'] == 'The river runs north.'

    def test_a_bible_named_by_its_path_verifies_by_its_name(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='reference/character-bible.md',
            established_quote=self.BIBLE_QUOTE)])])
        assert result.findings[0].established_scene == 'character-bible.md'

    def test_a_bible_left_out_is_named_as_left_out(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='world-bible.md', established_quote='x')])])
        assert 'not given to the checker' in result.unverified[0].problem


class TestSearchShowsTheNearestHits:
    def _book(self, n):
        from storyforge.checker import Book
        order = {f's{i}': i for i in range(n)}
        prose = {f's{i}': f'The scar on his thumb, scene {i}. ' + 'x ' * 400 for i in range(n)}
        return Book(order, {}, prose, [])

    def test_nearest_earlier_first_then_later(self):
        out = checker._search(self._book(6), 's3', {'query': 'scar thumb'})
        order = [line.split(',')[0][1:] for line in out.splitlines()[1:]]
        assert order == ['s2', 's1', 's0', 's4', 's5']
        assert 'all shown' in out

    def test_many_hits_are_snippets_and_the_cap_is_said(self):
        out = checker._search(self._book(60), 's59', {'query': 'scar thumb'})
        lines = out.splitlines()
        assert f'the nearest {checker.MAX_SEARCH_HITS} shown' in lines[0]
        assert len(lines) == checker.MAX_SEARCH_HITS + 1
        assert lines[1].startswith('[s58, earlier]')
        assert all(len(line) < checker.SNIPPET_CHARS + 40 for line in lines[1:])


    def test_a_snippet_is_centred_on_the_match_despite_italics_and_prefixes(self):
        from storyforge.checker import Book
        para = 'Oscar ' + '*so* ' * 120 + 'the scar on his thumb ' + 'y ' * 300
        prose = {f's{i}': para for i in range(14)}
        book = Book({f's{i}': i for i in range(14)}, {}, prose, [])
        out = checker._search(book, 's13', {'query': 'scar thumb'})
        assert all('the scar on his thumb' in line for line in out.splitlines()[1:])

    def test_within_an_earlier_scene_its_last_paragraph_comes_first(self):
        from storyforge.checker import Book
        prose = {'a': 'first scar thumb.\n\nsecond scar thumb.', 'b': 'here'}
        out = checker._search(Book({'a': 0, 'b': 1}, {}, prose, []), 'b',
                              {'query': 'scar thumb'})
        assert out.splitlines()[1].endswith('second scar thumb.')


class TestStorySoFar:
    """The earlier scenes follow the bibles in the system prompt, whole, the
    way drafting sees them (E4 run 8: searching alone caught 2 of 9 scenes
    the judge, which reads them, found contradictions in)."""
    LATER = 'act2-sc01'

    def _system(self, project_dir, scene=LATER):
        with patch('storyforge.api._api_request', side_effect=[_answer()]) as api:
            check_scene(project_dir, scene, model='claude-opus-5-5')
        body = api.call_args[0][1]
        return body.get('system', []), body['messages'][0]['content']

    def test_earlier_scenes_follow_the_bibles_in_reading_order_cached(self, project_dir):
        system, prompt = self._system(project_dir)
        assert system[0]['text'].startswith("The book's reference material")
        assert 'THE STORY SO FAR' in system[1]['text']
        ids = [b['text'].split('"')[1] for b in system[2:]]
        assert ids == ['act1-sc01', 'act1-sc02', 'new-x1']
        assert THERE in system[2]['text']
        assert [b.get('cache_control') for b in system] == [
            {'type': 'ephemeral'}, None, None, None, {'type': 'ephemeral'}]
        assert 'story so far: 3 scene(s)' in prompt
        assert 'Some of the scenes' not in prompt

    def test_the_scene_checked_and_later_ones_are_not_sent(self, project_dir):
        system, _ = self._system(project_dir, 'act1-sc02')
        text = ''.join(b['text'] for b in system)
        assert '<scene id="act1-sc01"' in text
        assert 'id="act1-sc02"' not in text and 'id="new-x1"' not in text

    def test_the_first_scene_gets_no_story_and_the_search_instruction(self, project_dir):
        system, prompt = self._system(project_dir, 'act1-sc01')
        assert len(system) == 1
        assert 'Use the tools before you report anything' in prompt
        assert 'story so far:' not in prompt

    def test_without_bibles_the_story_is_the_whole_system_prompt(self, project_dir):
        import os
        for name in checker.REFERENCE_DOCS:
            path = os.path.join(project_dir, 'reference', name)
            if os.path.exists(path):
                os.remove(path)
        system, prompt = self._system(project_dir)
        assert 'THE STORY SO FAR' in system[0]['text']
        assert 'no reference material' in prompt

    def test_past_the_cap_it_gets_the_window_and_says_so(self, project_dir, monkeypatch, capsys):
        from storyforge import prompts
        monkeypatch.setattr(prompts, 'FULL_MAX_WORDS', 10)
        system, prompt = self._system(project_dir)
        ids = [b['text'].split('"')[1] for b in system[2:]]
        assert ids == ['new-x1']
        assert 'story so far: 1 scene(s)' in prompt
        assert prompt.count('Some of the scenes before this one') == 1
        assert 'the earlier scenes not shown there' in prompt
        assert 'act2-sc01 (the check):' in capsys.readouterr().out

    def test_the_scene_given_as_prose_is_checked_not_its_file(self, project_dir):
        import os
        with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md')) as f:
            on_disk = f.read().strip()
        with patch('storyforge.api._api_request', side_effect=[_answer()]) as api:
            check_scene(project_dir, SCENE, prose='Fresh draft words.',
                        model='claude-opus-5-5')
        body = api.call_args[0][1]
        system = ''.join(b['text'] for b in body['system'])
        assert 'Fresh draft words.' in body['messages'][0]['content']
        assert 'Fresh draft words.' not in system and on_disk not in system
        assert on_disk not in body['messages'][0]['content']

    def test_a_finding_quoting_the_story_so_far_verifies(self, project_dir):
        result, bodies = _run(project_dir, [_answer([_finding()])])
        assert THERE in ''.join(b['text'] for b in bodies[0]['system'])
        assert len(result.findings) == 1 and result.unverified == []

    def test_at_most_three_cache_breakpoints(self, project_dir):
        replies = [_tool_call('search_manuscript', {'query': 'calipers'}), _answer()]
        with patch('storyforge.api._api_request', side_effect=replies) as api:
            check_scene(project_dir, self.LATER, model='claude-opus-5-5')
        for call in api.call_args_list:
            body = call[0][1]
            marks = json.dumps(body).count('"cache_control"')
            assert marks <= 4    # the API's limit
            assert sum('cache_control' in b for b in body['system']) == 2

    def test_cut_and_merged_scenes_are_not_the_book(self, project_dir):
        from storyforge.elaborate import update_scene
        import os
        update_scene('act1-sc02', os.path.join(project_dir, 'reference'), {'status': 'cut'})
        system, prompt = self._system(project_dir)
        assert 'id="act1-sc02"' not in ''.join(b['text'] for b in system)
        assert '- act1-sc02:' not in prompt
        assert 'story so far: 2 scene(s)' in prompt
        replies = [_tool_call('read_scene', {'scene_id': 'act1-sc02'}),
                   _answer([_finding(scene_quote='The edge of the mapped world was not a line on the ground', kind='contradiction',
                                     established_scene='act1-sc02',
                                     established_quote=HERE)])]
        with patch('storyforge.api._api_request', side_effect=replies) as api:
            result = check_scene(project_dir, self.LATER, model='claude-opus-5-5')
        tool_reply = json.dumps(api.call_args_list[1][0][1]['messages'][-1])
        assert 'no scene' in tool_reply
        assert result.findings == []
        assert "'act1-sc02' is not a scene" in result.unverified[0].problem


class TestCalendar:
    """The checker sees each scene's day from scenes.csv (E8's thornwall-020:
    "Ten days" from day 5 to day 19 passed the gate with no calendar)."""

    def _sent(self, project_dir, scene=SCENE):
        with patch('storyforge.api._api_request', side_effect=[_answer()]) as api:
            check_scene(project_dir, scene, model='claude-opus-5-5')
        body = api.call_args[0][1]
        return ''.join(b['text'] for b in body.get('system', [])), body['messages'][0]['content']

    def test_the_scene_list_header_and_story_so_far_carry_the_day(self, project_dir):
        system, prompt = self._sent(project_dir)
        assert '- act1-sc01: The Finest Cartographer (POV Dorren Hayle, Pressure Cartography Office; day 1, morning)' in prompt
        assert '- new-x1: ' in prompt and 'day 2, afternoon)' in prompt
        assert "location: Dorren's private study; day 1, evening" in prompt
        assert 'this scene is day 1, evening' in prompt
        assert '<scene id="act1-sc01" when="day 1, morning">' in system

    def test_an_undated_book_gets_no_calendar_note(self, project_dir):
        import csv, os
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(path, newline='') as f:
            rows = list(csv.DictReader(f, delimiter='|'))
        for r in rows:
            r['timeline_day'] = r['time_of_day'] = ''
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter='|', lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
        system, prompt = self._sent(project_dir)
        assert '**The calendar.**' not in prompt
        assert '; day' not in prompt and 'when="' not in system

    def test_a_finding_against_a_calendar_line_verifies(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='scenes.csv', established_quote='act1-sc01: day 1, morning')])])
        assert len(result.findings) == 1 and result.unverified == []

    @pytest.mark.parametrize('quote', ['act1-sc01: day 4, morning', 'day 1', 'act1-sc01'])
    def test_a_quote_that_is_not_a_calendar_line_is_unverified(self, project_dir, quote):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='scenes.csv', established_quote=quote)])])
        assert result.findings == []
        assert "not a dated scene's line in the scene list" in result.unverified[0].problem

    @pytest.mark.parametrize('scene, quote', [
        ('scenes.csv', '- act1-sc01: The Finest Cartographer (POV Dorren Hayle, '
                       'Pressure Cartography Office; day 1, morning)'),
        ('scenes.csv', "act1-sc02: The Missing Village (POV Dorren Hayle, Dorren's private "
                       'study; day 1, evening)  <- this scene'),
        ('reference/scenes.csv', 'act1-sc01: day 1, morning'),
    ])
    def test_the_scene_list_line_and_the_file_path_verify(self, project_dir, scene, quote):
        """Recorded checks quoted the whole scene-list line (#478's review)."""
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene=scene, established_quote=quote)])])
        assert result.unverified == []
        assert result.findings[0].established_scene == 'scenes.csv'
        assert 'contradicts the calendar (scenes.csv)' in result.findings[0].message()

    def test_the_prompt_example_is_a_line_that_verifies(self, project_dir):
        _, prompt = self._sent(project_dir)
        example = prompt.split('copied whole from the scene list (for example `')[1].split('`')[0]
        assert checker.Book.load(project_dir, SCENE).in_calendar(example)

    def test_an_undated_scene_line_does_not_verify(self, project_dir):
        from storyforge.elaborate import update_scene
        import os
        update_scene('new-x1', os.path.join(project_dir, 'reference'),
                     {'timeline_day': '', 'time_of_day': ''})
        book = checker.Book.load(project_dir, SCENE)
        assert not book.in_calendar(book.index_line('new-x1'))
        assert book.in_calendar(book.index_line('act1-sc01'))


def test_the_prompt_asks_for_one_search_per_name_in_later_scenes(project_dir):
    """E8's thornwall-026: a later scene contradicted the redraft, and the
    re-check searched another Warden's name."""
    _, bodies = _run(project_dir, [_answer()])
    prompt = bodies[0]['messages'][0]['content']
    assert '**Later scenes too.**' in prompt
    assert 'one search per name' in prompt


class TestCalendarReview478:
    """#478's review: quote shapes, undated and time-only scenes, time_mode."""

    def _set(self, project_dir, sid, **cols):
        import os
        from storyforge.elaborate import update_scene
        update_scene(sid, os.path.join(project_dir, 'reference'), cols)

    def _prompt(self, project_dir):
        with patch('storyforge.api._api_request', side_effect=[_answer()]) as api:
            check_scene(project_dir, SCENE, model='claude-opus-5-5')
        body = api.call_args[0][1]
        return ''.join(b['text'] for b in body.get('system', [])), body['messages'][0]['content']

    @pytest.mark.parametrize('quote', ['"act1-sc01: day 1, morning"', "'act1-sc01: day 1, morning.'",
                                       '`act1-sc01: Day 1, Morning`'])
    def test_wrapped_or_recased_calendar_lines_verify(self, project_dir, quote):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='scenes.csv', established_quote=quote)])])
        assert result.unverified == [] and len(result.findings) == 1

    def test_a_scenes_when_cited_under_its_id_verifies_as_the_calendar(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='act1-sc01', established_quote='day 1, morning')])])
        assert result.unverified == []
        assert result.findings[0].established_scene == 'scenes.csv'

    def test_another_scenes_when_under_this_id_does_not(self, project_dir):
        result, _ = _run(project_dir, [_answer([_finding(
            established_scene='act1-sc01', established_quote='day 2, afternoon')])])
        assert 'not in act1-sc01' in result.unverified[0].problem

    def test_an_undated_scene_is_shown_a_dated_scenes_line_as_the_example(self, project_dir):
        self._set(project_dir, SCENE, timeline_day='', time_of_day='')
        _, prompt = self._prompt(project_dir)
        assert 'this scene has no day' in prompt
        example = prompt.split('copied whole from the scene list (for example `')[1].split('`')[0]
        assert example.startswith('act1-sc01:')
        assert checker.Book.load(project_dir, SCENE).in_calendar(example)
        assert f'- {SCENE}: The Missing Village (POV Dorren Hayle, Dorren\'s private study)' in prompt

    def test_a_book_with_times_but_no_days_gets_no_calendar_note(self, project_dir):
        for sid in checker.Book.load(project_dir, SCENE).order:
            self._set(project_dir, sid, timeline_day='')
        _, prompt = self._prompt(project_dir)
        assert '**The calendar.**' not in prompt
        assert '(POV Dorren Hayle, Pressure Cartography Office; morning)' in prompt

    def test_day_only_time_only_and_time_mode(self, project_dir):
        self._set(project_dir, 'act1-sc01', time_of_day='', time_mode='summary')
        self._set(project_dir, 'new-x1', timeline_day='', time_mode='frame')
        book = checker.Book.load(project_dir, SCENE)
        assert book.when('act1-sc01') == 'day 1, a summary: covers a stretch from that day'
        assert book.when('new-x1') == "afternoon, frame narration: not the story's present"
        assert book.calendar().splitlines()[0].startswith('act1-sc01: day 1')

    def test_a_time_only_scene_is_not_said_to_be_a_day(self, project_dir):
        self._set(project_dir, SCENE, timeline_day='')
        _, prompt = self._prompt(project_dir)
        assert 'this scene has no day' in prompt and 'this scene is evening' not in prompt

    def test_the_when_attribute_is_escaped(self, project_dir):
        self._set(project_dir, 'act1-sc01', time_of_day='"late" <night>')
        system, _ = self._prompt(project_dir)
        assert 'when="day 1, &quot;late&quot; &lt;night&gt;"' in system


# Words in act1-sc02 besides HERE
HERE2 = 'Blank parchment. Not even a contour line.'


class TestReadings:
    """Two readings of one scene find different things (E8, 2026-11-01:
    33 of 41 findings shared); the gate takes their union."""

    def test_each_reading_is_its_own_request_and_the_union_is_returned(self, project_dir):
        result, bodies = _run(project_dir, [_answer([_finding()]),
                                            _answer([_finding(scene_quote=HERE2)])],
                              readings=2)
        assert [f.scene_quote for f in result.findings] == [HERE, HERE2]
        assert result.readings == 2
        first, second = (b['messages'][0]['content'] for b in bodies)
        assert 'Reading 2' not in first and 'Reading 2: an independent check' in second
        assert first != second   # recordings are keyed by the request

    def test_one_reading_sends_what_it_always_sent(self, project_dir):
        _, bodies = _run(project_dir, [_answer()])
        assert 'Reading' not in bodies[0]['messages'][0]['content']

    def test_a_finding_both_readings_make_is_kept_once(self, project_dir):
        shorter = 'four hundred and twelve at last census'
        result, _ = _run(project_dir, [_answer([_finding()]),
                                       _answer([_finding(scene_quote=shorter)])],
                         readings=2)
        assert [f.scene_quote for f in result.findings] == [HERE]

    def test_the_same_words_against_another_source_are_two_findings(self, project_dir):
        result, _ = _run(project_dir, [
            _answer([_finding()]),
            _answer([_finding(established_scene='', fact_id='village-vanished',
                              established_quote='x')])], readings=2)
        assert len(result.findings) == 2

    def test_unverified_in_one_and_verified_in_the_other_is_a_finding(self, project_dir):
        result, _ = _run(project_dir, [
            _answer([_finding(established_quote='words act1-sc01 never says')]),
            _answer([_finding()])], readings=2)
        assert len(result.findings) == 1 and result.unverified == []

    def test_unverified_findings_of_both_readings_are_kept(self, project_dir):
        result, _ = _run(project_dir, [
            _answer([_finding(scene_quote='words the scene never says')]),
            _answer([_finding(scene_quote='other words it never says')])], readings=2)
        assert len(result.unverified) == 2

    def test_a_reading_that_fails_fails_the_check(self, project_dir):
        cut = dict(_answer(), stop_reason='max_tokens')
        with pytest.raises(CheckError, match=r'reading 2.*cut off'):
            _run(project_dir, [_answer([_finding()]), cut], readings=2)

    def test_the_second_reading_logs_beside_the_first(self, project_dir, tmp_path):
        log = tmp_path / 'gate-check-x.json'
        _run(project_dir, [_answer(), _answer()], readings=2, log_file=str(log))
        assert log.exists() and (tmp_path / 'gate-check-x.r2.json').exists()

    def test_readings_below_one_are_refused(self, project_dir):
        with pytest.raises(ValueError, match='at least 1'):
            _run(project_dir, [], readings=0)

    def test_kept_facts_are_unioned_by_id(self, project_dir):
        reading = [{'fact_id': 'village-vanished', 'quote': HERE}]
        result, _ = _run(project_dir, [_answer(kept=reading), _answer(kept=reading)],
                         readings=2)
        assert result.kept == [('village-vanished', HERE)]


def _promise(fact_id, item):
    return checker.Finding('broken-promise', 'PRM', '', '', item, fact_id, 'why')


def _contra(quote, source='s1', fact_id=''):
    return checker.Finding('contradiction', 'TIM', quote, source, 'x', fact_id, 'why')


class TestMergeReadings:
    def _merge(self, *readings, disputes=None):
        results = []
        for findings, cleared in readings:
            r = checker.CheckResult('s', findings=list(findings))
            r.cleared = [d for d in disputes or [] if d.fact_id in cleared]
            results.append(r)
        return checker.merge_readings(results, disputes)

    def test_a_dispute_any_reading_reports_is_a_finding(self):
        d = checker.Dispute('fact-1', 'stated', 'claimed')
        out = self._merge(([], {'fact-1'}), ([_contra('q', '', 'fact-1')], set()),
                          disputes=[d])
        assert out.cleared == [] and out.unruled == [] and len(out.findings) == 1

    def test_a_dispute_one_reading_clears_and_none_reports_is_cleared(self):
        d = checker.Dispute('fact-1', 'stated', 'claimed')
        out = self._merge(([], set()), ([], {'fact-1'}), disputes=[d])
        assert out.cleared == [d] and out.unruled == []

    def test_a_dispute_no_reading_rules_on_is_unruled(self):
        d = checker.Dispute('fact-1', 'stated', 'claimed')
        out = self._merge(([], set()), ([], set()), disputes=[d])
        assert out.unruled == [d]

    def test_one_broken_promise_reported_twice_is_one(self):
        out = self._merge(([_promise('outcome', 'the map is burned')], set()),
                          ([_promise('outcome', 'The map is burned.')], set()))
        assert len(out.findings) == 1

    def test_two_items_of_one_field_are_two_broken_promises(self):
        out = self._merge(([_promise('key_actions', 'she burns the map')], set()),
                          ([_promise('key_actions', 'she leaves the study')], set()))
        assert len(out.findings) == 2

    def test_one_reading_is_returned_as_it_is(self):
        r = checker.CheckResult('s', findings=[_contra('q')])
        assert checker.merge_readings([r]) is r
