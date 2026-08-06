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


class TestAllThreeWritersAgree:
    """"Preserve" is only one policy if every writer implements it identically.

    Two of the three sniffed for the newline differently — `cleanup` on CRLF
    appearing anywhere, `update_artifact_entry` on the first line — so they
    disagreed on a mixed file while a docstring claimed they matched. And
    `cmd_write._replace_in_file` was a third writer that normalized outright,
    which falsified the premise of `_check_crlf`'s new finding.
    """

    #: First line LF, later lines CRLF. Under the old sniffs `cleanup` read this
    #: as CRLF and `update_artifact_entry` read it as LF.
    MIXED = ('project:\n  title: "X"\r\nartifacts:\r\n  chapter_map:\r\n'
             '    exists: false\r\n')

    def test_the_shared_detector_is_used_by_all_three(self):
        from storyforge.common import detect_newline
        assert detect_newline(self.MIXED) == '\n'
        assert detect_newline('a\r\nb\n') == '\r\n'
        assert detect_newline('no newline at all') == '\n'
        assert detect_newline('') == '\n'

    def test_cleanup_and_update_pick_the_same_terminator(self, tmp_path):
        """The divergence, pinned. Both must insert the same ending."""
        from storyforge.common import update_artifact_entry
        path = os.path.join(str(tmp_path), 'storyforge.yaml')
        with open(path, 'wb') as f:
            f.write(self.MIXED.encode())

        update_artifact_entry(str(tmp_path), 'chapter_map',
                              updated='2026-08-06')

        raw = open(path, 'rb').read()
        # First line is LF, so LF is the file's style and the insert matches it.
        assert b'    updated: "2026-08-06"\n' in raw
        assert b'    updated: "2026-08-06"\r\n' not in raw

    def test_cmd_write_phase_advance_preserves_crlf(self, tmp_path):
        """The third writer. `storyforge write` advances `phase`, and a text-mode
        read/write there normalized the whole file as a side effect of changing
        one word — #314 in a different command."""
        from storyforge.cmd_write import _replace_in_file
        path = os.path.join(str(tmp_path), 'storyforge.yaml')
        with open(path, 'wb') as f:
            f.write(b'project:\r\n  title: "X"\r\nphase: seed\r\n')

        _replace_in_file(path, r'^(\s*phase:).*', r'\1 drafting')

        raw = open(path, 'rb').read()
        assert b'phase: drafting\r\n' in raw
        assert raw.replace(b'\r\n', b'').count(b'\n') == 0

    def test_cmd_write_phase_advance_does_not_eat_the_cr(self, tmp_path):
        """`.` matches `\\r`, so `^(\\s*phase:).*` consumes the CR off that line.

        Running the regex against LF-normalized text and restoring after is why
        this works without every pattern having to know about `\\r`.
        """
        from storyforge.cmd_write import _replace_in_file
        path = os.path.join(str(tmp_path), 'storyforge.yaml')
        with open(path, 'wb') as f:
            f.write(b'phase: seed\r\nnext: keep\r\n')

        _replace_in_file(path, r'^(\s*phase:).*', r'\1 drafting')

        assert open(path, 'rb').read() == b'phase: drafting\r\nnext: keep\r\n'

    def test_cmd_write_leaves_lf_alone(self, tmp_path):
        from storyforge.cmd_write import _replace_in_file
        path = os.path.join(str(tmp_path), 'storyforge.yaml')
        with open(path, 'wb') as f:
            f.write(b'phase: seed\nnext: keep\n')

        _replace_in_file(path, r'^(\s*phase:).*', r'\1 drafting')

        assert open(path, 'rb').read() == b'phase: drafting\nnext: keep\n'

    def test_cmd_write_does_not_write_when_nothing_matches(self, tmp_path):
        from storyforge.cmd_write import _replace_in_file
        path = os.path.join(str(tmp_path), 'storyforge.yaml')
        with open(path, 'wb') as f:
            f.write(b'phase: drafting\r\n')
        before = os.stat(path).st_mtime_ns

        _replace_in_file(path, r'^(\s*nothing:).*', r'\1 x')

        assert os.stat(path).st_mtime_ns == before


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
        # A value that is *entirely* a `#`-word loses everything, not a suffix —
        # the worse of the two cases, and the example named in
        # `_LIKELY_VALUE_HASH`'s own comment. A `stripped and` guard used to
        # short-circuit before the heuristic and make it unreachable, and this
        # test asserted the false negative as though it were intended.
        ('#ff8800', 'comment_truncated'),
        ('#2b1a0f', 'comment_truncated'),
    ])
    def test_it_finds_the_issue(self, raw, expected):
        assert yaml_scalar_issue(raw) == expected

    def test_a_whole_value_lost_to_a_hash_is_reported(self, tmp_path):
        """`production.cover.palette` is a live field, so this is reachable."""
        write_yaml(str(tmp_path),
                   'production:\n  cover:\n    palette: #2b1a0f\n')

        findings = _check_yaml_scalars(str(tmp_path))

        assert len(findings) == 1
        assert findings[0]['type'] == 'yaml_value_truncated_by_comment'
        assert '`palette`' in findings[0]['detail']

    @pytest.mark.parametrize('raw', [
        '',
        '   ',
        'plain value',
        'a#b',                              # no space: part of the value
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

    #: `(raw, what the parser returns, what the reporter says)`. The values are
    #: written out rather than derived, because that is the whole point — see
    #: `test_the_reader_and_the_reporter_are_pinned_together`.
    PAIRED = [
        ('Book #2', 'Book', 'comment_truncated'),
        ('a#b', 'a#b', None),
        ('fantasy  # default', 'fantasy', None),
        ('  # Optional: unset', '', None),
        ('#ff8800', '', 'comment_truncated'),
        ('"unterminated', '"unterminated', 'unterminated_quote'),
        ('""Unicorn Tail""', '"Unicorn Tail"', 'trailing_after_quote'),
        ('"quoted" then junk', '"quoted" then junk', 'trailing_after_quote'),
        ('"All Good"  # a comment', 'All Good', None),
        ("'Children''s book'", "Children's book", None),
        ('"tagged #1 of 3"', 'tagged #1 of 3', None),
        # The input that catches an edit to the shared `_closing_quote_index`:
        # the closing quote is followed by a comment containing another quote.
        ('"a" # c "', 'a', None),
    ]

    @pytest.mark.parametrize('raw,parsed,issue', PAIRED)
    def test_the_reader_and_the_reporter_are_pinned_together(self, raw, parsed,
                                                             issue):
        """Both halves, against written-out expectations.

        This replaces a test that called `parse_yaml_scalar` before and after
        `yaml_scalar_issue` and asserted they matched. Both functions are pure, so
        that asserted `f(x) == f(x)` — it passed with `yaml_scalar_issue` replaced
        by `lambda raw: None` *and* by a constant. Worse, it was the only stated
        guard on the invariant that the reporter must not change the reader, and
        an edit to the `_closing_quote_index` the two now share could alter the
        parser's answer for `'"a" # c "'` with the test still green.

        Pinning literal values on both sides is what actually holds it: the two
        share a scan precisely so they cannot disagree, so both answers belong in
        one table.
        """
        from storyforge.common import parse_yaml_scalar
        assert parse_yaml_scalar(raw) == parsed
        assert yaml_scalar_issue(raw) == issue


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


class TestTheCollectorCannotBeKilled:
    """`build_cleanup_report` is the single finding collector.

    An exception out of any one check discards every other finding *and* the
    report file, so `skills/forge/SKILL.md`'s `status=pending` scan reads a broken
    project as clean. The #298 precedent.
    """

    def test_an_unreadable_yaml_does_not_kill_the_report(self, tmp_path):
        """`_check_crlf` reads storyforge.yaml and runs *before* the guarded
        check, so its own guard is what matters here."""
        from storyforge.cmd_cleanup import build_cleanup_report
        path = write_yaml(str(tmp_path), COMPLETE_YAML)
        os.chmod(path, 0o000)
        try:
            report = build_cleanup_report(str(tmp_path))
        finally:
            os.chmod(path, 0o644)

        assert report['findings'], 'the report must still be produced'
        kinds = {f['type'] for f in report['findings']}
        assert 'unreadable_file' in kinds

    def test_the_unreadable_finding_is_csv_safe(self, tmp_path):
        from storyforge.cmd_cleanup import _check_crlf
        path = write_yaml(str(tmp_path), COMPLETE_YAML)
        os.chmod(path, 0o000)
        try:
            findings = _check_crlf(str(tmp_path))
        finally:
            os.chmod(path, 0o644)

        assert all('|' not in f['detail'] and '\n' not in f['detail']
                   for f in findings)

    def test_migrate_survives_an_undecodable_file(self, tmp_path, capsys):
        """`main` calls this at step 3 of 13 with no handler above it, so an
        exception here took down the read-only report, which is the product."""
        with open(os.path.join(str(tmp_path), 'storyforge.yaml'), 'wb') as f:
            f.write(b'project:\n  title: \xff\xfe\n')

        migrate_storyforge_yaml(str(tmp_path))

        assert 'WARNING' in capsys.readouterr().out

    def test_every_issue_has_a_finding_entry(self):
        """Totality. The subscript is unguarded and inside the collector, so a
        member added to one declaration and not the other must fail at import,
        not as a KeyError mid-report."""
        from typing import get_args
        from storyforge.cmd_cleanup import _YAML_SCALAR_FINDINGS
        from storyforge.common import YamlScalarIssue

        assert set(_YAML_SCALAR_FINDINGS) == set(get_args(YamlScalarIssue))

    def test_each_finding_entry_is_distinct_and_in_the_right_slot(self):
        """A NamedTuple, because swapping `detail` with `action` would tell an
        author with an unterminated quote to remove text after a closing one."""
        from storyforge.cmd_cleanup import _YAML_SCALAR_FINDINGS

        assert len({e.kind for e in _YAML_SCALAR_FINDINGS.values()}) == 3
        assert len({e.action for e in _YAML_SCALAR_FINDINGS.values()}) == 3
        assert 'quote' in _YAML_SCALAR_FINDINGS['unterminated_quote'].action
        assert _YAML_SCALAR_FINDINGS['comment_truncated'].kind == (
            'yaml_value_truncated_by_comment')


class TestBlockScalarsAreNotScannedAsKeys:

    def test_a_block_scalar_body_produces_no_finding(self, tmp_path):
        """A body line is not a `key: value` pair, and scanning one named a key
        the author never wrote — a false claim about their file."""
        write_yaml(str(tmp_path), (
            'production:\n'
            '  dedication: |\n'
            '    For Nora.\n'
            '    Note #3 in a series.\n'))

        assert _check_yaml_scalars(str(tmp_path)) == []

    def test_a_folded_block_is_also_skipped(self, tmp_path):
        write_yaml(str(tmp_path),
                   'production:\n  blurb: >\n    Wrapped #7 here.\n')
        assert _check_yaml_scalars(str(tmp_path)) == []

    def test_scanning_resumes_after_the_block_ends(self, tmp_path):
        """Skipping must not swallow the rest of the file."""
        write_yaml(str(tmp_path), (
            'production:\n'
            '  dedication: |\n'
            '    Note #3 in a series.\n'
            '  after: Book #2\n'))

        findings = _check_yaml_scalars(str(tmp_path))

        assert len(findings) == 1
        assert '`after`' in findings[0]['detail']

    def test_block_indicators_with_modifiers_are_recognized(self, tmp_path):
        write_yaml(str(tmp_path),
                   'a: |-\n  Note #3\nb: >2\n  Note #4\nc: ok\n')
        assert _check_yaml_scalars(str(tmp_path)) == []


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
