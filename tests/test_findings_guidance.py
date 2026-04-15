"""Tests for findings-based revision guidance generation."""

import os
import pytest


class TestLoadFindings:
    def test_loads_repetition_findings(self, tmp_path):
        from storyforge.cmd_revise import _load_findings

        cycle_dir = str(tmp_path)
        with open(os.path.join(cycle_dir, 'repetition-findings.csv'), 'w') as f:
            f.write('phrase|category|severity|count|scene_ids\n')
            f.write('the edge of the|signature_phrase|high|21|s01;s02;s03\n')
            f.write('chin on her paws|character_tell|high|16|s01;s04;s05\n')

        findings = _load_findings(cycle_dir)
        assert len(findings['repetition']) == 2
        assert findings['repetition'][0]['phrase'] == 'the edge of the'
        assert findings['repetition'][0]['count'] == 21

    def test_loads_scene_findings(self, tmp_path):
        from storyforge.cmd_revise import _load_findings

        cycle_dir = str(tmp_path)
        with open(os.path.join(cycle_dir, 'scene-findings.csv'), 'w') as f:
            f.write('scene_id|principle|finding|detail\n')
            f.write('s01|avoid_passive|ap-1|5/20 passive sentences (25%), cluster=True\n')
            f.write('s01|avoid_adverbs|aa-1|3 adverb issues (2.1/1000 words)\n')
            f.write('s02|economy_clarity|ec-1|filler 4.2/1000 words\n')

        findings = _load_findings(cycle_dir)
        assert 's01' in findings['scenes']
        assert len(findings['scenes']['s01']) == 2
        assert findings['scenes']['s01'][0]['principle'] == 'avoid_passive'

    def test_missing_files_return_empty(self, tmp_path):
        from storyforge.cmd_revise import _load_findings

        findings = _load_findings(str(tmp_path))
        assert findings['repetition'] == []
        assert findings['scenes'] == {}


class TestBuildFindingsGuidance:
    def test_manuscript_preamble_from_repetition(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [
                {'phrase': 'the edge of the', 'category': 'signature_phrase',
                 'severity': 'high', 'count': 21, 'scene_ids': ['s01', 's02', 's03']},
                {'phrase': 'chin on her paws', 'category': 'character_tell',
                 'severity': 'high', 'count': 16, 'scene_ids': ['s01', 's04']},
            ],
            'scenes': {},
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01', 's02'])
        assert 'the edge of the' in guidance
        assert '21' in guidance
        assert 'reduce' in guidance.lower()
        assert 'eliminate' not in guidance.lower()

    def test_per_scene_specifics(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [],
            'scenes': {
                's01': [
                    {'principle': 'avoid_passive', 'finding': 'ap-1',
                     'detail': '5/20 passive sentences (25%), cluster=True'},
                    {'principle': 'avoid_adverbs', 'finding': 'aa-1',
                     'detail': '3 adverb issues'},
                ],
                's02': [
                    {'principle': 'economy_clarity', 'finding': 'ec-1',
                     'detail': 'filler 4.2/1000 words'},
                ],
            },
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01', 's02'])
        assert 's01' in guidance
        assert 'passive' in guidance.lower()
        assert 's02' in guidance
        assert 'filler' in guidance.lower()

    def test_only_target_scenes_included(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [],
            'scenes': {
                's01': [{'principle': 'avoid_passive', 'finding': 'ap-1',
                         'detail': 'passive cluster'}],
                's99': [{'principle': 'avoid_passive', 'finding': 'ap-1',
                         'detail': 'should not appear'}],
            },
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        assert 's01' in guidance
        assert 's99' not in guidance

    def test_empty_findings_returns_empty_string(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {'repetition': [], 'scenes': {}}
        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        assert guidance == ''

    def test_repetition_target_count(self):
        """Target occurrences should be count/5, minimum 2."""
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [
                {'phrase': 'common phrase', 'category': 'signature_phrase',
                 'severity': 'high', 'count': 10, 'scene_ids': ['s01']},
                {'phrase': 'rare phrase', 'category': 'signature_phrase',
                 'severity': 'medium', 'count': 3, 'scene_ids': ['s01']},
            ],
            'scenes': {},
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        assert 'reduce to 2' in guidance.lower()

    def test_limits_to_top_10_repetitions(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [
                {'phrase': f'phrase {i}', 'category': 'signature_phrase',
                 'severity': 'high', 'count': 20 - i, 'scene_ids': ['s01']}
                for i in range(15)
            ],
            'scenes': {},
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        assert 'phrase 0' in guidance
        assert 'phrase 9' in guidance
        assert 'phrase 10' not in guidance

    def test_limits_to_top_5_findings_per_scene(self):
        from storyforge.cmd_revise import _build_findings_guidance

        findings = {
            'repetition': [],
            'scenes': {
                's01': [
                    {'principle': f'principle_{i}', 'finding': f'f{i}',
                     'detail': f'detail {i}'}
                    for i in range(8)
                ],
            },
        }

        guidance = _build_findings_guidance(findings, target_scenes=['s01'])
        assert 'detail 0' in guidance
        assert 'detail 4' in guidance
        assert 'detail 5' not in guidance


class TestScoresPlanWithFindings:
    def test_scores_plan_includes_repetition_guidance(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')

        latest_dir = str(tmp_path / 'latest')
        os.makedirs(latest_dir)
        with open(os.path.join(latest_dir, 'repetition-findings.csv'), 'w') as f:
            f.write('phrase|category|severity|count|scene_ids\n')
            f.write('the edge of|signature_phrase|high|15|s01;s02;s03\n')

        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01;s02', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows, findings_dir=latest_dir)
        assert len(rows) >= 1
        all_guidance = ' '.join(r['guidance'] for r in rows)
        assert 'the edge of' in all_guidance
        assert 'reduce' in all_guidance.lower()

    def test_scores_plan_includes_scene_findings(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')

        latest_dir = str(tmp_path / 'latest')
        os.makedirs(latest_dir)
        with open(os.path.join(latest_dir, 'scene-findings.csv'), 'w') as f:
            f.write('scene_id|principle|finding|detail\n')
            f.write('s01|avoid_passive|ap-1|passive cluster (25%)\n')

        diag_rows = [
            {'principle': 'avoid_passive', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows, findings_dir=latest_dir)
        craft_passes = [r for r in rows if r['fix_location'] == 'craft']
        assert len(craft_passes) >= 1
        assert 'passive cluster' in craft_passes[0]['guidance']

    def test_scores_plan_works_without_findings(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows, findings_dir=str(tmp_path))
        assert len(rows) >= 1


class TestWriteHoneFindings:
    def test_sanitizes_pipes_and_newlines_in_guidance(self, tmp_path):
        """Guidance with pipes and newlines must not corrupt the hone findings CSV."""
        import csv
        from storyforge.cmd_revise import _write_hone_findings

        findings_path = str(tmp_path / 'findings.csv')
        # Guidance with pipes (from detail fields) and newlines (from multi-line findings)
        guidance = (
            'Score-driven fixes.\n'
            'Cross-scene patterns:\n'
            '  - "the edge of the" (21x|signature_phrase) — reduce to 4\n'
            '  Scene s01: avoid_passive: 5/20 passive (25%)|cluster=True'
        )

        _write_hone_findings(findings_path, 'brief', 's01;s02', guidance)

        with open(findings_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            rows = list(reader)

        # Should parse cleanly — exactly 4 columns per row
        assert len(rows) == 2
        for row in rows:
            assert set(row.keys()) == {'scene_id', 'target_file', 'fields', 'guidance'}
            assert None not in row.values()
            assert row['scene_id'] in ('s01', 's02')
            assert row['target_file'] == 'scene-briefs.csv'
            # Pipes and newlines should be sanitized
            assert '|' not in row['guidance']
            assert '\n' not in row['guidance']
