"""Tests for structural scoring engine (migrated from test-structural.sh)."""

import os
import shutil


class TestScoreCompleteness:
    def test_returns_score_and_findings(self, fixture_dir):
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.structural import score_completeness
        scenes = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scene-intent.csv'))
        briefs = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scene-briefs.csv'))
        result = score_completeness(scenes, intent, briefs)
        assert 0 <= result['score'] <= 1
        assert isinstance(result['findings'], list)

    def test_fully_briefed_scores_one(self):
        from storyforge.structural import score_completeness
        full_scenes = {'s1': {'id': 's1'}, 's2': {'id': 's2'}}
        full_intent = {
            's1': {'id': 's1', 'function': 'Hook', 'value_at_stake': 'truth', 'value_shift': '+/-',
                   'emotional_arc': 'calm to tense', 'mice_threads': '+inquiry:x'},
            's2': {'id': 's2', 'function': 'Climax', 'value_at_stake': 'life', 'value_shift': '-/+',
                   'emotional_arc': 'tense to resolved', 'mice_threads': '-inquiry:x'},
        }
        full_briefs = {}
        for sid in ['s1', 's2']:
            full_briefs[sid] = {
                'id': sid, 'goal': 'G', 'conflict': 'C', 'outcome': 'O', 'crisis': 'Cr',
                'decision': 'D', 'knowledge_in': 'ki', 'knowledge_out': 'ko',
                'key_actions': 'ka', 'key_dialogue': 'kd', 'emotions': 'e', 'motifs': 'm',
                'continuity_deps': 'cd', 'physical_state_in': 'psi', 'physical_state_out': 'pso',
            }
        result = score_completeness(full_scenes, full_intent, full_briefs)
        assert result['score'] == 1.0
        assert len(result['findings']) == 0

    def test_empty_scene_scores_zero(self):
        from storyforge.structural import score_completeness
        result = score_completeness({'e1': {'id': 'e1'}}, {'e1': {'id': 'e1'}}, {'e1': {'id': 'e1'}})
        assert result['score'] == 0.0
        severities = [f['severity'] for f in result['findings']]
        assert 'important' in severities
        assert 'minor' in severities

    def test_orphan_scene(self):
        from storyforge.structural import score_completeness
        result = score_completeness({'orphan': {'id': 'orphan'}}, {}, {})
        assert result['score'] == 0.0

    def test_fixture_range(self, fixture_dir):
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.structural import score_completeness
        scenes = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scene-intent.csv'))
        briefs = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scene-briefs.csv'))
        result = score_completeness(scenes, intent, briefs)
        assert 0.3 < result['score'] < 0.9


class TestScoreThematicConcentration:
    def test_focused_scores_high(self, tmp_path):
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.structural import score_thematic_concentration
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i, val in enumerate(['truth', 'truth', 'justice', 'safety', 'justice', 'truth'], 1):
                f.write(f's{i:02d}|test|action|flat|{val}|+/-|revelation|A|A|\n')
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        result = score_thematic_concentration(intent)
        assert result['score'] > 0.6

    def test_scattered_scores_low(self, tmp_path):
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.structural import score_thematic_concentration
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 21):
                f.write(f's{i:02d}|test|action|flat|value-{i}|+/-|revelation|A|A|\n')
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        result = score_thematic_concentration(intent)
        assert result['score'] < 0.5


class TestClassifyArcShape:
    def test_all_shapes(self):
        from storyforge.structural import _classify_arc_shape

        shape, rev, comp = _classify_arc_shape(['+/-', '+/-', '+/-'])
        assert shape == 'tragedy'
        assert rev == 0

        shape, rev, comp = _classify_arc_shape(['-/+', '-/+', '-/+'])
        assert shape == 'rags-to-riches'

        shape, rev, comp = _classify_arc_shape(['+/-', '+/-', '-/+', '-/+'])
        assert shape == 'man-in-a-hole'
        assert rev == 1

        shape, rev, comp = _classify_arc_shape(['-/+', '-/+', '+/-', '+/-'])
        assert shape == 'icarus'

        shape, rev, comp = _classify_arc_shape(['+/-', '-/+', '+/-', '-/+'])
        assert shape == 'cinderella'
        assert comp is True

        shape, rev, comp = _classify_arc_shape(['-/+', '+/-', '-/+', '+/-'])
        assert shape == 'oedipus'

        shape, rev, comp = _classify_arc_shape(['', '', ''])
        assert shape == 'flat'


class TestScoreArcs:
    def test_varied_beats_flat(self, tmp_path):
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.structural import score_arcs
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i, pov in enumerate(['alice', 'alice', 'bob', 'alice', 'bob', 'alice', 'bob', 'alice'], 1):
                f.write(f's{i:02d}|{i}|Scene {i}|{(i-1)//3+1}|{pov}|X|{i}|morning|1h|action|drafted|2000|2000\n')

        shifts = ['+/-', '-/+', '+/-', '+/-', '+/-', '-/+', '+/-', '-/+']
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i, shift in enumerate(shifts, 1):
                pov = 'alice' if i in [1,2,4,6,8] else 'bob'
                f.write(f's{i:02d}|test|action|flat|truth|{shift}|revelation|{pov}|{pov}|\n')

        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        result = score_arcs(scenes, intent)
        assert 0 <= result['score'] <= 1


class TestStructuralScore:
    def test_returns_all_dimensions(self, fixture_dir):
        from storyforge.structural import structural_score
        report = structural_score(os.path.join(fixture_dir, 'reference'))
        assert 'overall_score' in report
        assert len(report['dimensions']) == 9
        names = [d['name'] for d in report['dimensions']]
        for expected in ['arc_completeness', 'thematic_concentration', 'pacing_shape',
                         'character_presence', 'mice_health', 'knowledge_chain',
                         'function_variety', 'completeness', 'physical_state']:
            assert expected in names

    def test_format_scorecard(self, fixture_dir):
        from storyforge.structural import structural_score, format_scorecard
        report = structural_score(os.path.join(fixture_dir, 'reference'))
        card = format_scorecard(report)
        assert 'Structural Score' in card
        assert 'Arc Completeness' in card

    def test_format_diagnosis_all_levels(self, fixture_dir):
        from storyforge.structural import structural_score, format_diagnosis
        report = structural_score(os.path.join(fixture_dir, 'reference'))
        for level in ['full', 'coach', 'strict']:
            result = format_diagnosis(report, level)
            assert isinstance(result, str)

    def test_fix_location_in_findings(self, fixture_dir):
        from storyforge.structural import structural_score
        report = structural_score(os.path.join(fixture_dir, 'reference'))
        for dim in report['dimensions']:
            for f in dim['findings']:
                assert 'fix_location' in f
                assert f['fix_location'] in ('structural', 'intent', 'brief', 'registry')


class TestSaveLoadScores:
    def test_roundtrip(self, fixture_dir, tmp_path):
        from storyforge.structural import structural_score, save_structural_scores, load_previous_scores
        save_dir = str(tmp_path / 'save')
        os.makedirs(save_dir)

        assert load_previous_scores(save_dir) is None

        report = structural_score(os.path.join(fixture_dir, 'reference'))
        path = save_structural_scores(report, save_dir)
        assert path is not None

        prev = load_previous_scores(save_dir)
        assert prev is not None
        assert 'arc_completeness' in prev
        assert 'overall' in prev
        assert abs(prev['overall'] - report['overall_score']) < 0.001


class TestGenerateProposals:
    def test_creates_proposals(self, tmp_path):
        from storyforge.structural import structural_score, generate_structural_proposals
        ref = str(tmp_path / 'reference')
        scores_dir = str(tmp_path / 'working' / 'scores')
        os.makedirs(ref)
        os.makedirs(scores_dir)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 5):
                f.write(f's{i:02d}|{i}|Scene {i}|1|alice|X|{i}|morning|1h|action|drafted|2000|2000\n')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 5):
                f.write(f's{i:02d}|test|action|calm|truth|+/-|revelation|alice|alice|\n')
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            for i in range(1, 5):
                f.write(f's{i:02d}|g|c|yes-but|cr|d|||a|d|e|m||false\n')

        report = structural_score(ref)
        path = generate_structural_proposals(report, scores_dir)
        assert path is not None
        assert os.path.isfile(path)

    def test_none_when_above_target(self, tmp_path):
        from storyforge.structural import generate_structural_proposals
        report = {
            'overall_score': 0.90,
            'dimensions': [
                {'name': 'completeness', 'score': 0.95, 'target': 0.80, 'findings': []},
                {'name': 'thematic_concentration', 'score': 0.85, 'target': 0.60, 'findings': []},
                {'name': 'pacing_shape', 'score': 0.80, 'target': 0.75, 'findings': []},
                {'name': 'arc_completeness', 'score': 0.90, 'target': 0.80, 'findings': []},
                {'name': 'character_presence', 'score': 0.85, 'target': 0.70, 'findings': []},
                {'name': 'mice_health', 'score': 0.75, 'target': 0.60, 'findings': []},
                {'name': 'knowledge_chain', 'score': 0.70, 'target': 0.60, 'findings': []},
                {'name': 'function_variety', 'score': 0.80, 'target': 0.65, 'findings': []},
            ],
        }
        path = generate_structural_proposals(report, str(tmp_path / 'no-proposals'))
        assert path is None


class TestPrintScoreDelta:
    def test_shows_deltas(self):
        from storyforge.structural import print_score_delta
        pre = {
            'arc_completeness': {'score': 0.80, 'target': 0.80},
            'thematic_concentration': {'score': 0.30, 'target': 0.60},
            'pacing_shape': {'score': 0.62, 'target': 0.75},
        }
        post = {
            'arc_completeness': {'score': 0.85, 'target': 0.80},
            'thematic_concentration': {'score': 0.50, 'target': 0.60},
            'pacing_shape': {'score': 0.62, 'target': 0.75},
        }
        output = print_score_delta(pre, post)
        assert 'arc_completeness' in output
        assert '+0.05' in output
        assert '+0.20' in output
        assert '0.00' in output


class TestMiceScoringBareNames:
    def test_resolves_from_registry(self, fixture_dir, tmp_path):
        from storyforge.structural import score_mice_health
        from storyforge.elaborate import _read_csv_as_map, _read_csv, _write_csv, _FILE_MAP

        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('map-anomaly|Map Anomaly|inquiry|\n')
            f.write('archive-erasure|Archive Erasure|inquiry|\n')

        intent_path = os.path.join(ref, 'scene-intent.csv')
        rows = _read_csv(intent_path)
        for r in rows:
            if r['id'] == 'act1-sc01':
                r['mice_threads'] = '+map-anomaly'
            elif r['id'] == 'act1-sc02':
                r['mice_threads'] = '+archive-erasure'
            elif r['id'] == 'act2-sc03':
                r['mice_threads'] = '-map-anomaly;-archive-erasure'
        _write_csv(intent_path, rows, _FILE_MAP['scene-intent.csv'])

        scenes_map = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        intent_map = _read_csv_as_map(intent_path)
        result = score_mice_health(scenes_map, intent_map, ref_dir=ref)
        assert 0 <= result['score'] <= 1


class TestCharacterPresenceUsesIds:
    """Regression test for #128: char_roles must be keyed by ID, not display name."""

    def test_antagonist_detected_with_kebab_ids(self, tmp_path):
        """on_stage uses kebab-case IDs; characters.csv has display names.
        char_roles must use the id column so antagonist lookup succeeds."""
        from storyforge.structural import score_character_presence
        from storyforge.elaborate import _read_csv_as_map

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        # characters.csv — display name differs from id
        with open(os.path.join(ref, 'characters.csv'), 'w') as f:
            f.write('id|name|aliases|role\n')
            f.write('garrett-steen|Garrett Steen||antagonist\n')
            f.write('elena-voss|Elena Voss||protagonist\n')

        # scenes.csv — pov uses kebab-case ids
        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 9):
                pov = 'elena-voss'
                f.write(f's{i:02d}|{i}|Scene {i}|1|{pov}|X|{i}|morning|1h|action|drafted|2000|2000\n')

        # scene-intent.csv — on_stage uses kebab-case ids
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 9):
                on_stage = 'elena-voss;garrett-steen' if i % 2 == 0 else 'elena-voss'
                f.write(f's{i:02d}|test|action|flat|truth|+/-|revelation|elena-voss;garrett-steen|{on_stage}|\n')

        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        result = score_character_presence(scenes, intent, ref)

        # The antagonist garrett-steen is on-stage in 4/8 scenes (50%).
        # Before the fix, char_roles was keyed by "Garrett Steen" which never
        # matched on_stage "garrett-steen", so antagonist visibility was 0%.
        assert result['score'] > 0.5

        # Verify no finding about antagonist having 0 scenes on-stage
        antag_findings = [f for f in result['findings']
                          if 'antagonist' in f.get('message', '').lower()
                          and '0/' in f.get('message', '')]
        assert len(antag_findings) == 0, f"Antagonist should not show 0 on-stage: {antag_findings}"


class TestPacingEscalation:
    """Regression tests for #131: escalation sub-metric should not assume a single narrative shape."""

    def _make_pacing_data(self, n, tension_fn):
        """Build scenes_map, intent_map, briefs_map with controlled tension values."""
        scenes_map = {}
        intent_map = {}
        briefs_map = {}
        for i in range(n):
            sid = f's{i:02d}'
            scenes_map[sid] = {'seq': str(i + 1), 'part': '1', 'target_words': '2000'}
            shift, outcome, action = tension_fn(i, n)
            intent_map[sid] = {'value_shift': shift, 'action_sequel': action}
            briefs_map[sid] = {'outcome': outcome}
        return scenes_map, intent_map, briefs_map

    def test_crisis_resolution_not_penalized(self):
        """A novel that peaks at ~80% then resolves should score well, not be penalized."""
        from storyforge.structural import score_pacing

        # Build tension that rises to climax zone then gently resolves
        def tension_fn(i, n):
            pct = i / (n - 1)
            if pct < 0.65:
                # Rising action: alternate high/low tension
                if i % 2 == 0:
                    return '+/-', 'no-and', 'action'
                else:
                    return '-/+', 'yes-but', 'sequel'
            elif pct < 0.90:
                # Climax zone: high tension
                return '+/-', 'no-and', 'action'
            else:
                # Resolution: lower tension
                return '-/+', 'yes', 'sequel'
        scenes, intent, briefs = self._make_pacing_data(20, tension_fn)
        result = score_pacing(scenes, intent, briefs)
        # Should not contain "no escalation" finding
        esc_findings = [f for f in result['findings'] if 'escalation' in f.get('message', '').lower()]
        assert len(esc_findings) == 0, f"Crisis-resolution shape should not trigger escalation warning: {esc_findings}"

    def test_flat_tension_penalized(self):
        """A novel with truly flat tension throughout should still be flagged."""
        from storyforge.structural import score_pacing

        def tension_fn(i, n):
            return '-/+', 'yes', 'sequel'  # all low tension
        scenes, intent, briefs = self._make_pacing_data(20, tension_fn)
        result = score_pacing(scenes, intent, briefs)
        # Flat tension = climax peak equals first quarter mean, should get neutral or low score
        assert result['score'] < 0.85
