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
                if col in header:     # motif_details isn't in the fixture's header
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


def test_the_notes_rule_is_scoped_to_scene_rows(project_dir):
    """#644's review CR-2: the spine prompt asks for a theme and a Lie vs.
    Need; "no interpretation" covers the scene rows, and the architecture
    and bible documents are named as where those belong."""
    assert "Write every scene row's cells (the CSV blocks)" in pe.NOTES_RULE
    assert 'No interpretation in a scene row' in pe.NOTES_RULE
    assert ('The story architecture and the character and world bibles are where a theme, '
            'a want, a need, a wound or a lie belongs') in pe.NOTES_RULE
    spine = pe.build_spine_prompt(project_dir, PLUGIN, 'seed')
    assert '(Lie vs. Need)' in spine and pe.NOTES_RULE in spine


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
    assert ('Not yours to write: goal, conflict, crisis, decision, key_dialogue, subtext, '
            'emotions, motifs, motif_details. They are the '
            "author's optional notes") in prompt
    assert 'A motif is noticed in the draft and recorded after' in prompt


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
        assert ('The brief is a plan of what happens. It lists no events (key_actions is '
                'empty)') in p
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

    def test_the_authors_notes_still_reach_the_drafter(self, project_dir):
        """#644's review T3: notes the author fills go to drafting (subtext
        under its show-never-tell framing), and none of them is a fact the
        scene is held to."""
        _set_cols(project_dir, 'scene-briefs.csv', 'act1-sc02',
                  subtext='Dorren says the archive is complete but means it was purged',
                  emotions='routine;dread', motifs='maps/cartography')
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full')
        assert ('**SUBTEXT (show, never tell):** Dorren says the archive is complete but '
                'means it was purged') in p
        assert 'routine;dread' in p and 'maps/cartography' in p
        facts = p.split('## Task', 1)[1].split('Hold to its facts:', 1)[1].split(
            'Its other fields', 1)[0]
        for note in ('purged', 'routine;dread', 'maps/cartography'):
            assert note not in facts

    def test_coach_mode_names_what_the_brief_has(self, project_dir):
        """#644's review T4: the other half of the coach test, on the
        fixture's full brief."""
        p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'coach')
        task = p.split('## Task', 1)[1]
        assert '- Craft reminders relevant to the scene type (sequel)' in task
        assert '- How the value shift noted in the brief (-/--) might land' in task
        assert '- Suggested approach for the crisis/decision moment' in task
        assert '- Line-level suggestions for key dialogue' in task
        assert '- Pacing guidance given the emotional arc' in task

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


def test_a_fact_only_brief_is_complete(project_dir):
    """#644's review T1, CR-5, TD-5, C3: structural completeness counts the
    brief's facts. A brief the briefs stage writes (no author notes, no craft
    notes) has no "Missing required fields" finding; its empty craft notes
    are one advisory finding that carries no weight, and its empty author
    notes (goal, conflict, crisis, decision since plan decision 9) none."""
    from storyforge import structural
    from storyforge.elaborate import BRIEF_FACT_COLUMNS, _read_csv_as_map
    _fact_only(project_dir)
    ref = os.path.join(project_dir, 'reference')
    maps = [_read_csv_as_map(os.path.join(ref, f))
            for f in ('scenes.csv', 'scene-intent.csv', 'scene-briefs.csv')]
    result = structural.score_completeness(*maps)
    mine = [f for f in result['findings'] if f['scene_id'] == 'act1-sc02']
    assert not [f for f in mine if f['message'].startswith('Missing required fields')]
    [craft] = [f for f in mine if f.get('advisory')]
    assert craft['severity'] == 'minor'
    assert 'value_shift' in craft['fields']
    assert not set(craft['fields']) & {'goal', 'conflict', 'crisis', 'decision'}
    for col in AUTHOR_NOTE_COLUMNS:
        assert col not in structural.ENRICHMENT_FIELDS + structural.REQUIRED_FIELDS
    assert set(BRIEF_FACT_COLUMNS) <= set(structural.REQUIRED_FIELDS)
    # an empty key_actions is a missing required field
    _set_cols(project_dir, 'scene-briefs.csv', 'act1-sc02', key_actions='')
    maps[2] = _read_csv_as_map(os.path.join(ref, 'scene-briefs.csv'))
    missing = [f for f in structural.score_completeness(*maps)['findings']
               if f['scene_id'] == 'act1-sc02' and f['message'].startswith('Missing required')]
    assert missing[0]['fields'] == ['key_actions']


def test_the_outcome_is_worded_for_a_scene_without_a_goal(project_dir):
    """#644's review CR-6 (and #643's CR-3), plan decision 9: outcome stays
    required, and is judged by what the POV character is trying to do, never
    against a goal (the briefs stage writes none)."""
    prompt = pe.build_briefs_prompt(project_dir, PLUGIN)
    assert 'judged by what they are trying to do or hoping for in the scene' in prompt
    assert 'yes (it goes their way)' in prompt


def test_gap_fill_may_leave_a_craft_note_empty(project_dir):
    """#644's review CR-5: gap-fill no longer forces a value into a craft
    note the scene doesn't have; a fact field gets no such allowance."""
    p = pe.build_gap_fill_prompt('act1-sc01', 'g', ['value_shift', 'turning_point', 'location'],
                                 project_dir, os.path.join(project_dir, 'scenes'))
    assert ('value_shift, turning_point: craft-framework notes, not requirements. Fill one '
            'only when the scene plainly has it; otherwise leave its cell empty') in p
    p = pe.build_gap_fill_prompt('act1-sc01', 'g', ['location'], project_dir,
                                 os.path.join(project_dir, 'scenes'))
    assert 'craft-framework notes' not in p


def test_brief_fidelity_scores_a_brief_without_a_goal(project_dir):
    """#644's review TD-6: goal is optional, so a fact-only brief is still
    scored; only a brief with no fact and no goal is skipped."""
    from storyforge.scoring import build_fidelity_prompt, has_brief_facts
    _fact_only(project_dir)
    assert build_fidelity_prompt('act1-sc02', project_dir, PLUGIN)
    assert has_brief_facts({'key_actions': 'x'}) and has_brief_facts({'goal': 'g'})
    assert not has_brief_facts({'subtext': 's', 'emotions': 'e'})


# -- no model rewrites the author's notes (#644's review TD-2, CR-3, SF-3/4) ---

def test_hone_reports_an_authors_emotions_without_rewriting_them(project_dir, monkeypatch,
                                                                 capsys):
    """act1-sc02's four emotion beats are over hone's limit; they are the
    author's, so hone says so and no model call rewrites them."""
    from storyforge import api
    from storyforge.hone import hone_briefs
    calls = []
    monkeypatch.setattr(api, 'invoke_to_file', lambda prompt, *a, **kw: calls.append(prompt))
    ref = os.path.join(project_dir, 'reference')
    path = os.path.join(ref, 'scene-briefs.csv')
    hone_briefs(ref, project_dir, scene_ids=['act1-sc02'], model='m',
                log_dir=os.path.join(project_dir, 'working', 'logs'), coaching_level='full')
    out = capsys.readouterr().out
    assert "finding(s) on the author's notes reported, not rewritten (#644)" in out
    assert 'act1-sc02.emotions (overspecified)' in out
    from storyforge.elaborate import _read_csv_as_map
    assert (_read_csv_as_map(path)['act1-sc02']['emotions']
            == _read_csv_as_map(os.path.join(PLUGIN, 'tests', 'fixtures', 'test-project',
                                             'reference', 'scene-briefs.csv'))
            ['act1-sc02']['emotions'])
    assert not any('**emotions**' in c for c in calls)     # no fix block for it


def test_report_author_notes_keeps_an_evaluation_finding():
    from storyforge.hone import _report_author_notes
    issues = [{'scene_id': 's', 'field': 'subtext', 'issue': 'verbose'},
              {'scene_id': 's', 'field': 'subtext', 'issue': 'evaluation'},
              {'scene_id': 's', 'field': 'key_actions', 'issue': 'verbose'}]
    assert [i['issue'] for i in _report_author_notes(issues)] == ['evaluation', 'verbose']


def test_revision_protects_only_a_must_line(project_dir):
    """SF-4: revision agrees with drafting: an unmarked key_dialogue line
    is a note, not a beat that MUST survive."""
    from storyforge.revision import build_revision_prompt
    p = build_revision_prompt('prose-tightening', 'Tighten prose', 'act1-sc02', project_dir)
    section = p.split('## Intent-Beat Protection', 1)[1].split('\n## ', 1)[0]
    assert 'forty years ago' not in section
    assert '**key_actions:** Cross-references maps' in section
    _set_cols(project_dir, 'scene-briefs.csv', 'act1-sc02',
              key_dialogue='must: "There is no note";"It was there forty years ago"')
    p = build_revision_prompt('prose-tightening', 'Tighten prose', 'act1-sc02', project_dir)
    section = p.split('## Intent-Beat Protection', 1)[1].split('\n## ', 1)[0]
    assert ('**key_dialogue (marked must:, word for word):** must: "There is no note"'
            in section)
    assert 'forty years ago' not in section


def test_write_notes_unmarked_dialogue_once(project_dir, capsys):
    from storyforge.cmd_write import _note_unmarked_dialogue
    _note_unmarked_dialogue(project_dir, ['act1-sc01', 'act1-sc02', 'new-x1'])
    out = capsys.readouterr().out
    assert out.count('NOTE: key_dialogue lines not marked must:') == 1
    assert 'in 2 scene(s): act1-sc01, act1-sc02.' in out
    _set_cols(project_dir, 'scene-briefs.csv', 'act1-sc02', key_dialogue='must: "No note"')
    _note_unmarked_dialogue(project_dir, ['act1-sc02'])
    assert capsys.readouterr().out == ''
