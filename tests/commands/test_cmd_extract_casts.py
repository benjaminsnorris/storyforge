"""storyforge extract --phase 2 --casts-only, end to end (#523).

The batch goes through mock_api's Batch API fakes, git through mock_git.
The fixture project's scene files are act1-sc01, act1-sc02, new-x1 and
act2-sc01; its casts are written as names (Dorren Hayle), which the
registry's aliases resolve.
"""

import json
import os
import re

import pytest

from storyforge.cmd_extract import main, parse_args

ASKABLE = 'act1-sc01,act1-sc02,new-x1,act2-sc01'


def _cast(characters=(), on_stage=()):
    return json.dumps({'characters': list(characters), 'on_stage': list(on_stage)})


def _rows(project_dir):
    from storyforge.elaborate import _read_csv_as_map
    return _read_csv_as_map(os.path.join(project_dir, 'reference', 'scene-intent.csv'))


def _prompts(mock_api):
    return {r['custom_id']: r['params']['messages'][0]['content']
            for c in mock_api.calls_for('submit_batch') for r in c['requests']}


@pytest.fixture
def run(mock_api, mock_git, mock_costs, project_dir, monkeypatch):
    """main() on the fixture project with a key set and hone stubbed (it
    records the call and adds no row); returns the hone calls."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_extract.detect_project_root', lambda: project_dir)
    monkeypatch.chdir(project_dir)
    hone_calls = []
    monkeypatch.setattr('storyforge.cmd_hone.main', lambda argv: hone_calls.append(argv))
    return hone_calls


class TestArgs:
    def test_casts_only_with_its_filters(self):
        args = parse_args(['--phase', '2', '--casts-only', '--from-seq', '25',
                           '--exclude-scenes', 'a,b'])
        assert args.casts_only and args.from_seq == '25' and args.exclude_scenes == 'a,b'

    @pytest.mark.parametrize('argv', [
        ['--casts-only'],                                   # phase 2's
        ['--phase', '3', '--casts-only'],
        ['--phase', '2', '--casts-only', '--force'],        # would replace, not add
        ['--phase', '2', '--casts-only', '--cleanup'],
        ['--phase', '2', '--casts-only', '--scenes', 'a', '--from-seq', '3'],
        ['--phase', '2', '--scenes', 'a'],                  # a filter the phase would ignore
        ['--exclude-scenes', 'a'],
    ])
    def test_refused_combinations(self, argv):
        with pytest.raises(SystemExit) as e:
            parse_args(argv)
        assert e.value.code == 2


class TestDryRun:
    def test_prints_the_prompt_and_forecast_and_sends_nothing(
            self, run, mock_api, mock_git, project_dir, capsys):
        from storyforge.enrich import PARTIAL_REGISTRY_NOTE
        before = open(os.path.join(project_dir, 'reference', 'scene-intent.csv')).read()
        main(['--phase', '2', '--casts-only', '--dry-run', '--scenes', ASKABLE])
        out = capsys.readouterr().out
        assert 'DRY RUN: Phase 2, casts only — 4 scene(s)' in out
        assert 'Name the cast of this scene.' in out
        assert f'### Characters (reference/characters.csv) — {PARTIAL_REGISTRY_NOTE}' in out
        assert '### Locations' not in out      # only the characters bear on a cast
        assert re.search(r'Forecast: \$\d+\.\d\d', out)
        assert mock_api.call_count == 0
        assert not mock_git.calls_for('create_branch')
        assert not mock_git.calls_for('commit_and_push')
        assert run == []
        assert open(os.path.join(project_dir, 'reference', 'scene-intent.csv')).read() == before

    def test_does_not_need_an_api_key(self, run, mock_api, monkeypatch, capsys):
        monkeypatch.delenv('ANTHROPIC_API_KEY')
        main(['--phase', '2', '--casts-only', '--dry-run', '--scenes', ASKABLE])
        assert 'Forecast:' in capsys.readouterr().out

    def test_a_scene_that_cant_be_asked_is_named_and_the_exit_is_1(self, run, capsys):
        with pytest.raises(SystemExit) as e:
            main(['--phase', '2', '--casts-only', '--dry-run'])   # act2-sc02/03 have no prose
        assert e.value.code == 1
        assert 'Not asked: act2-sc02: no scenes/act2-sc02.md' in capsys.readouterr().out


class TestSceneFilter:
    def test_scenes_by_id(self, run, mock_api):
        mock_api.set_response(_cast())
        main(['--phase', '2', '--casts-only', '--scenes', 'act1-sc02,act1-sc01'])
        assert list(_prompts(mock_api)) == ['act1-sc01', 'act1-sc02']   # reading order

    def test_a_seq_range(self, run, mock_api):
        mock_api.set_response(_cast())
        main(['--phase', '2', '--casts-only', '--from-seq', '2-4'])
        assert list(_prompts(mock_api)) == ['act1-sc02', 'new-x1', 'act2-sc01']

    def test_an_act(self, run, mock_api):
        mock_api.set_response(_cast())
        with pytest.raises(SystemExit):   # act2-sc02 and act2-sc03 have no prose
            main(['--phase', '2', '--casts-only', '--act', '2'])
        assert list(_prompts(mock_api)) == ['act2-sc01']

    def test_excluded_scenes_are_not_asked_or_touched(self, run, mock_api, project_dir):
        mock_api.set_response(_cast(['zed-orlo'], ['zed-orlo']))
        before = _rows(project_dir)['act1-sc01']
        main(['--phase', '2', '--casts-only', '--scenes', ASKABLE,
              '--exclude-scenes', 'act1-sc01'])
        assert 'act1-sc01' not in _prompts(mock_api)
        assert _rows(project_dir)['act1-sc01'] == before
        assert _rows(project_dir)['act1-sc02']['characters'].endswith(';zed-orlo')

    def test_an_excluded_id_that_isnt_a_scene_stops_the_run(self, run, mock_api):
        with pytest.raises(SystemExit) as e:
            main(['--phase', '2', '--casts-only', '--scenes', ASKABLE,
                  '--exclude-scenes', 'act1-sc1'])
        assert e.value.code == 1
        assert mock_api.call_count == 0


class TestMerge:
    def test_new_ids_are_added_and_nothing_else_changes(
            self, run, mock_api, mock_git, project_dir):
        path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        before_lines = open(path).read().split('\n')

        def reply(prompt):
            if '## Scene: act1-sc01' in prompt:
                # Tessa (an alias) is already there; Pell leaves on_stage out
                return _cast(['Tessa', 'old-mother-vey', 'Kael'], ['old-mother-vey', 'Kael'])
            return _cast(['dorren-hayle'], ['dorren-hayle'])
        mock_api.set_response_fn(reply)

        main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])

        rows = _rows(project_dir)
        assert rows['act1-sc01']['characters'] == \
            'Dorren Hayle;Tessa Merrin;Pell;old-mother-vey;kael-maren'
        assert rows['act1-sc01']['on_stage'] == 'Dorren Hayle;Tessa Merrin;old-mother-vey;kael-maren'
        after_lines = open(path).read().split('\n')
        header = before_lines[0].split('|')
        cast_cols = {header.index('characters'), header.index('on_stage')}
        for old, new in zip(before_lines, after_lines):
            o, n = old.split('|'), new.split('|')
            assert [v for i, v in enumerate(o) if i not in cast_cols] == \
                   [v for i, v in enumerate(n) if i not in cast_cols]
        # act2-sc01 lacked Dorren: added to both columns
        assert rows['act2-sc01']['characters'] == 'Tessa Merrin;Pell;dorren-hayle'
        # scenes not asked are as they were
        assert after_lines[5:] == before_lines[5:]

        commits = [c[1] for c in mock_git.calls_for('commit_and_push')]
        assert commits[0].startswith('Extract: Phase 2 casts — ')
        assert commits[-1] == 'Extract: Phase 2 casts review'
        assert run == [['--domain', 'characters']]   # the registry pass, characters only

    def test_extraction_records_are_left_as_they_were(self, run, mock_api, project_dir):
        """No cast cell is in phase 5's cell record or the provenance record;
        the merge only adds, so it writes neither."""
        working = os.path.join(project_dir, 'working')
        cells = os.path.join(working, 'extraction-cells.csv')
        prov = os.path.join(working, 'extraction-provenance.csv')
        with open(cells, 'w') as f:
            f.write('file|scene_id|column|value\n'
                    'scene-intent.csv|act1-sc01|theme_threads|audit\n')
        with open(prov, 'w') as f:
            f.write('file|version|step|written_at|sha256\n')
        before = (open(cells).read(), open(prov).read())
        mock_api.set_response(_cast(['zed-orlo'], []))
        main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        assert (open(cells).read(), open(prov).read()) == before

    def test_the_review_lists_each_scenes_additions(self, run, mock_api, project_dir, capsys):
        mock_api.set_response_fn(lambda p: _cast(['zed-orlo', 'Kael'], ['Kael'])
                                 if '## Scene: act1-sc02' in p else _cast())
        main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        review = open(os.path.join(project_dir, 'working', 'extract-casts-review.md')).read()
        assert ('### act1-sc02\n- characters: zed-orlo (not in characters.csv), '
                'kael-maren (Kael Maren)\n- on_stage: kael-maren (Kael Maren)\n') in review
        assert 'Ids added: 2 to characters, 1 to on_stage.' in review
        assert '## Answered with no one' in review
        out = capsys.readouterr()
        assert '1 of 4 scene(s) gained someone' in out.err + out.out

    def test_nothing_gained_writes_no_cast_commit_and_runs_no_registry_pass(
            self, run, mock_api, mock_git, project_dir):
        path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        before = open(path, 'rb').read()
        mock_api.set_response(_cast(['dorren-hayle'], []))
        main(['--phase', '2', '--casts-only', '--scenes', 'act1-sc01'])
        assert open(path, 'rb').read() == before
        assert run == []
        assert [c[1] for c in mock_git.calls_for('commit_and_push')] == \
            ['Extract: Phase 2 casts review']


class TestFailures:
    def test_a_failed_item_is_named_and_the_rest_merged(
            self, run, mock_api, project_dir, capsys, monkeypatch):
        """A batch item with no usable reply (no .txt: failed, refused or cut
        off) is left as it was, listed, and the run exits 1."""
        mock_api.set_response(_cast(['zed-orlo'], []))
        real = mock_api._download_batch_results

        def download(url, output_dir, log_dir, keep_incomplete=False):
            done = real(url, output_dir, log_dir, keep_incomplete)
            os.remove(os.path.join(log_dir, 'act1-sc02.txt'))
            return [d for d in done if d != 'act1-sc02']
        monkeypatch.setattr('storyforge.cmd_extract.download_batch_results', download)
        before = _rows(project_dir)['act1-sc02']
        with pytest.raises(SystemExit) as e:
            main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        assert e.value.code == 1
        rows = _rows(project_dir)
        assert rows['act1-sc02'] == before
        assert rows['act1-sc01']['characters'].endswith(';zed-orlo')
        review = open(os.path.join(project_dir, 'working', 'extract-casts-review.md')).read()
        assert '- act1-sc02: no usable reply' in review
        assert 'act1-sc02: no usable reply' in capsys.readouterr().out

    def test_an_unreadable_reply_is_named(self, run, mock_api, project_dir):
        mock_api.set_response_fn(lambda p: 'not json' if '## Scene: new-x1' in p
                                 else _cast(['zed-orlo'], []))
        with pytest.raises(SystemExit):
            main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        review = open(os.path.join(project_dir, 'working', 'extract-casts-review.md')).read()
        assert '- new-x1: unreadable reply' in review

    def test_a_failed_batch_merges_nothing(self, run, mock_api, project_dir, monkeypatch):
        def boom(batch_file):
            raise RuntimeError('HTTP 529 overloaded')
        monkeypatch.setattr('storyforge.cmd_extract.submit_batch', boom)
        before = open(os.path.join(project_dir, 'reference', 'scene-intent.csv')).read()
        with pytest.raises(SystemExit) as e:
            main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        assert e.value.code == 1
        assert open(os.path.join(project_dir, 'reference', 'scene-intent.csv')).read() == before
        assert run == []

    def test_over_the_threshold_sends_nothing(self, run, mock_api, mock_costs):
        mock_costs.threshold_ok = False
        with pytest.raises(SystemExit) as e:
            main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        assert e.value.code == 1
        assert not mock_api.calls_for('submit_batch')

    def test_a_failed_registry_pass_is_an_error(self, run, mock_api, project_dir, monkeypatch):
        def hone_fails(argv):
            raise SystemExit(1)
        monkeypatch.setattr('storyforge.cmd_hone.main', hone_fails)
        mock_api.set_response(_cast(['zed-orlo'], []))
        with pytest.raises(SystemExit) as e:
            main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        assert e.value.code == 1
        review = open(os.path.join(project_dir, 'working', 'extract-casts-review.md')).read()
        assert 'Registry: FAILED' in review
        # the casts are still merged: they are right, the registry is behind
        assert _rows(project_dir)['act1-sc01']['characters'].endswith(';zed-orlo')

    def test_a_failed_commit_is_an_error(self, run, mock_api, mock_git):
        mock_git.commit_success = False
        mock_api.set_response(_cast(['zed-orlo'], []))
        with pytest.raises(SystemExit) as e:
            main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])
        assert e.value.code == 1


class TestWithHone:
    def test_new_ids_become_registry_rows_with_no_pronouns(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """The real registry pass: hone asks what each unresolved reference
        is, and a NEW answer becomes a characters.csv row with hone's role
        and an empty pronouns cell (#513: empty beats a guess)."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root', lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_hone.detect_project_root', lambda: project_dir)
        monkeypatch.chdir(project_dir)
        chars_path = os.path.join(project_dir, 'reference', 'characters.csv')
        with open(chars_path) as f:
            text = f.read()
        with open(chars_path, 'w') as f:   # a pronouns column, as the template has
            f.write(text.replace('death_scene\n', 'death_scene|pronouns\n', 1)
                    .replace('protagonist|\n', 'protagonist||he\n'))

        def reply(prompt):
            if prompt.startswith('Name the cast of this scene.'):
                return _cast(['old-mother-vey'], ['old-mother-vey']) \
                    if '## Scene: act1-sc01' in prompt else _cast()
            # hone's mapping call: every reference is someone new
            lines = re.findall(r'^(\d+)\. (\S[^\[]*?)\s*(?:\[|$)', prompt, re.M)
            return '\n'.join(f'{n} | NEW | {t.lower().replace(" ", "-")} | {t.title()} | minor'
                             for n, t in lines)
        mock_api.set_response_fn(reply)

        main(['--phase', '2', '--casts-only', '--scenes', ASKABLE])

        from storyforge.elaborate import _read_csv
        rows = {r['id']: r for r in _read_csv(chars_path)}
        assert rows['old-mother-vey']['role'] == 'minor'
        assert rows['old-mother-vey']['pronouns'] == ''
        assert rows['dorren-hayle']['pronouns'] == 'he'
        review = open(os.path.join(project_dir, 'working', 'extract-casts-review.md')).read()
        assert '- characters: old-mother-vey (Old-Mother-Vey)' in review
        assert 'Registry: hone --domain characters added' in review
