"""The book's voice folder, reference/voice/ (ready-to-draft plan,
2026-11-14): book.md and the anchors are the voice a writer gets; checks.md
is for a reviewer only; the pipeline's voice files are no longer read."""

import os
import shutil

import pytest

from storyforge import voice_book as vb
from storyforge.common import ReferenceDocError


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'wb' if isinstance(text, bytes) else 'w'
    with open(path, mode) as f:
        f.write(text)


# --- anchors ---

def test_an_anchor_header_is_read_and_left_out_of_the_passage():
    a = vb.parse_anchor('a.md', 'kind: Battle, God\ntense: Past\npov: Zeus\n\nHe nodded.\n')
    assert (a.kind, a.tense, a.pov, a.text) == (('battle', 'god'), 'past', 'Zeus', 'He nodded.')
    assert a.label() == 'a (kind: battle, god; tense: past; POV: Zeus)'


def test_a_first_paragraph_that_isnt_all_header_is_the_passage():
    raw = 'kind: battle\nHe ran at the wall.\n\nThen he fell.'
    a = vb.parse_anchor('a.md', raw)
    assert a.kind == () and a.text == raw
    # prose that happens to start "Note: ..." is prose
    assert vb.parse_anchor('b.md', 'Note: she said.\n\nMore.').text.startswith('Note:')


def test_a_header_without_a_passage_or_with_a_bad_tense_is_refused():
    with pytest.raises(ValueError, match='empty'):
        vb.parse_anchor('a.md', 'kind: battle\n\n')
    with pytest.raises(ValueError, match="tense 'future'"):
        vb.parse_anchor('a.md', 'tense: future\n\nText.')
    with pytest.raises(ValueError, match='given twice'):
        vb.parse_anchor('a.md', 'kind: a\nkind: b\n\nText.')


def test_a_bad_anchor_is_left_out_and_said(project_dir):
    _write(os.path.join(project_dir, vb.ANCHORS_DIR, 'zz-bad.md'), 'tense: future\n\nText.')
    folder = vb.read_folder(project_dir)
    assert [a.name for a in folder.anchors] == ['dorren-at-the-survey']
    assert any('zz-bad.md' in s for s in folder.skipped)
    shutil.rmtree(os.path.join(project_dir, vb.ANCHORS_DIR))
    _write(os.path.join(project_dir, vb.ANCHORS_DIR, 'bad.md'), 'tense: future\n\nText.')
    v = vb.resolve(project_dir)
    assert v.kind == 'empty' and 'bad.md' in v.detail     # why there's no anchor


def test_non_markdown_files_in_anchors_are_ignored(project_dir):
    _write(os.path.join(project_dir, vb.ANCHORS_DIR, 'notes.txt'), 'Not an anchor.')
    assert [a.name for a in vb.read_folder(project_dir).anchors] == ['dorren-at-the-survey']


# --- the writing section ---

def test_the_writing_section_never_carries_checks(project_dir):
    text = vb.resolve(project_dir).text
    assert 'Measures before it feels' in text and 'The village was not there' in text
    assert 'Her heart pounded' not in text
    assert 'Her heart pounded' in vb.checks_text(project_dir)


def test_render_puts_the_authors_voice_first():
    folder = vb.BookVoiceFolder('Notes.', (vb.Anchor('x.md', 'Passage.'),))
    text = vb.render(folder, 'AUTHOR')
    assert text.index('AUTHOR') < text.index('Notes.') < text.index('Passage.')


def test_a_template_checks_md_is_empty(project_dir):
    shutil.copy(os.path.join(vb.get_plugin_dir(), 'templates', vb.CHECKS_FILE),
                os.path.join(project_dir, vb.CHECKS_FILE))
    assert vb.checks_text(project_dir) == ''


def test_an_unreadable_checks_md_raises(project_dir):
    _write(os.path.join(project_dir, vb.CHECKS_FILE), b'\xff\xfe')
    with pytest.raises(ReferenceDocError, match='checks.md'):
        vb.checks_text(project_dir)


def test_register_section(project_dir):
    _write(os.path.join(project_dir, vb.BOOK_FILE),
           '# V\n\n## Register exemptions\n\n- "by my faith"\n\n## People\n\nX.\n')
    assert vb.register_section(project_dir, 'Register exemptions') == '- "by my faith"'
    assert vb.register_section(project_dir, 'Missing') == ''


# --- the old files ---

@pytest.mark.parametrize('rel', ['reference/voice-guide.md', 'reference/voice-profile.csv',
                                 'reference/persistent-prompt.md',
                                 'reference/prose-exemplars.md',
                                 'reference/exemplars/dorren.md',
                                 'references/voice-guide.md'])
def test_each_old_voice_file_is_named_and_kept(project_dir, rel):
    _write(os.path.join(project_dir, rel), 'Old.\n')
    note = vb.old_files_note(project_dir)
    assert os.path.dirname(rel) == 'reference/exemplars' or rel in note
    assert 'no longer read' in note and 'delete it' in note
    assert os.path.exists(os.path.join(project_dir, rel))


def test_no_old_files_no_note(project_dir):
    assert vb.old_voice_files(project_dir) == [] and vb.old_files_note(project_dir) == ''


def test_cleanup_reports_old_voice_files_in_a_prose_book_only(project_dir, monkeypatch):
    from storyforge import cmd_cleanup
    _write(os.path.join(project_dir, 'reference', 'voice-guide.md'), 'Old.\n')
    issues = cmd_cleanup.report_csv_schema(project_dir)
    assert 'OLD_VOICE_FILE:reference/voice-guide.md' in issues
    finding = cmd_cleanup._classify_issue('OLD_VOICE_FILE:reference/voice-guide.md', {})
    assert finding['type'] == 'old_voice_file' and finding['severity'] == 'warning'
    assert 'never' not in finding['action'] and 'delete the file' in finding['action']
    monkeypatch.setattr(cmd_cleanup, 'get_medium', lambda pd: 'graphic-novel')
    assert not [i for i in cmd_cleanup.report_csv_schema(project_dir)
                if i.startswith('OLD_VOICE_FILE')]


# --- setting up the folder ---

def test_scaffold_makes_only_what_is_missing(tmp_path):
    made = vb.scaffold(str(tmp_path))
    assert made == list(vb.SCAFFOLD)
    assert vb.resolve(str(tmp_path)).kind == 'template'
    assert vb.scaffold(str(tmp_path)) == []
    _write(str(tmp_path / vb.BOOK_FILE), 'Mine.\n')
    assert vb.scaffold(str(tmp_path)) == []
    with open(tmp_path / vb.BOOK_FILE) as f:
        assert f.read() == 'Mine.\n'


def test_scaffold_dry_run_writes_nothing(tmp_path):
    assert vb.scaffold(str(tmp_path), dry_run=True) == list(vb.SCAFFOLD)
    assert not os.path.exists(tmp_path / 'reference')


# --- tense ---

PRESENT = ('He walks to the gate. He sees her. She is running. He takes her hand. '
           'She says nothing. He looks at the boy, who turns away. He knows. She feels '
           'his hand. They stand there. He waits. He finds the words. He holds them.')
PAST = ('He walked to the gate. He saw her. She was running. He took her hand. '
        'She said nothing. He looked at the boy, who turned away. He knew. She felt '
        'his hand. They stood there. He waited. He found the words. He held them.')


def test_tense_is_read_from_narration_not_speech():
    r = vb.read_tense(PRESENT + ' "I was there. I saw it. I knew."')
    assert r.past == 0 and r.present >= vb.MIN_TENSE_SIGNALS
    curly = vb.read_tense('“I was there, I saw, I knew, I said,” he says.')
    assert curly.past == 0 and curly.present == 1


@pytest.mark.parametrize('prose, declared, problem', [
    (PRESENT, 'present', False), (PAST, 'past', False),
    (PRESENT, 'past', True), (PAST, 'present', True),
    (PAST, '', False), (PAST, 'future', False),
    ('He walked. She saw.', 'present', False),            # too short to judge
])
def test_tense_problem(prose, declared, problem):
    assert bool(vb.tense_problem(prose, declared)) is problem


def test_present_narration_may_still_say_had_and_was():
    # what came before is told in the past inside a present-tense scene
    prose = PRESENT + ' He had been here before. It was spring then. He was young.'
    assert vb.tense_problem(prose, 'present') == ''
