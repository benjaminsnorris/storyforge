"""Tests for storyforge migrate — project migration to normalized registries.

Covers: parse_args (all flags), individual migration steps, main orchestration
with mocked dependencies, dry-run mode, no-commit mode, idempotency,
and error handling for missing files.
"""

import os
import sys

import pytest

from storyforge.cmd_migrate import (
    parse_args,
    main,
    step1_rename_scene_type,
    step2_remove_threads,
    step3_seed_registries,
    _slugify,
    _read_csv,
    _write_registry,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run
        assert not args.no_commit

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_no_commit(self):
        args = parse_args(['--no-commit'])
        assert args.no_commit

    def test_combined_flags(self):
        args = parse_args(['--dry-run', '--no-commit'])
        assert args.dry_run
        assert args.no_commit


# ============================================================================
# _slugify
# ============================================================================


class TestSlugify:
    """Test the slugify helper."""

    def test_simple_text(self):
        assert _slugify('Hello World') == 'hello-world'

    def test_special_characters(self):
        assert _slugify("It's a test!") == 'its-a-test'

    def test_multiple_spaces(self):
        assert _slugify('a   b   c') == 'a-b-c'

    def test_leading_trailing_whitespace(self):
        assert _slugify('  hello  ') == 'hello'

    def test_preserves_hyphens(self):
        assert _slugify('already-slugged') == 'already-slugged'

    def test_empty_string(self):
        assert _slugify('') == ''


# ============================================================================
# _read_csv
# ============================================================================


class TestReadCsv:
    """Test the CSV reader helper."""

    def test_reads_valid_csv(self, tmp_path):
        csv_file = tmp_path / 'test.csv'
        csv_file.write_text('id|name|value\na|Alice|10\nb|Bob|20\n')
        header, rows = _read_csv(str(csv_file))
        assert header == ['id', 'name', 'value']
        assert len(rows) == 2
        assert rows[0] == {'id': 'a', 'name': 'Alice', 'value': '10'}
        assert rows[1] == {'id': 'b', 'name': 'Bob', 'value': '20'}

    def test_missing_file(self, tmp_path):
        header, rows = _read_csv(str(tmp_path / 'nonexistent.csv'))
        assert header == []
        assert rows == []

    def test_empty_file(self, tmp_path):
        csv_file = tmp_path / 'empty.csv'
        csv_file.write_text('')
        header, rows = _read_csv(str(csv_file))
        assert header == []
        assert rows == []

    def test_header_only(self, tmp_path):
        csv_file = tmp_path / 'header.csv'
        csv_file.write_text('id|name\n')
        header, rows = _read_csv(str(csv_file))
        assert header == ['id', 'name']
        assert rows == []

    def test_strips_crlf(self, tmp_path):
        csv_file = tmp_path / 'crlf.csv'
        csv_file.write_bytes(b'id|name\r\na|Alice\r\n')
        header, rows = _read_csv(str(csv_file))
        assert header == ['id', 'name']
        assert rows[0]['name'] == 'Alice'


# ============================================================================
# step1_rename_scene_type
# ============================================================================


class TestStep1RenameSceneType:
    """Test renaming scene_type -> action_sequel in scene-intent.csv."""

    def test_renames_column(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|scene_type|other\nsc1|action|x\nsc2|sequel|y\n')
        result = step1_rename_scene_type(ref_dir, dry_run=False)
        assert result == 'done:2'
        with open(str(intent_path)) as f:
            header = f.readline()
        assert 'action_sequel' in header
        assert 'scene_type' not in header

    def test_dry_run_does_not_modify(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        original = 'id|scene_type|other\nsc1|action|x\n'
        intent_path.write_text(original)
        result = step1_rename_scene_type(ref_dir, dry_run=True)
        assert result == 'done:1'
        assert intent_path.read_text() == original

    def test_already_renamed(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|action_sequel|other\nsc1|action|x\n')
        result = step1_rename_scene_type(ref_dir, dry_run=False)
        assert result == 'skip:already renamed'

    def test_no_file(self, tmp_path):
        result = step1_rename_scene_type(str(tmp_path), dry_run=False)
        assert result == 'skip:no scene-intent.csv'

    def test_empty_file(self, tmp_path):
        ref_dir = str(tmp_path)
        (tmp_path / 'scene-intent.csv').write_text('')
        result = step1_rename_scene_type(ref_dir, dry_run=False)
        assert result == 'skip:empty file'


# ============================================================================
# step2_remove_threads
# ============================================================================


class TestStep2RemoveThreads:
    """Test removing the threads column from scene-intent.csv."""

    def test_removes_threads_column(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|threads|other\nsc1|t1|x\nsc2|t2|y\n')
        result = step2_remove_threads(ref_dir, dry_run=False)
        assert result == 'done:2'
        with open(str(intent_path)) as f:
            content = f.read()
        assert 'threads' not in content
        # Check remaining columns are preserved
        assert 'id|other' in content

    def test_dry_run_does_not_modify(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        original = 'id|threads|other\nsc1|t1|x\n'
        intent_path.write_text(original)
        result = step2_remove_threads(ref_dir, dry_run=True)
        assert result == 'done:1'
        assert intent_path.read_text() == original

    def test_already_removed(self, tmp_path):
        ref_dir = str(tmp_path)
        (tmp_path / 'scene-intent.csv').write_text('id|other\nsc1|x\n')
        result = step2_remove_threads(ref_dir, dry_run=False)
        assert result == 'skip:already removed'

    def test_no_file(self, tmp_path):
        result = step2_remove_threads(str(tmp_path), dry_run=False)
        assert result == 'skip:no scene-intent.csv'


# ============================================================================
# step3_seed_registries
# ============================================================================


class TestStep3SeedRegistries:
    """Test seeding registry files from scene data."""

    def test_seeds_values_csv(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text(
            'id|value_at_stake|mice_threads\n'
            'sc1|truth|\n'
            'sc2|safety|\n'
        )
        # Need scene-briefs.csv for knowledge seeding
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1||\n')

        results = step3_seed_registries(ref_dir, dry_run=False)
        values_result = [r for r in results if r.startswith('values.csv')][0]
        assert 'done:2' in values_result
        assert os.path.isfile(os.path.join(ref_dir, 'values.csv'))

    def test_does_not_seed_knowledge(self, tmp_path):
        """Knowledge lives in the ledger (step 4); a slugged fact from a
        brief's wording would carry no scene, so it is not seeded."""
        ref_dir = str(tmp_path)
        (tmp_path / 'scene-intent.csv').write_text('id|value_at_stake|mice_threads\nsc1||\n')
        (tmp_path / 'scene-briefs.csv').write_text(
            'id|knowledge_in|knowledge_out\n'
            'sc1|fact-a|fact-b\n'
        )
        results = step3_seed_registries(ref_dir, dry_run=False)
        assert [r.split(':')[0] for r in results] == ['values.csv', 'mice-threads.csv']
        assert not os.path.isfile(os.path.join(ref_dir, 'knowledge.csv'))
        assert not os.path.isfile(os.path.join(ref_dir, 'commitments.csv'))

    def test_seeds_mice_threads_csv(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text(
            'id|value_at_stake|mice_threads\n'
            'sc1||+inquiry:map-anomaly\n'
        )
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1||\n')

        results = step3_seed_registries(ref_dir, dry_run=False)
        mice_result = [r for r in results if r.startswith('mice-threads.csv')][0]
        assert 'done:1' in mice_result

    def test_skips_existing_registry(self, tmp_path):
        ref_dir = str(tmp_path)
        # Pre-create values.csv with entries
        values_path = tmp_path / 'values.csv'
        values_path.write_text('id|name|aliases\ntruth|truth|\n')
        # Intent file
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|value_at_stake|mice_threads\nsc1|truth|\n')
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1||\n')

        results = step3_seed_registries(ref_dir, dry_run=False)
        values_result = [r for r in results if r.startswith('values.csv')][0]
        assert 'skip' in values_result

    def test_dry_run_does_not_create_files(self, tmp_path):
        ref_dir = str(tmp_path)
        intent_path = tmp_path / 'scene-intent.csv'
        intent_path.write_text('id|value_at_stake|mice_threads\nsc1|truth|\n')
        briefs_path = tmp_path / 'scene-briefs.csv'
        briefs_path.write_text('id|knowledge_in|knowledge_out\nsc1|fact-a|\n')

        results = step3_seed_registries(ref_dir, dry_run=True)
        # Files should not be created
        assert not os.path.isfile(os.path.join(ref_dir, 'values.csv'))
        assert not os.path.isfile(os.path.join(ref_dir, 'knowledge.csv'))


# ============================================================================
# main — dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode."""

    def test_dry_run_no_file_modifications(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        # Patch step6_validate since it imports elaborate/enrich/schema
        monkeypatch.setattr('storyforge.cmd_migrate.step6_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--dry-run'])
        # No git commits in dry-run mode
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0

    def test_dry_run_no_branch_creation(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step6_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--dry-run'])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 0


# ============================================================================
# main — no-commit mode
# ============================================================================


class TestMainNoCommit:
    """Test main() with --no-commit flag."""

    def test_no_commit_skips_git(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        # Patch normalize (step4) and validate (step5) which have heavy imports
        monkeypatch.setattr('storyforge.cmd_migrate.step5_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step6_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--no-commit'])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0

    def test_no_commit_no_branch_creation(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step6_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main(['--no-commit'])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 0


# ============================================================================
# main — full run
# ============================================================================


class TestMainFullRun:
    """Test main() full migration path."""

    def test_commits_on_full_run(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step6_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main([])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 1
        assert 'Migrate' in commit_calls[0][1]

    def test_ensures_on_branch(self, mock_api, mock_git, mock_costs,
                               project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step6_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        main([])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 1


# ============================================================================
# main — error handling
# ============================================================================


class TestMainErrors:
    """Test error handling in main()."""

    def test_missing_scenes_csv_exits(self, mock_api, mock_git, mock_costs,
                                      project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        # Remove scenes.csv to trigger the error
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.isfile(scenes_csv):
            os.remove(scenes_csv)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_idempotent_steps(self, mock_api, mock_git, mock_costs,
                              project_dir, monkeypatch):
        """Running migration twice should not cause errors."""
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.step5_normalize',
                            lambda ref_dir, proj_dir: 0)
        monkeypatch.setattr('storyforge.cmd_migrate.step6_validate',
                            lambda ref_dir, proj_dir: '0 passed, 0 failed, 0 skipped')
        # First run
        main(['--no-commit'])
        # Second run (should not raise)
        main(['--no-commit'])
        # Both runs complete successfully — idempotent
        assert mock_api.call_count == 0


# ============================================================================
# _write_registry
# ============================================================================


class TestWriteRegistry:
    """Test registry file writing."""

    def test_writes_header_and_rows(self, tmp_path):
        path = str(tmp_path / 'test.csv')
        _write_registry(path, 'id|name|aliases', ['a|Alice|', 'b|Bob|'])
        with open(path) as f:
            content = f.read()
        assert content == 'id|name|aliases\na|Alice|\nb|Bob|\n'

    def test_empty_rows(self, tmp_path):
        path = str(tmp_path / 'test.csv')
        _write_registry(path, 'id|name', [])
        with open(path) as f:
            content = f.read()
        assert content == 'id|name\n'


# ============================================================================
# Step 4: knowledge.csv and physical-states.csv move into the ledger
# ============================================================================

LEGACY = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fixtures',
                      'legacy-registries')


class TestStep4Ledger:
    def _legacy(self, project_dir):
        """The fixture project before the ledger."""
        import shutil
        ref = os.path.join(project_dir, 'reference')
        os.remove(os.path.join(ref, 'commitments.csv'))
        for name in ('knowledge.csv', 'physical-states.csv'):
            shutil.copy(os.path.join(LEGACY, name), ref)
        return ref

    def _run(self, project_dir, monkeypatch, *argv):
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        main(['--no-commit', *argv])

    def test_moves_the_files_into_the_ledger(self, mock_api, mock_git, mock_costs,
                                              project_dir, monkeypatch, capsys):
        from storyforge import ledger
        expected = open(os.path.join(project_dir, 'reference', 'commitments.csv')).read()
        ref = self._legacy(project_dir)
        self._run(project_dir, monkeypatch)
        assert open(os.path.join(ref, 'commitments.csv')).read() == expected
        assert ledger.legacy_files(ref) == []
        out = capsys.readouterr().out
        assert '[4/10] Move registries into commitments.csv: done (5 knowledge, 4 physical' in out
        # Every quirk on its own line, with counts by kind
        assert '9 change(s) to review: character-id 4, no-scene 5' in out
        assert "physical-states.csv sprained-ankle-tessa: character 'Tessa Merrin' is " \
               "written as its id 'tessa-merrin'" in out
        assert out.count('knowledge.csv ') >= 5
        # Steps 5 and 6 read the ledger after it
        assert '[6/10] Schema validation:' in out

    def test_commit_includes_the_removed_files(self, mock_api, mock_git, mock_costs,
                                               project_dir, monkeypatch):
        self._legacy(project_dir)
        monkeypatch.setattr('storyforge.cmd_migrate.detect_project_root',
                            lambda: project_dir)
        main([])
        assert 'reference/' in mock_git.calls_for('commit_and_push')[0][2]

    def test_idempotent(self, mock_api, mock_git, mock_costs, project_dir,
                        monkeypatch, capsys):
        ref = self._legacy(project_dir)
        self._run(project_dir, monkeypatch)
        first = open(os.path.join(ref, 'commitments.csv')).read()
        capsys.readouterr()
        self._run(project_dir, monkeypatch)
        assert open(os.path.join(ref, 'commitments.csv')).read() == first
        assert '[4/10] Move registries into commitments.csv: skipped' in capsys.readouterr().out

    def test_dry_run_changes_nothing(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch, capsys):
        ref = self._legacy(project_dir)
        before = {n: open(os.path.join(ref, n)).read() for n in os.listdir(ref)
                  if n.endswith('.csv')}
        self._run(project_dir, monkeypatch, '--dry-run')
        after = {n: open(os.path.join(ref, n)).read() for n in os.listdir(ref)
                 if n.endswith('.csv')}
        assert after == before
        out = capsys.readouterr().out
        assert 'dry run (5 knowledge, 4 physical; would remove knowledge.csv, ' \
               'physical-states.csv)' in out
        assert '[6/10] Schema validation: skipped (dry run' in out

    def _assert_stopped(self, project_dir, monkeypatch, capsys, ref, needle):
        # Step 1 would rename this column: a stop must come before it
        intent = os.path.join(ref, 'scene-intent.csv')
        with open(intent) as f:
            text = f.read()
        with open(intent, 'w') as f:
            f.write(text.replace('action_sequel', 'scene_type', 1))
        before = {n: open(os.path.join(ref, n)).read() for n in os.listdir(ref)
                  if n.endswith('.csv')}
        with pytest.raises(SystemExit) as exc:
            self._run(project_dir, monkeypatch)
        assert exc.value.code == 1
        after = {n: open(os.path.join(ref, n)).read() for n in os.listdir(ref)
                 if n.endswith('.csv')}
        assert after == before
        out = capsys.readouterr().out
        assert 'so nothing was changed' in out and needle in out

    def test_a_migration_error_stops_before_any_step(self, mock_api, mock_git, mock_costs,
                                                     project_dir, monkeypatch, capsys):
        ref = self._legacy(project_dir)
        with open(os.path.join(ref, 'knowledge.csv'), 'a') as f:
            f.write('village-vanished|A different statement|||\n')
        self._assert_stopped(project_dir, monkeypatch, capsys, ref,
                             "id 'village-vanished' is on two rows that differ")

    def test_an_existing_ledger_beside_the_old_files_stops(self, mock_api, mock_git,
                                                           mock_costs, project_dir,
                                                           monkeypatch, capsys):
        import shutil
        ref = os.path.join(project_dir, 'reference')
        shutil.copy(os.path.join(LEGACY, 'knowledge.csv'), ref)
        self._assert_stopped(project_dir, monkeypatch, capsys, ref,
                             'still present beside reference/commitments.csv')

    def test_a_round_trip_lost_in_writing_restores_the_old_files(self, project_dir,
                                                                 monkeypatch):
        """A difference that only the written file shows (the writer changed
        a cell) stops it: the ledger is removed and the old files kept."""
        from storyforge import ledger
        ref = self._legacy(project_dir)
        real = ledger.write_ledger

        def lossy(path, rows):
            real(path, [{**r, 'statement': r['statement'] + '!'} for r in rows])
        monkeypatch.setattr(ledger, 'write_ledger', lossy)
        result = ledger.migrate_files(ref)
        assert result.status == 'stopped' and result.problems
        assert not os.path.isfile(os.path.join(ref, 'commitments.csv'))
        assert ledger.legacy_files(ref) == ['knowledge.csv', 'physical-states.csv']


class TestStep5Normalize:
    def test_leaves_cells_whose_parenthetical_text_would_be_dropped(
            self, project_dir, capsys):
        """understory: normalizing stripped "(Hunter residue)" from motifs
        and "(for both — ...)" from value_at_stake."""
        from storyforge.cmd_migrate import step5_normalize
        from storyforge.csv_cli import get_field, update_field
        ref = os.path.join(project_dir, 'reference')
        briefs = os.path.join(ref, 'scene-briefs.csv')
        intent = os.path.join(ref, 'scene-intent.csv')
        update_field(briefs, 'act1-sc01', 'motifs', 'maps; erasure (Hunter residue)')
        update_field(intent, 'act1-sc01', 'characters', 'Dorren Hayle;Tessa Merrin')

        step5_normalize(ref, project_dir)

        assert get_field(briefs, 'act1-sc01', 'motifs') == 'maps; erasure (Hunter residue)'
        assert get_field(intent, 'act1-sc01', 'characters') == 'dorren-hayle;tessa-merrin'
        out = capsys.readouterr().out
        assert 'left as they are' in out and 'act1-sc01 motifs' in out
