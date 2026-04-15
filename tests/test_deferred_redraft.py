"""Tests for deferred redrafting in revision pass execution."""

import os
import pytest


class TestDeferredRedraft:
    def test_collect_upstream_scenes(self):
        """_collect_upstream_scenes should gather all scenes from upstream passes."""
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'brief-fix-1', 'fix_location': 'brief',
             'targets': 's01;s02;s03', 'status': 'pending'},
            {'pass': '2', 'name': 'intent-fix', 'fix_location': 'intent',
             'targets': 's02;s04', 'status': 'pending'},
            {'pass': '3', 'name': 'craft-polish', 'fix_location': 'craft',
             'targets': 's01;s05', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        assert scenes == {'s01', 's02', 's03', 's04'}
        assert count == 2

    def test_no_upstream_passes_returns_empty(self):
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'craft', 'fix_location': 'craft',
             'targets': 's01', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        assert scenes == set()
        assert count == 0

    def test_skips_completed_passes(self):
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'brief-1', 'fix_location': 'brief',
             'targets': 's01', 'status': 'completed'},
            {'pass': '2', 'name': 'brief-2', 'fix_location': 'brief',
             'targets': 's02', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        assert scenes == {'s02'}
        assert count == 1

    def test_single_upstream_pass_still_defers(self):
        from storyforge.cmd_revise import _collect_upstream_scenes

        plan_rows = [
            {'pass': '1', 'name': 'brief-fix', 'fix_location': 'brief',
             'targets': 's01;s02', 'status': 'pending'},
            {'pass': '2', 'name': 'craft', 'fix_location': 'craft',
             'targets': '', 'status': 'pending'},
        ]

        scenes, count = _collect_upstream_scenes(plan_rows)
        assert scenes == {'s01', 's02'}
        assert count == 1
