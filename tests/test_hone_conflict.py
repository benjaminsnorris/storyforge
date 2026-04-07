"""Tests for conflict-free brief detection in hone."""


class TestDetectConflictFree:
    def _make_briefs(self, conflict_val, outcome='no'):
        return {
            'test-scene': {
                'id': 'test-scene',
                'conflict': conflict_val,
                'outcome': outcome,
            }
        }

    def _make_intent(self, value_shift=''):
        return {
            'test-scene': {
                'id': 'test-scene',
                'value_shift': value_shift,
            }
        }

    # ---- keyword checks ----

    def test_observation_only_flagged(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She notices the door is locked and realizes she is trapped')
        intent = self._make_intent('+/-')
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 1
        r = results[0]
        assert r['scene_id'] == 'test-scene'
        assert r['field'] == 'conflict'
        assert r['issue'] == 'conflict_free'
        assert r['reason'] in ('keyword', 'both')
        assert r['observation_count'] >= 1
        assert r['opposition_count'] == 0

    def test_opposition_present_not_flagged_keyword(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She refuses to leave; he blocks the exit')
        intent = self._make_intent('+/-')
        results = detect_conflict_free(briefs, intent)
        assert results == []

    def test_mixed_observation_and_opposition_not_flagged(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She notices the danger but he blocks her escape')
        intent = self._make_intent('+/-')
        results = detect_conflict_free(briefs, intent)
        assert results == []

    # ---- structural checks ----

    def test_outcome_yes_flat_shift_flagged(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She solves the problem quickly', outcome='yes')
        intent = self._make_intent('+/+')
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 1
        r = results[0]
        assert r['issue'] == 'conflict_free'
        assert r['reason'] in ('structural', 'both')
        assert r['outcome'] == 'yes'
        assert r['value_shift'] == '+/+'

    def test_outcome_yes_empty_shift_flagged(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She finishes the task', outcome='yes')
        intent = self._make_intent('')
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 1
        assert results[0]['reason'] in ('structural', 'both')

    def test_outcome_no_not_flagged_structurally(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She tries but fails', outcome='no')
        intent = self._make_intent('+/+')
        results = detect_conflict_free(briefs, intent)
        assert results == []

    def test_outcome_no_flat_shift_not_flagged_structurally(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She tries but fails', outcome='no')
        intent = self._make_intent('-/-')
        results = detect_conflict_free(briefs, intent)
        assert results == []

    def test_outcome_yes_non_flat_shift_not_flagged_structurally(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She overcomes the guard', outcome='yes')
        intent = self._make_intent('+/-')
        results = detect_conflict_free(briefs, intent)
        assert results == []

    # ---- empty conflict not flagged ----

    def test_empty_conflict_not_flagged(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('')
        intent = self._make_intent('+/+')
        results = detect_conflict_free(briefs, intent)
        assert results == []

    # ---- reason='both' ----

    def test_both_keyword_and_structural_gives_reason_both(self):
        from storyforge.hone import detect_conflict_free
        briefs = self._make_briefs('She notices the pattern and realizes the truth', outcome='yes')
        intent = self._make_intent('+/+')
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 1
        assert results[0]['reason'] == 'both'

    # ---- scene filter ----

    def test_scene_filter_limits_scope(self):
        from storyforge.hone import detect_conflict_free
        briefs = {
            'scene-a': {'id': 'scene-a', 'conflict': 'She notices the silence', 'outcome': 'no'},
            'scene-b': {'id': 'scene-b', 'conflict': 'She notices the fire', 'outcome': 'no'},
        }
        intent = {
            'scene-a': {'id': 'scene-a', 'value_shift': '+/-'},
            'scene-b': {'id': 'scene-b', 'value_shift': '+/-'},
        }
        results = detect_conflict_free(briefs, intent, scene_ids=['scene-a'])
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' not in ids

    def test_scene_filter_none_checks_all(self):
        from storyforge.hone import detect_conflict_free
        briefs = {
            'scene-a': {'id': 'scene-a', 'conflict': 'She notices the silence', 'outcome': 'no'},
            'scene-b': {'id': 'scene-b', 'conflict': 'She observes the ruins', 'outcome': 'no'},
        }
        intent = {
            'scene-a': {'id': 'scene-a', 'value_shift': '+/-'},
            'scene-b': {'id': 'scene-b', 'value_shift': '+/-'},
        }
        results = detect_conflict_free(briefs, intent)
        ids = [r['scene_id'] for r in results]
        assert 'scene-a' in ids
        assert 'scene-b' in ids

    # ---- missing intent entry doesn't crash ----

    def test_missing_intent_entry_skips_structural(self):
        from storyforge.hone import detect_conflict_free
        briefs = {'test-scene': {'id': 'test-scene', 'conflict': 'She notices the danger', 'outcome': 'yes'}}
        intent = {}  # no entry for test-scene
        # Should not crash; structural check is skipped or uses empty value_shift
        results = detect_conflict_free(briefs, intent)
        # Either flags keyword or structural (empty shift), but doesn't raise
        assert isinstance(results, list)


class TestDetectBriefIssuesIntegration:
    """Verify detect_brief_issues wires through conflict_free when intent_map provided."""

    def test_no_intent_map_skips_conflict_free(self):
        from storyforge.hone import detect_brief_issues
        briefs = {
            's': {'id': 's', 'conflict': 'She notices the silence', 'outcome': 'no',
                  'key_actions': '', 'emotions': '', 'goal': '', 'decision': '',
                  'crisis': '', 'subtext': ''},
        }
        scenes = {'s': {'id': 's', 'target_words': '1000'}}
        issues = detect_brief_issues(briefs, scenes)
        types = [i['issue'] for i in issues]
        assert 'conflict_free' not in types

    def test_intent_map_enables_conflict_free(self):
        from storyforge.hone import detect_brief_issues
        briefs = {
            's': {'id': 's', 'conflict': 'She notices the silence', 'outcome': 'no',
                  'key_actions': '', 'emotions': '', 'goal': '', 'decision': '',
                  'crisis': '', 'subtext': ''},
        }
        scenes = {'s': {'id': 's', 'target_words': '1000'}}
        intent = {'s': {'id': 's', 'value_shift': '+/-'}}
        issues = detect_brief_issues(briefs, scenes, intent_map=intent)
        types = [i['issue'] for i in issues]
        assert 'conflict_free' in types
