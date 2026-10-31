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


def _evidence(project_dir):
    from storyforge import extract_describe as d
    scenes = d.scene_table(os.path.join(project_dir, 'reference'))
    title, _ = d._book_title(project_dir)
    return (scenes, d.character_evidence(project_dir, scenes)[0],
            d.world_evidence(project_dir, scenes, title)[0],
            d.voice_evidence(project_dir, scenes, title)[0])


def _characters_reply(project_dir, **override):
    """A valid 5d reply for the characters the project's scenes show."""
    _, chars, _, _ = _evidence(project_dir)
    full = {k: f'{k} shown.' for k in ('physical', 'want', 'need', 'wound', 'lie',
                                       'flaw_as_strength', 'voice', 'relational',
                                       'arc_start', 'arc_turns', 'arc_end')}
    reply = {
        'characters': [{'id': c.id, 'tier': 'primary' if c.pov_scenes else 'secondary',
                        'role': f'{c.name}\'s role.', **full, 'left_open': ['Their past.']}
                       for c in chars],
        'relationships': ([{'a': chars[0].id, 'b': chars[1].id, 'nature': 'Mentor.'}]
                          if len(chars) > 1 else []),
        'pov': [{'id': c.id, 'gives': 'Close access.'} for c in chars if c.pov_scenes],
        'pov_excluded': '',
    }
    reply.update(override)
    return json.dumps(reply)


def _world_reply(project_dir, **override):
    from storyforge.extract_describe import _WORLD_SECTIONS
    _, _, world, _ = _evidence(project_dir)
    reply = {
        'overview': 'A city of maps.', 'macro': 'Cold coast.',
        'locations': [{'id': loc.id, 'description': f'{loc.name} is grey.',
                       'function': 'Work.', 'occupants': 'Clerks.'} for loc in world.locations],
        **{sec: {k: '' for k in keys} for sec, keys in _WORLD_SECTIONS.items()},
        'institutions': [{'name': 'The Office', 'function': 'Maps.', 'notes': ''}],
        'open_questions': ['Who erased the village.'],
        'system': {'present': 'yes', 'name': 'Pressure cartography',
                   'what_it_is': 'Maps that record pressure.', 'who': 'Cartographers.',
                   'how': 'Ink and instrument.', 'rules': ['A map shows what is.'],
                   'costs': '', 'feels': '', 'social': ''},
    }
    reply.update(override)
    return json.dumps(reply)


def _voice_reply(project_dir, **override):
    _, _, _, voice = _evidence(project_dir)
    pov = voice.pov if voice else []
    reply = {
        'lineage': [{'influence': 'Le Guin', 'what': 'Plain lyricism.'}],
        'blend': 'Measured and cool.',
        'pov_voices': [{'id': p, **{k: f'{k}.' for k in (
            'interiority', 'sentence_patterns', 'metaphor_domain', 'notices',
            'emotional_register', 'speech')}} for p in pov],
        'senses': {k: '' for k in ('sight', 'sound', 'smell', 'touch', 'taste')},
        'dialogue': {k: 'Sparse.' for k in ('balance', 'use', 'subtext', 'declarations',
                                            'silence')},
        'emotion': {'restraint': 'Held.', 'key_moments': ['The village vanishes.'],
                    'physical': 'Hands.'},
        'habits': ['The narrator names instruments precisely.'],
        'never_does': ['The narrator never explains the cartography.'],
        'pacing': [{'scene_type': 'Office', 'description': 'Slow.'}],
        'recurring': [{'phrase': 'pressure', 'usage': 'Maps.', 'significance': 'Truth.'}],
        'register': 'Formal, close third.',
        'profiles': [{'id': p, 'preferred_words': ['meridian', 'ink'],
                      'metaphor_families': ['cartography'], 'rhythm': 'Long.',
                      'dialogue_style': 'Clipped.'} for p in pov],
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
    # The bibles and voice guide as init leaves them: templates, no profile
    import shutil
    from storyforge.common import get_plugin_dir
    for name in ('character-bible.md', 'voice-guide.md'):
        shutil.copy(os.path.join(get_plugin_dir(), 'templates', 'reference', name),
                    os.path.join(ref, name))
    os.remove(os.path.join(ref, 'voice-profile.csv'))
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
        if '## Its characters, as the scenes show them' in prompt:
            return _characters_reply(project_dir)
        if '**overview**' in prompt:
            return _world_reply(project_dir)
        if '**lineage**' in prompt:
            return _voice_reply(project_dir)
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
            'reference/story-summary.md', 'reference/story-architecture.md',
            'reference/character-bible.md', 'reference/world-bible.md',
            'reference/systems-bible.md', 'reference/voice-guide.md',
            'reference/voice-profile.csv', 'reference/timeline.md'}
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
        assert len(mock_api.calls) == calls + 5     # all but 5b
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
        answer = _answer(book)
        mock_api.set_response_fn(lambda p: next(replies) if '**spine**' in p else answer(p))
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
                                              'architecture, story summary and architecture, '
                                              'world and systems bibles, timeline and chapter '
                                              'map)')

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


def _add_facts(project_dir, *facts):
    """Append ledger rows: (subject, type, mutable, status, statement, quote)."""
    from storyforge import ledger
    rows = ledger.load(project_dir)
    for i, (subject, type_, mutable, status, statement, quote) in enumerate(facts):
        rows.append({'id': f'fact-{i}', 'scene_id': 'act1-sc01', 'type': type_,
                     'subject': subject, 'statement': statement, 'quote': quote,
                     'origin': 'prose', 'status': status, 'mutable': mutable,
                     'introduced_by': 'commitments'})
    ledger.save(project_dir, rows, command='test')


def _write_scene(project_dir, sid, text):
    with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'w') as f:
        f.write(text)


class TestCharacters:
    """Step 5d."""

    def test_evidence_orders_pov_first_and_reads_facts_and_lines(self, book):
        from storyforge.extract_describe import character_evidence, scene_table
        cid = 'dorren-hayle'
        _add_facts(book, (cid, 'trait', 'fixed', 'binding', 'Dorren is left-handed',
                          'her left hand'),
                   (cid, 'physical', 'state', 'binding', 'Dorren is soaked', ''),
                   (cid, 'trait', 'fixed', 'rejected', 'Dorren is a liar', ''))
        _write_scene(book, 'act1-sc01', 'The office was cold.\n\n"The map is wrong, and '
                     'I know it," said Dorren, folding it.\n\n"Nonsense," Pell said.\n')
        scenes = scene_table(os.path.join(book, 'reference'))
        chars, notes, _ = character_evidence(book, scenes)
        assert [c.id for c in chars] == ['dorren-hayle', 'tessa-merrin', 'kael-maren', 'pell']
        dorren = next(c for c in chars if c.id == cid)
        assert dorren.facts == ['trait: Dorren is left-handed ("her left hand")']  # fixed, binding
        assert dorren.lines == ['The map is wrong, and I know it,']
        assert not any('ledger' in n or 'commitments' in n for n in notes)

    def test_an_unmigrated_ledger_is_said_not_guessed(self, book):
        from storyforge.extract_describe import character_evidence, scene_table
        with open(os.path.join(book, 'reference', 'knowledge.csv'), 'w') as f:
            f.write('id|name|aliases|category|origin\n')
        chars, notes, _ = character_evidence(book, scene_table(os.path.join(book, 'reference')))
        assert chars and all(c.facts == [] for c in chars)
        assert any('the ledger is not migrated' in n for n in notes)

    def test_the_cap_and_unknown_names_are_reported(self, book, monkeypatch):
        from storyforge import extract_describe as d
        from storyforge.elaborate import update_scene
        monkeypatch.setattr(d, 'MAX_CHARACTERS', 1)
        update_scene('act1-sc02', os.path.join(book, 'reference'), {'on_stage': 'Nobody Known'})
        chars, notes, _ = d.character_evidence(book, d.scene_table(os.path.join(book, 'reference')))
        assert len(chars) == 1
        assert any('are left out of the character bible' in n for n in notes)
        assert any('match no character in characters.csv' in n and 'Nobody Known' in n
                   for n in notes)

    def test_the_bible_is_written_with_code_counts(self, book, mock_api, mock_git, mock_costs):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        with open(os.path.join(book, 'reference', 'character-bible.md')) as f:
            doc = f.read()
        assert doc.startswith('<!-- storyforge:extracted v')
        assert '**Appears:** POV in 3 scene(s); on stage in 4' in doc
        assert '**What the text leaves open:**' in doc and 'Expansion Opportunities' not in doc
        assert '## POV Decisions' in doc and '- **Dorren Hayle:** 3 scene(s). Close access.' in doc

    @pytest.mark.parametrize('mutate,expected', [
        (lambda r, ids: r['characters'].pop(), 'characters leaves out'),
        (lambda r, ids: r['characters'][0].update(id='nobody'),
         "characters names 'nobody', which is not one of the ids given"),
        (lambda r, ids: r['characters'][0].update(tier='secondary'), 'so is primary'),
        (lambda r, ids: r['characters'][0].update(voice=''), '.voice is empty'),
        (lambda r, ids: r['characters'][-1].update(role=''), '.role is empty'),
        (lambda r, ids: r['relationships'].append({'a': ids[0], 'b': ids[0], 'nature': 'x'}),
         'must name two different character ids'),
        (lambda r, ids: r['pov'].pop(0), 'pov leaves out POV character(s)'),
    ])
    def test_problems(self, book, mutate, expected):
        from storyforge.extract_describe import ReplyProblems, parse_characters
        _, chars, _, _ = _evidence(book)
        reply = json.loads(_characters_reply(book))
        mutate(reply, [c.id for c in chars])
        with pytest.raises(ReplyProblems) as e:
            parse_characters(json.dumps(reply), chars)
        assert any(expected in p for p in e.value.problems)


class TestWorld:
    """Step 5e."""

    def test_a_book_with_no_system_gets_a_stub_saying_why(self, book, mock_api, mock_git,
                                                          mock_costs):
        none = {'present': 'no', 'name': '', 'what_it_is': 'The maps work by no stated rules.',
                'who': '', 'how': '', 'rules': [], 'costs': '', 'feels': '', 'social': ''}
        answer = _answer(book)
        mock_api.set_response_fn(lambda p: _world_reply(book, system=none)
                                 if '**overview**' in p else answer(p))
        _run(book)
        ref = os.path.join(book, 'reference')
        with open(os.path.join(ref, 'systems-bible.md')) as f:
            assert 'No formal system: The maps work by no stated rules.' in f.read()
        with open(os.path.join(ref, 'world-bible.md')) as f:
            world = f.read()
        assert '### Formal System\nNone. The maps work by no stated rules.' in world
        assert '**Pressure Cartography Office** (1 scene(s))' in world
        assert '## What the text leaves open' in world and 'Open Questions' not in world

    def test_a_system_is_written_with_its_rules(self, book, mock_api, mock_git, mock_costs):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        with open(os.path.join(book, 'reference', 'systems-bible.md')) as f:
            doc = f.read()
        assert '## System 1: Pressure cartography' in doc and '1. A map shows what is.' in doc

    @pytest.mark.parametrize('override,expected', [
        ({'overview': ''}, 'overview is empty'),
        ({'locations': []}, 'locations leaves out'),
        ({'system': {'present': 'yes', 'name': 'X', 'what_it_is': 'Y', 'who': '', 'how': '',
                     'rules': [], 'costs': '', 'feels': '', 'social': ''}},
         'system.rules has no items'),
        ({'system': {'present': 'no', 'name': '', 'what_it_is': '', 'who': '', 'how': '',
                     'rules': [], 'costs': '', 'feels': '', 'social': ''}},
         'say why the book has no formal system'),
    ])
    def test_problems(self, book, override, expected):
        from storyforge.extract_describe import ReplyProblems, parse_world
        _, _, world, _ = _evidence(book)
        with pytest.raises(ReplyProblems) as e:
            parse_world(_world_reply(book, **override), world)
        assert any(expected in p for p in e.value.problems)

    def test_world_facts_come_from_the_ledger(self, book):
        from storyforge.extract_describe import scene_table, world_evidence
        _add_facts(book, ('', 'world', 'fixed', 'binding', 'Maps record pressure', 'pressure'),
                   ('', 'world', 'state', 'binding', 'It is raining', ''))
        ev, _ = world_evidence(book, scene_table(os.path.join(book, 'reference')), 'T')
        assert ev.facts == ['world: Maps record pressure ("pressure")']


class TestVoice:
    """Step 5f."""

    def test_the_guide_and_profile_are_described_and_loadable(self, book, mock_api, mock_git,
                                                              mock_costs):
        import re
        from storyforge.extract_describe import VOICE_PROFILE_COLUMNS
        from storyforge.prompts import load_voice_profile
        mock_api.set_response_fn(_answer(book))
        _run(book)
        ref = os.path.join(book, 'reference')
        with open(os.path.join(ref, 'voice-guide.md')) as f:
            guide = f.read()
        assert '- Nothing was measured: too little prose' in guide   # the fixture is short
        for gone in ('Influence Blend', 'Style Rules', 'Prose Naturalness', '### Do Not'):
            assert gone not in guide
        # No bullet reads as an instruction (decision 2)
        from storyforge.extract_describe import _IMPERATIVE
        bullets = [line[2:] for line in guide.splitlines() if line.startswith('- ')]
        assert not [b for b in bullets if _IMPERATIVE.match(b)]
        with open(os.path.join(ref, 'voice-profile.csv')) as f:
            assert f.readline().strip().split('|') == VOICE_PROFILE_COLUMNS
        project, chars = load_voice_profile(book)
        assert project == {'register': 'Formal, close third.'}     # no banned_words
        assert chars['dorren-hayle']['preferred_words'] == 'meridian;ink'

    def test_an_instruction_is_sent_back(self, book):
        from storyforge.extract_describe import ReplyProblems, parse_voice
        _, _, _, voice = _evidence(book)
        with pytest.raises(ReplyProblems) as e:
            parse_voice(_voice_reply(book, never_does=['Never explain the maps.']), voice)
        assert any('reads as an instruction' in p for p in e.value.problems)

    def test_profile_words_with_a_semicolon_and_missing_pov_are_problems(self, book):
        from storyforge.extract_describe import ReplyProblems, parse_voice
        _, _, _, voice = _evidence(book)
        reply = json.loads(_voice_reply(book))
        reply['profiles'][0]['preferred_words'] = ['a;b']
        reply['pov_voices'].pop()
        with pytest.raises(ReplyProblems) as e:
            parse_voice(json.dumps(reply), voice)
        assert any('semicolon' in p for p in e.value.problems)
        assert any('pov_voices leaves out POV character(s)' in p for p in e.value.problems)

    def test_samples_are_chosen_by_position_and_dialogue(self, book):
        from storyforge.extract_describe import scene_table, voice_evidence
        long = ' '.join(['word'] * 400)
        _write_scene(book, 'act1-sc02', long + ' "' + ' '.join(['talk'] * 300) + '," she said.')
        ev, _ = voice_evidence(book, scene_table(os.path.join(book, 'reference')), 'T')
        labels = [(label, sid) for label, sid, _ in ev.samples]
        ids = [sid for sid in _scene_ids(book)        # the scenes with prose
               if os.path.exists(os.path.join(book, 'scenes', f'{sid}.md'))]
        assert labels[:3] == [('opening', ids[0]), ('middle', ids[len(ids) // 2]),
                              ('close', ids[-1])]
        assert ('most dialogue', 'act1-sc02') in labels

    def test_no_prose_skips_5f_and_says_so(self, book, mock_api, mock_git, mock_costs, capsys):
        import shutil
        shutil.rmtree(os.path.join(book, 'scenes'))
        os.makedirs(os.path.join(book, 'scenes'))
        mock_api.set_response_fn(_answer(book))
        _run(book)
        out = capsys.readouterr().out
        assert '5f skipped: no scene has prose to describe a voice from' in out
        assert not any('**lineage**' in c['prompt'] for c in mock_api.calls)
        assert not os.path.exists(os.path.join(book, 'reference', 'voice-profile.csv'))


def test_dialogue_spans_keep_lines_apart():
    from storyforge.prose_analysis import dialogue_spans
    text = '"One," he said. "Two."'
    assert [inner for _, _, inner in dialogue_spans(text)] == ['One,', 'Two.']
    assert text[dialogue_spans(text)[1][0]:dialogue_spans(text)[1][1]] == '"Two."'


def test_a_supporting_character_outranks_minor_ones(book, monkeypatch):
    """Live on Carol: Tiny Tim (supporting, on stage once) was cut while
    minor characters on stage twice made the bible."""
    from storyforge import extract_describe as d
    from storyforge.elaborate import update_scene
    ref = os.path.join(book, 'reference')
    with open(os.path.join(ref, 'characters.csv'), 'a') as f:
        f.write('tim|Tim||supporting|\nmaid|Maid||minor|\n')
    with open(os.path.join(ref, 'characters.csv')) as f:
        header = f.readline().strip().split('|')
    assert header[:2] == ['id', 'name']
    update_scene('act1-sc02', ref, {'on_stage': 'Dorren Hayle;Maid;Tim'})
    update_scene('act2-sc02', ref, {'on_stage': 'Tessa Merrin;Maid'})
    monkeypatch.setattr(d, 'MAX_CHARACTERS', 6)
    chars, _, _ = d.character_evidence(book, d.scene_table(ref))
    ids = [c.id for c in chars]
    assert 'tim' in ids and ids.index('tim') < ids.index('maid')


def test_a_scene_set_in_several_places_counts_each(book):
    """Live on Carol: `belles-family-home;scrooges-bedroom` was read as one
    unknown name."""
    from storyforge.elaborate import update_scene
    from storyforge.extract_describe import scene_table, world_evidence
    ref = os.path.join(book, 'reference')
    from storyforge.extract_describe import _registry
    _, alias, _ = _registry(book, 'locations.csv')
    first, second = list(dict.fromkeys(alias.values()))[:2]
    update_scene('act1-sc01', ref, {'location': f'{first};{second}'})
    ev, notes = world_evidence(book, scene_table(ref), 'T')
    assert {first, second} <= {loc.id for loc in ev.locations}
    assert not any(f'{first};{second}' in n for n in notes)


class TestBiblesReviewFixes:
    """Regression tests for the #447 review (finding ids in each docstring)."""

    def _ev(self, book):
        from storyforge.extract_describe import scene_table
        return scene_table(os.path.join(book, 'reference'))

    def test_an_unreadable_scene_file_stops_naming_it(self, book):
        """SF-1: an undecodable scene was counted as absent, and the voice
        was measured from the rest as the whole book."""
        from storyforge.extract_describe import DescribeFailed, voice_evidence
        with open(os.path.join(book, 'scenes', 'act1-sc01.md'), 'ab') as f:
            f.write(b'\xff\xfe')
        with pytest.raises(DescribeFailed, match='scenes/act1-sc01.md could not be read'):
            voice_evidence(book, self._ev(book), 'T')

    def test_absent_scenes_are_named(self, book):
        from storyforge.extract_describe import character_evidence
        _, notes, _ = character_evidence(book, self._ev(book))
        assert any('2 of 6 scene(s) have no prose in scenes/ (absent or blank): '
                   'act2-sc02, act2-sc03' in n for n in notes)

    def test_a_location_row_with_no_id_is_left_out_not_a_crash(self, book):
        """SF-2 / CR-1: `|Counting House|` crashed 5e with a bare KeyError."""
        from storyforge.elaborate import update_scene
        from storyforge.extract_describe import world_evidence
        ref = os.path.join(book, 'reference')
        with open(os.path.join(ref, 'locations.csv'), 'a') as f:
            f.write('|Counting House|\n')
        update_scene('act1-sc01', ref, {'location': 'Counting House'})
        ev, notes = world_evidence(book, self._ev(book), 'T')
        assert '1 row(s) of reference/locations.csv have no id and are left out' in notes
        assert any('match no entry in locations.csv' in n and 'Counting House' in n
                   for n in notes)

    @pytest.mark.parametrize('content,expected', [
        (b'name|aliases\nX|\n', 'reference/characters.csv has no id column'),
        (b'id|name\n\xff|x\n', 'reference/characters.csv could not be read'),
    ])
    def test_an_unusable_registry_stops_naming_it(self, book, content, expected):
        """SF-3: a registry with no id column was read by name; an unreadable
        one raised a bare error."""
        from storyforge.extract_describe import DescribeFailed, character_evidence
        with open(os.path.join(book, 'reference', 'characters.csv'), 'wb') as f:
            f.write(content)
        with pytest.raises(DescribeFailed, match=expected):
            character_evidence(book, self._ev(book))

    def test_an_absent_registry_is_named_and_5e_skips_with_no_places(
            self, book, mock_api, mock_git, mock_costs, capsys):
        """SF-3 / T-9: an absent locations.csv wrote a world bible with no
        places and a malformed prompt."""
        os.remove(os.path.join(book, 'reference', 'locations.csv'))
        mock_api.set_response_fn(_answer(book))
        _run(book)
        out = capsys.readouterr().out
        assert '5e: reference/locations.csv is absent' in out
        assert '5e skipped: no scene is set in a place locations.csv names' in out
        assert not any('**overview**' in c['prompt'] for c in mock_api.calls)
        assert not os.path.exists(os.path.join(book, 'reference', 'world-bible.md'))

    def test_headers_name_only_the_sources_used(self, book, mock_api, mock_git, mock_costs):
        """SF-4: 5d-5f's headers always claimed commitments, prose and the registries."""
        with open(os.path.join(book, 'reference', 'knowledge.csv'), 'w') as f:
            f.write('id|name|aliases|category|origin\n')
        mock_api.set_response_fn(_answer(book))
        _run(book)
        ref = os.path.join(book, 'reference')
        with open(os.path.join(ref, 'character-bible.md')) as f:
            assert 'from=profile,scenes,characters,prose -->' in f.readline()
        with open(os.path.join(ref, 'world-bible.md')) as f:
            assert 'from=profile,scenes,locations -->' in f.readline()

    @pytest.mark.parametrize('override,expected', [
        ({'habits': ['', ' ']}, 'habits has 0 item(s); at least 1'),
        ({'lineage': []}, 'lineage has 0 item(s); at least 1'),
        ({'pacing': []}, 'pacing has 0 item(s); at least 1'),
        ({'never_does': []}, 'never_does has 0 item(s); at least 1'),
        ({'emotion': {'restraint': 'x', 'key_moments': [], 'physical': 'y'}},
         'emotion.key_moments has no items'),
        ({'dialogue': {'balance': '', 'use': 'u', 'subtext': 's', 'declarations': 'd',
                       'silence': 's'}}, 'dialogue.balance is empty'),
        ({'blend': ''}, 'blend is empty'),
        ({'register': ''}, 'register is empty'),
        ({'pacing': [{'scene_type': 'Office', 'description': 'Keep it slow.'}]},
         'pacing item'),
    ])
    def test_voice_lists_and_fields_are_required(self, book, override, expected):
        """SF-5 / T-13: an empty list rendered as "(none)", read as a fact."""
        from storyforge.extract_describe import ReplyProblems, parse_voice
        _, _, _, voice = _evidence(book)
        with pytest.raises(ReplyProblems) as e:
            parse_voice(_voice_reply(book, **override), voice)
        assert any(expected in p for p in e.value.problems)

    def test_profiles_are_checked_against_characters_csv(self, book):
        """T-13: unknown and repeated profiles; a non-POV profile is fine."""
        from storyforge.extract_describe import ReplyProblems, parse_voice
        _, _, _, voice = _evidence(book)
        reply = json.loads(_voice_reply(book))
        extra = dict(reply['profiles'][0], id='pell')
        parse_voice(json.dumps({**reply, 'profiles': reply['profiles'] + [extra]}), voice)
        bad = dict(reply['profiles'][0], id='nobody')
        with pytest.raises(ReplyProblems) as e:
            parse_voice(json.dumps({**reply, 'profiles': reply['profiles'] + [bad,
                                                                             reply['profiles'][0]]}),
                        voice)
        assert any("profiles names 'nobody'" in p for p in e.value.problems)
        assert any('twice' in p for p in e.value.problems)

    def test_measures_say_what_they_cover_and_skip_small_samples(self, book):
        """SF-6: "whole book" covered 4 of 6 scenes; one short scene gave a
        rate the model was told to trust."""
        from storyforge.extract_describe import voice_evidence
        long = ' '.join(f'The clerk wrote line {i} of the ledger.' for i in range(150))
        _write_scene(book, 'act1-sc01', long)
        ev, notes = voice_evidence(book, self._ev(book), 'T')
        whats = [w for w, _ in ev.measures]
        assert any(w.startswith('the book (4 of 6 scenes, ') for w in whats)
        assert any('words of prose, under 1,000, so it is not measured' in n for n in notes)

    def test_single_quoted_speech_is_not_measured_as_none(self, book):
        """CR-3: a book quoting with ‘…’ read as 0% dialogue."""
        from storyforge.extract_describe import voice_evidence
        text = ' '.join('‘Good day,’ said Dorren to the clerk at the desk.'
                        for _ in range(120))
        _write_scene(book, 'act1-sc01', text)
        ev, notes = voice_evidence(book, self._ev(book), 'T')
        assert any('single quotation marks' in n for n in notes)
        assert all('%' not in v for w, v in ev.measures if 'dialogue share' in w)

    def test_the_dry_run_prints_notes_skips_and_stops(self, book, mock_api, mock_git,
                                                      mock_costs, capsys):
        """SF-7 / CR-4 / T-5: notes were dropped, a skipping step vanished,
        and an unreadable file raised a traceback."""
        def dry():
            cmd_extract._run_phase_5(book, os.path.join(book, 'working', 'logs'),
                                     os.path.join(book, 'working', 'extraction-profile.json'),
                                     False, dry_run=True)
        dry()
        out = capsys.readouterr().out
        assert '5d characters:' in out and '5e world:' in out and '5f voice:' in out
        assert '5d characters: note: 2 of 6 scene(s) have no prose' in out
        os.remove(os.path.join(book, 'reference', 'locations.csv'))
        dry()
        assert '5e world: would skip: no scene is set in a place' in capsys.readouterr().out
        with open(os.path.join(book, 'reference', 'characters.csv'), 'wb') as f:
            f.write(b'id|name\n\xff|x\n')
        dry()
        out = capsys.readouterr().out
        assert '5d characters: would stop: reference/characters.csv could not be read' in out
        assert mock_api.calls == []

    def test_the_fact_cap_and_a_missing_ledger_are_said(self, book, monkeypatch):
        """SF-8 / SF-9."""
        from storyforge import extract_describe as d
        monkeypatch.setattr(d, 'MAX_FACTS_PER_CHARACTER', 1)
        _add_facts(book, ('dorren-hayle', 'trait', 'fixed', 'binding', 'A', ''),
                   ('dorren-hayle', 'trait', 'fixed', 'binding', 'B', ''))
        _, notes, _ = d.character_evidence(book, self._ev(book))
        assert any('have more than 1 established facts' in n and 'dorren-hayle' in n
                   for n in notes)
        os.remove(os.path.join(book, 'reference', 'commitments.csv'))
        _, notes, sources = d.character_evidence(book, self._ev(book))
        assert 'reference/commitments.csv is absent, so the bibles use no established facts' \
            in notes
        assert 'commitments' not in sources

    def test_a_broken_ledger_is_said(self, book):
        """T-10: the LedgerError branch."""
        from storyforge.extract_describe import character_evidence
        with open(os.path.join(book, 'reference', 'commitments.csv'), 'w') as f:
            f.write('nope|header\nx|y\n')
        chars, notes, _ = character_evidence(book, self._ev(book))
        assert any(n.startswith('the ledger could not be read (') for n in notes)
        assert all(c.facts == [] for c in chars)

    def test_5f_names_pov_characters_it_cannot_resolve(self, book):
        """SF-10."""
        from storyforge.elaborate import update_scene
        from storyforge.extract_describe import voice_evidence
        update_scene('act1-sc01', os.path.join(book, 'reference'), {'pov': 'Ghost'})
        _, notes = voice_evidence(book, self._ev(book), 'T')
        assert any('POV name(s) match no character' in n and 'Ghost' in n for n in notes)

    @pytest.mark.parametrize('item,imperative', [
        ('Close third person throughout.', False),
        ('End-of-chapter hooks are rare.', False),
        ('Open fields dominate the middle.', False),
        ('Use of dialect is rare.', False),
        ('Never explains the Spirits.', False),
        ('Always returns to the clock.', False),
        ('The narrator never explains the Spirits.', False),
        ('Never explain the Spirits.', True),
        ('Avoid adverbs.', True),
        ("Don't explain.", True),
        ('Be terse.', True),
        ('Use short sentences.', True),
    ])
    def test_the_imperative_lint(self, item, imperative):
        """SF-11 / T-6: "Close third" and "Never explains" were sent back,
        and two such replies stopped the phase."""
        from storyforge.extract_describe import _IMPERATIVE
        assert bool(_IMPERATIVE.match(item)) is imperative

    def test_open_questions_and_left_open_are_linted(self, book):
        """CR-5 / C-1: parse_world promised the check and didn't run it;
        left_open had none."""
        from storyforge.extract_describe import ReplyProblems, parse_characters, parse_world
        _, chars, world, _ = _evidence(book)
        with pytest.raises(ReplyProblems, match='open_questions item'):
            parse_world(_world_reply(book, open_questions=['Keep the eraser unnamed.']), world)
        reply = json.loads(_characters_reply(book))
        reply['characters'][0]['left_open'] = ['Avoid her past.']
        with pytest.raises(ReplyProblems, match='left_open item'):
            parse_characters(json.dumps(reply), chars)

    def test_speech_tags_not_nearby_names(self):
        """CR-2: Fred's lines were given to Scrooge because "Scrooge's
        nephew" sat within 80 characters."""
        from storyforge.extract_describe import _speech
        text = ('"A merry Christmas, uncle! God save you!" cried a cheerful voice. It was '
                'the voice of Scrooge\'s nephew. "Bah!" said Scrooge. "Humbug and nonsense, '
                'I say to you," said Scrooge. "Christmas a humbug, uncle! You don\'t mean '
                'that," said the nephew.')
        assert _speech(text, ['Scrooge']) == ['Humbug and nonsense, I say to you,']

    @pytest.mark.parametrize('line,kept', [
        ('one two three', False), ('one two three four', True),
        ('x' * 294 + ' a b c', True), ('x' * 295 + ' a b c', False),
    ])
    def test_speech_length_limits(self, line, kept):
        """T-15."""
        from storyforge.extract_describe import _speech
        assert (_speech(f'"{line}" said Dorren.', ['Dorren']) != []) is kept

    @pytest.mark.parametrize('text,kept', [
        ('"Four words right here," said Dorren.', True),
        ('"Four words right here," Dorren said.', True),
        ('"Four words right here" \u2014 said Dorren.', True),
        ('Dorren said, "Four words right here."', True),
        ('Then Dorren said: "Four words right here."', True),
        ('"Four words right here." The rain fell. Later, said Dorren.', False),
        ('Dorren said nothing. "Four words right here."', False),
        ('"Four words right here," said Dorrenson.', False),
        ('"Four words right here," said Dorren\'s nephew.', False),
    ])
    def test_speech_tags_sit_against_the_quote(self, text, kept):
        """T-15 / CR-2."""
        from storyforge.extract_describe import _speech
        assert bool(_speech(text, ['Dorren'])) is kept

    def test_speaker_names_drop_shared_words(self):
        """T-16."""
        from storyforge.extract_describe import _speaker_names
        names = _speaker_names([
            {'id': 'bob', 'name': 'Bob Cratchit', 'aliases': 'Bob'},
            {'id': 'mrs', 'name': 'Mrs Cratchit', 'aliases': ''},
            {'id': 'eb', 'name': 'Ebenezer Scrooge', 'aliases': ''},
            {'id': 'boy', 'name': 'Boy Scrooge Sends for Turkey', 'aliases': ''}])
        assert 'Cratchit' not in names['bob'] and 'Cratchit' not in names['mrs']
        # Live on Carol: the boy's name took "Scrooge" from Ebenezer
        assert names['eb'] == ['Ebenezer Scrooge', 'Ebenezer', 'Scrooge']
        assert 'Scrooge' not in names['boy']

    def test_sample(self):
        from storyforge.extract_describe import _sample
        assert _sample(list(range(20)), 8)[0] == 0 and _sample(list(range(20)), 8)[-1] == 19
        assert len(_sample(list(range(20)), 8)) == 8
        assert _sample([1, 2], 8) == [1, 2]
        assert _sample(list(range(5)), 1) == [0, 4]   # n < 2 can't divide by zero

    def test_a_short_book_does_not_repeat_its_samples(self, book):
        """SF-12."""
        import shutil
        from storyforge.extract_describe import voice_evidence
        for sid in ('act1-sc02', 'new-x1', 'act2-sc01'):
            os.remove(os.path.join(book, 'scenes', f'{sid}.md'))
        ev, _ = voice_evidence(book, self._ev(book), 'T')
        ids = [sid for _, sid, _ in ev.samples]
        assert len(ids) == len(set(ids)) == 1
        shutil.rmtree(os.path.join(book, 'scenes'))

    def test_the_voice_profile_validates(self, book, mock_api, mock_git, mock_costs):
        """TD / T-17: the written profile passes schema's own check, and a
        `|` in model text keeps the columns aligned."""
        from storyforge.extract_describe import VOICE_PROFILE_COLUMNS
        from storyforge.prompts import load_voice_profile
        from storyforge.schema import VOICE_PROFILE_COLUMNS as SCHEMA_COLUMNS
        from storyforge.schema import validate_voice_profile
        assert VOICE_PROFILE_COLUMNS is SCHEMA_COLUMNS
        answer = _answer(book)

        def reply(p):
            if '**lineage**' in p:
                r = json.loads(_voice_reply(book))
                r['profiles'][0]['rhythm'] = 'Long | winding'
                return json.dumps(r)
            return answer(p)
        mock_api.set_response_fn(reply)
        _run(book)
        assert validate_voice_profile(book)['errors'] == []
        _, chars = load_voice_profile(book)
        first = next(iter(chars.values()))
        assert first['dialogue_style'] == 'Clipped.'

    def test_a_graphic_novel_project_skips_phase_5(self, book, mock_api, mock_git, mock_costs,
                                                   capsys):
        """The plan's stated scope: phase 5 describes prose books."""
        yaml = os.path.join(book, 'storyforge.yaml')
        with open(yaml) as f:
            text = f.read()
        with open(yaml, 'w') as f:
            f.write(text.replace('project:\n', 'project:\n  medium: "graphic-novel"\n', 1))
        assert not cmd_extract._run_phase_5(
            book, os.path.join(book, 'working', 'logs'),
            os.path.join(book, 'working', 'extraction-profile.json'), False, False)
        assert 'Graphic-novel project' in capsys.readouterr().out
        assert mock_api.calls == []


class TestBiblesGateAndSteps:
    """T-1 to T-4, T-8, T-11, T-12: the write gate and skips for 5d-5f."""

    @pytest.mark.parametrize('marker,rel,step', [
        ('## Its characters, as the scenes show them', 'character-bible.md', '5d'),
        ('**overview**', 'systems-bible.md', '5e'),
        ('**lineage**', 'voice-profile.csv', '5f'),
    ])
    def test_a_file_changed_during_the_call_stops_the_step_and_those_after(
            self, book, mock_api, mock_git, mock_costs, capsys, marker, rel, step):
        path = os.path.join(book, 'reference', rel)
        answer = _answer(book)

        def reply(prompt):
            if marker in prompt:
                with open(path, 'w') as f:
                    f.write('id|name\nmine|Mine\n' if rel.endswith('.csv') else '# Mine\n')
            return answer(prompt)
        mock_api.set_response_fn(reply)
        _run(book)
        out = capsys.readouterr().out
        assert f'{step} stopped part-way' in out
        with open(path) as f:
            assert 'Mine' in f.read()
        later = {'5d': ['world and systems bibles', 'voice guide'], '5e': ['voice guide'],
                 '5f': []}[step]
        for name in later:
            assert f'{name} skipped: ' in out

    def test_force_and_an_edit_block_both_world_files(self, book, mock_api, mock_git,
                                                      mock_costs, capsys):
        mock_api.set_response_fn(_answer(book))
        _run(book)
        world = os.path.join(book, 'reference', 'world-bible.md')
        with open(world, 'rb') as f:
            before = f.read()
        with open(os.path.join(book, 'reference', 'systems-bible.md'), 'a') as f:
            f.write('\nMine.\n')
        calls = len(mock_api.calls)
        _run(book, force=True)
        out = capsys.readouterr().out
        assert '5e (world and systems bibles) skipped: it writes' in out
        assert not any('**overview**' in c['prompt'] for c in mock_api.calls[calls:])
        with open(world, 'rb') as f:
            assert f.read() == before

    def test_force_regenerates_an_unedited_voice_profile(self, book, mock_api, mock_git,
                                                         mock_costs):
        from storyforge.prompts import load_voice_profile
        mock_api.set_response_fn(_answer(book))
        _run(book)
        answer = _answer(book)
        mock_api.set_response_fn(lambda p: _voice_reply(book, register='Plain.')
                                 if '**lineage**' in p else answer(p))
        _run(book, force=True)
        assert load_voice_profile(book)[0] == {'register': 'Plain.'}

    def test_required_places_are_those_set_twice(self, book):
        """T-8: the fixture's places are each in one scene, so only the
        all-places fallback ran."""
        from storyforge.elaborate import update_scene
        from storyforge.extract_describe import ReplyProblems, parse_world, world_evidence
        ref = os.path.join(book, 'reference')
        update_scene('act1-sc02', ref, {'location': 'Pressure Cartography Office'})
        ev, _ = world_evidence(book, self._scenes(book), 'T')
        office = ev.locations[0].id
        assert ev.required == [office]
        reply = json.loads(_world_reply(book))
        reply['locations'] = [loc for loc in reply['locations'] if loc['id'] == office]
        parse_world(json.dumps(reply), ev)
        reply['locations'] = []
        with pytest.raises(ReplyProblems, match=f'locations leaves out: {office}'):
            parse_world(json.dumps(reply), ev)

    def _scenes(self, book):
        from storyforge.extract_describe import scene_table
        return scene_table(os.path.join(book, 'reference'))

    def test_5d_skips_when_no_character_resolves(self, book, mock_api, mock_git, mock_costs,
                                                 capsys):
        """T-11: and 5e and 5f still run (a skip isn't a stop)."""
        from storyforge.elaborate import update_scene
        ref = os.path.join(book, 'reference')
        for sid in _scene_ids(book):
            update_scene(sid, ref, {'pov': 'Nobody', 'on_stage': 'Nobody',
                                    'characters': 'Nobody'})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        out = capsys.readouterr().out
        assert '5d skipped: no scene names a character' in out
        assert any('**overview**' in c['prompt'] for c in mock_api.calls)

    def test_a_placeholder_title_is_not_used_in_the_bibles(self, book, mock_api, mock_git,
                                                           mock_costs, capsys):
        """T-12."""
        yaml = os.path.join(book, 'storyforge.yaml')
        with open(yaml) as f:
            text = f.read()
        with open(yaml, 'w') as f:
            f.write(text.replace('"The Cartographer\'s Silence"', '"PROJECT_TITLE"', 1))
        answer = _answer(book)
        mock_api.set_response_fn(lambda p: _pitch_reply(
            book, title_meaning={'surface': '', 'deeper': '', 'final': ''})
            if '**logline**' in p else answer(p))
        _run(book)
        ref = os.path.join(book, 'reference')
        for name, heading in (('character-bible.md', 'Character Bible'),
                              ('world-bible.md', 'World Bible'),
                              ('systems-bible.md', 'Systems Bible'),
                              ('voice-guide.md', 'Voice Guide')):
            with open(os.path.join(ref, name)) as f:
                doc = f.read()
            assert f'# Untitled -- {heading}' in doc and 'PROJECT_TITLE' not in doc
        out = capsys.readouterr().out
        assert '5d: storyforge.yaml has no project.title' in out
        assert '5f: storyforge.yaml has no project.title' in out

    @pytest.mark.parametrize('mutate,expected', [
        (lambda r: r['characters'].append(dict(r['characters'][0])), 'twice'),
        (lambda r: r['relationships'].append({'a': r['characters'][0]['id'], 'b': 'nobody',
                                              'nature': 'x'}), 'must name two different'),
        (lambda r: r['relationships'].append({'a': r['characters'][0]['id'],
                                              'b': r['characters'][1]['id'], 'nature': ''}),
         'has no nature'),
        (lambda r: r['pov'][0].update(gives=''), '.gives is empty'),
        (lambda r: r['characters'][0].update(arc_end=''), '.arc_end is empty'),
    ])
    def test_more_character_problems(self, book, mutate, expected):
        """T-14."""
        from storyforge.extract_describe import ReplyProblems, parse_characters
        _, chars, _, _ = _evidence(book)
        reply = json.loads(_characters_reply(book))
        mutate(reply)
        with pytest.raises(ReplyProblems) as e:
            parse_characters(json.dumps(reply), chars)
        assert any(expected in p for p in e.value.problems)

    def test_a_secondary_character_may_leave_fields_empty(self, book):
        """T-14: only role is required of a secondary character."""
        from storyforge.extract_describe import parse_characters
        _, chars, _, _ = _evidence(book)
        reply = json.loads(_characters_reply(book))
        for c in reply['characters']:
            if c['tier'] == 'secondary':
                c.update({k: '' for k in ('physical', 'want', 'need', 'wound', 'lie',
                                          'flaw_as_strength', 'voice', 'relational',
                                          'arc_start', 'arc_turns', 'arc_end')})
        parse_characters(json.dumps(reply), chars)


class TestTimelineAndChapterMap:
    """Step 5g (no model), with the #448 review's regression tests."""

    def _scenes(self, book):
        from storyforge.extract_describe import scene_table
        return scene_table(os.path.join(book, 'reference'))

    def _all_prose(self, book):
        """Give every fixture scene a file (two have none)."""
        for sid in _scene_ids(book):
            path = os.path.join(book, 'scenes', f'{sid}.md')
            if not os.path.exists(path):
                _write_scene(book, sid, 'Text.\n')

    def _set(self, book, **cells):
        from storyforge.elaborate import update_scene
        for sid, values in cells.items():
            update_scene(sid, os.path.join(book, 'reference'), values)

    def test_the_timeline_describes_days_earlier_time_and_frames(self, book):
        from storyforge.extract_describe import render_timeline
        ids = _scene_ids(book)
        self._set(book, **{ids[0]: {'time_mode': 'Frame'},       # any case
                           ids[1]: {'timeline_day': '3', 'timeline_date': 'XXXX-12-24'},
                           ids[2]: {'timeline_day': '1'},
                           ids[3]: {'timeline_day': ''},
                           ids[4]: {'timeline_day': '3', 'time_mode': 'summary'}})
        doc, notes = render_timeline(self._scenes(book), 'T', {}, 'H')
        assert '### Day 3 (XXXX-12-24)' in doc
        assert f'`{ids[2]}`' in doc.split('## Earlier Time')[1]
        assert 'day 1, read after day 3' in doc
        assert f'`{ids[0]}`' in doc.split('## Frame')[1]
        assert f'`{ids[3]}`' in doc.split('## Not Placed in Time')[1]
        assert '(covers a stretch of time from here)' in next(
            line for line in doc.splitlines() if f'`{ids[4]}`' in line)
        assert doc.count(f'`{ids[4]}`') == 1            # listed once
        assert any('have no timeline_day' in n for n in notes)

    def test_the_span_is_timeline_span_not_the_shape(self, book):
        """Review: `timeline` is the shape (linear, frame-narrative); the span
        is `timeline_span`."""
        from storyforge.extract_describe import render_timeline
        doc, _ = render_timeline(self._scenes(book), 'T',
                                 {'timeline': 'frame-narrative', 'timeline_span': 'One night'},
                                 'H')
        assert '**Span:** One night' in doc and '**Shape:** frame-narrative' in doc

    def test_a_prologue_read_first_is_earlier_time(self, book):
        """Review: a flashback read first was listed as the story's present."""
        from storyforge.extract_describe import render_timeline
        ids = _scene_ids(book)
        self._set(book, **{ids[0]: {'timeline_day': '-3650'}, ids[1]: {'timeline_day': '1'}})
        doc, _ = render_timeline(self._scenes(book), 'T', {}, 'H')
        assert '### Day -3650' not in doc
        assert 'day -3650, before day 1' in doc

    @pytest.mark.parametrize('value', ['--1', '3a', '1.5', '+2', '\u0663'])
    def test_an_unreadable_day_is_listed_and_said_not_a_crash(self, book, value):
        """Review: '--1' crashed the phase; non-numbers were called blank."""
        from storyforge.extract_describe import render_timeline
        ids = _scene_ids(book)
        self._set(book, **{ids[0]: {'timeline_day': value}})
        doc, notes = render_timeline(self._scenes(book), 'T', {}, 'H')
        assert 'is not a whole number' in doc
        assert any('not a whole number' in n and ids[0] in n for n in notes)

    def test_no_days_writes_no_timeline_and_says_so(self, book, mock_api, mock_git,
                                                    mock_costs, capsys):
        for sid in _scene_ids(book):
            self._set(book, **{sid: {'timeline_day': ''}})
        mock_api.set_response_fn(_answer(book))
        _run(book)
        out = capsys.readouterr().out
        assert "5g: no scene in the story's present has a timeline_day" in out
        assert not os.path.exists(os.path.join(book, 'reference', 'timeline.md'))

    def test_force_with_nothing_new_says_the_old_file_is_out_of_date(
            self, book, mock_api, mock_git, mock_costs, capsys):
        """Review: the stale extracted file stayed while the note said none
        is written."""
        mock_api.set_response_fn(_answer(book))
        _run(book)
        for sid in _scene_ids(book):
            self._set(book, **{sid: {'timeline_day': ''}})
        _run(book, force=True)
        assert ('5g: reference/timeline.md is kept from an earlier run and is now out of date'
                in capsys.readouterr().out)

    def test_the_chapter_map_comes_from_the_headings(self, book, mock_api, mock_git,
                                                     mock_costs):
        from storyforge.assembly import (_CHAPTER_HEADINGS, get_chapter_scenes,
                                         read_chapter_field)
        ids = _scene_ids(book)
        self._all_prose(book)
        os.remove(os.path.join(book, 'reference', 'chapter-map.csv'))
        _write_scene(book, ids[0], '\ufeff# Stave I: Marley\'s Ghost\n\nMarley was dead.\n')
        _write_scene(book, 'new-x1', '## Stave II | The First Spirit ##\n\nWhen he woke.\n')
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert read_chapter_field(1, book, 'title') == "Stave I: Marley's Ghost"
        assert read_chapter_field(1, book, 'heading') == 'none' in _CHAPTER_HEADINGS
        assert read_chapter_field(1, book, 'part') == '1'
        split = ids.index('new-x1')
        assert get_chapter_scenes(1, book) == ids[:split]
        assert read_chapter_field(2, book, 'title') == 'Stave II / The First Spirit'
        assert get_chapter_scenes(2, book) == ids[split:]
        assert 'reference/chapter-map.csv' in read_provenance(book)

    def test_a_scene_with_no_prose_writes_no_map(self, book):
        """Review: a missing chapter-opening scene merged two chapters."""
        from storyforge.extract_describe import chapter_map_rows
        rows, notes = chapter_map_rows({'a': '# One\n\nText.'},
                                       [{'id': 'a'}, {'id': 'b'}])
        assert rows == [] and 'no prose to read a chapter heading from' in notes[0]

    def test_a_heading_that_is_the_scenes_title_writes_no_map(self, book, mock_api, mock_git,
                                                              mock_costs, capsys):
        """Review: the guess dropped a chapter; the fixture's new-x1 opens
        with its own title."""
        self._all_prose(book)
        os.remove(os.path.join(book, 'reference', 'chapter-map.csv'))
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert ("5g: 1 scene(s) open with a heading that is also their scenes.csv title"
                in capsys.readouterr().out)
        assert not os.path.exists(os.path.join(book, 'reference', 'chapter-map.csv'))

    def test_an_authors_map_is_kept_and_a_header_only_one_is_filled(self, book, mock_api,
                                                                    mock_git, mock_costs,
                                                                    capsys):
        """Review: a header-only map (cleanup tells authors to copy the
        template) read as the author's own."""
        from storyforge.extract_describe import file_state
        from storyforge.schema import CHAPTER_MAP_COLUMNS
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert "reference/chapter-map.csv: kept (the author's own" in capsys.readouterr().out
        with open(os.path.join(book, 'reference', 'chapter-map.csv'), 'w') as f:
            f.write('|'.join(CHAPTER_MAP_COLUMNS) + '\n')
        assert file_state(book, 'reference/chapter-map.csv', {}) == 'header_only'

    def test_scenes_before_the_first_heading_and_frontmatter(self):
        from storyforge.extract_describe import chapter_map_rows
        scenes = [{'id': 'a', 'part': '1'}, {'id': 'b', 'part': '2'}, {'id': 'c', 'part': '2'}]
        rows, notes = chapter_map_rows({'a': 'Prologue text.',
                                        'b': '---\nid: b\n---\n\n# One\n\nText.',
                                        'c': 'More.'}, scenes)
        assert [(r['title'], r['part'], r['scenes']) for r in rows] == \
            [('', '1', 'a'), ('One', '2', 'b;c')]
        assert 'untitled first chapter: a' in notes[0]

    @pytest.mark.parametrize('line,title', [
        ('# One', 'One'), ('### Three ###', 'Three'), ('# C#', 'C#'),
        ('#### Four', None), ('   # Indented', None), ('#NoSpace', None),
    ])
    def test_heading_forms(self, line, title):
        from storyforge.extract_describe import _CHAPTER_HEADING
        m = _CHAPTER_HEADING.match(line)
        assert (m.group(1) if m else None) == title

    def test_the_dry_run_says_what_5g_would_do(self, book, mock_api, mock_git, mock_costs,
                                               capsys):
        """Review: the dry run said nothing about 5g."""
        cmd_extract._run_phase_5(book, os.path.join(book, 'working', 'logs'),
                                 os.path.join(book, 'working', 'extraction-profile.json'),
                                 False, dry_run=True)
        out = capsys.readouterr().out
        assert '5g reference/timeline.md: would write' in out
        assert '5g reference/chapter-map.csv: note: 2 of 6 scene(s) have no prose' in out
        assert not os.path.exists(os.path.join(book, 'reference', 'timeline.md'))

    def test_a_placeholder_title_in_the_timeline(self, book, mock_api, mock_git, mock_costs):
        yaml = os.path.join(book, 'storyforge.yaml')
        with open(yaml) as f:
            text = f.read()
        with open(yaml, 'w') as f:
            f.write(text.replace('"The Cartographer\'s Silence"', '"PROJECT_TITLE"', 1))
        answer = _answer(book)
        mock_api.set_response_fn(lambda p: _pitch_reply(
            book, title_meaning={'surface': '', 'deeper': '', 'final': ''})
            if '**logline**' in p else answer(p))
        _run(book)
        with open(os.path.join(book, 'reference', 'timeline.md')) as f:
            assert f.read().splitlines()[1] == '# Untitled -- Timeline'

    def test_one_refused_file_does_not_stop_the_other(self, book, mock_api, mock_git,
                                                      mock_costs, monkeypatch, capsys):
        """Review: a refused timeline returned before the chapter map was tried."""
        from storyforge import extract_describe as d
        self._all_prose(book)
        _write_scene(book, _scene_ids(book)[0], '# One\n\nText.\n')
        _write_scene(book, 'new-x1', 'Text.\n')
        os.remove(os.path.join(book, 'reference', 'chapter-map.csv'))
        real = d._write_all

        def refuse_timeline(run, files, step, label):
            if files[0][0] == 'reference/timeline.md':
                run.reports.append(f'{label} stopped part-way')
                return False
            return real(run, files, step, label)
        monkeypatch.setattr(d, '_write_all', refuse_timeline)
        mock_api.set_response_fn(_answer(book))
        _run(book)
        assert '5g (timeline) stopped part-way' in capsys.readouterr().out
        assert os.path.exists(os.path.join(book, 'reference', 'chapter-map.csv'))


def test_the_chapter_map_columns_are_one_declaration():
    """Review: three hand copies of the header (and of voice-profile's)."""
    from storyforge.cmd_cleanup import EXPECTED_CSV_SCHEMAS
    from storyforge.common import get_plugin_dir
    from storyforge.schema import CHAPTER_MAP_COLUMNS, VOICE_PROFILE_COLUMNS
    with open(os.path.join(get_plugin_dir(), 'templates', 'production', 'chapter-map.csv')) as f:
        assert f.readline().strip().split('|') == CHAPTER_MAP_COLUMNS
    assert EXPECTED_CSV_SCHEMAS['reference/chapter-map.csv'] == CHAPTER_MAP_COLUMNS
    assert EXPECTED_CSV_SCHEMAS['reference/voice-profile.csv'] == VOICE_PROFILE_COLUMNS


def test_e9_snapshot_skips_only_the_projects_own_working(tmp_path):
    """Review: a path with '/working' anywhere above emptied the snapshot,
    so the rerun gate passed comparing nothing."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'evals'))
    from suites.e9_reference import _snapshot
    project = tmp_path / 'working-copy' / 'book'
    (project / 'reference' / 'working-notes').mkdir(parents=True)
    (project / 'working').mkdir()
    (project / 'reference' / 'working-notes' / 'a.md').write_text('a')
    (project / 'working' / 'log.json').write_text('{}')
    assert set(_snapshot(str(project))) == {os.path.join('reference', 'working-notes', 'a.md')}
