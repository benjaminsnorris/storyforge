"""Tests for reverse elaboration extraction helpers (migrated from test-extract.sh)."""

import os
import shutil


class TestParseCharacterizeResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_characterize_response
        response = (
            'NARRATIVE_MODE: third-limited\n'
            'POV_CHARACTERS: Dorren Hayle;Tessa Merrin\n'
            'TIMELINE: linear\nTIMELINE_SPAN: 3 weeks\n'
            'SCENE_BREAK_STYLE: explicit-markers\nESTIMATED_SCENES: 42\n'
            'MAJOR_THREADS: institutional-failure;chosen-blindness;the-anomaly\n'
            'CENTRAL_CONFLICT: A cartographer must choose between institutional loyalty and truth\n'
            'CAST_SIZE: 12'
        )
        result = parse_characterize_response(response)
        assert result['narrative_mode'] == 'third-limited'
        assert 'Dorren Hayle;Tessa Merrin' in result['pov_characters']
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
        response = (
            'FUNCTION: Emmett reads the staged crime scene and connects the murder to a disappearance\n'
            'ACTION_SEQUEL: action\nEMOTIONAL_ARC: Professional detachment to resolved determination\n'
            'VALUE_AT_STAKE: truth\nVALUE_SHIFT: +/-\nTURNING_POINT: revelation\n'
            'CHARACTERS: Emmett Slade;Samuel Orcutt;Colson\n'
            'ON_STAGE: Emmett Slade;Colson\nMICE_THREADS: +inquiry:who-killed-orcutt\n'
            'CONFIDENCE: high'
        )
        result = parse_intent_response(response, 'arranged-dead')
        assert 'staged crime scene' in result['function']
        assert result['action_sequel'] == 'action'
        assert result['value_shift'] == '+/-'
        assert result['_confidence'] == 'high'


class TestParseBriefResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_brief_parallel_response
        response = (
            'GOAL: Determine cause of death and establish whether it is murder\n'
            'CONFLICT: The crime scene has been deliberately staged to look accidental\n'
            'OUTCOME: no-and\n'
            'CRISIS: Report the staging and alert the territorial marshal, or investigate quietly\n'
            'DECISION: Investigates quietly\n'
            'KEY_ACTIONS: Examines body;Notes staged positioning\n'
            'KEY_DIALOGUE: The body was found like this?\n'
            'EMOTIONS: professional-calm;suspicion\n'
            'MOTIFS: arranged-bodies;survey-equipment'
        )
        result = parse_brief_parallel_response(response, 'arranged-dead')
        assert 'cause of death' in result['goal']
        assert result['outcome'] == 'no-and'
        assert 'Report the staging' in result['crisis']


class TestParseKnowledgeResponse:
    def test_extracts_fields(self):
        from storyforge.extract import parse_knowledge_response
        response = (
            'KNOWLEDGE_IN: Orcutt was found dead at the alkali flat\n'
            'KNOWLEDGE_OUT: Orcutt was found dead;the body was deliberately staged;survey equipment present\n'
            'CONTINUITY_DEPS: discovery-at-flat\n'
            'SCENE_SUMMARY: Emmett examines the staged crime scene and decides to investigate quietly'
        )
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
        assert 'FUNCTION' in prompt and 'VALUE_SHIFT' in prompt and 'MICE_THREADS' in prompt


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


class TestValueAtStakeIsBare:
    """value_at_stake must be the value alone so the values registry can
    resolve it (The Great Gatsby yielded "truth — specifically ...")."""

    def _parse(self, value):
        from storyforge.extract import parse_intent_response
        return parse_intent_response(f'VALUE_AT_STAKE: {value}\n', 's1')['value_at_stake']

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
        text = ''.join(f'{k.upper()}: {v}\n' for k, v in fields.items())
        return parse_intent_response(text, 's1')

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
