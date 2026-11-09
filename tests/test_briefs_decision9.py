"""Plan decision 9 (#644's follow-up): a brief is events, the turn, POV, the
outcome, and the knowledge and physical state in and out. goal, conflict,
crisis and decision are optional author notes, like key_dialogue: the briefs
stage never generates them, and every reader takes an empty one as fine.

And #668's SF-5: the briefs prompt and hone agree on how many events a
brief lists and how long key_actions runs, from one set of constants
(`elaborate.MAX_BRIEF_EVENTS`, `BRIEF_EVENTS_PER_1K`,
`KEY_ACTIONS_MAX_CHARS`, `brief_event_limit`)."""

import os

import pytest

from storyforge import elaborate, hone
from storyforge.elaborate import (
    AUTHOR_NOTE_COLUMNS, BRIEF_EVENTS_PER_1K, CRAFT_FRAMEWORK_COLUMNS,
    KEY_ACTIONS_MAX_CHARS, MAX_BRIEF_EVENTS, _read_csv_as_map, brief_event_limit,
)
from storyforge.enrich import update_csv_field

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOUR = ('goal', 'conflict', 'crisis', 'decision')


def _ref(proj):
    return os.path.join(proj, 'reference')


def _clear_four(proj):
    """Every brief in the fixture without goal, conflict, crisis, decision."""
    path = os.path.join(_ref(proj), 'scene-briefs.csv')
    for sid in _read_csv_as_map(path):
        for col in FOUR:
            update_csv_field(path, sid, col, '')
    return path


class TestTheFourAreAuthorNotes:
    def test_they_are_author_notes_and_not_framework_columns(self):
        assert set(FOUR) <= set(AUTHOR_NOTE_COLUMNS)
        assert not set(AUTHOR_NOTE_COLUMNS) & set(CRAFT_FRAMEWORK_COLUMNS)

    def test_the_briefs_reply_header_leaves_them_out(self):
        from storyforge.prompts_elaborate import BRIEFS_OUTPUT_HEADER
        cols = BRIEFS_OUTPUT_HEADER.split('|')
        assert not set(cols) & set(FOUR)
        assert {'outcome', 'key_actions', 'knowledge_in', 'knowledge_out',
                'physical_state_in', 'physical_state_out'} <= set(cols)

    def test_the_briefs_prompt_asks_for_none_of_them(self, project_dir):
        from storyforge.prompts_elaborate import build_briefs_prompt
        prompt = build_briefs_prompt(project_dir, PLUGIN)
        for col in FOUR:
            assert f'**{col}**' not in prompt
        assert 'never fill goal' not in prompt
        not_yours = prompt.split('Not yours to write: ', 1)[1].split('.', 1)[0]
        for col in FOUR:
            assert col in not_yours


class TestTheOutcomeAssumesNoGoal:
    def test_the_outcome_guide_never_names_a_goal(self):
        from storyforge.schema import OUTCOME_GUIDE, VALID_OUTCOMES
        assert 'goal' not in OUTCOME_GUIDE.lower()
        for value in VALID_OUTCOMES:
            assert f'{value} (' in OUTCOME_GUIDE

    def test_the_briefs_prompt_judges_the_outcome_without_a_goal(self, project_dir):
        from storyforge.prompts_elaborate import build_briefs_prompt
        prompt = build_briefs_prompt(project_dir, PLUGIN)
        outcome = prompt.split('- **outcome**:', 1)[1].split('\n', 1)[0]
        assert 'goal' not in outcome.lower()


class TestEventCount:
    def test_one_limit(self):
        assert brief_event_limit(0) == MAX_BRIEF_EVENTS
        assert brief_event_limit(1000) == 2          # 2.5 a 1,000 words, never under 2
        assert brief_event_limit(2000) == 5
        assert brief_event_limit(10000) == MAX_BRIEF_EVENTS
        assert brief_event_limit(400) == 2

    def test_hone_flags_past_the_limit_only(self):
        def beats(n):
            return ';'.join(f'event {i}' for i in range(n))
        briefs = {'a': {'key_actions': beats(MAX_BRIEF_EVENTS)},
                  'b': {'key_actions': beats(MAX_BRIEF_EVENTS + 1)},
                  'c': {'key_actions': beats(3)}, 'd': {'key_actions': beats(2)}}
        scenes = {'a': {}, 'b': {}, 'c': {'target_words': '1000'},
                  'd': {'target_words': '400'}}
        flagged = {r['scene_id'] for r in hone.detect_overspecified(briefs, scenes)
                   if r['field'] == 'key_actions'}
        assert flagged == {'b', 'c'}

    def test_the_old_density_rule_is_kept_exactly(self):
        """count > brief_event_limit(tw) is the old `count > 2 and
        count/tw*1000 > 2.5` rule for every count under the cap."""
        for tw in range(100, 6000, 50):
            for n in range(1, MAX_BRIEF_EVENTS + 1):
                old = n > 2 and n / tw * 1000 > BRIEF_EVENTS_PER_1K
                assert (n > brief_event_limit(tw)) == old, (tw, n)

    def test_hone_reads_the_shared_length(self):
        assert hone._TERSE_FIELDS['key_actions'] == KEY_ACTIONS_MAX_CHARS
        long = 'x' * (KEY_ACTIONS_MAX_CHARS + 1)
        ok = 'x' * KEY_ACTIONS_MAX_CHARS
        found = {r['scene_id'] for r in hone.detect_verbose_fields(
            {'long': {'key_actions': long}, 'ok': {'key_actions': ok}})}
        assert found == {'long'}

    def test_the_briefs_prompt_states_the_same_limits(self, project_dir):
        from storyforge.prompts_elaborate import build_briefs_prompt
        prompt = build_briefs_prompt(project_dir, PLUGIN)
        ka = prompt.split('- **key_actions**:', 1)[1].split('\n- **', 1)[0]
        assert f'never more than {MAX_BRIEF_EVENTS}' in ka
        assert f'{KEY_ACTIONS_MAX_CHARS} characters' in ka
        assert f'{BRIEF_EVENTS_PER_1K:g}' in ka
        assert f'{brief_event_limit(1000)} in a 1,000-word scene' in ka

    def test_hones_trim_aims_at_the_same_limit(self):
        prompt = hone.build_trim_prompt(
            's', [{'field': 'key_actions', 'issue': 'overspecified'}],
            {'key_actions': ';'.join(f'e{i}' for i in range(9))}, target_words=2000)
        assert f'Reduce to {brief_event_limit(2000)} events' in prompt


class TestAnEmptyNoteIsFine:
    """Every reader of goal, conflict, crisis and decision, on briefs that
    have none of them."""

    def test_validate_reports_nothing_about_them(self, project_dir):
        _clear_four(project_dir)
        report = elaborate.validate_structure(_ref(project_dir))
        for f in report['failures']:
            text = f"{f.get('message', '')} {f.get('fields') or ''}"
            for col in FOUR:
                assert f"'{col}'" not in text, f

    def test_hone_lists_no_gap(self, project_dir):
        _clear_four(project_dir)
        ref = _ref(project_dir)
        gaps = hone.detect_gaps(_read_csv_as_map(os.path.join(ref, 'scenes.csv')),
                                _read_csv_as_map(os.path.join(ref, 'scene-intent.csv')),
                                _read_csv_as_map(os.path.join(ref, 'scene-briefs.csv')))
        assert not [g for g in gaps if g['field'] in FOUR]

    def test_structural_completeness_names_none(self, project_dir):
        from storyforge.structural import score_completeness
        _clear_four(project_dir)
        ref = _ref(project_dir)
        result = score_completeness(_read_csv_as_map(os.path.join(ref, 'scenes.csv')),
                                    _read_csv_as_map(os.path.join(ref, 'scene-intent.csv')),
                                    _read_csv_as_map(os.path.join(ref, 'scene-briefs.csv')))
        for f in result['findings']:
            assert not set(f.get('fields') or ()) & set(FOUR), f

    def test_the_brief_floor_checks_none(self, project_dir):
        from storyforge.scoring_levels import score_level
        _clear_four(project_dir)
        result = score_level(project_dir, 6)
        for c in result['checks']:
            if not c['passed']:
                for col in FOUR:
                    assert col not in c['check'] and col not in (c.get('detail') or ''), c

    def test_the_story_power_pre_pass_wants_only_the_facts(self, project_dir):
        from storyforge.scoring_story_power import (
            _check_briefs_deterministic, parse_scene_briefs)
        _clear_four(project_dir)
        briefs = parse_scene_briefs(project_dir)
        assert briefs, 'a fact-only brief is a brief, not a pre-briefed placeholder'
        findings = _check_briefs_deterministic(briefs, [b.id for b in briefs])
        assert not [f for f in findings if f['field'] in FOUR]

    def test_the_story_power_pre_pass_still_wants_an_outcome(self, project_dir):
        from storyforge.scoring_story_power import (
            _check_briefs_deterministic, parse_scene_briefs)
        path = _clear_four(project_dir)
        update_csv_field(path, 'act1-sc01', 'outcome', '')
        briefs = parse_scene_briefs(project_dir)
        findings = _check_briefs_deterministic(briefs, [b.id for b in briefs])
        assert [f for f in findings if f['scene_id'] == 'act1-sc01'
                and f['field'] == 'outcome']

    def test_structure_scoring_reads_a_fact_only_brief(self, project_dir):
        _clear_four(project_dir)
        scores = {s['scene_id']: s for s in elaborate.score_structure(_ref(project_dir))}
        s = scores['act1-sc01']
        assert s['issues'] != ['No brief data']
        assert not [i for i in s['issues'] if any(c in i.lower() for c in FOUR)]

    def test_an_adaptation_does_not_rebrief_a_fact_only_brief(self, project_dir):
        from storyforge.prompts_source import _scenes_to_brief
        _clear_four(project_dir)
        todo = _scenes_to_brief(project_dir, None)
        assert 'act1-sc01' not in todo and 'act1-sc02' not in todo

    def test_brief_fidelity_scores_only_what_the_brief_lists(self, project_dir):
        from storyforge.scoring import build_fidelity_prompt, parse_fidelity_response
        _clear_four(project_dir)
        os.makedirs(os.path.join(project_dir, 'scenes'), exist_ok=True)
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), 'w') as f:
            f.write('Dorren reviewed the maps. ' * 20)
        prompt = build_fidelity_prompt('act1-sc01', project_dir, PLUGIN)
        assert '**goal:**' not in prompt.split('## Scene Prose', 1)[0]
        assert 'leave its score empty' in prompt
        parsed = parse_fidelity_response(
            'SCORES\nid|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|'
            'emotions|knowledge\nact1-sc01|||4|||5|||3\n', 'act1-sc01')
        assert parsed['scores'] == {'outcome': 4, 'key_actions': 5, 'knowledge': 3}

    def test_source_fidelity_takes_an_empty_note_as_no_departure(self):
        with open(os.path.join(PLUGIN, 'scripts', 'prompts', 'scoring',
                               'source-fidelity.md'), encoding='utf-8') as f:
            text = f.read()
        assert 'may leave goal and key_dialogue out' in text
        assert 'One left out is not a departure' in text

    def test_the_mice_gap_prompt_leaves_an_empty_goal_out(self):
        prompt = hone.build_mice_fill_prompt(
            't', 'T', 'inquiry', [{'id': 's1', 'title': 'One', 'goal': '', 'function': 'f'}],
            's0', 's2')
        assert 'goal: unknown' not in prompt and 'goal: ;' not in prompt

    def test_the_boundary_prompts_leave_empty_notes_out(self, project_dir):
        from storyforge import scoring_boundary
        _clear_four(project_dir)
        pairs = scoring_boundary._collect_per_scene_intent_vs_brief(project_dir, None)
        assert pairs
        for _sid, _up, down in pairs:
            assert 'Goal:' not in down and 'Crisis:' not in down


class TestReviseNeverRewritesThem:
    def test_the_source_fix_rewrites_only_the_facts(self):
        from storyforge import cmd_revise
        assert cmd_revise._SOURCE_FIX_FIELDS == ('outcome', 'key_actions')

    def test_drift_in_an_author_note_is_reported(self):
        from storyforge.cmd_revise import _split_note_drift
        fix, notes = _split_note_drift(['brief goal: the source wants the cup',
                                        'brief key_actions: the cup is never taken',
                                        'brief key_dialogue: a line',
                                        'prose goal: the prose drifts'])
        assert fix == ['brief key_actions: the cup is never taken',
                       'prose goal: the prose drifts']
        assert notes == ['brief goal: the source wants the cup', 'brief key_dialogue: a line']

    def test_a_brief_root_cause_is_reported_not_rewritten(self, project_dir, capsys):
        from storyforge.cmd_revise import _detect_upstream_scenes
        rows = [{'root_cause': 'brief', 'worst_items': 'act1-sc01;act1-sc02',
                 'principle': 'scene_turn'}]
        assert _detect_upstream_scenes(project_dir, rows) == []
        out = capsys.readouterr().out
        assert 'act1-sc01' in out and 'author' in out
