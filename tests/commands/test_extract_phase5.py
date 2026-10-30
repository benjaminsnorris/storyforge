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
        assert 'genre: "literary fantasy" # Primary genre' in yaml
        assert 'subgenre: "secondary world"' in yaml     # the author's, kept
        assert set(read_provenance(book)) == {
            'reference/spine.csv', 'reference/architecture.csv',
            'reference/themes.csv', 'reference/motif-taxonomy.csv'}
        commits = [c for c in mock_git.calls if c[0] == 'commit_and_push']
        assert 'reference/spine.csv' in commits[-1][2]
        assert all(c['model'] for c in mock_api.calls)

    def test_blank_statuses_on_an_already_extracted_book_are_marked(
            self, book, mock_api, mock_git, mock_costs):
        from storyforge.elaborate import get_scene, update_scene
        ref = os.path.join(book, 'reference')
        update_scene('act1-sc01', ref, {'status': ''})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert get_scene('act1-sc01', ref)['status'] == 'drafted'

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


def test_column_lists_are_one_declaration():
    """Review TD on #444: three declarations of the motif header had to
    agree, with nothing tying phase 5's to cleanup's."""
    from storyforge.cmd_cleanup import EXPECTED_CSV_SCHEMAS
    from storyforge.common import get_plugin_dir
    from storyforge.elaborate import _MOTIF_COLS, _THEMES_COLS
    for name, cols in (('themes.csv', _THEMES_COLS), ('motif-taxonomy.csv', _MOTIF_COLS)):
        with open(os.path.join(get_plugin_dir(), 'templates', 'reference', name)) as f:
            assert f.readline().strip().split('|') == cols
        assert EXPECTED_CSV_SCHEMAS[f'reference/{name}'] == cols


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
    assert b'genre: "literary fantasy" # Primary genre\r\n' in data
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


def _commits(mock_git):
    return [c for c in mock_git.calls if c[0] == 'commit_and_push']


class TestReviewFixes:
    """Regression tests for the #444 review."""

    def test_force_with_new_anchors_and_themes_leaves_no_dangling_refs(
            self, book, mock_api, mock_git, mock_costs, monkeypatch):
        """TA C1 / SF C1 / CR I1: a forced rerun picking other anchors and
        theme ids left the first run's cells naming ids that no longer exist."""
        from storyforge.elaborate import _read_csv_as_map
        from storyforge import extract_describe
        from storyforge.schema import validate_schema
        # Six scenes would force all six to be anchors; let one drop out
        monkeypatch.setattr(extract_describe, 'ARCHITECTURE_RANGE', (5, 25))
        ids = _scene_ids(book)
        mock_api.set_response_fn(_answer(book))
        _run(book)
        second = json.loads(_structure_reply(ids))
        second['architecture'] = second['architecture'][:5]   # the 6th is no longer an anchor
        themes2 = json.loads(_themes_reply(ids, 'the brass compass'))
        for t in themes2['themes']:
            t['id'] = 'u' + t['id']
        for st in themes2['scene_themes']:
            st['themes'] = ['ut1']
        mock_api.set_response_fn(_answer(book, structure=json.dumps(second),
                                         themes=json.dumps(themes2)))
        _run(book, force=True)
        ref = os.path.join(book, 'reference')
        anchors = set(_read_csv_as_map(os.path.join(ref, 'architecture.csv')))
        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        assert ids[5] not in anchors and scenes[ids[5]]['architecture_scene'] == ''
        assert all(r['architecture_scene'] in anchors | {''} for r in scenes.values())
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert all(intent[sid]['theme_threads'] == 'ut1' for sid in ids)
        report = validate_schema(ref, book)
        bad = [f for f in report['errors']
               if f.get('column') in ('theme_threads', 'motifs', 'architecture_scene')]
        assert bad == []

    def test_an_authors_theme_threads_cell_is_kept_and_reported(
            self, book, mock_api, mock_git, mock_costs, capsys):
        from storyforge.elaborate import get_scene, update_scene
        ref = os.path.join(book, 'reference')
        sid = _scene_ids(book)[0]
        update_scene(sid, ref, {'theme_threads': 'my-own-theme'})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert get_scene(sid, ref)['theme_threads'] == 'my-own-theme'
        assert ('1 scene(s) have a theme_threads cell naming themes not in themes.csv'
                in capsys.readouterr().out)
        update_scene(sid, ref, {'theme_threads': 't2'})      # names a theme that exists
        _run(book, force=True)
        assert get_scene(sid, ref)['theme_threads'] == 't2'
        assert '1 scene(s) have a theme_threads cell of their own, kept' in capsys.readouterr().out

    def test_validate_passes_on_motifs_after_5b(self, book, mock_api, mock_git, mock_costs):
        """CR H1: once the taxonomy had rows, every brief's descriptive
        motifs failed the registry check. Briefs now name motif ids, and
        every description moves to motif_details (Ben: ids, nothing lost)."""
        from storyforge.elaborate import get_scene, update_scene
        from storyforge.schema import validate_schema
        ref = os.path.join(book, 'reference')
        ids = _scene_ids(book)
        update_scene(ids[2], ref, {'motifs': 'a lone kite over the moor'})   # recurs nowhere
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert get_scene(ids[0], ref)['motifs'] == 'm'
        assert get_scene(ids[0], ref)['motif_details'] == 'the brass compass'
        assert get_scene(ids[2], ref)['motifs'] == ''
        assert get_scene(ids[2], ref)['motif_details'] == 'a lone kite over the moor'
        report = validate_schema(ref, book)
        assert [e for e in report['errors'] if e['column'] in ('motifs', 'motif_details')] == []

    def test_a_forced_rerun_regroups_from_the_details(self, book, mock_api, mock_git,
                                                       mock_costs):
        """After 5b, motifs holds ids; a rerun must group the descriptions,
        not the ids, or the second taxonomy is built from its own output."""
        mock_api.set_response_fn(_answer(book))
        _run(book)
        _run(book, force=True)
        themes_prompts = [c['prompt'] for c in mock_api.calls if '**themes**' in c['prompt']]
        assert ': the brass compass' in themes_prompts[-1]

    def test_an_authors_motif_details_is_the_source_and_is_kept(
            self, book, mock_api, mock_git, mock_costs):
        from storyforge.elaborate import get_scene, update_scene
        ref = os.path.join(book, 'reference')
        sid = _scene_ids(book)[0]
        update_scene(sid, ref, {'motif_details': 'my own notes'})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        prompt = next(c['prompt'] for c in mock_api.calls if '**themes**' in c['prompt'])
        assert f'[0] {sid}: my own notes' in prompt
        assert get_scene(sid, ref)['motif_details'] == 'my own notes'

    def test_an_api_failure_in_5b_commits_5a_and_stops(self, book, mock_api, mock_git,
                                                        mock_costs, monkeypatch, capsys):
        """SF C2 / CR H2: a RuntimeError (HTTP error, refusal) escaped with a
        traceback and left 5a's writes uncommitted."""
        from storyforge import api
        ids = _scene_ids(book)
        structure = _structure_reply(ids)
        real = api.invoke_to_file

        def invoke(prompt, *a, **k):
            if '**themes**' in prompt:
                raise RuntimeError('API returned HTTP 529')
            return real(prompt, *a, **k)
        mock_api.set_response_fn(lambda p: structure)
        monkeypatch.setattr(api, 'invoke_to_file', invoke)
        with pytest.raises(SystemExit):
            _run(book)
        out = capsys.readouterr().out
        assert 'themes: the API call failed (API returned HTTP 529)' in out
        assert os.path.exists(os.path.join(book, 'reference', 'spine.csv'))
        assert set(read_provenance(book)) == {'reference/spine.csv', 'reference/architecture.csv'}
        last = _commits(mock_git)[-1]
        assert last[1] == 'Extract: Phase 5 — describe (stopped)'
        assert 'reference/spine.csv' in last[2] and 'working/' in last[2]

    @pytest.mark.parametrize('reply,expected', [
        ('not json', 'structure: unreadable reply'),
        (json.dumps({'genre': '', 'subgenre': '', 'scene_summaries': [{'scene_id': 1}],
                     'spine': [], 'architecture': []}), 'structure: malformed reply'),
    ])
    def test_unreadable_and_malformed_replies_stop_without_a_retry(
            self, book, mock_api, mock_git, mock_costs, capsys, reply, expected):
        mock_api.set_response_fn(lambda p: reply)
        with pytest.raises(SystemExit):
            _run(book)
        assert len(mock_api.calls) == 1
        assert expected in capsys.readouterr().out

    def test_a_truncated_reply_stops_without_a_retry(self, book, mock_api, mock_git,
                                                     mock_costs, capsys):
        mock_api.set_response_dict({
            'content': [{'type': 'text', 'text': _structure_reply(_scene_ids(book))}],
            'stop_reason': 'max_tokens', 'usage': {'input_tokens': 1, 'output_tokens': 1}})
        with pytest.raises(SystemExit):
            _run(book)
        assert len(mock_api.calls) == 1
        assert 'structure: the reply hit its token limit' in capsys.readouterr().out
        assert not os.path.exists(os.path.join(book, 'reference', 'spine.csv'))

    def test_a_file_changed_during_the_call_stops_the_step_part_way(
            self, book, mock_api, mock_git, mock_costs, capsys):
        """SF M3 / TD: the gate is decided before a minutes-long call; an
        author edit in between left spine and architecture disagreeing and
        the cell fills ran on rows never written."""
        from storyforge.elaborate import get_scene
        ids = _scene_ids(book)
        arch = os.path.join(book, 'reference', 'architecture.csv')
        answer = _answer(book)

        def reply(prompt):
            if '**themes**' not in prompt:
                with open(arch, 'w') as f:
                    f.write('id|seq\nmine|1\n')
            return answer(prompt)
        mock_api.set_response_fn(reply)
        _run(book)
        out = capsys.readouterr().out
        assert '5a stopped part-way' in out
        assert get_scene(ids[0], os.path.join(book, 'reference')).get('architecture_scene', '') == ''
        assert 'stopped part-way' in _commits(mock_git)[-1][1]

    def test_every_changed_file_is_committed(self, book, mock_api, mock_git, mock_costs):
        import hashlib

        def snapshot():
            out = {}
            for root, _, files in os.walk(book):
                if '.git' in root:
                    continue
                for name in files:
                    path = os.path.join(root, name)
                    with open(path, 'rb') as f:
                        out[os.path.relpath(path, book)] = hashlib.sha256(f.read()).hexdigest()
            return out
        before = snapshot()
        mock_api.set_response_fn(_answer(book))
        _run(book)
        after = snapshot()
        changed = {p for p in after if before.get(p) != after[p]}
        paths = _commits(mock_git)[-1][2]
        uncovered = [p for p in changed
                     if not any(p == c or p.startswith(c) for c in paths)]
        assert changed and uncovered == []

    def test_statuses_are_left_alone_when_provenance_is_unusable(
            self, book, mock_api, mock_git, mock_costs):
        """CR I3 / SF L1: statuses were marked before the provenance check
        exited, and were left uncommitted."""
        from storyforge.elaborate import get_scene, update_scene
        ref = os.path.join(book, 'reference')
        update_scene('act1-sc01', ref, {'status': ''})
        os.makedirs(os.path.join(book, 'working'), exist_ok=True)
        with open(os.path.join(book, 'working', 'extraction-provenance.csv'), 'wb') as f:
            f.write(b'\xff broken')
        with pytest.raises(SystemExit):
            _run(book)
        assert get_scene('act1-sc01', ref)['status'] == ''

    def test_the_commit_says_what_was_written(self, project_dir, mock_api, mock_git,
                                              mock_costs, capsys):
        """TD: with the taxonomy the author's, 5b is skipped; the commit and
        PR task used to claim it anyway."""
        mock_api.set_response_fn(_answer(project_dir))
        assert cmd_extract._run_phase_5(
            project_dir, os.path.join(project_dir, 'working', 'logs'),
            os.path.join(project_dir, 'working', 'extraction-profile.json'), False, False)
        assert _commits(mock_git)[-1][1] == 'Extract: Phase 5 — describe (spine and architecture)'

    def test_nothing_written_returns_false(self, book, mock_api, mock_git, mock_costs, capsys):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert not cmd_extract._run_phase_5(
            book, os.path.join(book, 'working', 'logs'),
            os.path.join(book, 'working', 'extraction-profile.json'), False, False)
        assert 'Phase 5 wrote nothing' in capsys.readouterr().out

    def test_a_cost_logging_failure_is_said(self, project_dir, capsys):
        cmd_extract._log_api_usage('/no/such/file.json', 'extract-describe-themes', 'book',
                                   'claude-opus-5-5', project_dir)
        assert 'cost of extract-describe-themes (book) not recorded' in capsys.readouterr().out


class TestCsvCells:
    """CR I2 / SF H2: a quoting writer wrapped cells holding `"` or `|`,
    which the readers that split on `|` can't undo."""

    def test_quotes_and_pipes_round_trip_through_every_reader(self, tmp_path):
        from storyforge.elaborate import _SPINE_COLS
        from storyforge.extract_describe import _csv_text
        from storyforge.scoring_story_power import parse_spine
        row = {'id': 'e1', 'seq': '1', 'title': 'Old sport',
               'summary': '"Old sport," Gatsby says | and smiles.',
               'function': 'x', 'act': '1'}
        (tmp_path / 'reference').mkdir()
        path = tmp_path / 'reference' / 'spine.csv'
        path.write_text(_csv_text([row], _SPINE_COLS))
        read = _read_csv(str(path))[0]
        assert read['summary'] == '“Old sport," Gatsby says / and smiles.'
        assert read['act'] == '1'
        spine = parse_spine(str(tmp_path))
        assert len(spine) == 1


class TestProjectField:
    """CR I4 / SF L2: the regex wasn't scoped to project:, and lost the
    comment's column."""

    def _run_obj(self, project_dir):
        from storyforge.extract_describe import Run
        return Run(project_dir=project_dir, model='m', log_dir='', force=False, version='1',
                   provenance={}, on_usage=lambda *a: None)

    def test_the_template_yaml(self, tmp_path):
        import shutil
        from storyforge.common import get_plugin_dir
        from storyforge.extract_describe import _fill_project_field
        shutil.copy(os.path.join(get_plugin_dir(), 'templates', 'storyforge.yaml'),
                    tmp_path / 'storyforge.yaml')
        run = self._run_obj(str(tmp_path))
        _fill_project_field(run, 'genre', 'literary fiction')
        _fill_project_field(run, 'subgenre', 'Jazz Age')
        text = (tmp_path / 'storyforge.yaml').read_text()
        genre = next(line for line in text.splitlines() if line.startswith('  genre:'))
        assert genre.startswith('  genre: "literary fiction"') and genre.index('#') == 40
        sub = next(line for line in text.splitlines() if line.startswith('  subgenre:'))
        assert sub.startswith('  subgenre: "Jazz Age"') and sub.index('#') == 40
        assert run.reports == []

    def test_only_the_project_block(self, tmp_path):
        from storyforge.extract_describe import _fill_project_field
        (tmp_path / 'storyforge.yaml').write_text(
            'production:\n  genre: ""\n# a comment\nproject:\n  title: "T"\n'
            '  genre: "PROJECT_GENRE"\n')
        _fill_project_field(self._run_obj(str(tmp_path)), 'genre', 'mystery')
        assert (tmp_path / 'storyforge.yaml').read_text() == \
            'production:\n  genre: ""\n# a comment\nproject:\n  title: "T"\n  genre: "mystery"\n'

    def test_no_genre_line_is_reported(self, tmp_path):
        from storyforge.extract_describe import _fill_project_field
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: "T"\n')
        run = self._run_obj(str(tmp_path))
        _fill_project_field(run, 'genre', 'mystery')
        assert run.reports == ["storyforge.yaml: project.genre not set (no `genre:` line "
                               "under project: to fill); the book reads as 'mystery'"]
        assert (tmp_path / 'storyforge.yaml').read_text() == 'project:\n  title: "T"\n'


class TestCellRecord:
    """Phase 5 replaces a filled scene-CSV cell only while it still holds
    what phase 5 wrote (working/extraction-cells.csv)."""

    def test_an_author_edit_of_an_extracted_cell_survives_force(
            self, book, mock_api, mock_git, mock_costs, capsys):
        from storyforge.elaborate import get_scene, update_scene
        ref = os.path.join(book, 'reference')
        sid = _scene_ids(book)[0]
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert get_scene(sid, ref)['theme_threads'] == 't1;t2'
        update_scene(sid, ref, {'theme_threads': 't2'})      # the author narrows it
        _run(book, force=True)
        assert get_scene(sid, ref)['theme_threads'] == 't2'
        assert get_scene(_scene_ids(book)[1], ref)['theme_threads'] == 't1;t2'

    def test_an_unreadable_record_fills_only_blank_cells_and_is_left_alone(
            self, book, mock_api, mock_git, mock_costs, capsys):
        from storyforge.elaborate import get_scene, update_scene
        from storyforge.extract_describe import CELLS_FILE
        ref = os.path.join(book, 'reference')
        ids = _scene_ids(book)
        mock_api.set_response_fn(_answer(book))
        _run(book)
        record = os.path.join(book, CELLS_FILE)
        with open(record, 'wb') as f:
            f.write(b'\xff broken')
        update_scene(ids[0], ref, {'theme_threads': ''})
        themes2 = json.loads(_themes_reply(ids, 'the brass compass'))
        for st in themes2['scene_themes']:
            st['themes'] = ['t3']
        mock_api.set_response_fn(_answer(book, themes=json.dumps(themes2)))
        _run(book, force=True)
        assert get_scene(ids[0], ref)['theme_threads'] == 't3'      # was blank
        assert get_scene(ids[1], ref)['theme_threads'] == 't1;t2'   # can't be shown ours
        assert 'extraction-cells.csv could not be read' in capsys.readouterr().out
        with open(record, 'rb') as f:
            assert f.read() == b'\xff broken'
