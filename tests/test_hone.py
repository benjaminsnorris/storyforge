"""Tests for hone CSV data quality tool (migrated from test-hone.sh)."""

import os
import shutil


class TestHoneExports:
    def test_exports_reconcile_functions(self):
        from storyforge.hone import (
            build_registry_prompt,
            parse_registry_response,
            write_registry,
            apply_updates,
            apply_registry_normalization,
            reconcile_domain,
            reconcile_outcomes,
            normalize_outcomes,
            _collect_knowledge_chain,
            _collect_physical_state_chain,
        )

    def test_backwards_compatible_reconcile(self):
        from storyforge.reconcile import (
            build_registry_prompt,
            parse_registry_response,
            write_registry,
            apply_updates,
            reconcile_domain,
        )


class TestAbstractLanguageDetection:
    def test_detects_abstract_key_actions(self):
        from storyforge.hone import detect_abstract_fields
        row = {
            'id': 'test-scene',
            'key_actions': 'The realization building; connecting her hiding to the creatures hiding; the parallel crystallizing',
            'crisis': 'She could keep hiding or face the truth',
            'decision': 'She faces it',
            'knowledge_in': '',
            'knowledge_out': 'k01',
        }
        results = detect_abstract_fields({'test-scene': row})
        fields = [r['field'] for r in results]
        assert 'key_actions' in fields

    def test_concrete_not_flagged(self):
        from storyforge.hone import detect_abstract_fields
        row = {
            'id': 'test-scene',
            'key_actions': 'Naji leads her down a stairwell; the door at the bottom is painted gray; she holds the bowl and her hands shake',
            'crisis': 'Go through the door or walk away',
            'decision': 'She goes through the door',
            'knowledge_in': '',
            'knowledge_out': 'k01',
        }
        results = detect_abstract_fields({'test-scene': row})
        assert len(results) == 0


class TestConcretizePrompt:
    def test_builds_prompt(self):
        from storyforge.hone import build_concretize_prompt
        prompt = build_concretize_prompt(
            scene_id='mirror',
            fields=['key_actions'],
            current_values={'key_actions': 'The realization building; the parallel crystallizing'},
            voice_guide='Zara thinks in food metaphors. Sensory-first.',
            character_entry='Zara: 19, line cook, synesthete.',
        )
        assert 'physically does or perceives' in prompt
        assert 'realization building' in prompt

    def test_parses_response(self):
        from storyforge.hone import parse_concretize_response
        response = 'key_actions: Zara in the bathroom; light buzzing at copper-penny frequency'
        result = parse_concretize_response(response, 'mirror', ['key_actions'])
        assert 'Zara in the bathroom' in result.get('key_actions', '')


class TestDetectGaps:
    def test_detects_missing_fields(self):
        from storyforge.hone import detect_gaps
        scenes_map = {'s1': {'id': 's1', 'status': 'briefed', 'seq': '1'}}
        briefs_map = {'s1': {'id': 's1', 'goal': 'Do the thing', 'conflict': '',
                             'outcome': 'yes', 'crisis': '', 'decision': 'decides'}}
        intent_map = {'s1': {'id': 's1', 'function': 'Hook', 'value_at_stake': '',
                             'value_shift': '+/-', 'emotional_arc': 'calm to tense'}}
        results = detect_gaps(scenes_map, intent_map, briefs_map)
        fields = [r['field'] for r in results if r['scene_id'] == 's1']
        assert 'conflict' in fields
        assert 'crisis' in fields

    def test_no_gaps_for_complete(self):
        from storyforge.hone import detect_gaps
        scenes_map = {'s1': {'id': 's1', 'status': 'briefed', 'seq': '1'}}
        briefs_map = {'s1': {'id': 's1', 'goal': 'Do it', 'conflict': 'Obstacle',
                             'outcome': 'yes', 'crisis': 'Now or never', 'decision': 'Now'}}
        intent_map = {'s1': {'id': 's1', 'function': 'Hook', 'value_at_stake': 'truth',
                             'value_shift': '+/-', 'emotional_arc': 'calm to tense'}}
        results = detect_gaps(scenes_map, intent_map, briefs_map)
        assert len(results) == 0

    def test_skips_spine_scenes(self):
        from storyforge.hone import detect_gaps
        scenes_map = {'s1': {'id': 's1', 'status': 'spine', 'seq': '1'}}
        briefs_map = {'s1': {'id': 's1'}}
        intent_map = {'s1': {'id': 's1'}}
        results = detect_gaps(scenes_map, intent_map, briefs_map)
        assert len(results) == 0


class TestOverspecification:
    def test_flags_too_many_beats(self):
        from storyforge.hone import detect_overspecified
        briefs = {'s1': {'id': 's1', 'key_actions': 'a; b; c; d; e; f; g', 'emotions': 'x;y'}}
        scenes = {'s1': {'id': 's1', 'target_words': '1500'}}
        results = detect_overspecified(briefs, scenes)
        fields = [(r['field'], r['beat_count']) for r in results]
        assert ('key_actions', 7) in fields

    def test_reasonable_not_flagged(self):
        from storyforge.hone import detect_overspecified
        briefs = {'s1': {'id': 's1', 'key_actions': 'Enters room; Finds letter; Leaves',
                         'emotions': 'tension;calm'}}
        scenes = {'s1': {'id': 's1', 'target_words': '2500'}}
        results = detect_overspecified(briefs, scenes)
        assert len(results) == 0

    def test_excessive_emotions(self):
        from storyforge.hone import detect_overspecified
        briefs = {'s1': {'id': 's1', 'key_actions': 'Does thing',
                         'emotions': 'competence;unease;self-doubt;resolve'}}
        scenes = {'s1': {'id': 's1', 'target_words': '2500'}}
        results = detect_overspecified(briefs, scenes)
        fields = [r['field'] for r in results]
        assert 'emotions' in fields

    def test_absolute_threshold(self):
        from storyforge.hone import detect_overspecified
        briefs = {'s1': {'id': 's1', 'key_actions': 'a; b; c; d; e; f; g; h', 'emotions': 'x;y'}}
        scenes = {'s1': {'id': 's1', 'target_words': '8000'}}
        results = detect_overspecified(briefs, scenes)
        fields = [r['field'] for r in results]
        assert 'key_actions' in fields

    def test_two_beats_short_scene_not_flagged(self):
        """Issue #130: 2 beats is the functional minimum — never flag by density."""
        from storyforge.hone import detect_overspecified
        briefs = {'s1': {'id': 's1', 'key_actions': 'Enters room; Finds letter',
                         'emotions': 'tension'}}
        scenes = {'s1': {'id': 's1', 'target_words': '450'}}
        results = detect_overspecified(briefs, scenes)
        ka_results = [r for r in results if r['field'] == 'key_actions']
        assert len(ka_results) == 0

    def test_three_beats_short_scene_flagged(self):
        """3 beats in a short scene exceeds density — should still flag."""
        from storyforge.hone import detect_overspecified
        briefs = {'s1': {'id': 's1', 'key_actions': 'a; b; c', 'emotions': 'x'}}
        scenes = {'s1': {'id': 's1', 'target_words': '450'}}
        results = detect_overspecified(briefs, scenes)
        ka_results = [r for r in results if r['field'] == 'key_actions']
        assert len(ka_results) == 1


class TestVerboseFields:
    def test_flags_paragraph_decision(self):
        from storyforge.hone import detect_verbose_fields
        briefs = {
            's1': {
                'id': 's1',
                'decision': 'They hold. Naji breaks her deal and stands with the community. '
                            'The Hunter kills her \u2014 not erasure but death. She dies while every mind holds her name.',
            },
        }
        results = detect_verbose_fields(briefs)
        fields = [r['field'] for r in results]
        assert 'decision' in fields

    def test_terse_passes(self):
        from storyforge.hone import detect_verbose_fields
        briefs = {
            's1': {
                'id': 's1', 'decision': 'She goes through the door',
                'goal': 'Find the map', 'conflict': 'Guards block the entrance',
                'crisis': 'Now or never', 'key_actions': 'Opens door; Runs; Grabs map',
                'emotions': 'fear;relief',
            },
        }
        results = detect_verbose_fields(briefs)
        assert len(results) == 0


class TestCombinedDetection:
    def test_finds_all_types(self):
        from storyforge.hone import detect_brief_issues
        briefs = {
            's1': {
                'id': 's1',
                'key_actions': 'The realization dawns; connecting deeper; the parallel emerging; '
                               'crystallizing; the truth building; she transforms',
                'decision': 'They hold. Naji breaks her deal and stands with the community. '
                            'The Hunter kills her \u2014 not erasure but death. She dies while every mind holds her name.',
                'emotions': 'hope;dread;resolve;calm',
                'crisis': 'Stay or go', 'goal': 'Find truth', 'conflict': 'Opposition',
            },
        }
        scenes = {'s1': {'id': 's1', 'target_words': '1500'}}
        issues = detect_brief_issues(briefs, scenes)
        types = set(i['issue'] for i in issues)
        assert 'abstract' in types
        assert 'overspecified' in types
        assert 'verbose' in types

    def test_concretizable_fields(self):
        from storyforge.hone import _CONCRETIZABLE_FIELDS
        assert 'goal' in _CONCRETIZABLE_FIELDS
        assert 'conflict' in _CONCRETIZABLE_FIELDS
        assert 'emotions' in _CONCRETIZABLE_FIELDS


class TestSubtext:
    def test_in_briefs_cols(self):
        from storyforge.elaborate import _BRIEFS_COLS
        assert 'subtext' in _BRIEFS_COLS

    def test_in_schema(self):
        from storyforge.schema import COLUMN_SCHEMA
        assert 'subtext' in COLUMN_SCHEMA
        assert COLUMN_SCHEMA['subtext']['file'] == 'scene-briefs.csv'
        assert COLUMN_SCHEMA['subtext']['type'] == 'free_text'

    def test_verbose_flags_long_subtext(self):
        from storyforge.hone import detect_verbose_fields
        briefs = {
            's1': {
                'id': 's1',
                'subtext': 'Zara says she is fine but her synesthesia is worsening and she knows it '
                           'and everyone around her knows it too but nobody is willing to say it out loud '
                           'because they are all afraid of what it means for the community and for her specifically.',
            },
        }
        results = detect_verbose_fields(briefs)
        fields = [r['field'] for r in results]
        assert 'subtext' in fields

    def test_terse_subtext_passes(self):
        from storyforge.hone import detect_verbose_fields
        briefs = {
            's1': {
                'id': 's1',
                'subtext': 'Zara says she is fine but means the opposite; show through her hands shaking',
            },
        }
        results = detect_verbose_fields(briefs)
        fields = [r['field'] for r in results]
        assert 'subtext' not in fields

    def test_extract_parser_handles_subtext(self):
        from storyforge.extract import parse_brief_parallel_response
        response = (
            'GOAL: Find the map\nCONFLICT: Guards block the way\n'
            'OUTCOME: yes-but\nCRISIS: Fight or sneak\nDECISION: Sneaks past\n'
            'KEY_ACTIONS: Opens door; Grabs map\nKEY_DIALOGUE: Where is it?\n'
            'EMOTIONS: tension;relief\nMOTIFS: maps;darkness\n'
            'SUBTEXT: She tells the guard she is lost but she knows exactly where she is; '
            'show through confident body language that contradicts her words'
        )
        result = parse_brief_parallel_response(response, 'test-scene')
        assert 'subtext' in result
        assert 'confident body language' in result['subtext']

    def test_extract_parser_filters_none(self):
        from storyforge.extract import parse_brief_parallel_response
        response = 'GOAL: Find the map\nSUBTEXT: NONE'
        result = parse_brief_parallel_response(response, 'test-scene')
        assert 'subtext' not in result


class TestExemplars:
    def test_split_sentences(self):
        from storyforge.exemplars import split_sentences
        text = 'The car horn hit me in the chest. Violet. Deep, wet violet, the color of a bruise two days old. I blinked and it was gone.'
        sents = split_sentences(text)
        assert len(sents) >= 2

    def test_rhythm_signature(self):
        from storyforge.exemplars import compute_rhythm_signature
        text = (
            'The car horn hit me in the chest before I heard it.\n'
            'Violet. Deep, wet violet, the color of a bruise two days old.\n'
            'I blinked and it was gone.\n'
            'The prep station was just a prep station again: cutting boards, mise en place.\n'
            'Outside, the horn blared again. Lighter this time.\n'
            'I went back to the tomatoes. Knife work was good for this.'
        )
        sig = compute_rhythm_signature(text)
        assert sig is not None
        assert 'mean_sentence_words' in sig
        assert 'buckets' in sig
        assert sig['sentence_count'] >= 5

    def test_validate_exemplars_short(self):
        from storyforge.exemplars import validate_exemplars
        result = validate_exemplars('Too short.')
        assert not result['valid']
        assert any('Too short' in i for i in result['issues'])


class TestMiceDormancy:
    def test_detects_gaps(self, tmp_path):
        from storyforge.hone import detect_mice_dormancy

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 21):
                f.write(f's{i:02d}|{i}|Scene {i}|1|zara|loc|1|morning|1hr|action|drafted|1000|1500\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 21):
                mice = ''
                if i == 1:
                    mice = '+test-thread'
                elif i == 20:
                    mice = '-test-thread'
                f.write(f's{i:02d}|func|action|flat|truth|+/-|revelation|zara|zara|{mice}\n')

        with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('test-thread|Test Thread|inquiry|\n')

        gaps = detect_mice_dormancy(ref)
        assert len(gaps) == 1
        assert gaps[0]['thread_id'] == 'test-thread'
        assert gaps[0]['gap_size'] == 19

    def test_bare_mention_breaks_gap(self, tmp_path):
        """Issue #133: bare mentions (no +/- prefix) should reset dormancy."""
        from storyforge.hone import detect_mice_dormancy

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 21):
                f.write(f's{i:02d}|{i}|Scene {i}|1|zara|loc|1|morning|1hr|action|drafted|1000|1500\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 21):
                mice = ''
                if i == 1:
                    mice = '+test-thread'
                elif i == 10:
                    mice = 'test-thread'  # bare mention
                elif i == 20:
                    mice = '-test-thread'
                f.write(f's{i:02d}|func|action|flat|truth|+/-|revelation|zara|zara|{mice}\n')

        with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('test-thread|Test Thread|inquiry|\n')

        gaps = detect_mice_dormancy(ref)
        # With bare mention at s10, max gap is 9 (not 19), below threshold of 8+
        # So we get two sub-gaps of 9, each just above threshold
        for g in gaps:
            assert g['gap_size'] < 19, "Bare mention should split the 19-scene gap"

    def test_fill_prompt(self):
        from storyforge.hone import build_mice_fill_prompt
        prompt = build_mice_fill_prompt(
            thread_id='family-secret',
            thread_name='The Family Secret',
            thread_type='inquiry',
            gap_scenes=[
                {'id': 's05', 'title': 'The Mirror', 'goal': 'Recognize parallels',
                 'function': 'Self-reflection'},
            ],
            before_scene='s04',
            after_scene='s07',
        )
        assert 'family-secret' in prompt
        assert 'The Mirror' in prompt

    def test_parse_fill_response(self):
        from storyforge.hone import parse_mice_fill_response
        result = parse_mice_fill_response('MENTION: s05\nMENTION: s08\n')
        assert len(result) == 2
        assert parse_mice_fill_response('NONE\n') == []


class TestLoopFlag:
    def test_parse_loop_flag(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args(['--loop'])
        assert args.loop is True
        assert args.max_loops == 5

    def test_parse_max_loops(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args(['--loop', '--max-loops', '3'])
        assert args.max_loops == 3

    def test_loop_default_false(self):
        from storyforge.cmd_hone import parse_args
        args = parse_args([])
        assert args.loop is False


class TestCountBriefIssues:
    def test_counts_by_type(self, tmp_path):
        from storyforge.cmd_hone import _count_brief_issues

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s1|1|Scene 1|1|zara|loc|1|morning|1hr|action|briefed|1000|1500\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow|subtext\n')
            f.write('s1|Find truth|Opposition|yes|Stay or go|Decides|k01|k02|'
                    'The realization dawns; connecting deeper; the parallel emerging; '
                    'crystallizing; the truth building; she transforms|dialog|hope;dread;resolve;calm|m1||no|\n')

        counts = _count_brief_issues(ref, None)
        assert counts['total'] > 0
        assert 'abstract' in counts
        assert 'overspecified' in counts
        assert 'verbose' in counts
        assert counts['scenes'] == 1

    def test_zero_issues(self, tmp_path):
        from storyforge.cmd_hone import _count_brief_issues

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s1|1|Scene 1|1|zara|loc|1|morning|1hr|action|briefed|1000|2500\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow|subtext\n')
            f.write('s1|Find the map|Guards block entrance|yes|Now or never|Goes through|k01|k02|'
                    'Opens door; Grabs map; Runs|Where is it?|tension;relief|m1||no|\n')

        counts = _count_brief_issues(ref, None)
        assert counts['total'] == 0
        assert counts['scenes'] == 0
