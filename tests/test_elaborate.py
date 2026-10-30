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

    def test_detects_duplicate_seq(self, fixture_dir, tmp_path):
        """Thornwall shipped two scenes at seq 58; nothing reported it."""
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)
        path = os.path.join(ref, 'scenes.csv')
        with open(path) as f:
            lines = f.read().splitlines()
        header = lines[0].split('|')
        seq_i = header.index('seq')
        first, second = lines[1].split('|'), lines[2].split('|')
        second[seq_i] = first[seq_i]
        lines[2] = '|'.join(second)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

        report = validate_structure(ref)
        dup = [c for c in report['checks'] if c['check'] == 'duplicate-seq']
        assert len(dup) == 1 and not dup[0]['passed']
        assert first[0] in dup[0]['message'] and second[0] in dup[0]['message']
        assert not report['passed']

    def test_mice_nesting(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        thread_checks = [c for c in report['checks'] if c['category'] == 'threads']
        ops = [c for c in thread_checks if c['check'] == 'mice-ops']
        assert any(c['passed'] for c in ops)

    def test_cross_type_parallel_pass(self, tmp_path):
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|act|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
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
        assert any(c['check'] == 'mice-ops' and c['passed'] for c in thread_checks)
        assert not any(c['check'] == 'mice-interleaving' for c in thread_checks)

    def test_same_type_interleaving_is_advisory(self, tmp_path):
        # Nesting is guidance, not a rule (author's decision): literary
        # novels interleave threads, so this is described, never blocking.
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|act|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
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
        interleaving = [c for c in thread_checks if c['check'] == 'mice-interleaving']
        assert len(interleaving) == 1
        assert interleaving[0]['severity'] == 'advisory'
        assert 'inquiry:inner-question' in interleaving[0]['message']
        assert not [c for c in report['failures'] if c['category'] == 'threads'
                    and c.get('severity', 'blocking') != 'advisory']

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
            f.write('id|seq|title|act|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
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
        assert 'crosscut' in messages.lower()
        assert 'blocking' not in severities

    def test_advisory_only_failures_do_not_fail_passed(self, tmp_path):
        """Regression: validate_structure returns passed=True when the ONLY
        failures are advisory.

        Documents the semantics introduced in commit 87b8080: advisory
        findings (e.g., crosscut pacing on a single timeline_day) are
        reported as FYI in `failures` but do not flip `passed` to False.
        Blocking failures still do.
        """
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        # Same crosscut scenario as above — produces an advisory timeline check.
        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|act|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
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
        failures = report['failures']
        # There must be at least one advisory failure (the crosscut).
        assert any(f.get('severity') == 'advisory' for f in failures), (
            'fixture expected to produce at least one advisory failure'
        )
        # And NO blocking failures.
        assert not any(
            f.get('severity', 'blocking') == 'blocking' for f in failures
        ), 'fixture expected to produce ONLY advisory failures'
        # Therefore passed must be True — advisory findings are FYI only.
        assert report['passed'] is True, (
            'validate_structure must return passed=True when the only '
            'failures are advisory (FYI signals do not gate the pipeline)'
        )

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


class TestTimelineOrderGroupsSteppingBack:
    """F-122: on a multi-plot novel (Middlemarch) validate gave one
    timeline-order note per scene, so two crosscuts alone gave 44 lines and
    buried every other finding. A contiguous run of scenes set before the
    story's present is one finding naming its first and last scene and the
    count; every scene stays listed in the finding's ``scenes``."""

    @staticmethod
    def _scenes(rows):
        return {sid: {'seq': str(i + 1), 'timeline_day': day, 'pov': pov,
                      'time_mode': mode}
                for i, (sid, day, pov, mode) in enumerate(rows)}

    @staticmethod
    def _failures(scenes):
        from storyforge.elaborate import _validate_timeline
        checks = []
        _validate_timeline(scenes, checks)
        return [c for c in checks if c['check'] == 'timeline-order' and not c['passed']]

    def test_a_crosscut_run_is_one_finding(self):
        scenes = self._scenes([
            ('rome', '30', 'dorothea', ''),
            ('fred-debt', '10', 'fred', ''),
            ('horse-fair', '11', 'fred', ''),
            ('confesses', '12', 'fred', ''),
            ('rome-again', '31', 'dorothea', ''),
        ])
        failures = self._failures(scenes)
        assert len(failures) == 1
        f = failures[0]
        assert f['severity'] == 'advisory'
        assert f['scene_id'] == 'fred-debt'
        assert f['scenes'] == ['fred-debt', 'horse-fair', 'confesses']
        assert f['message'].startswith('Crosscut: 3 scenes, fred-debt (day 10) to confesses (day 12),')
        assert "story's present (day 30, reached in rome)" in f['message']

    def test_a_single_scene_keeps_its_one_line_message(self):
        scenes = self._scenes([
            ('rome', '30', 'dorothea', ''),
            ('childhood', '5', 'dorothea', ''),
            ('rome-again', '31', 'dorothea', ''),
        ])
        failures = self._failures(scenes)
        assert [f['message'] for f in failures] == [
            "Flashback: childhood (day 5) is set before the story's present "
            "(day 30, reached in rome)"]
        assert failures[0]['scene_id'] == 'childhood'
        assert failures[0]['scenes'] == ['childhood']

    def test_runs_split_where_the_present_returns(self):
        scenes = self._scenes([
            ('a', '30', 'x', ''), ('b', '10', 'y', ''), ('c', '11', 'y', ''),
            ('d', '30', 'x', ''), ('e', '12', 'y', ''), ('f', '13', 'y', ''),
        ])
        failures = self._failures(scenes)
        assert [f['scenes'] for f in failures] == [['b', 'c'], ['e', 'f']]
        assert 'reached in a' in failures[0]['message']
        assert 'reached in d' in failures[1]['message']

    def test_a_mixed_run_counts_its_crosscut_and_flashback_scenes(self):
        scenes = self._scenes([
            ('present', '64', 'lydgate', ''),
            ('vincys', '15', 'fred', ''),
            ('paris', '-1100', 'lydgate', ''),
            ('vote', '52', 'lydgate', ''),
        ])
        [f] = self._failures(scenes)
        assert f['scenes'] == ['vincys', 'paris', 'vote']
        assert f['message'].startswith('Crosscut: 3 scenes, vincys (day 15) to vote (day 52),')
        assert '1 crosscut, 2 flashback' in f['message']
        assert 'reaching back to day -1100' in f['message']

    def test_a_scene_without_a_day_breaks_the_run_and_a_frame_does_not(self):
        scenes = self._scenes([
            ('a', '30', 'x', ''), ('b', '10', 'y', ''), ('frame', '99', 'n', 'frame'),
            ('c', '11', 'y', ''), ('undated', '', 'y', ''), ('d', '12', 'y', ''),
        ])
        failures = self._failures(scenes)
        assert [f['scenes'] for f in failures] == [['b', 'c'], ['d']]

    def test_findings_match_the_flashback_passages(self):
        from storyforge.structural import assess_flashbacks
        scenes = self._scenes([
            ('a', '30', 'x', ''), ('b', '10', 'y', ''), ('frame', '99', 'n', 'frame'),
            ('c', '11', 'x', ''), ('undated', '', 'y', ''), ('d', '12', 'y', ''),
            ('e', '40', 'x', ''), ('f', '39', 'x', ''), ('g', '41', 'y', ''),
        ])
        passages = [p['scenes'] for p in assess_flashbacks(scenes, {})]
        assert [f['scenes'] for f in self._failures(scenes)] == passages
        # Every scene set before the present is still listed: nothing is lost
        listed = [sid for f in self._failures(scenes) for sid in f['scenes']]
        assert listed == ['b', 'c', 'd', 'f']


    def test_reaching_back_is_left_out_when_the_earliest_day_ends_the_run(self):
        first = self._scenes([('p', '30', 'x', ''), ('a', '5', 'y', ''),
                              ('b', '9', 'y', ''), ('c', '12', 'y', '')])
        last = self._scenes([('p', '30', 'x', ''), ('a', '12', 'y', ''),
                             ('b', '9', 'y', ''), ('c', '5', 'y', '')])
        middle = self._scenes([('p', '30', 'x', ''), ('a', '12', 'y', ''),
                               ('b', '5', 'y', ''), ('c', '9', 'y', '')])
        assert 'reaching back' not in self._failures(first)[0]['message']
        assert 'reaching back' not in self._failures(last)[0]['message']
        assert self._failures(middle)[0]['message'].endswith('; reaching back to day 5')

    def test_cut_and_merged_scenes_still_count_in_the_order(self):
        """As the docstring says, unlike assess_flashbacks: a cut scene with a
        later day still moves the present, and so ends a run."""
        scenes = self._scenes([('p', '30', 'x', ''), ('a', '10', 'y', ''),
                               ('gone', '40', 'x', ''), ('b', '11', 'y', '')])
        scenes['gone']['status'] = 'cut'
        failures = self._failures(scenes)
        assert [f['scenes'] for f in failures] == [['a'], ['b']]
        assert 'reached in gone' in failures[1]['message']

    def test_finding_scene_list_names_every_scene_of_a_longer_run(self):
        from storyforge.elaborate import finding_scene_list
        assert finding_scene_list({'scenes': ['a', 'b', 'c']}) == 'scenes: a, b, c'
        assert finding_scene_list({'scenes': ['a', 'b']}) == ''   # the message names both
        assert finding_scene_list({'scene_id': 'a'}) == ''

    def test_validate_text_report_lists_the_scenes_between(self, capsys):
        from storyforge.cmd_validate import _print_human_readable
        scenes = self._scenes([('p', '30', 'x', ''), ('a', '10', 'y', ''),
                               ('mid', '11', 'y', ''), ('b', '12', 'y', '')])
        failures = self._failures(scenes)
        _print_human_readable({'structural': {'passed': False, 'checks': failures,
                                              'failures': failures},
                               'schema': None})
        out = capsys.readouterr().out
        assert 'scenes: a, mid, b' in out


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


class TestMiceOps:
    """F-020: per-scene extraction marked scenes that touch a thread with
    +/-, so The Great Gatsby had one thread opened in 15 scenes and another
    closed in 9, producing 53 blocking 'nesting violations'."""

    def _report(self, tmp_path, mice):
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)
        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|act|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, len(mice) + 1):
                f.write(f's0{i}|{i}|Scene {i}|1|Alice|Room|{i}|morning|1 hour|action|briefed|1000|2000\n')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i, m in enumerate(mice, 1):
                f.write(f's0{i}|test|action|flat|truth|+/-|revelation|Alice|Alice|{m}\n')
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            for i in range(1, len(mice) + 1):
                f.write(f's0{i}|g|c|o|cr|d|k|k|a|d|e|m||false\n')
        return validate_structure(ref)

    def test_repeated_ops_are_advisory_data_findings(self, tmp_path):
        report = self._report(tmp_path, ['+inquiry:q', '+inquiry:q', '-inquiry:q', '-inquiry:q'])
        msgs = [c for c in report['checks'] if c['check'] == 'mice-ops' and not c['passed']]
        assert any('opened in 2 scenes' in c['message'] for c in msgs)
        assert any('closed in 2 scenes' in c['message'] for c in msgs)
        assert all(c['severity'] == 'advisory' for c in msgs)

    def test_mentions_are_not_operations(self, tmp_path):
        report = self._report(tmp_path, ['+inquiry:q', 'inquiry:q', 'inquiry:q', '-inquiry:q'])
        assert any(c['check'] == 'mice-ops' and c['passed'] for c in report['checks'])

    def test_mice_never_blocks(self, tmp_path):
        report = self._report(tmp_path, ['+inquiry:a', '+inquiry:b', '-inquiry:a', '-inquiry:a', '-inquiry:z'])
        assert not [c for c in report['failures'] if c['category'] == 'threads'
                    and c.get('severity', 'blocking') != 'advisory']

    def test_prompts_use_open_once_notation(self):
        from storyforge.extract import build_intent_prompt
        prompt = build_intent_prompt('s1', 'Prose.', {}, {})
        assert 'only if this scene is where the thread begins' in prompt
        assert 'bare thread-name' in prompt


class TestUnmigratedActReportedOnce:
    """Dry run on a real project: before cleanup, every scene failed as
    blocking 'missing required columns: [act]' (43 of 43 in one project)."""

    def test_one_notice_not_one_per_scene(self, tmp_path):
        from storyforge.elaborate import validate_structure
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)
        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 4):
                f.write(f's0{i}|{i}|S{i}|{i}|Ann|Room|{i}|morning|1h|action|mapped|100|100\n')
        report = validate_structure(ref)
        act_missing = [c for c in report['failures'] if "['act']" in c['message']]
        notices = [c for c in report['failures'] if c['check'] == 'act-migration']
        assert act_missing == []
        assert len(notices) == 1 and 'storyforge cleanup' in notices[0]['message']
