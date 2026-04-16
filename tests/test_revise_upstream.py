"""Tests for revise upstream delegation and validation gate."""

import csv
import os


class TestFileHash:
    def test_consistent_hash(self, tmp_path):
        from storyforge.cmd_revise import _file_hash
        f = tmp_path / 'test.csv'
        f.write_text('id|goal\nscene-a|something\n')
        h1 = _file_hash(str(f))
        h2 = _file_hash(str(f))
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_detects_change(self, tmp_path):
        from storyforge.cmd_revise import _file_hash
        f = tmp_path / 'test.csv'
        f.write_text('id|goal\nscene-a|old\n')
        h1 = _file_hash(str(f))
        f.write_text('id|goal\nscene-a|new\n')
        h2 = _file_hash(str(f))
        assert h1 != h2

    def test_missing_file(self):
        from storyforge.cmd_revise import _file_hash
        assert _file_hash('/nonexistent/file.csv') == ''


class TestWriteHoneFindings:
    def test_writes_correct_format(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'brief', 'scene-a;scene-b', 'Fix the briefs')

        with open(path) as f:
            content = f.read()
        assert 'scene_id|target_file|fields|guidance' in content
        assert 'scene-a|scene-briefs.csv||Fix the briefs' in content
        assert 'scene-b|scene-briefs.csv||Fix the briefs' in content

    def test_intent_target_file(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'intent', 'scene-a', 'Fix intent')

        with open(path) as f:
            content = f.read()
        assert 'scene-intent.csv' in content

    def test_empty_targets_no_ref_dir_writes_header_only(self, tmp_path):
        """Without ref_dir, empty targets produces header-only file with warning."""
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'brief', '', 'General fix')

        with open(path) as f:
            lines = f.read().strip().split('\n')
        assert len(lines) == 1  # Header only — no data rows

    def test_empty_targets_with_ref_dir_expands_to_all_scenes(self, tmp_path, fixture_dir):
        """Regression #199: full-scope pass must expand to all scene IDs from the CSV."""
        from storyforge.cmd_revise import _write_hone_findings
        ref_dir = os.path.join(fixture_dir, 'reference')
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'brief', '', 'General fix', ref_dir=ref_dir)

        with open(path) as f:
            lines = f.read().strip().split('\n')
        # Header + one row per scene in scene-briefs.csv
        assert len(lines) > 1
        # Every data row should have a non-empty scene_id
        for line in lines[1:]:
            sid = line.split('|')[0]
            assert sid, f'Empty scene_id in findings row: {line}'
            assert 'scene-briefs.csv' in line

    def test_empty_targets_intent_expands_to_all_scenes(self, tmp_path, fixture_dir):
        """Full scope for intent fix_location expands to all scene IDs."""
        from storyforge.cmd_revise import _write_hone_findings
        ref_dir = os.path.join(fixture_dir, 'reference')
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'intent', '', 'Fix intent globally', ref_dir=ref_dir)

        with open(path) as f:
            lines = f.read().strip().split('\n')
        assert len(lines) > 1
        for line in lines[1:]:
            sid = line.split('|')[0]
            assert sid, f'Empty scene_id in findings row: {line}'
            assert 'scene-intent.csv' in line

    def test_character_name_targets_resolve_to_scenes(self, tmp_path, fixture_dir):
        """Regression #199: character name targets must resolve to scene IDs."""
        from storyforge.cmd_revise import _write_hone_findings
        ref_dir = os.path.join(fixture_dir, 'reference')
        path = str(tmp_path / 'findings.csv')
        # "Pell" is a character in the fixture's scene-intent.csv
        _write_hone_findings(path, 'brief', 'Pell', 'Fix Pell scenes', ref_dir=ref_dir)

        with open(path) as f:
            lines = f.read().strip().split('\n')
        assert len(lines) > 1
        # All data rows should have valid scene IDs, not "Pell"
        for line in lines[1:]:
            sid = line.split('|')[0]
            assert sid != 'Pell', 'Character name should be resolved to scene IDs'
            assert sid, f'Empty scene_id in findings row: {line}'

    def test_mixed_scene_ids_and_character_names(self, tmp_path, fixture_dir):
        """Mix of valid scene IDs and character names resolves correctly."""
        from storyforge.cmd_revise import _write_hone_findings
        ref_dir = os.path.join(fixture_dir, 'reference')
        path = str(tmp_path / 'findings.csv')
        # act1-sc01 is a valid scene ID, "Pell" is a character name
        _write_hone_findings(path, 'intent', 'act1-sc01;Pell', 'Fix things', ref_dir=ref_dir)

        with open(path) as f:
            lines = f.read().strip().split('\n')
        scene_ids = [line.split('|')[0] for line in lines[1:]]
        assert 'act1-sc01' in scene_ids
        # Pell should be resolved, not kept as raw target
        assert 'Pell' not in scene_ids


class TestGenerateStructuralPlan:
    """Regression tests for _generate_structural_plan guidance population."""

    def _write_proposals(self, project_dir, rows):
        """Write a proposals CSV from a list of row dicts."""
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(scores_dir, exist_ok=True)
        filepath = os.path.join(scores_dir, 'structural-proposals.csv')
        header = 'id|dimension|fix_location|target|change|rationale|status'
        lines = [header]
        for row in rows:
            lines.append(
                f"{row['id']}|{row['dimension']}|{row['fix_location']}|"
                f"{row['target']}|{row['change']}|{row['rationale']}|{row['status']}"
            )
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def test_guidance_includes_prescription_and_change(self, tmp_path):
        """Regression: guidance must contain prescription text and change directives."""
        from storyforge.cmd_revise import _generate_structural_plan

        project_dir = str(tmp_path)
        plans_dir = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans_dir, exist_ok=True)
        plan_file = os.path.join(plans_dir, 'revision-plan.csv')

        self._write_proposals(project_dir, [{
            'id': 'sp001',
            'dimension': 'character_presence',
            'fix_location': 'intent',
            'target': 'scene-a',
            'change': 'add Charlie to on_stage',
            'rationale': 'Charlie absent from mid-section',
            'status': 'pending',
        }])

        rows = _generate_structural_plan(project_dir, plan_file)
        assert len(rows) == 1
        guidance = rows[0]['guidance']
        # Must include the prescription text from _PRESCRIPTIONS_FULL
        assert 'add them to on_stage' in guidance
        # Must include the proposal's change directive
        assert 'add Charlie to on_stage' in guidance

    def test_guidance_empty_change_still_has_prescription(self, tmp_path):
        """Even with empty change field, guidance should have the prescription."""
        from storyforge.cmd_revise import _generate_structural_plan

        project_dir = str(tmp_path)
        plans_dir = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans_dir, exist_ok=True)
        plan_file = os.path.join(plans_dir, 'revision-plan.csv')

        self._write_proposals(project_dir, [{
            'id': 'sp001',
            'dimension': 'pacing_shape',
            'fix_location': 'intent',
            'target': 'global',
            'change': '',
            'rationale': 'score 0.60 below target 0.70',
            'status': 'pending',
        }])

        rows = _generate_structural_plan(project_dir, plan_file)
        assert len(rows) == 1
        guidance = rows[0]['guidance']
        assert 'act proportions' in guidance.lower() or 'Part 1' in guidance
        # No "Proposed changes:" since change field is empty
        assert 'Proposed changes:' not in guidance

    def test_multiple_proposals_same_dimension_merge_changes(self, tmp_path):
        """Multiple proposals for same dimension should merge change directives."""
        from storyforge.cmd_revise import _generate_structural_plan

        project_dir = str(tmp_path)
        plans_dir = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans_dir, exist_ok=True)
        plan_file = os.path.join(plans_dir, 'revision-plan.csv')

        self._write_proposals(project_dir, [
            {
                'id': 'sp001',
                'dimension': 'character_presence',
                'fix_location': 'intent',
                'target': 'scene-a',
                'change': 'add Charlie to on_stage',
                'rationale': 'Charlie absent',
                'status': 'pending',
            },
            {
                'id': 'sp002',
                'dimension': 'character_presence',
                'fix_location': 'intent',
                'target': 'scene-b',
                'change': 'add Dana to characters',
                'rationale': 'Dana missing',
                'status': 'pending',
            },
        ])

        rows = _generate_structural_plan(project_dir, plan_file)
        assert len(rows) == 1
        guidance = rows[0]['guidance']
        assert 'add Charlie to on_stage' in guidance
        assert 'add Dana to characters' in guidance
