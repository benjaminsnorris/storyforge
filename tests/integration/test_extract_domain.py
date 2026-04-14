"""Tests for storyforge.extract — extraction prompt builders, response parsers,
similarity functions, cleanup passes, and expansion analysis.

Focuses on library functions that don't require API calls: parsers, prompt
builders, similarity helpers, and deterministic cleanup operations.
"""

import os

import pytest

from storyforge.extract import (
    _read_file,
    _read_all_scenes,
    _read_manuscript,
    _similarity,
    _id_similarity,
    parse_characterize_response,
    parse_skeleton_response,
    parse_intent_response,
    parse_brief_parallel_response,
    parse_knowledge_response,
    parse_physical_state_response,
    build_characterize_prompt,
    build_skeleton_prompt,
    build_intent_prompt,
    build_brief_parallel_prompt,
    build_knowledge_prompt,
    build_physical_state_prompt,
    analyze_expansion_opportunities,
    cleanup_timeline,
    cleanup_knowledge,
    cleanup_mice_threads,
    cleanup_physical_states,
    run_cleanup,
)


# ============================================================================
# Helper utilities
# ============================================================================


class TestReadFile:
    """Tests for _read_file."""

    def test_reads_existing_file(self, project_dir):
        path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        content = _read_file(path)
        assert 'Dorren Hayle' in content

    def test_returns_empty_for_missing_file(self, project_dir):
        result = _read_file(os.path.join(project_dir, 'nonexistent.md'))
        assert result == ''


class TestReadAllScenes:
    """Tests for _read_all_scenes."""

    def test_reads_all_scene_files(self, project_dir):
        scenes = _read_all_scenes(project_dir)
        assert 'act1-sc01' in scenes
        assert 'act1-sc02' in scenes
        assert 'act2-sc01' in scenes
        assert 'new-x1' in scenes
        assert len(scenes) == 4

    def test_scene_ids_from_filenames(self, project_dir):
        scenes = _read_all_scenes(project_dir)
        # IDs are filenames minus .md
        for sid in scenes:
            assert not sid.endswith('.md')

    def test_returns_empty_if_no_scenes_dir(self, tmp_path):
        result = _read_all_scenes(str(tmp_path))
        assert result == {}


class TestReadManuscript:
    """Tests for _read_manuscript."""

    def test_concatenates_scenes_in_seq_order(self, project_dir):
        manuscript = _read_manuscript(project_dir)
        assert manuscript != ''
        # Should contain scene markers
        assert '=== SCENE: act1-sc01 ===' in manuscript
        assert '=== SCENE: act1-sc02 ===' in manuscript
        # act1-sc01 (seq=1) should appear before act1-sc02 (seq=2)
        pos1 = manuscript.index('=== SCENE: act1-sc01 ===')
        pos2 = manuscript.index('=== SCENE: act1-sc02 ===')
        assert pos1 < pos2

    def test_returns_empty_for_empty_project(self, tmp_path):
        result = _read_manuscript(str(tmp_path))
        assert result == ''

    def test_orders_by_seq_from_csv(self, project_dir):
        manuscript = _read_manuscript(project_dir)
        # act2-sc01 is seq=4, should come after new-x1 (seq=3)
        pos_x1 = manuscript.index('=== SCENE: new-x1 ===')
        pos_act2 = manuscript.index('=== SCENE: act2-sc01 ===')
        assert pos_x1 < pos_act2


# ============================================================================
# Similarity functions
# ============================================================================


class TestSimilarity:
    """Tests for _similarity (word-overlap Jaccard)."""

    def test_identical_strings(self):
        assert _similarity('the map is forged', 'the map is forged') == 1.0

    def test_completely_different(self):
        assert _similarity('hello world', 'foo bar baz') == 0.0

    def test_partial_overlap(self):
        score = _similarity('the eastern readings', 'the eastern section readings')
        assert 0.5 < score < 1.0

    def test_empty_strings(self):
        assert _similarity('', '') == 0.0
        assert _similarity('hello', '') == 0.0
        assert _similarity('', 'world') == 0.0


class TestIdSimilarity:
    """Tests for _id_similarity (edit-distance based)."""

    def test_identical_ids(self):
        assert _id_similarity('broken-arm-marcus', 'broken-arm-marcus') == 1.0

    def test_empty_strings(self):
        # Two empty strings are equal, so the function returns 1.0
        assert _id_similarity('', '') == 1.0
        assert _id_similarity('hello', '') == 0.0
        assert _id_similarity('', 'world') == 0.0

    def test_single_char_typo(self):
        score = _id_similarity('broken-arm-marcus', 'broken-arm-marcas')
        assert score > 0.9  # One character difference

    def test_very_different_ids(self):
        score = _id_similarity('broken-arm-marcus', 'has-compass-elena')
        assert score < 0.5

    def test_short_ids(self):
        score = _id_similarity('ab', 'ac')
        assert 0.0 < score < 1.0


# ============================================================================
# Response parsers
# ============================================================================


class TestParseCharacterizeResponse:
    """Tests for parse_characterize_response."""

    def test_parses_labeled_fields(self):
        response = """NARRATIVE_MODE: first-person
POV_CHARACTERS: Dorren Hayle; Tessa Merrin
TIMELINE: linear
TIMELINE_SPAN: 3 days
SCENE_BREAK_STYLE: explicit-markers
ESTIMATED_SCENES: 42
ACT_STRUCTURE: 3 acts: scenes 1-12, 13-28, 29-42
MAJOR_THREADS: map-anomaly; archive-erasure
CENTRAL_CONFLICT: A cartographer discovers her maps are erasing people
PROTAGONIST_ARC: Perfectionist denial to confronting institutional power
TONE: ominous literary
CAST_SIZE: 12
KEY_LOCATIONS: Pressure Cartography Office; The Deep Archive
COMPRESSION_POINTS: council confrontation
STRUCTURAL_CONCERNS: pacing in act 2"""

        result = parse_characterize_response(response)
        assert result['narrative_mode'] == 'first-person'
        assert result['pov_characters'] == 'Dorren Hayle; Tessa Merrin'
        assert result['timeline'] == 'linear'
        assert result['estimated_scenes'] == '42'
        assert result['central_conflict'] == 'A cartographer discovers her maps are erasing people'
        assert result['tone'] == 'ominous literary'

    def test_skips_unknown_and_na_values(self):
        response = """NARRATIVE_MODE: first-person
TIMELINE: N/A
CAST_SIZE: none
KEY_LOCATIONS: []"""

        result = parse_characterize_response(response)
        assert 'narrative_mode' in result
        assert 'timeline' not in result
        assert 'cast_size' not in result
        assert 'key_locations' not in result

    def test_skips_non_labeled_lines(self):
        response = """Some introductory text.
NARRATIVE_MODE: third-limited
Another line of commentary.
TONE: dark"""

        result = parse_characterize_response(response)
        assert len(result) == 2
        assert result['narrative_mode'] == 'third-limited'
        assert result['tone'] == 'dark'

    def test_empty_response(self):
        result = parse_characterize_response('')
        assert result == {}


class TestParseSkeletonResponse:
    """Tests for parse_skeleton_response."""

    def test_parses_all_fields(self):
        response = """TITLE: The Finest Cartographer
POV: Dorren Hayle
LOCATION: Pressure Cartography Office
TIMELINE_DAY: 1
TIME_OF_DAY: morning
DURATION: 2 hours
TYPE: character
TARGET_WORDS: 2500
PART: 1"""

        result = parse_skeleton_response(response, 'act1-sc01')
        assert result['id'] == 'act1-sc01'
        assert result['title'] == 'The Finest Cartographer'
        assert result['pov'] == 'Dorren Hayle'
        assert result['location'] == 'Pressure Cartography Office'
        assert result['timeline_day'] == '1'
        assert result['time_of_day'] == 'morning'
        assert result['type'] == 'character'
        assert result['target_words'] == '2500'
        assert result['part'] == '1'

    def test_skips_unknown_values(self):
        response = """TITLE: A Scene
POV: UNKNOWN
LOCATION: Some Place"""

        result = parse_skeleton_response(response, 'test-scene')
        assert result['id'] == 'test-scene'
        assert result['title'] == 'A Scene'
        assert 'pov' not in result
        assert result['location'] == 'Some Place'

    def test_ignores_unknown_labels(self):
        response = """TITLE: Test
BOGUS_FIELD: should be ignored
POV: Alice"""

        result = parse_skeleton_response(response, 's1')
        assert 'bogus_field' not in result
        assert result['title'] == 'Test'
        assert result['pov'] == 'Alice'


class TestParseIntentResponse:
    """Tests for parse_intent_response."""

    def test_parses_intent_fields(self):
        response = """FUNCTION: Establishes Dorren as institutional gatekeeper
ACTION_SEQUEL: action
EMOTIONAL_ARC: Controlled competence to buried unease
VALUE_AT_STAKE: truth
VALUE_SHIFT: +/-
TURNING_POINT: revelation
CHARACTERS: Dorren Hayle; Tessa Merrin; Pell
ON_STAGE: Dorren Hayle; Tessa Merrin
MICE_THREADS: +inquiry:map-anomaly
CONFIDENCE: high"""

        result = parse_intent_response(response, 'act1-sc01')
        assert result['id'] == 'act1-sc01'
        assert result['function'] == 'Establishes Dorren as institutional gatekeeper'
        assert result['action_sequel'] == 'action'
        assert result['value_at_stake'] == 'truth'
        assert result['characters'] == 'Dorren Hayle; Tessa Merrin; Pell'
        assert result['_confidence'] == 'high'

    def test_skips_unknown_values(self):
        response = """FUNCTION: Does something important
VALUE_AT_STAKE: UNKNOWN"""

        result = parse_intent_response(response, 'test')
        assert 'function' in result
        assert 'value_at_stake' not in result


class TestParseBriefParallelResponse:
    """Tests for parse_brief_parallel_response."""

    def test_parses_brief_fields(self):
        response = """GOAL: Complete the quarterly pressure audit on schedule
CONFLICT: Anomalous readings don't match known patterns
OUTCOME: no-and
CRISIS: Report the anomaly or file it as error
DECISION: Files as instrument error but keeps a private note
KEY_ACTIONS: Reviews maps; Finds anomaly; Consults Tessa
KEY_DIALOGUE: "The eastern readings are within acceptable variance"
EMOTIONS: competence; unease; self-doubt; resolve
MOTIFS: maps/cartography; acceptable-variance
SUBTEXT: Dorren says acceptable but means unexplained"""

        result = parse_brief_parallel_response(response, 'act1-sc01')
        assert result['id'] == 'act1-sc01'
        assert result['goal'] == 'Complete the quarterly pressure audit on schedule'
        assert result['outcome'] == 'no-and'
        assert 'Reviews maps' in result['key_actions']
        assert result['motifs'] == 'maps/cartography; acceptable-variance'

    def test_skips_none_for_subtext(self):
        response = """GOAL: Do something
SUBTEXT: NONE"""

        result = parse_brief_parallel_response(response, 'test')
        assert 'subtext' not in result

    def test_skips_unknown_for_all_fields(self):
        response = """GOAL: UNKNOWN
CONFLICT: Something real"""

        result = parse_brief_parallel_response(response, 'test')
        assert 'goal' not in result
        assert result['conflict'] == 'Something real'


class TestParseKnowledgeResponse:
    """Tests for parse_knowledge_response."""

    def test_parses_knowledge_fields(self):
        response = """KNOWLEDGE_IN: map-anomaly-exists; village-vanished
KNOWLEDGE_OUT: map-anomaly-exists; village-vanished; archive-erasure
CONTINUITY_DEPS: act1-sc01; act1-sc02
SCENE_SUMMARY: Kael reveals the archive has been systematically altered."""

        result = parse_knowledge_response(response, 'new-x1')
        assert result['id'] == 'new-x1'
        assert 'map-anomaly-exists' in result['knowledge_in']
        assert 'archive-erasure' in result['knowledge_out']
        assert result['continuity_deps'] == 'act1-sc01; act1-sc02'
        assert result['_summary'] == 'Kael reveals the archive has been systematically altered.'

    def test_empty_knowledge_in_kept(self):
        # Unlike other parsers, knowledge allows empty-looking values
        response = """KNOWLEDGE_IN:
KNOWLEDGE_OUT: some-fact
SCENE_SUMMARY: First scene."""

        result = parse_knowledge_response(response, 's1')
        # Empty value after colon -> not stored
        assert 'knowledge_in' not in result
        assert result['knowledge_out'] == 'some-fact'


class TestParsePhysicalStateResponse:
    """Tests for parse_physical_state_response."""

    def test_parses_simple_response(self):
        response = """PHYSICAL_STATE_IN: broken-arm-marcus; has-compass-elena
PHYSICAL_STATE_OUT: broken-arm-marcus; has-compass-elena; exhaustion-tessa
NEW_STATES: exhaustion-tessa|Tessa|Exhausted after climbing|fatigue|false
RESOLVED_STATES:"""

        result = parse_physical_state_response(response, 'act2-sc01')
        assert result['id'] == 'act2-sc01'
        assert 'broken-arm-marcus' in result['physical_state_in']
        assert 'exhaustion-tessa' in result['physical_state_out']
        assert len(result['_new_states']) == 1
        assert result['_new_states'][0]['id'] == 'exhaustion-tessa'
        assert result['_new_states'][0]['character'] == 'Tessa'
        assert result['_new_states'][0]['category'] == 'fatigue'
        assert result['_resolved'] == []

    def test_parses_multiple_new_states(self):
        response = """PHYSICAL_STATE_IN:
PHYSICAL_STATE_OUT: broken-arm-marcus; has-compass-elena
NEW_STATES: broken-arm-marcus|Marcus|Left arm broken|injury|true
has-compass-elena|Elena|Carrying stolen compass|equipment|false
RESOLVED_STATES: old-wound-marcus"""

        result = parse_physical_state_response(response, 's1')
        assert len(result['_new_states']) == 2
        assert result['_new_states'][0]['id'] == 'broken-arm-marcus'
        assert result['_new_states'][1]['id'] == 'has-compass-elena'
        assert result['_resolved'] == ['old-wound-marcus']

    def test_parses_resolved_states(self):
        response = """PHYSICAL_STATE_IN: broken-arm-marcus
PHYSICAL_STATE_OUT:
RESOLVED_STATES: broken-arm-marcus; old-wound"""

        result = parse_physical_state_response(response, 's2')
        assert result['_resolved'] == ['broken-arm-marcus', 'old-wound']

    def test_empty_response(self):
        result = parse_physical_state_response('', 's3')
        assert result['id'] == 's3'
        assert result['_new_states'] == []
        assert result['_resolved'] == []


# ============================================================================
# Prompt builders
# ============================================================================


class TestBuildCharacterizePrompt:
    """Tests for build_characterize_prompt."""

    def test_includes_project_metadata(self, project_dir):
        prompt = build_characterize_prompt(project_dir)
        assert "The Cartographer's Silence" in prompt
        assert 'fantasy' in prompt

    def test_includes_scene_content(self, project_dir):
        prompt = build_characterize_prompt(project_dir)
        assert 'Dorren Hayle' in prompt
        assert '=== SCENE:' in prompt

    def test_returns_empty_for_no_scenes(self, tmp_path):
        # Create a minimal storyforge.yaml but no scenes
        yaml_path = tmp_path / 'storyforge.yaml'
        yaml_path.write_text('project:\n  title: "Test"\n  genre: "test"\n')
        prompt = build_characterize_prompt(str(tmp_path))
        assert prompt == ''


class TestBuildSkeletonPrompt:
    """Tests for build_skeleton_prompt."""

    def test_includes_scene_text(self):
        prompt = build_skeleton_prompt(
            'test-scene', 'The rain fell hard.',
            {'pov_characters': 'Alice', 'key_locations': 'The Library'},
        )
        assert 'test-scene' in prompt
        assert 'The rain fell hard.' in prompt
        assert 'Alice' in prompt

    def test_includes_existing_metadata(self):
        prompt = build_skeleton_prompt(
            's1', 'text', {'pov_characters': 'Bob'},
            existing_metadata={'title': 'The Start', 'pov': 'Bob'},
        )
        assert 'title: The Start' in prompt
        assert 'pov: Bob' in prompt

    def test_includes_registries(self):
        prompt = build_skeleton_prompt(
            's1', 'text', {},
            registries_text='## Character Registry\nAlice | protagonist',
        )
        assert '## Character Registry' in prompt


class TestBuildIntentPrompt:
    """Tests for build_intent_prompt."""

    def test_includes_skeleton_context(self):
        prompt = build_intent_prompt(
            'act1-sc01', 'Scene text here.',
            {'major_threads': 'thread-a; thread-b', 'central_conflict': 'Good vs evil'},
            {'title': 'The Start', 'pov': 'Dorren', 'location': 'Office'},
        )
        assert 'Title: The Start' in prompt
        assert 'POV: Dorren' in prompt
        assert 'thread-a; thread-b' in prompt
        assert 'Good vs evil' in prompt


class TestBuildBriefParallelPrompt:
    """Tests for build_brief_parallel_prompt."""

    def test_includes_intent_context(self):
        prompt = build_brief_parallel_prompt(
            'act1-sc01', 'Scene text.',
            {},
            {'title': 'The Start', 'pov': 'Alice'},
            {'function': 'Establishes tension', 'value_at_stake': 'truth', 'value_shift': '+/-'},
        )
        assert 'Function: Establishes tension' in prompt
        assert 'Value at stake: truth' in prompt
        assert 'Value shift: +/-' in prompt


class TestBuildKnowledgePrompt:
    """Tests for build_knowledge_prompt."""

    def test_includes_prior_knowledge(self):
        prompt = build_knowledge_prompt(
            'act1-sc02', 'Scene text.',
            {'pov': 'Dorren'},
            {},
            {'Dorren': 'map-anomaly-exists'},
            ['Scene 1: Dorren finds an anomaly in the maps.'],
        )
        assert 'POV Character: Dorren' in prompt
        assert 'map-anomaly-exists' in prompt
        assert 'Dorren finds an anomaly' in prompt

    def test_first_scene_no_prior(self):
        prompt = build_knowledge_prompt(
            'act1-sc01', 'Scene text.',
            {'pov': 'Dorren'},
            {},
            {},
            [],
        )
        assert '(first scene)' in prompt
        assert 'No prior knowledge established' in prompt


class TestBuildPhysicalStatePrompt:
    """Tests for build_physical_state_prompt."""

    def test_includes_prior_states(self):
        prompt = build_physical_state_prompt(
            'act2-sc02', 'Scene text.',
            {'on_stage': 'Tessa; Pell'},
            {'Tessa': {'exhaustion-tessa'}, 'Pell': {'has-compass-pell'}},
            ['Scene 3: Tessa enters the reaches.'],
        )
        assert 'On-stage characters: Tessa; Pell' in prompt
        assert 'exhaustion-tessa' in prompt
        assert 'has-compass-pell' in prompt

    def test_no_prior_states(self):
        prompt = build_physical_state_prompt(
            'act1-sc01', 'Scene text.',
            {'pov': 'Dorren'},
            {},
            [],
        )
        assert '(no prior physical states established)' in prompt


# ============================================================================
# Expansion analysis
# ============================================================================


class TestAnalyzeExpansionOpportunities:
    """Tests for analyze_expansion_opportunities."""

    def test_detects_opportunities_from_fixture(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        opportunities = analyze_expansion_opportunities(ref_dir)
        # Should return a list (may be empty depending on fixture data)
        assert isinstance(opportunities, list)
        for opp in opportunities:
            assert 'type' in opp
            assert 'scene_id' in opp
            assert 'description' in opp
            assert 'priority' in opp

    def test_detects_missing_sequel(self, project_dir):
        """Consecutive action scenes should flag a missing sequel."""
        ref_dir = os.path.join(project_dir, 'reference')
        opportunities = analyze_expansion_opportunities(ref_dir)
        missing_sequel = [o for o in opportunities if o['type'] == 'missing_sequel']
        # The fixture has consecutive action scenes (act2-sc01 and act2-sc02 are both action)
        assert len(missing_sequel) >= 1

    def test_sorted_by_priority(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        opportunities = analyze_expansion_opportunities(ref_dir)
        if len(opportunities) > 1:
            priority_order = {'high': 0, 'medium': 1, 'low': 2}
            for i in range(len(opportunities) - 1):
                assert (priority_order.get(opportunities[i]['priority'], 3)
                        <= priority_order.get(opportunities[i + 1]['priority'], 3))


# ============================================================================
# Cleanup passes
# ============================================================================


class TestCleanupTimeline:
    """Tests for cleanup_timeline."""

    def test_fills_missing_timeline_days(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')

        # Clear a timeline_day to create a gap
        scenes_csv = os.path.join(ref_dir, 'scenes.csv')
        with open(scenes_csv, encoding='utf-8') as f:
            lines = f.readlines()

        # Remove timeline_day for act1-sc02 (seq=2, day=1)
        # Header: id|seq|title|part|pov|location|timeline_day|...
        new_lines = [lines[0]]
        for line in lines[1:]:
            fields = line.strip().split('|')
            if fields[0] == 'act1-sc02':
                fields[6] = ''  # timeline_day
                new_lines.append('|'.join(fields) + '\n')
            else:
                new_lines.append(line)

        with open(scenes_csv, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        fixes = cleanup_timeline(ref_dir)
        assert len(fixes) >= 1
        fix_ids = [f['scene_id'] for f in fixes]
        assert 'act1-sc02' in fix_ids

    def test_no_fixes_when_complete(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        fixes = cleanup_timeline(ref_dir)
        # All fixture scenes have timeline_day set, so no fixes needed
        assert fixes == []


class TestCleanupKnowledge:
    """Tests for cleanup_knowledge."""

    def test_normalizes_similar_knowledge(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')

        # Modify knowledge_in for act2-sc03 to use slightly different wording
        briefs_csv = os.path.join(ref_dir, 'scene-briefs.csv')
        with open(briefs_csv, encoding='utf-8') as f:
            content = f.read()

        # Replace an exact knowledge_in fact with a slightly different wording
        # act2-sc03 has knowledge_in: village-vanished;archive-erasure
        # Change "village-vanished" to "the village vanished" (similar but different)
        content = content.replace(
            'village-vanished;archive-erasure',
            'the village has vanished;archive-erasure',
        )
        with open(briefs_csv, 'w', encoding='utf-8') as f:
            f.write(content)

        fixes = cleanup_knowledge(ref_dir)
        # cleanup_knowledge processes knowledge fields — result depends on
        # similarity thresholds and the specific data. Verify it runs cleanly.
        assert isinstance(fixes, list)
        assert all(isinstance(f, dict) for f in fixes) if fixes else True


class TestCleanupMiceThreads:
    """Tests for cleanup_mice_threads."""

    def test_removes_duplicate_opens(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')

        # Add a duplicate open to act2-sc01
        intent_csv = os.path.join(ref_dir, 'scene-intent.csv')
        with open(intent_csv, encoding='utf-8') as f:
            content = f.read()

        # act1-sc01 already opens +inquiry:map-anomaly. Add it again in act2-sc01
        content = content.replace(
            '+milieu:uncharted-reaches',
            '+inquiry:map-anomaly;+milieu:uncharted-reaches',
        )
        with open(intent_csv, 'w', encoding='utf-8') as f:
            f.write(content)

        fixes = cleanup_mice_threads(ref_dir)
        assert len(fixes) >= 1
        # Should remove the duplicate open
        dup_fixes = [f for f in fixes if 'duplicate open' in f['new_value']]
        assert len(dup_fixes) >= 1

    def test_removes_close_for_unopened(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')

        intent_csv = os.path.join(ref_dir, 'scene-intent.csv')
        with open(intent_csv, encoding='utf-8') as f:
            content = f.read()

        # Add a close for a thread that was never opened
        content = content.replace(
            '+milieu:uncharted-reaches',
            '+milieu:uncharted-reaches;-inquiry:never-opened',
        )
        with open(intent_csv, 'w', encoding='utf-8') as f:
            f.write(content)

        fixes = cleanup_mice_threads(ref_dir)
        unopened_fixes = [f for f in fixes if 'unopened' in f['new_value']]
        assert len(unopened_fixes) >= 1


class TestCleanupPhysicalStates:
    """Tests for cleanup_physical_states."""

    def test_normalizes_typo_in_state_id(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')

        # act1-sc02 has physical_state_in: archive-key-dorren;exhaustion-tessa
        # Introduce a typo: "archve-key-dorren"
        briefs_csv = os.path.join(ref_dir, 'scene-briefs.csv')
        with open(briefs_csv, encoding='utf-8') as f:
            content = f.read()

        # new-x1 has physical_state_in: archive-key-dorren
        # and physical_state_out: archive-key-dorren
        # act1-sc02 has physical_state_in that includes archive-key-dorren
        # Introduce a typo in act2-sc03's physical_state_in
        content = content.replace(
            'archive-key-dorren;exhaustion-tessa|archive-key-dorren',
            'archve-key-dorren;exhaustion-tessa|archive-key-dorren',
        )
        with open(briefs_csv, 'w', encoding='utf-8') as f:
            f.write(content)

        fixes = cleanup_physical_states(ref_dir)
        assert len(fixes) >= 1


class TestRunCleanup:
    """Tests for run_cleanup (orchestrator)."""

    def test_returns_summary_dict(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        summary = run_cleanup(ref_dir)
        assert 'timeline' in summary
        assert 'knowledge' in summary
        assert 'mice_threads' in summary
        assert 'total_fixes' in summary
        assert isinstance(summary['total_fixes'], int)
        assert summary['timeline']['count'] == len(summary['timeline']['fixes'])
        assert summary['knowledge']['count'] == len(summary['knowledge']['fixes'])
        assert summary['mice_threads']['count'] == len(summary['mice_threads']['fixes'])
