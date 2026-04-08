"""Tests for cmd_migrate command module."""

import os
import pytest
from storyforge.cmd_migrate import (
    parse_args, _read_csv, _slugify, _write_registry,
    step1_rename_scene_type, step2_remove_threads,
    step3_seed_registries,
)


class TestParseArgs:
    """Argument parsing for storyforge migrate."""

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

    def test_both_flags(self):
        args = parse_args(['--dry-run', '--no-commit'])
        assert args.dry_run
        assert args.no_commit


class TestSlugify:
    """_slugify produces clean URL-safe slugs."""

    def test_basic(self):
        assert _slugify('Hello World') == 'hello-world'

    def test_special_chars(self):
        assert _slugify("It's a Test!") == 'its-a-test'

    def test_extra_spaces(self):
        assert _slugify('  too   many  spaces  ') == 'too-many-spaces'

    def test_extra_dashes(self):
        assert _slugify('a--b---c') == 'a-b-c'

    def test_empty(self):
        assert _slugify('') == ''

    def test_unicode_stripped(self):
        assert _slugify('test@#$%value') == 'testvalue'

    def test_preserves_numbers(self):
        assert _slugify('Chapter 1') == 'chapter-1'

    def test_leading_trailing_dashes(self):
        assert _slugify('-test-') == 'test'


class TestReadCsv:
    """_read_csv reads pipe-delimited CSVs correctly."""

    def test_reads_header_and_rows(self, tmp_path):
        csv = tmp_path / 'test.csv'
        csv.write_text('id|name|type\na|Alpha|m\nb|Beta|i\n')
        header, rows = _read_csv(str(csv))
        assert header == ['id', 'name', 'type']
        assert len(rows) == 2
        assert rows[0]['id'] == 'a'
        assert rows[1]['name'] == 'Beta'

    def test_empty_file(self, tmp_path):
        csv = tmp_path / 'empty.csv'
        csv.write_text('')
        header, rows = _read_csv(str(csv))
        assert header == []
        assert rows == []

    def test_missing_file(self, tmp_path):
        header, rows = _read_csv(str(tmp_path / 'missing.csv'))
        assert header == []
        assert rows == []

    def test_header_only(self, tmp_path):
        csv = tmp_path / 'header.csv'
        csv.write_text('id|name\n')
        header, rows = _read_csv(str(csv))
        assert header == ['id', 'name']
        assert rows == []


class TestWriteRegistry:
    """_write_registry writes correct format."""

    def test_writes_header_and_rows(self, tmp_path):
        path = str(tmp_path / 'reg.csv')
        _write_registry(path, 'id|name|aliases', ['abc|Alpha|a', 'def|Beta|b'])
        content = (tmp_path / 'reg.csv').read_text()
        lines = content.strip().splitlines()
        assert lines[0] == 'id|name|aliases'
        assert lines[1] == 'abc|Alpha|a'
        assert lines[2] == 'def|Beta|b'


class TestStep1RenameSceneType:
    """step1_rename_scene_type renames scene_type -> action_sequel."""

    def test_renames_header(self, tmp_path):
        intent = tmp_path / 'scene-intent.csv'
        intent.write_text('id|scene_type|value\na|action|high\n')
        result = step1_rename_scene_type(str(tmp_path), dry_run=False)
        assert result.startswith('done:')
        header = intent.read_text().splitlines()[0]
        assert 'action_sequel' in header
        assert 'scene_type' not in header

    def test_already_renamed(self, tmp_path):
        intent = tmp_path / 'scene-intent.csv'
        intent.write_text('id|action_sequel|value\na|action|high\n')
        result = step1_rename_scene_type(str(tmp_path), dry_run=False)
        assert result.startswith('skip:')

    def test_dry_run_no_write(self, tmp_path):
        intent = tmp_path / 'scene-intent.csv'
        intent.write_text('id|scene_type|value\na|action|high\n')
        result = step1_rename_scene_type(str(tmp_path), dry_run=True)
        assert result.startswith('done:')
        # File should still have old header
        header = intent.read_text().splitlines()[0]
        assert 'scene_type' in header

    def test_missing_file(self, tmp_path):
        result = step1_rename_scene_type(str(tmp_path), dry_run=False)
        assert result.startswith('skip:')


class TestStep2RemoveThreads:
    """step2_remove_threads drops the threads column."""

    def test_removes_column(self, tmp_path):
        intent = tmp_path / 'scene-intent.csv'
        intent.write_text('id|threads|value\na|t1;t2|high\nb|t3|low\n')
        result = step2_remove_threads(str(tmp_path), dry_run=False)
        assert result.startswith('done:')
        lines = intent.read_text().strip().splitlines()
        assert 'threads' not in lines[0]
        assert lines[0] == 'id|value'
        assert lines[1] == 'a|high'

    def test_already_removed(self, tmp_path):
        intent = tmp_path / 'scene-intent.csv'
        intent.write_text('id|value\na|high\n')
        result = step2_remove_threads(str(tmp_path), dry_run=False)
        assert result.startswith('skip:')

    def test_dry_run_no_write(self, tmp_path):
        intent = tmp_path / 'scene-intent.csv'
        intent.write_text('id|threads|value\na|t1|high\n')
        result = step2_remove_threads(str(tmp_path), dry_run=True)
        assert result.startswith('done:')
        assert 'threads' in intent.read_text().splitlines()[0]


class TestStep3SeedRegistries:
    """step3_seed_registries creates registry files from scene data."""

    def test_seeds_values_csv(self, tmp_path):
        ref = tmp_path
        (ref / 'scenes.csv').write_text('id|seq\na|1\n')
        (ref / 'scene-intent.csv').write_text('id|value_at_stake|mice_threads\na|Honor|\n')
        (ref / 'scene-briefs.csv').write_text('id|knowledge_in|knowledge_out\na||knows the truth\n')
        results = step3_seed_registries(str(ref), dry_run=False)
        assert any('values.csv:done:1' in r for r in results)
        assert (ref / 'values.csv').exists()

    def test_seeds_knowledge_csv(self, tmp_path):
        ref = tmp_path
        (ref / 'scenes.csv').write_text('id|seq\na|1\n')
        (ref / 'scene-intent.csv').write_text('id|value_at_stake|mice_threads\na||\n')
        (ref / 'scene-briefs.csv').write_text('id|knowledge_in|knowledge_out\na|prior fact|knows the truth\n')
        results = step3_seed_registries(str(ref), dry_run=False)
        assert any('knowledge.csv:done' in r for r in results)
        assert (ref / 'knowledge.csv').exists()

    def test_skips_existing_registries(self, tmp_path):
        ref = tmp_path
        (ref / 'scenes.csv').write_text('id|seq\na|1\n')
        (ref / 'scene-intent.csv').write_text('id|value_at_stake|mice_threads\na|Honor|\n')
        (ref / 'scene-briefs.csv').write_text('id|knowledge_in|knowledge_out\na||\n')
        (ref / 'values.csv').write_text('id|name|aliases\nhonor|Honor|\n')
        results = step3_seed_registries(str(ref), dry_run=False)
        assert any('values.csv:skip' in r for r in results)
