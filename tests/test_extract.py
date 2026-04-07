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
