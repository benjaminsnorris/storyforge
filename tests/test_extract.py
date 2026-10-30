"""Tests for reverse elaboration extraction helpers (migrated from test-extract.sh)."""

import json
import os
import re
import shutil

import pytest


def _knowledge_reply(**fields):
    """A structured Phase 3b reply (KNOWLEDGE_SCHEMA) holding every required field."""
    reply = {'knowledge_in': [], 'knowledge_out': [], 'new_facts': [],
             'continuity_deps': [], 'scene_summary': ''}
    reply.update(fields)
    return json.dumps(reply)


def _physical_reply(**fields):
    """A structured Phase 3c reply (PHYSICAL_STATE_SCHEMA) holding every required field."""
    reply = {'physical_state_in': [], 'physical_state_out': [], 'new_states': [],
             'resolved_states': []}
    reply.update(fields)
    return json.dumps(reply)


def _reply(schema_name, **fields):
    """A structured reply for ``extract.<schema_name>``: every required field,
    empty unless given."""
    from storyforge import extract
    schema = getattr(extract, schema_name)
    reply = {k: [] if schema['properties'][k]['type'] == 'array' else ''
             for k in schema['required']}
    reply.update(fields)
    return json.dumps(reply)


class TestParseCharacterizeResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_characterize_response
        response = _reply('CHARACTERIZE_SCHEMA',
            narrative_mode='third-limited', pov_characters=['Dorren Hayle', 'Tessa Merrin'],
            timeline='linear', timeline_span='3 weeks', scene_break_style='explicit-markers',
            estimated_scenes='42',
            major_threads=['institutional-failure', 'chosen-blindness', 'the-anomaly'],
            central_conflict='A cartographer must choose between institutional loyalty and truth',
            cast_size='12')
        result = parse_characterize_response(response)
        assert result['narrative_mode'] == 'third-limited'
        assert result['pov_characters'] == 'Dorren Hayle; Tessa Merrin'
        assert result['estimated_scenes'] == '42'
        assert 'institutional-failure' in result['major_threads']


class TestParseSkeletonResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_skeleton_response
        response = (
            'TITLE: The Arranged Dead\nPOV: Emmett Slade\n'
            'LOCATION: Alkali Flat\nTIMELINE_DAY: 1\n'
            'TIME_OF_DAY: afternoon\nDURATION: 2 hours\n'
            'TARGET_WORDS: 1300\nPART: 1'
        )
        result = parse_skeleton_response(response, 'arranged-dead')
        assert result['id'] == 'arranged-dead'
        assert result['title'] == 'The Arranged Dead'
        assert result['pov'] == 'Emmett Slade'


class TestParseIntentResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_intent_response
        response = _reply('INTENT_SCHEMA',
            function='Emmett reads the staged crime scene and connects the murder to a disappearance',
            action_sequel='action', emotional_arc='Professional detachment to resolved determination',
            value_at_stake='truth', value_shift='+/-', turning_point='revelation',
            characters=['Emmett Slade', 'Samuel Orcutt', 'Colson'],
            on_stage=['Emmett Slade', 'Colson'], mice_threads=['+inquiry:who-killed-orcutt'],
            confidence='high')
        result = parse_intent_response(response, 'arranged-dead')
        assert 'staged crime scene' in result['function']
        assert result['action_sequel'] == 'action'
        assert result['value_shift'] == '+/-'
        assert result['_confidence'] == 'high'
        assert result['on_stage'] == 'Emmett Slade;Colson'


class TestParseBriefResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_brief_parallel_response
        response = _reply('BRIEF_PARALLEL_SCHEMA',
            goal='Determine cause of death and establish whether it is murder',
            conflict='The crime scene has been deliberately staged to look accidental',
            outcome='no-and',
            crisis='Report the staging and alert the territorial marshal, or investigate quietly',
            decision='Investigates quietly',
            key_actions=['Examines body', 'Notes staged positioning'],
            key_dialogue=['The body was found like this?'],
            emotions=['professional-calm', 'suspicion'],
            motifs=['arranged-bodies', 'survey-equipment'], subtext='none')
        result = parse_brief_parallel_response(response, 'arranged-dead')
        assert 'cause of death' in result['goal']
        assert result['outcome'] == 'no-and'
        assert 'Report the staging' in result['crisis']
        assert result['key_actions'] == 'Examines body;Notes staged positioning'
        assert 'subtext' not in result

    def test_unreadable_or_partial_reply_raises(self):
        from storyforge.extract import parse_brief_parallel_response
        with pytest.raises(ValueError, match='not a JSON object'):
            parse_brief_parallel_response('GOAL: x\n', 's1')
        with pytest.raises(ValueError, match='reply has no'):
            parse_brief_parallel_response('{"goal": "x"}', 's1')


class TestParseKnowledgeResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_knowledge_response
        response = _knowledge_reply(
            knowledge_in=['Orcutt was found dead at the alkali flat'],
            knowledge_out=['Orcutt was found dead', 'the body was deliberately staged',
                           'survey equipment present'],
            continuity_deps=['discovery-at-flat'],
            scene_summary='Emmett examines the staged crime scene and decides to investigate quietly')
        result = parse_knowledge_response(response, 'arranged-dead')
        assert 'Orcutt was found dead' in result['knowledge_in']
        assert 'deliberately staged' in result['knowledge_out']
        assert result['continuity_deps'] == 'discovery-at-flat'
        assert 'examines the staged' in result['_summary']


class TestAnalyzeExpansion:
    def test_produces_output(self, fixture_dir):
        from storyforge.extract import analyze_expansion_opportunities
        opps = analyze_expansion_opportunities(os.path.join(fixture_dir, 'reference'))
        assert isinstance(opps, list)


class TestBuildPrompts:
    def test_characterize_prompt(self, fixture_dir):
        from storyforge.extract import build_characterize_prompt
        prompt = build_characterize_prompt(fixture_dir)
        assert len(prompt) > 0

    def test_skeleton_prompt(self):
        from storyforge.extract import build_skeleton_prompt
        prompt = build_skeleton_prompt('act1-sc01', 'Some scene prose here.',
                                       {'pov_characters': 'Alice', 'timeline': 'linear'})
        assert 'POV' in prompt and 'TITLE' in prompt and 'LOCATION' in prompt

    def test_skeleton_prompt_asks_for_act_not_part(self):
        """Book parts come from the manuscript's part headings
        (scenes-setup); the model is asked only for the structural act."""
        from storyforge.extract import build_skeleton_prompt
        prompt = build_skeleton_prompt('act1-sc01', 'Some scene prose here.',
                                       {'pov_characters': 'Alice'})
        assert '\nACT: ' in prompt
        assert 'PART:' not in prompt

    def test_skeleton_response_maps_act_and_ignores_part(self):
        from storyforge.extract import parse_skeleton_response
        result = parse_skeleton_response('TITLE: T\nACT: 2\nPART: 1', 's1')
        assert result['act'] == '2'
        assert 'part' not in result

    def test_intent_prompt_context_names_the_act(self):
        from storyforge.extract import build_intent_prompt
        prompt = build_intent_prompt('s1', 'Prose.', {},
                                     {'title': 'T', 'act': '3', 'part': '1'})
        assert 'Act: 3' in prompt
        assert 'Part:' not in prompt

    def test_intent_prompt(self):
        from storyforge.extract import build_intent_prompt
        prompt = build_intent_prompt('act1-sc01', 'Scene prose.',
                                     {'major_threads': 'thread-a'},
                                     {'title': 'Test', 'pov': 'Alice'})
        assert '- function:' in prompt and '- value_shift:' in prompt and '- mice_threads' in prompt
        assert 'FUNCTION:' not in prompt

    def test_intent_prompt_offers_only_valid_value_shifts(self):
        """The prompt asks for exactly one shift, and every shift it names
        is one the schema allows.

        Without "exactly one", models invented shifts such as +/-- that
        validation rejects (Self-Control, Pride and Prejudice, The Plastic
        Age). The flat shifts (+/+, -/-) stay unoffered: offering them
        turned 45 of Self-Control's 247 scenes flat, a craft call (F-042).
        """
        from storyforge.extract import build_intent_prompt
        from storyforge.schema import VALID_VALUE_SHIFTS
        prompt = build_intent_prompt('s1', 'Prose.', {}, {'title': 'T'})
        line = next(l for l in prompt.splitlines() if l.startswith('- value_shift:'))
        named = set(re.findall(r'[+-]{1,2}/[+-]{1,2}', line))
        assert named == {'+/-', '-/+', '+/++', '-/--'} and named <= VALID_VALUE_SHIFTS
        assert 'exactly one' in line
        from storyforge.extract import INTENT_SCHEMA
        assert set(INTENT_SCHEMA['properties']['value_shift']['enum']) == named | {'unknown'}


class TestCleanupTimeline:
    def test_fills_gap(self, fixture_dir, tmp_path):
        from storyforge.extract import cleanup_timeline
        from storyforge.elaborate import update_scene

        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)
        update_scene('act1-sc02', ref, {'timeline_day': ''})

        fixes = cleanup_timeline(ref)
        scene_ids = [f['scene_id'] for f in fixes]
        assert 'act1-sc02' in scene_ids


class TestCleanupMiceThreads:
    def test_removes_duplicates(self, fixture_dir, tmp_path):
        from storyforge.extract import cleanup_mice_threads
        from storyforge.elaborate import update_scene

        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)
        update_scene('new-x1', ref, {
            'mice_threads': '+inquiry:archive-erasure;+inquiry:archive-erasure;-event:nonexistent'
        })

        fixes = cleanup_mice_threads(ref)
        all_text = ' '.join(str(f) for f in fixes)
        assert 'duplicate open' in all_text or len(fixes) > 0


class TestRunCleanup:
    def test_returns_summary(self, fixture_dir):
        from storyforge.extract import run_cleanup
        result = run_cleanup(os.path.join(fixture_dir, 'reference'))
        assert 'total_fixes' in result


class TestFidelityScoring:
    def test_parse_fidelity_response(self):
        from storyforge.scoring import parse_fidelity_response
        response = (
            'SCORES\nid|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|emotions|knowledge\n'
            'act1-sc01|4|3|4|3|4|5|4|3|4\n\n'
            'RATIONALE\nid|element|score|evidence\n'
            'act1-sc01|goal|4|Character clearly pursues the audit objective\n'
            'act1-sc01|conflict|3|Anomaly creates tension but opposition is indirect\n'
        )
        result = parse_fidelity_response(response, 'act1-sc01')
        assert result['scores']['goal'] == '4' or result['scores']['goal'] == 4
        assert result['scores']['conflict'] == '3' or result['scores']['conflict'] == 3

    def test_generate_fidelity_diagnosis(self):
        from storyforge.scoring import parse_fidelity_response, generate_fidelity_diagnosis
        r1 = parse_fidelity_response(
            'SCORES\nid|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|emotions|knowledge\n'
            's1|4|2|4|2|4|4|3|3|4', 's1'
        )
        r2 = parse_fidelity_response(
            'SCORES\nid|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|emotions|knowledge\n'
            's2|4|2|3|1|3|4|3|2|3', 's2'
        )
        diagnosis = generate_fidelity_diagnosis([r1, r2])
        elements = [d['element'] for d in diagnosis]
        priorities = [d['priority'] for d in diagnosis]
        assert 'crisis' in elements
        assert 'conflict' in elements
        assert 'high' in priorities

    def test_build_fidelity_prompt(self, fixture_dir, plugin_dir):
        from storyforge.scoring import build_fidelity_prompt
        prompt = build_fidelity_prompt('act1-sc01', fixture_dir, plugin_dir)
        assert len(prompt) > 0
        assert 'goal' in prompt.lower() and 'conflict' in prompt.lower()


class TestFitManuscript:
    """Phase 0 keeps the ending of an over-long manuscript (a short novel
    like The Great Gatsby, ~278k chars, used to lose its last chapters)."""

    def test_short_novel_sent_whole(self):
        from storyforge.extract import _fit_manuscript
        text = 'paragraph of prose.\n' * 14_000  # ~280k chars
        assert _fit_manuscript(text) == text

    def test_long_manuscript_keeps_opening_and_ending(self):
        from storyforge.extract import _fit_manuscript
        lines = [f'line {n} of the book.' for n in range(10_000)]
        text = '\n'.join(lines) + '\n'
        fitted = _fit_manuscript(text, limit=20_000)
        assert fitted.startswith('line 0 of the book.\n')
        assert fitted.endswith('line 9999 of the book.\n')
        assert len(fitted) < 21_000
        assert 'words from the middle of the manuscript are omitted' in fitted

    def test_trims_on_line_boundaries(self):
        from storyforge.extract import _fit_manuscript
        lines = [f'line {n} of the book.' for n in range(10_000)]
        fitted = _fit_manuscript('\n'.join(lines) + '\n', limit=20_000)
        kept = [l for l in fitted.splitlines() if l.startswith('line ')]
        assert all(l in set(lines) for l in kept)

    def test_marker_names_omitted_scenes(self):
        # Pride and Prejudice lost Hunsford and both halves of the first
        # proposal, and the profile called the cut "the excerpt omits the
        # structural heart". Naming the omitted scenes keeps their events
        # (scene ids are event slugs) in view.
        from storyforge.extract import _fit_manuscript
        scenes = [f'=== SCENE: scene-{n} ===\n\n' + 'prose line.\n' * 200
                  for n in range(40)]
        fitted = _fit_manuscript('\n\n'.join(scenes), limit=20_000)
        assert '=== SCENE: scene-0 ===' in fitted
        assert '=== SCENE: scene-39 ===' in fitted
        assert '=== SCENE: scene-20 ===' not in fitted
        assert 'scene-20' in fitted

    def test_prompt_says_the_cut_is_not_the_book(self, tmp_path, monkeypatch):
        from storyforge import extract
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: "T"\n')
        monkeypatch.setattr(extract, '_read_manuscript', lambda d: 'x\n' * 10)
        assert 'not a gap in the book' not in extract.build_characterize_prompt(str(tmp_path))
        monkeypatch.setattr(extract, 'CHARACTERIZE_MAX_CHARS', 8)
        assert 'not a gap in the book' in extract.build_characterize_prompt(str(tmp_path))


class TestValueAtStakeIsBare:
    """value_at_stake must be the value alone so the values registry can
    resolve it (The Great Gatsby yielded "truth — specifically ...")."""

    def _parse(self, value):
        from storyforge.extract import parse_intent_response
        return parse_intent_response(_reply('INTENT_SCHEMA', value_at_stake=value),
                                     's1')['value_at_stake']

    def test_em_dash_elaboration_dropped(self):
        assert self._parse('truth — specifically, the hidden past') == 'truth'

    def test_unspaced_em_dash_and_en_dash(self):
        assert self._parse('Truth—the gap between persona and reality') == 'Truth'
        assert self._parse('hope – that the past can return') == 'hope'

    def test_spaced_hyphen_and_colon(self):
        assert self._parse('love - whether it can be recovered') == 'love'
        assert self._parse('loyalty: to the dead') == 'loyalty'

    def test_hyphenated_value_kept(self):
        assert self._parse('self-respect') == 'self-respect'

    def test_prompt_asks_for_value_only(self):
        from storyforge.extract import build_intent_prompt
        prompt = build_intent_prompt('s1', 'Scene prose.', {}, {})
        assert 'Name only the value' in prompt


class TestEnumAnswersReduced:
    """Every action_sequel and turning_point from The Great Gatsby failed
    validation because the answer carried an explanation."""

    def _intent(self, **fields):
        from storyforge.extract import parse_intent_response
        return parse_intent_response(_reply('INTENT_SCHEMA', **fields), 's1')

    def test_explanations_dropped(self):
        r = self._intent(action_sequel='sequel — reaction: Nick broods',
                         turning_point='Revelation — Owl Eyes understands',
                         value_shift='+/- (the hope briefly sustained)')
        assert (r['action_sequel'], r['turning_point'], r['value_shift']) == (
            'sequel', 'revelation', '+/-')

    def test_longest_allowed_value_wins(self):
        assert self._intent(value_shift='-/-- worse')['value_shift'] == '-/--'
        assert self._intent(value_shift='-/-')['value_shift'] == '-/-'

    def test_unrecognized_answer_left_for_validation(self):
        assert self._intent(action_sequel='actionable')['action_sequel'] == 'actionable'
        assert self._intent(turning_point='a slow realization')['turning_point'] == 'a slow realization'

    def test_skeleton_time_of_day(self):
        from storyforge.extract import parse_skeleton_response
        r = parse_skeleton_response('TIME_OF_DAY: Evening (after dinner)\n', 's1')
        assert r['time_of_day'] == 'evening'


class TestKnowledgeIdsAtSource:
    """Phase 3b writes knowledge_in/out as ids from a registry built while the
    chain is extracted, not as sentences matched up afterwards (F-022)."""

    def test_prompt_offers_registry_ids(self):
        from storyforge.extract import build_knowledge_prompt
        prompt = build_knowledge_prompt(
            's2', 'Scene text.', {'pov': 'Nick'}, {},
            {'Nick': 'tom-affair-ny'}, [],
            known_facts={'tom-affair-ny': 'Tom has a mistress in New York',
                         'gatsby-throws-parties': 'Gatsby throws the parties'})
        assert '- tom-affair-ny — Tom has a mistress in New York' in prompt
        assert '- gatsby-throws-parties — Gatsby throws the parties' in prompt
        for field in ('knowledge_in', 'knowledge_out', 'new_facts', 'continuity_deps',
                      'scene_summary'):
            assert f'- {field}:' in prompt
        assert 'NEW_FACTS:' not in prompt and 'KNOWLEDGE_IN:' not in prompt
        assert 'IDs only, never sentences' in prompt
        assert 'at most 15 words' in prompt
        assert 'an empty list is a valid value' in prompt

    def test_parses_new_facts(self):
        from storyforge.extract import parse_knowledge_response
        result = parse_knowledge_response(_knowledge_reply(
            knowledge_in=['tom-affair-ny'],
            knowledge_out=['tom-affair-ny', 'myrtle-is-mistress', 'wilson-unaware'],
            new_facts=[
                {'id': 'myrtle-is-mistress', 'name': "Tom's mistress is Myrtle Wilson",
                 'category': 'identity'},
                {'id': 'wilson-unaware', 'name': 'George Wilson does not know of the affair',
                 'category': 'identity'},
            ],
            continuity_deps=['s1'],
            scene_summary='Nick meets Myrtle.'), 's2')
        assert [f['id'] for f in result['_new_facts']] == ['myrtle-is-mistress', 'wilson-unaware']
        assert result['_new_facts'][0]['category'] == 'identity'
        assert result['continuity_deps'] == 's1'
        assert result['_summary'] == 'Nick meets Myrtle.'

    @pytest.mark.parametrize('value', ['none', '(none)', 'None.', 'n/a', '(empty)', '-',
                                       'No new facts'])
    def test_placeholder_fields_are_empty(self, value):
        from storyforge.extract import parse_knowledge_response
        result = parse_knowledge_response(_knowledge_reply(
            knowledge_in=[value], knowledge_out=['fact-a', value],
            new_facts=[{'id': value, 'name': '', 'category': 'identity'}],
            continuity_deps=[value]), 's1')
        assert 'knowledge_in' not in result
        assert result['knowledge_out'] == 'fact-a'
        assert 'continuity_deps' not in result
        assert result['_new_facts'] == []

    def test_physical_state_placeholders_are_empty(self):
        from storyforge.extract import parse_physical_state_response
        result = parse_physical_state_response(_physical_reply(
            physical_state_in=['(none)'], physical_state_out=['none'],
            new_states=[{'id': 'none', 'character': '', 'description': '',
                         'category': 'injury', 'action_gating': False}],
            resolved_states=['none']), 's1')
        assert 'physical_state_in' not in result
        assert 'physical_state_out' not in result
        assert result['_new_states'] == []
        assert result['_resolved'] == []

    def test_registry_grows_and_names_resolve_to_ids(self):
        from storyforge.extract import merge_new_knowledge_facts, resolve_knowledge_ids
        registry = {'tom-affair-ny': {'id': 'tom-affair-ny', 'name': 'Tom has a mistress',
                                      'aliases': '', 'category': 'identity', 'origin': 's1'}}
        added = merge_new_knowledge_facts(registry, [
            {'id': 'tom-affair-ny', 'name': 'dup', 'category': ''},
            {'id': 'myrtle-is-mistress', 'name': 'The mistress is Myrtle', 'category': 'identity'},
        ], 's2')
        assert added == ['myrtle-is-mistress']
        assert registry['myrtle-is-mistress']['origin'] == 's2'
        assert registry['tom-affair-ny']['name'] == 'Tom has a mistress'
        assert resolve_knowledge_ids(
            registry, 'Tom has a mistress;myrtle-is-mistress;(none);something else'
        ) == 'tom-affair-ny;myrtle-is-mistress;something else'


class TestStructuredReplies:
    """Phase 3b/3c replies are structured outputs: an unreadable reply raises
    rather than reading as "nothing changed", and the schemas meet the API's
    structured-output rules."""

    def test_missing_required_field_raises(self):
        from storyforge.extract import parse_knowledge_response
        reply = json.loads(_knowledge_reply(knowledge_out=['fact-a']))
        del reply['continuity_deps']
        with pytest.raises(ValueError, match='continuity_deps'):
            parse_knowledge_response(json.dumps(reply), 's1')

    def test_non_json_raises(self):
        from storyforge.extract import parse_knowledge_response
        with pytest.raises(ValueError):
            parse_knowledge_response('The POV character learns nothing new.', 's1')

    def test_labeled_line_reply_raises(self):
        from storyforge.extract import parse_knowledge_response
        with pytest.raises(ValueError):
            parse_knowledge_response('**KNOWLEDGE_IN: a**', 's1')

    @staticmethod
    def _objects(schema, path='$'):
        """Every object schema within ``schema``, with its path."""
        if isinstance(schema, dict):
            if schema.get('type') == 'object':
                yield path, schema
            for key, sub in schema.get('properties', {}).items():
                yield from TestStructuredReplies._objects(sub, f'{path}.{key}')
            if 'items' in schema:
                yield from TestStructuredReplies._objects(schema['items'], f'{path}[]')

    @pytest.mark.parametrize('name', ['KNOWLEDGE_SCHEMA', 'PHYSICAL_STATE_SCHEMA'])
    def test_schemas_are_strict(self, name):
        from storyforge import extract
        objects = list(self._objects(getattr(extract, name)))
        assert len(objects) == 2  # the reply and its new_facts / new_states entries
        for path, obj in objects:
            assert sorted(obj['required']) == sorted(obj['properties']), path
            assert obj['additionalProperties'] is False, path


class TestCharacterizeBudget:
    """#355: Phase 0's budget was sized for a 200k window, so Pride and
    Prejudice (122k words) lost its middle 37.6k (Hunsford, the first
    proposal, the letter) though the model takes 1M tokens."""

    def test_budget_follows_the_models_window(self, monkeypatch):
        from storyforge import extract
        monkeypatch.setattr('storyforge.common.model_catalog', lambda: [
            {'id': 'big', 'max_input_tokens': 1_000_000},
            {'id': 'small', 'max_input_tokens': 200_000}])
        assert extract.characterize_budget('small') == extract.CHARACTERIZE_MAX_CHARS == 480_000
        assert extract.characterize_budget('big') > 3_000_000
        assert extract.characterize_budget('unlisted') == 480_000

    def test_long_novel_sent_whole_to_a_large_window(self, tmp_path, monkeypatch):
        from storyforge import extract
        monkeypatch.setattr('storyforge.common.model_catalog', lambda: [
            {'id': 'big', 'max_input_tokens': 1_000_000}])
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: "T"\n')
        book = 'prose line of the novel.\n' * 30_000  # ~750k chars, like P&P
        monkeypatch.setattr(extract, '_read_manuscript', lambda d: book)
        assert 'omitted here' in extract.build_characterize_prompt(str(tmp_path))
        assert 'omitted here' not in extract.build_characterize_prompt(str(tmp_path), model='big')


class TestCharacterizeLists:
    """Opus 5.5 answered ACT_STRUCTURE and STRUCTURAL_CONCERNS as bullet
    lists on Pride and Prejudice, and the line parser dropped the concerns.
    The reply is now structured; list fields join with "; "."""

    def test_list_fields_join(self):
        from storyforge.extract import parse_characterize_response
        result = parse_characterize_response(_reply(
            'CHARACTERIZE_SCHEMA', tone='ironic',
            act_structure='3 acts, following the volumes: Act I (scenes 1-62); Act II',
            structural_concerns=['Darcy fades', 'Kitty: thin'], cast_size='55'))
        assert result['tone'] == 'ironic'
        assert result['structural_concerns'] == 'Darcy fades; Kitty: thin'
        assert result['cast_size'] == '55'

    def test_empty_and_none_fields_dropped(self):
        from storyforge.extract import parse_characterize_response
        assert parse_characterize_response(_reply(
            'CHARACTERIZE_SCHEMA', timeline='linear', compression_points=['none'])) == {
            'timeline': 'linear'}


class TestExtractValidation:
    def test_schema_errors_fail_validation(self, fixture_dir):
        """F-058: extract logged "All validation checks pass" while
        `validate` found schema errors (Self-Control: 7), because it ran
        only the structural checks. The fixture has 6 schema errors."""
        from storyforge.cmd_extract import _run_validation
        from storyforge.schema import validate_schema
        ref = os.path.join(fixture_dir, 'reference')
        schema_failures = validate_schema(ref, fixture_dir)['failed']
        assert schema_failures > 0
        passed, failures = _run_validation(ref, fixture_dir)
        assert not passed
        # The structural report passes; its advisories aren't failures
        assert failures == schema_failures


class TestForcedChainClearsStaleFields:
    """A forced re-extraction kept the last run's knowledge and physical
    states wherever 3b/3c now found none: the parsers drop empty fields, so
    Gatsby's lunch with Wolfshiem still carried Myrtle's broken nose."""

    def _brief(self, project_dir, field):
        from storyforge.elaborate import get_scene
        return get_scene('act1-sc01', os.path.join(project_dir, 'reference'))[field]

    def _reply(self, project_dir, force):
        from storyforge.cmd_extract import _update_chain_fields
        ref = os.path.join(project_dir, 'reference')
        _update_chain_fields('act1-sc01', ref, {'id': 'act1-sc01'}, force,
                             ('knowledge_in', 'knowledge_out', 'continuity_deps'))

    def test_forced_empty_reply_clears_the_field(self, project_dir):
        assert self._brief(project_dir, 'knowledge_out') == 'map-anomaly-exists'
        self._reply(project_dir, force=True)
        assert self._brief(project_dir, 'knowledge_out') == ''

    def test_unforced_empty_reply_keeps_the_field(self, project_dir):
        self._reply(project_dir, force=False)
        assert self._brief(project_dir, 'knowledge_out') == 'map-anomaly-exists'

    def test_forced_reply_with_values_writes_them(self, project_dir):
        from storyforge.cmd_extract import _update_chain_fields
        ref = os.path.join(project_dir, 'reference')
        _update_chain_fields('act1-sc01', ref,
                             {'id': 'act1-sc01', 'physical_state_out': 'cut-hand'},
                             True, ('physical_state_in', 'physical_state_out'))
        assert self._brief(project_dir, 'physical_state_out') == 'cut-hand'
        assert self._brief(project_dir, 'physical_state_in') == ''


class TestForcedPhase3PrunesRegistries:
    """F-083 (Ben's decision, option 3): a forced phase 3 seeds the registries
    from the last run, so old entries piled up and stayed active. Afterwards
    keep what a brief uses or the pass declared; drop the rest."""

    def _ids(self, project_dir, name):
        from storyforge.elaborate import _read_csv_as_map
        return set(_read_csv_as_map(os.path.join(project_dir, 'reference', name)))

    def _add_rows(self, project_dir, name, rows):
        with open(os.path.join(project_dir, 'reference', name), 'a') as f:
            f.writelines(r + '\n' for r in rows)

    def test_drops_only_entries_nothing_uses(self, project_dir):
        from storyforge.cmd_extract import _prune_registries
        self._add_rows(project_dir, 'knowledge.csv',
                       ['stale-fact|An old fact|||act1-sc01', 'fresh-fact|New this pass|||act2-sc01'])
        self._add_rows(project_dir, 'physical-states.csv',
                       ['broken-nose-old|Tessa Merrin|old|injury|act1-sc01|never|true'])
        before_k = self._ids(project_dir, 'knowledge.csv')
        before_p = self._ids(project_dir, 'physical-states.csv')

        _prune_registries(os.path.join(project_dir, 'reference'),
                          created_facts={'fresh-fact'}, created_states=set())

        knowledge = self._ids(project_dir, 'knowledge.csv')
        states = self._ids(project_dir, 'physical-states.csv')
        assert 'stale-fact' not in knowledge
        assert 'fresh-fact' in knowledge            # declared this pass
        assert {'map-anomaly-exists', 'village-vanished'} <= knowledge   # in briefs
        assert 'broken-nose-old' not in states
        assert 'archive-key-dorren' in states       # in briefs
        # The fixture's own unused state goes too; every dropped id is unused
        assert 'sprained-ankle-tessa' not in states
        assert before_k - knowledge == {'stale-fact', 'subsidence-not-natural'}
        assert before_p - states == {'broken-nose-old', 'sprained-ankle-tessa',
                                     'scar-left-hand-kael'}

    def test_keeps_columns_and_rows_of_kept_entries(self, project_dir):
        from storyforge.cmd_extract import _prune_registries
        path = os.path.join(project_dir, 'reference', 'physical-states.csv')
        with open(path) as f:
            header = f.readline()
        _prune_registries(os.path.join(project_dir, 'reference'), set(), set())
        with open(path) as f:
            assert f.readline() == header
            assert any(l.startswith('archive-key-dorren|Dorren Hayle|holds the restricted')
                       for l in f)

    def test_unforced_run_does_not_prune(self):
        import inspect
        from storyforge import cmd_extract
        src = inspect.getsource(cmd_extract._run_phase_3)
        assert 'if force:\n        _prune_registries(' in src
