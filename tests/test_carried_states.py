"""F-149 and F-150: a state the brief carries in and out unchanged is
continuity, not something the scene must put on the page again; and where
the brief has a character do what a carried state rules out, the brief
wins.

Drafting Quintus Book VIII restated Neoptolemus's honour-gifts (gold,
silver, handmaids, jars of wine) in 7 of 10 scenes, because every carried
state was a must-show item, and the checker held the scene to each as a
promise. Aeneas "has withdrawn from the fight" yet the brief has him kill
two men: the draft invented a left-handed throw to fit both."""

import os

from storyforge import checker
from storyforge.elaborate import update_scene
from storyforge.prompts import build_scene_prompt_from_briefs

SCENE = 'act1-sc02'


def _carry(project_dir, state_in, state_out):
    update_scene(SCENE, os.path.join(project_dir, 'reference'),
                 {'physical_state_in': state_in, 'physical_state_out': state_out})


def _checklist(prompt):
    task = prompt[prompt.index('## Task'):]
    if 'Physical states checklist' not in task:
        return ''
    return task[task.index('Physical states checklist'):].split('**Prose rules')[0]


class TestDraftingPrompt:
    def test_a_carried_state_is_not_a_must_show_item(self, project_dir, plugin_dir):
        # archive-key-dorren enters and leaves the scene; exhaustion-tessa is new
        _carry(project_dir, 'archive-key-dorren', 'archive-key-dorren;exhaustion-tessa')
        prompt = build_scene_prompt_from_briefs(SCENE, project_dir, plugin_dir)
        checklist = _checklist(prompt)
        assert checklist.count('- [ ]') == 1
        assert 'even when it carries over' not in prompt
        # still in the prompt, as continuity
        states = prompt[prompt.index('## Active Physical States'):]
        assert states.count('- **') >= 1

    def test_a_carried_state_matches_by_alias_and_case(self, project_dir, plugin_dir):
        _carry(project_dir, 'ARCHIVE-KEY-DORREN', 'archive-key-dorren')
        prompt = build_scene_prompt_from_briefs(SCENE, project_dir, plugin_dir)
        assert _checklist(prompt) == ''

    def test_a_state_in_words_carried_over_is_not_listed(self, project_dir, plugin_dir):
        _carry(project_dir, 'no sleep 36h', 'no sleep 36h;bruised ribs')
        checklist = _checklist(build_scene_prompt_from_briefs(SCENE, project_dir, plugin_dir))
        assert '- [ ] bruised ribs' in checklist and 'no sleep 36h' not in checklist

    def test_carried_states_are_kept_true_not_restated(self, project_dir, plugin_dir):
        _carry(project_dir, 'archive-key-dorren', 'archive-key-dorren')
        prompt = build_scene_prompt_from_briefs(SCENE, project_dir, plugin_dir)
        states = prompt[prompt.index('## Active Physical States'):]
        assert "Don't restate them for their own sake" in states

    def test_the_brief_wins_over_a_carried_state(self, project_dir, plugin_dir):
        """F-150."""
        _carry(project_dir, 'archive-key-dorren', 'archive-key-dorren')
        prompt = build_scene_prompt_from_briefs(SCENE, project_dir, plugin_dir)
        states = prompt[prompt.index('## Active Physical States'):]
        assert 'the brief wins' in states and "don't invent a way around it" in states
        assert 'unless the brief has them do it' in prompt


class TestChecker:
    def test_a_carried_state_holds_entering_and_is_not_a_promise(self, project_dir):
        _carry(project_dir, 'archive-key-dorren', 'archive-key-dorren;exhaustion-tessa')
        book = checker.Book.load(project_dir, SCENE)
        brief = checker._brief(book, project_dir, SCENE)
        entering, promises = brief.text.split("## The brief's promises")
        assert 'archive-key-dorren' in entering and 'archive-key-dorren' not in promises
        assert 'archive-key-dorren' not in brief.promised
        assert 'exhaustion-tessa' in brief.promised

    def test_a_state_the_brief_overrides_is_not_a_contradiction(self, project_dir):
        """F-150."""
        _carry(project_dir, 'archive-key-dorren', 'archive-key-dorren')
        book = checker.Book.load(project_dir, SCENE)
        brief = checker._brief(book, project_dir, SCENE)
        assert 'ended before the scene: that is not a contradiction' in brief.text
