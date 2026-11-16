import os
import shutil
from typing import get_args

import pytest

from storyforge import cmd_status, status


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


def _solid_prose_tier(pd):
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


def test_build_status_prose_solid_points_to_the_voice_then_spine(tmp_path):
    # #656: all three prose rungs solid and no voice → the voice comes
    # first (the soft default), with the spine after it
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    v = status.build_status(pd)
    prose = {r['name']: r['state'] for r in v['ladder'] if r['level'] < 3}
    assert prose == {'logline': 'solid', 'synopsis': 'solid',
                     'act-shape': 'solid'}
    assert v['phase'] == 'voice'
    assert v['next']['stage'] == 'voice'
    assert v['next']['command'] == 'storyforge elaborate --stage voice'
    assert 'voice_stage: later' in v['next']['reason']
    assert '--moment' in v['next']['reason']
    assert v['then']['stage'] == 'spine'
    assert v['then']['command'] == 'storyforge elaborate --stage spine'
    assert v['voice'] == {'name': 'voice', 'state': 'not_started',
                          'detail': 'reference/voice/ has no voice yet', 'when': 'first',
                          'pov_gaps': None}
    # soft: no blocker before drafting
    assert not any(b['source'] == 'voice' for b in v['blockers'])
    text = cmd_status.render_human(v)
    lines = text.splitlines()
    v_line = next(i for i, ln in enumerate(lines) if ln.startswith('  V  voice'))
    assert lines[v_line - 1].startswith('  L2 act-shape')
    assert lines[v_line + 1].startswith('  L3 spine')


def test_build_status_prose_solid_with_a_voice_points_to_spine(tmp_path):
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    _voice_guide(pd)
    v = status.build_status(pd)
    assert v['phase'] == 'spine'
    assert v['next']['stage'] == 'spine'
    assert v['next']['command'] == 'storyforge elaborate --stage spine'
    assert v['voice']['state'] == 'solid'


@pytest.mark.parametrize('line', ['voice_stage: later', '- `voice_stage`: Later  (structure first)'])
def test_voice_stage_later_builds_the_structure_first(tmp_path, line):
    # the author skips the voice-first default: the old order
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    _write(os.path.join(pd, 'reference', 'key-decisions.md'), f'# Decisions\n\n{line}\n')
    v = status.build_status(pd)
    assert v['phase'] == 'spine'
    assert v['next']['stage'] == 'spine'
    assert v['voice']['when'] == 'later'
    text = cmd_status.render_human(v)
    assert 'later (key-decisions.md: voice_stage: later)' in text
    # the voice line comes after the structure, before drafting
    lines = text.splitlines()
    assert lines.index(next(ln for ln in lines if ln.startswith('  V  voice'))) > \
        lines.index(next(ln for ln in lines if ln.startswith('  L6')))


def test_a_voice_stage_value_it_doesnt_take_is_said_and_stays_first(tmp_path):
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    _write(os.path.join(pd, 'reference', 'key-decisions.md'), 'voice_stage: never\n')
    v = status.build_status(pd)
    assert v['next']['stage'] == 'voice'
    assert any("can't read 'voice_stage: never'" in n for n in v['notes'])


def test_a_commented_voice_stage_line_is_not_read(tmp_path):
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    _write(os.path.join(pd, 'reference', 'key-decisions.md'),
           '<!-- voice_stage: later -->\n')
    assert status.build_status(pd)['next']['stage'] == 'voice'


@pytest.mark.parametrize('phase_level', [3, 4, 5, 6])
def test_voice_first_holds_at_every_structural_rung(tmp_path, monkeypatch, phase_level):
    # a book already part-built without its voice: the voice is next, the
    # rung it was on is then
    pd = str(tmp_path)
    ladder = [{'level': lvl, 'name': name,
               'state': 'solid' if lvl < phase_level else 'not_started', 'detail': ''}
              for lvl, name in status.LEVEL_NAMES.items()]
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: ladder)
    v = status.build_status(pd)
    assert v['next']['stage'] == 'voice'
    assert v['then']['stage'] == status.LEVEL_NAMES[phase_level]


def _mapped(pd, povs=('Ann Lee', 'Bo Tan')):
    _write(os.path.join(pd, 'reference', 'characters.csv'),
           'id|name|aliases\nann-lee|Ann Lee|Annie\nbo-tan|Bo Tan|\n')
    rows = ''.join(f's{i}|{i}|{p}|mapped\n' for i, p in enumerate(povs, 1))
    _write(os.path.join(pd, 'reference', 'scenes.csv'), 'id|seq|pov|status\n' + rows)


def _ladder_up_to(monkeypatch, solid_below):
    ladder = [{'level': lvl, 'name': name,
               'state': 'solid' if lvl < solid_below else 'not_started', 'detail': ''}
              for lvl, name in status.LEVEL_NAMES.items()]
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: ladder)


def test_the_check_after_the_map_names_the_pov_book_md_is_silent_on(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _mapped(pd)
    _voice_guide(pd, '# The voice\n\n## People\n\n- **Annie** speaks in short bursts.\n')
    _ladder_up_to(monkeypatch, 6)   # the map solid, briefs not
    v = status.build_status(pd)
    assert v['phase'] == 'voice'
    assert v['next']['action'] == 'Check the voice against the map'
    assert v['next']['command'] == 'storyforge elaborate --stage voice'
    assert 'Bo Tan' in v['next']['reason'] and 'Ann Lee' not in v['next']['reason']
    assert v['then']['stage'] == 'briefs'
    assert v['voice']['pov_gaps'] == ['Bo Tan']
    assert 'book.md says nothing of POV(s): Bo Tan' in cmd_status.render_human(v)


def test_the_check_after_the_map_passes_when_every_pov_is_named(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _mapped(pd, ('ann-lee', 'Bo Tan', 'narrator'))
    _voice_guide(pd, '# The voice\n\nAnnie sees it all. Bo Tan, rarely. The narrator stands far '
                     'back.\n')
    _ladder_up_to(monkeypatch, 6)
    v = status.build_status(pd)
    assert v['next']['stage'] == 'briefs'
    assert v['voice']['pov_gaps'] == []


def test_the_check_after_the_map_waits_for_the_map(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _mapped(pd)
    _voice_guide(pd)
    _ladder_up_to(monkeypatch, 5)   # the map not solid yet
    v = status.build_status(pd)
    assert v['next']['stage'] == 'scene-map'
    assert v['voice']['pov_gaps'] is None   # not run: the map isn't solid


def test_the_check_after_the_map_is_a_note_once_briefs_are_done(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _mapped(pd)
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           'id|seq|pov|status\ns1|1|Ann Lee|briefed\ns2|2|Bo Tan|briefed\n')
    _voice_guide(pd)
    _ladder_up_to(monkeypatch, 7)
    v = status.build_status(pd)
    assert v['next']['stage'] == 'draft'
    assert any('says nothing of 2 POV(s) of the map: Ann Lee, Bo Tan' in n
               for n in v['notes'])
    assert not any(b['source'] == 'voice' for b in v['blockers'])


def test_voice_notes_survive_scenes_waiting_on_the_gate(tmp_path, monkeypatch):
    # the gate branch used to rebind `notes`, dropping every note before it
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    _write(os.path.join(pd, 'reference', 'key-decisions.md'), 'voice_stage: sometime\n')
    _ladder_up_to(monkeypatch, 7)
    monkeypatch.setattr(status, 'gate_waiting', lambda pd_: [
        {'scene_id': 's1', 'command': 'write', 'reason': 'contradiction'}])
    monkeypatch.setattr(status, 'free_to_draft', lambda pd_: (1, 1, []))
    v = status.build_status(pd)
    assert v['next']['stage'] == 'draft'
    assert v['then']['stage'] == 'check'   # the gate branch that rebound notes ran
    assert any('voice_stage' in n for n in v['notes'])


def test_what_status_couldnt_read_of_the_scenes_left_is_a_gate_blocker(tmp_path, monkeypatch):
    # the renamed `unread`: free_to_draft's notes are blockers, not notes
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    _ladder_up_to(monkeypatch, 7)
    monkeypatch.setattr(status, 'gate_waiting', lambda pd_: [
        {'scene_id': 's1', 'command': 'write', 'reason': 'contradiction'}])
    monkeypatch.setattr(status, 'free_to_draft',
                        lambda pd_: (0, 0, ['could not tell which scenes write can draft']))
    v = status.build_status(pd)
    assert {'source': 'gate', 'level': -1,
            'detail': 'could not tell which scenes write can draft'} in v['blockers']
    assert not any('could not tell' in n for n in v['notes'])
    assert '; see the blockers)' in v['next']['reason']


def test_a_thin_briefs_rung_in_a_drafting_book_makes_the_check_a_note(tmp_path, monkeypatch):
    # CR-2: on iliad-adult with one brief blanked, the check came first
    pd = str(tmp_path)
    _mapped(pd)
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           'id|seq|pov|status\ns1|1|Ann Lee|drafted\ns2|2|Bo Tan|briefed\n')
    _voice_guide(pd)
    ladder = [{'level': lvl, 'name': name,
               'state': 'solid' if lvl < 6 else 'thin', 'detail': ''}
              for lvl, name in status.LEVEL_NAMES.items()]
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: ladder)
    v = status.build_status(pd)
    assert v['next']['stage'] == 'briefs'
    assert v['voice']['pov_gaps'] == ['Ann Lee', 'Bo Tan']
    assert any('says nothing of 2 POV(s)' in n for n in v['notes'])


def test_a_briefs_rung_with_a_brief_written_makes_the_check_a_note(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _mapped(pd)
    _voice_guide(pd)
    ladder = [{'level': lvl, 'name': name,
               'state': 'solid' if lvl < 6 else 'thin', 'detail': ''}
              for lvl, name in status.LEVEL_NAMES.items()]
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: ladder)
    assert status.build_status(pd)['next']['stage'] == 'briefs'


def test_voice_stage_later_defers_the_check_after_the_map_too(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _mapped(pd)
    _voice_guide(pd)
    _write(os.path.join(pd, 'reference', 'key-decisions.md'), 'voice_stage: later\n')
    _ladder_up_to(monkeypatch, 6)
    v = status.build_status(pd)
    assert v['next']['stage'] == 'briefs'
    assert v['voice']['pov_gaps'] == ['Ann Lee', 'Bo Tan']
    assert any('says nothing of 2 POV(s)' in n for n in v['notes'])


def test_an_unreadable_voice_shows_as_unreadable(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    os.makedirs(os.path.join(pd, 'reference', 'voice', 'book.md'))   # a folder, not a file
    v = status.build_status(pd)
    assert v['voice']['state'] == 'unreadable'
    assert '  V  voice         ! unreadable' in cmd_status.render_human(v)


def test_an_author_repo_voice_with_no_book_md_text_is_said(tmp_path, monkeypatch):
    from storyforge import voice_book
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    monkeypatch.setattr(voice_book, 'resolve', lambda p: voice_book.DocState(
        'ok', 'reference/voice', 'reference/voice', 'THE AUTHOR VOICE', ()))
    v = status.build_status(pd)
    assert v['next']['stage'] == 'spine'
    assert any('comes from the author repo' in n for n in v['notes'])


def test_a_clean_check_after_the_map_is_said_in_the_ladder(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _mapped(pd)
    _voice_guide(pd, '# The voice\n\nAnn Lee and Bo Tan, both close.\n')
    _ladder_up_to(monkeypatch, 6)
    v = status.build_status(pd)
    assert v['voice']['pov_gaps'] == []
    assert 'book.md names every POV of the map' in cmd_status.render_human(v)


def test_a_graphic_novel_has_no_voice_record(tmp_path):
    pd = str(tmp_path)
    _solid_prose_tier(pd)
    v = status.build_status(pd, 'graphic-novel')
    assert v['voice'] is None
    assert v['next']['stage'] == 'spine'


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
    assert nxt['command'] == 'storyforge write --session'
    assert then['stage'] == 'evaluate'
    nxt, then = status._recommend('evaluate')
    assert nxt['command'] == 'storyforge evaluate'
    assert then is None
    nxt, then = status._recommend('voice')
    assert nxt['command'] == 'storyforge elaborate --stage voice'
    assert then['stage'] == 'draft'


def test_collect_blockers_positive_on_fixture(project_dir):
    blockers = status.collect_blockers(project_dir)
    assert blockers                                    # fixture has real issues
    assert all(set(b) == {'source', 'level', 'detail'} for b in blockers)
    assert any(b['source'] in ('coverage', 'consistency') for b in blockers)


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
                         'ladder', 'next', 'then', 'blockers', 'notes', 'advisory', 'voice'}
    assert set(data['voice']) == {'name', 'state', 'detail', 'when', 'pov_gaps'}
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
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['phase'] == 'evaluate'
    assert v['next']['command'] == 'storyforge evaluate'
    assert v['then'] is None
    assert v['phase_matches_yaml'] is True
    assert not any(b['source'] == 'phase' for b in v['blockers'])


def _voice_guide(pd, text='# The voice\n\nShort, plain sentences.\n', anchor=True):
    """reference/voice/: book.md with `text`, and (unless not `anchor`) an anchor."""
    _write(os.path.join(pd, 'reference', 'voice', 'book.md'), text)
    if anchor:
        _write(os.path.join(pd, 'reference', 'voice', 'anchors', 'a.md'), 'She ran.\n')


def test_all_solid_some_drafted_recommends_draft(tmp_path, monkeypatch):
    # All structure solid but not every scene drafted → phase 'draft'.
    pd = str(tmp_path)
    _write(os.path.join(pd, 'reference', 'scenes.csv'),
           "id|seq|status\ns1|1|drafted\ns2|2|briefed\n")
    _voice_guide(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['phase'] == 'draft'
    assert v['next']['command'] == 'storyforge write --session'
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
                        lambda pd_, medium='novel', floors=None: ladder)
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
    assert {'story-power', 'voice', 'draft', 'evaluate'} <= stages
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


# --- #596: no drafting while the voice (reference/voice/) is missing or the template ---

def _briefed(pd, statuses=('briefed', 'briefed')):
    rows = ''.join(f's{i}|{i}|{st}\n' for i, st in enumerate(statuses, 1))
    _write(os.path.join(pd, 'reference', 'scenes.csv'), 'id|seq|status\n' + rows)


def _template_voice_guide(pd):
    """reference/voice/ as init leaves it: the templates, no anchor."""
    from storyforge import voice_book
    shutil.rmtree(os.path.join(pd, 'reference', 'voice'), ignore_errors=True)
    voice_book.scaffold(pd)


@pytest.mark.parametrize('setup, problem', [
    (lambda pd: None, 'reference/voice/ has no voice yet'),
    (_template_voice_guide, "reference/voice/book.md is still init's template"),
    (lambda pd: _voice_guide(pd, '\n  \n'), 'reference/voice/book.md is missing or empty'),
    (lambda pd: _voice_guide(pd, anchor=False), 'reference/voice/anchors/ holds no anchor'),
])
def test_voice_rung_before_drafting(tmp_path, monkeypatch, setup, problem):
    # The Telemachy pilot: L0-L6 solid, the voice still init's template,
    # and status said NEXT `storyforge write`
    pd = str(tmp_path)
    _briefed(pd)
    setup(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['phase'] == 'voice'
    assert v['next']['stage'] == 'voice'
    assert v['next']['command'] == 'storyforge elaborate --stage voice'
    assert v['then']['stage'] == 'draft'
    voice = [b for b in v['blockers'] if b['source'] == 'voice']
    assert len(voice) == 1
    assert problem in voice[0]['detail']
    assert 'reference/voice/anchors/' in voice[0]['detail']
    text = cmd_status.render_human(v)
    assert 'NEXT:  Find the voice  [storyforge elaborate --stage voice]' in text
    assert '[voice] reference/voice' in text


def test_filled_voice_guide_is_no_blocker(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['next']['stage'] == 'draft'
    assert not any(b['source'] == 'voice' for b in v['blockers'])


def test_voice_guide_reported_after_drafting(tmp_path, monkeypatch):
    # Every scene drafted: evaluate stays next, the missing guide is said
    pd = str(tmp_path)
    _briefed(pd, ('drafted', 'drafted'))
    _template_voice_guide(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['next']['stage'] == 'evaluate'
    assert [b['source'] for b in v['blockers']][:1] == ['voice']


def test_voice_rung_waits_for_upstream_rungs(tmp_path):
    # An unfinished ladder still points at its own rung, not the voice guide
    v = status.build_status(str(tmp_path))
    assert v['next']['stage'] == 'logline'
    assert not any(b['source'] == 'voice' for b in v['blockers'])


def test_graphic_novel_has_no_voice_rung(tmp_path, monkeypatch):
    # The GN script has its own voice files
    pd = str(tmp_path)
    _briefed(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd, 'graphic-novel')
    assert v['next']['stage'] == 'draft'
    assert not any(b['source'] == 'voice' for b in v['blockers'])


def test_gate_waiting_keeps_voice_as_then(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _briefed(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    monkeypatch.setattr(status, 'gate_waiting', lambda pd_: [
        {'scene_id': 's1', 'command': 'draft', 'reason': 'x'}])
    v = status.build_status(pd)
    assert v['next']['command'] == 'storyforge check --pending'
    # TD-6: forge routes on next.stage; the phase's stage would send it to
    # the Voice Stage instead of the gate check
    assert v['next']['stage'] == 'check'
    assert v['phase'] == 'voice'
    assert v['then']['stage'] == 'voice'


def test_gate_waiting_while_drafting_keeps_drafting_next(tmp_path, monkeypatch):
    # #641: write drafts past a scene waiting on the gate (holding only the
    # scenes that depend on it), so drafting stays next and the check is
    # then; the waiting scene is a gate blocker. (TD-6: next.stage and
    # next.command still agree.)
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    monkeypatch.setattr(status, 'gate_waiting', lambda pd_: [
        {'scene_id': 's1', 'command': 'provisional', 'reason': 'x'}])
    v = status.build_status(pd)
    assert (v['next']['stage'], v['next']['command']) == ('draft', status.WRITE_COMMAND)
    assert '1 scene(s) in working/gate-pending.csv, 1 committed provisionally' \
        in v['next']['reason']
    assert (v['then']['stage'], v['then']['command']) == ('check', status.CHECK_COMMAND)
    assert any(b['source'] == 'gate' and b['detail'].startswith('s1 (provisional)')
               for b in v['blockers'])


def test_gate_waiting_once_everything_is_drafted_routes_to_the_check(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    monkeypatch.setattr(status, 'draft_stage', lambda pd_: ('evaluate', 3, 3))
    monkeypatch.setattr(status, 'gate_waiting', lambda pd_: [
        {'scene_id': 's1', 'command': 'draft', 'reason': 'x'}])
    v = status.build_status(pd)
    assert (v['next']['stage'], v['next']['command']) == ('check', status.CHECK_COMMAND)
    assert v['then']['stage'] == 'evaluate'


def test_old_voice_files_alone_are_a_voice_blocker_and_said(tmp_path, monkeypatch):
    # the pipeline's files are no longer read: no voice, and a note about them
    pd = str(tmp_path)
    _briefed(pd)
    _write(os.path.join(pd, 'reference', 'voice-guide.md'), '# Voice\n\nTerse.\n')
    _write(os.path.join(pd, 'reference', 'persistent-prompt.md'), 'Old voice.\n')
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['next']['stage'] == 'voice'
    assert [b['source'] for b in v['blockers']] == ['voice']
    assert len(v['notes']) == 1
    assert ('reference/voice-guide.md, reference/persistent-prompt.md are no longer read'
            in v['notes'][0])
    assert 'NOTE: reference/voice-guide.md' in cmd_status.render_human(v)
    assert os.path.isfile(os.path.join(pd, 'reference', 'voice-guide.md'))


def test_old_voice_files_beside_a_good_voice_block_nothing(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    _write(os.path.join(pd, 'reference', 'voice-guide.md'), '# Voice\n\nTerse.\n')
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['next']['stage'] == 'draft' and v['blockers'] == []
    assert 'no longer read' in v['notes'][0]


def test_a_skipped_anchor_is_a_note_even_when_the_voice_is_ready(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    _write(os.path.join(pd, 'reference', 'voice', 'anchors', 'bad.md'), 'tense: future\n\nX.')
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['next']['stage'] == 'draft'
    assert any('bad.md' in n and 'left out' in n for n in v['notes'])


def test_a_bad_voice_block_is_a_blocker_not_a_crash(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _briefed(pd)
    _voice_guide(pd)
    _write(os.path.join(pd, 'storyforge.yaml'), 'voice:\n  author: ../nope\n')
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd)
    assert v['next']['stage'] == 'voice'
    assert 'voice.author: ../nope is not there' in v['blockers'][0]['detail']


def test_a_graphic_novel_keeps_its_voice_files_unremarked(tmp_path, monkeypatch):
    pd = str(tmp_path)
    _briefed(pd)
    _write(os.path.join(pd, 'reference', 'voice-profile.csv'), 'character\n')
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd, 'graphic-novel')
    assert not any(b['source'] == 'old-voice-files' for b in v['blockers'])


def test_every_elaborate_command_status_emits_is_a_valid_stage():
    # TD-5/7: the stage status names after --stage must be one elaborate takes
    from storyforge.cmd_elaborate import VALID_STAGES
    emitted = []
    for stage in get_args(status.Stage):
        if stage in ('story-power', 'check'):
            continue          # then-only / the gate: no _recommend branch of their own
        nxt, then = status._recommend(stage)
        emitted += [s['command'] for s in (nxt, then) if s]
    elaborate = [c.split('--stage ', 1)[1] for c in emitted
                 if c.startswith('storyforge elaborate --stage ')]
    assert 'voice' in elaborate
    assert set(elaborate) <= VALID_STAGES


def test_status_names_the_voice_stage_on_the_fixture(project_dir, monkeypatch):
    # end to end on a real project: the ladder solid, the guide the template
    monkeypatch.setattr(status, 'ladder_states', lambda pd, medium='novel', floors=None: [
        {'level': lvl, 'name': name, 'state': 'solid', 'detail': ''}
        for lvl, name in status.LEVEL_NAMES.items()])
    monkeypatch.setattr(status, 'gate_waiting', lambda pd: [])
    _template_voice_guide(project_dir)
    v = status.build_status(project_dir)
    assert v['next']['command'] == 'storyforge elaborate --stage voice'
    shutil.rmtree(os.path.join(project_dir, 'reference', 'voice'))
    shutil.copytree(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fixtures',
                                 'test-project', 'reference', 'voice'),
                    os.path.join(project_dir, 'reference', 'voice'))
    assert status.build_status(project_dir)['next']['stage'] != 'voice'


def _gate_advisory(verdict):
    """The verdict's advisory records from the gate, not the craft-framework
    floor checks (#643) the fixture project also has."""
    return [a for a in verdict['advisory'] if a['source'] != status.CRAFT_ADVISORY_SOURCE]


def test_advisory_broken_promises_are_listed_not_blockers(project_dir):
    """#642: the gate's advisory broken promises are in the verdict and the
    human output, and never a blocker or the next step."""
    from storyforge import gate
    from storyforge.checker import Finding
    gate.record_advisory(project_dir, 'act1-sc02', 'draft', [Finding(
        'broken-promise', 'PRM', '', '', 'Finds nothing', 'key_actions', 'not delivered')])
    verdict = status.build_status(project_dir)
    # TD-3: records, not preformatted lines
    assert _gate_advisory(verdict) == [{
        'scene_id': 'act1-sc02', 'command': 'draft', 'source': 'key_actions',
        'quote': 'Finds nothing', 'stale': '',
        'finding': 'PRM the brief\'s key_actions promises "Finds nothing" — not delivered'}]
    assert not any(b['source'] == 'gate' for b in verdict['blockers'])
    assert verdict['next']['stage'] != 'check'
    out = cmd_status.render_human(verdict)
    assert 'ADVISORY: 1 broken promise(s) the gate reported but did not stop on' in out
    assert '  act1-sc02: PRM the brief' in out


def test_no_advisory_section_without_any(project_dir, monkeypatch):
    monkeypatch.setattr(status, 'craft_advisory', lambda floors: [])
    verdict = status.build_status(project_dir)
    assert verdict['advisory'] == []
    assert 'ADVISORY' not in cmd_status.render_human(verdict)


def test_an_unreadable_advisory_list_says_so(project_dir):
    from storyforge import gate
    os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)
    with open(os.path.join(project_dir, gate.ADVISORY_PATH), 'w') as f:
        f.write('bad header\n')
    # CR-4, SF-5, TD-2: a gate blocker, never listed as a promise
    verdict = status.build_status(project_dir)
    assert _gate_advisory(verdict) == []
    [blocker] = [b for b in verdict['blockers'] if b['source'] == 'gate']
    assert blocker['detail'].startswith(f'{gate.ADVISORY_PATH} could not be read')
    out = cmd_status.render_human(verdict)
    assert 'broken promise' not in out and f'{gate.ADVISORY_PATH} could not be read' in out


def test_an_advisory_row_the_scene_moved_past_says_so(project_dir):
    # SF-7, TD-4: the row was found on other prose, or another brief
    from storyforge import gate
    from storyforge.checker import Finding
    finding = Finding('broken-promise', 'PRM', '', '', 'Finds nothing', 'key_actions',
                      'not delivered')
    path = os.path.join(project_dir, 'scenes', 'act1-sc02.md')
    prose = open(path).read()
    gate.record_advisory(project_dir, 'act1-sc02', 'draft', [finding], prose=prose)
    assert _gate_advisory(status.build_status(project_dir))[0]['stale'] == ''
    with open(path, 'a') as f:
        f.write('\nShe closed the ledger.\n')
    [row] = _gate_advisory(status.build_status(project_dir))
    assert row['stale'] == gate.STALE_PROSE
    assert gate.STALE_PROSE in cmd_status.render_human(status.build_status(project_dir))
    gate.record_advisory(project_dir, 'act1-sc02', 'draft', [finding],
                         prose=open(path).read())
    briefs = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    text = open(briefs).read().replace('Searches removal logs', 'Burns the archive')
    with open(briefs, 'w') as f:
        f.write(text)
    assert _gate_advisory(status.build_status(project_dir))[0]['stale'] == gate.STALE_BRIEF


def test_a_graphic_novel_is_drafted_scene_by_scene(tmp_path, monkeypatch):
    # #655: sessions draft prose; a graphic novel's script keeps write --keep-going
    pd = str(tmp_path)
    _briefed(pd)
    monkeypatch.setattr(status, 'ladder_states',
                        lambda pd_, medium='novel', floors=None: _all_solid_ladder())
    v = status.build_status(pd, 'graphic-novel')
    assert v['next']['command'] == 'storyforge write --keep-going'
    assert status.write_command('novel') == 'storyforge write --session'
