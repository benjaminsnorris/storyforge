"""Tests for elaboration pipeline helpers (migrated from test-elaborate.sh)."""

import json
import os
import shutil
import tempfile


class TestGetScene:
    def test_returns_id(self, fixture_dir):
        from storyforge.elaborate import get_scene
        scene = get_scene('act1-sc01', os.path.join(fixture_dir, 'reference'))
        assert scene['id'] == 'act1-sc01'

    def test_returns_pov(self, fixture_dir):
        from storyforge.elaborate import get_scene
        scene = get_scene('act1-sc01', os.path.join(fixture_dir, 'reference'))
        assert scene['pov'] == 'Dorren Hayle'

    def test_returns_function(self, fixture_dir):
        from storyforge.elaborate import get_scene
        scene = get_scene('act1-sc01', os.path.join(fixture_dir, 'reference'))
        assert 'function' in scene

    def test_returns_goal(self, fixture_dir):
        from storyforge.elaborate import get_scene
        scene = get_scene('act1-sc01', os.path.join(fixture_dir, 'reference'))
        assert 'goal' in scene

    def test_returns_value_shift(self, fixture_dir):
        from storyforge.elaborate import get_scene
        scene = get_scene('act1-sc01', os.path.join(fixture_dir, 'reference'))
        assert scene['value_shift'] == '+/-'

    def test_no_brief_scene(self, fixture_dir):
        from storyforge.elaborate import get_scene
        scene = get_scene('act2-sc01', os.path.join(fixture_dir, 'reference'))
        assert scene['pov'] == 'Tessa Merrin'
        assert scene['goal'] == ''

    def test_nonexistent(self, fixture_dir):
        from storyforge.elaborate import get_scene
        assert get_scene('nonexistent', os.path.join(fixture_dir, 'reference')) is None


class TestGetScenes:
    def test_column_selection(self, fixture_dir):
        from storyforge.elaborate import get_scenes
        scenes = get_scenes(os.path.join(fixture_dir, 'reference'),
                           columns=['id', 'pov', 'value_shift'])
        assert any(s['id'] == 'act1-sc01' for s in scenes)
        assert any(s.get('value_shift') == '+/-' for s in scenes)
        assert all('goal' not in s for s in scenes)

    def test_filter_by_pov(self, fixture_dir):
        from storyforge.elaborate import get_scenes
        scenes = get_scenes(os.path.join(fixture_dir, 'reference'),
                           filters={'pov': 'Dorren Hayle'})
        assert len(scenes) == 3

    def test_ordering_by_seq(self, fixture_dir):
        from storyforge.elaborate import get_scenes
        scenes = get_scenes(os.path.join(fixture_dir, 'reference'), columns=['id'])
        ids = [s['id'] for s in scenes]
        assert ids == ['act1-sc01', 'act1-sc02', 'new-x1', 'act2-sc01', 'act2-sc02', 'act2-sc03']


class TestGetColumn:
    def test_pov_column(self, fixture_dir):
        from storyforge.elaborate import get_column
        result = get_column(os.path.join(fixture_dir, 'reference'), 'pov')
        assert result == ['Dorren Hayle', 'Dorren Hayle', 'Kael Maren',
                          'Tessa Merrin', 'Tessa Merrin', 'Dorren Hayle']


class TestUpdateScene:
    def test_update_scenes_csv(self, fixture_dir, tmp_path):
        from storyforge.elaborate import update_scene, get_scene
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        update_scene('act1-sc01', ref, {'status': 'drafted', 'word_count': '2450'})
        scene = get_scene('act1-sc01', ref)
        assert scene['status'] == 'drafted'
        assert scene['word_count'] == '2450'

    def test_update_briefs(self, fixture_dir, tmp_path):
        from storyforge.elaborate import update_scene, get_scene
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        update_scene('act1-sc01', ref, {'goal': 'Survive the audit'})
        scene = get_scene('act1-sc01', ref)
        assert scene['goal'] == 'Survive the audit'

    def test_update_intent(self, fixture_dir, tmp_path):
        from storyforge.elaborate import update_scene, get_scene
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        update_scene('act1-sc01', ref, {'value_shift': '-/+'})
        scene = get_scene('act1-sc01', ref)
        assert scene['value_shift'] == '-/+'


class TestAddScenes:
    def test_creates_rows(self, fixture_dir, tmp_path):
        from storyforge.elaborate import add_scenes, get_scene
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        add_scenes(ref, [
            {'id': 'new-scene', 'seq': '7', 'title': 'The New Scene',
             'status': 'spine', 'function': 'Test scene'},
        ])
        scene = get_scene('new-scene', ref)
        assert scene['title'] == 'The New Scene'
        assert scene['function'] == 'Test scene'
        assert scene['status'] == 'spine'


class TestValidateStructure:
    def test_identity_checks_pass(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        identity = [c for c in report['checks'] if c['category'] == 'identity']
        assert all(c['passed'] for c in identity)

    def test_completeness_checks_pass(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        completeness = [c for c in report['checks'] if c['category'] == 'completeness']
        assert all(c['passed'] for c in completeness)

    def test_detects_orphaned_intent(self, fixture_dir, tmp_path):
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        with open(os.path.join(ref, 'scene-intent.csv'), 'a') as f:
            f.write('orphan-scene|Orphan function|action|calm to panic|truth|+/-|action|thread-a|Char A|Char A|\n')

        report = validate_structure(ref)
        identity = [c for c in report['checks'] if c['category'] == 'identity' and not c['passed']]
        assert len(identity) > 0

    def test_mice_nesting(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        thread_checks = [c for c in report['checks'] if c['category'] == 'threads']
        nesting = [c for c in thread_checks if c['check'] == 'mice-nesting']
        assert any(c['passed'] for c in nesting)

    def test_cross_type_parallel_pass(self, tmp_path):
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 6):
                f.write(f's0{i}|{i}|Scene {i}|1|Alice|Room|{i}|morning|1 hour|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|a|Alice|Alice|+character:alice-arc\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|a|Alice|Alice|+inquiry:who-killed;+milieu:castle\n')
            f.write('s03|test|action|flat|truth|+/-|revelation|a|Alice|Alice|-milieu:castle\n')
            f.write('s04|test|action|flat|truth|+/-|revelation|a|Alice|Alice|-inquiry:who-killed\n')
            f.write('s05|test|action|flat|truth|+/-|revelation|a|Alice|Alice|-character:alice-arc\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            for i in range(1, 6):
                f.write(f's0{i}|g|c|o|cr|d|k|k|a|d|e|m||false\n')

        report = validate_structure(ref)
        thread_checks = [c for c in report['checks'] if c['category'] == 'threads']
        nesting = [c for c in thread_checks if c['check'] == 'mice-nesting']
        assert any(c['passed'] for c in nesting)
        assert not any('nesting violation' in c.get('message', '') for c in thread_checks)

    def test_same_type_nesting_violation(self, tmp_path):
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 4):
                f.write(f's0{i}|{i}|Scene {i}|1|Alice|Room|{i}|morning|1 hour|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|a|Alice|Alice|+inquiry:outer-question\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|a|Alice|Alice|+inquiry:inner-question\n')
            f.write('s03|test|action|flat|truth|+/-|revelation|a|Alice|Alice|-inquiry:outer-question\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            for i in range(1, 4):
                f.write(f's0{i}|g|c|o|cr|d|k|k|a|d|e|m||false\n')

        report = validate_structure(ref)
        thread_checks = [c for c in report['checks'] if c['category'] == 'threads']
        messages = ' '.join(c.get('message', '') for c in thread_checks)
        assert 'nesting violation' in messages
        assert 'inquiry:inner-question' in messages

    def test_timeline_order(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
        assert any(c['check'] == 'timeline-order' and c['passed'] for c in timeline_checks)

    def test_backwards_timeline_detected(self, fixture_dir, tmp_path):
        from storyforge.elaborate import validate_structure, update_scene
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        update_scene('act1-sc02', ref, {'timeline_day': '5'})

        report = validate_structure(ref)
        timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
        failed = [c for c in timeline_checks if not c['passed']]
        assert len(failed) > 0

    def test_crosscut_advisory(self, tmp_path):
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|Scene One|1|Emmett|Town|13|morning|1 hour|action|briefed|1000|2000\n')
            f.write('s02|2|Scene Two|1|Emmett|Town|14|morning|1 hour|action|briefed|1000|2000\n')
            f.write('s03|3|Scene Three|1|Lena|Station|12|morning|1 hour|action|briefed|1000|2000\n')
            f.write('s04|4|Scene Four|1|Emmett|Town|15|morning|1 hour|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads\n')
            for sid, char in [('s01', 'Emmett'), ('s02', 'Emmett'), ('s03', 'Lena'), ('s04', 'Emmett')]:
                f.write(f'{sid}|test|action|flat|truth|+/-|revelation|a|{char}|{char}|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            for i in range(1, 5):
                f.write(f's0{i}|g|c|o|cr|d|k|k|a|d|e|m||false\n')

        report = validate_structure(ref)
        timeline_checks = [c for c in report['checks'] if c['category'] == 'timeline']
        severities = [c.get('severity', 'blocking') for c in timeline_checks]
        messages = ' '.join(c.get('message', '') for c in timeline_checks)
        assert 'advisory' in severities
        assert 'crosscut' in messages
        assert 'blocking' not in severities

    def test_knowledge_flow(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        knowledge_checks = [c for c in report['checks'] if c['category'] == 'knowledge']
        assert any(c['passed'] for c in knowledge_checks)

    def test_pacing(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        pacing_checks = [c for c in report['checks'] if c['category'] == 'pacing']
        assert all(c['passed'] for c in pacing_checks)

    def test_flat_polarity_detected(self, fixture_dir, tmp_path):
        from storyforge.elaborate import validate_structure, update_scene
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        for sid in ['act1-sc01', 'act1-sc02', 'new-x1', 'act2-sc01']:
            update_scene(sid, ref, {'value_shift': '+/+'})

        report = validate_structure(ref)
        pacing = [c for c in report['checks'] if c['category'] == 'pacing']
        failed = [c for c in pacing if not c['passed']]
        assert len(failed) > 0


class TestComputeDraftingWaves:
    def test_waves(self, fixture_dir):
        from storyforge.elaborate import compute_drafting_waves
        waves = compute_drafting_waves(os.path.join(fixture_dir, 'reference'))
        all_ids = [sid for wave in waves for sid in wave]
        assert 'act1-sc01' in all_ids
        assert 'act2-sc03' in all_ids
        assert len(waves) > 0

    def test_wave1_no_deps(self, fixture_dir):
        from storyforge.elaborate import compute_drafting_waves
        waves = compute_drafting_waves(os.path.join(fixture_dir, 'reference'))
        assert 'act1-sc01' in waves[0]


class TestScoreStructure:
    def test_fully_briefed_scores_high(self, fixture_dir):
        from storyforge.elaborate import score_structure
        scores = score_structure(os.path.join(fixture_dir, 'reference'))
        act1 = [s for s in scores if s['scene_id'] == 'act1-sc01']
        assert act1[0]['score'] == 5

    def test_unbriefed_scores_zero(self, fixture_dir):
        from storyforge.elaborate import score_structure
        scores = score_structure(os.path.join(fixture_dir, 'reference'))
        act2 = [s for s in scores if s['scene_id'] == 'act2-sc01']
        assert act2[0]['score'] == 0
