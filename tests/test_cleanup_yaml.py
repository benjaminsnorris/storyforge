"""Regression tests for `cleanup`'s handling of storyforge.yaml.

- **#314** — `migrate_storyforge_yaml` set `modified = True` unconditionally and
  opened both ends in text mode, so every `storyforge cleanup` rewrote the file
  and silently normalized its line endings. That also defeated
  `common.update_artifact_entry`, which preserves them on the same file.
- **#315** — two silent value-reading behaviours, both correct and neither
  reported: malformed quoting degrades leniently, and ` #` opens a comment, so
  `title: Book #2` becomes `Book` with no signal until it reaches an epub.
"""

import hashlib
import os

import pytest

from storyforge.cmd_cleanup import (
    _check_crlf,
    _check_yaml_scalars,
    migrate_storyforge_yaml,
)
from storyforge.common import yaml_scalar_issue


#: A file with every section `migrate_storyforge_yaml` would otherwise add, so a
#: run over it has nothing legitimate to do. That is the precondition for testing
#: idempotence at all — with a section missing, a rewrite is correct.
COMPLETE_YAML = '''project:
  title: "The Lantern Folk"
artifacts:
  world_bible:
    exists: false
    path: reference/world-bible.md
    updated:

scene_extensions: []

evaluation:
  custom_evaluators: []

production:
  author: Ben Norris

parts:
  - number: 1
    title: "Part One"
'''


def write_yaml(project_dir, text, *, crlf=False):
    path = os.path.join(project_dir, 'storyforge.yaml')
    data = text.replace('\n', '\r\n') if crlf else text
    with open(path, 'wb') as f:
        f.write(data.encode())
    return path


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


# ===========================================================================
# #314 — write only on a real change, and leave line endings alone
# ===========================================================================

class TestMigrateWritesOnlyWhenSomethingChanged:

    def test_a_complete_file_is_left_byte_identical(self, tmp_path):
        path = write_yaml(str(tmp_path), COMPLETE_YAML)
        before = digest(path)

        migrate_storyforge_yaml(str(tmp_path))

        assert digest(path) == before

    def test_a_complete_file_is_not_rewritten_at_all(self, tmp_path):
        """Byte-identical is not enough — `modified = True` was unconditional, so
        every run rewrote the file and dirtied its mtime."""
        path = write_yaml(str(tmp_path), COMPLETE_YAML)
        before = os.stat(path).st_mtime_ns

        migrate_storyforge_yaml(str(tmp_path))

        assert os.stat(path).st_mtime_ns == before

    def test_a_missing_section_is_still_added(self, tmp_path):
        """The write must still happen when there is something to do."""
        path = write_yaml(
            str(tmp_path), COMPLETE_YAML.replace('scene_extensions: []\n', ''))

        migrate_storyforge_yaml(str(tmp_path))

        assert 'scene_extensions: []' in open(path).read()

    def test_a_missing_file_is_a_no_op(self, tmp_path):
        migrate_storyforge_yaml(str(tmp_path))
        assert not os.path.exists(os.path.join(tmp_path, 'storyforge.yaml'))


class TestMigratePreservesLineEndings:

    def test_crlf_survives_a_no_op_run(self, tmp_path):
        path = write_yaml(str(tmp_path), COMPLETE_YAML, crlf=True)
        before = digest(path)

        migrate_storyforge_yaml(str(tmp_path))

        assert digest(path) == before

    def test_crlf_survives_a_run_that_changes_something(self, tmp_path):
        path = write_yaml(
            str(tmp_path), COMPLETE_YAML.replace('scene_extensions: []\n', ''),
            crlf=True)

        migrate_storyforge_yaml(str(tmp_path))

        raw = open(path, 'rb').read()
        assert b'scene_extensions: []' in raw
        # The inserted line matches the file, so the result is not mixed. A
        # hardcoded '\n' in the inserted block would leave one bare LF behind.
        assert raw.replace(b'\r\n', b'').count(b'\n') == 0

    def test_a_crlf_project_still_receives_migrations(self, tmp_path):
        """Preserving endings means the patterns must tolerate CRLF.

        `^artifacts:\\n` does not match `artifacts:\\r\\n`. Before #314 the
        text-mode read hid that by normalizing first, so switching to
        `newline=''` without fixing the patterns would have silently stopped
        migrating CRLF projects — trading a cosmetic bug for a functional one.
        """
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'characters.csv').write_text('id|name\n')
        path = write_yaml(str(tmp_path), COMPLETE_YAML, crlf=True)

        migrate_storyforge_yaml(str(tmp_path))

        raw = open(path, 'rb').read()
        assert b'  characters:\r\n' in raw
        assert b'    path: reference/characters.csv\r\n' in raw
        assert raw.replace(b'\r\n', b'').count(b'\n') == 0

    def test_lf_stays_lf(self, tmp_path):
        path = write_yaml(str(tmp_path), COMPLETE_YAML)
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'characters.csv').write_text('id|name\n')

        migrate_storyforge_yaml(str(tmp_path))

        assert b'\r\n' not in open(path, 'rb').read()

    def test_an_artifact_path_with_a_backslash_does_not_corrupt(self, tmp_path):
        """The inserted block reaches `re.sub` as a *replacement*.

        With `r'\\1' + insert`, a backslash in the path is read as a group
        reference — so the insert either raises or silently mangles. A function
        replacement takes the string literally.
        """
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'characters.csv').write_text('id|name\n')
        path = write_yaml(str(tmp_path), COMPLETE_YAML)

        migrate_storyforge_yaml(str(tmp_path))

        assert 'path: reference/characters.csv' in open(path).read()


class TestCrlfIsReportedForStoryforgeYaml:

    def test_a_crlf_yaml_is_reported(self, tmp_path):
        """Removing the silent conversion without reporting it moves the silence
        rather than closing it — nothing else converts this file now."""
        write_yaml(str(tmp_path), COMPLETE_YAML, crlf=True)

        findings = _check_crlf(str(tmp_path))

        assert len(findings) == 1
        assert findings[0]['type'] == 'crlf_line_endings'
        assert 'storyforge.yaml' in findings[0]['file']
        assert findings[0]['severity'] == 'warning'

    def test_an_lf_yaml_is_not_reported(self, tmp_path):
        write_yaml(str(tmp_path), COMPLETE_YAML)
        assert _check_crlf(str(tmp_path)) == []

    def test_the_remedy_covers_the_yaml_too(self, tmp_path):
        write_yaml(str(tmp_path), COMPLETE_YAML, crlf=True)
        assert 'storyforge.yaml' in _check_crlf(str(tmp_path))[0]['command']


# ===========================================================================
# #315 — say when a value was probably not read as its author meant
# ===========================================================================

class TestYamlScalarIssue:

    @pytest.mark.parametrize('raw,expected', [
        ('Book #2', 'comment_truncated'),
        ('Part #1: The Blank', 'comment_truncated'),
        ('"unterminated', 'unterminated_quote'),
        ("'unterminated", 'unterminated_quote'),
        ('"quoted" then junk', 'trailing_after_quote'),
        ('""Unicorn Tail""', 'trailing_after_quote'),
    ])
    def test_it_finds_the_issue(self, raw, expected):
        assert yaml_scalar_issue(raw) == expected

    @pytest.mark.parametrize('raw', [
        '',
        '   ',
        'plain value',
        'a#b',                              # no space: part of the value
        '#ff8800',                          # a colour, not a comment
        'fantasy  # default, literary-fiction',   # the template's own form
        '  # Optional: series title',       # unset key carrying its comment
        '"All Good"  # a comment',          # quoted, then a real comment
        "'Children''s book'",
        '"tagged #1 of 3"',                 # inside quotes, so literal
    ])
    def test_it_stays_silent(self, raw):
        assert yaml_scalar_issue(raw) is None

    def test_a_space_after_the_hash_reads_as_a_comment(self):
        """The documented limit of the heuristic.

        `Book # 2` is not reported, because a `#` followed by a space is how a
        comment is conventionally written and the shipped template puts one on
        nearly every key. Erring this way keeps the finding usable; erring the
        other way buries it on every project.
        """
        assert yaml_scalar_issue('Book # 2') is None

    def test_it_never_changes_what_the_parser_returns(self):
        """Reporting only. The parser's behaviour is deliberate in both cases and
        cannot change without reintroducing #277."""
        from storyforge.common import parse_yaml_scalar
        for raw in ['Book #2', '"unterminated', '""Unicorn Tail""',
                    'fantasy  # default', 'a#b']:
            before = parse_yaml_scalar(raw)
            yaml_scalar_issue(raw)
            assert parse_yaml_scalar(raw) == before


class TestCheckYamlScalars:

    def test_it_reports_each_kind_with_its_own_remedy(self, tmp_path):
        write_yaml(str(tmp_path), (
            'project:\n'
            '  title: Book #2\n'
            '  subtitle: "unterminated\n'
            '  tagline: "quoted" then junk\n'))

        by_type = {f['type']: f for f in _check_yaml_scalars(str(tmp_path))}

        assert set(by_type) == {'yaml_value_truncated_by_comment',
                                'yaml_unterminated_quote',
                                'yaml_trailing_after_quote'}
        # Three distinct remedies, because the three fixes differ. A shared one
        # would fit at most one, which is the inert-advice problem.
        actions = {f['action'] for f in by_type.values()}
        assert len(actions) == 3
        assert all(f['severity'] == 'warning' for f in by_type.values())
        assert all(f['file'] == 'storyforge.yaml' for f in by_type.values())

    def test_the_detail_names_the_line_and_the_key(self, tmp_path):
        write_yaml(str(tmp_path), 'project:\n  title: Book #2\n')

        detail = _check_yaml_scalars(str(tmp_path))[0]['detail']

        assert 'line 2' in detail
        assert '`title`' in detail
        assert 'Book' in detail

    def test_a_pipe_in_the_value_cannot_break_the_report(self, tmp_path):
        """`working/cleanup-report.csv` is unquoted pipe-delimited, so a `|`
        shifts every later column and empties the trailing `status` cell that
        `skills/forge/SKILL.md` scans — a row that silences its own finding."""
        write_yaml(str(tmp_path), 'project:\n  title: Vol #2 | extra\n')

        findings = _check_yaml_scalars(str(tmp_path))

        assert findings
        assert all('|' not in f['detail'] for f in findings)

    def test_a_newline_cannot_break_the_report(self, tmp_path):
        write_yaml(str(tmp_path), 'project:\n  title: Book #2\n')
        assert all('\n' not in f['detail']
                   for f in _check_yaml_scalars(str(tmp_path)))

    def test_the_shipped_template_produces_no_findings(self, plugin_dir,
                                                       tmp_path):
        """The check is worthless if it fires on a fresh project.

        The template puts a real trailing comment on nearly every key, so this is
        the test that keeps the ` #` heuristic honest.
        """
        import shutil
        shutil.copy(os.path.join(plugin_dir, 'templates', 'storyforge.yaml'),
                    os.path.join(tmp_path, 'storyforge.yaml'))

        assert _check_yaml_scalars(str(tmp_path)) == []

    def test_the_fixture_project_produces_no_findings(self, project_dir):
        assert _check_yaml_scalars(project_dir) == []

    def test_a_missing_file_produces_no_findings(self, tmp_path):
        assert _check_yaml_scalars(str(tmp_path)) == []

    def test_an_undecodable_file_is_reported_not_raised(self, tmp_path):
        """One check inside the single finding collector.

        An unreadable file must not take down every other check in the report —
        the `ill.sha256_of` regression (#298). `UnicodeDecodeError` is a
        `ValueError`, not an `OSError`, so it is named explicitly.
        """
        with open(os.path.join(tmp_path, 'storyforge.yaml'), 'wb') as f:
            f.write(b'project:\n  title: \xff\xfe not utf-8\n')

        findings = _check_yaml_scalars(str(tmp_path))

        assert len(findings) == 1
        assert findings[0]['type'] == 'yaml_unreadable'
        assert findings[0]['severity'] == 'warning'
        assert '|' not in findings[0]['detail']

    def test_list_items_are_skipped(self, tmp_path):
        """Documented scope: only `key: value` lines are examined."""
        write_yaml(str(tmp_path), 'parts:\n  - title: Part #1\n')
        assert _check_yaml_scalars(str(tmp_path)) == []

    def test_a_nested_key_is_examined(self, tmp_path):
        write_yaml(str(tmp_path),
                   'production:\n  copyright:\n    holder: Acme #7\n')
        findings = _check_yaml_scalars(str(tmp_path))
        assert len(findings) == 1
        assert '`holder`' in findings[0]['detail']

    def test_a_comment_line_is_not_a_key(self, tmp_path):
        write_yaml(str(tmp_path), 'project:\n  # title: Book #2\n')
        assert _check_yaml_scalars(str(tmp_path)) == []

    def test_crlf_does_not_confuse_the_line_scan(self, tmp_path):
        write_yaml(str(tmp_path), 'project:\n  title: Book #2\n', crlf=True)
        findings = _check_yaml_scalars(str(tmp_path))
        assert len(findings) == 1
        assert 'line 2' in findings[0]['detail']


class TestTheFindingsReachTheReport:

    def test_build_cleanup_report_includes_them(self, tmp_path):
        """A finding nothing surfaces is not a finding."""
        from storyforge.cmd_cleanup import build_cleanup_report
        write_yaml(str(tmp_path), 'project:\n  title: Book #2\n')

        report = build_cleanup_report(str(tmp_path))

        kinds = {f['type'] for f in report['findings']}
        assert 'yaml_value_truncated_by_comment' in kinds

    def test_they_are_actionable_not_info(self, tmp_path):
        """`build_cleanup_report` filters `action_items` on severity != info, and
        `skills/forge/SKILL.md` scans those for `status=pending`."""
        from storyforge.cmd_cleanup import build_cleanup_report
        write_yaml(str(tmp_path), 'project:\n  title: Book #2\n')

        report = build_cleanup_report(str(tmp_path))

        assert any(f['type'] == 'yaml_value_truncated_by_comment'
                   for f in report['action_items'])

    def test_the_written_report_keeps_its_columns_aligned(self, tmp_path):
        """End to end through `_write_report`, which joins on `|` unescaped."""
        from storyforge.cmd_cleanup import _write_report, build_cleanup_report
        from storyforge.cmd_cleanup import REPORT_COLUMNS
        write_yaml(str(tmp_path), 'project:\n  title: Vol #2 | extra\n')

        report = build_cleanup_report(str(tmp_path))
        path = _write_report(report, str(tmp_path))

        with open(path) as f:
            rows = [line.rstrip('\n').split('|') for line in f if line.strip()]
        assert all(len(r) == len(REPORT_COLUMNS) for r in rows), (
            'a stray pipe shifted a row')
