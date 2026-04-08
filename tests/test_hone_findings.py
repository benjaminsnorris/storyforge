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
