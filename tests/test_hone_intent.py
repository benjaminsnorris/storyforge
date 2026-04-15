"""Tests for intent quality detection in hone.py.

Covers all 6 detectors, the combined detector, and the fix prompt builder.
"""


# ============================================================================
# detect_vague_function
# ============================================================================

class TestDetectVagueFunction:
    def _make_intent(self, function_val):
        return {'test-scene': {'id': 'test-scene', 'function': function_val}}

    def test_flags_abstract_dominated_function(self):
        from storyforge.hone import detect_vague_function
        intent = self._make_intent(
            'Naji grapples with the choice, realizes the cost, and begins to understand the weight'
        )
        results = detect_vague_function(intent)
        assert len(results) == 1
        r = results[0]
        assert r['scene_id'] == 'test-scene'
        assert r['field'] == 'function'
        assert r['issue'] == 'vague'
        assert r['abstract_count'] >= 2
        assert r['abstract_count'] > r['concrete_count']

    def test_concrete_function_not_flagged(self):
        from storyforge.hone import detect_vague_function
        intent = self._make_intent(
            'Naji refuses the deal, confesses to Elara, and discovers the locked room'
        )
        results = detect_vague_function(intent)
        assert results == []

    def test_empty_function_skipped(self):
        from storyforge.hone import detect_vague_function
        intent = {'s1': {'id': 's1', 'function': ''}}
        results = detect_vague_function(intent)
        assert results == []

    def test_single_abstract_word_not_flagged(self):
        """Only 1 abstract indicator — threshold is >= 2."""
        from storyforge.hone import detect_vague_function
        intent = self._make_intent('Naji realizes she must leave and decides to go')
        results = detect_vague_function(intent)
        # 'realizes' = 1 abstract, 'decides' = 1 concrete — not flagged
        assert results == []

    def test_scene_ids_filter(self):
        from storyforge.hone import detect_vague_function
        intent = {
            'scene-a': {'id': 'scene-a', 'function': 'She grapples and connects and evolves'},
            'scene-b': {'id': 'scene-b', 'function': 'She grapples and connects and evolves'},
        }
        results = detect_vague_function(intent, scene_ids=['scene-a'])
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' not in ids

    def test_returns_value_in_result(self):
        from storyforge.hone import detect_vague_function
        val = 'She grapples with grief, reflects on loss, and begins to understand the truth'
        intent = {'s1': {'id': 's1', 'function': val}}
        results = detect_vague_function(intent)
        assert results[0]['value'] == val

    def test_abstract_equals_concrete_not_flagged(self):
        """Ties don't trigger: abstract_count must be strictly > concrete_count."""
        from storyforge.hone import detect_vague_function
        # 'grapples' + 'reflects' = 2 abstract; 'decides' + 'refuses' = 2 concrete
        intent = self._make_intent('She grapples with her fear and reflects, then decides and refuses')
        results = detect_vague_function(intent)
        # abstract_count (2) is NOT > concrete_count (2) — no flag
        assert results == []


# ============================================================================
# detect_overlong_function
# ============================================================================

class TestDetectOverlongFunction:
    def test_flags_function_over_400_chars(self):
        from storyforge.hone import detect_overlong_function
        long_val = 'A' * 401
        intent = {'s1': {'id': 's1', 'function': long_val}}
        results = detect_overlong_function(intent)
        assert len(results) == 1
        r = results[0]
        assert r['scene_id'] == 's1'
        assert r['field'] == 'function'
        assert r['char_count'] == 401
        assert r['issue'] == 'overlong'

    def test_exactly_400_chars_not_flagged(self):
        from storyforge.hone import detect_overlong_function
        val = 'A' * 400
        intent = {'s1': {'id': 's1', 'function': val}}
        results = detect_overlong_function(intent)
        assert results == []

    def test_short_function_not_flagged(self):
        from storyforge.hone import detect_overlong_function
        intent = {'s1': {'id': 's1', 'function': 'She decides to leave.'}}
        results = detect_overlong_function(intent)
        assert results == []

    def test_empty_function_skipped(self):
        from storyforge.hone import detect_overlong_function
        intent = {'s1': {'id': 's1', 'function': ''}}
        results = detect_overlong_function(intent)
        assert results == []

    def test_scene_ids_filter(self):
        from storyforge.hone import detect_overlong_function
        long_val = 'B' * 500
        intent = {
            'scene-a': {'id': 'scene-a', 'function': long_val},
            'scene-b': {'id': 'scene-b', 'function': long_val},
        }
        results = detect_overlong_function(intent, scene_ids=['scene-a'])
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' not in ids


# ============================================================================
# detect_flat_emotional_arc
# ============================================================================

class TestDetectFlatEmotionalArc:
    def _make_intent(self, arc_val):
        return {'s1': {'id': 's1', 'emotional_arc': arc_val}}

    def test_no_transition_flagged(self):
        from storyforge.hone import detect_flat_emotional_arc
        # "steady dread throughout" has no transition phrase
        intent = self._make_intent('steady dread throughout')
        results = detect_flat_emotional_arc(intent)
        assert len(results) == 1
        r = results[0]
        assert r['field'] == 'emotional_arc'
        assert r['issue'] == 'flat'

    def test_simple_x_to_y_passes(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent = self._make_intent('dread to relief')
        results = detect_flat_emotional_arc(intent)
        assert results == []

    def test_rich_transition_passes(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent = self._make_intent('cold resolve giving way to grief')
        results = detect_flat_emotional_arc(intent)
        assert results == []

    def test_breaking_into_passes(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent = self._make_intent('suppressed panic breaking into open rage')
        results = detect_flat_emotional_arc(intent)
        assert results == []

    def test_empty_field_skipped(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent = {'s1': {'id': 's1', 'emotional_arc': ''}}
        results = detect_flat_emotional_arc(intent)
        assert results == []

    def test_scene_ids_filter(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent = {
            'scene-a': {'id': 'scene-a', 'emotional_arc': 'steady dread'},
            'scene-b': {'id': 'scene-b', 'emotional_arc': 'steady dread'},
        }
        results = detect_flat_emotional_arc(intent, scene_ids=['scene-a'])
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' not in ids

    def test_becoming_transition_passes(self):
        from storyforge.hone import detect_flat_emotional_arc
        intent = self._make_intent('fear becoming resolve')
        results = detect_flat_emotional_arc(intent)
        assert results == []

    def test_returns_value(self):
        from storyforge.hone import detect_flat_emotional_arc
        val = 'static unease'
        intent = self._make_intent(val)
        results = detect_flat_emotional_arc(intent)
        assert results[0]['value'] == val


# ============================================================================
# detect_abstract_emotional_arc
# ============================================================================

class TestDetectAbstractEmotionalArc:
    def _make_intent(self, arc_val):
        return {'s1': {'id': 's1', 'emotional_arc': arc_val}}

    def test_flags_abstract_arc(self):
        from storyforge.hone import detect_abstract_emotional_arc
        # 'tension', 'turmoil' = 2 abstract; 0 grounded
        intent = self._make_intent('tension giving way to turmoil and inner struggle')
        results = detect_abstract_emotional_arc(intent)
        assert len(results) == 1
        r = results[0]
        assert r['field'] == 'emotional_arc'
        assert r['issue'] == 'abstract_arc'
        assert r['abstract_count'] >= 2
        assert r['abstract_count'] > r['concrete_count']

    def test_grounded_arc_not_flagged(self):
        from storyforge.hone import detect_abstract_emotional_arc
        intent = self._make_intent('grief giving way to resolve')
        results = detect_abstract_emotional_arc(intent)
        assert results == []

    def test_empty_field_skipped(self):
        from storyforge.hone import detect_abstract_emotional_arc
        intent = {'s1': {'id': 's1', 'emotional_arc': ''}}
        results = detect_abstract_emotional_arc(intent)
        assert results == []

    def test_single_abstract_word_not_flagged(self):
        """Only 1 abstract word — threshold is >= 2."""
        from storyforge.hone import detect_abstract_emotional_arc
        intent = self._make_intent('tension giving way to grief')
        results = detect_abstract_emotional_arc(intent)
        # 'tension' = 1 abstract; 'grief' = 1 grounded — not flagged
        assert results == []

    def test_mixed_abstract_and_grounded(self):
        """2 abstract + 2 grounded: abstract_count not > concrete_count — no flag."""
        from storyforge.hone import detect_abstract_emotional_arc
        intent = self._make_intent('tension and turmoil giving way to grief and dread')
        results = detect_abstract_emotional_arc(intent)
        # 2 abstract, 2 grounded — tie, no flag
        assert results == []

    def test_scene_ids_filter(self):
        from storyforge.hone import detect_abstract_emotional_arc
        intent = {
            'scene-a': {'id': 'scene-a', 'emotional_arc': 'tension to turmoil and struggle'},
            'scene-b': {'id': 'scene-b', 'emotional_arc': 'tension to turmoil and struggle'},
        }
        results = detect_abstract_emotional_arc(intent, scene_ids=['scene-a'])
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' not in ids


# ============================================================================
# detect_onstage_subset_violation
# ============================================================================

class TestDetectOnstageSubsetViolation:
    def _make_intent(self, characters, on_stage):
        return {
            's1': {
                'id': 's1',
                'characters': characters,
                'on_stage': on_stage,
            }
        }

    def test_flags_on_stage_not_in_characters(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent('alice;bob', 'alice;charlie')
        results = detect_onstage_subset_violation(intent)
        assert len(results) == 1
        r = results[0]
        assert r['field'] == 'on_stage'
        assert r['issue'] == 'not_subset'
        assert 'charlie' in r['violating']

    def test_valid_subset_not_flagged(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent('alice;bob;charlie', 'alice;bob')
        results = detect_onstage_subset_violation(intent)
        assert results == []

    def test_exact_match_not_flagged(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent('alice;bob', 'alice;bob')
        results = detect_onstage_subset_violation(intent)
        assert results == []

    def test_empty_on_stage_skipped(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent('alice;bob', '')
        results = detect_onstage_subset_violation(intent)
        assert results == []

    def test_case_insensitive_comparison(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent('Alice;Bob', 'alice;bob')
        results = detect_onstage_subset_violation(intent)
        assert results == []

    def test_whitespace_stripped(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent(' alice ; bob ', ' alice ')
        results = detect_onstage_subset_violation(intent)
        assert results == []

    def test_multiple_violations_in_violating_list(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent('alice', 'alice;bob;charlie')
        results = detect_onstage_subset_violation(intent)
        assert len(results) == 1
        assert 'bob' in results[0]['violating']
        assert 'charlie' in results[0]['violating']

    def test_scene_ids_filter(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = {
            'scene-a': {'id': 'scene-a', 'characters': 'alice', 'on_stage': 'alice;bob'},
            'scene-b': {'id': 'scene-b', 'characters': 'alice', 'on_stage': 'alice;bob'},
        }
        results = detect_onstage_subset_violation(intent, scene_ids=['scene-a'])
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' not in ids

    def test_violating_is_sorted(self):
        from storyforge.hone import detect_onstage_subset_violation
        intent = self._make_intent('alice', 'charlie;alice;bob')
        results = detect_onstage_subset_violation(intent)
        assert results[0]['violating'] == sorted(results[0]['violating'])


# ============================================================================
# detect_value_shift_outcome_mismatch
# ============================================================================

class TestDetectValueShiftOutcomeMismatch:
    def _make_maps(self, value_shift, outcome):
        intent = {'s1': {'id': 's1', 'value_shift': value_shift}}
        briefs = {'s1': {'id': 's1', 'outcome': outcome}}
        return intent, briefs

    def test_yes_outcome_negative_shift_flagged(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/-', 'yes')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert len(results) == 1
        r = results[0]
        assert r['field'] == 'value_shift'
        assert r['issue'] == 'outcome_mismatch'
        assert r['outcome'] == 'yes'

    def test_yes_outcome_double_negative_shift_flagged(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/--', 'yes')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert len(results) == 1

    def test_yes_outcome_positive_shift_not_flagged(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/+', 'yes')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_no_outcome_positive_shift_flagged(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('-/+', 'no')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert len(results) == 1
        r = results[0]
        assert r['outcome'] == 'no'
        assert r['issue'] == 'outcome_mismatch'

    def test_no_outcome_negative_shift_not_flagged(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/-', 'no')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_yes_but_skipped(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/-', 'yes-but')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_no_and_skipped(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('-/+', 'no-and')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_empty_value_shift_skipped(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('', 'yes')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_empty_outcome_skipped(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/-', '')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_scene_ids_filter(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent = {
            'scene-a': {'id': 'scene-a', 'value_shift': '+/-'},
            'scene-b': {'id': 'scene-b', 'value_shift': '+/-'},
        }
        briefs = {
            'scene-a': {'id': 'scene-a', 'outcome': 'yes'},
            'scene-b': {'id': 'scene-b', 'outcome': 'yes'},
        }
        results = detect_value_shift_outcome_mismatch(intent, briefs, scene_ids=['scene-a'])
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' not in ids

    def test_result_includes_value_shift_and_outcome(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/-', 'yes')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        r = results[0]
        assert r['value_shift'] == '+/-'
        assert r['outcome'] == 'yes'
        assert r['value'] == '+/-'

    def test_missing_brief_row_skipped(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent = {'s1': {'id': 's1', 'value_shift': '+/-'}}
        briefs = {}  # no entry
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_yes_double_positive_shift_not_flagged(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('-/++', 'yes')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []

    def test_no_double_negative_shift_not_flagged(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent, briefs = self._make_maps('+/--', 'no')
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert results == []


# ============================================================================
# detect_intent_issues (combined)
# ============================================================================

class TestDetectIntentIssues:
    def test_combines_all_detectors(self):
        """A scene with every type of issue should trigger all detectors."""
        from storyforge.hone import detect_intent_issues

        # function: vague (grapples/reflects/evolves = 3 abstract, 0 concrete)
        # emotional_arc: flat (no transition) AND abstract (tension/turmoil/struggle = 3)
        # on_stage: not subset (charlie not in characters)
        # value_shift/outcome: mismatch (yes + negative shift)
        intent = {
            's1': {
                'id': 's1',
                'function': 'She grapples with the choice and reflects deeply and evolves through the experience',
                'emotional_arc': 'tension and turmoil and struggle',
                'characters': 'alice;bob',
                'on_stage': 'alice;charlie',
                'value_shift': '+/-',
            }
        }
        briefs = {'s1': {'id': 's1', 'outcome': 'yes'}}
        scenes = {'s1': {'id': 's1'}}

        issues = detect_intent_issues(intent, scenes, briefs)
        issue_types = {i['issue'] for i in issues}

        assert 'vague' in issue_types
        assert 'flat' in issue_types
        assert 'abstract_arc' in issue_types
        assert 'not_subset' in issue_types
        assert 'outcome_mismatch' in issue_types

    def test_clean_data_returns_empty(self):
        from storyforge.hone import detect_intent_issues
        intent = {
            's1': {
                'id': 's1',
                'function': 'Naji refuses the deal and confesses to Elara',
                'emotional_arc': 'dread giving way to resolve',
                'characters': 'naji;elara',
                'on_stage': 'naji;elara',
                'value_shift': '+/+',
            }
        }
        briefs = {'s1': {'id': 's1', 'outcome': 'yes'}}
        scenes = {'s1': {'id': 's1'}}
        issues = detect_intent_issues(intent, scenes, briefs)
        assert issues == []

    def test_results_sorted_by_scene_field_issue(self):
        from storyforge.hone import detect_intent_issues
        intent = {
            'b-scene': {
                'id': 'b-scene',
                'function': 'She grapples and reflects and evolves',
                'emotional_arc': 'tension and turmoil and struggle',
                'characters': '',
                'on_stage': '',
                'value_shift': '',
            },
            'a-scene': {
                'id': 'a-scene',
                'function': 'She grapples and reflects and evolves',
                'emotional_arc': 'tension and turmoil and struggle',
                'characters': '',
                'on_stage': '',
                'value_shift': '',
            },
        }
        briefs = {
            'a-scene': {'id': 'a-scene', 'outcome': ''},
            'b-scene': {'id': 'b-scene', 'outcome': ''},
        }
        scenes = {'a-scene': {'id': 'a-scene'}, 'b-scene': {'id': 'b-scene'}}
        issues = detect_intent_issues(intent, scenes, briefs)
        keys = [(i['scene_id'], i['field'], i['issue']) for i in issues]
        assert keys == sorted(keys)

    def test_scene_ids_filter_propagated(self):
        from storyforge.hone import detect_intent_issues
        intent = {
            'scene-a': {'id': 'scene-a', 'function': 'She grapples and reflects and evolves',
                        'emotional_arc': '', 'characters': '', 'on_stage': '', 'value_shift': ''},
            'scene-b': {'id': 'scene-b', 'function': 'She grapples and reflects and evolves',
                        'emotional_arc': '', 'characters': '', 'on_stage': '', 'value_shift': ''},
        }
        briefs = {
            'scene-a': {'id': 'scene-a', 'outcome': ''},
            'scene-b': {'id': 'scene-b', 'outcome': ''},
        }
        scenes = {'scene-a': {'id': 'scene-a'}, 'scene-b': {'id': 'scene-b'}}
        issues = detect_intent_issues(intent, scenes, briefs, scene_ids=['scene-a'])
        ids = {i['scene_id'] for i in issues}
        assert 'scene-a' in ids
        assert 'scene-b' not in ids

    def test_overlong_function_included(self):
        from storyforge.hone import detect_intent_issues
        intent = {
            's1': {
                'id': 's1',
                'function': 'X' * 401,
                'emotional_arc': '',
                'characters': '',
                'on_stage': '',
                'value_shift': '',
            }
        }
        briefs = {'s1': {'id': 's1', 'outcome': ''}}
        scenes = {'s1': {'id': 's1'}}
        issues = detect_intent_issues(intent, scenes, briefs)
        issue_types = {i['issue'] for i in issues}
        assert 'overlong' in issue_types


# ============================================================================
# build_intent_fix_prompt
# ============================================================================

class TestBuildIntentFixPrompt:
    def test_includes_scene_id(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='mirror-scene',
            fields=['function'],
            current_values={'function': 'She grapples and reflects'},
            issues=[{'field': 'function', 'issue': 'vague'}],
        )
        assert 'mirror-scene' in prompt

    def test_includes_field_value(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['function'],
            current_values={'function': 'She grapples and reflects'},
            issues=[{'field': 'function', 'issue': 'vague'}],
        )
        assert 'She grapples and reflects' in prompt

    def test_vague_instructions_included(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['function'],
            current_values={'function': 'She grapples'},
            issues=[{'field': 'function', 'issue': 'vague'}],
        )
        assert 'testable actions' in prompt

    def test_overlong_instructions_included(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['function'],
            current_values={'function': 'X' * 401},
            issues=[{'field': 'function', 'issue': 'overlong'}],
        )
        assert '1-3 sentences' in prompt

    def test_flat_arc_instructions_included(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['emotional_arc'],
            current_values={'emotional_arc': 'static dread'},
            issues=[{'field': 'emotional_arc', 'issue': 'flat'}],
        )
        assert 'giving way to' in prompt

    def test_abstract_arc_instructions_included(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['emotional_arc'],
            current_values={'emotional_arc': 'tension to turmoil'},
            issues=[{'field': 'emotional_arc', 'issue': 'abstract_arc'}],
        )
        assert 'grounded' in prompt.lower() or 'grief' in prompt

    def test_output_format_labels_match_fields(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['function', 'emotional_arc'],
            current_values={
                'function': 'She grapples',
                'emotional_arc': 'static dread',
            },
            issues=[
                {'field': 'function', 'issue': 'vague'},
                {'field': 'emotional_arc', 'issue': 'flat'},
            ],
        )
        # Both fields should appear in the output format section
        assert 'function: [rewritten value]' in prompt
        assert 'emotional_arc: [rewritten value]' in prompt

    def test_parseable_by_parse_concretize_response(self):
        """Verify the output format is compatible with the existing parser."""
        from storyforge.hone import build_intent_fix_prompt, parse_concretize_response
        fields = ['function', 'emotional_arc']
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=fields,
            current_values={
                'function': 'She grapples with it',
                'emotional_arc': 'static tension',
            },
            issues=[
                {'field': 'function', 'issue': 'vague'},
                {'field': 'emotional_arc', 'issue': 'flat'},
            ],
        )
        # Simulate a response from Claude
        fake_response = (
            'function: She confesses the plan to Elara\n'
            'emotional_arc: dread giving way to resolve'
        )
        result = parse_concretize_response(fake_response, 's1', fields)
        assert 'function' in result
        assert 'emotional_arc' in result
        assert 'confesses' in result['function']
        assert 'resolve' in result['emotional_arc']

    def test_voice_guide_included_when_provided(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['function'],
            current_values={'function': 'She grapples'},
            issues=[{'field': 'function', 'issue': 'vague'}],
            voice_guide='She thinks in metallic tastes and copper-penny sounds.',
        )
        assert 'copper-penny' in prompt

    def test_no_voice_guide_shows_not_available(self):
        from storyforge.hone import build_intent_fix_prompt
        prompt = build_intent_fix_prompt(
            scene_id='s1',
            fields=['function'],
            current_values={'function': 'She grapples'},
            issues=[{'field': 'function', 'issue': 'vague'}],
        )
        assert 'not available' in prompt


# ============================================================================
# hone_intent()
# ============================================================================

import os
import inspect


class TestHoneIntentSignature:
    def test_accepts_expected_params(self):
        from storyforge.hone import hone_intent
        sig = inspect.signature(hone_intent)
        params = list(sig.parameters.keys())
        assert 'ref_dir' in params
        assert 'project_dir' in params
        assert 'scene_ids' in params
        assert 'findings_file' in params
        assert 'model' in params
        assert 'log_dir' in params
        assert 'coaching_level' in params
        assert 'dry_run' in params

    def test_returns_result_dict_dry_run(self, tmp_path):
        """Dry run with no data should return zeroed stats."""
        from storyforge.hone import hone_intent
        # Create minimal intent CSV
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        (ref_dir / 'scene-intent.csv').write_text(
            'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n'
            'scene-a|She realizes and connects and transforms|action|tension|truth|+/-|action|kael|kael|\n'
        )
        (ref_dir / 'scenes.csv').write_text('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\nscene-a|1|Test|1|kael|here|1|morning|short|action|drafted|1000|1500\n')
        result = hone_intent(
            ref_dir=str(ref_dir),
            project_dir=str(tmp_path),
            dry_run=True,
        )
        assert 'scenes_flagged' in result
        assert 'scenes_rewritten' in result
        assert 'fields_rewritten' in result
        assert result['scenes_flagged'] >= 1  # should detect vague function
        assert result['scenes_rewritten'] == 0  # dry run

    def test_missing_intent_file(self, tmp_path):
        from storyforge.hone import hone_intent
        result = hone_intent(
            ref_dir=str(tmp_path),
            project_dir=str(tmp_path),
        )
        assert result == {'scenes_flagged': 0, 'scenes_rewritten': 0, 'fields_rewritten': 0}

    def test_deterministic_subset_fix_adds_to_characters(self, tmp_path):
        """Regression: not_subset fix should add missing on_stage chars to characters,
        not remove them from on_stage. character_presence rewards on_stage presence."""
        from storyforge.hone import hone_intent
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        (ref_dir / 'scene-intent.csv').write_text(
            'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n'
            'scene-a|Kael reads the letter and refuses|action|dread giving way to resolve|truth|-/+|action|kael;sera|kael;sera;bren|\n'
        )
        (ref_dir / 'scenes.csv').write_text('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\nscene-a|1|Test|1|kael|here|1|morning|short|action|drafted|1000|1500\n')
        os.makedirs(str(tmp_path / 'working' / 'logs'), exist_ok=True)
        result = hone_intent(
            ref_dir=str(ref_dir),
            project_dir=str(tmp_path),
            log_dir=str(tmp_path / 'working' / 'logs'),
            coaching_level='strict',  # strict = no API calls, but deterministic fixes still apply
        )
        assert result['fields_rewritten'] >= 1
        # Verify: bren was ADDED to characters (not removed from on_stage)
        updated = _read_csv_as_map(str(ref_dir / 'scene-intent.csv'))
        characters = updated['scene-a']['characters']
        on_stage = updated['scene-a']['on_stage']
        # on_stage should be unchanged — bren should still be there
        assert 'bren' in on_stage.lower()
        assert 'kael' in on_stage.lower()
        assert 'sera' in on_stage.lower()
        # characters should now include bren
        assert 'bren' in characters.lower()
        assert 'kael' in characters.lower()
        assert 'sera' in characters.lower()

    def test_not_subset_fix_preserves_existing_characters(self, tmp_path):
        """The fix should preserve all existing characters when adding new ones."""
        from storyforge.hone import hone_intent
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        (ref_dir / 'scene-intent.csv').write_text(
            'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n'
            'scene-a|Kael reads the letter|action|dread|truth|-/+|action|kael;sera;dana|kael;sera;bren;tomas|\n'
        )
        (ref_dir / 'scenes.csv').write_text('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\nscene-a|1|Test|1|kael|here|1|morning|short|action|drafted|1000|1500\n')
        os.makedirs(str(tmp_path / 'working' / 'logs'), exist_ok=True)
        result = hone_intent(
            ref_dir=str(ref_dir),
            project_dir=str(tmp_path),
            log_dir=str(tmp_path / 'working' / 'logs'),
            coaching_level='strict',
        )
        assert result['fields_rewritten'] >= 1
        updated = _read_csv_as_map(str(ref_dir / 'scene-intent.csv'))
        characters = updated['scene-a']['characters']
        chars_list = [c.strip().lower() for c in characters.split(';')]
        # All original characters preserved
        assert 'kael' in chars_list
        assert 'sera' in chars_list
        assert 'dana' in chars_list
        # Missing on_stage chars added
        assert 'bren' in chars_list
        assert 'tomas' in chars_list
