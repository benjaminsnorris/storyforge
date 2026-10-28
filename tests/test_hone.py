"""Tests for hone CSV data quality tool (migrated from test-hone.sh)."""

import os
import shutil


class TestHoneExports:
    def test_exports_reconcile_functions(self):
        from storyforge.hone import (
            build_mapping_prompt,
            parse_mapping_response,
            apply_mapping,
            write_registry,
            apply_registry_normalization,
            reconcile_domain,
            reconcile_outcomes,
            normalize_outcomes,
            _collect_knowledge_chain,
            _collect_physical_state_chain,
        )

    def test_backwards_compatible_reconcile(self):
        from storyforge.reconcile import (
            build_mapping_prompt,
            parse_mapping_response,
            apply_mapping,
            write_registry,
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


def _set_column(ref_dir, filename, column, values):
    """Set *column* in each row of *filename*: a list (by row) or a dict
    (by scene id). Rows not given get ''."""
    import csv as _csv
    path = os.path.join(ref_dir, filename)
    with open(path) as f:
        rows = list(_csv.DictReader(f, delimiter='|'))
        header = list(rows[0].keys())
    for i, row in enumerate(rows):
        if isinstance(values, dict):
            row[column] = values.get(row['id'], '')
        else:
            row[column] = values[i] if i < len(values) else ''
    with open(path, 'w') as f:
        w = _csv.DictWriter(f, fieldnames=header, delimiter='|', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def _column(ref_dir, filename, column):
    from storyforge.elaborate import _read_csv_as_map
    return {sid: row.get(column, '') for sid, row in
            _read_csv_as_map(os.path.join(ref_dir, filename)).items()}


def _mock_api(monkeypatch, responses, stop_reasons=None):
    """Answer each call with the next response; returns the prompts sent."""
    calls = []

    def fake_invoke(prompt, model, log_file, **kwargs):
        calls.append(prompt)
        n = len(calls) - 1
        with open(log_file, 'w') as f:
            f.write(responses[n])
        return {'stop_reason': (stop_reasons or {}).get(n, 'end_turn')}

    monkeypatch.setattr('storyforge.api.invoke_to_file', fake_invoke)
    monkeypatch.setattr('storyforge.api.extract_text_from_file',
                        lambda path: open(path).read())
    return calls


class TestUnresolvedReferences:
    """Every reference must resolve to a registry entry; a registry can
    silently omit some (The Great Gatsby: a bare "West Egg" beside
    "Gatsby's Mansion, West Egg"), and normalization passes unknowns through."""

    def _set_locations(self, ref_dir, locations):
        _set_column(ref_dir, 'scenes.csv', 'location', locations)

    def test_find_unresolved_lists_missing_references(self, project_dir):
        from storyforge.hone import find_unresolved
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_locations(ref_dir, ['the office', 'West Egg;the study',
                                      'Plaza Hotel (tea-garden)'])
        assert find_unresolved('locations', ref_dir) == ['Plaza Hotel', 'West Egg']

    def test_find_unresolved_accepts_canonical_ids(self, project_dir):
        from storyforge.hone import find_unresolved
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_locations(ref_dir, ['cartography-office', 'deep-archive'])
        assert 'cartography-office' not in find_unresolved('locations', ref_dir)

    def test_find_unresolved_ignores_placeholders(self, project_dir):
        from storyforge.hone import find_unresolved
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scene-briefs.csv', 'knowledge_in', ['(none)', 'n/a'])
        assert find_unresolved('knowledge', ref_dir) == []


class TestReconcileByDeltas:
    """F-026: a registry rebuild re-emitted the whole registry plus an UPDATE
    per scene, so output grew with the book and Gatsby's knowledge reconcile
    was cut off. Only unresolved references go to the model, in batches."""

    def test_reconciled_project_makes_no_call(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        # The fixture names a few people and places its registries lack
        with open(os.path.join(ref_dir, 'characters.csv'), 'a') as f:
            f.write('council-members|Council Members||minor|\n')
        with open(os.path.join(ref_dir, 'locations.csv'), 'a') as f:
            f.write('council-chamber|Council Chamber|\neastern-ridge|Eastern Ridge|\n')
        calls = _mock_api(monkeypatch, [])
        for domain in ('characters', 'locations', 'values', 'mice-threads',
                       'knowledge', 'physical-states'):
            result = reconcile_domain(domain, ref_dir, 'test-model', str(tmp_path))
            assert result['calls'] == 0, domain
        assert calls == []

    def test_only_unresolved_references_are_sent(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain, find_unresolved
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location', ['the office', 'West Egg'])
        calls = _mock_api(monkeypatch, ['1 | NEW | west-egg | West Egg\n'])

        reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))

        refs = calls[0].split('## Unresolved References')[1].split('## Instructions')[0]
        assert '1. West Egg' in refs and 'the office' not in refs
        assert find_unresolved('locations', ref_dir) == []
        assert _column(ref_dir, 'scenes.csv', 'location')['act1-sc02'] == 'west-egg'

    def test_existing_entry_gains_alias(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        from storyforge.enrich import load_alias_map
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location', ['Cartography HQ'])
        _mock_api(monkeypatch, ['1 | cartography-office\n'])

        reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))

        aliases = load_alias_map(os.path.join(ref_dir, 'locations.csv'))
        assert aliases['cartography hq'] == 'cartography-office'
        assert _column(ref_dir, 'scenes.csv', 'location')['act1-sc01'] == 'cartography-office'

    def test_composite_reference_maps_to_each_place(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location',
                    ['the office to the archive', 'Plaza Hotel'])
        _mock_api(monkeypatch, ['1 | cartography-office;deep-archive\n'
                                '2 | NEW | plaza-hotel | Plaza Hotel\n'])

        reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))

        locs = _column(ref_dir, 'scenes.csv', 'location')
        assert locs['act1-sc01'] == 'cartography-office;deep-archive'
        assert locs['act1-sc02'] == 'plaza-hotel'
        # A composite mapping is never recorded as one entry's alias
        with open(os.path.join(ref_dir, 'locations.csv')) as f:
            assert 'the office to the archive' not in f.read()

    def test_batches_apply_in_order(self, project_dir, monkeypatch, tmp_path):
        """Batch 2's prompt lists the entry batch 1 declared, and may map to it."""
        import storyforge.hone as hone
        ref_dir = os.path.join(project_dir, 'reference')
        monkeypatch.setattr(hone, '_BATCH_SIZE', 1)
        _set_column(ref_dir, 'scenes.csv', 'location', ['Plaza Hotel', 'the Plaza'])
        calls = _mock_api(monkeypatch, ['1 | NEW | plaza-hotel | Plaza Hotel\n',
                                        '1 | plaza-hotel\n'])

        result = hone.reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))

        assert len(calls) == 2 and result['calls'] == 2
        assert '- plaza-hotel — Plaza Hotel' in calls[1]
        locs = _column(ref_dir, 'scenes.csv', 'location')
        assert locs['act1-sc01'] == locs['act1-sc02'] == 'plaza-hotel'

    def test_skip_is_removed_so_a_rerun_makes_no_call(self, project_dir, monkeypatch, tmp_path, capsys):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location',
                    ['the office;somewhere unspecified', 'various rooms'])
        calls = _mock_api(monkeypatch, ['1 | SKIP\n2 | SKIP (noise)\n'])

        result = reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))

        out = capsys.readouterr().out
        assert 'removed 2 reference(s) that are not a place: somewhere unspecified' in out
        assert 'still unresolved' not in out
        assert result['unresolved'] == 0
        locs = _column(ref_dir, 'scenes.csv', 'location')
        assert locs['act1-sc01'] == 'cartography-office' and locs['act1-sc02'] == ''
        reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))
        assert len(calls) == 1

    def test_unknown_id_is_ignored_and_reported(self, project_dir, monkeypatch, tmp_path, capsys):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location', ['West Egg'])
        calls = _mock_api(monkeypatch, ['1 | not-a-registered-id\n', '1 | west-egg\n'])

        reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))

        # One retry round, which says why it is asking again
        assert len(calls) == 2 and 'Answer again' in calls[1]
        assert 'still unresolved: West Egg' in capsys.readouterr().out

    def test_retry_resolves_an_undeclared_id(self, project_dir, monkeypatch, tmp_path):
        """Gatsby: `5 | the-chauffeur` named an id that was never declared."""
        from storyforge.hone import reconcile_domain, find_unresolved
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location', ['the garage'])
        _mock_api(monkeypatch, ['1 | the-garage\n', '1 | NEW | the-garage | The garage\n'])
        reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))
        assert find_unresolved('locations', ref_dir) == []

    def test_truncated_batch_is_not_applied(self, project_dir, monkeypatch, tmp_path, capsys):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        with open(os.path.join(ref_dir, 'locations.csv')) as f:
            before = f.read()
        _set_column(ref_dir, 'scenes.csv', 'location', ['West Egg', 'East Egg'])
        _mock_api(monkeypatch, ['1 | NEW | west-egg | West Egg\n2 | NEW | east'],
                  stop_reasons={0: 'max_tokens'})

        reconcile_domain('locations', ref_dir, 'test-model', str(tmp_path))

        out = capsys.readouterr().out
        assert 'hit the' in out and 'token limit' in out
        with open(os.path.join(ref_dir, 'locations.csv')) as f:
            assert f.read() == before
        assert _column(ref_dir, 'scenes.csv', 'location')['act1-sc01'] == 'West Egg'

    def test_character_columns_beyond_the_domain_are_kept(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'pov', ['Nick Carraway'])
        _mock_api(monkeypatch, ['1 | NEW | nick-carraway | Nick Carraway | protagonist\n'
                                '2 | NEW | council-members | Council Members | minor\n'])

        reconcile_domain('characters', ref_dir, 'test-model', str(tmp_path))

        with open(os.path.join(ref_dir, 'characters.csv')) as f:
            text = f.read()
        assert 'death_scene' in text.split('\n')[0]
        assert 'nick-carraway|Nick Carraway|protagonist' in text

    def test_dry_run_counts_calls(self, project_dir, capsys):
        from storyforge.cmd_hone import _run_registry_domain
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location', ['West Egg'])
        _run_registry_domain('locations', ref_dir, project_dir, '', 'm', '', True)
        assert '1 unresolved reference(s): 1 mapping call(s)' in capsys.readouterr().out


class TestAliasCollisions:
    """An alias under two entries silently resolves to whichever loads last
    (The Great Gatsby: `power` listed `love` beside a `love` entry)."""

    def _write_registry(self, ref_dir, *rows):
        with open(os.path.join(ref_dir, 'values.csv'), 'w') as f:
            f.write('id|name|aliases\n' + '\n'.join(rows) + '\n')

    def test_detects_alias_shared_by_two_entries(self, project_dir):
        from storyforge.hone import find_alias_collisions
        ref_dir = os.path.join(project_dir, 'reference')
        self._write_registry(ref_dir, 'love|Love|romance', 'power|Power|love;control')
        assert find_alias_collisions('values', ref_dir) == {'love': ['love', 'power']}

    def test_distinct_aliases_have_no_collisions(self, project_dir):
        from storyforge.hone import find_alias_collisions
        ref_dir = os.path.join(project_dir, 'reference')
        self._write_registry(ref_dir, 'love|Love|romance', 'power|Power|control')
        assert find_alias_collisions('values', ref_dir) == {}

    def test_alias_stays_with_entry_named_by_it(self, project_dir, capsys):
        from storyforge.hone import resolve_alias_collisions, find_alias_collisions
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        self._write_registry(ref_dir, 'power|Power|love;control', 'love|Love|romance')
        resolve_alias_collisions('values', ref_dir)
        assert find_alias_collisions('values', ref_dir) == {}
        assert _read_csv_as_map(os.path.join(ref_dir, 'values.csv'))['power']['aliases'] == 'control'
        assert 'alias "love" kept on love, removed from power' in capsys.readouterr().out

    def test_otherwise_first_entry_keeps_it(self, project_dir):
        from storyforge.hone import resolve_alias_collisions
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        self._write_registry(ref_dir, 'love|Love|desire', 'lust|Lust|desire;want')
        resolve_alias_collisions('values', ref_dir)
        reg = _read_csv_as_map(os.path.join(ref_dir, 'values.csv'))
        assert reg['love']['aliases'] == 'desire' and reg['lust']['aliases'] == 'want'

    def test_reconcile_resolves_collisions_without_a_call(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain, find_alias_collisions
        ref_dir = os.path.join(project_dir, 'reference')
        self._write_registry(ref_dir, 'truth|Truth|honesty', 'safety|Safety|honesty',
                             'justice|Justice|', 'life|Life|')
        calls = _mock_api(monkeypatch, [])
        reconcile_domain('values', ref_dir, 'test-model', str(tmp_path))
        assert calls == []
        assert find_alias_collisions('values', ref_dir) == {}


class TestPhysicalStateCharacters:
    """Physical states named their character by display name ("Daisy
    Buchanan") instead of the characters.csv id."""

    def test_write_registry_stores_character_ids(self, project_dir):
        from storyforge.hone import write_registry
        import csv as _csv
        ref_dir = os.path.join(project_dir, 'reference')
        with open(os.path.join(ref_dir, 'characters.csv'), 'w') as f:
            f.write('id|name|role|aliases\ndaisy-buchanan|Daisy Buchanan|supporting|Daisy\n')
        write_registry(ref_dir, 'physical-states', [
            {'id': 'bruised-knuckle-daisy', 'character': 'Daisy Buchanan',
             'description': 'bruised knuckle', 'category': 'injury',
             'acquired': 'act1-sc01', 'resolves': 'never', 'action_gating': 'false'},
            {'id': 'has-medal', 'character': 'Daisy', 'description': 'medal',
             'category': 'equipment', 'acquired': 'act1-sc01', 'resolves': 'never',
             'action_gating': 'false'},
        ])
        with open(os.path.join(ref_dir, 'physical-states.csv')) as f:
            chars = [r['character'] for r in _csv.DictReader(f, delimiter='|')]
        assert chars == ['daisy-buchanan', 'daisy-buchanan']

    def test_prompt_includes_character_registry(self, project_dir):
        from storyforge.hone import build_mapping_prompt
        ref_dir = os.path.join(project_dir, 'reference')
        batch = [{'key': 'bruised', 'text': 'bruised', 'type': '', 'scenes': []}]
        prompt = build_mapping_prompt('physical-states', ref_dir, batch)
        assert '## Character Registry' in prompt
        assert '- dorren-hayle — Dorren Hayle' in prompt
        assert "character's id from the Character Registry" in prompt

    def test_new_state_gets_derived_columns(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scene-briefs.csv', 'physical_state_in',
                    {'act2-sc03': 'Dorren has a cut hand'})
        _set_column(ref_dir, 'scene-briefs.csv', 'physical_state_out',
                    {'act1-sc02': 'Dorren has a cut hand'})
        _mock_api(monkeypatch, ['1 | NEW | cut-hand-dorren | Dorren Hayle | '
                                'shallow cut across right palm | injury | false\n'])

        reconcile_domain('physical-states', ref_dir, 'test-model', str(tmp_path))

        row = _read_csv_as_map(os.path.join(ref_dir, 'physical-states.csv'))['cut-hand-dorren']
        assert row['character'] == 'dorren-hayle'
        assert row['acquired'] == 'act1-sc02'
        assert row['resolves'] == 'never'
        assert row['action_gating'] == 'false'
        assert _column(ref_dir, 'scene-briefs.csv', 'physical_state_in')['act2-sc03'] == 'cut-hand-dorren'


class TestLocationPrompt:
    """The locations registry holds individual places, never routes (Gatsby's
    first pass invented east-egg-to-nyc-route)."""

    def test_prompt_forbids_route_entries(self, project_dir):
        from storyforge.hone import build_mapping_prompt
        batch = [{'key': 'x', 'text': 'x', 'type': '', 'scenes': ['act1-sc01']}]
        prompt = build_mapping_prompt('locations', os.path.join(project_dir, 'reference'), batch)
        assert 'Never make an entry for a route, journey or transition' in prompt
        assert '1. x  [scenes: act1-sc01]' in prompt
        assert '- cartography-office — Pressure Cartography Office' in prompt

    def test_place_list_splits_into_references(self, project_dir):
        from storyforge.hone import find_unresolved
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'location', ['East Egg;Valley of Ashes'])
        assert find_unresolved('locations', ref_dir) == ['East Egg', 'Valley of Ashes']


class TestKnowledgeIdsAfterReconcile:
    """knowledge_in/out are registry-backed id lists. On The Great Gatsby the
    knowledge reconcile response ran past its token limit mid-registry, so no
    UPDATE lines arrived and the briefs kept raw sentences beside ids (F-022)."""

    def _set_briefs(self, ref_dir, knowledge, physical=None):
        _set_column(ref_dir, 'scene-briefs.csv', 'knowledge_in',
                    {k: v[0] for k, v in knowledge.items()})
        _set_column(ref_dir, 'scene-briefs.csv', 'knowledge_out',
                    {k: v[1] for k, v in knowledge.items()})
        if physical is not None:
            _set_column(ref_dir, 'scene-briefs.csv', 'physical_state_in',
                        {k: v[0] for k, v in physical.items()})
            _set_column(ref_dir, 'scene-briefs.csv', 'physical_state_out',
                        {k: v[1] for k, v in physical.items()})

    def _entries(self, ref_dir, cols=('knowledge_in', 'knowledge_out')):
        from storyforge.elaborate import _read_csv
        out = []
        for row in _read_csv(os.path.join(ref_dir, 'scene-briefs.csv')):
            for col in cols:
                out += [e for e in (row.get(col) or '').split(';') if e.strip()]
        return out

    def _ids(self, ref_dir):
        from storyforge.elaborate import _read_csv
        return {r['id'] for r in _read_csv(os.path.join(ref_dir, 'knowledge.csv'))}

    def test_reconcile_maps_sentences_to_ids(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_briefs(ref_dir, {
            'act1-sc01': ('', 'A village vanished from the maps'),
            'act1-sc02': ('A village vanished from the maps',
                          'A village vanished from the maps;'
                          'Kael was the one who erased the archive;'
                          'map-anomaly-exists'),
        })
        # Numbered in scene order: 1 = the village sentence, 2 = Kael's
        calls = _mock_api(monkeypatch, [
            '1 | village-vanished\n'
            '2 | NEW | kael-erased-archive | Kael erased the archive | identity\n'])

        reconcile_domain('knowledge', ref_dir, 'test-model', str(tmp_path))

        assert len(calls) == 1
        ids = self._ids(ref_dir)
        entries = self._entries(ref_dir)
        assert entries and all(e in ids for e in entries), entries
        k = _read_csv_as_map(os.path.join(ref_dir, 'knowledge.csv'))
        assert k['kael-erased-archive']['origin'] == 'act1-sc02'
        assert k['kael-erased-archive']['category'] == 'identity'
        # Sentences are not kept as aliases
        assert k['village-vanished']['aliases'] == 'missing village;village disappeared'

    def test_new_fact_only_in_knowledge_in_is_backstory(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_briefs(ref_dir, {'act1-sc01': ('Dorren trained at the academy', '')})
        _mock_api(monkeypatch, ['1 | NEW | dorren-academy-trained | '
                                'Dorren trained at the academy | identity\n'])
        reconcile_domain('knowledge', ref_dir, 'test-model', str(tmp_path))
        k = _read_csv_as_map(os.path.join(ref_dir, 'knowledge.csv'))
        assert k['dorren-academy-trained']['origin'] == 'backstory'

    def test_mapping_prompt_numbers_entries_and_lists_registry(self, project_dir):
        from storyforge.hone import build_mapping_prompt
        from storyforge.schema import MAX_FACT_NAME_WORDS
        ref_dir = os.path.join(project_dir, 'reference')
        batch = [{'key': 'the maps are wrong', 'text': 'the maps are wrong',
                  'type': '', 'scenes': []}]
        prompt = build_mapping_prompt('knowledge', ref_dir, batch)
        assert '- map-anomaly-exists — A map anomaly exists' in prompt
        assert '1. the maps are wrong' in prompt
        assert f'at most {MAX_FACT_NAME_WORDS} words' in prompt

    def test_placeholders_never_stored(self, project_dir):
        """`(empty)` is how an empty field used to be rendered in prompts; a
        model echoing it (or `none`) must not create a fact or a state."""
        from storyforge.hone import apply_registry_normalization
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_briefs(
            ref_dir,
            {'act1-sc01': ('none', 'map-anomaly-exists;(none)'),
             'act1-sc02': ('(empty)', 'village-vanished;none')},
            physical={'act1-sc01': ('(none)', 'n/a'), 'act1-sc02': ('none', '')})
        apply_registry_normalization('knowledge', ref_dir)
        apply_registry_normalization('physical-states', ref_dir)
        entries = self._entries(ref_dir, ('knowledge_in', 'knowledge_out',
                                          'physical_state_in', 'physical_state_out'))
        from storyforge.enrich import is_placeholder
        assert not [e for e in entries if is_placeholder(e)], entries
        assert 'map-anomaly-exists' in entries and 'village-vanished' in entries


class TestParseMappingResponse:
    def test_line_forms(self):
        from storyforge.hone import parse_mapping_response
        mapping, new_rows, skipped = parse_mapping_response(
            'characters',
            '1 | tom\n'
            '2. | tom;daisy\n'
            '- 3 | NEW | nick | Nick Carraway | protagonist\n'
            '4 | nick\n'
            '5 | SKIP\n'
            '6 | stranger\n'
            '9 | tom\n'
            'commentary\n',
            batch_size=6, known={'tom', 'daisy'})
        assert mapping == {1: ['tom'], 2: ['tom', 'daisy'], 3: ['nick'], 4: ['nick']}
        assert new_rows == [{'id': 'nick', 'name': 'Nick Carraway', 'role': 'protagonist'}]
        assert skipped == {5}

    def test_new_with_registered_id_maps_to_it(self):
        from storyforge.hone import parse_mapping_response
        mapping, new_rows, _ = parse_mapping_response(
            'locations', '1 | NEW | West-Egg | West Egg\n', 1, {'west-egg'})
        assert mapping == {1: ['west-egg']} and new_rows == []


class TestMiceOperations:
    """MICE opens/closes used to be normalized by per-scene UPDATEs in the
    full rebuild. Now only anomalous threads are sent, one line each."""

    def _set_threads(self, ref_dir, threads):
        _set_column(ref_dir, 'scene-intent.csv', 'mice_threads', threads)

    def test_fixture_has_no_anomalies(self, project_dir):
        from storyforge.hone import find_mice_anomalies
        assert find_mice_anomalies(os.path.join(project_dir, 'reference')) == []

    def test_detects_double_close_and_close_before_open(self, project_dir):
        from storyforge.hone import find_mice_anomalies
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_threads(ref_dir, {
            'act1-sc01': '+map-anomaly;-archive-erasure',
            'act1-sc02': '-map-anomaly',
            'new-x1': '-map-anomaly;+archive-erasure',
        })
        assert sorted(find_mice_anomalies(ref_dir)) == ['archive-erasure', 'map-anomaly']

    def test_thread_rewritten_from_decision(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain, find_mice_anomalies
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_threads(ref_dir, {
            'act1-sc01': '+inquiry:map-anomaly',
            'act1-sc02': '-inquiry:map-anomaly',
            'new-x1': '+inquiry:map-anomaly',
            'act2-sc03': '-inquiry:map-anomaly;+milieu:uncharted-reaches',
        })
        calls = _mock_api(monkeypatch, ['map-anomaly | act1-sc01 | act2-sc03\n'])

        result = reconcile_domain('mice-threads', ref_dir, 'test-model', str(tmp_path))

        assert len(calls) == 1 and result['calls'] == 1
        assert '### map-anomaly — Map anomaly (inquiry)' in calls[0]
        assert 'uncharted-reaches' not in calls[0]
        threads = _column(ref_dir, 'scene-intent.csv', 'mice_threads')
        assert threads['act1-sc01'] == '+map-anomaly'
        assert threads['act1-sc02'] == 'map-anomaly'
        assert threads['new-x1'] == 'map-anomaly'
        assert threads['act2-sc03'] == '-map-anomaly;+uncharted-reaches'
        assert find_mice_anomalies(ref_dir) == []

    def test_unclosed_and_invalid_scenes(self, project_dir):
        from storyforge.hone import parse_mice_operations_response
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_threads(ref_dir, {
            'act1-sc01': '+map-anomaly',
            'act1-sc02': '+map-anomaly',
            'new-x1': '+archive-erasure',
            'act2-sc01': '+archive-erasure',
        })
        decisions = parse_mice_operations_response(
            'map-anomaly | act1-sc01 | UNCLOSED\n'
            'archive-erasure | act2-sc01 | new-x1\n'   # close before open
            'other | act1-sc01 | UNCLOSED\n',
            ref_dir, ['map-anomaly', 'archive-erasure'])
        assert decisions == {'map-anomaly': ('act1-sc01', '')}

    def test_unresolved_thread_name_keeps_prefix(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        self._set_threads(ref_dir, {
            'act1-sc01': '+inquiry:what-is-wrong-with-the-maps',
            'act2-sc03': '-inquiry:map-anomaly',
        })
        _mock_api(monkeypatch, ['1 | map-anomaly\n'])
        reconcile_domain('mice-threads', ref_dir, 'test-model', str(tmp_path))
        threads = _column(ref_dir, 'scene-intent.csv', 'mice_threads')
        assert threads['act1-sc01'] == '+map-anomaly'
        assert threads['act2-sc03'] == '-map-anomaly'


class TestTruncationIsNeverSilent:
    def test_is_truncated(self):
        from storyforge.api import is_truncated
        assert is_truncated({'stop_reason': 'max_tokens'})
        assert not is_truncated({'stop_reason': 'end_turn'})
        assert not is_truncated(None)


class TestGatsbyFieldShapes:
    """Shapes on The Great Gatsby that the delta pass would otherwise send to
    the model as references: comma-joined MICE entries, and explained
    placeholders in physical states."""

    def test_explained_placeholders(self):
        from storyforge.enrich import is_placeholder
        for entry in ('[none for nick-carraway]',
                      '[none — Nick carries no tracked physical states into this scene]',
                      'ewing-klipspringer: (none prior)', '(none prior)'):
            assert is_placeholder(entry), entry
        for entry in ('nonesuch-ring', 'none-of-the-above-badge', 'gatsby-has-medal',
                      'Daisy: bruised knuckle'):
            assert not is_placeholder(entry), entry

    def test_comma_joined_mice_entries_are_split(self, project_dir):
        from storyforge.hone import find_unresolved, apply_registry_normalization
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scene-intent.csv', 'mice_threads',
                    {'act1-sc01': '+map-anomaly,+archive-erasure,+new-thread'})
        assert find_unresolved('mice-threads', ref_dir) == ['new-thread']
        apply_registry_normalization('mice-threads', ref_dir)
        assert _column(ref_dir, 'scene-intent.csv', 'mice_threads')['act1-sc01'] == \
            '+map-anomaly;+archive-erasure;+new-thread'

    def test_none_sentences_are_facts(self):
        from storyforge.enrich import is_placeholder
        for entry in ('None of the guests have met Gatsby',
                      "None of Gatsby's money is legitimate",
                      'Nick: none of this is real'):
            assert not is_placeholder(entry), entry

    def test_comma_inside_a_free_text_thread_name_stays(self):
        from storyforge.enrich import split_mice_entries
        assert split_mice_entries('+inquiry:what does Gatsby want, really;-a') == \
            ['+inquiry:what does Gatsby want, really', '-a']
        assert split_mice_entries('a,+b,-c, inquiry:d') == ['a', '+b', '-c', ' inquiry:d']


class TestReviewFixes:
    """Fresh-context review of #322."""

    def test_pov_never_gets_a_composite(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'pov', ['the Merrins'])
        _set_column(ref_dir, 'scene-intent.csv', 'characters', {'act1-sc01': 'the Merrins'})
        calls = _mock_api(monkeypatch, ['1 | tessa-merrin;dorren-hayle\n2 | SKIP\n'])
        reconcile_domain('characters', ref_dir, 'test-model', str(tmp_path))
        assert len(calls) == 1  # answered, so not retried
        assert _column(ref_dir, 'scenes.csv', 'pov')['act1-sc01'] == 'the Merrins'
        assert _column(ref_dir, 'scene-intent.csv', 'characters')['act1-sc01'] == \
            'tessa-merrin;dorren-hayle'

    def test_new_ids_are_slugged_or_rejected(self):
        from storyforge.hone import parse_mapping_response
        mapping, new_rows, _ = parse_mapping_response(
            'characters',
            '1 | NEW | Myrtle Wilson | Myrtle Wilson | supporting\n'
            '2 | NEW | east-egg;west-egg | East Egg | minor\n'
            '3 | NEW | Tommy | Tom | minor\n',
            3, {'tom': 'tom-buchanan', 'tommy': 'tom-buchanan', 'tom-buchanan': 'tom-buchanan'})
        assert [r['id'] for r in new_rows] == ['myrtle-wilson']
        assert mapping == {1: ['myrtle-wilson'], 3: ['tom-buchanan']}

    def test_mapping_line_may_name_an_alias(self):
        from storyforge.hone import parse_mapping_response
        mapping, _, _ = parse_mapping_response(
            'characters', '1 | Gatsby\n', 1, {'gatsby': 'jay-gatsby', 'jay-gatsby': 'jay-gatsby'})
        assert mapping == {1: ['jay-gatsby']}

    def test_origin_recomputed_across_batches(self, project_dir, monkeypatch, tmp_path):
        import storyforge.hone as hone
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        monkeypatch.setattr(hone, '_BATCH_SIZE', 1)
        # Scene order: act1-sc01's knowledge_in first, then act1-sc02's out
        _set_column(ref_dir, 'scene-briefs.csv', 'knowledge_in',
                    {'act1-sc01': 'Pell is a spy'})
        _set_column(ref_dir, 'scene-briefs.csv', 'knowledge_out',
                    {'act1-sc02': 'Pell spies for the council'})
        _mock_api(monkeypatch, ['1 | NEW | pell-is-a-spy | Pell is a spy | identity\n',
                                '1 | pell-is-a-spy\n'])
        hone.reconcile_domain('knowledge', ref_dir, 'test-model', str(tmp_path))
        k = _read_csv_as_map(os.path.join(ref_dir, 'knowledge.csv'))
        assert k['pell-is-a-spy']['origin'] == 'act1-sc02'

    def test_skip_never_blanks_pov(self, project_dir, monkeypatch, tmp_path):
        from storyforge.hone import reconcile_domain
        ref_dir = os.path.join(project_dir, 'reference')
        _set_column(ref_dir, 'scenes.csv', 'pov', ['the narrator'])
        _set_column(ref_dir, 'scene-intent.csv', 'characters', {'act1-sc01': 'the narrator'})
        _mock_api(monkeypatch, ['1 | SKIP\n2 | SKIP\n'])
        reconcile_domain('characters', ref_dir, 'test-model', str(tmp_path))
        assert _column(ref_dir, 'scenes.csv', 'pov')['act1-sc01'] == 'the narrator'
        assert _column(ref_dir, 'scene-intent.csv', 'characters')['act1-sc01'] == ''

    def test_new_id_findable_by_its_spelling(self):
        from storyforge.hone import parse_mapping_response
        mapping, new_rows, _ = parse_mapping_response(
            'locations', "1 | NEW | Daisy's Car | Daisy's car\n2 | Daisy's Car\n3 | daisy-s-car\n",
            3, set())
        assert [r['id'] for r in new_rows] == ['daisy-s-car']
        assert mapping == {1: ['daisy-s-car'], 2: ['daisy-s-car'], 3: ['daisy-s-car']}

    def test_lowercase_skip_is_an_id(self):
        from storyforge.hone import parse_mapping_response
        mapping, _, skipped = parse_mapping_response(
            'characters', '1 | skip\n', 1, {'skip': 'skip'})
        assert mapping == {1: ['skip']} and skipped == set()
