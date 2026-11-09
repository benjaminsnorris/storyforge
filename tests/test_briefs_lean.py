"""Lean briefs and terse notes (#644, plan D3 and D4), the prompt side.

Every elaboration prompt asks for terse notes and forbids interpretation.
The craft-framework fields (value shift, turning point, scene ending) are
notes in the generation prompts, not mandates (deferred here by #643).
Drafting works when the optional columns are empty."""

import os

import pytest

from storyforge import prompts_elaborate as pe
from storyforge.elaborate import AUTHOR_NOTE_COLUMNS
from storyforge.prompts import build_scene_prompt_from_briefs

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMPTIED = AUTHOR_NOTE_COLUMNS + ('goal', 'conflict', 'crisis', 'decision')


def _set_cols(project_dir, filename, scene_id, **cols):
    path = os.path.join(project_dir, 'reference', filename)
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    header = lines[0].split('|')
    for i, line in enumerate(lines):
        cells = line.split('|')
        if cells[0] == scene_id:
            for col, value in cols.items():
                cells[header.index(col)] = value
            lines[i] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _fact_only(project_dir, scene_id='act1-sc02'):
    """The scene's brief as the briefs stage now writes it: no author notes,
    no craft notes; its intent without the craft-framework columns."""
    _set_cols(project_dir, 'scene-briefs.csv', scene_id, **{c: '' for c in EMPTIED})
    _set_cols(project_dir, 'scene-intent.csv', scene_id, value_shift='', emotional_arc='',
              value_at_stake='', turning_point='', action_sequel='')


# -- terse notes in every elaboration prompt ----------------------------------

@pytest.mark.parametrize('name, build', [
    ('spine', lambda p: pe.build_spine_prompt(p, PLUGIN, 'seed')),
    ('architecture', lambda p: pe.build_architecture_prompt(p, PLUGIN)),
    ('map', lambda p: pe.build_map_prompt(p, PLUGIN)),
    ('briefs', lambda p: pe.build_briefs_prompt(p, PLUGIN)),
    ('gap-fill', lambda p: pe.build_gap_fill_prompt(
        'act1-sc01', 'intent-fields', ['emotional_arc'], p, os.path.join(p, 'scenes'))),
])
def test_every_elaboration_prompt_asks_for_terse_notes(project_dir, name, build):
    prompt = build(project_dir)
    assert pe.NOTES_RULE in prompt
    assert 'No interpretation' in pe.NOTES_RULE
    assert 'Briseis is the sixth stud' in pe.NOTES_RULE


@pytest.mark.parametrize('build', [
    lambda p: pe.build_architecture_prompt(p, PLUGIN),
    lambda p: pe.build_map_prompt(p, PLUGIN),
])
def test_value_shifts_and_turns_are_notes_not_rules(project_dir, build):
    prompt = build(project_dir)
    for mandate in ('No flat polarity stretches', 'Vary scene types: no 4+',
                    'Vary turning point types', '(action or revelation — vary these)'):
        assert mandate not in prompt
    assert pe._CRAFT_NOTES in prompt
    assert 'not requirements' in pe._CRAFT_NOTES


def test_the_briefs_prompt_names_the_authors_notes_as_not_its_own(project_dir):
    prompt = pe.build_briefs_prompt(project_dir, PLUGIN)
    assert ('Not yours to write: key_dialogue, subtext, emotions, motifs. They are the '
            "author's optional notes") in prompt
    assert 'A motif is noticed in the draft and recorded after' in prompt
    assert 'optional notes. Fill one only when the scene plainly has it' in prompt


# -- drafting with the optional columns empty ---------------------------------

class TestDraftingAFactOnlyBrief:
    def test_no_empty_requirements(self, project_dir):
        _fact_only(project_dir)
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full')
        assert '()' not in p
        assert 'The value shift specified' not in p
        assert 'The emotional arc from' not in p
        assert '**Key dialogue' not in p
        assert 'SUBTEXT' not in p
        task = p.split('## Task', 1)[1]
        assert ('The brief is a plan of what happens. Hold to its facts:\n'
                '- The events in key_actions\n'
                '- The outcome: no-and\n'
                "- By the scene's end the POV character knows: "
                'village-vanished;archive-erasure\n') in task
        assert 'are notes, not requirements' in task

    def test_a_brief_with_no_facts_filled_still_builds(self, project_dir):
        _fact_only(project_dir)
        _set_cols(project_dir, 'scene-briefs.csv', 'act1-sc02', outcome='', key_actions='',
                  knowledge_out='')
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full')
        assert 'The brief is a plan of what happens.\nIts other fields' in p
        assert 'Hold to its facts' not in p

    def test_scene_endings_are_not_a_template(self, project_dir):
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full')
        assert 'choose ONE' not in p
        assert '**Scene ending:** no set shape.' in p
        # the closer Wrath's drafts fell into is still ruled out
        assert 'Do NOT close on a reflection, a thematic echo' in p

    def test_coach_mode_leaves_out_what_the_brief_lacks(self, project_dir):
        _fact_only(project_dir)
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'coach')
        task = p.split('## Task', 1)[1]
        assert '()' not in task
        for item in ('value shift', 'crisis/decision', 'key dialogue', 'emotional arc',
                     'scene type'):
            assert item not in task
        assert '- Pacing guidance' in task

    def test_a_dependency_shows_only_what_it_has(self, project_dir):
        _fact_only(project_dir, 'act1-sc01')
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full',
                                           dep_scenes=['act1-sc01'])
        dep = p.split('## Dependency Scenes', 1)[1].split('\n## ', 1)[0]
        assert 'emotional_arc' not in dep
        assert 'outcome: no-and' in dep

    def test_only_a_must_line_is_required(self, project_dir):
        """#642: only a `must:` line must be in the prose word for word; the
        author's other lines are notes."""
        _set_cols(project_dir, 'scene-briefs.csv', 'act1-sc02',
                  key_dialogue='must: "There is no note";"It was there forty years ago"')
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full')
        required = p.split('**Key dialogue checklist', 1)[1].split('\n\n', 1)[0]
        assert 'MUST appear in the scene word for word' in required
        assert '  - [ ] "There is no note"' in required
        assert 'forty years' not in required
        notes = p.split('**Key dialogue notes', 1)[1].split('\n\n', 1)[0]
        assert '  - "It was there forty years ago"' in notes


def test_a_brief_without_author_notes_is_complete(project_dir):
    """Structural completeness doesn't count the author's optional notes."""
    from storyforge import structural
    for col in AUTHOR_NOTE_COLUMNS:
        assert col not in structural.ENRICHMENT_FIELDS
        assert col not in structural.REQUIRED_FIELDS
