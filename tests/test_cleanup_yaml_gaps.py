"""The `storyforge.yaml` paths #316's own tests leave unguarded.

Every test here was written against a surviving mutant: the mutation was applied
to `cmd_cleanup.py`, the full suite stayed green, and the test below is what
turns it red. The verdicts are recorded per class.

The shape of the gap is the one #313 was reviewed for — a helper is tested and
its wiring is not — narrowed here to one region. #316 made six regexes in
`migrate_storyforge_yaml` CRLF-tolerant and wrote one test covering one of them
(`test_a_crlf_project_still_receives_migrations`, the artifact-entry insert).
The other five, plus the whole `chapter_map` relocation block, were reachable
only through code no test executes: lines 434-467 of `cmd_cleanup.py` were
uncovered by all 6062 tests.

Lives beside `test_cleanup_yaml.py` rather than inside it so the two can be read
as what they are — that file pins the behaviour #316 changed on purpose, this one
pins the behaviour it changed as a consequence.
"""

import hashlib
import os
import re

import pytest

from storyforge.cmd_cleanup import (
    _check_crlf,
    _check_yaml_scalars,
    migrate_storyforge_yaml,
)
from storyforge.common import (
    _parse_quoted_scalar,
    parse_yaml_scalar,
    yaml_scalar_issue,
)

#: Everything `migrate_storyforge_yaml` would otherwise add, so a run has nothing
#: legitimate to do. Mirrors `test_cleanup_yaml.COMPLETE_YAML`; duplicated rather
#: than imported so an edit there for one purpose cannot silently retune the
#: other file's mutants.
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

#: A pre-migration project: `chapter_map` at the top level instead of under
#: `artifacts`. This is the shape the relocation block exists for, and no test
#: in the suite had ever constructed it.
WITH_TOP_LEVEL_CHAPTER_MAP = '''project:
  title: "The Lantern Folk"

chapter_map:
  exists: true
  path: reference/chapter-map.csv
  updated: 2026-08-01

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
    path = os.path.join(str(project_dir), 'storyforge.yaml')
    data = text.replace('\n', '\r\n') if crlf else text
    with open(path, 'wb') as f:
        f.write(data.encode())
    return path


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def digest(path):
    return hashlib.sha256(read_bytes(path)).hexdigest()


def endings_are_consistent(raw: bytes) -> bool:
    """True when the whole file uses one line ending.

    Emitting LF into a CRLF file leaves it mixed, which is worse than either
    policy applied consistently, so this is the assertion every insert needs. It
    has to be ending-aware in both directions: on a CRLF file a surviving bare LF
    is the defect, and on an LF file a stray CR is.
    """
    if b'\r\n' in raw:
        return raw.replace(b'\r\n', b'').count(b'\n') == 0
    return b'\r' not in raw


# ===========================================================================
# The five CRLF patterns the one CRLF migration test does not reach
# ===========================================================================

class TestEveryPatternToleratesCrlf:
    """#316's stated trap, applied to the patterns its test misses.

    From the PR: switching to `newline=''` alone "would have silently stopped
    migrating CRLF projects — trading a cosmetic bug for a functional one."
    That is true of all six `\\r?\\n` edits, and
    `test_a_crlf_project_still_receives_migrations` covers one.
    """

    def test_a_crlf_project_still_has_its_exists_flags_corrected(self, tmp_path):
        """The widest-blast-radius pattern of the six, and it had no test.

        Reverting `_fix_exists`' pattern to `^  [a-z_]+:\\n(?:    (?:exists|path|
        updated):.*\\n)+` leaves all 45 of #316's tests passing while a CRLF
        project's `exists` flags stop being corrected altogether: `[a-z_]+` cannot
        match the `\\r`, so the first line never matches and the whole pass
        becomes a no-op. This is the correction that runs on every artifact of
        every project on every run, so it fails silently and everywhere.
        """
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'world-bible.md').write_text('x\n')
        path = write_yaml(tmp_path, COMPLETE_YAML, crlf=True)

        migrate_storyforge_yaml(str(tmp_path))

        raw = read_bytes(path)
        assert b'exists: true' in raw, (
            'the exists flag was not corrected on a CRLF file')
        assert endings_are_consistent(raw)

    def test_an_lf_project_has_its_exists_flags_corrected(self, tmp_path):
        """The LF twin, so the pair reads as a matrix rather than a CRLF quirk."""
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'world-bible.md').write_text('x\n')
        path = write_yaml(tmp_path, COMPLETE_YAML)

        migrate_storyforge_yaml(str(tmp_path))

        raw = read_bytes(path)
        assert b'exists: true' in raw
        assert b'\r\n' not in raw

    def test_a_run_of_blank_lines_is_collapsed_on_a_crlf_file(self, tmp_path):
        """`(?:\\r?\\n){3,}` -> `\\n{3,}`: on CRLF nothing collapses, so removing
        the top-level block leaves the gap it used to occupy behind."""
        text = WITH_TOP_LEVEL_CHAPTER_MAP.replace(
            '\nartifacts:', '\n\n\n\nartifacts:')
        path = write_yaml(tmp_path, text, crlf=True)

        migrate_storyforge_yaml(str(tmp_path))

        raw = read_bytes(path)
        assert b'\r\n\r\n\r\n' not in raw, 'a run of blank lines survived'
        assert endings_are_consistent(raw)


# ===========================================================================
# The chapter_map relocation — 34 lines no test executed
# ===========================================================================

class TestTheChapterMapRelocation:
    """`cmd_cleanup.py` lines 434-467, uncovered by the whole suite.

    #316 rewrote three regexes here and converted the insert from a replacement
    template to a function. Nothing ran any of it, in either line ending, which
    is why four separate mutations of this block survive.
    """

    def test_a_misplaced_chapter_map_is_moved_under_artifacts(self, tmp_path):
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'chapter-map.csv').write_text('a\n')
        path = write_yaml(tmp_path, WITH_TOP_LEVEL_CHAPTER_MAP)

        migrate_storyforge_yaml(str(tmp_path))

        out = open(path, newline='').read()
        assert '\nchapter_map:' not in out, 'the top-level block survived'
        assert '  chapter_map:\n' in out
        assert 'path: reference/chapter-map.csv' in out
        assert 'updated: 2026-08-01' in out, 'the value was dropped in the move'

    def test_a_crlf_project_relocates_without_mixing_its_endings(self, tmp_path):
        """Kills three mutants at once: the block-match, the removal, and the
        insert anchor. Each reverts to `\\n` and each silently stops relocating.
        """
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'chapter-map.csv').write_text('a\n')
        path = write_yaml(tmp_path, WITH_TOP_LEVEL_CHAPTER_MAP, crlf=True)

        migrate_storyforge_yaml(str(tmp_path))

        raw = read_bytes(path)
        assert b'  chapter_map:\r\n' in raw
        assert b'\r\nchapter_map:' not in raw, 'the top-level block survived'
        assert b'updated: 2026-08-01' in raw
        assert endings_are_consistent(raw)

    @pytest.mark.parametrize('crlf', [False, True], ids=['lf', 'crlf'])
    def test_a_windows_style_path_is_not_read_as_a_group_reference(self, tmp_path,
                                                                  crlf):
        r"""The *reachable* backslash case, and the one that had no test.

        `test_an_artifact_path_with_a_backslash_does_not_corrupt` exercises no
        backslash — it uses the hardcoded `reference/characters.csv`, and every
        entry in `artifact_files` is a forward-slash literal, so a backslash can
        never reach that insert. `cm_path` here comes from **author YAML**, so it
        can. Under the pre-#316 `r'\1' + insert_block` this raises
        `re.error: bad escape \c`; the function replacement takes it literally.
        """
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'chapter-map.csv').write_text('a\n')
        text = WITH_TOP_LEVEL_CHAPTER_MAP.replace(
            'path: reference/chapter-map.csv',
            'path: reference\\chapter-map.csv')
        path = write_yaml(tmp_path, text, crlf=crlf)

        migrate_storyforge_yaml(str(tmp_path))

        assert 'reference\\chapter-map.csv' in open(path, newline='').read(), (
            'the backslash path was mangled or lost')

    @pytest.mark.parametrize('crlf', [False, True], ids=['lf', 'crlf'])
    def test_a_chapter_map_is_never_dropped_when_there_is_nowhere_to_put_it(
            self, tmp_path, crlf):
        """Silent data loss, found as a strict xfail and now fixed.

        With no `artifacts:` block the removal ran and the re-insert had no
        anchor, so the entry — path, dates and all — was destroyed and written to
        disk. `cleanup` deleting data out of `storyforge.yaml` is #276's exact
        shape, in the one branch nothing in the suite reached.

        The relocation is now all-or-nothing: `re.subn` reports whether the insert
        landed, and a miss abandons the whole move and warns. Leaving a misplaced
        top-level entry is harmless because nothing reads it; deleting it loses
        the only record of the path.
        """
        text = WITH_TOP_LEVEL_CHAPTER_MAP.replace(
            'artifacts:\n  world_bible:\n    exists: false\n'
            '    path: reference/world-bible.md\n    updated:\n', '')
        path = write_yaml(tmp_path, text, crlf=crlf)

        migrate_storyforge_yaml(str(tmp_path))

        content = open(path, newline='').read()
        assert 'reference/chapter-map.csv' in content
        # Left where it was, rather than half-moved.
        assert re.search(r'^chapter_map:', content, re.MULTILINE)

    @pytest.mark.parametrize('crlf', [False, True], ids=['lf', 'crlf'])
    def test_a_failed_relocation_warns(self, tmp_path, crlf, capsys):
        """Silence would leave a misplaced entry looking migrated."""
        text = WITH_TOP_LEVEL_CHAPTER_MAP.replace(
            'artifacts:\n  world_bible:\n    exists: false\n'
            '    path: reference/world-bible.md\n    updated:\n', '')
        write_yaml(tmp_path, text, crlf=crlf)

        migrate_storyforge_yaml(str(tmp_path))

        out = capsys.readouterr().out
        assert 'WARNING' in out and 'no `artifacts:` block' in out


# ===========================================================================
# Idempotence past the first run, and the sections the one add-test misses
# ===========================================================================

class TestMigrateIsIdempotentOnceItHasDoneItsWork:
    """#316 asserts idempotence only for a file with nothing to do.

    The artifact-insert guard (`if f'  {aid}:' not in content`) is therefore
    never exercised on its second, suppressing pass — the arc is uncovered — so a
    re-insert-every-run regression would reproduce #314's symptom in a branch
    #314's own test cannot see.
    """

    def test_a_second_run_over_a_project_with_artifact_files_changes_nothing(
            self, tmp_path):
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'characters.csv').write_text('id|name\n')
        (tmp_path / 'reference' / 'locations.csv').write_text('id|name\n')
        path = write_yaml(tmp_path, COMPLETE_YAML)

        migrate_storyforge_yaml(str(tmp_path))
        after_first, mtime = digest(path), os.stat(path).st_mtime_ns

        migrate_storyforge_yaml(str(tmp_path))

        assert digest(path) == after_first, 'the second run changed bytes'
        assert os.stat(path).st_mtime_ns == mtime, (
            'the second run rewrote the file — #314 in the artifact-insert '
            'branch')

    def test_a_second_run_after_a_chapter_map_move_changes_nothing(self,
                                                                  tmp_path):
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'chapter-map.csv').write_text('a\n')
        path = write_yaml(tmp_path, WITH_TOP_LEVEL_CHAPTER_MAP)

        migrate_storyforge_yaml(str(tmp_path))
        after_first, mtime = digest(path), os.stat(path).st_mtime_ns

        migrate_storyforge_yaml(str(tmp_path))

        assert digest(path) == after_first
        assert os.stat(path).st_mtime_ns == mtime


class TestEveryMissingSectionIsAdded:
    """Only `scene_extensions` was covered; three adds and two suppressions
    were not."""

    @pytest.mark.parametrize('removed,expected', [
        ('scene_extensions: []\n', 'scene_extensions: []'),
        ('evaluation:\n  custom_evaluators: []\n', 'evaluation:'),
        ('production:\n  author: Ben Norris\n', '# production:'),
        ('parts:\n  - number: 1\n    title: "Part One"\n', '# parts:'),
    ])
    def test_a_missing_section_is_appended(self, tmp_path, removed, expected):
        path = write_yaml(tmp_path, COMPLETE_YAML.replace(removed, ''))

        migrate_storyforge_yaml(str(tmp_path))

        assert expected in open(path).read()

    @pytest.mark.parametrize('commented', ['# production:', '# parts:'])
    def test_an_already_commented_section_is_not_added_again(self, tmp_path,
                                                            commented):
        """The `and not re.search(r'^# production:')` conjuncts. Without them the
        template's own commented-out blocks would be duplicated on every run —
        which is #314's symptom by another route."""
        live = commented.lstrip('# ')
        text = COMPLETE_YAML.replace(
            'production:\n  author: Ben Norris\n', '').replace(
            'parts:\n  - number: 1\n    title: "Part One"\n', '')
        path = write_yaml(tmp_path, text + f'\n{commented}\n')

        migrate_storyforge_yaml(str(tmp_path))
        migrate_storyforge_yaml(str(tmp_path))

        assert open(path).read().count(commented) == 1, (
            f'{commented} was added alongside the existing one')
        assert f'\n{live}\n' not in open(path).read()

    @pytest.mark.parametrize('crlf', [False, True], ids=['lf', 'crlf'])
    def test_an_appended_section_matches_the_file(self, tmp_path, crlf):
        path = write_yaml(
            tmp_path,
            COMPLETE_YAML.replace('evaluation:\n  custom_evaluators: []\n', ''),
            crlf=crlf)

        migrate_storyforge_yaml(str(tmp_path))

        raw = read_bytes(path)
        assert b'custom_evaluators: []' in raw
        assert endings_are_consistent(raw)


# ===========================================================================
# #315 — which remedy goes with which issue, and the invariant behind it
# ===========================================================================

class TestEachIssueCarriesItsOwnRemedy:
    """`test_it_reports_each_kind_with_its_own_remedy` checks that the *set* of
    three kinds appears and that the three actions are distinct — not which goes
    with which. Swapping the `unterminated_quote` and `trailing_after_quote`
    payloads wholesale (kind, detail and remedy) leaves the entire suite green,
    so an author with `title: "unterminated` is told to "Remove the text after
    the closing quote". That is the inert-advice failure `YamlScalarIssue` is a
    three-member Literal to prevent.
    """

    @pytest.mark.parametrize('value,kind,remedy_fragment,detail_fragment', [
        ('"unterminated', 'yaml_unterminated_quote',
         'Close the quote', 'never closed'),
        ('"quoted" then junk', 'yaml_trailing_after_quote',
         'after the closing quote', 'follows the closing quote'),
        ('Book #2', 'yaml_value_truncated_by_comment',
         'double quotes', 'start of a comment'),
    ])
    def test_the_pairing_is_not_merely_a_set(self, tmp_path, value, kind,
                                             remedy_fragment, detail_fragment):
        write_yaml(tmp_path, f'project:\n  title: {value}\n')

        findings = _check_yaml_scalars(str(tmp_path))

        assert len(findings) == 1
        assert findings[0]['type'] == kind
        assert remedy_fragment in findings[0]['action']
        assert detail_fragment in findings[0]['detail']


class TestTheReaderAndTheReporterScanIdentically:
    """The invariant `_closing_quote_index` was extracted to provide.

    #316's stated reason for the extraction is that two scanners "would be the
    #277 shape again — the reader and the reporter disagreeing about what is
    malformed, so `cleanup` says a value is fine while the parser is falling back
    on it." Nothing asserted it. `test_it_never_changes_what_the_parser_returns`
    does not: neither function has state, so it passes against
    `yaml_scalar_issue = lambda raw: None` and against a constant
    `'comment_truncated'` alike.
    """

    QUOTED = [
        '"All Good"  # a comment', "'Children''s book'", '"tagged #1 of 3"',
        '"unterminated', "'unterminated", '"quoted" then junk',
        '""Unicorn Tail""', '"A"', "'A'", '""', "''", '"', "'",
        r'"a \"quoted\" word"', r'"trailing backslash\\"', r'"bad escape\"',
        "'it''s", '"A"#tight', '"A" ', '"#ff8800"',
    ]

    @pytest.mark.parametrize('raw', QUOTED)
    def test_the_reporter_flags_exactly_what_the_reader_falls_back_on(self, raw):
        fell_back = _parse_quoted_scalar(raw.strip()) is None
        flagged = yaml_scalar_issue(raw) in ('unterminated_quote',
                                             'trailing_after_quote')
        assert fell_back == flagged, (
            f'{raw!r}: reader fell back={fell_back}, reporter flagged={flagged}')

    @pytest.mark.parametrize('raw', QUOTED)
    def test_a_flagged_value_is_never_reported_as_read_correctly(self, raw):
        """The consequence the invariant buys: whenever the reporter is silent
        about the quoting, the parser really did read the quoted form."""
        if yaml_scalar_issue(raw) is not None:
            return
        stripped = raw.strip()
        if stripped and stripped[0] in ('"', "'"):
            assert _parse_quoted_scalar(stripped) == parse_yaml_scalar(raw)


class TestTheHeuristicsProtectionIsNotAccidental:
    """`test_the_shipped_template_produces_no_findings` is what keeps the ` #`
    heuristic honest, and it rests on a single template line.

    Measured: the scanner examines 32 `key: value` lines in the shipped template
    and exactly one — `target_words: 80000  # Target manuscript word count` — is
    the unquoted-value-with-trailing-comment shape that exercises the
    `comment_truncated` path at all. The PR body and the `_LIKELY_VALUE_HASH`
    docstring both describe the template as putting "a real trailing comment on
    nearly every key" and cite `genre_preset: fantasy  # ...`; that line is
    commented out in the template and carries no comment in the fixture. The
    protection is real but thinner than the argument for it, so the shape it
    depends on is pinned here rather than left incidental.
    """

    def test_the_template_still_carries_the_shape_the_guard_needs(self,
                                                                 plugin_dir):
        import re
        text = open(os.path.join(plugin_dir, 'templates',
                                 'storyforge.yaml')).read()
        risky = []
        for line in text.splitlines():
            m = re.match(r'^(\s{0,4})([A-Za-z_][\w-]*):(?:[ \t]+(\S.*?))?\s*$',
                         line)
            value = m.group(3) if m else None
            if value and '#' in value and not value.startswith(('"', "'", '#')):
                risky.append((m.group(2), value))
        assert risky, (
            'no unquoted value with a trailing comment is left in the template, '
            'so test_the_shipped_template_produces_no_findings no longer guards '
            'the ` #` heuristic against being made permissive')

    @pytest.mark.parametrize('permissive', ['#', r'#.', r'#\s*\S'])
    def test_a_permissive_heuristic_is_caught_by_the_template(
            self, permissive, plugin_dir, tmp_path, monkeypatch):
        """The naive rule #316 argues against, and two near-misses, must all
        fire on the template — that is the whole basis for the claim that a
        conservative heuristic is the usable one."""
        import re
        import shutil
        from storyforge import common
        monkeypatch.setattr(common, '_LIKELY_VALUE_HASH',
                            re.compile(permissive))
        shutil.copy(os.path.join(plugin_dir, 'templates', 'storyforge.yaml'),
                    os.path.join(str(tmp_path), 'storyforge.yaml'))

        assert _check_yaml_scalars(str(tmp_path)), (
            f'{permissive!r} would report a fresh project on every run and '
            'nothing would notice')


# ===========================================================================
# _check_crlf, with both kinds of file dirty at once
# ===========================================================================

class TestCrlfReportsEveryDirtyFileTogether:

    def test_a_dirty_csv_and_a_dirty_yaml_are_one_finding_naming_both(self,
                                                                     tmp_path):
        """#316 widened the loop and rewrote the detail from 'CSV file(s)' to
        'file(s)'. Nothing exercised the two together, so neither the `; ` join
        nor the count was asserted over a mixed set."""
        os.makedirs(os.path.join(str(tmp_path), 'reference'))
        with open(os.path.join(str(tmp_path), 'reference', 'scenes.csv'),
                  'wb') as f:
            f.write(b'id|seq\r\n')
        write_yaml(tmp_path, COMPLETE_YAML, crlf=True)

        findings = _check_crlf(str(tmp_path))

        assert len(findings) == 1
        assert 'storyforge.yaml' in findings[0]['file']
        assert 'reference/scenes.csv' in findings[0]['file']
        assert '2 file(s)' in findings[0]['detail']

    def test_the_detail_no_longer_claims_the_files_are_csvs(self, tmp_path):
        write_yaml(tmp_path, COMPLETE_YAML, crlf=True)

        detail = _check_crlf(str(tmp_path))[0]['detail']

        assert 'CSV file(s)' not in detail, (
            'the yaml is reported as a CSV')
        assert '1 file(s)' in detail
