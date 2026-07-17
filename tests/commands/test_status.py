from typing import get_args

import pytest

import os
from storyforge import status


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_artifact_present_prose_and_csv(tmp_path):
    pd = str(tmp_path)
    # No story-summary.md, no CSVs → nothing present.
    assert status.artifact_present(pd, 0) is False
    assert status.artifact_present(pd, 3) is False

    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           "## Logline\nA mapmaker who cannot lie must chart a lie.\n\n"
           "## Synopsis\n\n## Act-shape\n\n## Theme\n")
    assert status.artifact_present(pd, 0) is True   # logline has body
    assert status.artifact_present(pd, 1) is False  # synopsis empty

    # CSV present only counts when it has a data row beyond the header.
    _write(os.path.join(pd, 'reference', 'spine.csv'), "id|seq|title\n")
    assert status.artifact_present(pd, 3) is False
    _write(os.path.join(pd, 'reference', 'spine.csv'),
           "id|seq|title\ne1|1|Opening\n")
    assert status.artifact_present(pd, 3) is True


def test_ladder_states_empty_project(tmp_path):
    ladder = status.ladder_states(str(tmp_path))
    assert [r['level'] for r in ladder] == [0, 1, 2, 3, 4, 5, 6]
    assert all(r['state'] == 'not_started' for r in ladder)
    assert ladder[0]['name'] == 'logline'


def test_ladder_states_prose_solid_and_thin(tmp_path):
    pd = str(tmp_path)
    # A short, well-formed logline passes the L0 floor → solid.
    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           "## Logline\nA cartographer who cannot lie must forge a map.\n\n"
           "## Synopsis\n\n## Act-shape\n\n## Theme\n")
    by_level = {r['level']: r for r in status.ladder_states(pd)}
    assert by_level[0]['state'] == 'solid'
    assert by_level[1]['state'] == 'not_started'   # synopsis empty

    # A logline well over the 35-word floor is present but fails → thin,
    # with a non-empty detail explaining the failure.
    long_logline = ' '.join(['word'] * 60)
    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           f"## Logline\n{long_logline}.\n\n## Synopsis\n\n## Act-shape\n\n## Theme\n")
    l0 = {r['level']: r for r in status.ladder_states(pd)}[0]
    assert l0['state'] == 'thin'
    assert l0['detail']   # non-empty explanation


def test_build_status_empty_project_points_to_logline(tmp_path):
    v = status.build_status(str(tmp_path))
    assert v['phase'] == 'logline'
    assert v['next']['stage'] == 'logline'
    assert v['next']['command'] == 'storyforge score --level 0'
    assert v['then']['stage'] == 'story-power'
    assert v['blockers'] == []


def test_build_status_prose_solid_points_to_spine(tmp_path):
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           "## Logline\n"
           "A cartographer who cannot draw a false line is ordered to forge "
           "a map that will start a war.\n\n"
           "## Synopsis\n"
           "She takes the commission. She learns the war it will start. She "
           "must choose between the guild that made her and the truth only "
           "she can draw. In the end she draws the true map and burns the "
           "guild's copy.\n\n"
           "## Act-shape\n"
           "### Act 1\nShe accepts the forbidden commission.\n"
           "### Act 2\nShe uncovers the war it will trigger and is trapped.\n"
           "### Act 3\nShe draws the truth and pays for it.\n\n"
           "## Theme\nTruth has a cost; someone must pay it.\n")
    v = status.build_status(pd)
    # All three prose rungs solid → phase advances to spine.
    prose = {r['name']: r['state'] for r in v['ladder'] if r['level'] < 3}
    assert prose == {'logline': 'solid', 'synopsis': 'solid',
                     'act-shape': 'solid'}
    assert v['phase'] == 'spine'
    assert v['next']['stage'] == 'spine'
    assert v['next']['command'] == 'storyforge elaborate --stage spine'


def test_fresh_project_no_spurious_phase_blocker(tmp_path):
    # New projects default to phase: spine but nothing is built. The declared
    # phase is intent, not an overclaim → no phase blocker, matches=True.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'storyforge.yaml'), "phase: spine\n")
    v = status.build_status(pd)
    assert v['phase'] == 'logline'
    assert v['phase_declared'] == 'spine'
    assert v['phase_matches_yaml'] is True
    assert not any(b['source'] == 'phase' for b in v['blockers'])


def test_phase_mismatch_reported_when_work_exists(tmp_path):
    # A built logline means the ladder is NOT all-not_started, so a declared
    # phase that diverges from the computed rung IS a real mismatch.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           "## Logline\nA cartographer who cannot lie must forge a map.\n\n"
           "## Synopsis\n\n## Act-shape\n\n## Theme\n")
    _write(os.path.join(pd, 'storyforge.yaml'), "phase: briefs\n")
    v = status.build_status(pd)
    assert v['phase'] == 'synopsis'           # logline solid → synopsis is next
    assert v['phase_matches_yaml'] is False    # declared 'briefs' != computed
    assert any(b['source'] == 'phase' for b in v['blockers'])


def test_unrecognized_legacy_phase_not_flagged(tmp_path):
    pd = str(tmp_path)
    _write(os.path.join(pd, 'storyforge.yaml'), "phase: development\n")
    v = status.build_status(pd)
    assert v['phase'] == 'logline'
    assert v['phase_matches_yaml'] is True          # legacy/unknown → not compared
    assert not any(b['source'] == 'phase' for b in v['blockers'])


def test_draft_stage_excludes_cut_merged(tmp_path):
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           "id|seq|status\ns1|1|drafted\ns2|2|briefed\ns3|3|cut\n")
    assert status.draft_stage(pd) == ('draft', 1, 2)   # cut excluded, not all drafted
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           "id|seq|status\ns1|1|drafted\ns2|2|polished\ns3|3|merged\n")
    assert status.draft_stage(pd) == ('evaluate', 2, 2)  # merged excluded, all drafted+


def test_collect_blockers_empty_project_has_none(tmp_path):
    # No artifacts present → every coverage/consistency level is skipped.
    assert status.collect_blockers(str(tmp_path)) == []


def test_recommend_structural_stage_mapping():
    for stage, elab, then_stage in [
        ('spine', 'spine', 'architecture'),
        ('architecture', 'architecture', 'scene-map'),
        ('scene-map', 'map', 'briefs'),
        ('briefs', 'briefs', 'draft'),
    ]:
        nxt, then = status._recommend(stage)
        assert nxt['stage'] == stage
        assert nxt['command'] == f'storyforge elaborate --stage {elab}'
        assert nxt['command']            # always non-empty
        assert then['stage'] == then_stage


def test_recommend_prose_and_terminal_stages():
    for stage, level in [('logline', 0), ('synopsis', 1), ('act-shape', 2)]:
        nxt, then = status._recommend(stage)
        assert nxt['stage'] == stage
        assert nxt['command'] == f'storyforge score --level {level}'
        assert then['stage'] == 'story-power'   # story-power is then-only
    nxt, then = status._recommend('draft')
    assert nxt['command'] == 'storyforge write'
    assert then['stage'] == 'evaluate'
    nxt, then = status._recommend('evaluate')
    assert nxt['command'] == 'storyforge evaluate'
    assert then is None


def test_collect_blockers_positive_on_fixture(project_dir):
    blockers = status.collect_blockers(project_dir)
    assert blockers                                    # fixture has real issues
    assert all(set(b) == {'source', 'level', 'detail'} for b in blockers)
    assert any(b['source'] in ('coverage', 'consistency') for b in blockers)


from storyforge import cmd_status


def test_render_human_contains_ladder_and_next(tmp_path):
    v = status.build_status(str(tmp_path))
    text = cmd_status.render_human(v)
    assert 'PHASE:' in text
    assert 'L0 logline' in text
    assert 'NEXT:' in text
    assert 'storyforge score --level 0' in text


def test_main_json_output(tmp_path, capsys, monkeypatch):
    import json as _json
    monkeypatch.setattr(cmd_status, 'detect_project_root',
                        lambda: str(tmp_path))
    monkeypatch.setattr(cmd_status, 'get_medium', lambda pd: 'novel')
    cmd_status.main(['--json'])
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data['phase'] == 'logline'
    assert data['next']['stage'] == 'logline'
    # Full verdict contract forge/elaborate route on — lock the whole shape.
    assert set(data) == {'phase', 'phase_declared', 'phase_matches_yaml',
                         'ladder', 'next', 'then', 'blockers'}
    assert isinstance(data['ladder'], list) and len(data['ladder']) == 7
    assert set(data['next']) == {'stage', 'action', 'command', 'reason'}
    assert isinstance(data['blockers'], list)


def test_draft_stage_keeps_short_rows(tmp_path):
    # A row too short to reach the status column must NOT vanish from the
    # count. Regression: reading via csv_cli.get_column silently dropped such
    # rows, so an all-drafted count could be reported when a scene was missing.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           "id|seq|title|status\n"
           "s1|1|One|drafted\n"
           "s2|2|Two|drafted\n"
           "s3|3\n")                       # short row: no status field
    stage, drafted, total = status.draft_stage(pd)
    assert total == 3                       # the short row is still counted
    assert drafted == 2
    assert stage == 'draft'                 # NOT 'evaluate' — not all drafted


def test_artifact_present_rejects_blank_data_row(tmp_path):
    # A delimiter-only / whitespace-only data row is not real content.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'spine.csv'), "id|seq|title\n|||\n")
    assert status.artifact_present(pd, 3) is False
    _write(os.path.join(pd, 'reference', 'spine.csv'),
           "id|seq|title\ne1|1|Opening\n")
    assert status.artifact_present(pd, 3) is True


def _all_solid_ladder():
    return [{'level': lvl, 'name': name, 'state': 'solid', 'detail': ''}
            for lvl, name in status.LEVEL_NAMES.items()]


def test_no_phase_blocker_when_prereqs_met(tmp_path, monkeypatch):
    # All ladder rungs solid + declared legacy 'drafting' (which no command
    # advances past): declared normalizes to 'draft', computed phase is
    # 'evaluate' (all scenes drafted). They differ, but every prerequisite
    # rung is solid, so this must NOT flag. Regression for the permanent
    # post-drafting phase blocker. Also exercises build_status's all-solid →
    # draft_stage composition path.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'storyforge.yaml'), "phase: drafting\n")
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           "id|seq|status\ns1|1|drafted\ns2|2|polished\n")
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel': _all_solid_ladder())
    v = status.build_status(pd)
    assert v['phase'] == 'evaluate'
    assert v['next']['command'] == 'storyforge evaluate'
    assert v['then'] is None
    assert v['phase_matches_yaml'] is True
    assert not any(b['source'] == 'phase' for b in v['blockers'])


def test_all_solid_some_drafted_recommends_draft(tmp_path, monkeypatch):
    # All structure solid but not every scene drafted → phase 'draft'.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           "id|seq|status\ns1|1|drafted\ns2|2|briefed\n")
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel': _all_solid_ladder())
    v = status.build_status(pd)
    assert v['phase'] == 'draft'
    assert v['next']['command'] == 'storyforge write'
    assert v['then']['stage'] == 'evaluate'


def test_phase_blocker_when_prereq_unmet(tmp_path, monkeypatch):
    # Declared 'architecture' but an upstream rung (spine) is thin → real
    # overclaim, flagged (the spec's motivating example).
    pd = str(tmp_path)
    _write(os.path.join(pd, 'storyforge.yaml'), "phase: architecture\n")
    ladder = [{'level': lvl, 'name': name,
               'state': ('solid' if lvl < 3 else
                         'thin' if lvl == 3 else 'not_started'),
               'detail': ''}
              for lvl, name in status.LEVEL_NAMES.items()]
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel': ladder)
    v = status.build_status(pd)
    assert v['phase_matches_yaml'] is False
    phase_blockers = [b for b in v['blockers'] if b['source'] == 'phase']
    assert phase_blockers and 'spine' in phase_blockers[0]['detail']


def test_recommend_raises_on_unknown_stage():
    # Fail loud rather than silently returning a "go evaluate" verdict.
    with pytest.raises(ValueError):
        status._recommend('bogus-stage')


def test_elaborate_stage_values_are_valid_cli_stages():
    # status.ELABORATE_STAGE bridges to the elaborate CLI (scene-map → map);
    # this pins the hand-mirrored mapping so a rename in either file fails CI.
    from storyforge.cmd_elaborate import VALID_STAGES
    assert set(status.ELABORATE_STAGE.values()) <= VALID_STAGES


def test_stage_and_rungstate_literals_are_complete():
    stages = set(get_args(status.Stage))
    assert set(status.LEVEL_NAMES.values()) <= stages
    assert {'story-power', 'draft', 'evaluate'} <= stages
    assert set(get_args(status.RungState)) == {'solid', 'thin', 'not_started'}


def test_collect_blockers_skips_accepted_and_gates_absent(tmp_path, monkeypatch):
    # A present artifact's real failure surfaces; an accepted failure is
    # skipped; a failure on an absent-artifact level is gated out.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'architecture.csv'),
           "id|seq|title\na1|1|X\n")           # level 4 present
    def fake_coverage(pd_):
        return [
            {'level': 4, 'checks': [
                {'check': 'r', 'passed': False, 'detail': 'real fail', 'accepted': False},
                {'check': 'w', 'passed': False, 'detail': 'waived fail', 'accepted': True},
            ]},
            {'level': 3, 'checks': [          # spine.csv absent → gated
                {'check': 'g', 'passed': False, 'detail': 'gated fail', 'accepted': False},
            ]},
        ]
    monkeypatch.setattr(status, 'score_coverage_all_levels', fake_coverage)
    monkeypatch.setattr(status, 'score_consistency_all_levels', lambda pd_: [])
    details = [b['detail'] for b in status.collect_blockers(pd)]
    assert 'real fail' in details
    assert 'waived fail' not in details      # accepted → skipped
    assert 'gated fail' not in details       # absent artifact → gated


def test_draft_stage_no_scenes_file(tmp_path):
    # Missing scenes.csv must not raise, and must not read as "all drafted".
    assert status.draft_stage(str(tmp_path)) == ('draft', 0, 0)


def test_render_human_terminal_verdict_no_then_no_blockers():
    verdict = {
        'phase': 'evaluate', 'phase_declared': 'drafting',
        'phase_matches_yaml': True,
        'ladder': [{'level': 0, 'name': 'logline', 'state': 'solid', 'detail': ''}],
        'next': {'stage': 'evaluate', 'action': 'Evaluate and polish',
                 'command': 'storyforge evaluate', 'reason': 'All scenes are drafted'},
        'then': None,
        'blockers': [],
    }
    text = cmd_status.render_human(verdict)
    assert 'THEN:' not in text                    # then is None → no THEN line
    assert 'BLOCKERS: none' in text
    assert 'matches storyforge.yaml' in text      # declared-phase suffix


def test_render_human_shows_declared_phase_name_on_mismatch():
    verdict = {
        'phase': 'spine', 'phase_declared': 'architecture',
        'phase_matches_yaml': False,
        'ladder': [{'level': 3, 'name': 'spine', 'state': 'thin', 'detail': 'x'}],
        'next': {'stage': 'spine', 'action': 'Develop the spine',
                 'command': 'storyforge elaborate --stage spine', 'reason': 'r'},
        'then': {'stage': 'architecture', 'action': 'Develop the architecture',
                 'command': 'storyforge elaborate --stage architecture', 'reason': ''},
        'blockers': [{'source': 'phase', 'level': -1, 'detail': 'upstream not solid'}],
    }
    text = cmd_status.render_human(verdict)
    assert "declared 'architecture'" in text
    assert 'THEN:' in text
    assert '[phase] upstream not solid' in text
