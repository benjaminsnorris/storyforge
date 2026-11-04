"""Text fidelity: the upper tiers checked against the book's prose.

On three extracted books (storyforge-evals F-161) the boundary checks said
"both are right" 98 times in 105 while the synopses carried wrong causes,
processes squeezed into one moment and a reading from Euripides: nothing read
the book. `score --text-fidelity` does.
"""

import json
import os

import pytest

from storyforge import api
from storyforge import scoring_text_fidelity as tf


def _write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(header) + '\n')
        for r in rows:
            f.write('|'.join(r.get(c, '') for c in header) + '\n')


SUMMARY = """---
logline_updated: 2026-11-03
---

# Story summary

## Logline

Ann finds the letter and leaves the town.

## Synopsis

Ann finds a letter in the attic. She burns it and leaves.

## Act-shape

### Act 1

Ann finds the letter.

## Theme

Secrets cost more than they hide.
"""


@pytest.fixture
def book(tmp_path):
    ref, scenes = tmp_path / 'reference', tmp_path / 'scenes'
    scenes.mkdir()
    rows = [{'id': f's{i}', 'seq': str(i), 'title': f'Scene {i}', 'summary': f'Summary {i}',
             'status': 'drafted'} for i in range(1, 5)]
    rows.append({'id': 's5', 'seq': '5', 'title': 'Cut', 'summary': '', 'status': 'cut'})
    _write(str(ref / 'scenes.csv'), ['id', 'seq', 'title', 'summary', 'status'], rows)
    for r in rows:
        (scenes / f'{r["id"]}.md').write_text(f'Prose of {r["id"]}. ' * 50)
    (ref / 'story-summary.md').write_text(SUMMARY)
    _write(str(ref / 'spine.csv'), ['id', 'seq', 'summary', 'function', 'act'],
           [{'id': 'letter-found', 'seq': '1', 'summary': 'Ann finds the letter.',
             'function': 'f', 'act': '1'}])
    _write(str(ref / 'architecture.csv'), ['id', 'seq', 'summary', 'act', 'spine_event'],
           [{'id': 's1', 'seq': '1', 'summary': 'Ann climbs to the attic.', 'act': '1',
             'spine_event': 'letter-found'},
            {'id': 's5', 'seq': '5', 'summary': 'A cut scene.', 'act': '1',
             'spine_event': 'letter-found'}])
    (tmp_path / 'working').mkdir()
    return tmp_path


def _reply(payload):
    return {'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'stop_reason': 'end_turn', 'usage': {'input_tokens': 10, 'output_tokens': 10}}


def _claims_payload():
    return {'claims': [
        {'section': 'logline', 'kind': 'event', 'claim': 'Ann finds the letter', 'scenes': ['s1']},
        {'section': 'synopsis', 'kind': 'event', 'claim': 'She burns it', 'scenes': ['s3']},
        {'section': 'act-shape', 'kind': 'event', 'claim': 'Ann finds the letter', 'scenes': ['s1']},
        {'section': 'theme', 'kind': 'interpretation', 'claim': 'Secrets cost more',
         'scenes': ['s2', 's4']},
        {'section': 'spine:letter-found', 'kind': 'event', 'claim': 'Ann finds the letter',
         'scenes': ['s1']},
    ]}


class TestReadTiers:
    def test_reads_the_written_tiers(self, book):
        tiers = tf.read_tiers(str(book))
        assert tiers.summary['logline'].startswith('Ann finds')
        assert tiers.anchors == {'letter-found': ['s1', 's5']}
        assert not tiers.empty()

    def test_a_template_summary_counts_as_empty(self, tmp_path):
        from storyforge.common import get_plugin_dir
        template = os.path.join(get_plugin_dir(), 'templates', 'reference', 'story-summary.md')
        if not os.path.isfile(template):
            pytest.skip('no story-summary template')
        os.makedirs(tmp_path / 'reference')
        with open(template) as f:
            (tmp_path / 'reference' / 'story-summary.md').write_text(f.read())
        assert tf.read_tiers(str(tmp_path)).empty()


class TestClaims:
    def test_prompt_lists_documents_and_scenes(self, book):
        tiers = tf.read_tiers(str(book))
        prompt = tf.build_claims_prompt(tiers, tf._scenes(str(book)))
        assert '### synopsis' in prompt and '### spine:letter-found' in prompt
        assert 'its anchor scenes: s1, s5' in prompt
        assert '1. s1 | Scene 1 | Summary 1' in prompt
        assert 's5 | Cut' not in prompt      # cut scenes aren't in the book

    def test_parse_reads_claims(self, book):
        tiers = tf.read_tiers(str(book))
        claims = tf.parse_claims(json.dumps(_claims_payload()), tiers, tf._scenes(str(book)))
        assert [c.section for c in claims][:2] == ['logline', 'synopsis']
        assert claims[3].scenes == ['s2', 's4']

    @pytest.mark.parametrize('change, problem', [
        (lambda p: p['claims'][0].update(section='preface'), 'not one of the documents'),
        (lambda p: p['claims'][0].update(scenes=['nope']), 'not in the list'),
        (lambda p: p['claims'][0].update(scenes=[]), 'cites no scene'),
        (lambda p: p['claims'][0].update(scenes=['s1', 's2', 's3', 's4', 's1']), 'at most 4'),
        (lambda p: p['claims'].pop(3), 'no claims from: theme'),
    ])
    def test_unusable_answers_are_named(self, book, change, problem):
        payload = _claims_payload()
        change(payload)
        with pytest.raises(tf._Problems, match=problem):
            tf.parse_claims(json.dumps(payload), tf.read_tiers(str(book)), tf._scenes(str(book)))

    def test_anchor_summaries_are_claims_about_their_own_scene(self, book):
        claims = tf.anchor_claims(tf.read_tiers(str(book)), tf._scenes(str(book)))
        assert [(c.section, c.scenes) for c in claims] == [('architecture:s1', ['s1'])]


class TestBatches:
    def test_groups_stay_within_the_budget_and_cover_every_claim(self):
        claims = [tf.Claim('synopsis', 'event', f'c{i}', [s]) for i, s in
                  enumerate(['s1', 's2', 's3', 's1', 's4'])]
        words = {'s1': 600, 's2': 600, 's3': 600, 's4': 600}
        groups = tf.batches(claims, words, budget=1300)
        assert sorted(i for g in groups for i in g) == [0, 1, 2, 3, 4]
        for g in groups:
            assert sum(words[s] for s in {s for i in g for s in claims[i].scenes}) <= 1300
        assert any({0, 3} <= set(g) for g in groups)     # claims on one scene share it

    def test_an_oversized_claim_goes_alone(self):
        claims = [tf.Claim('synopsis', 'event', 'big', ['s1', 's2']),
                  tf.Claim('synopsis', 'event', 'small', ['s3'])]
        groups = tf.batches(claims, {'s1': 900, 's2': 900, 's3': 10}, budget=1000)
        assert groups == [[0], [1]]


class TestVerify:
    def test_prompt_shows_passages_once_and_numbers_claims(self):
        claims = [tf.Claim('synopsis', 'event', 'A', ['s1']),
                  tf.Claim('theme', 'interpretation', 'B', ['s1', 's2'])]
        prompt = tf.build_verify_prompt(claims, [0, 1], {'s1': 'ONE', 's2': 'TWO'})
        assert prompt.count('=== scene s1 ===') == 1 and '=== scene s2 ===' in prompt
        assert '1. [synopsis; event; scenes s1] A' in prompt
        assert '2. [theme; interpretation; scenes s1, s2] B' in prompt
        assert 'Judge only from these passages' in prompt
        assert 'another work or tradition' in prompt

    @pytest.mark.parametrize('verdicts, problem', [
        ([{'n': 1}], 'no verdict for claim'),
        ([{'n': 1}, {'n': 1}, {'n': 2}], 'two verdicts'),
        ([{'n': 1}, {'n': 2}, {'n': 3}], 'not in the list'),
    ])
    def test_every_claim_answered_exactly_once(self, verdicts, problem):
        payload = {'verdicts': [dict(v, verdict='supported', evidence='', correction='')
                                for v in verdicts]}
        with pytest.raises(tf._Problems, match=problem):
            tf.parse_verdicts(json.dumps(payload), 2)


class TestRun:
    def _fake(self, monkeypatch, replies):
        calls = []

        def fake(prompt, model, log_file, max_tokens=4096, **kw):
            calls.append(prompt)
            reply = replies(prompt, len(calls))
            if isinstance(reply, Exception):
                raise reply
            with open(log_file, 'w') as f:
                json.dump(reply, f)
            return reply
        monkeypatch.setattr(api, 'invoke_to_file', fake)
        return calls

    def _verdicts_for(self, prompt, bad='She burns it'):
        lines = [l for l in prompt.split('## Claims')[1].splitlines() if l[:1].isdigit()]
        return _reply({'verdicts': [
            {'n': int(l.split('.')[0]),
             'verdict': 'contradicted' if bad in l else 'supported',
             'evidence': 'she kept it' if bad in l else 'x',
             'correction': 'She keeps it.' if bad in l else ''} for l in lines]})

    def test_both_passes_and_the_report(self, book, monkeypatch):
        calls = self._fake(monkeypatch, lambda p, n: _reply(_claims_payload()) if n == 1
                           else self._verdicts_for(p))
        approved, usage = [], []
        result = tf.run(str(book), 'claude-opus-5-5', log_dir=str(book / 'logs'),
                        approve=lambda c: approved.append(c) or True,
                        on_usage=lambda path, label: usage.append(label))
        assert len(result.claims) == 6          # 5 from pass 1, 1 anchor
        burned = next(c for c in result.claims if c.claim == 'She burns it')
        assert burned.verdict == 'contradicted' and burned.correction == 'She keeps it.'
        assert all(c.verdict for c in result.claims)
        assert len(approved) == 1 and usage[0] == 'text-fidelity-claims'
        out = str(book / 'out')
        tf.write(result, out, 'Ann')
        report = open(os.path.join(out, 'report.md')).read()
        assert '## Contradicted by the text (1)' in report and 'She keeps it.' in report
        assert '| synopsis | 0 | 1 | 0 | 0 | 0 |' in report
        assert open(os.path.join(out, 'claims.csv')).readline().strip() == \
            '|'.join(tf.CLAIM_COLUMNS)

    def test_a_declined_verify_pass_stops(self, book, monkeypatch):
        self._fake(monkeypatch, lambda p, n: _reply(_claims_payload()))
        with pytest.raises(tf.FidelityError, match='declined'):
            tf.run(str(book), 'm', log_dir=str(book / 'logs'), approve=lambda c: False)

    def test_an_unusable_claims_answer_is_sent_back_once(self, book, monkeypatch):
        bad = _claims_payload()
        bad['claims'][0]['scenes'] = ['nope']
        calls = self._fake(monkeypatch, lambda p, n: _reply(bad) if n == 1 else
                           (_reply(_claims_payload()) if n == 2 else self._verdicts_for(p)))
        tf.run(str(book), 'm', log_dir=str(book / 'logs'))
        assert 'not in the list' in calls[1]

    def test_an_api_error_is_a_fidelity_error(self, book, monkeypatch):
        self._fake(monkeypatch, lambda p, n: RuntimeError('HTTP 529'))
        with pytest.raises(tf.FidelityError, match='HTTP 529'):
            tf.run(str(book), 'm', log_dir=str(book / 'logs'))

    def test_no_tiers_is_an_error(self, tmp_path):
        _write(str(tmp_path / 'reference' / 'scenes.csv'), ['id', 'seq'], [{'id': 's1', 'seq': '1'}])
        with pytest.raises(tf.FidelityError, match='no upper tiers'):
            tf.run(str(tmp_path), 'm', log_dir=str(tmp_path / 'logs'))


class TestCommand:
    def test_flag_is_exclusive_with_other_entry_points(self, book, monkeypatch, capsys):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: str(book))
        with pytest.raises(SystemExit):
            cmd_score.main(['--text-fidelity', '--story-power'])

    def test_dry_run_forecasts_without_calling(self, book, monkeypatch, capsys):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: str(book))
        monkeypatch.setattr(api, 'invoke_to_file',
                            lambda *a, **k: pytest.fail('dry run called the API'))
        cmd_score.main(['--text-fidelity', '--dry-run'])
        assert 'These documents summarize a book' in capsys.readouterr().out


class TestReviewEdges:
    def test_quotes_and_backslashes_read_back_as_written(self, tmp_path):
        from storyforge.elaborate import _read_csv
        r = tf.Result([tf.Claim('synopsis', 'event', 'He "finally" lost it \\ all', ['s1'],
                                'contradicted', '"I kept it," said Joe', 'He keeps some.')])
        tf.write(r, str(tmp_path))
        row = _read_csv(str(tmp_path / 'claims.csv'))[0]
        assert row['claim'] == 'He "finally" lost it \\ all'
        assert row['evidence'] == '\u201cI kept it," said Joe'   # a leading quote is curled

    def test_batches_cap_claims(self):
        claims = [tf.Claim('synopsis', 'event', f'c{i}', ['s1']) for i in range(90)]
        groups = tf.batches(claims, {'s1': 10}, max_claims=40)
        assert [len(g) for g in groups] == [40, 40, 10]

    def test_a_failed_batch_is_unchecked_and_the_rest_kept(self, book, monkeypatch):
        payload = _claims_payload()

        def fake(prompt, model, log_file, max_tokens=4096, **kw):
            if 'Split them' in prompt:
                reply = _reply(payload)
            elif 'She burns it' in prompt:
                raise RuntimeError('HTTP 529')
            else:
                lines = [l for l in prompt.split('## Claims')[1].splitlines() if l[:1].isdigit()]
                reply = _reply({'verdicts': [{'n': int(l.split('.')[0]), 'verdict': 'supported',
                                              'evidence': '', 'correction': ''} for l in lines]})
            with open(log_file, 'w') as f:
                json.dump(reply, f)
            return reply
        monkeypatch.setattr(api, 'invoke_to_file', fake)
        monkeypatch.setattr(tf, 'BATCH_CLAIMS', 1)
        monkeypatch.setattr(tf.batches, '__defaults__', (tf.BATCH_WORDS, 1))
        result = tf.run(str(book), 'm', log_dir=str(book / 'logs'))
        verdicts = {c.claim: c.verdict for c in result.claims}
        assert verdicts['She burns it'] == tf.UNCHECKED
        assert verdicts['Secrets cost more'] == 'supported'
        assert any('not checked' in n for n in result.notes)

    def test_claims_on_prose_less_scenes_are_unchecked_without_a_call(self, book, monkeypatch):
        (book / 'scenes' / 's3.md').write_text('')
        prompts = []

        def fake(prompt, model, log_file, max_tokens=4096, **kw):
            prompts.append(prompt)
            if 'Split them' in prompt:
                reply = _reply(_claims_payload())
            else:
                lines = [l for l in prompt.split('## Claims')[1].splitlines() if l[:1].isdigit()]
                reply = _reply({'verdicts': [{'n': int(l.split('.')[0]), 'verdict': 'supported',
                                              'evidence': '', 'correction': ''} for l in lines]})
            with open(log_file, 'w') as f:
                json.dump(reply, f)
            return reply
        monkeypatch.setattr(api, 'invoke_to_file', fake)
        result = tf.run(str(book), 'm', log_dir=str(book / 'logs'))
        assert {c.claim: c.verdict for c in result.claims}['She burns it'] == tf.UNCHECKED
        assert not any('She burns it' in p for p in prompts[1:])

    @pytest.mark.parametrize('payload, problem', [
        ({'claims': ['not a dict']}, 'not an object'),
        ({'claims': [{'section': 'logline', 'kind': 'event', 'claim': 'x', 'scenes': None}]},
         'not an object'),
        ({'claims': [{'section': 'logline', 'kind': 'gossip', 'claim': 'x', 'scenes': ['s1']}]},
         'kind'),
    ])
    def test_malformed_claims_are_problems(self, book, payload, problem):
        with pytest.raises(tf._Problems, match=problem):
            tf.parse_claims(json.dumps(payload), tf.read_tiers(str(book)), tf._scenes(str(book)))

    @pytest.mark.parametrize('verdict, problem', [
        ({'n': True, 'verdict': 'supported'}, 'not in the list'),
        ({'n': 1, 'verdict': 'maybe'}, 'is not one of'),
        ('nope', 'not an object'),
    ])
    def test_malformed_verdicts_are_problems(self, verdict, problem):
        with pytest.raises(tf._Problems, match=problem):
            tf.parse_verdicts(json.dumps({'verdicts': [verdict]}), 1)
