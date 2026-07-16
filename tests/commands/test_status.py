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


def test_phase_mismatch_is_reported(tmp_path):
    pd = str(tmp_path)
    _write(os.path.join(pd, 'storyforge.yaml'), "phase: architecture\n")
    v = status.build_status(pd)
    assert v['phase_declared'] == 'architecture'
    assert v['phase'] == 'logline'          # nothing built yet
    assert v['phase_matches_yaml'] is False
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
