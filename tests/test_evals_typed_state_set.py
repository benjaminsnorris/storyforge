"""The typed-state set (#744): its store, replay, matching and scoring, its
builder (report A's tables, a book repo's scene commits), and the suite end
to end, on a small set built here from the test project (the real set is
private prose and never enters this repo). Nothing calls a model: the
extraction is answered from the saved typed state."""

import json
import os
import subprocess
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402
import typed_state_set as tss  # noqa: E402
from typed_state_set import build  # noqa: E402

from storyforge import typed_state  # noqa: E402
from storyforge.typed_state import Record  # noqa: E402

SUITE_FILE = PLUGIN_DIR / 'evals' / 'suites' / 'typed_state_set.py'
REPORT_A = PLUGIN_DIR / 'docs' / 'plans' / '2026-11-26-checker-review' / 'A-log-census.md'

SCENE, PREV = 'act1-sc02', 'act1-sc01'
PROSE_1 = 'Pell slipped on the ice and lay dead at the foot of the stair.'
PROSE_2 = 'Dorren walked to the study. Pell met him there and spoke of the map.'


def _write(project_dir, scene, prose):
    with open(os.path.join(project_dir, 'scenes', f'{scene}.md'), 'w', encoding='utf-8') as f:
        f.write(prose)


def _book(project_dir):
    """Pell dies in PREV and is present in SCENE: one life finding."""
    _write(project_dir, PREV, PROSE_1)
    typed_state.write_state(project_dir, PREV, PROSE_1, [
        Record('alive', 'Pell', value='dead', quote='lay dead at the foot of the stair')])
    _write(project_dir, SCENE, PROSE_2)
    typed_state.write_state(project_dir, SCENE, PROSE_2, [
        Record('at', 'Pell', 'the study', quote='Pell met him there'),
        Record('at', 'Dorren', 'the study', quote='Dorren walked to the study')],
        model='claude-haiku-5-5')


def _files(project_dir):
    out = {}
    for root, _dirs, names in os.walk(project_dir):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), project_dir).replace(os.sep, '/')
            if build.kept(rel):
                out[rel] = os.path.join(root, n)
    return out


def _label(lid, verdict='false', check='life', quote='Pell met him there', rounds=('.',),
           scene=SCENE):
    return {'id': lid, 'scene': scene, 'rounds': list(rounds), 'check': check,
            'verdict': verdict, 'quote': quote, 'reason': 'invented'}


def _make_set(root, project_dir, labels=None):
    path = os.path.join(root, tss.SET_NAME)
    files = {rel: tss.put_blob(path, open(src, 'rb').read())
             for rel, src in _files(project_dir).items()}
    data = {'format': tss.FORMAT, 'book': 'tale', 'built_from': {},
            'runs': [{'id': f'tale/{SCENE}/.', 'scene': SCENE, 'round': '.',
                      'commit': 'abc1234', 'files': files}],
            'labels': labels if labels is not None else [
                _label('Q1'), _label('Q2', check='possession', rounds=('recheck',))],
            'not_replayable': [{'scene': SCENE, 'round': 'recheck', 'why': 'invented'}]}
    with open(os.path.join(path, tss.SET_FILE), 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return path, data


@pytest.fixture
def private_set(project_dir, tmp_path, monkeypatch):
    _book(project_dir)
    root = tmp_path / 'private'
    path, data = _make_set(str(root), project_dir)
    monkeypatch.setenv(tss.PRIVATE_ENV, str(root))
    return path, data


def _suite():
    return next(s for s in harness.discover(str(SUITE_FILE.parent))
                if s.name == 'typed-state-set')


# ============================================================================
# The set
# ============================================================================

class TestSet:
    def test_missing_set_says_where_to_put_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv(tss.PRIVATE_ENV, str(tmp_path))
        with pytest.raises(tss.SetMissing, match='storyforge-evals'):
            tss.set_dir()
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'stale' and result['unavailable']

    def test_blobs_are_stored_once_and_checked_on_the_way_out(self, tmp_path):
        a = tss.put_blob(str(tmp_path), b'words')
        assert tss.put_blob(str(tmp_path), b'words') == a
        run = {'id': 'r', 'files': {'scenes/x.md': a}}
        tss.materialize(str(tmp_path), run, str(tmp_path / 'out'))
        assert (tmp_path / 'out' / 'scenes' / 'x.md').read_bytes() == b'words'
        import gzip
        with open(tss.blob_path(str(tmp_path), a), 'wb') as f:
            f.write(gzip.compress(b'other'))
        with pytest.raises(ValueError, match='not its bytes'):
            tss.materialize(str(tmp_path), run, str(tmp_path / 'again'))

    def test_a_path_out_of_the_project_is_refused(self, tmp_path):
        a = tss.put_blob(str(tmp_path), b'x')
        with pytest.raises(ValueError, match='leaves the project'):
            tss.materialize(str(tmp_path), {'id': 'r', 'files': {'../evil': a}},
                            str(tmp_path / 'out'))

    def test_validate_names_ids_never_quotes(self, private_set):
        _path, data = private_set
        assert tss.validate(data) == []
        bad = dict(data, labels=[_label('Q9', verdict='maybe', check='smell'), _label('Q9')])
        problems = tss.validate(bad)
        assert any("verdict 'maybe'" in p for p in problems)
        assert any("check 'smell'" in p for p in problems)
        assert any("label id 'Q9' repeated" in p for p in problems)
        assert not any('Pell met him' in p for p in problems)


# ============================================================================
# Replay and scoring
# ============================================================================

class TestReplay:
    def test_the_saved_state_answers_the_extraction(self, private_set, tmp_path, monkeypatch):
        from storyforge import api
        monkeypatch.setattr(api, '_api_request', lambda *a, **k: pytest.fail('called the API'))
        path, data = private_set
        out = tss.replay_run(path, data['runs'][0], str(tmp_path / 'run'))
        assert [(f['check'], f['quote']) for f in out['findings']] == [
            ('life', 'Pell met him there')]
        assert typed_state._call.__name__ == '_call'     # put back

    def test_state_of_other_prose_is_an_error_naming_its_type_only(self, private_set, tmp_path):
        path, data = private_set
        run = data['runs'][0]
        other = tss.put_blob(path, b'Dorren walked alone.')
        out = tss.replay_run(path, dict(run, files={**run['files'],
                                                     f'scenes/{SCENE}.md': other}),
                             str(tmp_path / 'run'))
        assert out == {'error': 'ValueError'}

    def test_score_by_check_and_verdict(self, private_set):
        _path, data = private_set
        found = {data['runs'][0]['id']: [
            {'check': 'life', 'quote': 'Pell met him there'},
            {'check': 'possession', 'quote': 'spoke of the map'}]}
        m, ids = tss.score(data, found)
        assert (m['life_findings'], m['life_false'], m['life_precision']) == (1, 1, 0.0)
        assert (m['possession_findings'], m['possession_unlabelled']) == (1, 1)
        assert (m['findings'], m['false_alarms'], m['unlabelled'], m['real_kept']) == (2, 1, 1, 0)
        assert m['labels'] == 2 and m['labels_in_set'] == 1     # Q2 is on a run not in the set
        assert ids['false'] == ['Q1'] and ids['unlabelled'] == [f'{SCENE} (possession)']
        assert 'injury_precision' not in m                     # no findings: no precision

    def test_a_label_matches_one_finding_of_its_check_and_round(self, private_set):
        _path, data = private_set
        run = data['runs'][0]
        twice = [{'check': 'life', 'quote': 'Pell met him there'},
                 {'check': 'life', 'quote': 'Pell met him'}]
        assert [lab and lab['id'] for _f, lab in tss.match(run, twice, data['labels'])] == [
            'Q1', None]
        other_check = [{'check': 'injury', 'quote': 'Pell met him there'}]
        assert tss.match(run, other_check, data['labels'])[0][1] is None

    def test_a_real_catch_lost_and_a_false_one_cleared(self, private_set):
        _path, data = private_set
        data = dict(data, labels=[_label('Q1'), _label('Q3', verdict='real',
                                                       quote='Dorren walked')])
        m, ids = tss.score(data, {})
        assert ids['real_missed'] == ['Q3'] and ids['cleared'] == ['Q1']
        assert (m['real_missed'], m['cleared'], m['findings']) == (1, 1, 0)


# ============================================================================
# The suite
# ============================================================================

class TestSuite:
    def test_end_to_end_free_and_without_prose(self, private_set, tmp_path, monkeypatch):
        import typed_state_set as mod
        suite = _suite()
        monkeypatch.setitem(suite.run.__globals__, 'RECORDED_SET', '')
        monkeypatch.setitem(suite.run.__globals__, 'WORKERS', 2)
        result = harness.run_suite(suite, 'replay', str(tmp_path / 'c'))
        assert result['status'] in ('pass', 'fail'), result.get('error')
        assert result['metrics']['life_false'] == 1 and result['cost']['calls'] == 0
        assert any('false alarms still made (1): Q1' in n for n in result['notes'])
        text = json.dumps({k: result[k] for k in ('metrics', 'gates', 'notes', 'error')})
        for words in ('Pell met him', 'Dorren walked', 'the study'):
            assert words not in text
        path, _data = private_set
        with open(os.path.join(path, 'results', 'latest.json')) as f:
            assert 'Pell met him there' in f.read()             # private, beside the set
        assert mod.CHECKS                                       # imported once, in the parent

    def test_another_set_errors(self, private_set, tmp_path):
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error' and 'not the one FLOORS' in result['error']


# ============================================================================
# The builder
# ============================================================================

class TestBuild:
    def test_kept_files(self):
        for p in ('storyforge.yaml', 'reference/commitments.csv', 'scenes/a.md',
                  'working/typed-state/a.json', 'working/stage-sheets/a.writer.json',
                  'reference/source/iliad/characters.csv',
                  'reference/source/iliad/reference/characters.csv'):
            assert build.kept(p), p
        for p in ('reference/outline.md', 'reference/source/iliad/scenes/b.md',
                  'working/logs/gate/x.json', 'scenes/notes/a.md', 'manuscript.md'):
            assert not build.kept(p), p

    def test_report_a_parses(self):
        text = REPORT_A.read_text(encoding='utf-8')
        counts = build.runs_per_scene(text)
        labels = build.labels(text)
        assert len(counts) == 44 and sum(counts.values()) == 100
        by = {}
        for lab in labels:
            by.setdefault(lab['check'], []).append(lab['verdict'])
        assert {c: len(v) for c, v in by.items()} == {
            'possession': 43, 'injury': 13, 'life': 8, 'time': 1}
        assert by['time'] == ['real'] and by['life'].count('false') == 8
        assert all(set(lab['rounds']) <= set(build.ROUNDS[counts[lab['scene']]])
                   for lab in labels)

    def test_build_from_a_book_repo(self, project_dir, tmp_path):
        """Each scene commit is a run: its parent's files, its own prose and
        state; a scene whose state isn't of its prose is left out, said."""
        _book(project_dir)
        repo = str(tmp_path / 'book')
        os.makedirs(repo)

        def git(*a):
            subprocess.run(['git', '-C', repo, *a], check=True, capture_output=True)

        git('init', '-q', '-b', 'main')
        git('config', 'user.email', 't@example.com')
        git('config', 'user.name', 't')
        import shutil
        for rel in ('storyforge.yaml', 'reference'):
            src = os.path.join(project_dir, rel)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(repo, rel))
        os.makedirs(os.path.join(repo, 'working', 'typed-state'))
        os.makedirs(os.path.join(repo, 'scenes'))
        git('add', '-A')
        git('commit', '-q', '-m', 'Start')
        for scene in (PREV, SCENE):
            for rel in (f'scenes/{scene}.md', f'working/typed-state/{scene}.json'):
                shutil.copy(os.path.join(project_dir, rel), os.path.join(repo, rel))
            if scene == PREV:   # a discarded fix: the state is of other prose
                with open(os.path.join(repo, 'scenes', f'{scene}.md'), 'a') as f:
                    f.write(' More.')
            git('add', '-A')
            git('commit', '-q', '-m', f'Draft scene {scene}')
        report = ('### Per scene\n\n| Scene | Runs | Run by run | End |\n|---|---|---|---|\n'
                  f'| {PREV} | 1 | pass | passed |\n| {SCENE} | 2 | life×1 → pass | passed |\n'
                  '\n### Every blocking finding, classified\n\n'
                  '| # | Scene | Runs | Layer | Quote | Verdict | Reason | Log |\n'
                  '|---|---|---|---|---|---|---|---|\n'
                  f'| Q1 | {SCENE} | recheck | typed:life | Pell met him there | **FALSE** | x | y |\n'
                  f'| Q2 | {SCENE} | . | blocking | Dorren walked | **REAL** | x | y |\n')
        out = str(tmp_path / 'private')
        data = build.build(repo, report, out, branch='main')
        assert [r['id'] for r in data['runs']] == [f'wrath/{SCENE}/recheck']
        assert [lab['id'] for lab in data['labels']] == ['Q1']        # typed layers only
        assert {(x['scene'], x['round']) for x in data['not_replayable']} == {
            (PREV, '.'), (SCENE, '.')}
        files = data['runs'][0]['files']
        assert f'scenes/{PREV}.md' in files and f'scenes/{SCENE}.md' in files
        path = os.path.join(out, tss.SET_NAME)
        assert tss.validate(tss.load(path)) == []
        out_run = tss.replay_run(path, data['runs'][0], str(tmp_path / 'run'))
        # PREV's state isn't of its prose, so its death isn't read: no finding
        assert out_run['findings'] == []

    def test_a_label_on_a_run_the_scene_never_had_stops_the_build(self, tmp_path):
        report = ('### Per scene\n\n| Scene | Runs | Run by run | End |\n|---|---|---|---|\n'
                  '| s1 | 1 | pass | passed |\n'
                  '\n### Every blocking finding, classified\n\n'
                  '| Q1 | s1 | recheck | typed:life | q | **FALSE** | x | y |\n')
        repo = str(tmp_path / 'book')
        os.makedirs(repo)
        for args in (['init', '-q'], ['-c', 'user.email=t@example.com', '-c', 'user.name=t',
                                      'commit', '-q', '--allow-empty', '-m', 'Draft scene s1']):
            subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True)
        with pytest.raises(ValueError, match="rounds aren't runs of their scene: Q1"):
            build.build(repo, report, str(tmp_path / 'o'), branch='HEAD')
