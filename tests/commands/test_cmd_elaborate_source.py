"""elaborate's map stage on an adaptation (#477): the reply's source-map-csv
block becomes reference/source-map.csv, and the stage's validation reports
coverage, holding the phase on a silent cut in faithful mode."""

import os

import pytest

from storyforge import source
from storyforge.cmd_elaborate import main

from source_helpers import YAML, _write, import_source, make_adaptation

SCENES_BLOCK = (
    '```scenes-csv\n'
    'id|seq|title|act|pov|location|timeline_day|time_mode|time_of_day|duration|status\n'
    'olympus-council-meets|1|Council|1|narrator|olympus|1|scene|morning|1 hour|mapped\n'
    'athena-at-the-door|2|At the Door|1|telemachus|ithaca-hall|1|scene|noon|1 hour|mapped\n'
    '```\n'
    '```intent-csv\n'
    'id|function|on_stage|characters\n'
    'olympus-council-meets|The gods free him|zeus;athena|zeus;athena\n'
    'athena-at-the-door|Athena rouses Telemachus|athena;telemachus|athena;telemachus\n'
    '```\n'
)

FULL_MAP = (
    '```source-map-csv\n'
    'scene_id|source_scenes|treatment|note\n'
    'olympus-council-meets|gods-debate|dramatize|\n'
    'athena-at-the-door|minerva-visits;assembly-called|compress|two days in one\n'
    '|ship-sails|cut|told in a line\n'
    '```\n'
)


@pytest.fixture
def adapted(tmp_path, monkeypatch, mock_git, mock_costs):
    proj = make_adaptation(tmp_path)
    import_source(proj)
    _write(proj, {'storyforge.yaml': YAML.format(extra='  mode: faithful') + 'phase: scene-map\n',
                  'reference/scenes.csv': 'id|seq|title|status\n'})
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: proj)
    return proj


def _run(mock_api, reply):
    mock_api.set_response(reply)
    try:
        main(['--stage', 'map'])
    except SystemExit as e:
        return e.code
    return 0


def test_map_stage_writes_the_source_map(adapted, mock_api, capsys):
    _run(mock_api, SCENES_BLOCK + FULL_MAP)
    rows = source.read_source_map(adapted)
    assert [r['treatment'] for r in rows] == ['dramatize', 'compress', 'cut']
    out = capsys.readouterr().out
    assert 'source-map.csv (3 rows)' in out
    assert 'Source odyssey: 4 scenes, 3 mapped, 2 compressed, 1 cut (reasons given)' in out


def test_a_silent_cut_fails_the_stage_validation(adapted, mock_api, capsys):
    _run(mock_api, SCENES_BLOCK + FULL_MAP.replace('|ship-sails|cut|told in a line\n', ''))
    out = capsys.readouterr().out
    assert 'odyssey:ship-sails is not in the source map' in out
    assert 'Validation: ' in out and 'PASSED' not in out


def test_a_map_reply_without_the_block_is_an_error(adapted, mock_api, capsys):
    _run(mock_api, SCENES_BLOCK)
    out = capsys.readouterr().out
    assert 'no source-map-csv block' in out
    assert not os.path.exists(source.source_map_path(adapted))
    assert 'PASSED' not in out


def test_a_wrong_header_leaves_the_map_alone(adapted, mock_api, capsys):
    _write(adapted, {'reference/source-map.csv': 'scene_id|source_scenes|treatment|note\n'})
    _run(mock_api, SCENES_BLOCK + FULL_MAP.replace('scene_id|source_scenes|treatment|note',
                                                    'scene|source'))
    assert 'header is scene|source' in capsys.readouterr().out
    assert source.read_source_map(adapted) == []


def test_map_prompt_without_source_is_unchanged(project_dir, mock_api, mock_git, mock_costs,
                                                monkeypatch, capsys):
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    main(['--stage', 'map', '--dry-run'])
    out = capsys.readouterr().out
    assert 'source-map' not in out and 'Source' not in out
