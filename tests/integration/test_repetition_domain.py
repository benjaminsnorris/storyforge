"""Tests for repetition.py domain library and cmd_repetition.py command.

Covers functions and code paths not already tested in tests/test_repetition.py:
  - categorize_finding: sensory, structural, signature_phrase, as-if/as-though simile
  - scan_scenes: severity levels, custom thresholds, multi-scene tracking
  - scan_manuscript: directory fallback, no scenes dir, status filtering
  - suppress_subphrases: edge cases
  - cmd_repetition: parse_args, main (report generation, category filter)
"""

import os

from storyforge.repetition import (
    tokenize_scene,
    extract_ngrams,
    categorize_finding,
    suppress_subphrases,
    scan_scenes,
    scan_manuscript,
    score_scene_repetition,
    STOP_WORDS,
    THRESHOLDS,
)


# ============================================================================
# categorize_finding — uncovered categories
# ============================================================================

class TestCategorizeFinding:
    def test_sensory_category(self):
        assert categorize_finding('the cold sharp air') == 'sensory'

    def test_sensory_with_smell(self):
        assert categorize_finding('he smelled the bitter smoke') == 'sensory'

    def test_structural_category_for_the_first_time(self):
        assert categorize_finding('for the first time she') == 'structural'

    def test_structural_category_in_that_moment(self):
        assert categorize_finding('in that moment she knew') == 'structural'

    def test_structural_category_the_kind_of(self):
        assert categorize_finding('it was the kind of') == 'structural'

    def test_signature_phrase_fallback(self):
        """Phrases matching no specific category should be signature_phrase."""
        cat = categorize_finding('the weight of silence')
        assert cat == 'signature_phrase'

    def test_simile_as_if(self):
        cat = categorize_finding('moved as if nothing mattered')
        assert cat == 'simile'

    def test_simile_as_though(self):
        cat = categorize_finding('spoke as though rehearsed long')
        assert cat == 'simile'

    def test_like_at_start_not_simile(self):
        """'like' as the first word is not a simile (e.g., 'like a')."""
        # categorize_finding checks 'like' in words[1:], so index 0 is excluded
        cat = categorize_finding('like something in the dark')
        # 'like' is at index 0, so NOT a simile — should fall through
        assert cat != 'simile'

    def test_body_part_takes_priority_over_sensory(self):
        """Body parts should categorize as character_tell even if sensory words present."""
        # 'hands' = body part, 'cold' = sensory; body parts checked first
        cat = categorize_finding('her cold rough hands')
        assert cat == 'character_tell'


# ============================================================================
# scan_scenes — severity, thresholds, filtering
# ============================================================================

class TestScanScenes:
    def _make_scenes(self, phrase, scene_count):
        """Build scene_texts where the same phrase appears in multiple scenes."""
        padding = 'the quick brown fox jumps over the lazy dog and runs away'
        scenes = {}
        for i in range(scene_count):
            scenes[f's{i+1}'] = f'{padding} {phrase} {padding}'
        return scenes

    def test_high_severity_for_4plus_occurrences(self):
        scenes = self._make_scenes('her dark piercing eyes narrowed', 5)
        findings = scan_scenes(scenes)
        relevant = [f for f in findings if 'eyes narrowed' in f['phrase']
                     or 'piercing eyes' in f['phrase']
                     or 'dark piercing eyes' in f['phrase']]
        assert len(relevant) > 0, "Expected repeated phrase to be detected"
        high = [f for f in relevant if f['severity'] == 'high']
        assert len(high) > 0

    def test_medium_severity_for_fewer_occurrences(self):
        # 4-grams need 5 occurrences for default threshold, so 3 should not match
        # But 6-grams need only 2, so craft a 6-gram that appears in 3 scenes
        phrase = 'a very specific unique six word'
        scenes = {}
        for i in range(3):
            scenes[f's{i+1}'] = f'once upon {phrase} story told by many'
        findings = scan_scenes(scenes)
        relevant = [f for f in findings if 'specific unique' in f['phrase']]
        assert len(relevant) > 0, "Expected repeated phrase to be detected"
        # Any findings at this count should be medium (count < 4)
        medium = [f for f in relevant if f['count'] < 4]
        for f in medium:
            assert f['severity'] == 'medium'

    def test_custom_thresholds(self):
        """Custom min_occurrences overrides defaults."""
        phrase = 'the ancient stone bridge'
        scenes = {f's{i+1}': f'they crossed {phrase} at dawn' for i in range(2)}
        # Default 4-gram threshold is 5, so 2 scenes won't trigger
        findings_default = scan_scenes(scenes)
        default_phrases = [f['phrase'] for f in findings_default]

        # Lower threshold to 2 for 4-grams
        findings_custom = scan_scenes(scenes, min_occurrences={4: 2})
        custom_phrases = [f['phrase'] for f in findings_custom]

        # With lowered threshold, we should find more (or at least as many)
        assert len(findings_custom) >= len(findings_default)

    def test_single_scene_phrases_excluded(self):
        """Phrases appearing in only one scene are never reported."""
        scenes = {
            's1': 'the magnificent crystal tower shone brightly ' * 3,
            's2': 'the humble wooden cottage stood alone ' * 3,
        }
        findings = scan_scenes(scenes)
        for f in findings:
            assert len(f['scene_ids']) >= 2

    def test_empty_scenes(self):
        findings = scan_scenes({})
        assert findings == []

    def test_single_scene_input(self):
        findings = scan_scenes({'s1': 'hello world this is a test'})
        assert findings == []


# ============================================================================
# extract_ngrams edge cases
# ============================================================================

class TestExtractNgramsEdgeCases:
    def test_deduplicates_same_scene(self):
        """Same phrase multiple times in one scene only records scene once."""
        tokens = tokenize_scene('the cat sat on the mat and the cat sat on the rug')
        ngrams = extract_ngrams(tokens, 4, 'scene-1')
        key = ('the', 'cat', 'sat', 'on')
        assert key in ngrams
        # Scene should appear only once even though the phrase occurs twice
        assert ngrams[key] == ['scene-1']

    def test_empty_tokens(self):
        ngrams = extract_ngrams([], 4, 'scene-1')
        assert ngrams == {}

    def test_tokens_shorter_than_n(self):
        tokens = ['hello', 'world']
        ngrams = extract_ngrams(tokens, 4, 'scene-1')
        assert ngrams == {}


# ============================================================================
# suppress_subphrases edge cases
# ============================================================================

class TestSuppressSubphrasesEdgeCases:
    def test_empty_list(self):
        assert suppress_subphrases([]) == []

    def test_no_containment(self):
        findings = [
            {'phrase': 'the red fox', 'count': 5, 'category': 'signature_phrase'},
            {'phrase': 'blue sky above', 'count': 3, 'category': 'signature_phrase'},
        ]
        result = suppress_subphrases(findings)
        assert len(result) == 2

    def test_similar_count_suppresses(self):
        findings = [
            {'phrase': 'back of his neck', 'count': 5, 'category': 'character_tell'},
            {'phrase': 'of his neck', 'count': 5, 'category': 'character_tell'},
        ]
        result = suppress_subphrases(findings)
        phrases = [f['phrase'] for f in result]
        assert 'back of his neck' in phrases
        assert 'of his neck' not in phrases

    def test_distant_counts_preserved(self):
        """Subphrase with very different count is kept (diff > 1)."""
        findings = [
            {'phrase': 'back of his neck', 'count': 5, 'category': 'character_tell'},
            {'phrase': 'of his', 'count': 20, 'category': 'character_tell'},
        ]
        result = suppress_subphrases(findings)
        phrases = [f['phrase'] for f in result]
        assert 'back of his neck' in phrases
        assert 'of his' in phrases  # kept because count difference > 1


# ============================================================================
# scan_manuscript
# ============================================================================

class TestScanManuscript:
    def test_no_scenes_dir_returns_empty(self, tmp_path):
        """If scenes/ directory doesn't exist, return empty list."""
        findings = scan_manuscript(str(tmp_path))
        assert findings == []

    def test_directory_listing_fallback(self, tmp_path):
        """Without scenes.csv, falls back to listing .md files in scenes/."""
        scenes_dir = tmp_path / 'scenes'
        scenes_dir.mkdir()

        # Write two scenes with repeated phrase
        phrase = 'the old stone bridge across the river'
        for name in ['scene-a', 'scene-b']:
            (scenes_dir / f'{name}.md').write_text(
                f'They crossed {phrase}. Later, they returned to {phrase}. '
                f'The memory of {phrase} haunted them.'
            )

        # No reference/scenes.csv -> should use directory listing
        findings = scan_manuscript(str(tmp_path))
        assert len(findings) >= 1  # repeated phrase should be detected

    def test_status_filtering(self, tmp_path):
        """Scenes with cut/merged/spine/architecture/mapped status are excluded."""
        ref = tmp_path / 'reference'
        ref.mkdir()
        scenes_dir = tmp_path / 'scenes'
        scenes_dir.mkdir()

        with open(ref / 'scenes.csv', 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('active|1|Active|1|A|R|1|m|1h|a|briefed|1000|2000\n')
            f.write('cutscene|2|Cut|1|A|R|2|m|1h|a|cut|1000|2000\n')

        (scenes_dir / 'active.md').write_text('Active scene content.')
        (scenes_dir / 'cutscene.md').write_text('Cut scene content.')

        findings = scan_manuscript(str(tmp_path))
        # The cut scene should not appear in any finding's scene_ids
        for f in findings:
            assert 'cutscene' not in f['scene_ids']

    def test_explicit_scene_ids(self, project_dir):
        """Passing explicit scene_ids filters to those scenes only."""
        findings = scan_manuscript(project_dir, scene_ids=['act1-sc01'])
        # With only one scene, no cross-scene repetition possible
        assert findings == []

    def test_full_scan_on_fixture(self, project_dir):
        """Full scan on fixture data produces valid findings structure."""
        findings = scan_manuscript(project_dir)
        assert isinstance(findings, list)
        for f in findings:
            assert 'phrase' in f
            assert 'category' in f
            assert f['severity'] in ('high', 'medium')
            assert isinstance(f['scene_ids'], list)
            assert len(f['scene_ids']) >= 2


# ============================================================================
# score_scene_repetition edge cases
# ============================================================================

class TestScoreSceneRepetitionEdgeCases:
    def test_sensory_maps_to_pr4(self):
        findings = [
            {'phrase': 'the cold sharp air', 'category': 'sensory',
             'severity': 'medium', 'count': 3, 'scene_ids': ['s1', 's2', 's3']},
        ]
        scores = score_scene_repetition('s1', findings)
        assert scores['pr-4'] == 1

    def test_signature_phrase_maps_to_pr4(self):
        findings = [
            {'phrase': 'the weight of silence', 'category': 'signature_phrase',
             'severity': 'medium', 'count': 3, 'scene_ids': ['s1', 's2', 's3']},
        ]
        scores = score_scene_repetition('s1', findings)
        assert scores['pr-4'] == 1

    def test_empty_findings(self):
        scores = score_scene_repetition('s1', [])
        assert scores == {'pr-1': 0, 'pr-2': 0, 'pr-3': 0, 'pr-4': 0}

    def test_multiple_categories_in_one_scene(self):
        findings = [
            {'phrase': 'eyes like broken glass', 'category': 'simile',
             'severity': 'high', 'count': 4, 'scene_ids': ['s1', 's2', 's3', 's4']},
            {'phrase': 'the cold sharp wind', 'category': 'sensory',
             'severity': 'medium', 'count': 3, 'scene_ids': ['s1', 's2', 's3']},
            {'phrase': 'for the first time', 'category': 'structural',
             'severity': 'high', 'count': 5, 'scene_ids': ['s1', 's2', 's3', 's4', 's5']},
        ]
        scores = score_scene_repetition('s1', findings)
        assert scores['pr-1'] == 1  # simile
        assert scores['pr-3'] == 1  # structural
        assert scores['pr-4'] == 1  # sensory


# ============================================================================
# cmd_repetition — parse_args and main
# ============================================================================

class TestCmdRepetitionParseArgs:
    def test_default_args(self):
        from storyforge.cmd_repetition import parse_args
        args = parse_args([])
        assert args.min_occurrences == 0
        assert args.category is None

    def test_category_filter(self):
        from storyforge.cmd_repetition import parse_args
        args = parse_args(['--category', 'simile'])
        assert args.category == 'simile'

    def test_min_occurrences(self):
        from storyforge.cmd_repetition import parse_args
        args = parse_args(['--min-occurrences', '5'])
        assert args.min_occurrences == 5

    def test_scene_filter_args_present(self):
        from storyforge.cmd_repetition import parse_args
        args = parse_args(['--scenes', 's1,s2'])
        assert hasattr(args, 'scenes')


class TestCmdRepetitionMain:
    def test_main_writes_report(self, project_dir, monkeypatch):
        """main() should write a repetition-report.csv to working/."""
        from storyforge.cmd_repetition import main

        monkeypatch.setattr(
            'storyforge.cmd_repetition.detect_project_root', lambda: project_dir
        )

        main([])

        report_path = os.path.join(project_dir, 'working', 'repetition-report.csv')
        assert os.path.isfile(report_path)

        with open(report_path) as f:
            header = f.readline().strip()
        assert header == 'phrase|category|severity|count|scene_ids'

    def test_main_category_filter(self, project_dir, monkeypatch):
        """Category filter should limit findings in the report."""
        from storyforge.cmd_repetition import main

        monkeypatch.setattr(
            'storyforge.cmd_repetition.detect_project_root', lambda: project_dir
        )

        # Run with category filter
        main(['--category', 'simile'])

        report_path = os.path.join(project_dir, 'working', 'repetition-report.csv')
        assert os.path.isfile(report_path)

        with open(report_path) as f:
            lines = f.readlines()
        # All data lines (skip header) should be simile category
        for line in lines[1:]:
            if line.strip():
                fields = line.strip().split('|')
                assert fields[1] == 'simile'
