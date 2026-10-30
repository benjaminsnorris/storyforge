"""Extract phase 5's write gate and provenance record (#440)."""

import os
import shutil
from typing import get_args, get_type_hints

import pytest

from storyforge.common import get_plugin_dir
from storyforge.extract_describe import (
    _POLICY, PROVENANCE_COLUMNS, PROVENANCE_FILE, FileState, ProvenanceError,
    ProvenanceRow, decide, file_state, provenance_header, read_provenance,
    write_described,
)

TEMPLATES = os.path.join(get_plugin_dir(), 'templates', 'reference')
FREE = {'missing', 'empty', 'header_only', 'template'}


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'reference').mkdir()
    return tmp_path


def _put(project, rel, content):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
    return rel


def _write(project, rel, content, force=False, step='5f'):
    return write_described(str(project), rel, content, step=step, version='1.101.0',
                           force=force, provenance=read_provenance(str(project)))


def _state(project, rel):
    return file_state(str(project), rel, read_provenance(str(project)))


class TestFileState:
    def test_missing(self, project):
        assert _state(project, 'reference/voice-guide.md') == 'missing'

    def test_whitespace_only_is_empty(self, project):
        assert _state(project, _put(project, 'reference/voice-guide.md', '\n  \n')) == 'empty'

    def test_template_copy(self, project):
        shutil.copy(os.path.join(TEMPLATES, 'voice-guide.md'),
                    project / 'reference' / 'voice-guide.md')
        assert _state(project, 'reference/voice-guide.md') == 'template'

    def test_template_saved_with_crlf_and_bom_is_still_the_template(self, project):
        with open(os.path.join(TEMPLATES, 'world-bible.md'), encoding='utf-8') as f:
            text = f.read()
        rel = _put(project, 'reference/world-bible.md',
                   '﻿'.encode() + text.replace('\n', '\r\n').encode())
        assert _state(project, rel) == 'template'

    @pytest.mark.parametrize('header', [
        'id|seq|title|function|act\n',            # the old template's header
        'id|seq|title|summary|function|act\n',    # today's
        'id|name\r\n\r\n',
        'character|preferred_words|banned_words\n',   # voice-profile.csv
    ])
    def test_any_header_only_csv(self, project, header):
        assert _state(project, _put(project, 'reference/spine.csv', header)) == 'header_only'

    @pytest.mark.parametrize('line', ['grief|Grief|core|What loss costs',
                                      'My only theme|grief',
                                      'grief|loss'])   # column-shaped, but no key column
    def test_a_one_line_csv_without_a_header_is_the_authors(self, project, line):
        """Review SF-4: any single line counted as a header, so a hand-written
        one-row file was 'content-free' and replaced."""
        assert _state(project, _put(project, 'reference/themes.csv', line + '\n')) == 'author'

    def test_a_csv_with_a_row_is_the_authors(self, project):
        rel = _put(project, 'reference/themes.csv', 'id|name|tier|description\nhope|Hope|1|x\n')
        assert _state(project, rel) == 'author'

    def test_an_edited_doc_is_the_authors(self, project):
        rel = _put(project, 'reference/character-bible.md', '# Nick\n\nThe author wrote this.\n')
        assert _state(project, rel) == 'author'

    def test_undecodable_is_unreadable_and_says_why(self, project, capsys):
        rel = _put(project, 'reference/voice-guide.md', b'\xff\xfe\x00bad \xe9')
        assert _state(project, rel) == 'unreadable'
        assert 'reference/voice-guide.md could not be read' in capsys.readouterr().out

    def test_a_directory_is_unreadable(self, project):
        (project / 'reference' / 'voice-guide.md').mkdir()
        assert _state(project, 'reference/voice-guide.md') == 'unreadable'

    @pytest.mark.parametrize('dangling', [True, False])
    def test_a_symlink_is_never_written_through(self, project, tmp_path_factory, dangling):
        """Review SF-3: a dangling link read as 'missing', and the write
        followed it to create a file outside the project."""
        outside = tmp_path_factory.mktemp('series') / 'world-bible.md'
        if not dangling:
            outside.write_text('')   # an empty target would read as 'empty'
        os.symlink(outside, project / 'reference' / 'world-bible.md')
        assert _state(project, 'reference/world-bible.md') == 'symlink'
        verdict = _write(project, 'reference/world-bible.md', '# World\n')
        assert not verdict.write
        assert outside.exists() is not dangling   # nothing created
        if not dangling:
            assert outside.read_text() == ''

    def test_extracted_and_unchanged(self, project):
        _write(project, 'reference/voice-guide.md', '# Voice\n\nDescribed.\n')
        assert _state(project, 'reference/voice-guide.md') == 'extracted'

    def test_extracted_then_edited(self, project):
        _write(project, 'reference/voice-guide.md', '# Voice\n\nDescribed.\n')
        _put(project, 'reference/voice-guide.md', '# Voice\n\nDescribed, and a line.\n')
        assert _state(project, 'reference/voice-guide.md') == 'edited'

    def test_extracted_then_reset_to_template_is_free_again(self, project):
        _write(project, 'reference/voice-guide.md', '# Voice\n\nDescribed.\n')
        shutil.copy(os.path.join(TEMPLATES, 'voice-guide.md'),
                    project / 'reference' / 'voice-guide.md')
        assert _state(project, 'reference/voice-guide.md') == 'template'

    def test_extracted_csv_cleared_to_its_header_is_free_again(self, project):
        _write(project, 'reference/themes.csv', 'id|name|tier|description\nhope|Hope|1|x\n',
               step='5b')
        _put(project, 'reference/themes.csv', 'id|name|tier|description\n')
        assert _state(project, 'reference/themes.csv') == 'header_only'

    def test_a_record_with_no_hash_is_not_extracted(self, project):
        rel = _put(project, 'reference/voice-guide.md', '# Voice\n')
        _put(project, PROVENANCE_FILE,
             '|'.join(PROVENANCE_COLUMNS) + '\nreference/voice-guide.md|1.0|5f|t|\n')
        assert _state(project, rel) == 'edited'

    def test_the_path_spelling_does_not_matter(self, project):
        _write(project, 'reference/voice-guide.md', '# Voice\n')
        assert file_state(str(project), './reference//voice-guide.md',
                          read_provenance(str(project))) == 'extracted'


class TestPolicy:
    def test_total_over_every_state(self):
        """A new FileState must get its own rule and sentence, not inherit
        another state's."""
        assert set(_POLICY) == set(get_args(FileState))
        for state, (rule, reason) in _POLICY.items():
            assert (rule == 'free') == (reason == ''), state

    @pytest.mark.parametrize('force', [False, True])
    def test_free_states_are_written(self, project, force):
        for rel in ('reference/a.md', 'reference/b.md'):
            verdict = decide(str(project), rel, force, {})
            assert verdict.write and verdict.report() == '' and verdict.state == 'missing'

    def test_extracted_only_under_force(self, project):
        _write(project, 'reference/voice-guide.md', '# Voice\n')
        kept = _write(project, 'reference/voice-guide.md', '# Voice v2\n')
        assert kept.report() == ('reference/voice-guide.md: kept (extracted earlier; '
                                 '--force regenerates it)')
        assert (project / 'reference/voice-guide.md').read_text() == '# Voice\n'
        assert _write(project, 'reference/voice-guide.md', '# Voice v2\n', force=True).write
        assert (project / 'reference/voice-guide.md').read_text() == '# Voice v2\n'
        assert _state(project, 'reference/voice-guide.md') == 'extracted'

    def test_never_states_are_kept_with_or_without_force(self, project):
        rel = _put(project, 'reference/character-bible.md', '# Mine\n')
        for force in (False, True):
            verdict = _write(project, rel, '# Extracted\n', force=force)
            assert verdict.state == 'author'
            assert verdict.report().startswith('reference/character-bible.md: kept')
        assert (project / rel).read_text() == '# Mine\n'


class TestProvenance:
    def test_columns_match_the_row_type(self):
        assert PROVENANCE_COLUMNS == list(get_type_hints(ProvenanceRow))

    def test_one_row_per_file_latest_wins_and_lf(self, project):
        _write(project, 'reference/spine.csv', 'id|seq\na|1\n', step='5a')
        _write(project, 'reference/spine.csv', 'id|seq\na|1\nb|2\n', step='5a', force=True)
        rows = read_provenance(str(project))
        assert list(rows) == ['reference/spine.csv']
        assert b'\r' not in (project / PROVENANCE_FILE).read_bytes()

    def test_the_callers_record_is_updated_in_place(self, project):
        provenance = read_provenance(str(project))
        write_described(str(project), 'reference/a.md', 'x\n', step='5c', version='1',
                        force=False, provenance=provenance)
        assert 'reference/a.md' in provenance

    @pytest.mark.parametrize('broken', [
        b'\xff\xfe\x00broken',                                       # undecodable
        b'file|version|step|written_at|sha256\n' + b'x' * 200_000 + b'|1|5a|t|abc\n',  # csv.Error
        b'path|sha256\nreference/a.md|abc\n',                        # another shape
    ])
    def test_an_unusable_record_is_never_rewritten(self, project, capsys, broken):
        """Review SF-1/SF-2/TD: a failed read returned {}, and the next write
        rewrote the record with one row, erasing every other file's."""
        _write(project, 'reference/a.md', '# A\n')
        _put(project, PROVENANCE_FILE, broken)
        provenance = read_provenance(str(project))
        assert provenance is None
        assert 'could not be used' in capsys.readouterr().out
        # A file with content can't be verified, so it is kept, and says why
        verdict = decide(str(project), 'reference/a.md', True, provenance)
        assert verdict.state == 'unverified' and 'could not be read' in verdict.reason
        # Nothing is written, and the broken record is left as it was
        with pytest.raises(ProvenanceError):
            write_described(str(project), 'reference/b.md', '# B\n', step='5c',
                            version='1', force=False, provenance=provenance)
        assert not (project / 'reference/b.md').exists()
        assert (project / PROVENANCE_FILE).read_bytes() == broken

    def test_a_record_that_is_a_directory_is_unusable(self, project):
        (project / PROVENANCE_FILE).mkdir(parents=True)
        assert read_provenance(str(project)) is None

    def test_header_line(self):
        assert provenance_header('1.101.0', '5c', ['profile', 'spine']) == \
            '<!-- storyforge:extracted v1.101.0 step=5c from=profile,spine -->'
        assert 'vunknown' in provenance_header('', '5c', ['profile'])
