"""Regression tests for the storyforge.yaml read/write helpers.

Two bugs, both silent, both in `storyforge.yaml` handling:

- **#276** — `assemble` updated the `artifacts:` block with a whole-file
  `re.sub` under `re.DOTALL` ending in an unanchored `.*`. It matched to end of
  file, so every block after the first `updated:` was deleted and the truncated
  file was committed.
- **#277** — three copies of a "strip the quotes" value parser, none of which
  removed an inline comment, feeding values into an epub metadata block that
  quoted them without escaping. A comment became part of a value, an empty field
  with a template comment became truthy, and one apostrophe broke pandoc.
"""

import os

import pytest
from yaml_probe import parse_emitted_yaml_metadata

from storyforge.assembly import (
    _strip_yaml_quotes,
    generate_epub_metadata,
    read_production_field,
)
from storyforge.common import (
    _strip_yaml_value,
    parse_yaml_scalar,
    read_yaml_field,
    update_artifact_entry,
    yaml_single_quote,
)
from storyforge.prompts import _strip_yaml_value as _prompts_strip_yaml_value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: A project file shaped like the real one that lost data: content *after* the
#: artifacts block, which is exactly what the truncating regex deleted.
YAML_WITH_TRAILING_BLOCKS = '''project:
  title: "The Lantern Folk"
artifacts:
  chapter_map:
    exists: false
    path: reference/chapter-map.csv
    updated:

  manuscript:
    exists: false
    path: manuscript/
    updated:   # set by assemble

phase: drafting
parts:
  - number: 1
    title: "Part One"
production:
  author: Ben Norris
  cover_image: production/cover.png
  language: en
'''


@pytest.fixture
def yaml_project(tmp_path):
    """A project dir holding `YAML_WITH_TRAILING_BLOCKS`."""
    (tmp_path / 'storyforge.yaml').write_text(YAML_WITH_TRAILING_BLOCKS)
    return str(tmp_path)


def read_yaml(project_dir):
    with open(os.path.join(project_dir, 'storyforge.yaml')) as f:
        return f.read()


#: `tests/yaml_probe.py` — one shared reader, independent of the code under test
#: so a regression cannot agree with itself. It replaced a private copy here
#: whose `startswith`/`endswith` check was blind to an unescaped apostrophe: with
#: `yaml_single_quote` removed from `assembly._quoted`, every test in this file
#: still passed while pandoc exited 64 on the output.
parse_flat_metadata = parse_emitted_yaml_metadata


# ===========================================================================
# #276 — the artifacts block is edited in place, not rewritten
# ===========================================================================

class TestUpdateArtifactEntryPreservesFile:

    def test_trailing_blocks_survive(self, yaml_project):
        """The reported bug: everything after `artifacts:` was deleted.

        `phase`, `parts`, and the whole `production` section vanished, and
        `commit_and_push` staged the result.
        """
        for artifact in ('chapter_map', 'manuscript'):
            update_artifact_entry(yaml_project, artifact,
                                  exists=True, updated='2026-08-06')

        content = read_yaml(yaml_project)
        assert 'phase: drafting' in content
        assert 'parts:' in content
        assert 'title: "Part One"' in content
        assert 'production:' in content
        assert 'author: Ben Norris' in content
        assert 'cover_image: production/cover.png' in content
        assert 'language: en' in content

    def test_both_artifacts_are_updated(self, yaml_project):
        """The quiet half of #276: the second artifact never got updated.

        The first artifact's rewrite had already deleted the second one, so the
        loop's next iteration matched nothing and silently did nothing.
        """
        for artifact in ('chapter_map', 'manuscript'):
            update_artifact_entry(yaml_project, artifact,
                                  exists=True, updated='2026-08-06')

        content = read_yaml(yaml_project)
        assert content.count('exists: true') == 2
        assert content.count('updated: "2026-08-06"') == 2

    def test_only_the_named_artifact_changes(self, yaml_project):
        update_artifact_entry(yaml_project, 'chapter_map', exists=True)

        content = read_yaml(yaml_project)
        assert content.count('exists: true') == 1
        assert content.count('exists: false') == 1
        # The untouched artifact keeps its empty `updated:` line verbatim.
        assert 'updated:   # set by assemble' in content

    def test_inline_comment_is_preserved(self, yaml_project):
        """Comments survive a write. #277 is a bug from *reading* them as
        values; discarding them on write would be the same disrespect for author
        annotation, arrived at from the other side."""
        update_artifact_entry(yaml_project, 'manuscript', updated='2026-08-06')

        assert 'updated: "2026-08-06"  # set by assemble' in read_yaml(
            yaml_project)

    def test_everything_outside_the_two_values_is_byte_identical(
            self, yaml_project):
        before = read_yaml(yaml_project)
        update_artifact_entry(yaml_project, 'chapter_map',
                              exists=True, updated='2026-08-06')
        after = read_yaml(yaml_project)

        expected = before.replace(
            '    exists: false\n    path: reference/chapter-map.csv\n'
            '    updated:\n',
            '    exists: true\n    path: reference/chapter-map.csv\n'
            '    updated: "2026-08-06"\n')
        assert after == expected

    def test_blank_line_separators_are_kept(self, yaml_project):
        update_artifact_entry(yaml_project, 'chapter_map',
                              exists=True, updated='2026-08-06')

        content = read_yaml(yaml_project)
        assert 'updated: "2026-08-06"\n\n  manuscript:' in content


class TestUpdateArtifactEntryReturnValue:

    def test_returns_true_when_it_writes(self, yaml_project):
        assert update_artifact_entry(
            yaml_project, 'chapter_map', exists=True) is True

    def test_returns_false_when_already_correct(self, yaml_project):
        update_artifact_entry(yaml_project, 'chapter_map',
                              exists=True, updated='2026-08-06')
        assert update_artifact_entry(yaml_project, 'chapter_map',
                                     exists=True,
                                     updated='2026-08-06') is False

    def test_a_no_op_does_not_rewrite_the_file(self, yaml_project):
        update_artifact_entry(yaml_project, 'chapter_map', exists=True,
                             updated='2026-08-06')
        content = read_yaml(yaml_project)
        update_artifact_entry(yaml_project, 'chapter_map', exists=True,
                             updated='2026-08-06')
        assert read_yaml(yaml_project) == content

    def test_missing_artifact_returns_false_and_changes_nothing(
            self, yaml_project):
        before = read_yaml(yaml_project)
        assert update_artifact_entry(
            yaml_project, 'no_such_artifact', exists=True) is False
        assert read_yaml(yaml_project) == before

    def test_missing_yaml_returns_false(self, tmp_path):
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', exists=True) is False

    def test_no_artifacts_block_returns_false(self, tmp_path):
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: "X"\n')
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', exists=True) is False

    def test_an_already_correct_entry_does_not_touch_the_file(
            self, yaml_project):
        """`False` must mean "I did not write", not merely "same bytes".

        Asserted on mtime rather than content, because content equality holds
        either way — so a rewrite-every-time regression is invisible to a
        content check. The `if changed:` guard is what keeps an assemble run
        from dirtying `storyforge.yaml` for git when nothing moved.
        """
        path = os.path.join(yaml_project, 'storyforge.yaml')
        update_artifact_entry(yaml_project, 'chapter_map', exists=True,
                              updated='2026-08-06')
        os.utime(path, (0, 0))
        before = os.stat(path).st_mtime_ns

        assert update_artifact_entry(yaml_project, 'chapter_map', exists=True,
                                     updated='2026-08-06') is False
        assert os.stat(path).st_mtime_ns == before

    def test_a_missing_artifact_logs_a_warning(self, yaml_project, capsys):
        """`False` is the only other signal, and #276's quiet half is what
        happens when a no-op is not announced. The log must name the artifact."""
        update_artifact_entry(yaml_project, 'no_such_artifact', exists=True)

        out = capsys.readouterr().out
        assert 'WARNING' in out
        assert 'no_such_artifact' in out

    def test_a_missing_yaml_logs_a_warning(self, tmp_path, capsys):
        update_artifact_entry(str(tmp_path), 'chapter_map', exists=True)

        out = capsys.readouterr().out
        assert 'WARNING' in out
        assert 'chapter_map' in out


class TestUpdateArtifactEntryEdgeCases:

    def test_a_prefix_named_artifact_is_not_matched(self, tmp_path):
        """`manuscript` must not match `manuscript_notes`."""
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n'
            '  manuscript_notes:\n'
            '    exists: false\n'
            '    updated:\n')
        assert update_artifact_entry(
            str(tmp_path), 'manuscript', exists=True) is False
        assert 'exists: false' in (tmp_path / 'storyforge.yaml').read_text()

    def test_a_missing_key_is_inserted_inside_the_block(self, tmp_path):
        """Insert rather than skip — a silent no-op is #276's own shape.

        It must land inside the block, not after the blank line that separates
        it from the next artifact.
        """
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n'
            '  chapter_map:\n'
            '    exists: false\n'
            '\n'
            '  manuscript:\n'
            '    exists: false\n')
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', updated='2026-08-06') is True

        content = (tmp_path / 'storyforge.yaml').read_text()
        assert content == (
            'artifacts:\n'
            '  chapter_map:\n'
            '    exists: false\n'
            '    updated: "2026-08-06"\n'
            '\n'
            '  manuscript:\n'
            '    exists: false\n')

    def test_crlf_line_endings_are_preserved(self, tmp_path):
        """A rewrite that normalized these would surface as `crlf_line_endings`
        from `cleanup` on a project that legitimately uses them."""
        path = tmp_path / 'storyforge.yaml'
        path.write_bytes(b'artifacts:\r\n  chapter_map:\r\n'
                         b'    exists: false\r\n    updated:\r\n'
                         b'phase: drafting\r\n')
        update_artifact_entry(str(tmp_path), 'chapter_map',
                              exists=True, updated='2026-08-06')

        raw = path.read_bytes()
        assert b'exists: true\r\n' in raw
        assert b'updated: "2026-08-06"\r\n' in raw
        assert b'phase: drafting\r\n' in raw
        assert b'\n\r' not in raw

    def test_an_inserted_key_matches_crlf_line_endings(self, tmp_path):
        """The insert path builds a line from scratch, so it has to look at the
        file rather than assume LF — otherwise a CRLF project gains one stray LF
        line and `cleanup` reports mixed endings."""
        path = tmp_path / 'storyforge.yaml'
        path.write_bytes(b'artifacts:\r\n  chapter_map:\r\n'
                         b'    exists: false\r\n')
        update_artifact_entry(str(tmp_path), 'chapter_map',
                              updated='2026-08-06')

        raw = path.read_bytes()
        assert raw == (b'artifacts:\r\n  chapter_map:\r\n'
                       b'    exists: false\r\n'
                       b'    updated: "2026-08-06"\r\n')

    def test_an_insert_terminates_an_unterminated_preceding_line(
            self, tmp_path):
        """The insert must not append itself to the previous line.

        Without terminating it first, a block whose last line lacks a newline
        gets `path: reference/chapter-map.csv    updated: "..."` on one line —
        the `path` value destroyed, the YAML invalid, and `assemble` commits it.
        #276's own consequence class, produced by #276's fix; the earlier test
        covered only the *rewrite* path, where the regex supplies the newline.
        """
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n  chapter_map:\n'
            '    exists: false\n    path: reference/chapter-map.csv')
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', updated='2026-08-06') is True

        assert (tmp_path / 'storyforge.yaml').read_text() == (
            'artifacts:\n  chapter_map:\n'
            '    exists: false\n    path: reference/chapter-map.csv\n'
            '    updated: "2026-08-06"\n')

    def test_an_inserted_key_matches_a_four_space_project(self, tmp_path):
        """The child indent is read off the file, never assumed to be two.

        Guessing `key_indent + '  '` emitted the key at indent 6 among siblings
        at 8 — invalid YAML, and invisible to every Storyforge reader because
        they match `^\\s+key:` at any indent.
        """
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n    chapter_map:\n        exists: false\n')
        update_artifact_entry(str(tmp_path), 'chapter_map',
                              updated='2026-08-06')

        assert (tmp_path / 'storyforge.yaml').read_text() == (
            'artifacts:\n    chapter_map:\n'
            '        exists: false\n        updated: "2026-08-06"\n')

    def test_a_nested_key_of_the_same_name_is_not_matched(self, tmp_path):
        """`updated:` nested deeper must not be taken for the direct child."""
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n  chapter_map:\n'
            '    meta:\n      updated: "2020-01-01"\n'
            '    updated: "2021-01-01"\n')
        update_artifact_entry(str(tmp_path), 'chapter_map',
                              updated='2026-08-06')

        assert (tmp_path / 'storyforge.yaml').read_text() == (
            'artifacts:\n  chapter_map:\n'
            '    meta:\n      updated: "2020-01-01"\n'
            '    updated: "2026-08-06"\n')

    def test_a_value_cannot_inject_yaml(self, tmp_path):
        """A value is escaped, not interpolated raw.

        `updated` reaching the file unescaped let a crafted value close the
        scalar and open new top-level keys — #277's write-side half, in the
        module fixing #277's read side. The only caller passes an ISO date, so
        this was never reachable in production; it is pinned because the raw
        interpolation sat 80 lines from the escaper written to prevent it.
        """
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n  chapter_map:\n    exists: false\n    updated:\n'
            '\nphase: drafting\n')
        update_artifact_entry(str(tmp_path), 'chapter_map',
                              updated='2026-08-06"\nphase: PWNED\nx: "')

        content = (tmp_path / 'storyforge.yaml').read_text()
        # The payload survives as *text inside the scalar* — that is the point.
        # What must not happen is it becoming structure, so the assertion is
        # about top-level keys rather than about the substring appearing at all.
        top_level = [line for line in content.split('\n')
                     if line[:1].strip() and ':' in line]
        assert top_level == ['artifacts:', 'phase: drafting']
        assert content.count('\nphase:') == 1

    def test_a_file_without_a_trailing_newline_is_handled(self, tmp_path):
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n  chapter_map:\n    exists: false')
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', exists=True) is True
        assert (tmp_path / 'storyforge.yaml').read_text() == (
            'artifacts:\n  chapter_map:\n    exists: true\n')

    def test_exists_false_can_be_written(self, yaml_project):
        update_artifact_entry(yaml_project, 'chapter_map', exists=True)
        assert update_artifact_entry(
            yaml_project, 'chapter_map', exists=False) is True
        assert 'exists: false' in read_yaml(yaml_project)

    def test_an_artifact_name_outside_the_artifacts_block_is_not_matched(
            self, tmp_path):
        """The search stops at the end of `artifacts:`, and must.

        Without that bound the scan runs on into the rest of the file and the
        first same-named key anywhere wins — here a `manuscript:` under
        `production:`, which then gets `exists: true` and a date written into it.
        That is #276's failure mode (an unbounded match corrupting a block it
        was never meant to touch) rebuilt inside the function that replaced it,
        so it is pinned separately from the "artifact simply absent" case: both
        return False, so a return-value assertion cannot tell them apart.
        """
        path = tmp_path / 'storyforge.yaml'
        body = ('artifacts:\n'
                '  world_bible:\n'
                '    exists: false\n'
                '    updated:\n'
                'phase: drafting\n'
                'production:\n'
                '  manuscript:\n'
                '    exists: false\n'
                '    updated:\n')
        path.write_text(body)

        assert update_artifact_entry(
            str(tmp_path), 'manuscript', exists=True,
            updated='2026-08-06') is False
        assert path.read_text() == body

    def test_a_comment_line_inside_the_artifacts_block_is_tolerated(
            self, tmp_path):
        """The block-exit check exempts comment lines, so a commented-out
        artifact must not truncate the search for a later real one."""
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n'
            '# chapter_map is generated by `storyforge assemble`\n'
            '  chapter_map:\n'
            '    exists: false\n'
            '    updated:\n')
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', exists=True) is True
        assert 'exists: true' in (tmp_path / 'storyforge.yaml').read_text()

    def test_an_artifact_key_with_its_own_comment_is_matched(self, tmp_path):
        """`key_re` explicitly allows a trailing comment on the artifact line,
        and the comment survives untouched."""
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n'
            '  chapter_map:  # written by assemble\n'
            '    exists: false\n'
            '    updated:\n')
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', exists=True,
            updated='2026-08-06') is True

        content = (tmp_path / 'storyforge.yaml').read_text()
        assert '  chapter_map:  # written by assemble\n' in content
        assert 'updated: "2026-08-06"' in content

    def test_both_missing_keys_are_inserted_in_order(self, tmp_path):
        """Two inserts in one call — the only path that advances the insert
        position between them. Getting that wrong reverses the pair or lands the
        second outside the block."""
        (tmp_path / 'storyforge.yaml').write_text(
            'artifacts:\n'
            '  chapter_map:\n'
            '    path: reference/chapter-map.csv\n'
            '\n'
            '  manuscript:\n'
            '    path: manuscript/\n')
        assert update_artifact_entry(
            str(tmp_path), 'chapter_map', exists=True,
            updated='2026-08-06') is True

        assert (tmp_path / 'storyforge.yaml').read_text() == (
            'artifacts:\n'
            '  chapter_map:\n'
            '    path: reference/chapter-map.csv\n'
            '    exists: true\n'
            '    updated: "2026-08-06"\n'
            '\n'
            '  manuscript:\n'
            '    path: manuscript/\n')


# ===========================================================================
# #277 — one scalar parser, and it knows what a comment is
# ===========================================================================

#: The three historical copies. Parametrizing over them is what asserts the
#: "one such function" property holds — a future divergence fails here rather
#: than in whichever command happened to read the odd one out.
SCALAR_PARSERS = pytest.mark.parametrize('parse', [
    parse_yaml_scalar,
    _strip_yaml_value,
    _prompts_strip_yaml_value,
    _strip_yaml_quotes,
], ids=['common.parse_yaml_scalar', 'common._strip_yaml_value',
        'prompts._strip_yaml_value', 'assembly._strip_yaml_quotes'])


class TestParseYamlScalar:

    @SCALAR_PARSERS
    def test_inline_comment_is_not_part_of_a_quoted_value(self, parse):
        assert parse('"Children\'s chapter book"  # Primary genre') == (
            "Children's chapter book")

    @SCALAR_PARSERS
    def test_inline_comment_is_not_part_of_a_plain_value(self, parse):
        assert parse('fantasy   # Primary genre') == 'fantasy'

    @SCALAR_PARSERS
    def test_a_comment_only_field_is_empty_not_truthy(self, parse):
        """The `belongs-to-collection` bug: an unset field carrying a template
        comment read as a *value*, so a book with no series declared one."""
        assert parse('  # Optional: series title (e.g., "The Trilogy")') == ''

    @SCALAR_PARSERS
    def test_a_hash_not_preceded_by_whitespace_is_kept(self, parse):
        """YAML opens a comment only at the start or after whitespace. Stripping
        on a bare `#` is this bug pointed the other way — it would truncate a
        URL fragment or a CSS colour."""
        assert parse('a#b') == 'a#b'
        assert parse('#ff8800') == ''
        assert parse('"#ff8800"') == '#ff8800'

    @SCALAR_PARSERS
    def test_quotes_are_stripped(self, parse):
        assert parse('"quoted"') == 'quoted'
        assert parse("'quoted'") == 'quoted'
        assert parse('plain') == 'plain'
        assert parse('') == ''
        assert parse('   ') == ''

    @SCALAR_PARSERS
    def test_a_doubled_apostrophe_in_single_quotes_is_unescaped(self, parse):
        assert parse("'Children''s book'") == "Children's book"

    @SCALAR_PARSERS
    def test_escapes_in_double_quotes_are_resolved(self, parse):
        assert parse(r'"a \"quoted\" word"') == 'a "quoted" word'

    @SCALAR_PARSERS
    def test_an_unquoted_apostrophe_is_left_alone(self, parse):
        assert parse("The Cartographer's Silence") == (
            "The Cartographer's Silence")

    @SCALAR_PARSERS
    def test_malformed_quoting_degrades_rather_than_emptying(self, parse):
        """`""x""` is not valid YAML and its strict reading is the empty string.

        Returning that would turn a typo into a silently missing title, which is
        worse than the bug being fixed — so a malformed value keeps the lenient
        result it has always had.
        """
        assert parse('""Unicorn Tail""') == '"Unicorn Tail"'
        assert parse('"unterminated') == '"unterminated'

    @SCALAR_PARSERS
    def test_a_hash_inside_quotes_is_literal(self, parse):
        assert parse('"tagged #1 of 3"') == 'tagged #1 of 3'

    @SCALAR_PARSERS
    def test_escape_sequences_in_double_quotes_are_resolved(self, parse):
        r"""The escapes YAML defines are resolved; an unknown one is kept whole.

        Pinned separately from `test_escapes_in_double_quotes_are_resolved`,
        which only covers `\"` — and `\"` takes a branch that passes with the
        whole mapping deleted.
        """
        assert parse(r'"a\nb"') == 'a\nb'
        assert parse(r'"a\tb"') == 'a\tb'
        assert parse(r'"a\rb"') == 'a\rb'
        assert parse(r'"a\\b"') == 'a\\b'

    @SCALAR_PARSERS
    def test_numeric_escapes_are_resolved_not_left_as_prose(self, parse):
        r"""`\xNN` / `\uNNNN` / `\UNNNNNNNN` are real YAML escapes.

        The naive `\\(.)` rule consumed only the `x` or `u` and left the hex
        digits as literal text, so `"\x41"` came back as the string `x41` — an
        escape silently turned into nearby-looking prose, which is the class of
        failure this module exists to remove.
        """
        assert parse(r'"\x41"') == 'A'
        assert parse(r'"caf\xe9"') == 'café'
        assert parse(r'"\u00e9"') == 'é'
        assert parse(r'"\U0001F600"') == '\U0001f600'
        # Not hex, so not an escape — kept verbatim rather than half-eaten.
        assert parse(r'"\xZZ"') == r'\xZZ'

    @SCALAR_PARSERS
    def test_an_unknown_escape_keeps_its_backslash(self, parse):
        r"""YAML rejects `"a\qb"` outright, so neither reading is *correct*.

        Keeping the text shows the author what they typed; dropping the
        backslash — the previous behaviour — returned a plausible-looking value
        with no sign anything had happened.
        """
        assert parse(r'"a\qb"') == r'a\qb'
        assert parse(r'"prod\cover.png"') == r'prod\cover.png'

    @SCALAR_PARSERS
    def test_a_defined_escape_still_wins_over_a_windows_path(self, parse):
        r"""`"C:\temp"` resolving to `C:` + tab is *correct*, not a bug.

        `\t` is a defined YAML escape, so a double-quoted Windows path is
        genuinely ambiguous in YAML and this reading is the right one. Pinned so
        the unknown-escape change above is not mistaken for licence to stop
        resolving the defined ones. A literal backslash needs `\\`, or single
        quotes, where backslashes are literal.
        """
        assert parse(r'"C:\temp"') == 'C:\temp'
        assert parse(r'"C:\\temp"') == r'C:\temp'
        assert parse(r"'C:\temp'") == r'C:\temp'

    @SCALAR_PARSERS
    def test_a_trailing_backslash_in_double_quotes_degrades(self, parse):
        r"""`"a\` has no closing quote once the backslash consumes it, so it is
        malformed and takes the lenient fallback rather than raising."""
        assert parse('"a\\') == '"a\\'


class TestTheDelegationReachesTheProductionReaders:
    """The parametrized tests above call the three helpers directly.

    These go through the *production* entry points that read a real file, which
    is where #277 was actually observed: `assembly._strip_yaml_quotes`' docstring
    claims "an inline comment on `author:` or `language:` reached the epub
    metadata as part of the value", and nothing exercised that path end to end.
    """

    def _project(self, tmp_path, body):
        (tmp_path / 'storyforge.yaml').write_text(body)
        return str(tmp_path)

    def test_a_comment_on_a_production_field_is_not_part_of_the_value(
            self, tmp_path):
        project = self._project(tmp_path, (
            'production:\n'
            '  author: Ben Norris  # the author\n'
            '  language: en  # BCP-47 tag\n'))

        assert read_production_field(project, 'author') == 'Ben Norris'
        assert read_production_field(project, 'language') == 'en'

    def test_a_commented_production_field_reaches_the_epub_clean(self,
                                                                tmp_path):
        project = self._project(tmp_path, (
            'project:\n'
            '  title: "A Book"\n'
            'production:\n'
            '  author: Ben Norris  # the author\n'
            '  language: en  # BCP-47 tag\n'))

        metadata = generate_epub_metadata(project)
        parsed = parse_flat_metadata(metadata)
        assert parsed['author'] == 'Ben Norris'
        assert parsed['lang'] == 'en'
        assert '#' not in metadata

    def test_common_read_yaml_field_strips_an_inline_comment(self, tmp_path):
        """Note the argument order — `common.read_yaml_field(field, dir)` is the
        mirror of `prompts.read_yaml_field(file, field)`, the footgun CLAUDE.md
        documents. Both delegate to the same scalar parser."""
        project = self._project(tmp_path, (
            'project:\n'
            '  title: "The Lantern Folk"  # Working title\n'
            'phase: drafting  # not final\n'))

        assert read_yaml_field('project.title', project) == 'The Lantern Folk'
        assert read_yaml_field('phase', project) == 'drafting'


class TestYamlSingleQuote:

    def test_an_apostrophe_is_doubled(self):
        """The #277 crash: one apostrophe closed the string and pandoc exited
        64 on a valid project."""
        assert yaml_single_quote("Children's book") == "'Children''s book'"

    def test_a_plain_value_is_wrapped(self):
        assert yaml_single_quote('fantasy') == "'fantasy'"

    def test_double_quotes_need_no_escaping_in_this_style(self):
        assert yaml_single_quote('a "quoted" word') == '\'a "quoted" word\''

    def test_a_backslash_is_literal_in_this_style(self):
        assert yaml_single_quote(r'C:\path') == r"'C:\path'"

    def test_line_breaks_are_folded(self):
        assert yaml_single_quote('two\nlines') == "'two lines'"
        assert yaml_single_quote('two\r\nlines') == "'two lines'"

    def test_other_whitespace_is_left_exactly_as_the_author_wrote_it(self):
        """Folding every `\\s+` run corrupted a validated file path.

        `generate_epub_metadata` checks a cover path with `os.path.isfile` and
        then emits it through here, so `production/my  cover.png` was verified
        as real and written altered — pandoc then failed on a valid project,
        which is #277's failure mode restored by #277's fix. Tabs and
        non-breaking spaces in a title are the author's too.
        """
        assert yaml_single_quote('my  cover.png') == "'my  cover.png'"
        assert yaml_single_quote('a\tb') == "'a\tb'"
        assert yaml_single_quote('The\xa0Lantern Folk') == "'The\xa0Lantern Folk'"

    def test_the_reader_and_the_writer_agree(self):
        """The invariant the four-way parser parametrization does not cover.

        `parse_yaml_scalar` and `yaml_single_quote` are a reader/writer pair over
        one wire format, and #277 *was* those two halves disagreeing — the PR
        established "one reader" rigorously and asserted nothing about
        reader-matches-writer. Every value here is one that could plausibly break
        the round trip: a leading `#`, an embedded `#`, a colon, a list marker, a
        YAML keyword, nothing but apostrophes.
        """
        for value in ['#ff8800', 'a#b', 'a: b', '- item', 'null', 'true', '42',
                      "'''", "O'Brien", 'has "double" quotes', 'my  cover.png',
                      '', ' leading', 'trailing ']:
            emitted = yaml_single_quote(value)
            assert parse_yaml_scalar(emitted) == value.strip(), (
                f'{value!r} did not survive {emitted!r}')

    def test_double_quoting_is_deliberately_not_idempotent(self):
        """Applying the writer twice yields *valid* YAML with a wrong value.

        Pinned because that is the dangerous shape: nothing raises, nothing looks
        malformed, and the value has gained quotes. A `NewType` would not catch
        it — a NewType stays assignable to `str` — so the guard is this test.
        """
        once = yaml_single_quote("O'Brien")
        twice = yaml_single_quote(once)
        assert parse_yaml_scalar(twice) == once
        assert parse_yaml_scalar(twice) != "O'Brien"

    def test_it_round_trips_through_an_independent_parser(self):
        for value in ["Children's book", "O'Brien", 'plain',
                      "a'b''c", 'has "double" quotes', '#ff8800']:
            emitted = f'subject: {yaml_single_quote(value)}'
            assert parse_flat_metadata(emitted)['subject'] == value


# ===========================================================================
# #277 end to end — the metadata block pandoc actually receives
# ===========================================================================

class TestEpubMetadataEscaping:

    def _write_project_yaml(self, tmp_path, body):
        (tmp_path / 'storyforge.yaml').write_text(body)
        return str(tmp_path)

    def test_an_apostrophe_in_genre_produces_parseable_yaml(self, tmp_path):
        """The exact repro: `genre` with an apostrophe *and* an inline comment.

        Before the fix this emitted
        `subject: '"Children's chapter book"     # Primary genre'`
        and pandoc died with "did not find expected key".
        """
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "The Lantern Folk"\n'
            '  genre: "Children\'s chapter book"  # Primary genre\n'
            'production:\n'
            '  author: Ben Norris\n'))

        parsed = parse_flat_metadata(generate_epub_metadata(project))
        assert parsed['subject'] == "Children's chapter book"
        assert parsed['title'] == 'The Lantern Folk'

    def test_the_emitted_block_doubles_an_apostrophe(self, tmp_path):
        """The escaping is asserted on the *bytes*, not through a parse.

        A parse cannot see this: `'O'Brien'` and `'O''Brien'` reduce to the same
        value under any reader lenient enough to accept the first, which is why
        `generate_epub_metadata` passed every metadata test with
        `yaml_single_quote` removed from it while pandoc exited 64 on the output.
        `parse_flat_metadata` now rejects the undoubled form too; this test says
        the same thing in the one form that cannot drift — the literal string.
        """
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "It\'s Here"\n'
            'production:\n'
            "  author: O'Brien\n"
            '  copyright:\n'
            '    year: 2026\n'))

        metadata = generate_epub_metadata(project)
        assert "title: 'It''s Here'" in metadata
        assert "author: 'O''Brien'" in metadata
        assert "rights: 'Copyright © 2026 O''Brien'" in metadata

    def test_an_apostrophe_in_the_author_reaches_title_and_rights(self,
                                                                 tmp_path):
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "A Book"\n'
            'production:\n'
            "  author: Flannery O'Connor\n"))

        parsed = parse_flat_metadata(generate_epub_metadata(project))
        assert parsed['author'] == "Flannery O'Connor"
        assert parsed['rights'].endswith("Flannery O'Connor")

    def test_an_empty_series_name_with_a_comment_emits_no_collection(
            self, tmp_path):
        """A book with no series must not declare one."""
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "A Book"\n'
            '  series_name:  # Optional: series title (e.g., "The Trilogy")\n'
            '  series_position:  # Optional: 1, 2, 3\n'
            'production:\n'
            '  author: Ben Norris\n'))

        metadata = generate_epub_metadata(project)
        assert 'belongs-to-collection' not in metadata
        assert 'group-position' not in metadata

    def test_a_real_series_name_still_emits_a_collection(self, tmp_path):
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "A Book"\n'
            '  series_name: "The Mapmaker Trilogy"  # series\n'
            '  series_position: 2\n'
            'production:\n'
            '  author: Ben Norris\n'))

        parsed = parse_flat_metadata(generate_epub_metadata(project))
        assert parsed['belongs-to-collection'] == 'The Mapmaker Trilogy'
        assert parsed['group-position'] == '2'

    def test_a_declared_but_missing_cover_warns(self, tmp_path, capsys):
        """It was dropped in silence — the one quiet cover consumer in the repo.

        `_resolve_cover_path` warns and `require_cover_asset` refuses, because an
        epub built without the cover the author declared is a wrong artifact that
        looks like a right one.
        """
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "A Book"\n'
            'production:\n'
            '  author: Ben Norris\n'
            '  cover_image: production/nope.png\n'))

        metadata = generate_epub_metadata(project)
        assert 'cover-image' not in metadata
        out = capsys.readouterr().out
        assert 'WARNING' in out and 'production/nope.png' in out

    def test_a_cover_that_exists_is_emitted_without_a_warning(self, tmp_path):
        (tmp_path / 'production').mkdir()
        (tmp_path / 'production' / 'cover.png').write_bytes(b'x')
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "A Book"\n'
            'production:\n'
            '  author: Ben Norris\n'
            '  cover_image: production/cover.png\n'))

        parsed = parse_flat_metadata(generate_epub_metadata(project))
        assert parsed['cover-image'].endswith('production/cover.png')

    def test_a_cover_path_with_a_double_space_is_not_altered(self, tmp_path):
        """The path is validated with `os.path.isfile` and then emitted, so
        folding whitespace verified a real file and wrote a different one."""
        (tmp_path / 'production').mkdir()
        (tmp_path / 'production' / 'my  cover.png').write_bytes(b'x')
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "A Book"\n'
            'production:\n'
            '  author: Ben Norris\n'
            '  cover_image: "production/my  cover.png"\n'))

        parsed = parse_flat_metadata(generate_epub_metadata(project))
        assert parsed['cover-image'].endswith('production/my  cover.png')
        assert os.path.isfile(parsed['cover-image'])

    def test_a_commented_title_does_not_carry_its_comment(self, tmp_path):
        """The earlier symptom #277 mentions: the project title carried its
        inline `# Working title` comment into output."""
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "The Lantern Folk"  # Working title, may change\n'
            'production:\n'
            '  author: Ben Norris\n'))

        parsed = parse_flat_metadata(generate_epub_metadata(project))
        assert parsed['title'] == 'The Lantern Folk'
        assert 'Working title' not in generate_epub_metadata(project)

    def test_every_value_in_a_full_project_is_quoted_and_parseable(
            self, tmp_path):
        """`parse_flat_metadata` asserts the quoting; this exercises every
        emitted key at once, including the ones with no author input."""
        project = self._write_project_yaml(tmp_path, (
            'project:\n'
            '  title: "It\'s Here"\n'
            '  genre: "Children\'s"\n'
            '  series_name: "O\'Brien\'s Trilogy"\n'
            '  series_position: 3\n'
            'production:\n'
            "  author: O'Brien\n"
            '  language: en\n'
            '  copyright:\n'
            '    year: 2026\n'
            '    isbn: 978-0-000000-00-0\n'))

        parsed = parse_flat_metadata(generate_epub_metadata(project))
        assert parsed == {
            'title': "It's Here",
            'author': "O'Brien",
            'lang': 'en',
            'date': '2026',
            'subject': "Children's",
            'identifier': '978-0-000000-00-0',
            'belongs-to-collection': "O'Brien's Trilogy",
            'group-position': '3',
            'rights': 'Copyright © 2026 O\'Brien',
        }
