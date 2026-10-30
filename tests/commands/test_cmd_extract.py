"""Tests for storyforge extract -- structural data extraction from prose.

Covers parse_args, main orchestration with mocked API/git/costs,
extraction phases (0-3), --force mode, --cleanup-only, --expand,
dry-run mode, scene sorting, and error handling.
"""

import json
import os
import subprocess

import pytest

from storyforge.cmd_extract import (
    parse_args,
    main,
    _build_sorted_scene_ids,
    _load_profile,
    _safe_remove,
    _safe_rmdir,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Test CLI argument parsing for the extract command."""

    def test_defaults(self):
        args = parse_args([])
        assert args.phase is None
        assert not args.cleanup
        assert not args.cleanup_only
        assert not args.force
        assert not args.expand
        assert not args.dry_run

    def test_phase_0(self):
        args = parse_args(['--phase', '0'])
        assert args.phase == 0

    def test_phase_1(self):
        args = parse_args(['--phase', '1'])
        assert args.phase == 1

    def test_phase_2(self):
        args = parse_args(['--phase', '2'])
        assert args.phase == 2

    def test_phase_3(self):
        args = parse_args(['--phase', '3'])
        assert args.phase == 3

    def test_cleanup_flag(self):
        args = parse_args(['--cleanup'])
        assert args.cleanup

    def test_cleanup_only_flag(self):
        args = parse_args(['--cleanup-only'])
        assert args.cleanup_only

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force

    def test_expand_flag(self):
        args = parse_args(['--expand'])
        assert args.expand

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_combined_flags(self):
        args = parse_args(['--phase', '1', '--force', '--dry-run'])
        assert args.phase == 1
        assert args.force
        assert args.dry_run

    def test_cleanup_and_expand(self):
        args = parse_args(['--cleanup', '--expand'])
        assert args.cleanup
        assert args.expand


# ============================================================================
# _build_sorted_scene_ids
# ============================================================================


class TestBuildSortedSceneIds:
    """Test scene ID sorting from files and CSV seq values."""

    def test_returns_all_scene_ids(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        # Fixture has act1-sc01, act1-sc02, act2-sc01, new-x1
        assert len(result) == 4
        assert 'act1-sc01' in result
        assert 'act1-sc02' in result

    def test_sorted_by_seq(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        # act1-sc01 has seq=1, act1-sc02 has seq=2, etc.
        assert result.index('act1-sc01') < result.index('act1-sc02')

    def test_falls_back_to_alpha_sort_without_csv(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        # Remove the scenes.csv to force alphabetical sorting
        csv_path = os.path.join(ref_dir, 'scenes.csv')
        os.remove(csv_path)
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        assert result == sorted(result)

    def test_empty_scenes_dir(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        # Remove all scene files
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        assert result == []


# ============================================================================
# _load_profile
# ============================================================================


class TestLoadProfile:
    """Test extraction profile loading."""

    def test_loads_existing_profile(self, tmp_path):
        profile_file = str(tmp_path / 'profile.json')
        data = {'genre': 'fantasy', 'pov_style': 'third-limited'}
        with open(profile_file, 'w') as f:
            json.dump(data, f)
        result = _load_profile(profile_file)
        assert result == data

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        result = _load_profile(str(tmp_path / 'nonexistent.json'))
        assert result == {}


# ============================================================================
# _safe_remove / _safe_rmdir
# ============================================================================


class TestSafeRemove:
    """Test safe file/directory removal helpers."""

    def test_safe_remove_existing_file(self, tmp_path):
        f = str(tmp_path / 'test.txt')
        with open(f, 'w') as fh:
            fh.write('test')
        _safe_remove(f)
        assert not os.path.exists(f)

    def test_safe_remove_nonexistent(self, tmp_path):
        path = str(tmp_path / 'nonexistent.txt')
        _safe_remove(path)
        assert not os.path.exists(path)

    def test_safe_remove_empty_string(self):
        _safe_remove('')
        assert not os.path.exists('')

    def test_safe_rmdir_existing(self, tmp_path):
        d = str(tmp_path / 'subdir')
        os.makedirs(d)
        with open(os.path.join(d, 'file.txt'), 'w') as f:
            f.write('test')
        _safe_rmdir(d)
        assert not os.path.exists(d)

    def test_safe_rmdir_nonexistent(self, tmp_path):
        path = str(tmp_path / 'nonexistent')
        _safe_rmdir(path)
        assert not os.path.exists(path)

    def test_safe_rmdir_empty_string(self):
        _safe_rmdir('')
        assert not os.path.exists('')


# ============================================================================
# main -- dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        assert mock_api.call_count == 0

    def test_dry_run_no_branch(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0

    def test_dry_run_no_pr(self, mock_api, mock_git, mock_costs,
                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) == 0

    def test_dry_run_phase_0_prints(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--phase', '0'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out

    def test_dry_run_phase_1_prints(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--phase', '1'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out

    def test_dry_run_does_not_need_api_key(self, mock_api, mock_git, mock_costs,
                                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        # Should NOT raise SystemExit
        main(['--dry-run'])
        assert mock_api.call_count == 0


# ============================================================================
# main -- error handling
# ============================================================================


class TestErrorHandling:
    """Test error cases and edge conditions."""

    def test_no_api_key_exits(self, mock_api, mock_git, mock_costs,
                              project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit):
            main([])

    def test_no_scene_files_exits(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Remove all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        with pytest.raises(SystemExit):
            main([])

    def test_cleanup_only_does_not_need_api_key(self, mock_api, mock_git,
                                                  mock_costs, project_dir,
                                                  monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        # Patch the cleanup and validation to not fail
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True,
            'failures': [],
            'checks': ['check1'],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        # Patch run_cleanup to succeed
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        # Should NOT raise SystemExit — cleanup-only skips API key check
        main(['--cleanup-only'])
        assert mock_api.call_count == 0  # no API calls needed


# ============================================================================
# main -- phase execution
# ============================================================================


def _structured(schema_name, **fields):
    """A structured reply for ``extract.<schema_name>``, every field empty
    unless given."""
    from storyforge import extract
    schema = getattr(extract, schema_name)
    reply = {k: [] if schema['properties'][k]['type'] == 'array' else ''
             for k in schema['required']}
    reply.update(fields)
    return json.dumps(reply)


SKELETON_REPLY = _structured('SKELETON_SCHEMA', title='Test', pov='Dorren Hayle',
                             location=['Office'], time_relation='continues',
                             time_gap='an hour')

CHARACTERIZE_REPLY = _structured('CHARACTERIZE_SCHEMA', narrative_mode='third-limited',
                                 tone='literary')


def _chain_or_csv_reply(prompt):
    """Structured JSON for the phases that ask for it, a CSV block for
    everything else."""
    if 'characterize its structure' in prompt:
        return CHARACTERIZE_REPLY
    if 'Extract the narrative intent' in prompt:
        return _structured('INTENT_SCHEMA', function='Sets up the audit.')
    if 'Extract the drafting contract' in prompt:
        return _structured('BRIEF_PARALLEL_SCHEMA', goal='Finish the audit.')
    if 'Extract structural metadata' in prompt:
        return SKELETON_REPLY
    if 'Track the knowledge state' in prompt:
        return json.dumps({'knowledge_in': [], 'knowledge_out': [], 'new_facts': [],
                           'continuity_deps': [], 'scene_summary': 'Something happens.'})
    if 'Track the physical state' in prompt:
        return json.dumps({'physical_state_in': [], 'physical_state_out': [],
                           'new_states': [], 'resolved_states': []})
    if 'Extract every commitment the scene makes' in prompt:
        return json.dumps({'commitments': []})
    return 'id|seq|title\nact1-sc01|1|Test\n'


class TestPhaseExecution:
    """Test individual phase execution through main."""

    def test_phase_0_invokes_api(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        # Provide characterize response
        mock_api.set_response(CHARACTERIZE_REPLY)

        # Patch validate_structure
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        # Should have called invoke_to_file for characterization
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) >= 1

    @pytest.mark.parametrize('reply, stop', [
        ('NARRATIVE_MODE: third-limited', 'end_turn'),   # not the structured answer
        (CHARACTERIZE_REPLY, 'max_tokens'),               # cut off
        (_structured('CHARACTERIZE_SCHEMA', tone='unknown'), 'end_turn'),  # nothing in it
    ])
    def test_phase_0_halts_on_a_bad_profile(self, mock_api, mock_git, mock_costs,
                                            project_dir, monkeypatch, capsys, reply, stop):
        """Every later phase reads the profile; a cut-off one was saved with a
        WARNING and steered them with missing fields."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root', lambda: project_dir)
        mock_api.set_response_dict({'content': [{'type': 'text', 'text': reply}],
                                    'usage': {'input_tokens': 1, 'output_tokens': 1},
                                    'stop_reason': stop})
        with pytest.raises(SystemExit) as exit_info:
            main(['--phase', '0'])
        assert exit_info.value.code == 1
        assert 'ERROR: manuscript characterization failed' in capsys.readouterr().out
        assert mock_api.calls_for('invoke_to_file')[0]['output_schema'] is not None

    def test_phase_0_creates_branch(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response(CHARACTERIZE_REPLY)

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1
        assert branch_calls[0][1] == 'extract'

    def test_phase_1_submits_batch(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        # Mock _run_hone to avoid it calling detect_project_root in cmd_hone
        monkeypatch.setattr('storyforge.cmd_extract._run_hone',
                            lambda plugin_dir, phase: None)

        mock_api.set_response(SKELETON_REPLY)

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '1'])

        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) >= 1
        # One structured reply feeds both scenes.csv and the timeline cues
        from storyforge.extract import SKELETON_SCHEMA
        requests = [r for c in batch_calls for r in c['requests']]
        assert requests and all(
            r['params']['output_config']['format']['schema'] == SKELETON_SCHEMA
            for r in requests)
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.timeline import read_cues
        scenes = _read_csv_as_map(os.path.join(project_dir, 'reference', 'scenes.csv'))
        cues = read_cues(project_dir)
        for r in requests:
            sid = r['custom_id']
            assert scenes[sid]['location']  # filled, or the fixture's own value kept
            assert (cues[sid]['relation'], cues[sid]['gap']) == ('continues', 'an hour')

    def test_phase_1_names_an_unreadable_reply_and_stores_no_cues_for_it(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        """A reply in the old labeled-line shape (or any reply that isn't the
        schema's JSON) is no reply: the scene is named, the run exits 1, and
        no empty cues pass for a fresh read."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_extract._run_hone',
                            lambda plugin_dir, phase: None)
        mock_api.set_response('TITLE: Test\nTIME_RELATION: continues\n')
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')

        from storyforge.elaborate import _read_csv_as_map
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        days_before = {sid: (r.get('timeline_day') or '', r.get('time_mode') or '')
                       for sid, r in _read_csv_as_map(scenes_csv).items()}

        def placed(*a, **kw):
            raise AssertionError('the calendar was placed without fresh cues')
        monkeypatch.setattr('storyforge.timeline.run_assignment', placed)

        with pytest.raises(SystemExit) as exc:
            main(['--phase', '1'])

        assert exc.value.code == 1
        assert 'scenes.csv: the reply for act1-sc01 is unreadable' in capsys.readouterr().out
        from storyforge.timeline import read_cues
        assert read_cues(project_dir) == {}
        # The calendar is one piece: no scene's day moves when any scene's
        # cues are missing
        assert {sid: (r.get('timeline_day') or '', r.get('time_mode') or '')
                for sid, r in _read_csv_as_map(scenes_csv).items()} == days_before

    @staticmethod
    def _phase_1_env(project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_extract._run_hone',
                            lambda plugin_dir, phase: None)
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')

    def test_phase_1_answers_reach_scenes_csv_normalized(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """With --force every skeleton answer replaces the row's value: places
        joined with ';' and, like names, mapped to their registry ids."""
        self._phase_1_env(project_dir, monkeypatch)
        monkeypatch.setattr('storyforge.timeline.run_assignment',
                            lambda *a, **kw: {'assigned': 0, 'unplaced': 0})
        mock_api.set_response(_structured(
            'SKELETON_SCHEMA', title='Test', pov='Dorren',
            location=['the office', 'The Deep Archive', 'unknown'],
            time_relation='later'))

        main(['--phase', '1', '--force'])

        from storyforge.elaborate import _read_csv_as_map
        rows = _read_csv_as_map(os.path.join(project_dir, 'reference', 'scenes.csv'))
        sent = [r['custom_id'] for c in mock_api.calls_for('submit_batch')
                for r in c['requests']]
        assert sent
        for sid in sent:
            assert (rows[sid]['title'], rows[sid]['pov'], rows[sid]['location']) == (
                'Test', 'dorren-hayle', 'cartography-office;deep-archive')

    def test_phase_1_takes_cues_only_from_this_batchs_answers(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """A scene the batch didn't answer (refused, cut off, failed) gets no
        cues even if an earlier run's reply file is still in the log dir; it
        is named and no calendar is placed."""
        self._phase_1_env(project_dir, monkeypatch)
        log_dir = os.path.join(project_dir, 'working', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        for sid in ('act1-sc01', 'act1-sc02'):
            with open(os.path.join(log_dir, f'{sid}.txt'), 'w') as f:
                f.write(SKELETON_REPLY)
        mock_api._batch_results = ['act1-sc01']
        calls = []
        monkeypatch.setattr('storyforge.timeline.run_assignment',
                            lambda *a, **kw: calls.append(a))

        with pytest.raises(SystemExit) as exc:
            main(['--phase', '1'])

        assert exc.value.code == 1
        from storyforge.timeline import read_cues
        assert set(read_cues(project_dir)) == {'act1-sc01'}
        assert calls == []

    def test_phase_1_stores_no_cues_from_a_reply_with_no_scene_values(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        """Cues alone don't make a usable reply: the scene is named as holding
        no values, its cues aren't stored, and no calendar is placed."""
        self._phase_1_env(project_dir, monkeypatch)
        mock_api.set_response(_structured('SKELETON_SCHEMA', title='unknown',
                                          time_relation='later', time_gap='a week'))
        calls = []
        monkeypatch.setattr('storyforge.timeline.run_assignment',
                            lambda *a, **kw: calls.append(a))

        with pytest.raises(SystemExit) as exc:
            main(['--phase', '1'])

        assert exc.value.code == 1
        assert 'scenes.csv: the reply for act1-sc01 holds no values' in capsys.readouterr().out
        from storyforge.timeline import read_cues
        assert read_cues(project_dir) == {}
        assert calls == []

    def test_phase_1_places_no_calendar_when_one_scene_lacks_cues(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """One unreadable reply among good ones: the good scenes' cues are
        stored, but placing the calendar without the bad scene's would move
        its neighbours, so no day is placed and the run exits 1."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_extract._run_hone',
                            lambda plugin_dir, phase: None)
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        from storyforge.cmd_extract import _build_sorted_scene_ids
        first = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'),
                                        os.path.join(project_dir, 'reference'))[0]
        mock_api.set_response_fn(
            lambda prompt: 'not json' if f'## Scene: {first}\n' in prompt else SKELETON_REPLY)
        calls = []
        monkeypatch.setattr('storyforge.timeline.run_assignment',
                            lambda *a, **kw: calls.append(a))

        with pytest.raises(SystemExit) as exc:
            main(['--phase', '1'])

        assert exc.value.code == 1
        assert calls == []
        from storyforge.timeline import read_cues
        cues = read_cues(project_dir)
        assert first not in cues and cues  # the others' cues are kept

    def test_all_phases_run_when_no_phase_flag(self, mock_api, mock_git,
                                                 mock_costs, project_dir,
                                                 monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        # Mock _run_hone to avoid calling detect_project_root in cmd_hone
        monkeypatch.setattr('storyforge.cmd_extract._run_hone',
                            lambda plugin_dir, phase: None)

        mock_api.set_response_fn(_chain_or_csv_reply)

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--force'])  # --force: the answers replace the fixture's values

        # Should have submitted batches for phases 1, 2, and 3a at minimum
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) >= 3

        # Phases 2 and 3a ask for their structured shapes, and their answers
        # reach the CSVs
        from storyforge.extract import BRIEF_PARALLEL_SCHEMA, INTENT_SCHEMA
        def schemas_for(marker):
            return [r['params'].get('output_config', {}).get('format', {}).get('schema')
                    for c in batch_calls for r in c['requests']
                    if marker in r['params']['messages'][0]['content']]
        intent = schemas_for('Extract the narrative intent')
        briefs = schemas_for('Extract the drafting contract')
        assert intent and all(s == INTENT_SCHEMA for s in intent)
        from storyforge.extract import SKELETON_SCHEMA
        skeleton = schemas_for('Extract structural metadata')
        assert skeleton and all(s == SKELETON_SCHEMA for s in skeleton)
        assert briefs and all(s == BRIEF_PARALLEL_SCHEMA for s in briefs)
        from storyforge.elaborate import _read_csv_as_map
        ref = os.path.join(project_dir, 'reference')
        intents = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv')).values()
        briefs = _read_csv_as_map(os.path.join(ref, 'scene-briefs.csv')).values()
        drafted = {f[:-3] for f in os.listdir(os.path.join(project_dir, 'scenes'))}
        assert all(r['function'] == 'Sets up the audit.' for r in intents if r['id'] in drafted)
        assert all(r['goal'] == 'Finish the audit.' for r in briefs if r['id'] in drafted)
        with open(os.path.join(project_dir, 'working', 'extraction-profile.json')) as f:
            assert json.load(f)['narrative_mode'] == 'third-limited'

    def test_commits_after_each_phase(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_extract.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))

        mock_api.set_response(CHARACTERIZE_REPLY)

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) >= 1


# ============================================================================
# main -- force mode
# ============================================================================


class TestForceMode:
    """Test --force flag behavior."""

    def test_force_flag_passed_through(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        # Dry-run with force should work without API key
        main(['--dry-run', '--force'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out


# ============================================================================
# main -- review phase
# ============================================================================


class TestReviewPhase:
    """Test that review phase is called at the end."""

    def test_review_phase_runs(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        mock_api.set_response(CHARACTERIZE_REPLY)

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) >= 1
        assert review_calls[0][1] == 'extraction'


# ============================================================================
# main -- expand mode
# ============================================================================


class TestExpandMode:
    """Test --expand flag behavior."""

    def test_expand_dry_run_no_expansion(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        """In dry-run mode, expansion should not run."""
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--expand'])
        assert mock_api.call_count == 0


# ============================================================================
# Merging extracted values into existing rows
# ============================================================================


class TestMergeFields:
    """Re-extraction on The Great Gatsby with --force kept every old value but
    reported 'Updated scene-intent.csv: 39 scenes'."""

    def test_fills_empty_field(self):
        from storyforge.cmd_extract import _merge_fields
        row = {'id': 's1', 'value_at_stake': ''}
        assert _merge_fields(row, {'value_at_stake': 'truth'}, force=False)
        assert row['value_at_stake'] == 'truth'

    def test_keeps_populated_field_without_force(self):
        from storyforge.cmd_extract import _merge_fields
        row = {'id': 's1', 'value_at_stake': 'truth — specifically'}
        assert not _merge_fields(row, {'value_at_stake': 'truth'}, force=False)
        assert row['value_at_stake'] == 'truth — specifically'

    def test_force_overwrites(self):
        from storyforge.cmd_extract import _merge_fields
        row = {'id': 's1', 'value_at_stake': 'truth — specifically'}
        assert _merge_fields(row, {'value_at_stake': 'truth'}, force=True)
        assert row['value_at_stake'] == 'truth'

    def test_identical_value_is_not_a_change(self):
        from storyforge.cmd_extract import _merge_fields
        row = {'id': 's1', 'value_at_stake': 'truth'}
        assert not _merge_fields(row, {'value_at_stake': 'truth'}, force=True)

    def test_metadata_keys_not_copied(self):
        from storyforge.cmd_extract import _merge_fields
        row = {'id': 's1'}
        _merge_fields(row, {'_confidence': 'high', 'id': 'other'}, force=True)
        assert row == {'id': 's1'}


class TestPhase2Force:
    def test_force_reaches_phase_2(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        seen = {}

        def fake_phase_2(*args, **kwargs):
            seen['force'] = args[6]

        monkeypatch.setattr('storyforge.cmd_extract._run_phase_2', fake_phase_2)
        monkeypatch.setattr('storyforge.cmd_extract._run_hone', lambda *a, **k: None)

        main(['--phase', '2', '--force'])

        assert seen['force'] is True


class TestMergeBatchResults:
    """Extracting The Great Gatsby wrote briefs for 1 of 39 scenes: the loop
    asked "is the CSV empty?" per scene, so only the first scene was added."""

    def _setup(self, tmp_path, ids):
        from storyforge.elaborate import _FILE_MAP
        csv_path = tmp_path / 'scene-briefs.csv'
        csv_path.write_text('|'.join(_FILE_MAP['scene-briefs.csv']) + '\n')
        log_dir = tmp_path / 'logs'
        log_dir.mkdir()
        for sid in ids:
            (log_dir / f'{sid}.txt').write_text(
                _structured('BRIEF_PARALLEL_SCHEMA', goal=f'goal of {sid}', outcome='no'))
        return str(csv_path), str(log_dir)

    def _rows(self, csv_path):
        import csv as _csv
        with open(csv_path) as f:
            return {r['id']: r for r in _csv.DictReader(f, delimiter='|')}

    def test_empty_csv_gets_every_scene(self, tmp_path):
        from storyforge.cmd_extract import _merge_batch_results
        from storyforge.extract import parse_brief_parallel_response
        ids = ['s1', 's2', 's3']
        csv_path, log_dir = self._setup(tmp_path, ids)

        count = _merge_batch_results(csv_path, 'scene-briefs.csv', ids, log_dir,
                                     parse_brief_parallel_response, {}, False)

        rows = self._rows(csv_path)
        assert count == 3
        assert [rows[sid]['goal'] for sid in ids] == [
            'goal of s1', 'goal of s2', 'goal of s3']

    def test_missing_scene_added_to_partial_csv(self, tmp_path):
        from storyforge.cmd_extract import _merge_batch_results
        from storyforge.extract import parse_brief_parallel_response
        csv_path, log_dir = self._setup(tmp_path, ['s1', 's2'])
        _merge_batch_results(csv_path, 'scene-briefs.csv', ['s1'], log_dir,
                             parse_brief_parallel_response, {}, False)

        count = _merge_batch_results(csv_path, 'scene-briefs.csv', ['s1', 's2'],
                                     log_dir, parse_brief_parallel_response, {}, False)

        assert count == 1   # s2 added; s1 unchanged
        assert set(self._rows(csv_path)) == {'s1', 's2'}


    def test_scene_without_a_reply_is_named_and_left_alone(self, tmp_path, capsys,
                                                            monkeypatch):
        """SF-2: a refused, cut-off or errored reply leaves no .txt; the scene
        was skipped without a word, and on a new project it had no row."""
        from storyforge import cmd_extract
        from storyforge.extract import parse_brief_parallel_response
        monkeypatch.setattr(cmd_extract, '_unanswered', {})
        csv_path, log_dir = self._setup(tmp_path, ['s1', 's3'])

        count = cmd_extract._merge_batch_results(
            csv_path, 'scene-briefs.csv', ['s1', 's2', 's3'], log_dir,
            parse_brief_parallel_response, {}, False)

        assert count == 2 and set(self._rows(csv_path)) == {'s1', 's3'}
        out = capsys.readouterr().out
        assert 'WARNING: scene-briefs.csv: no usable reply for 1 scene(s)' in out
        assert 'scene-briefs.csv has no row for s2' in out
        assert cmd_extract._unanswered == {'scene-briefs.csv': ['s2']}


    def test_unreadable_reply_is_named_and_left_alone(self, tmp_path, capsys, monkeypatch):
        """A reply that is not the structured answer (here the old KEY: value
        form) is reported like a missing one, never merged."""
        from storyforge import cmd_extract
        from storyforge.extract import parse_brief_parallel_response
        monkeypatch.setattr(cmd_extract, '_unanswered', {})
        csv_path, log_dir = self._setup(tmp_path, ['s1'])
        with open(os.path.join(log_dir, 's1.txt'), 'w') as f:
            f.write('GOAL: goal of s1\n')

        count = cmd_extract._merge_batch_results(
            csv_path, 'scene-briefs.csv', ['s1'], log_dir,
            parse_brief_parallel_response, {}, False)

        assert count == 0
        assert 'the reply for s1 is unreadable' in capsys.readouterr().out
        assert cmd_extract._unanswered == {'scene-briefs.csv': ['s1']}


    def test_a_reply_with_no_values_is_unanswered(self, tmp_path, capsys, monkeypatch):
        """SF4: valid JSON with every field unknown or empty merged nothing
        (or a blank new row counted as changed) without a word."""
        from storyforge import cmd_extract
        from storyforge.extract import parse_brief_parallel_response
        monkeypatch.setattr(cmd_extract, '_unanswered', {})
        csv_path, log_dir = self._setup(tmp_path, ['s1'])
        with open(os.path.join(log_dir, 's1.txt'), 'w') as f:
            f.write(_structured('BRIEF_PARALLEL_SCHEMA', goal='unknown', outcome='unknown'))

        count = cmd_extract._merge_batch_results(
            csv_path, 'scene-briefs.csv', ['s1'], log_dir,
            parse_brief_parallel_response, {}, False)

        assert count == 0
        assert 'the reply for s1 holds no values' in capsys.readouterr().out
        assert cmd_extract._unanswered == {'scene-briefs.csv': ['s1']}


class TestLoadProfile:
    """SF6: --phase 2/3 without a profile ran without a word; a corrupt one
    crashed with a traceback."""

    def test_missing_profile_is_reported(self, tmp_path, capsys):
        from storyforge.cmd_extract import _load_profile
        assert _load_profile(str(tmp_path / 'none.json')) == {}
        assert 'WARNING: no manuscript profile' in capsys.readouterr().out

    def test_corrupt_profile_stops_the_run(self, tmp_path, capsys):
        from storyforge.cmd_extract import _load_profile
        path = tmp_path / 'p.json'
        path.write_text('{not json')
        with pytest.raises(SystemExit) as exit_info:
            _load_profile(str(path))
        assert exit_info.value.code == 1
        assert 'is unreadable' in capsys.readouterr().out


class TestRecordPhysicalStates:
    """Phase 3c parsed the states a scene resolves but never wrote them to
    the registry, so every state stayed resolves=never (F-057). On Pride and
    Prejudice all 16 state-disappearance flags fell on the scene the model
    had said resolves the state, and Elizabeth's Hunsford headache gated 69
    later scenes."""

    def _rows(self, ref_dir):
        from storyforge import ledger
        return ledger.view_map(str(ref_dir), 'physical')

    def test_resolution_written_to_registry(self, tmp_path):
        from storyforge.cmd_extract import _record_physical_states
        phys = tmp_path
        _record_physical_states(str(phys), 'proposal', [
            {'id': 'elizabeth-headache', 'character': 'elizabeth-bennet',
             'description': 'a headache', 'category': 'fatigue',
             'action_gating': 'true'}], [], {})
        assert self._rows(phys)['elizabeth-headache']['resolves'] == 'never'
        _record_physical_states(str(phys), 'arrival-in-london', [], ['elizabeth-headache'], {})
        row = self._rows(phys)['elizabeth-headache']
        assert row['acquired'] == 'proposal'
        assert row['resolves'] == 'arrival-in-london'

    def test_state_resolved_in_scene_that_acquires_it(self, tmp_path):
        from storyforge.cmd_extract import _record_physical_states
        phys = tmp_path
        _record_physical_states(str(phys), 'lambton-news',
                                [{'id': 'trembling', 'character': 'elizabeth-bennet'}],
                                ['trembling'], {})
        assert self._rows(phys)['trembling']['resolves'] == 'lambton-news'

    def test_first_resolution_kept_and_unknown_ignored(self, tmp_path):
        from storyforge.cmd_extract import _record_physical_states
        phys = tmp_path
        _record_physical_states(str(phys), 'a', [{'id': 'cough', 'character': 'kitty'}], [], {})
        _record_physical_states(str(phys), 'b', [], ['cough', 'not-a-state'], {})
        _record_physical_states(str(phys), 'c', [], ['cough'], {})
        rows = self._rows(phys)
        assert rows['cough']['resolves'] == 'b'
        assert 'not-a-state' not in rows


class TestKnowledgeChainOffersOnlyEarlierFacts:
    """F-123: a forced re-run seeds phase 3b from the ledger, and each scene's
    prompt offered every fact in it, so a scene's knowledge_in could name a
    fact the book reveals later. Only facts established before the scene in
    reading order (plus backstory) are offered, or resolved."""

    def _run(self, project_dir, mock_api, monkeypatch, replies, force=True):
        from storyforge import cmd_extract, extract, ledger
        ref_dir = os.path.join(project_dir, 'reference')
        rows = ledger.load_from(ref_dir)
        view = ledger.knowledge_view(rows)
        view[0]['origin'] = 'act1-sc02'     # map-anomaly-exists
        view[1]['origin'] = 'act2-sc01'     # village-vanished: revealed later
        view[2]['origin'] = 'burnside'      # archive-erasure: a renamed scene
        ledger.save_to(ref_dir, ledger.replace_view(rows, 'knowledge', view,
                                                    origin='author', introduced_by='author'),
                       command='test')
        offered = {}

        def knowledge_prompt(scene_id, *args, known_facts=None, **kw):
            offered[scene_id] = dict(known_facts or {})
            return f'KNOWLEDGE {scene_id}'
        monkeypatch.setattr(extract, 'build_knowledge_prompt', knowledge_prompt)
        monkeypatch.setattr(extract, 'build_physical_state_prompt',
                            lambda scene_id, *a, **kw: f'PHYSICAL {scene_id}')

        def reply(prompt):
            if prompt.startswith('KNOWLEDGE '):
                return replies.get(prompt.split()[1], _structured('KNOWLEDGE_SCHEMA'))
            if prompt.startswith('PHYSICAL '):
                return _structured('PHYSICAL_STATE_SCHEMA')
            return _structured('BRIEF_PARALLEL_SCHEMA')
        mock_api.set_response_fn(reply)
        order = cmd_extract._build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref_dir)
        cmd_extract._run_phase_3(order, project_dir, os.path.join(project_dir, 'scenes'),
                                 ref_dir, os.path.join(project_dir, 'working', 'logs'),
                                 os.path.join(project_dir, 'working', 'profile.json'),
                                 force=force, dry_run=False)
        return offered, ledger.view_map(ref_dir, 'knowledge')

    BACKSTORY = {'archive-erasure', 'subsidence-not-natural', 'council-dismisses-evidence'}

    def test_a_scene_is_offered_only_facts_from_earlier_scenes(
            self, project_dir, mock_api, mock_git, mock_costs, monkeypatch):
        replies = {'act1-sc02': _structured(
            'KNOWLEDGE_SCHEMA', knowledge_out=['A map anomaly exists in the pressure records'])}
        offered, _ = self._run(project_dir, mock_api, monkeypatch, replies)
        # Backstory, and archive-erasure, whose scene is no scene
        assert set(offered['act1-sc01']) == self.BACKSTORY
        assert set(offered['act1-sc02']) == self.BACKSTORY     # not its own fact
        assert set(offered['new-x1']) == self.BACKSTORY | {'map-anomaly-exists'}
        assert 'village-vanished' not in offered['act2-sc01']   # established there
        assert offered['new-x1']['map-anomaly-exists'] == \
            'A map anomaly exists in the pressure records'

    def test_a_fact_this_run_never_established_is_not_offered(
            self, project_dir, mock_api, mock_git, mock_costs, monkeypatch):
        """F-123 on v1.93.0: the ledger places map-anomaly-exists at act1-sc02
        (the last run's answer). A forced run whose act1-sc02 reply omits it
        must not offer it to later scenes: nothing in this run has shown it,
        and a later knowledge_in naming it would be flagged (P&P: 32 flags)."""
        offered, _ = self._run(project_dir, mock_api, monkeypatch, {})
        assert set(offered['new-x1']) == self.BACKSTORY
        assert 'map-anomaly-exists' not in offered['act2-sc01']

    def test_an_unforced_run_counts_what_earlier_briefs_already_hold(
            self, project_dir, mock_api, mock_git, mock_costs, monkeypatch):
        """Without force an empty reply keeps the brief's knowledge_out, so
        the fact it holds counts as shown for the scenes after it."""
        from storyforge.elaborate import update_scene
        update_scene('act1-sc02', os.path.join(project_dir, 'reference'),
                     {'knowledge_out': 'map-anomaly-exists'})
        offered, _ = self._run(project_dir, mock_api, monkeypatch, {}, force=False)
        assert 'map-anomaly-exists' in offered['new-x1']

    def test_a_later_facts_wording_is_not_resolved_to_its_id(
            self, project_dir, mock_api, mock_git, mock_costs, monkeypatch):
        from storyforge.elaborate import get_scene
        replies = {'act1-sc01': _structured(
            'KNOWLEDGE_SCHEMA', knowledge_out=['missing village', 'archive-erasure'])}
        self._run(project_dir, mock_api, monkeypatch, replies)
        ref_dir = os.path.join(project_dir, 'reference')
        assert get_scene('act1-sc01', ref_dir)['knowledge_out'] == \
            'missing village;archive-erasure'

    def test_an_earlier_declaration_moves_the_facts_origin(
            self, project_dir, mock_api, mock_git, mock_costs, monkeypatch):
        replies = {'act1-sc01': _structured(
            'KNOWLEDGE_SCHEMA', knowledge_out=['village-vanished'],
            new_facts=[{'id': 'village-vanished', 'name': 'A village vanished',
                        'category': 'state-change'}])}
        offered, facts = self._run(project_dir, mock_api, monkeypatch, replies)
        assert facts['village-vanished']['origin'] == 'act1-sc01'
        # The first declaration's row is kept: only its scene moved
        assert facts['village-vanished']['name'] == \
            'A village has vanished from the pressure maps'
        assert 'village-vanished' in offered['act1-sc02']


class TestFactsWithNoKnownScene:
    """shared-dark's `burnside`, `playground`, `site-review`: a fact whose
    scene_id names no scene was never offered, and nothing said so."""

    def test_offered_like_backstory_with_a_warning(self, project_dir, mock_api, mock_git,
                                                   mock_costs, monkeypatch, capsys):
        offered, _ = TestKnowledgeChainOffersOnlyEarlierFacts()._run(
            project_dir, mock_api, monkeypatch, {})
        assert all('archive-erasure' in facts for facts in offered.values())
        out = capsys.readouterr().out
        assert ('WARNING: 1 knowledge fact(s) name a scene that is not in scenes.csv'
                in out and 'archive-erasure (burnside)' in out)

    def test_prune_keeps_one_a_brief_uses(self, project_dir):
        from storyforge import ledger
        from storyforge.cmd_extract import _prune_registries
        ref = os.path.join(project_dir, 'reference')
        rows = ledger.load_from(ref)
        used = next(r for r in rows if r['id'] == 'map-anomaly-exists')
        used['scene_id'] = 'burnside'
        ledger.save_to(ref, rows, command='test')
        _prune_registries(ref, set(), set())
        assert ledger.view_map(ref, 'knowledge')['map-anomaly-exists']['origin'] == 'burnside'
