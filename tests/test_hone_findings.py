"""Tests for external findings loading and integration with hone."""
import os
import inspect


class TestLoadExternalFindings:
    def test_parses_findings_csv(self, tmp_path):
        from storyforge.hone import load_external_findings
        f = tmp_path / 'findings.csv'
        f.write_text(
            'scene_id|target_file|fields|guidance\n'
            'scene-a|scene-briefs.csv|goal;conflict|Fix hallucinated characters\n'
            'scene-b|scene-intent.csv|function|Function is too vague\n'
        )
        results = load_external_findings(str(f))
        assert len(results) == 3
        r0 = [r for r in results if r['scene_id'] == 'scene-a' and r['field'] == 'goal'][0]
        assert r0['issue'] == 'evaluation'
        assert r0['guidance'] == 'Fix hallucinated characters'
        assert r0['target_file'] == 'scene-briefs.csv'
        r1 = [r for r in results if r['scene_id'] == 'scene-a' and r['field'] == 'conflict'][0]
        assert r1['issue'] == 'evaluation'
        r2 = [r for r in results if r['scene_id'] == 'scene-b'][0]
        assert r2['target_file'] == 'scene-intent.csv'

    def test_empty_fields_means_single_issue(self, tmp_path):
        from storyforge.hone import load_external_findings
        f = tmp_path / 'findings.csv'
        f.write_text(
            'scene_id|target_file|fields|guidance\n'
            'scene-a|scene-briefs.csv||General fix needed\n'
        )
        results = load_external_findings(str(f))
        assert len(results) == 1
        assert results[0]['field'] == ''
        assert results[0]['guidance'] == 'General fix needed'

    def test_missing_file_returns_empty(self):
        from storyforge.hone import load_external_findings
        results = load_external_findings('/nonexistent/file.csv')
        assert results == []


class TestBuildEvaluationFixPrompt:
    def test_includes_guidance_and_fields(self):
        from storyforge.hone import build_evaluation_fix_prompt
        prompt = build_evaluation_fix_prompt(
            scene_id='test-scene',
            fields=['goal', 'conflict'],
            current_values={'goal': 'old goal', 'conflict': 'old conflict'},
            guidance='Fix hallucinated characters Voss and Dren',
        )
        assert 'test-scene' in prompt
        assert 'goal' in prompt
        assert 'conflict' in prompt
        assert 'old goal' in prompt
        assert 'hallucinated' in prompt.lower() or 'Voss' in prompt

    def test_output_format(self):
        from storyforge.hone import build_evaluation_fix_prompt
        prompt = build_evaluation_fix_prompt(
            scene_id='s1',
            fields=['goal'],
            current_values={'goal': 'x'},
            guidance='fix it',
        )
        assert 'goal:' in prompt.lower()

    def test_includes_voice_guide_when_provided(self):
        from storyforge.hone import build_evaluation_fix_prompt
        prompt = build_evaluation_fix_prompt(
            scene_id='s1',
            fields=['goal'],
            current_values={'goal': 'x'},
            guidance='fix it',
            voice_guide='Use sensory details from cooking.',
        )
        assert 'cooking' in prompt.lower() or 'sensory' in prompt.lower()


class TestHoneBriefsWithFindings:
    def test_signature_accepts_findings_file(self):
        from storyforge.hone import hone_briefs
        sig = inspect.signature(hone_briefs)
        assert 'findings_file' in sig.parameters

    def test_invalid_scene_id_skipped_not_crash(self, project_dir):
        """Regression #199: non-scene-ID targets must not crash hone_briefs."""
        from storyforge.hone import hone_briefs
        ref_dir = os.path.join(project_dir, 'reference')

        # Write a findings file with an invalid scene ID (character name)
        findings = os.path.join(project_dir, 'working', 'findings.csv')
        os.makedirs(os.path.dirname(findings), exist_ok=True)
        with open(findings, 'w') as f:
            f.write('scene_id|target_file|fields|guidance\n')
            f.write('not-a-real-scene|scene-briefs.csv|goal|Fix this\n')

        # Should not raise KeyError
        result = hone_briefs(
            ref_dir=ref_dir,
            project_dir=project_dir,
            scene_ids=['not-a-real-scene'],
            coaching_level='full',
            dry_run=True,
            findings_file=findings,
        )
        assert isinstance(result, dict)


class TestHoneIntentWithFindings:
    def test_invalid_scene_id_skipped_not_crash(self, project_dir):
        """Regression #199: non-scene-ID targets must not crash hone_intent."""
        from storyforge.hone import hone_intent
        ref_dir = os.path.join(project_dir, 'reference')

        findings = os.path.join(project_dir, 'working', 'findings.csv')
        os.makedirs(os.path.dirname(findings), exist_ok=True)
        with open(findings, 'w') as f:
            f.write('scene_id|target_file|fields|guidance\n')
            f.write('not-a-real-scene|scene-intent.csv|function|Fix this\n')

        result = hone_intent(
            ref_dir=ref_dir,
            project_dir=project_dir,
            scene_ids=['not-a-real-scene'],
            coaching_level='full',
            dry_run=True,
            findings_file=findings,
        )
        assert isinstance(result, dict)


class TestResolveTargetsToSceneIds:
    def test_valid_scene_ids_pass_through(self):
        """Valid scene IDs should pass through unchanged."""
        from storyforge.cmd_revise import _resolve_targets_to_scene_ids
        valid = {'scene-a', 'scene-b', 'scene-c'}
        result = _resolve_targets_to_scene_ids(['scene-a', 'scene-b'], valid, '/tmp')
        assert result == ['scene-a', 'scene-b']

    def test_character_names_resolve_to_scenes(self, fixture_dir):
        """Character names should resolve to scenes via scene-intent.csv."""
        from storyforge.cmd_revise import _resolve_targets_to_scene_ids
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(fixture_dir, 'reference')
        briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
        valid = set(briefs_map.keys())
        # "Pell" is a character in the fixture
        result = _resolve_targets_to_scene_ids(['Pell'], valid, ref_dir)
        assert len(result) > 0
        assert 'Pell' not in result  # resolved to scene IDs

    def test_unknown_targets_skipped(self, fixture_dir):
        """Targets that are neither scene IDs nor character names are skipped."""
        from storyforge.cmd_revise import _resolve_targets_to_scene_ids
        ref_dir = os.path.join(fixture_dir, 'reference')
        valid = {'scene-a'}
        result = _resolve_targets_to_scene_ids(['nonexistent-thing'], valid, ref_dir)
        assert result == []
