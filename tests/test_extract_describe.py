"""Extract phase 5's never-overwrite rule and provenance record (#440)."""

import os
import shutil

import pytest

from storyforge.common import get_plugin_dir
from storyforge.extract_describe import (
    PROVENANCE_FILE, file_state, may_write, provenance_header, read_provenance,
    record_written, refusal,
)

TEMPLATES = os.path.join(get_plugin_dir(), 'templates', 'reference')


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'reference').mkdir()
    return tmp_path


def _write(project, rel, content, mode='w'):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        with open(path, mode, encoding='utf-8', newline='') as f:
            f.write(content)
    return rel


class TestFileState:
    def test_missing(self, project):
        assert file_state(str(project), 'reference/voice-guide.md') == 'missing'

    def test_whitespace_only_is_empty(self, project):
        rel = _write(project, 'reference/voice-guide.md', '\n  \n')
        assert file_state(str(project), rel) == 'empty'

    def test_template_copy(self, project):
        shutil.copy(os.path.join(TEMPLATES, 'voice-guide.md'),
                    project / 'reference' / 'voice-guide.md')
        assert file_state(str(project), 'reference/voice-guide.md') == 'template'

    def test_template_saved_with_crlf_and_bom_is_still_the_template(self, project):
        with open(os.path.join(TEMPLATES, 'world-bible.md'), encoding='utf-8') as f:
            text = f.read()
        rel = _write(project, 'reference/world-bible.md',
                     '﻿'.encode() + text.replace('\n', '\r\n').encode())
        assert file_state(str(project), rel) == 'template'

    @pytest.mark.parametrize('header', [
        'id|seq|title|function|act\n',            # the old template's header
        'id|seq|title|summary|function|act\n',    # today's
        'id|name\r\n\r\n',
    ])
    def test_any_header_only_csv(self, project, header):
        rel = _write(project, 'reference/spine.csv', header)
        assert file_state(str(project), rel) == 'header_only'

    def test_a_csv_with_a_row_is_the_authors(self, project):
        rel = _write(project, 'reference/themes.csv', 'id|name|tier|description\nhope|Hope|1|x\n')
        assert file_state(str(project), rel) == 'author'

    def test_an_edited_doc_is_the_authors(self, project):
        rel = _write(project, 'reference/character-bible.md', '# Nick\n\nThe author wrote this.\n')
        assert file_state(str(project), rel) == 'author'

    def test_undecodable_is_unreadable(self, project):
        rel = _write(project, 'reference/voice-guide.md', b'\xff\xfe\x00bad latin-1 \xe9')
        assert file_state(str(project), rel) == 'unreadable'

    def test_extracted_and_unchanged(self, project):
        rel = _write(project, 'reference/voice-guide.md', '# Voice\n\nDescribed.\n')
        record_written(str(project), rel, '5f', '1.101.0')
        assert file_state(str(project), rel) == 'extracted'

    def test_extracted_then_edited(self, project):
        rel = _write(project, 'reference/voice-guide.md', '# Voice\n\nDescribed.\n')
        record_written(str(project), rel, '5f', '1.101.0')
        _write(project, rel, '# Voice\n\nDescribed, and the author added a line.\n')
        assert file_state(str(project), rel) == 'edited'

    def test_extracted_then_reset_to_template_is_free_again(self, project):
        rel = _write(project, 'reference/voice-guide.md', '# Voice\n\nDescribed.\n')
        record_written(str(project), rel, '5f', '1.101.0')
        shutil.copy(os.path.join(TEMPLATES, 'voice-guide.md'), project / rel)
        assert file_state(str(project), rel) == 'template'

    def test_extracted_csv_cleared_to_its_header_is_free_again(self, project):
        rel = _write(project, 'reference/themes.csv', 'id|name|tier|description\nhope|Hope|1|x\n')
        record_written(str(project), rel, '5b', '1.101.0')
        _write(project, rel, 'id|name|tier|description\n')
        assert file_state(str(project), rel) == 'header_only'


class TestMayWrite:
    @pytest.mark.parametrize('state', ['missing', 'empty', 'header_only', 'template'])
    @pytest.mark.parametrize('force', [False, True])
    def test_free_states(self, state, force):
        assert may_write(state, force)
        assert refusal('reference/x.md', state, force) == ''

    def test_extracted_only_under_force(self):
        assert not may_write('extracted', False)
        assert may_write('extracted', True)
        assert '--force' in refusal('reference/x.md', 'extracted', False)

    @pytest.mark.parametrize('state', ['edited', 'author', 'unreadable'])
    def test_never_with_or_without_force(self, state):
        assert not may_write(state, False)
        assert not may_write(state, True)
        # Every refusal is said, so silence means the file was written
        assert refusal('reference/x.md', state, True).startswith('reference/x.md: kept')


class TestProvenance:
    def test_one_row_per_file_latest_wins(self, project):
        rel = _write(project, 'reference/spine.csv', 'id|seq\na|1\n')
        record_written(str(project), rel, '5a', '1.101.0')
        _write(project, rel, 'id|seq\na|1\nb|2\n')
        record_written(str(project), rel, '5a', '1.102.0')
        rows = read_provenance(str(project))
        assert list(rows) == ['reference/spine.csv']
        assert rows['reference/spine.csv']['version'] == '1.102.0'
        assert file_state(str(project), rel) == 'extracted'

    def test_written_lf(self, project):
        rel = _write(project, 'reference/spine.csv', 'id|seq\na|1\n')
        record_written(str(project), rel, '5a', '1.101.0')
        assert b'\r' not in (project / PROVENANCE_FILE).read_bytes()

    def test_unreadable_record_fails_safe(self, project, capsys):
        """A broken record must make --force refuse, never overwrite."""
        rel = _write(project, 'reference/voice-guide.md', '# Voice\n\nDescribed.\n')
        record_written(str(project), rel, '5f', '1.101.0')
        (project / PROVENANCE_FILE).write_bytes(b'\xff\xfe\x00broken')
        assert read_provenance(str(project)) == {}
        assert 'WARNING' in capsys.readouterr().out
        assert file_state(str(project), rel) == 'author'
        assert not may_write('author', True)

    def test_header_line(self):
        assert provenance_header('1.101.0', '5c', ['profile', 'spine']) == \
            '<!-- storyforge:extracted v1.101.0 step=5c from=profile,spine -->'
        assert 'vunknown' in provenance_header('', '5c', ['profile'])
