"""`storyforge bibles convert` (#702): an essay into rows by one model call,
held to the import's rules, written for review or imported; and the
`bibles-convert` eval suite's set, scoring and replay. The API is faked at
`api._live_request`, so the cassette path is the real one."""

import json
import os
import shutil
import sys

import pytest

from conftest import PLUGIN_DIR
from storyforge import bibles, bibles_convert as bc, ledger

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402

SET = PLUGIN_DIR / 'evals' / 'fixtures' / 'bibles-convert'


def _ref(project_dir, *parts):
    return os.path.join(project_dir, 'reference', *parts)


def _reply(data, stop='end_turn'):
    return {'id': 'msg', 'type': 'message', 'role': 'assistant', 'model': 'claude-sonnet-5-5',
            'stop_reason': stop, 'content': [{'type': 'text', 'text': json.dumps(data)}],
            'usage': {'input_tokens': 2000, 'output_tokens': 500}}


#: A reply for test-project's character bible: one of each problem
REPLY = {
    'facts': [
        {'type': 'trait', 'subject': 'Dorren Hayle', 'statement': 'Head cartographer of the office',
         'known_by': '', 'category': 'role'},
        {'type': 'relationship', 'subject': 'dorren-hayle',
         'statement': 'Dorren trained Tessa Merrin', 'known_by': 'pell', 'category': 'mentor'},
        {'type': 'knowledge', 'subject': 'kael-maren', 'statement': 'Kael hid the old survey',
         'known_by': 'Kael', 'category': 'secret'},
        {'type': 'trait', 'subject': 'pell', 'statement': 'Pell keeps a secret',
         'known_by': '', 'category': 'secret'},
        {'type': 'trait', 'subject': 'pell', 'statement': 'Reads a | b', 'known_by': '',
         'category': 'x'},
        {'type': 'trait', 'subject': 'dorren-hayle', 'statement': 'head cartographer of the office.',
         'known_by': '', 'category': 'role'},
        {'type': 'trait', 'subject': 'pell', 'statement': '', 'known_by': '', 'category': ''},
        {'type': 'trait', 'subject': 'pell', 'statement': 'Speaks in short bursts',
         'known_by': '', 'category': 'Voice'},
    ],
    'voices': [
        {'character': 'dorren-hayle', 'line': 'A line the essay never quotes, made up whole.'},
        {'character': 'nobody', 'line': 'Maps'},
    ],
    'notes': ['- The office smells of ink.', ''],
}


@pytest.fixture
def fake_api(monkeypatch):
    from storyforge import api
    calls = []

    def install(reply, stop='end_turn'):
        def live(path, body, method, timeout):
            calls.append(body)
            return _reply(reply, stop)
        monkeypatch.setattr(api, '_live_request', live)
        return calls
    return install


@pytest.fixture
def mock_git(monkeypatch):
    import storyforge.git as git
    monkeypatch.setattr(git, 'ensure_on_branch', lambda *a, **k: None)
    monkeypatch.setattr(git, 'commit_and_push', lambda *a, **k: True)


class TestParse:
    def _parse(self, project_dir, reply=REPLY, name='character-bible.md'):
        essay = bc.essay_text(project_dir, name)
        return bc.parse_reply(json.dumps(reply), name, essay,
                              bc._registry(project_dir, 'characters.csv'),
                              bc._registry(project_dir, 'locations.csv'))

    def test_rows_keep_the_import_rules(self, project_dir):
        conv = self._parse(project_dir)
        statements = [f['statement'] for f in conv.facts]
        assert statements == ['Head cartographer of the office', 'Dorren trained Tessa Merrin',
                              'Kael hid the old survey']
        # a name becomes its id; known_by is a knowledge fact's alone
        assert conv.facts[0]['subject'] == 'dorren-hayle'
        assert conv.facts[1]['known_by'] == ''
        assert conv.facts[2]['known_by'] == 'kael-maren'
        left = '\n'.join(conv.left_out)
        assert "category 'secret' on a trait fact" in left
        assert 'a `|` in a field' in left and 'given twice' in left and 'no statement' in left
        assert 'a description of how someone speaks' in left   # a voice is lines

    def test_a_voice_line_must_be_the_essays_words(self, project_dir):
        """#702: a line the essay doesn't quote would be the model's."""
        conv = self._parse(project_dir)
        assert conv.voices == []
        assert any('not in the essay as written' in x for x in conv.left_out)
        assert any("'nobody' is no character" in x for x in conv.left_out)

    def test_a_quoted_line_is_kept(self, project_dir):
        # curly quotes and a line break in the essay; straight in the reply
        with open(_ref(project_dir, 'character-bible.md'), 'a', encoding='utf-8') as f:
            f.write('\nShe says: \u201cThe map isn\u2019t\nwrong. The land is.\u201d\n')
        line = "The map isn't wrong. The land is."
        conv = self._parse(project_dir, {'facts': [], 'notes': [],
                                         'voices': [{'character': 'Dorren', 'line': line}]})
        assert conv.voices == [('dorren-hayle', line)]

    def test_notes_are_terse_lines(self, project_dir):
        conv = self._parse(project_dir)
        assert conv.notes == ['The office smells of ink.']
        assert any('note 2: empty' in x for x in conv.left_out)

    def test_a_reply_that_isnt_the_object_is_refused(self, project_dir):
        with pytest.raises(bc.ConvertError, match="isn't JSON"):
            bc.parse_reply('nope', 'character-bible.md', '', [], [])
        with pytest.raises(bc.ConvertError, match='facts, voices and notes'):
            bc.parse_reply('{"facts": []}', 'character-bible.md', '', [], [])


class TestEssay:
    def test_only_an_essay_in_reference_converts(self, project_dir, facts_project_dir):
        with pytest.raises(bc.ConvertError, match='not a bible essay'):
            bc.essay_text(project_dir, 'notes.md')
        with pytest.raises(bc.ConvertError, match='retired'):
            bc.essay_text(facts_project_dir, 'character-bible.md')
        with pytest.raises(bc.ConvertError, match='not there'):
            bc.essay_text(project_dir, 'world-bible.md')

    def test_a_graphic_novel_keeps_its_essays(self, project_dir_gn):
        with pytest.raises(bc.ConvertError, match='graphic novel'):
            bc.essay_text(project_dir_gn, 'character-bible.md')


class TestCommand:
    def test_writes_for_review_and_imports_nothing(self, project_dir, monkeypatch, fake_api,
                                                   capsys):
        from storyforge import cmd_bibles
        calls = fake_api(REPLY)
        before = open(ledger.ledger_path(project_dir), encoding='utf-8').read()
        monkeypatch.chdir(project_dir)
        cmd_bibles.main(['convert', 'character-bible.md'])
        assert len(calls) == 1 and calls[0]['output_config']
        paths = bc.review_paths(project_dir, 'character-bible.md')
        with open(paths['facts'], encoding='utf-8') as f:
            assert f.readline().strip() == '|'.join(bc.FACT_COLUMNS)
        assert bibles.read_import(paths['facts'])   # what import reads
        assert not os.path.exists(paths['voices'])  # every line was left out
        assert os.path.isfile(paths['left_out'])
        assert open(ledger.ledger_path(project_dir), encoding='utf-8').read() == before
        out = capsys.readouterr()
        text = out.out + out.err
        assert 'left out:' in text and '--essay character-bible.md' in text

    def test_import_makes_them_the_essays_conversion(self, project_dir, monkeypatch, fake_api,
                                                     mock_git):
        from storyforge import cmd_bibles
        fake_api(REPLY)
        monkeypatch.chdir(project_dir)
        cmd_bibles.main(['convert', 'character-bible.md', '--import', '--no-commit'])
        rows = [r for r in ledger.load(project_dir)
                if r['introduced_by'] == bibles.essay_writer('character-bible.md')]
        assert len(rows) == 3
        assert 'The office smells of ink.' in bibles.notes_text(project_dir)

    def test_a_dry_run_makes_no_call(self, project_dir, monkeypatch, capsys):
        from storyforge import api, cmd_bibles
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        monkeypatch.chdir(project_dir)
        cmd_bibles.main(['convert', 'character-bible.md', '--dry-run'])
        out = capsys.readouterr()
        assert 'one call, about $' in out.out + out.err
        assert not os.path.exists(bc.review_paths(project_dir, 'character-bible.md')['facts'])

    def test_over_the_threshold_sends_nothing(self, project_dir, monkeypatch):
        from storyforge import api, cmd_bibles
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '0')
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            cmd_bibles.main(['convert', 'character-bible.md'])

    def test_a_cut_off_reply_writes_nothing(self, project_dir, monkeypatch, fake_api):
        from storyforge import cmd_bibles
        fake_api(REPLY, stop='max_tokens')
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            cmd_bibles.main(['convert', 'character-bible.md'])
        assert not os.path.exists(bc.review_paths(project_dir, 'character-bible.md')['facts'])

    def test_an_older_review_file_is_removed(self, project_dir):
        conv = bc.Conversion('world-bible.md', voices=[])
        paths = bc.review_paths(project_dir, 'world-bible.md')
        os.makedirs(os.path.dirname(paths['voices']), exist_ok=True)
        open(paths['voices'], 'w').write('character|line\nx|old\n')
        conv.facts = [{'type': 'world', 'subject': '', 'statement': 'Rain', 'known_by': '',
                       'category': 'rule'}]
        written = bc.write_review(project_dir, conv)
        assert set(written) == {'facts'} and not os.path.exists(paths['voices'])


# ---------------------------------------------------------------------------
# The eval suite
# ---------------------------------------------------------------------------

def _suite():
    return next(s for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))
                if s.name == 'bibles-convert')


def _module():
    return _suite().run.__globals__


def _perfect(labels):
    """A conversion that states every labelled fact as its label wants, keeps
    every quoted line and note, and no interpretation."""
    out = {}
    for name, essay in labels['essays'].items():
        conv = bc.Conversion(name)
        for f in essay['facts']:
            words = ' '.join(g.split('|')[0] for g in f['all'])
            subject = f.get('subject') or ''
            subject = subject[-1] if isinstance(subject, list) else subject
            conv.facts.append({'type': f['types'][0], 'subject': subject,
                               'statement': words + ('?' if f.get('open') else ''),
                               'known_by': '',
                               'category': 'secret' if f.get('secret') else 'x'})
        conv.voices = [(v['character'], v['line']) for v in essay['voices']]
        conv.notes = [n['any'][0] for n in essay['notes']]
        out[name] = conv
    return out


class TestSuite:
    def test_the_set_is_sound(self):
        mod = _module()
        assert mod['validate'](mod['load_labels']()) == []

    def test_the_set_is_synthetic_and_names_no_real_book(self):
        labels = json.loads((SET / 'labels.json').read_text())
        assert 'Salt Ledger' in labels['about'] and 'no real book' in labels['about']

    def test_a_perfect_conversion_scores_full(self):
        mod = _module()
        labels = mod['load_labels']()
        m = mod['score'](labels, _perfect(labels))['metrics']
        assert m['fact_recall'] == m['type_accuracy'] == m['subject_accuracy'] == 1.0
        assert m['voice_recall'] == m['note_recall'] == 1.0
        assert m['secrets_kept'] == m['secrets_labelled'] == 2
        assert m['open_kept'] == m['open_labelled'] == 2
        assert m['interpretation_rows'] == m['description_as_voice'] == 0
        assert 'every measure' in mod['trust_notes'](m)[0]

    def test_interpretation_and_descriptions_are_counted(self):
        mod = _module()
        labels = mod['load_labels']()
        convs = _perfect(labels)
        convs['character-bible.md'].facts.append(
            {'type': 'trait', 'subject': 'teodor-brack', 'statement': 'A mirror of Mara',
             'known_by': '', 'category': 'x'})
        convs['character-bible.md'].voices.append(
            ('lise-anker', 'Her speech is low and careful, all questions.'))
        convs['character-bible.md'].left_out.append('voice 9 (x): not in the essay as written, '
                                                    'so not the author\'s line')
        convs['character-bible.md'].notes.append('Brack is a mirror of Mara')
        convs['character-bible.md'].facts.append(
            {'type': 'trait', 'subject': 'ivo-voss', 'statement': 'Talks fast when cornered',
             'known_by': '', 'category': 'voice'})
        m = mod['score'](labels, convs)['metrics']
        assert (m['interpretation_rows'], m['description_as_voice'], m['invented_lines']) \
            == (1, 1, 1)
        # interpretation in a note leaks too; a description of speech is no fact
        assert m['interpretation_notes'] == 1 and m['speech_descriptions'] == 1
        assert 'below the trust bar' in mod['trust_notes'](m)[0]

    def test_a_wrong_type_or_subject_is_scored(self):
        mod = _module()
        labels = mod['load_labels']()
        convs = _perfect(labels)
        row = next(r for r in convs['character-bible.md'].facts if 'scar' in r['statement'])
        row.update(type='world', subject='ivo-voss')
        result = mod['score'](labels, convs)
        assert result['metrics']['type_accuracy'] < 1 and result['metrics']['subject_accuracy'] < 1
        assert any(w.startswith('c03') for w in result['wrong'])

    def test_unrecorded_is_unavailable_not_an_error(self, tmp_path, monkeypatch):
        from storyforge import api
        suite = _suite()   # discover loads the module afresh: patch this one
        mod = suite.run.__globals__
        monkeypatch.setitem(mod, 'FLOORS', dict.fromkeys(mod['FLOORS']))
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        result = harness.run_suite(suite, 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'stale' and 'not recorded yet' in result['stale']

    def test_the_recording_replays_and_passes(self, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        result = harness.run_suite(_suite(), 'replay',
                                   str(PLUGIN_DIR / 'evals' / 'fixtures' / 'cassettes'))
        assert result['status'] == 'pass', result.get('error') or result['notes']

    def test_records_then_replays_free(self, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
        labels = _module()['load_labels']()
        perfect = _perfect(labels)
        calls = []

        def live(path, body, method, timeout):
            prompt = body['messages'][0]['content']
            name = next(n for n in labels['essays'] if f'(reference/{n})' in prompt)
            calls.append(name)
            conv = perfect[name]
            return _reply({'facts': conv.facts,
                           'voices': [{'character': c, 'line': l} for c, l in conv.voices],
                           'notes': conv.notes})
        monkeypatch.setattr(api, '_live_request', live)
        result = harness.run_suite(_suite(), 'record', str(tmp_path / 'c'))
        assert result['error'] is None, result['error']
        assert sorted(calls) == sorted(labels['essays'])
        assert result['metrics']['fact_recall'] == 1.0
        monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
        replayed = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert replayed['metrics'] == result['metrics']
