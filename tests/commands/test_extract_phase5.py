"""Extract phase 5 end to end, steps 5a and 5b (#440), against the fixture
project with the API mocked."""

import json
import os

import pytest

from storyforge import cmd_extract
from storyforge.elaborate import _read_csv, _read_csv_as_map
from storyforge.extract_describe import read_provenance


def _structure_reply(scene_ids, *, summaries=None):
    """A valid 5a reply over the fixture's six scenes: five events, every
    scene an anchor (a six-scene book's range is 6-6)."""
    spine = [{'id': f'event-{k}', 'title': f'Event {k}', 'summary': f'Event {k} happens.',
              'function': f'Turns {k}.'} for k in range(1, 6)]
    arch = [{'scene_id': sid, 'spine_event': f'event-{min(i, 4) + 1}'}
            for i, sid in enumerate(scene_ids)]
    if summaries is None:   # the fixture's scenes have none
        summaries = [{'scene_id': sid, 'summary': f'What happens in {sid}.'}
                     for sid in scene_ids]
    return json.dumps({'genre': 'literary fantasy', 'subgenre': 'cartographic mystery',
                       'scene_summaries': summaries, 'spine': spine,
                       'architecture': arch})


def _themes_reply(scene_ids, mention):
    return json.dumps({
        'themes': [{'id': f't{k}', 'name': f'T{k}', 'tier': 'primary',
                    'description': 'How the book treats it.'} for k in range(1, 4)],
        'scene_themes': [{'scene_id': sid, 'themes': ['t1', 't2']} for sid in scene_ids],
        'motifs': [{'id': 'm', 'name': 'M', 'aliases': [mention], 'tier': 'primary',
                    'mentions': [0, 1]}],
    })


@pytest.fixture
def book(project_dir):
    """The fixture with its upper layers as extraction leaves them: the
    taxonomy cut to its header, a placeholder genre, and two scenes sharing a
    motif mention."""
    ref = os.path.join(project_dir, 'reference')
    with open(os.path.join(ref, 'motif-taxonomy.csv'), 'w') as f:
        f.write('id|name|aliases|tier\n')
    yaml = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml) as f:
        text = f.read()
    with open(yaml, 'w') as f:
        f.write(text.replace('genre: "fantasy"', 'genre: "PROJECT_GENRE"   # Primary genre'))
    from storyforge.elaborate import update_scene
    ids = [r['id'] for r in _read_csv(os.path.join(ref, 'scenes.csv'))]
    for sid in ids[:2]:
        update_scene(sid, ref, {'motifs': 'the brass compass'})
    return project_dir


def _scene_ids(project_dir):
    from storyforge.extract_describe import scene_table
    return [s['id'] for s in scene_table(os.path.join(project_dir, 'reference'))]


def _answer(project_dir, structure=None, themes=None):
    ids = _scene_ids(project_dir)
    structure = structure or _structure_reply(ids)
    themes = themes or _themes_reply(ids, 'the brass compass')

    def reply(prompt):
        return themes if '**themes**' in prompt else structure
    return reply


def _run(project_dir, force=False):
    cmd_extract._run_phase_5(project_dir, os.path.join(project_dir, 'working', 'logs'),
                             os.path.join(project_dir, 'working', 'extraction-profile.json'),
                             force, dry_run=False)


class TestPhase5:
    def test_writes_the_layers_from_selection_and_copies(self, book, mock_api, mock_git,
                                                         mock_costs):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        ref = os.path.join(book, 'reference')
        spine = _read_csv(os.path.join(ref, 'spine.csv'))
        arch = _read_csv_as_map(os.path.join(ref, 'architecture.csv'))
        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert [r['id'] for r in spine] == [f'event-{k}' for k in range(1, 6)]
        for sid, row in arch.items():     # copied, not the model's
            assert row['pov'] == scenes[sid]['pov']
            assert row['value_shift'] == intent[sid]['value_shift']
            assert scenes[sid]['architecture_scene'] == sid
            assert intent[sid]['theme_threads'] == 't1;t2'
        motifs = _read_csv(os.path.join(ref, 'motif-taxonomy.csv'))
        assert motifs[0]['aliases'] == 'the brass compass'
        with open(os.path.join(book, 'storyforge.yaml')) as f:
            yaml = f.read()
        assert 'genre: "literary fantasy"   # Primary genre' in yaml
        assert 'subgenre: "secondary world"' in yaml     # the author's, kept
        assert set(read_provenance(book)) == {
            'reference/spine.csv', 'reference/architecture.csv',
            'reference/themes.csv', 'reference/motif-taxonomy.csv'}
        commits = [c for c in mock_git.calls if c[0] == 'commit_and_push']
        assert 'reference/spine.csv' in commits[-1][2]
        assert all(c['model'] for c in mock_api.calls)

    def test_a_rerun_writes_nothing_and_calls_nothing(self, book, mock_api, mock_git,
                                                      mock_costs, capsys):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        calls = len(mock_api.calls)
        _run(book)
        assert len(mock_api.calls) == calls
        out = capsys.readouterr().out
        assert 'reference/spine.csv: kept (extracted earlier; --force regenerates it)' in out
        assert '5a (structure) skipped' in out

    def test_force_regenerates_only_unedited_extracted_files(self, book, mock_api, mock_git,
                                                             mock_costs, capsys):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        themes = os.path.join(book, 'reference', 'themes.csv')
        with open(themes, 'a') as f:
            f.write('mine|Mine|primary|The author added this.\n')
        calls = len(mock_api.calls)
        _run(book, force=True)
        out = capsys.readouterr().out
        assert 'reference/themes.csv: kept (extracted earlier, then edited' in out
        assert '5b (themes and motifs) skipped' in out
        assert len(mock_api.calls) == calls + 1     # 5a only
        with open(themes) as f:
            assert 'The author added this.' in f.read()

    def test_an_authors_file_skips_its_step_before_any_call(self, project_dir, mock_api,
                                                             mock_git, mock_costs, capsys):
        # The fixture's motif-taxonomy.csv is the author's
        mock_api.set_response_fn(_answer(project_dir))
        _run(project_dir)
        prompts = [c['prompt'] for c in mock_api.calls]
        assert not any('**themes**' in p for p in prompts)
        assert ("reference/motif-taxonomy.csv: kept (the author's own; extraction never "
                'replaces it)') in capsys.readouterr().out
        assert not os.path.exists(os.path.join(project_dir, 'reference', 'themes.csv'))

    def test_one_retry_with_the_problems(self, book, mock_api, mock_git, mock_costs):
        ids = _scene_ids(book)
        bad = json.loads(_structure_reply(ids))
        bad['architecture'][0]['scene_id'] = 'no-such-scene'
        replies = iter([json.dumps(bad), _structure_reply(ids)])
        themes = _themes_reply(ids, 'the brass compass')
        mock_api.set_response_fn(lambda p: themes if '**themes**' in p else next(replies))
        _run(book)
        structure_prompts = [c['prompt'] for c in mock_api.calls if '**themes**' not in c['prompt']]
        assert len(structure_prompts) == 2
        assert "'no-such-scene' is not one of the scene ids" in structure_prompts[1]
        assert os.path.exists(os.path.join(book, 'reference', 'spine.csv'))

    def test_a_second_bad_reply_stops_and_writes_nothing_for_the_step(
            self, book, mock_api, mock_git, mock_costs, capsys):
        ids = _scene_ids(book)
        bad = json.loads(_structure_reply(ids))
        bad['spine'] = bad['spine'][:1]
        mock_api.set_response_fn(lambda p: json.dumps(bad))
        with pytest.raises(SystemExit):
            _run(book)
        assert not os.path.exists(os.path.join(book, 'reference', 'spine.csv'))
        assert 'Phase 5 stopped: structure: still unusable after a retry' in \
            capsys.readouterr().out
        commits = [c for c in mock_git.calls if c[0] == 'commit_and_push']
        assert commits[-1][1] == 'Extract: Phase 5 — describe (stopped)'

    def test_blank_scene_summaries_are_filled(self, book, mock_api, mock_git, mock_costs):
        ids = _scene_ids(book)
        from storyforge.elaborate import get_scene
        ref = os.path.join(book, 'reference')
        assert not get_scene(ids[0], ref).get('summary')   # the fixture has none
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert get_scene(ids[0], ref)['summary'] == f'What happens in {ids[0]}.'
        arch = _read_csv_as_map(os.path.join(ref, 'architecture.csv'))
        assert arch[ids[0]]['summary'] == f'What happens in {ids[0]}.'

    def test_an_unusable_provenance_record_stops_before_any_call(
            self, book, mock_api, mock_git, mock_costs):
        os.makedirs(os.path.join(book, 'working'), exist_ok=True)
        with open(os.path.join(book, 'working', 'extraction-provenance.csv'), 'wb') as f:
            f.write(b'\xff\xfe broken')
        with pytest.raises(SystemExit):
            _run(book)
        assert mock_api.calls == []


def test_column_lists_match_the_templates():
    from storyforge.common import get_plugin_dir
    from storyforge.extract_describe import MOTIF_COLUMNS, THEMES_COLUMNS
    for name, cols in (('themes.csv', THEMES_COLUMNS), ('motif-taxonomy.csv', MOTIF_COLUMNS)):
        with open(os.path.join(get_plugin_dir(), 'templates', 'reference', name)) as f:
            assert f.readline().strip().split('|') == cols


def test_genre_fill_keeps_crlf_and_the_comment(book, mock_api, mock_git, mock_costs):
    yaml = os.path.join(book, 'storyforge.yaml')
    with open(yaml, 'rb') as f:
        data = f.read()
    with open(yaml, 'wb') as f:
        f.write(data.replace(b'\n', b'\r\n'))
    mock_api.set_response_fn(_answer(book))
    _run(book)
    with open(yaml, 'rb') as f:
        data = f.read()
    assert b'genre: "literary fantasy"   # Primary genre\r\n' in data
    assert b'\n' not in data.replace(b'\r\n', b'')


def test_dry_run_calls_nothing_and_writes_nothing(book, mock_api, mock_git, mock_costs, capsys):
    cmd_extract._run_phase_5(book, os.path.join(book, 'working', 'logs'),
                             os.path.join(book, 'working', 'extraction-profile.json'),
                             False, dry_run=True)
    assert mock_api.calls == []
    assert not os.path.exists(os.path.join(book, 'reference', 'spine.csv'))
    assert '5a structure:' in capsys.readouterr().out


def test_phase_5_is_a_phase(monkeypatch):
    assert cmd_extract.parse_args(['--phase', '5']).phase == 5
