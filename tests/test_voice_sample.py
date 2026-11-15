"""Blind voice sample rounds (#654)."""

import json
import os
import random

import pytest

from storyforge import pr_marks, voice_sample as vs

SCENE = 'act1-sc01'


def test_one_per_line_and_back():
    text = 'She ran. He saw her! "Stop," he said.\n\nThe gate was open.'
    lines = vs.one_per_line(text)
    assert lines == 'She ran.\nHe saw her!\n"Stop," he said.\n\nThe gate was open.'
    assert vs.join_lines(lines) == 'She ran. He saw her! "Stop," he said.\n\nThe gate was open.'


ROUND = vs.render_round('Voice samples, round 1: s', 'Intro.',
                        [('A', 'She ran. He saw her.'), ('B', 'The gate shook.\n\nHe waited.')])


def test_a_round_parses_back_with_each_sentences_line():
    samples = vs.parse_round(ROUND)
    assert list(samples) == ['A', 'B']
    lines = ROUND.split('\n')
    for s in samples.values():
        for n, sentence in s.lines.items():
            assert lines[n - 1].strip() == sentence
    assert vs.join_lines(samples['B'].text) == 'The gate shook.\n\nHe waited.'
    assert '*5 words*' in ROUND


def test_marks_map_to_the_sample_and_sentence():
    lines = ROUND.split('\n')
    a2 = lines.index('He saw her.') + 1
    b1 = lines.index('The gate shook.') + 1
    prs = pr_marks.PrMarks(
        lines=[pr_marks.Comment('working/voice-samples/round-1.md', a2, 'keep'),
               pr_marks.Comment('working/voice-samples/round-1.md', b1, '',
                                suggestion='The gate held.', outdated=True),
               pr_marks.Comment('working/voice-samples/round-1.md', 1, 'title?'),
               pr_marks.Comment('working/costs/ledger.csv', 3, 'not this file')],
        general=['More like B.'])
    marks, notes = vs.marks_for_round(prs, ROUND, 'working/voice-samples/round-1.md')
    assert marks['A'].marks == [('He saw her.', 'keep')]
    assert marks['B'].suggestions == [('The gate shook.', 'The gate held.')]
    assert any('no sample\'s sentence' in n for n in notes)
    assert any('since changed' in n for n in notes)
    text = vs.describe_marks(vs.parse_round(ROUND), marks, {'tried': {'A': 'close past'}},
                             prs.general)
    assert 'it tried: close past' in text and '"The gate shook." → "The gate held."' in text
    assert 'More like B.' in text


def test_pr_comment_parsing_reads_suggestions_and_outdated_lines():
    c = pr_marks.parse_comment({'path': 'f.md', 'line': None, 'original_line': 12,
                                'body': 'Better:\n```suggestion\nHe held it.\n```\n'})
    assert (c.line, c.outdated, c.suggestion, c.body) == (12, True, 'He held it.', 'Better:')
    assert pr_marks.parse_comment({'path': 'f.md', 'line': None, 'original_line': None,
                                   'body': 'x'}) is None


@pytest.fixture
def calls(monkeypatch):
    """`api.invoke` answering a round, a review and a revision by schema; the
    blocking read finds nothing."""
    from storyforge import api, blocking
    seen = []

    def fake(prompt, model, tokens, **k):
        seen.append(prompt)
        props = k['output_schema']['properties']
        if 'variants' in props:
            text = {'variants': [{'tried': f'try {i}', 'text': f'Version {i} ran. It stopped.'}
                                 for i in range(5)]}
        elif 'flags' in props:
            text = {'flags': []}
        else:
            text = {'edits': [], 'kept': []}
        return {'content': [{'type': 'text', 'text': json.dumps(text)}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    monkeypatch.setattr(api, 'invoke', fake)
    monkeypatch.setattr(blocking, 'check_blocking',
                        lambda *a, **k: blocking.BlockingResult(SCENE))
    monkeypatch.setattr(vs, 'KEYS_ROOT', '')
    return seen


def test_a_round_is_written_shuffled_checked_and_keyed(project_dir, calls, tmp_path,
                                                        monkeypatch):
    monkeypatch.setattr(vs, 'key_path', lambda pd, n: str(tmp_path / 'keys' / f'r{n}.json'))
    rnd = vs.write_round(project_dir, SCENE, variants=5, vary=['tense'], influences='Renault',
                         model='m', log_dir=str(tmp_path / 'logs'), rng=random.Random(1))
    assert rnd.number == 1 and rnd.text.count('## Sample ') == 5
    assert 'try ' not in rnd.text                                  # blind
    assert sorted(rnd.key['tried'].values()) == [f'try {i}' for i in range(5)]
    assert 'Renault' in calls[0] and 'The Finest Cartographer' in calls[0]
    assert 'Her heart pounded' in calls[1]                         # checks.md: the reviewer
    assert 'Her heart pounded' not in calls[0]                     # never the writer
    vs.save_key(project_dir, rnd.number, rnd.key)
    assert vs.load_key(project_dir, 1)['scene'] == SCENE


def test_a_later_round_writes_toward_the_keeps(project_dir, calls, tmp_path):
    vs.write_round(project_dir, SCENE, variants=3, vary=['tense'], influences='', model='m',
                   log_dir=str(tmp_path), marked='## The last round, as the author marked it')
    assert 'Write toward what the author kept' in calls[0]


def test_a_take_has_one_version_per_named_difference(project_dir, calls, tmp_path):
    rnd = vs.write_take(project_dir, SCENE, sample='B', marked='MARKED', model='m',
                        versions=['present tense', 'past tense'], log_dir=str(tmp_path))
    assert '## present tense' in rnd.text and '## past tense' in rnd.text
    assert 'MARKED' in calls[0] and rnd.key['take'] == 'B'
    with pytest.raises(vs.SampleError, match='at least two'):
        vs.write_take(project_dir, SCENE, sample='B', marked='M', model='m',
                      versions=['one'], log_dir=str(tmp_path))


def test_a_slip_found_before_publishing_is_fixed_and_said(project_dir, monkeypatch, tmp_path):
    from storyforge import api, blocking
    from storyforge.checker import Finding

    def fake(prompt, model, tokens, **k):
        props = k['output_schema']['properties']
        text = ({'flags': []} if 'flags' in props else
                {'edits': [{'flag': 1, 'find': ' with both hands full', 'replace': ''}],
                 'kept': []})
        return {'content': [{'type': 'text', 'text': json.dumps(text)}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    monkeypatch.setattr(api, 'invoke', fake)
    slip = Finding('contradiction', 'BLK', 'waved with both hands full', SCENE, '', '',
                   'his hands are full')
    monkeypatch.setattr(blocking, 'check_blocking',
                        lambda *a, **k: blocking.BlockingResult(SCENE, findings=[slip]))
    texts, notes = vs.check_samples(project_dir, SCENE,
                                    {'A': 'He waved with both hands full. She went.'},
                                    model='m', log_dir=str(tmp_path))
    assert texts['A'] == 'He waved. She went.'
    assert notes and 'flagged before you saw it' in notes[-1]


def test_promote_saves_the_sample_as_edited_with_its_header(project_dir):
    path = os.path.join(project_dir, vs.round_rel(1))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(ROUND.replace('He saw her.', 'He saw her first.'))   # a hand edit
    rel = vs.promote(project_dir, vs.round_rel(1), 'A', 'gate-run', kind='intimate',
                     tense='past', pov='Hector')
    from storyforge import voice_book
    a = [x for x in voice_book.read_folder(project_dir).anchors if x.name == 'gate-run'][0]
    assert (a.kind, a.tense, a.pov, a.text) == (('intimate',), 'past', 'Hector',
                                                'She ran. He saw her first.')
    with pytest.raises(vs.SampleError, match='there already'):
        vs.promote(project_dir, vs.round_rel(1), 'A', 'gate-run')
    with pytest.raises(vs.SampleError, match='no sample'):
        vs.promote(project_dir, vs.round_rel(1), 'Z', 'other')
    with pytest.raises(vs.SampleError, match='--tense'):
        vs.promote(project_dir, vs.round_rel(1), 'A', 'x', tense='future')
    assert rel.endswith('gate-run.md')


def test_the_key_is_outside_the_book(project_dir):
    assert not os.path.realpath(vs.key_path(project_dir, 1)).startswith(
        os.path.realpath(project_dir))


@pytest.mark.parametrize('argv, why', [
    (['sample', '--take', 'B'], '--from-pr'),
    (['sample', '--promote', 'x.md'], '--sample and --name'),
    (['sample'], 'name the scene'),
])
def test_the_cli_says_what_is_missing(project_dir, monkeypatch, capsys, argv, why):
    from storyforge import cmd_voice, common
    monkeypatch.setattr(common, 'detect_project_root', lambda: project_dir)
    assert cmd_voice.main(argv) == 1
    assert why in capsys.readouterr().out


def test_a_dry_run_round_spends_nothing(project_dir, monkeypatch, capsys):
    from storyforge import api, cmd_voice, common
    monkeypatch.setattr(common, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: pytest.fail('spent'))
    assert cmd_voice.main(['sample', '--scene', SCENE, '--dry-run']) == 0
    assert 'Round 1: act1-sc01, 5 versions' in capsys.readouterr().out


def test_promote_dry_run_writes_nothing(project_dir):
    path = os.path.join(project_dir, vs.round_rel(1))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(ROUND)
    rel = vs.promote(project_dir, vs.round_rel(1), 'A', 'gate-run', dry_run=True)
    assert not os.path.exists(os.path.join(project_dir, rel))


def test_from_pr_must_hold_the_latest_round(project_dir, monkeypatch, capsys):
    from storyforge import cmd_voice, common
    monkeypatch.setattr(common, 'detect_project_root', lambda: project_dir)
    path = os.path.join(project_dir, vs.round_rel(1))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(ROUND)
    monkeypatch.setattr(pr_marks, 'files', lambda pr, d: ['working/voice-samples/round-9.md'])
    monkeypatch.setattr(pr_marks, 'fetch', lambda pr, d: pytest.fail('read the wrong PR'))
    assert cmd_voice.main(['sample', '--from-pr', '7']) == 1
    assert "doesn't change working/voice-samples/round-1.md" in capsys.readouterr().out
