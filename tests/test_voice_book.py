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
    folder = vb.BookVoiceFolder(notes='Notes.', notes_state='ok',
                                anchors=(vb.Anchor('x.md', 'Passage.'),))
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


@pytest.mark.parametrize('prose, declared, verdict', [
    (PRESENT, 'present', vb.TENSE_OK), (PAST, 'past', vb.TENSE_OK),
    (PRESENT, 'past', vb.TENSE_MISMATCH), (PAST, 'present', vb.TENSE_MISMATCH),
    (PAST, '', vb.TENSE_NOT_SAID), (PAST, 'future', vb.TENSE_NOT_SAID),
    ('He walked. She saw.', 'present', vb.TENSE_UNJUDGED),
])
def test_check_tense(prose, declared, verdict):
    check = vb.check_tense(prose, declared)
    assert check.verdict == verdict
    # what isn't checked is said, never silent
    if verdict in (vb.TENSE_UNJUDGED, vb.TENSE_MISMATCH) or declared == 'future':
        assert check.detail


def test_present_narration_may_still_say_had_and_was():
    # what came before is told in the past inside a present-tense scene
    prose = PRESENT + ' He had been here before. It was spring then. He was young.'
    assert vb.check_tense(prose, 'present').verdict == vb.TENSE_OK


def test_single_curly_speech_with_a_contraction_is_speech():
    r = vb.read_tense(PRESENT + ' ‘I don’t know what I was, or what I saw, or felt,’ he says.')
    assert r.past == 0


def test_speech_runs_across_sentence_lines():
    """A scene is a sentence per line (scene_layout): a quote spans lines."""
    r = vb.read_tense(PRESENT + '\n"I was there.\nI saw it.\nI knew."\nHe says it.')
    assert r.past == 0


def test_share_takes_only_a_tense():
    with pytest.raises(ValueError):
        vb.TenseReading(1, 1).share('Present')


# --- the review's fixes (#682) ---

def test_anchor_constructor_holds_the_rules():
    with pytest.raises(ValueError, match='empty'):
        vb.Anchor('a.md', '  ')
    with pytest.raises(ValueError, match="'future'"):
        vb.Anchor('a.md', 'Text.', tense='future')


def test_a_header_with_an_unknown_key_is_refused_not_read_as_prose():
    with pytest.raises(ValueError, match='`source:`'):
        vb.parse_anchor('a.md', 'kind: battle\nsource: Iliad 16\n\nHe fell.')


def test_crlf_header_and_bom_template_are_read(project_dir):
    a = vb.parse_anchor('a.md', 'kind: Battle\r\ntense: past\r\n\r\nHe ran.\r\n')
    assert (a.kind, a.tense, a.text) == (('battle',), 'past', 'He ran.')
    with open(os.path.join(vb.get_plugin_dir(), 'templates', vb.BOOK_FILE), 'rb') as f:
        data = f.read()
    _write(os.path.join(project_dir, vb.BOOK_FILE), b'\xef\xbb\xbf' + data.replace(b'\n', b'\r\n'))
    assert vb.is_template(project_dir, vb.BOOK_FILE)
    assert vb.resolve(project_dir).kind == 'template'


def test_a_skipped_anchor_is_carried_on_an_ok_verdict(project_dir):
    _write(os.path.join(project_dir, vb.ANCHORS_DIR, 'bad.md'), 'tense: future\n\nText.')
    _write(os.path.join(project_dir, vb.ANCHORS_DIR, 'nested', 'deep.md'), 'Text.')
    _write(os.path.join(project_dir, vb.ANCHORS_DIR, 'note.txt'), 'Text.')
    v = vb.resolve(project_dir)
    assert v.kind == 'ok' and len(v.skipped) == 3
    warning = vb.skipped_warning(v)
    assert warning.startswith('WARNING: 3 anchor file(s)')
    assert 'bad.md' in warning and 'nested' in warning and 'note.txt' in warning


def test_write_warns_about_a_skipped_anchor(project_dir, capsys):
    from storyforge.cmd_write import _check_reference_docs
    _write(os.path.join(project_dir, vb.ANCHORS_DIR, 'bad.md'), 'kind: x\nkind: y\n\nText.')
    _check_reference_docs(project_dir, 'full', False)
    out = capsys.readouterr()
    assert 'WARNING: 1 anchor file(s)' in out.out + out.err and 'given twice' in out.out + out.err


def test_a_directory_for_book_md_or_a_file_for_anchors_is_unreadable(project_dir):
    os.remove(os.path.join(project_dir, vb.BOOK_FILE))
    os.makedirs(os.path.join(project_dir, vb.BOOK_FILE))
    v = vb.resolve(project_dir)
    assert v.kind == 'unreadable' and 'not a regular file' in v.detail
    os.rmdir(os.path.join(project_dir, vb.BOOK_FILE))
    shutil.rmtree(os.path.join(project_dir, vb.ANCHORS_DIR))
    _write(os.path.join(project_dir, vb.ANCHORS_DIR), 'oops')
    v = vb.resolve(project_dir)
    assert v.kind == 'unreadable' and 'not a folder' in v.detail
    with pytest.raises(ReferenceDocError, match='not a folder'):
        vb.scaffold(project_dir)


def test_an_unreadable_checks_md_never_stops_writing(project_dir):
    _write(os.path.join(project_dir, vb.CHECKS_FILE), b'\xff\xfe')
    assert vb.resolve(project_dir).kind == 'ok'
    with pytest.raises(ReferenceDocError):
        vb.checks_text(project_dir)


def test_the_author_repo_alone_is_a_voice(project_dir, tmp_path, monkeypatch):
    from storyforge import voice_repo
    shutil.rmtree(os.path.join(project_dir, vb.VOICE_DIR))
    monkeypatch.setattr(voice_repo, 'voice_ref', lambda pd: object())
    monkeypatch.setattr(voice_repo, 'author_voice_section', lambda pd: 'THE AUTHOR')
    v = vb.resolve(project_dir)
    assert v.kind == 'ok' and 'THE AUTHOR' in v.text
    _write(os.path.join(project_dir, vb.BOOK_FILE), b'\xff\xfe')
    assert vb.resolve(project_dir).kind == 'unreadable'


SENTINEL = 'CHECKS_SENTINEL_7f3a'


@pytest.fixture
def sentinel(project_dir):
    _write(os.path.join(project_dir, vb.CHECKS_FILE), f'# Checks\n\n1. {SENTINEL}\n')
    return project_dir


@pytest.mark.parametrize('coaching', ['full', 'coach', 'strict'])
@pytest.mark.parametrize('system_context', [False, True])
def test_checks_md_never_reaches_a_drafting_prompt(sentinel, coaching, system_context):
    from storyforge.prompts import build_scene_prompt, build_scene_prompt_from_briefs
    for api_mode in (True, False):
        assert SENTINEL not in build_scene_prompt('act1-sc01', sentinel, coaching,
                                                  api_mode=api_mode,
                                                  system_context=system_context)
    assert SENTINEL not in build_scene_prompt_from_briefs(
        'act1-sc01', sentinel, vb.get_plugin_dir(), coaching, system_context=system_context)


@pytest.mark.parametrize('api_mode', [True, False])
@pytest.mark.parametrize('system_context', [False, True])
def test_checks_md_never_reaches_a_revision_prompt_or_the_shared_context(
        sentinel, api_mode, system_context):
    from storyforge.common import _shared_context_cache, build_shared_context
    from storyforge.prompts_elaborate import _existing_refs
    from storyforge.revision import build_revision_prompt
    assert SENTINEL not in build_revision_prompt('prose', 'Tighten', 'act1-sc01', sentinel,
                                                 api_mode=api_mode,
                                                 system_context=system_context)
    _shared_context_cache.clear()
    try:
        assert SENTINEL not in ''.join(b['text'] for b in build_shared_context(sentinel))
    finally:
        _shared_context_cache.clear()
    assert SENTINEL not in _existing_refs(sentinel) + _existing_refs(sentinel, shared=True)


def test_hone_carries_book_md_only(project_dir, capsys):
    from storyforge.hone import VOICE_EXCERPT_CHARS, voice_excerpt
    text = voice_excerpt(project_dir)
    assert 'Measures before it feels' in text and 'The village was not there' not in text
    _write(os.path.join(project_dir, vb.BOOK_FILE), 'x ' * VOICE_EXCERPT_CHARS)
    assert len(voice_excerpt(project_dir)) == VOICE_EXCERPT_CHARS
    assert 'hone\'s prompts carry the first' in capsys.readouterr().out


def test_the_voice_stage_dry_run_writes_nothing(project_dir, monkeypatch, capsys):
    from storyforge import git
    from storyforge.cmd_elaborate import _run_voice_stage
    commits = []
    monkeypatch.setattr(git, 'commit_and_push', lambda *a, **k: commits.append(a) or True)
    shutil.rmtree(os.path.join(project_dir, vb.VOICE_DIR))
    assert _run_voice_stage(project_dir, dry_run=True) == 0
    assert not os.path.exists(os.path.join(project_dir, vb.VOICE_DIR))
    assert commits == []
    assert 'Would set up reference/voice/book.md' in capsys.readouterr().out


def test_the_voice_stage_fails_when_its_commit_fails(project_dir, monkeypatch, capsys):
    from storyforge import cmd_elaborate, git
    shutil.rmtree(os.path.join(project_dir, vb.VOICE_DIR))
    monkeypatch.setattr(git, 'commit_and_push', lambda *a, **k: False)
    monkeypatch.setattr(git, 'last_commit_error', 'index.lock exists')
    assert cmd_elaborate._run_voice_stage(project_dir, dry_run=False) == 1
    assert 'not committed (index.lock exists)' in capsys.readouterr().out


def test_graphic_novel_elaboration_keeps_its_voice_guide(project_dir, monkeypatch):
    from storyforge import common
    from storyforge.prompts_elaborate import _existing_refs
    _write(os.path.join(project_dir, 'reference', 'voice-guide.md'), '# GN VOICE MARK\n')
    monkeypatch.setattr(common, 'get_medium', lambda pd: 'graphic-novel')
    common._shared_context_cache.clear()
    try:
        text = ''.join(b['text'] for b in common.build_shared_context(project_dir))
    finally:
        common._shared_context_cache.clear()
    assert '=== Voice Guide ===' in text and 'GN VOICE MARK' in text
    assert '=== The Voice ===' not in text
    assert 'GN VOICE MARK' in _existing_refs(project_dir)


# --- extract 5f's anchors ---

def test_an_extracted_anchor_keeps_paragraphs_and_stops_at_a_paragraph():
    from storyforge.extract_describe import anchor_passage, render_anchor
    text = '\n\n'.join(f'Para {i} ' + 'word ' * 400 for i in range(6))
    out = anchor_passage(text, max_words=1000)
    assert out.count('\n\n') == 1 and out.startswith('Para 0') and 'Para 2' not in out
    assert anchor_passage('one ' * 50, max_words=10).endswith('[…]')
    assert anchor_passage('---\nid: x\n---\n\nThe prose.') == 'The prose.'
    a = vb.parse_anchor('a.md', render_anchor('He ran.\n\nHe fell.', 'Hector'))
    assert (a.pov, a.text) == ('Hector', 'He ran.\n\nHe fell.')


# --- where the voice stage sits, and the check after the map (#656) ---

@pytest.mark.parametrize('text, want', [
    (None, 'first'),                                     # no key-decisions.md
    ('# Decisions\n\nnarrator_pov: off\n', 'first'),
    ('voice_stage: later\n', 'later'),
    ('- **`voice_stage`:** `first`\n', 'first'),
    # CR-3/SF-1: the forms real key-decisions files use
    ('**voice_stage**: later\n', 'later'),
    ('- **voice_stage:** later\n', 'later'),
    ('voice_stage: "later"\n', 'later'),
    ("voice_stage: 'later'\n", 'later'),
    ('Voice_Stage: Later\n', 'later'),
    ('* voice_stage: later (structure first, Ben 2026-11-15)\n', 'later'),
    ('- voice_stage: later — structure first\n', 'later'),
    # SF-7: a comment, one line or several, isn't read
    ('<!-- voice_stage: later -->\nvoice_stage: first\n', 'first'),
    ('<!--\nvoice_stage: later\n-->\n', 'first'),
])
def test_the_voice_stage_setting(tmp_path, text, want):
    if text is not None:
        _write(str(tmp_path / 'reference' / 'key-decisions.md'), text)
    assert vb.stage_setting(str(tmp_path)) == (want, '')


@pytest.mark.parametrize('line', [
    'voice_stage: whenever', 'voice_stage:', 'voice stage: later', 'voice_stage later',
    '- **voice_stage**: maybe later'])
def test_a_line_naming_the_key_it_cant_read_is_said(tmp_path, line):
    _write(str(tmp_path / 'reference' / 'key-decisions.md'), f'{line}\n')
    when, problem = vb.stage_setting(str(tmp_path))
    assert when == 'first'
    assert f"can't read {line!r}" in problem and 'The voice stage is first' in problem


def test_an_unreadable_line_doesnt_undo_a_good_one(tmp_path):
    _write(str(tmp_path / 'reference' / 'key-decisions.md'),
           'voice_stage: later\nvoice stage: soon\n')
    when, problem = vb.stage_setting(str(tmp_path))
    assert when == 'later' and "can't read 'voice stage: soon'" in problem


def test_prose_about_the_voice_stage_is_not_a_setting(tmp_path):
    _write(str(tmp_path / 'reference' / 'key-decisions.md'),
           'We found the voice stage useful.\n')
    assert vb.stage_setting(str(tmp_path)) == ('first', '')


def test_the_last_voice_stage_line_wins_and_a_change_is_said(tmp_path):
    # SF-2: key-decisions.md is added to over time
    _write(str(tmp_path / 'reference' / 'key-decisions.md'),
           'voice_stage: later\n\n## Later\n\nvoice_stage: first\n')
    when, problem = vb.stage_setting(str(tmp_path))
    assert when == 'first' and 'disagree' in problem and 'the last one, first' in problem
    _write(str(tmp_path / 'reference' / 'key-decisions.md'),
           'voice_stage: later\nvoice_stage: later\n')
    assert vb.stage_setting(str(tmp_path)) == ('later', '')


def test_an_unreadable_key_decisions_file_is_first_and_said(tmp_path):
    _write(str(tmp_path / 'reference' / 'key-decisions.md'), b'voice_stage: \xff\n')
    when, problem = vb.stage_setting(str(tmp_path))
    assert when == 'first' and "can't be read" in problem


def _map(pd, povs, statuses=None):
    _write(os.path.join(pd, 'reference', 'characters.csv'),
           'id|name|aliases\nlady-ann|Lady Ann Vale|the Widow\nbo-tan|Bo Tan|\n'
           'cy|Cy|\nwill-hart|Will Hart|\nana-reyes|Captain Ana Reyes|\n')
    statuses = statuses or ['mapped'] * len(povs)
    rows = ''.join(f's{i}|{len(povs) - i}|{p}|{st}\n'
                   for i, (p, st) in enumerate(zip(povs, statuses)))
    _write(os.path.join(pd, 'reference', 'scenes.csv'), 'id|seq|pov|status\n' + rows)


def test_pov_gaps_lists_the_povs_book_md_doesnt_name_in_reading_order(tmp_path):
    pd = str(tmp_path)
    _map(pd, ['lady-ann', 'Bo Tan', 'Cy', 'Omniscient narrator', 'Bo Tan', ''])
    # reading order is by seq (reversed here); each POV once
    assert vb.pov_gaps(pd, '') == ['Bo Tan', 'Omniscient narrator', 'Cy', 'lady-ann']
    # an alias, a hyphenated id with spaces in any case, the narrator: named
    assert vb.pov_gaps(pd, 'the Widow keeps her counsel. Bo Tan. The narrator is far.') \
        == ['Cy']
    assert vb.pov_gaps(pd, 'Lady ann; bo tan; Cy; narrator') == []


@pytest.mark.parametrize('notes, pov', [
    # CR-4/SF-6/T-1: a first name alone, or a common word, doesn't name
    ('Will she ever learn?', 'Will Hart'),
    ('The captain gives orders.', 'Captain Ana Reyes'),
    ('Ana watches.', 'Captain Ana Reyes'),
    ('Lady Macbeth.', 'lady-ann'),
    ('Cyril spoke.', 'Cy'),
    # names and aliases are as written: case counts (an id with spaces, any case)
    ('the widow', 'lady-ann'),
    # a narrator only where book.md doesn't say there's none
    ('There is no narrator: every scene is close.', 'narrator'),
    ('Not a narrator in sight.', 'narrator'),
])
def test_pov_gaps_doesnt_count_a_near_miss_as_named(tmp_path, notes, pov):
    pd = str(tmp_path)
    _map(pd, [pov])
    assert vb.pov_gaps(pd, notes) == [pov]


@pytest.mark.parametrize('notes, pov', [
    ('Will Hart is close.', 'Will Hart'),
    ('Captain Ana Reyes, at a distance.', 'Captain Ana Reyes'),
    ('will-hart: close', 'Will Hart'),
    ('No scene is without a narrator; the narrator is the bard.', 'narrator'),
])
def test_pov_gaps_counts_a_full_name_id_or_narrator(tmp_path, notes, pov):
    pd = str(tmp_path)
    _map(pd, [pov])
    assert vb.pov_gaps(pd, notes) == []


def test_pov_gaps_skips_cut_and_merged_scenes_and_reads_book_md(tmp_path):
    pd = str(tmp_path)
    _map(pd, ['Bo Tan', 'Cy'], ['cut', 'mapped'])
    assert vb.pov_gaps(pd, '') == ['Cy']
    _write(os.path.join(pd, 'reference', 'voice', 'book.md'), '# Voice\n\nCy, close.\n')
    assert vb.pov_gaps(pd) == []
    # init's template is no text: every POV is a gap
    shutil.rmtree(os.path.join(pd, 'reference', 'voice'))
    vb.scaffold(pd)
    assert vb.pov_gaps(pd) == ['Cy']


def test_pov_gaps_without_a_map_is_empty(tmp_path):
    assert vb.pov_gaps(str(tmp_path), 'anything') == []


@pytest.mark.parametrize('name', ['characters.csv', 'scenes.csv'])
def test_pov_gaps_on_a_file_it_cant_read_is_a_reference_doc_error(tmp_path, name):
    # SF-5: a bad byte was a traceback
    pd = str(tmp_path)
    _map(pd, ['Cy'])
    _write(os.path.join(pd, 'reference', name), b'id|name\n\xff|x\n')
    with pytest.raises(ReferenceDocError, match=name):
        vb.pov_gaps(pd, 'Cy')
