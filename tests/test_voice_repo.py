"""The author voice repo and the book's `voice:` block (#652, plan B0):
`storyforge.voice_repo`, `storyforge voice init / fingerprint`, the drafting
prompt and `score --voice` reading the book's block. The importer is in
test_voice_import.py."""

import os
import shutil

import pytest

from storyforge import voice_repo as vr
from storyforge import voiceprint as vp

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUSTEN = os.path.join(PLUGIN, 'references', 'voiceprints', 'austen')
MODERN = os.path.join(PLUGIN, 'tests', 'fixtures', 'voiceprint', 'others', 'gatsby', '02.md')


def _yaml(project_dir, block):
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.rstrip('\n') + '\n\n' + block)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _tree(d):
    out = {}
    for root, _, files in os.walk(d):
        for n in files:
            p = os.path.join(root, n)
            with open(p, 'rb') as f:
                out[os.path.relpath(p, d)] = f.read()
    return out


@pytest.fixture
def voice(tmp_path):
    """A small author voice repo with a description, two exemplars and a
    fiction anchor, beside where the book will be."""
    d = tmp_path / 'my-voice'
    vr.init_repo(str(d), 'Test Author')
    _write(str(d / 'description.md'),
           '# The described voice: Test Author\n\n<!-- Written by `storyforge voice accept` '
           '-->\n\n## What the voice does\n\n- Short declaratives, then one long one.\n')
    _write(str(d / 'exemplars' / 'exemplars.csv'),
           'id|job|source|paragraphs|words|why\n'
           'walk-1-2|description|corpus/walk.md|1-2|12|The heron, seen plainly.\n'
           'rain-3-3|quiet|corpus/rain.md|3-3|9|\n')
    _write(str(d / 'exemplars' / 'walk-1-2.md'), 'The heron stood in the shallows. '
                                                 'I decided it was the same heron.\n')
    _write(str(d / 'exemplars' / 'rain-3-3.md'), 'It rained for nine days, and we went out.\n')
    _write(str(d / 'fiction' / 'close-third' / 'opening.md'),
           '# Opening\n\nShe kept the light for eleven years.\n')
    return d


# ============================================================================
# voice.yaml and the corpus index
# ============================================================================

def test_init_makes_the_layout_and_replaces_nothing(tmp_path):
    d = tmp_path / 'ben-voice'
    made = vr.init_repo(str(d), 'Ben Norris')
    assert made == ['voice.yaml', 'corpus/index.csv', 'exemplars/', 'fiction/']
    s = vr.read_settings(str(d))
    assert s == vr.Settings('Ben Norris', ('essay', 'fiction'), 500)
    assert vr.read_index(str(d)) == []
    assert (d / 'exemplars' / '.gitkeep').exists() and (d / 'fiction' / '.gitkeep').exists()
    vr.check_repo(str(d))
    with pytest.raises(vr.VoiceRepoError, match='already there'):
        vr.init_repo(str(d), 'Someone Else')
    assert vr.read_settings(str(d)).author == 'Ben Norris'


def test_init_refuses_inside_a_book(project_dir):
    with pytest.raises(vr.VoiceRepoError, match='is in a book'):
        vr.init_repo(os.path.join(project_dir, 'voice'))
    assert not os.path.exists(os.path.join(project_dir, 'voice'))
    with pytest.raises(vr.VoiceRepoError, match='is a book'):
        vr.check_repo(project_dir)
    os.makedirs(os.path.join(project_dir, 'scenes', 'deeper'), exist_ok=True)
    with pytest.raises(vr.VoiceRepoError, match='is in a book'):
        vr.check_repo(os.path.join(project_dir, 'scenes', 'deeper'))


def test_settings_round_trip_an_author_with_quotes(tmp_path):
    _write(str(tmp_path / 'voice.yaml'), vr.render_settings(vr.Settings('Flannery "F" O\'Connor',
                                                                          ('fiction',), 0)))
    s = vr.read_settings(str(tmp_path))
    assert s.kinds == ('fiction',) and s.min_words == 0 and 'Connor' in s.author


@pytest.mark.parametrize('text, match', [
    ('author: X\ncorpus:\n  - file: corpus/a.md\n', 'corpus/index.csv'),
    ('author: X\ncolour: blue\n', "`colour` isn't a voice.yaml key"),
    ('author: X\nauthor: Y\n', 'given twice'),
    ('kinds:\n  - poetry\n', "kind 'poetry'"),
    ('kinds: [essay]\n', 'as a list'),
    ('kinds:\n', 'lists no kind'),
    ('min_words: lots\n', 'whole number'),
    ('min_words: -1\n', 'negative'),
    ('author X\n', "can't read"),
])
def test_settings_refuse_what_cant_be_used(tmp_path, text, match):
    _write(str(tmp_path / 'voice.yaml'), text)
    with pytest.raises(vr.VoiceRepoError, match=match):
        vr.read_settings(str(tmp_path))


def test_settings_of_a_missing_file(tmp_path):
    with pytest.raises(vr.VoiceRepoError, match='voice init'):
        vr.read_settings(str(tmp_path))


@pytest.mark.parametrize('row, match', [
    ('corpus/a.md|A|2020|essay|x|\ncorpus/a.md|B|2020|essay|y|', 'repeated file'),
    ('notes/a.md|A|2020|essay|x|', "isn't in corpus/"),
    ('corpus/a.md|A|March 2020|essay|x|', 'date'),
    ('corpus/a.md|A|2020|poem|x|', 'kind'),
    ('corpus/a.md|A|2020|essay|x|maybe', 'use'),
    ('corpus/a.md|A|2020|essay|x', '5 cells'),
])
def test_index_refuses_bad_rows(tmp_path, row, match):
    _write(str(tmp_path / 'corpus' / 'index.csv'), '|'.join(vr.INDEX_COLUMNS) + '\n' + row + '\n')
    with pytest.raises(vr.VoiceRepoError, match=match):
        vr.read_index(str(tmp_path))


def test_index_round_trips_a_pipe_in_a_title(tmp_path):
    rows = [vr.IndexRow('corpus/a.md', 'This | That', '2020-01-02', 'essay', 'https://x', '')]
    vr.write_index(str(tmp_path), rows)
    back = vr.read_index(str(tmp_path))
    assert back[0].title == 'This / That' and back[0].date == '2020-01-02'


def test_what_counts(tmp_path):
    vr.init_repo(str(tmp_path))
    long = 'The heron stood in the shallows below the footbridge again. ' * 60
    short = 'A short note about nothing much at all.\n'
    files = {'corpus/essay.md': long, 'corpus/note.md': short, 'corpus/link.md': long,
             'corpus/kept.md': short, 'corpus/held.md': long, 'corpus/out.md': long}
    for rel, text in files.items():
        _write(str(tmp_path / rel), text)
    vr.write_index(str(tmp_path), [
        vr.IndexRow('corpus/essay.md', kind='essay'),
        vr.IndexRow('corpus/note.md', kind='essay'),
        vr.IndexRow('corpus/link.md', kind='link'),
        vr.IndexRow('corpus/kept.md', kind='notes', use='in'),
        vr.IndexRow('corpus/held.md', kind='essay', use='held-out'),
        vr.IndexRow('corpus/out.md', kind='essay', use='out'),
    ])
    pieces, _ = vr.corpus(str(tmp_path))
    assert {p.row.file: p.counts for p in pieces} == {
        'corpus/essay.md': True, 'corpus/note.md': False, 'corpus/link.md': False,
        'corpus/kept.md': True, 'corpus/held.md': False, 'corpus/out.md': False}
    assert list(vr.counted_pieces(str(tmp_path))) == ['corpus/essay.md', 'corpus/kept.md']
    lines = vr.corpus_summary(pieces)
    assert lines[0].startswith('Corpus: 6 piece(s)') and '2 count' in lines[0]
    assert any('1 too short' in ln for ln in lines)
    assert any('1 a link piece' in ln for ln in lines)
    assert any('1 held out' in ln for ln in lines)
    assert lines[-1].startswith('WARNING: the pieces that count hold') and \
        f'{vp.MIN_CORPUS_WORDS:,}' in lines[-1]


def test_a_piece_the_index_names_but_isnt_there(tmp_path):
    vr.init_repo(str(tmp_path))
    vr.write_index(str(tmp_path), [vr.IndexRow('corpus/gone.md')])
    with pytest.raises(vr.VoiceRepoError, match="gone.md, which isn't there"):
        vr.corpus(str(tmp_path))


def test_austen_reference_is_a_voice_repo_in_the_settled_format():
    s = vr.read_settings(AUSTEN)
    assert s.author == 'Jane Austen' and s.kinds == ('fiction',)
    assert list(vr.counted_pieces(AUSTEN)) == ['corpus/pride-and-prejudice.md']


# ============================================================================
# storyforge voice init / fingerprint
# ============================================================================

def test_cmd_init_and_its_refusals(tmp_path, project_dir, capsys):
    from storyforge import cmd_voice
    d = tmp_path / 'v'
    assert cmd_voice.main(['init', '--dir', str(d), '--author', 'A. Writer']) == 0
    assert 'voice import' in capsys.readouterr().out
    assert cmd_voice.main(['init', '--dir', str(d)]) == 1
    assert 'already there' in capsys.readouterr().out
    assert cmd_voice.main(['init', '--dir', os.path.join(project_dir, 'v')]) == 1
    assert 'is in a book' in capsys.readouterr().out


def test_cmd_fingerprint_recomputes_the_austen_reference(tmp_path, capsys):
    """`voice fingerprint` on the reference repo makes exactly its stored
    fingerprint.json: the index's counted pieces are what it was made from."""
    from storyforge import cmd_voice
    d = tmp_path / 'austen'
    shutil.copytree(AUSTEN, d)
    assert cmd_voice.main(['fingerprint', '--dir', str(d)]) == 0
    out = capsys.readouterr().out
    assert 'is current' in out
    assert 'WARNING' not in out          # T2: 122,136 counted words, over the minimum
    os.remove(d / 'fingerprint.json')
    assert cmd_voice.main(['fingerprint', '--dir', str(d)]) == 0
    with open(d / 'fingerprint.json', encoding='utf-8') as a, \
            open(os.path.join(AUSTEN, 'fingerprint.json'), encoding='utf-8') as b:
        assert a.read() == b.read()


def test_cmd_fingerprint_with_nothing_that_counts(tmp_path, capsys):
    from storyforge import cmd_voice
    vr.init_repo(str(tmp_path / 'v'))
    assert cmd_voice.main(['fingerprint', '--dir', str(tmp_path / 'v')]) == 1
    out = capsys.readouterr().out
    assert 'no piece counts' in out and 'WARNING' in out
    assert not (tmp_path / 'v' / 'fingerprint.json').exists()


def test_cmd_fingerprint_says_a_corpus_too_small(tmp_path, capsys):
    from storyforge import cmd_voice
    d = tmp_path / 'v'
    vr.init_repo(str(d))
    _write(str(d / 'corpus' / 'a.md'), 'One short paragraph of prose, far too little.\n')
    vr.write_index(str(d), [vr.IndexRow('corpus/a.md', use='in')])
    assert cmd_voice.main(['fingerprint', '--dir', str(d)]) == 1
    assert 'a fingerprint needs at least' in capsys.readouterr().out


def test_cmd_voice_refuses_a_book(project_dir, capsys):
    from storyforge import cmd_voice
    for action in (['import', 'x'], ['fingerprint'], ['propose', '--dry-run']):
        assert cmd_voice.main(action + ['--dir', project_dir]) == 1
        assert 'is a book' in capsys.readouterr().out


# ============================================================================
# The book's `voice:` block
# ============================================================================

def test_no_block_is_no_voice(project_dir):
    assert vr.voice_ref(project_dir) is None
    assert vr.book_voice(project_dir) is None
    assert vr.require_voice(project_dir) == []
    assert vr.author_voice_section(project_dir) == ''


def test_block_loads_description_exemplars_and_anchor(project_dir, voice):
    rel = os.path.relpath(voice, project_dir)
    _yaml(project_dir, f'voice:\n  author: {rel}   # read in place\n'
                       f'  narrator: fiction/close-third\n')
    v = vr.book_voice(project_dir)
    assert v.ref.author == rel and v.ref.author_dir == str(voice)
    assert v.author == 'Test Author'
    assert 'Short declaratives' in v.description and '<!--' not in v.description
    assert [e.id for e in v.exemplars.exemplars] == ['walk-1-2', 'rain-3-3']
    assert v.anchor == (('fiction/close-third/opening.md',
                         '# Opening\n\nShe kept the light for eleven years.'),)
    assert v.book_notes == ''


def test_author_voice_section_carries_the_voice(project_dir, voice):
    rel = os.path.relpath(voice, project_dir)
    _yaml(project_dir, f'voice:\n  author: {rel}\n  narrator: fiction/close-third\n')
    _write(os.path.join(project_dir, 'reference', 'voice', 'book.md'),
           '# This book\n\nBronze-age vocabulary only.\n')
    text = vr.author_voice_section(project_dir)
    assert text.startswith("## The Author's Voice")
    assert '#### What the voice does' in text            # demoted under the section
    assert '#### Passage 1 (description): The heron, seen plainly.' in text
    assert 'The heron stood in the shallows.' in text
    assert '#### Passage 2 (quiet)\n\nIt rained' in text
    assert 'fiction anchor: fiction/close-third' in text and 'eleven years' in text
    assert 'reference/voice/book.md' in text and 'Bronze-age vocabulary' in text
    assert vr.require_voice(project_dir)[0].startswith('Voice: Test Author')


def test_the_voice_repo_is_never_written(project_dir, voice):
    _yaml(project_dir, f'voice:\n  author: {voice}\n')
    before = _tree(voice)
    vr.author_voice_section(project_dir)
    vr.require_voice(project_dir)
    assert _tree(voice) == before


def test_unlisted_exemplars_are_a_warning(project_dir, voice):
    _write(str(voice / 'exemplars' / 'stray.md'), 'Not in the index.\n')
    _yaml(project_dir, f'voice:\n  author: {voice}\n')
    lines = vr.require_voice(project_dir)
    assert lines[1].startswith('WARNING:') and 'stray.md' in lines[1]


@pytest.mark.parametrize('block, match', [
    ('voice:\n  author: ../nowhere\n', 'is not there'),
    ('voice:\n  narrator: fiction/x\n', 'names no author'),
    ('voice:\n  author: {v}\n  colour: blue\n', '`colour`'),
    ('voice:\n  author: {v}\n  author: {v}\n', 'twice'),
    ('voice:\n  author: ~\n', 'not a path'),
    ('voice: {v}\n', 'one-line value'),
    ('project2:\n  voice:\n    author: {v}\n', 'indented'),
    ('voice:\n  author: {v}\n  narrator: fiction/missing\n', 'not in the author voice repo'),
    ('voice:\n  author: {v}\n  narrator: ../../elsewhere\n', 'outside the author voice repo'),
    # T1: the corpus (drafts among it) or the repo itself is never "the narrator"
    ('voice:\n  author: {v}\n  narrator: corpus\n', "isn't in the repo's fiction/"),
    ('voice:\n  author: {v}\n  narrator: .\n', "isn't in the repo's fiction/"),
    ('voice:\n  author: {v}\n  narrator: description.md\n', "isn't in the repo's fiction/"),
    ('voice:\n  author: {v}\n  narrator: fiction\n', "isn't in the repo's fiction/"),
])
def test_block_refuses_what_cant_be_used(project_dir, voice, block, match):
    _yaml(project_dir, block.format(v=voice))
    with pytest.raises(vr.VoiceError, match=match):
        vr.book_voice(project_dir)


def test_a_repo_without_a_description_or_exemplars_stops(project_dir, voice):
    _yaml(project_dir, f'voice:\n  author: {voice}\n')
    os.remove(voice / 'description.md')
    with pytest.raises(vr.VoiceError, match='voice accept'):
        vr.book_voice(project_dir)
    _write(str(voice / 'description.md'), '<!-- only a comment -->\n')
    with pytest.raises(vr.VoiceError, match='is empty'):
        vr.book_voice(project_dir)


def test_an_empty_narrator_folder_stops(project_dir, voice):
    os.makedirs(voice / 'fiction' / 'distant')
    _yaml(project_dir, f'voice:\n  author: {voice}\n  narrator: fiction/distant\n')
    with pytest.raises(vr.VoiceError, match='holds no .md file'):
        vr.book_voice(project_dir)


def test_the_author_must_be_a_voice_repo(project_dir, tmp_path):
    other = tmp_path / 'not-a-voice'
    other.mkdir()
    _yaml(project_dir, f'voice:\n  author: {other}\n')
    with pytest.raises(vr.VoiceError, match='no voice.yaml'):
        vr.book_voice(project_dir)


def test_austen_reference_as_a_books_voice(project_dir):
    """The fixture voice repo the plan names: a book pointing at the Austen
    reference loads its description and its exemplars."""
    _yaml(project_dir, f'voice:\n  author: {os.path.relpath(AUSTEN, project_dir)}\n')
    v = vr.book_voice(project_dir)
    assert v.author == 'Jane Austen' and len(v.exemplars.exemplars) >= 20
    assert 'Never uses contractions in narration' in vr.author_voice_section(project_dir)


def test_a_bad_block_stops_the_dispatcher_plainly(project_dir, capsys):
    from storyforge import __main__ as dispatcher

    class Command:
        @staticmethod
        def main(argv):
            vr.book_voice(project_dir)
    _yaml(project_dir, 'voice:\n  author: ../nowhere\n')
    with pytest.raises(SystemExit) as exc:
        dispatcher._dispatch(Command)
    assert exc.value.code == 1
    assert capsys.readouterr().err.startswith('ERROR: voice.author: ../nowhere')


def test_write_stops_on_a_bad_block_before_anything_else(project_dir, monkeypatch):
    from storyforge import cmd_write
    monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
    _yaml(project_dir, 'voice:\n  author: ../nowhere\n')
    with pytest.raises(vr.VoiceError, match='nowhere is not there'):
        cmd_write.main(['--dry-run'])


# ============================================================================
# The drafting prompt
# ============================================================================

def _briefs_prompt(project_dir, **kw):
    from storyforge.common import get_plugin_dir
    from storyforge.prompts import build_scene_prompt_from_briefs
    return build_scene_prompt_from_briefs('act1-sc01', project_dir, get_plugin_dir(), **kw)


@pytest.mark.parametrize('coaching', ['full', 'coach', 'strict'])
def test_drafting_prompts_without_a_block_are_unchanged(project_dir, monkeypatch, coaching):
    """A book without `voice:` renders no section: whenever the builders ask
    for it, it is '', and no heading reaches either prompt. That the prompt
    is byte for byte what it was before #652 isn't shown here (both sides
    would be built by this branch's code): the eval replay shows it, since
    a recording's key hashes the whole prompt and a changed drafting prompt
    would miss its cassette (CR-8/T8)."""
    from storyforge import prompts
    calls = []
    real = vr.author_voice_section
    monkeypatch.setattr(vr, 'author_voice_section', lambda d: calls.append(d) or real(d))
    plain = _briefs_prompt(project_dir, coaching_level=coaching)
    old = prompts.build_scene_prompt('act1-sc01', project_dir, coaching, api_mode=True)
    assert "Author's Voice" not in plain and "Author's Voice" not in old
    assert all(real(d) == '' for d in calls)


@pytest.mark.parametrize('system_context', [False, True])
def test_briefs_prompt_carries_the_voice_and_nothing_else_changes(project_dir, voice,
                                                                  system_context):
    plain = _briefs_prompt(project_dir, system_context=system_context)
    _yaml(project_dir, f'voice:\n  author: {voice}\n  narrator: fiction/close-third\n')
    section = vr.author_voice_section(project_dir)
    voiced = _briefs_prompt(project_dir, system_context=system_context)
    assert section in voiced
    assert voiced.replace(section, '', 1) == plain
    # before the brief, the passages the writer holds to
    assert voiced.index('The heron stood') < voiced.index('## Scene Brief: act1-sc01')


def test_book_exemplars_follow_the_authors_voice(project_dir, voice):
    _write(os.path.join(project_dir, 'reference', 'prose-exemplars.md'),
           'The book\'s own exemplar passage.\n')
    _yaml(project_dir, f'voice:\n  author: {voice}\n')
    voiced = _briefs_prompt(project_dir)
    assert voiced.index('The heron stood') < voiced.index("The book's own exemplar passage")


def test_coach_and_strict_prompts_leave_the_voice_out(project_dir, voice):
    from storyforge.prompts import build_scene_prompt
    _yaml(project_dir, f'voice:\n  author: {voice}\n')
    for level in ('coach', 'strict'):
        assert "Author's Voice" not in _briefs_prompt(project_dir, coaching_level=level)
        # T8: the older builder too
        assert "Author's Voice" not in build_scene_prompt('act1-sc01', project_dir, level,
                                                          api_mode=True)


def test_older_drafting_prompt_carries_the_voice(project_dir, voice):
    from storyforge.prompts import build_scene_prompt
    plain = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    _yaml(project_dir, f'voice:\n  author: {voice}\n')
    voiced = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    section = vr.author_voice_section(project_dir)
    assert voiced.replace('\n\n' + section, '', 1) == plain


# ============================================================================
# score --voice reads the book's block
# ============================================================================

def test_score_voice_reads_the_books_block(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    with open(MODERN, encoding='utf-8') as f:
        prose = f.read()
    _write(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), prose)
    _yaml(project_dir, f'voice:\n  author: {os.path.relpath(AUSTEN, project_dir)}\n')
    cmd_score.main(['--voice', '--scenes', 'act1-sc01'])
    out = capsys.readouterr().out
    assert "Jane Austen's voice repo" in out and 'Distance: ' in out


def test_score_voice_without_a_block_or_flag_says_how(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice'])
    assert e.value.code == 1
    assert 'a `voice:` block' in capsys.readouterr().out


def test_score_voice_with_a_bad_block(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _yaml(project_dir, 'voice:\n  author: ../nowhere\n')
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice'])
    assert e.value.code == 1
    assert 'nowhere is not there' in capsys.readouterr().out


def test_score_voice_flags_win_over_the_block(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _yaml(project_dir, 'voice:\n  author: ../nowhere\n')   # never read
    with open(MODERN, encoding='utf-8') as f:
        _write(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), f.read())
    cmd_score.main(['--voice', '--fingerprint', os.path.join(AUSTEN, 'fingerprint.json'),
                    '--scenes', 'act1-sc01'])
    assert 'Distance: ' in capsys.readouterr().out


# ============================================================================
# Review fixes (#669)
# ============================================================================

def test_a_narrator_can_be_one_file_under_fiction(project_dir, voice):
    _yaml(project_dir, f'voice:\n  author: {voice}\n  narrator: fiction/close-third/opening.md\n')
    assert vr.book_voice(project_dir).anchor[0][0] == 'fiction/close-third/opening.md'


def test_a_voice_repo_inside_the_book_is_refused(project_dir, voice):
    """TD-4: `write` and `voice import` agree: a voice repo inside a book
    isn't one (the corpus would be committed with the book)."""
    inside = os.path.join(project_dir, 'voice')
    shutil.copytree(voice, inside)
    _yaml(project_dir, 'voice:\n  author: ./voice\n')
    with pytest.raises(vr.VoiceError, match='is in a book'):
        vr.book_voice(project_dir)


def test_every_voice_command_refuses_the_old_corpus_list(tmp_path):
    """CR-5: voice.yaml has one reader, so `voice propose/judge/accept` and
    `score --voice-repo` refuse the provisional `corpus:` list too."""
    from storyforge import voiceprint_meter as meter
    from storyforge import voiceprint_proposals as vpp
    d = tmp_path / 'old'
    shutil.copytree(AUSTEN, d)
    with open(d / 'voice.yaml', 'a', encoding='utf-8') as f:
        f.write('corpus:\n  - file: corpus/emma.md\n')
    with pytest.raises(vpp.ProposalError, match='lists no corpus'):
        vpp.check_voice_dir(str(d))
    with pytest.raises(vpp.ProposalError, match='lists no corpus'):
        vpp.load_voice(str(d))
    with pytest.raises(meter.MeterError, match='lists no corpus'):
        meter.load_source(voice_repo=str(d))


def _flip_use(d, file, use):
    rows = [vr.IndexRow(r.file, r.title, r.date, r.kind, r.source, use if r.file == file else r.use)
            for r in vr.read_index(str(d))]
    vr.write_index(str(d), rows)


def test_a_fingerprint_older_than_the_index_is_refused(tmp_path):
    """TD-3: a piece held out (or newly counted) since the fingerprint was
    made stops `voice propose` and `score --voice` until it's made again."""
    from storyforge import cmd_voice
    from storyforge import voiceprint_meter as meter
    from storyforge import voiceprint_proposals as vpp
    d = tmp_path / 'austen'
    shutil.copytree(AUSTEN, d)
    vpp.load_voice(str(d))                                  # current: fine
    counted = list(vr.counted_pieces(str(d)))
    _flip_use(d, counted[0], 'held-out')
    with pytest.raises(vpp.ProposalError, match=f'doesn.t count now: {counted[0]}'):
        vpp.load_voice(str(d))
    with pytest.raises(meter.MeterError, match='storyforge voice fingerprint'):
        meter.load_source(voice_repo=str(d))
    _flip_use(d, counted[0], '')
    held = next(r.file for r in vr.read_index(str(d)) if r.use == 'held-out')
    _flip_use(d, held, 'in')
    with pytest.raises(vpp.ProposalError, match=f'counts now but isn.t in it: {held}'):
        vpp.load_voice(str(d))
    assert cmd_voice.main(['fingerprint', '--dir', str(d)]) == 0
    vpp.load_voice(str(d))


@pytest.mark.parametrize('date, ok', [
    ('2019-02-28', True), ('2020-02-29', True), ('2019', True), ('2019-12', True), ('', False),
    ('2019-13-01', False), ('2019-02-30', False), ('2019-00', False), ('2019-13-99', False),
])
def test_valid_dates(date, ok):
    assert vr.valid_date(date) is ok


def test_index_refuses_an_impossible_date_and_write_index_refuses_what_read_would(tmp_path):
    """TD-6: a date that matched the pattern but isn't a date is refused on
    read; write_index refuses any row read_index would, writing nothing."""
    from storyforge import voice_import as vi
    d = tmp_path / 'v'
    vr.init_repo(str(d))
    _write(str(d / 'corpus' / 'index.csv'),
           'file|title|date|kind|source|use\ncorpus/a.md|A|2019-13-99|essay||\n')
    with pytest.raises(vr.VoiceRepoError, match="date '2019-13-99'"):
        vr.read_index(str(d))
    vr.init_repo(str(tmp_path / 'w'))
    for bad, match in ((vr.IndexRow('corpus/a.md', date='2019-02-30'), 'date'),
                       (vr.IndexRow('corpus/a.md', kind='poem'), 'kind'),
                       (vr.IndexRow('elsewhere/a.md'), "isn't in corpus/"),
                       (vr.IndexRow(''), 'blank')):
        with pytest.raises(vr.VoiceRepoError, match=match):
            vr.write_index(str(tmp_path / 'w'), [bad])
        assert vr.read_index(str(tmp_path / 'w')) == []
    with pytest.raises(vr.VoiceRepoError, match='repeated'):
        vr.write_index(str(tmp_path / 'w'), [vr.IndexRow('corpus/a.md'), vr.IndexRow('corpus/a.md')])
    assert vi._norm_date('2019-13-99') == '' and vi._date_from_name('2019-02-30-x.md') == ''


def test_the_minimum_corpus_warning_sums_counted_words_only():
    """T2: quiet at MIN_CORPUS_WORDS, a WARNING one word under, and a large
    held-out piece doesn't lift the counted words over it."""
    from storyforge.voiceprint import MIN_CORPUS_WORDS

    def piece(words, counts=True, why=''):
        return vr.CorpusPiece(vr.IndexRow(f'corpus/{words}-{counts}.md'), words, counts, why)
    at = vr.corpus_summary([piece(MIN_CORPUS_WORDS - 100), piece(100)])
    assert not any(l.startswith('WARNING') for l in at)
    under = vr.corpus_summary([piece(MIN_CORPUS_WORDS - 1)])
    assert under[-1].startswith('WARNING')
    held = vr.corpus_summary([piece(1000), piece(MIN_CORPUS_WORDS * 2, False, 'held out')])
    assert held[-1].startswith('WARNING: the pieces that count hold 1,000 words')
    assert '  not counted: 1 held out' in held
