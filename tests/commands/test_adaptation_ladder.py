"""#658's done-when: a `source:` book goes from source import to the scene
map without the spine and architecture stages (plan D8)."""

import os

import pytest

from storyforge import cmd_elaborate, cmd_source, source, status

from source_helpers import YAML, _write, make_adaptation

DECISIONS = """
## Interpretation decisions

- **What this version is about:** a boy finds he can act without his father.
- **Whose eyes:** Telemachus, close third; the gods' council in the narrator's.
- **What's cut:** the night sailing is told in a line.
- **What's invented:** nothing.
- **Where it ends:** the assembly breaks up.
- **Mode:** faithful.
"""

REPLY = (
    '```scenes-csv\n'
    'id|seq|title|summary|act|pov|location|timeline_day|time_mode|time_of_day|duration|status\n'
    'olympus-council-meets|1|Council|Zeus lets Odysseus go home|1|narrator|olympus|1|scene|morning|1 hour|mapped\n'
    'athena-at-the-door|2|At the Door|Athena rouses Telemachus to call the assembly|1|telemachus|ithaca-hall|1|scene|afternoon|1 hour|mapped\n'
    '```\n'
    '```intent-csv\n'
    'id|function|on_stage|characters\n'
    'olympus-council-meets|The gods free him|zeus;athena|zeus;athena\n'
    'athena-at-the-door|Athena rouses Telemachus|athena;telemachus|athena;telemachus\n'
    '```\n'
    '```source-map-csv\n'
    'scene_id|source_scenes|treatment|note\n'
    'olympus-council-meets|gods-debate|dramatize|\n'
    'athena-at-the-door|minerva-visits;assembly-called|compress|two days in one\n'
    '|ship-sails|cut|told in a line (key decisions: what\'s cut)\n'
    '```\n'
)


def _states(v):
    return {r['name']: r['state'] for r in v['ladder']}


def test_source_import_to_the_scene_map_without_spine_or_architecture(
        tmp_path, monkeypatch, mock_api, mock_git, mock_costs, capsys):
    proj = make_adaptation(tmp_path)
    _write(proj, {'storyforge.yaml': YAML.format(extra='  mode: faithful') + 'phase: spine\n'})
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    for mod in (cmd_elaborate, cmd_source):
        monkeypatch.setattr(mod, 'detect_project_root', lambda: proj)

    # 1. Nothing imported: status sends the author to the import
    assert status.build_status(proj)['next']['command'] == 'storyforge source import'
    assert cmd_source.main(['import', '--no-commit']) == 0

    # 2. Imported: the interpretation decisions are next; `source status` lists them
    v = status.build_status(proj)
    assert (v['phase'], v['next']['command']) == ('interpretation', 'storyforge source status')
    capsys.readouterr()
    cmd_source.main(['status'])
    out = capsys.readouterr().out
    assert 'Ladder: enters at the scene map' in out
    assert 'WARNING: reference/key-decisions.md has no `## Interpretation decisions`' in out

    # 3. Decided: the upper rungs are given; the voice, then the scene map
    with open(os.path.join(proj, 'reference', 'key-decisions.md'), 'a', encoding='utf-8') as f:
        f.write(DECISIONS)
    v = status.build_status(proj)
    assert [_states(v)[r] for r in ('logline', 'synopsis', 'act-shape', 'spine',
                                    'architecture')] == ['given'] * 5
    assert (v['next']['stage'], v['then']['stage']) == ('voice', 'scene-map')
    cmd_source.main(['status'])
    out = capsys.readouterr().out
    assert 'Interpretation decisions: all 6 recorded' in out
    assert '  Whose eyes: Telemachus, close third' in out

    # 4. The voice found: the scene map is next
    _write(proj, {'reference/voice/book.md': '# The voice\n\nShort, plain sentences.\n',
                  'reference/voice/anchors/a.md': 'He ran.\n'})
    v = status.build_status(proj)
    assert v['next']['command'] == 'storyforge elaborate --stage map'

    # 5. The map stage, built from the source and the decisions
    mock_api.set_response(REPLY)
    try:
        cmd_elaborate.main(['--stage', 'map'])
    except SystemExit as e:
        assert not e.code
    assert len(mock_api.calls_for('invoke_to_file')) == 1      # the map stage alone
    prompt = mock_api.calls_for('invoke_to_file')[0]['prompt']
    assert "expanding the source's events and the interpretation decisions into" in prompt
    assert 'Expand the architecture' not in prompt
    assert '### Entering at the scene map' in prompt
    assert 'Leave `architecture_scene` empty' in prompt
    assert 'Telemachus, close third' in prompt          # the decisions (Key Decisions)
    out = capsys.readouterr().out
    assert 'NOTE: this adaptation' not in out and 'WARNING: the map is built' not in out

    # 6. The map is there; the spine and architecture stages never ran
    v = status.build_status(proj)
    assert _states(v)['scene-map'] == 'solid', v['ladder']
    assert _states(v)['spine'] == _states(v)['architecture'] == 'given'
    from storyforge.elaborate import _read_csv
    rows = _read_csv(os.path.join(proj, 'reference', 'scenes.csv'))
    assert rows and all(not r.get('architecture_scene') for r in rows)
    # #656's check after the map, run for real: book.md names neither POV yet
    assert v['next']['action'] == 'Check the voice against the map'
    assert v['then']['stage'] == 'briefs'
    capsys.readouterr()
    with pytest.raises(SystemExit) as done:
        cmd_elaborate.main(['--stage', 'voice'])
    assert done.value.code == 0
    out = capsys.readouterr().out
    assert 'says nothing of 2 POV(s)' in out
    _write(proj, {'reference/voice/book.md': (
        '# The voice\n\nShort, plain sentences. The narrator holds the gods\' council, '
        'from far off; Telemachus\'s scenes are close third, past tense.\n')})
    with pytest.raises(SystemExit) as done:
        cmd_elaborate.main(['--stage', 'voice'])
    assert done.value.code == 0
    assert 'names every POV of the map' in capsys.readouterr().out
    v = status.build_status(proj)
    assert v['phase'] == 'briefs'
    assert not [b for b in v['blockers'] if b['source'] in ('source', 'coverage',
                                                            'interpretation')]
    assert not status.artifact_present(proj, 3)     # no spine of its own
    assert not status.artifact_present(proj, 4)     # no architecture
    assert len(source.read_source_map(proj)) == 3
    assert 'phase: briefs' in open(os.path.join(proj, 'storyforge.yaml')).read()


def _setup(tmp_path, monkeypatch, decisions=None):
    proj = make_adaptation(tmp_path)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    for mod in (cmd_elaborate, cmd_source):
        monkeypatch.setattr(mod, 'detect_project_root', lambda: proj)
    assert cmd_source.main(['import', '--no-commit']) == 0
    if decisions:
        with open(os.path.join(proj, 'reference', 'key-decisions.md'), 'a',
                  encoding='utf-8') as f:
            f.write(decisions)
    return proj


def _map(mock_api):
    mock_api.set_response(REPLY)
    try:
        cmd_elaborate.main(['--stage', 'map'])
    except SystemExit as e:
        return e.code or 0
    return 0


@pytest.mark.parametrize('decisions, why', [
    (None, 'has no `## Interpretation decisions` section'),
    (DECISIONS.replace('- **Where it ends:** the assembly breaks up.\n', ''),
     'missing Where it ends'),
    (DECISIONS.replace('faithful.', 'free.'), "source.mode is faithful"),
])
def test_the_map_stage_refuses_without_the_decisions(
        tmp_path, monkeypatch, mock_api, mock_git, mock_costs, capsys, decisions, why):
    """SF-1/CR-4: it warned and made the paid call; now it stops first."""
    proj = _setup(tmp_path, monkeypatch, decisions)
    assert _map(mock_api) == 1
    out = capsys.readouterr().out
    assert 'ERROR: the map of this adaptation is built from its source' in out
    assert why in out and 'Nothing was spent' in out
    assert not mock_api.calls_for('invoke_to_file')
    assert not os.path.exists(source.source_map_path(proj))


def test_a_dry_run_says_the_map_would_stop(tmp_path, monkeypatch, mock_api, mock_git,
                                           mock_costs, capsys):
    _setup(tmp_path, monkeypatch)
    try:
        cmd_elaborate.main(['--stage', 'map', '--dry-run'])
    except SystemExit:
        pass
    assert 'WARNING: the map is built from the source and the interpretation decisions, ' \
        'and the run would stop here' in capsys.readouterr().out
    assert not mock_api.calls_for('invoke_to_file')


def test_the_spine_stage_on_an_adaptation_says_it_takes_the_full_ladder(
        tmp_path, monkeypatch, mock_api, mock_git, mock_costs, capsys):
    proj = make_adaptation(tmp_path)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    for mod in (cmd_elaborate, cmd_source):
        monkeypatch.setattr(mod, 'detect_project_root', lambda: proj)
    assert cmd_source.main(['import', '--no-commit']) == 0
    mock_api.set_response('```spine-csv\nid|seq|title|summary\ne1|1|Suitors|They feast\n```\n')
    try:
        cmd_elaborate.main(['--stage', 'spine'])
    except SystemExit:
        pass
    assert ("NOTE: this adaptation's source gives its spine and architecture"
            in capsys.readouterr().out)
