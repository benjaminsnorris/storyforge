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


def _pitch_reply(project_dir, **override):
    """A valid 5c reply for the project as it is when asked: one entry per
    act in scenes.csv and a meaning for every motif in the taxonomy."""
    from storyforge.extract_describe import act_lengths, scene_table
    ref = os.path.join(project_dir, 'reference')
    taxonomy = os.path.join(ref, 'motif-taxonomy.csv')
    motif_ids = [r['id'] for r in _read_csv(taxonomy)] if os.path.isfile(taxonomy) else []
    reply = {
        'logline': 'A cartographer finds a village missing from the maps and must choose '
                   'between her post and the truth.',
        'synopsis': 'Dorren notices an anomaly. She hides it. A village vanishes. She '
                    'investigates. The archive is being erased. She exposes it at a cost.',
        'act_shape': {'act_1': 'Dorren notices.', 'act_2': 'Dorren digs.',
                      'act_3': 'Dorren exposes the erasure.'},
        'theme': 'What an institution owes the truth.',
        'premise': 'A mapmaker discovers her maps are lying.',
        'core_theme': 'What does loyalty to an institution cost?',
        'motif_meanings': [{'motif_id': m, 'meaning': f'{m} carries memory.'}
                           for m in motif_ids],
        'conflict': {'external': 'The erasure.', 'internal': 'Protocol vs conscience.',
                     'thematic': 'Order vs truth.'},
        'promise': ['A slow-burn mystery.', 'A map that lies.'],
        'structural_model': 'Three acts.',
        'acts': [{'act': a.act, 'title': f'Part {a.act}', 'description': 'It turns.',
                  'key_beats': ['A beat.', 'Another.'], 'turning_point': 'It changes.'}
                 for a in act_lengths(scene_table(ref))],
        'subplots': [{'name': 'Tessa', 'characters': 'Tessa Merrin', 'function': 'Mirror.',
                      'arc': 'Doubt to trust.'}],
        'pov': {'pattern': 'Close third on Dorren.', 'excluded': ''},
        'voice': {'prose_style': 'Precise.', 'pacing': 'Slow, then fast.'},
        'never_does': ['Explains the magic.'],
        'title_meaning': {'surface': 'A quiet office.', 'deeper': 'Complicity.',
                          'final': 'Speech.'},
        'identity': {'pov': 'close third, past tense', 'tone': 'unsettled'},
    }
    reply.update(override)
    return json.dumps(reply)


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


def _answer(project_dir, structure=None, themes=None, pitch=None):
    ids = _scene_ids(project_dir)
    structure = structure or _structure_reply(ids)
    themes = themes or _themes_reply(ids, 'the brass compass')

    def reply(prompt):
        if '**logline**' in prompt:
            return pitch or _pitch_reply(project_dir)
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
            'reference/themes.csv', 'reference/motif-taxonomy.csv',
            'reference/story-summary.md', 'reference/story-architecture.md'}
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
        assert len(mock_api.calls) == calls + 2     # 5a and 5c
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
        mock_api.set_response_fn(lambda p: _pitch_reply(book) if '**logline**' in p
                                 else themes if '**themes**' in p else next(replies))
        _run(book)
        structure_prompts = [c['prompt'] for c in mock_api.calls
                             if '**spine**' in c['prompt']]
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
        assert _commits(mock_git)[-1][1] == ('Extract: Phase 5 — describe (spine and '
                                              'architecture, story summary and architecture)')

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


class TestPitch:
    """Step 5c: story-summary.md and story-architecture.md."""

    def _read(self, project_dir, name):
        with open(os.path.join(project_dir, 'reference', name), encoding='utf-8') as f:
            return f.read()

    def test_the_summary_round_trips_and_passes_the_floors(self, book, mock_api, mock_git,
                                                           mock_costs):
        from storyforge.common import parse_story_summary
        from storyforge.scoring_levels import score_act_shape, score_logline, score_synopsis
        mock_api.set_response_fn(_answer(book))
        _run(book)
        parsed = parse_story_summary(book)
        assert parsed['logline'].startswith('A cartographer finds a village')
        assert parsed['act_shape'].count('### Act ') == 3
        assert parsed['theme'] == 'What an institution owes the truth.'
        assert all(parsed['frontmatter'][k] for k in parsed['frontmatter'])
        for score in (score_logline, score_synopsis, score_act_shape):
            assert score(book)['failed'] == 0
        assert self._read(book, 'story-summary.md').startswith('<!-- storyforge:extracted v')

    def test_lengths_and_names_come_from_the_csvs(self, book, mock_api, mock_git, mock_costs):
        from storyforge.elaborate import update_scene
        from storyforge.extract_describe import act_lengths, scene_table
        ref = os.path.join(book, 'reference')
        ids = _scene_ids(book)
        for i, sid in enumerate(ids):
            update_scene(sid, ref, {'word_count': str(1000 * (i + 1))})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        doc = self._read(book, 'story-architecture.md')
        total = sum(1000 * (i + 1) for i in range(len(ids)))
        assert f'{total:,} words in {len(ids)} scenes' in doc
        first = act_lengths(scene_table(ref))[0]
        assert (f'**{round(100 * first.words / total)}% of the novel '
                f'(~{first.words:,} words, {first.scenes} scenes)**') in doc
        assert f'### Act {first.act}: Part {first.act}' in doc
        assert "# The Cartographer's Silence -- Story Architecture" in doc
        assert '| M | m carries memory. |' in doc         # the taxonomy's name
        assert '| Dorren Hayle |' in doc                   # POV counted by code
        assert '### What the book never does' in doc
        assert 'Things to Avoid' not in doc

    def test_missing_word_counts_are_reported_not_guessed(self, book, mock_api, mock_git,
                                                          mock_costs, capsys):
        from storyforge.elaborate import update_scene
        update_scene(_scene_ids(book)[0], os.path.join(book, 'reference'), {'word_count': ''})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert '5c: 1 scene(s) have no word count in scenes.csv' in capsys.readouterr().out
        assert '(1 scene(s) with no word count in scenes.csv are not counted)' in \
            self._read(book, 'story-architecture.md')

    def test_a_floor_failure_is_retried_with_the_problems(self, book, mock_api, mock_git,
                                                          mock_costs):
        long = ' '.join(['word'] * 40) + '.'
        replies = iter([_pitch_reply(book, logline=long, synopsis='Too short.'), None])
        answer = _answer(book)

        def reply(prompt):
            if '**logline**' in prompt:
                return next(replies) or _pitch_reply(book)
            return answer(prompt)
        mock_api.set_response_fn(reply)
        _run(book)
        prompts = [c['prompt'] for c in mock_api.calls if '**logline**' in c['prompt']]
        assert len(prompts) == 2
        assert 'logline has 40 words; at most 35' in prompts[1]
        assert 'synopsis has 1 sentences; expected 4-8' in prompts[1]
        assert os.path.exists(os.path.join(book, 'reference', 'story-summary.md'))

    def test_acts_and_motifs_must_match_the_book(self, book, mock_api, mock_git, mock_costs,
                                                 capsys):
        bad = _pitch_reply(book, acts=[{'act': '9', 'title': 'T', 'description': 'D',
                                        'key_beats': [], 'turning_point': 'P'}],
                           motif_meanings=[{'motif_id': 'nope', 'meaning': 'x'}])
        mock_api.set_response_fn(_answer(book, pitch=bad))
        with pytest.raises(SystemExit):
            _run(book)
        out = capsys.readouterr().out
        assert "acts names '9', which is not one of the book's acts" in out
        assert 'acts leaves out act(s)' in out
        assert "motif_meanings names 'nope'" in out
        assert '1 motif(s) have no meaning: m' in out
        assert not os.path.exists(os.path.join(book, 'reference', 'story-summary.md'))
        assert 'reference/spine.csv' in read_provenance(book)   # 5a and 5b kept

    def test_model_text_cannot_open_a_section(self, book, mock_api, mock_git, mock_costs):
        from storyforge.common import parse_story_summary
        sneaky = ('## Theme\nHijacked. One. Two. Three. Four.')
        answer = _answer(book)
        mock_api.set_response_fn(lambda p: _pitch_reply(book, synopsis=sneaky)
                                 if '**logline**' in p else answer(p))
        _run(book)
        parsed = parse_story_summary(book)
        assert parsed['synopsis'] == '\\## Theme Hijacked. One. Two. Three. Four.'
        assert parsed['theme'] == 'What an institution owes the truth.'

    def test_an_authors_summary_skips_both_docs_before_the_call(
            self, book, mock_api, mock_git, mock_costs, capsys):
        path = os.path.join(book, 'reference', 'story-summary.md')
        with open(path, 'w') as f:
            f.write('# Mine\n\n## Logline\n\nMy own.\n')
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert not any('**logline**' in c['prompt'] for c in mock_api.calls)
        out = capsys.readouterr().out
        assert "reference/story-summary.md: kept (the author's own" in out
        assert '5c (story summary and architecture) skipped' in out
        assert not os.path.exists(os.path.join(book, 'reference', 'story-architecture.md'))
        with open(path) as f:
            assert f.read() == '# Mine\n\n## Logline\n\nMy own.\n'

    def test_the_templates_are_filled(self, book, mock_api, mock_git, mock_costs):
        import shutil
        from storyforge.common import get_plugin_dir, is_unfilled_template
        for name in ('story-summary.md', 'story-architecture.md'):
            dest = os.path.join(book, 'reference', name)
            shutil.copy(os.path.join(get_plugin_dir(), 'templates', 'reference', name), dest)
            assert is_unfilled_template(dest)
        mock_api.set_response_fn(_answer(book))
        _run(book)
        for name in ('story-summary.md', 'story-architecture.md'):
            assert not is_unfilled_template(os.path.join(book, 'reference', name))

    def test_5c_reads_what_5a_and_5b_wrote(self, book, mock_api, mock_git, mock_costs):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        prompt = next(c['prompt'] for c in mock_api.calls if '**logline**' in c['prompt'])
        assert '1. Event 1: Event 1 happens. (function: Turns 1.)' in prompt
        assert '- t1 (primary): T1. How the book treats it.' in prompt
        assert '- m: M' in prompt
        assert 'genre: literary fantasy (secondary world)' in prompt

    def test_a_book_without_spine_or_themes_says_so(self, project_dir, mock_api, mock_git,
                                                    mock_costs, capsys):
        from storyforge import extract_describe as describe
        run = describe.Run(project_dir=project_dir, model='m',
                           log_dir=os.path.join(project_dir, 'working', 'logs'), force=False,
                           version='1', provenance={}, on_usage=lambda *a: None)
        mock_api.set_response_fn(lambda p: _pitch_reply(project_dir))
        scenes = describe.scene_table(os.path.join(project_dir, 'reference'))
        assert describe.run_pitch(run, {}, scenes) == 'written'
        assert '5c: reference/spine.csv is absent' in run.reports
        assert '5c: reference/themes.csv is absent' in run.reports
        with open(os.path.join(project_dir, 'reference', 'story-summary.md')) as f:
            header = f.readline()
        assert 'from=profile,scenes,motif-taxonomy,mice-threads -->' in header


def _ev(acts=('1', '2'), motifs=('m', 'n'), title='T'):
    from storyforge.extract_describe import ActLength, PitchEvidence
    return PitchEvidence(title=title, genre='', spine=[], themes=[],
                         motifs=[{'id': m, 'name': m.upper()} for m in motifs], threads=[],
                         acts=[ActLength(a, scenes=1, words=10, uncounted=0) for a in acts])


def _reply(**override):
    """A valid 5c reply for `_ev()`, with fields overridden."""
    reply = json.loads(_pitch_reply_for(('1', '2'), ('m', 'n')))
    for key, value in override.items():
        target = reply
        *parents, last = key.split('__')
        for p in parents:
            target = target[p]
        target[last] = value
    return json.dumps(reply)


def _pitch_reply_for(acts, motif_ids):
    return json.dumps({
        'logline': 'A cartographer finds a village gone.',
        'synopsis': 'One. Two. Three. Four. Five.',
        'act_shape': {'act_1': 'A.', 'act_2': 'B.', 'act_3': 'C.'},
        'theme': 'T.', 'premise': 'P.', 'core_theme': 'Q?',
        'motif_meanings': [{'motif_id': m, 'meaning': f'{m} means.'} for m in motif_ids],
        'conflict': {'external': 'E.', 'internal': 'I.', 'thematic': 'T.'},
        'promise': ['A.'], 'structural_model': 'S.',
        'acts': [{'act': a, 'title': f'T{a}', 'description': 'D.', 'key_beats': ['b'],
                  'turning_point': 'P.'} for a in acts],
        'subplots': [], 'pov': {'pattern': 'P.', 'excluded': ''},
        'voice': {'prose_style': 'S.', 'pacing': 'P.'}, 'never_does': ['N.'],
        'title_meaning': {'surface': 'S.', 'deeper': 'D.', 'final': 'F.'},
        'identity': {'pov': 'P', 'tone': 'T'}})


class TestParsePitch:
    """Each problem branch of `parse_pitch`, and the review fixes on #446."""

    def _problems(self, reply, ev=None):
        from storyforge.extract_describe import ReplyProblems, parse_pitch
        with pytest.raises(ReplyProblems) as e:
            parse_pitch(reply, ev or _ev())
        return e.value.problems

    def test_a_valid_reply_parses(self):
        from storyforge.extract_describe import parse_pitch
        acts = json.loads(_reply())['acts'][::-1]
        pitch = parse_pitch(_reply(acts=acts, promise=['A.', '  ']), _ev())
        assert [a['act'] for a in pitch['acts']] == ['1', '2']    # the book's order
        assert pitch['promise'] == ['A.']                          # blank item dropped
        assert pitch['motif_meanings'] == {'m': 'm means.', 'n': 'n means.'}

    @pytest.mark.parametrize('override,expected', [
        ({'logline': ''}, 'logline is empty'),
        ({'theme': ' '}, 'theme is empty'),
        ({'premise': '\n'}, 'premise is empty'),
        ({'core_theme': ''}, 'core_theme is empty'),
        ({'act_shape__act_1': ''}, 'act_shape.act_1 is empty'),
        ({'conflict__internal': ''}, 'conflict.internal is empty'),
        ({'voice__pacing': ''}, 'voice.pacing is empty'),
        ({'identity__tone': ''}, 'identity.tone is empty'),
        ({'title_meaning__final': ''}, 'title_meaning.final is empty'),
        ({'structural_model': ''}, 'structural_model is empty'),
        ({'promise': ['', ' ']}, 'promise has no items'),
        ({'never_does': []}, 'never_does has no items'),
        ({'synopsis': ' '.join(['S.'] * 9)}, 'synopsis has 9 sentences; expected 4-8'),
        ({'subplots': [{'name': '', 'characters': 'c', 'function': 'f', 'arc': 'a'}]},
         'subplots[0].name is empty'),
    ])
    def test_an_empty_or_out_of_range_field_is_a_problem(self, override, expected):
        assert expected in self._problems(_reply(**override))

    def test_act_fields_and_repeats(self):
        reply = json.loads(_reply())
        reply['acts'][0].update(title='', key_beats=[], turning_point='Closing image:')
        reply['acts'].append(dict(reply['acts'][1]))
        problems = self._problems(json.dumps(reply))
        assert 'acts[0].title is empty' in problems
        assert 'acts[0].key_beats has no items' in problems
        assert 'acts[0].turning_point is empty' in problems     # only an echoed label
        assert "act '2' is described twice" in problems

    def test_motif_meanings_repeated_or_blank(self):
        problems = self._problems(_reply(motif_meanings=[
            {'motif_id': 'm', 'meaning': 'x'}, {'motif_id': 'm', 'meaning': 'y'},
            {'motif_id': 'n', 'meaning': '  '}]))
        assert 'motif m is given two meanings' in problems
        assert '1 motif(s) have no meaning: n' in problems

    def test_a_nested_null_is_malformed_not_the_word_none(self):
        """TD-1 / SF-8: a nested null became the text "None" in the doc."""
        from storyforge.extract_describe import parse_pitch
        with pytest.raises(TypeError, match='conflict.internal is NoneType'):
            parse_pitch(_reply(conflict__internal=None), _ev())

    def test_ids_are_matched_as_written(self):
        """TD-2 / SF-9: act and motif ids were cleaned like prose, so an act
        value with a double space or a leading dash could never match."""
        from storyforge.extract_describe import parse_pitch
        ev = _ev(acts=('Part  One', '- Coda'), motifs=('m',))
        pitch = parse_pitch(_pitch_reply_for(('Part  One', '- Coda'), ('m',)), ev)
        assert [a['act'] for a in pitch['acts']] == ['Part  One', '- Coda']

    @pytest.mark.parametrize('echo', ['Closing image: snow falls.',
                                      '**Closing image:** snow falls.',
                                      'Turning Point — snow falls.'])
    def test_an_echoed_label_is_stripped(self, echo):
        """Live on Carol: "**Closing image:** Closing image: ..."; SF-6: the
        bold and dash forms were missed."""
        from storyforge.extract_describe import parse_pitch
        reply = json.loads(_reply())
        reply['acts'][1]['turning_point'] = echo
        assert parse_pitch(json.dumps(reply), _ev())['acts'][1]['turning_point'] == \
            'snow falls.'

    def test_no_title_leaves_title_meaning_optional(self):
        """SF-2: with no title, the model was asked what "PROJECT_TITLE" means."""
        from storyforge.extract_describe import parse_pitch
        parse_pitch(_reply(title_meaning={'surface': '', 'deeper': '', 'final': ''}),
                    _ev(title=''))


@pytest.mark.parametrize('text,expected', [
    ('## Theme', '\\## Theme'), ('<!-- hide', '\\<!-- hide'), ('> quote', '\\> quote'),
    ('- item', '\\- item'), ('* item', '\\* item'), ('+ item', '\\+ item'),
    ('**Bold** start', '**Bold** start'), ('-3 degrees', '-3 degrees'),
    ('1. First', '1. First'), ('a\n\nb', 'a b'),
])
def test_one_line(text, expected):
    from storyforge.extract_describe import _one_line
    assert _one_line(text) == expected


def test_table_cells_escape_pipes_and_backslashes():
    """T-5: `\\|` in model text became `\\\\|`, a real cell delimiter."""
    from storyforge.extract_describe import _cell_md
    assert _cell_md('x | y') == 'x \\| y'
    assert _cell_md('x \\| y') == 'x \\\\\\| y'


class TestActs:
    def test_act_lengths_in_reading_order_with_uncounted(self):
        from storyforge.extract_describe import ActLength, act_lengths
        scenes = [{'act': '1', 'word_count': '100'}, {'act': '2', 'word_count': 'x'},
                  {'act': '1', 'word_count': '50'}, {'act': '', 'word_count': '7'}]
        assert act_lengths(scenes) == [ActLength('1', 2, 150, 0), ActLength('2', 1, 0, 1),
                                       ActLength('', 1, 7, 0)]

    def test_act_labels(self):
        from storyforge.extract_describe import _act_label
        assert _act_label('2') == 'Act 2'
        assert _act_label('Part One') == 'Part One'
        assert _act_label('') == 'Scenes with no act'


class TestPitchReviewFixes:
    """Regression tests for the #446 review (finding ids in each docstring)."""

    def test_a_file_changed_during_the_call_stops_5c_part_way(self, book, mock_api, mock_git,
                                                              mock_costs, capsys):
        """T-1."""
        arch = os.path.join(book, 'reference', 'story-architecture.md')
        answer = _answer(book)

        def reply(prompt):
            if '**logline**' in prompt:
                with open(arch, 'w') as f:
                    f.write('# Mine\n')
            return answer(prompt)
        mock_api.set_response_fn(reply)
        _run(book)
        assert '5c stopped part-way' in capsys.readouterr().out
        with open(arch) as f:
            assert f.read() == '# Mine\n'
        assert 'stopped part-way' in _commits(mock_git)[-1][1]

    def test_force_regenerates_5c_and_an_edit_blocks_both_docs(self, book, mock_api, mock_git,
                                                               mock_costs, capsys):
        """T-2."""
        from storyforge.common import parse_story_summary
        mock_api.set_response_fn(_answer(book))
        _run(book)
        new = 'A mapmaker learns her maps lie and must choose what to keep.'
        mock_api.set_response_fn(lambda p: _pitch_reply(book, logline=new)
                                 if '**logline**' in p else _answer(book)(p))
        _run(book, force=True)
        assert parse_story_summary(book)['logline'] == new
        summary = os.path.join(book, 'reference', 'story-summary.md')
        with open(summary, 'rb') as f:
            before = f.read()
        with open(os.path.join(book, 'reference', 'story-architecture.md'), 'a') as f:
            f.write('\nMy note.\n')
        calls = len(mock_api.calls)
        _run(book, force=True)
        out = capsys.readouterr().out
        assert 'reference/story-architecture.md: kept (extracted earlier, then edited' in out
        assert '5c (story summary and architecture) skipped' in out
        assert not any('**logline**' in c['prompt'] for c in mock_api.calls[calls:])
        with open(summary, 'rb') as f:
            assert f.read() == before
        assert 'were not filled either' not in out.split('5c (story summary')[1].split('\n')[0]

    def test_a_step_stopped_part_way_stops_the_steps_after_it(self, book, mock_api, mock_git,
                                                              mock_costs, capsys):
        """SF-1: 5c ran on a taxonomy and themes 5b had left disagreeing."""
        taxonomy = os.path.join(book, 'reference', 'motif-taxonomy.csv')
        answer = _answer(book)

        def reply(prompt):
            if '**themes**' in prompt:
                with open(taxonomy, 'w') as f:
                    f.write('id|name|aliases|tier\nmine|Mine|mine|primary\n')
            return answer(prompt)
        mock_api.set_response_fn(reply)
        _run(book)
        out = capsys.readouterr().out
        assert ('story summary and architecture skipped: themes and motifs stopped part-way'
                in out)
        assert not any('**logline**' in c['prompt'] for c in mock_api.calls)
        assert not os.path.exists(os.path.join(book, 'reference', 'story-summary.md'))

    @pytest.mark.parametrize('content,expected', [
        (b'id|name|description\nx|X|d\n', 'reference/themes.csv has no tier column'),
        (b'id|name|tier|description\n\xff|X|primary|d\n',
         'reference/themes.csv could not be read'),
    ])
    def test_an_unusable_evidence_file_is_named(self, book, mock_api, mock_git, mock_costs,
                                                capsys, content, expected):
        """SF-5: an unreadable or malformed author file stopped 5c without
        naming it, or was read as if every theme were supporting."""
        mock_api.set_response_fn(_answer(book))
        with open(os.path.join(book, 'reference', 'themes.csv'), 'wb') as f:
            f.write(content)
        with pytest.raises(SystemExit):
            _run(book)
        assert expected in capsys.readouterr().out
        assert not any('**logline**' in c['prompt'] for c in mock_api.calls)

    def test_the_dry_run_names_5c_or_why_it_would_stop(self, book, mock_api, mock_git,
                                                       mock_costs, capsys):
        """T-6 / SF-5: the dry run read 5c's evidence outside any handler."""
        def dry():
            cmd_extract._run_phase_5(book, os.path.join(book, 'working', 'logs'),
                                     os.path.join(book, 'working', 'extraction-profile.json'),
                                     False, dry_run=True)
        dry()
        assert '5c pitch:' in capsys.readouterr().out
        with open(os.path.join(book, 'reference', 'mice-threads.csv'), 'w') as f:
            f.write('id|type\nx|inquiry\n')
        dry()
        out = capsys.readouterr().out
        assert '5c pitch: would stop: 5c: reference/mice-threads.csv has no name column' in out
        assert mock_api.calls == []
        assert not os.path.exists(os.path.join(book, 'reference', 'story-summary.md'))

    def test_scenes_with_no_act_get_their_own_section(self, book, mock_api, mock_git,
                                                      mock_costs):
        """T-4."""
        from storyforge.elaborate import update_scene
        update_scene(_scene_ids(book)[0], os.path.join(book, 'reference'), {'act': ''})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        prompt = next(c['prompt'] for c in mock_api.calls if '**logline**' in c['prompt'])
        assert '("" is the scenes with no act)' in prompt
        with open(os.path.join(book, 'reference', 'story-architecture.md')) as f:
            assert '### Scenes with no act: Part\n' in f.read()

    def test_a_placeholder_title_is_not_described(self, book, mock_api, mock_git, mock_costs,
                                                  capsys):
        """SF-2."""
        yaml = os.path.join(book, 'storyforge.yaml')
        with open(yaml) as f:
            text = f.read()
        with open(yaml, 'w') as f:
            f.write(text.replace('"The Cartographer\'s Silence"', '"PROJECT_TITLE"', 1))
        mock_api.set_response_fn(lambda p: _pitch_reply(
            book, title_meaning={'surface': '', 'deeper': '', 'final': ''})
            if '**logline**' in p else _answer(book)(p))
        _run(book)
        prompt = next(c['prompt'] for c in mock_api.calls if '**logline**' in c['prompt'])
        assert "title: (none recorded: leave title_meaning's fields empty)" in prompt
        with open(os.path.join(book, 'reference', 'story-architecture.md')) as f:
            doc = f.read()
        assert 'PROJECT_TITLE' not in doc
        assert 'No title is recorded (`project.title` in storyforge.yaml).' in doc
        assert '5c: storyforge.yaml has no project.title' in capsys.readouterr().out

    def test_taxonomy_rows_with_no_id_are_left_out_and_said(self, book, mock_api, mock_git,
                                                            mock_costs, capsys):
        """TD: a blank-id row put '' among the ids needing a meaning, which
        no retry could satisfy."""
        from storyforge.extract_describe import pitch_evidence, scene_table
        with open(os.path.join(book, 'reference', 'motif-taxonomy.csv'), 'w') as f:
            f.write('id|name|aliases|tier\nm|M|m|primary\n|Nameless||primary\n')
        ev = pitch_evidence(book, scene_table(os.path.join(book, 'reference')))
        assert [m['id'] for m in ev.motifs] == ['m']
        assert ('1 row(s) of reference/motif-taxonomy.csv have no id and were left out'
                in ev.notes)

    def test_a_word_count_int_cannot_read_is_uncounted(self):
        """SF-7: '²'.isdigit() is True and int('²') raises."""
        from storyforge.extract_describe import ActLength, act_lengths
        assert act_lengths([{'act': '1', 'word_count': '²'}, {'act': '1', 'word_count': '5'}]) \
            == [ActLength('1', scenes=2, words=5, uncounted=1)]
