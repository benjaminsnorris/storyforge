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

from storyforge.assembly import (
    _strip_yaml_quotes,
    generate_epub_metadata,
)
from storyforge.common import (
    _strip_yaml_value,
    parse_yaml_scalar,
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


def parse_flat_metadata(metadata: str) -> dict[str, str]:
    """Parse the epub metadata block, independently of the code under test.

    Not `parse_yaml_scalar` — that is what these tests verify, and using it here
    would let a regression agree with itself. Not pyyaml either: it is on no
    declared dependency list and the repo's YAML handling is dependency-free.
    Single-quoted YAML is small enough to read directly: strip the outer quotes,
    unescape a doubled apostrophe.
    """
    out: dict[str, str] = {}
    for line in metadata.split('\n'):
        if line.strip() in ('---', ''):
            continue
        key, _, raw = line.partition(': ')
        raw = raw.strip()
        assert raw.startswith("'") and raw.endswith("'"), (
            f'every emitted value must be quoted, got {line!r}')
        out[key.strip()] = raw[1:-1].replace("''", "'")
    return out


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

    def test_newlines_are_collapsed(self):
        assert yaml_single_quote('two\nlines') == "'two lines'"

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
