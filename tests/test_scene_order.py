"""The reading order: `ledger.seq_number` (the one seq conversion),
`ledger.scene_order`, and what validate makes of the same seqs (#495)."""

import os

import pytest

from storyforge import ledger


def _scenes_path(project_dir):
    return os.path.join(project_dir, 'reference', 'scenes.csv')


def _set_seqs(project_dir, seqs: dict[str, str]):
    """Rewrite scenes.csv with `seqs` (id → seq cell) applied, as raw text."""
    path = _scenes_path(project_dir)
    with open(path) as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    i, j = header.index('id'), header.index('seq')
    out = [lines[0]]
    for line in lines[1:]:
        cells = line.split('|')
        if cells[i] in seqs:
            cells[j] = seqs[cells[i]]
        out.append('|'.join(cells))
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')


class TestSeqNumber:
    @pytest.mark.parametrize('text,value', [('4', 4.0), (' 4.0 ', 4.0), ('12.5', 12.5)])
    def test_numbers(self, text, value):
        assert ledger.seq_number(text) == value

    @pytest.mark.parametrize('text', ['', '  ', 'first', 'nan', 'NaN', 'inf', '-inf',
                                      'Infinity', None])
    def test_not_a_finite_number_raises(self, text):
        with pytest.raises(ValueError):
            ledger.seq_number(text)


class TestSceneOrder:
    def test_a_nan_seq_is_not_a_number(self, project_dir):
        """float('nan') passed, and a nan sorts nowhere in particular."""
        _set_seqs(project_dir, {'act1-sc02': 'nan'})
        with pytest.raises(ValueError, match="act1-sc02 has no numeric seq \\('nan'\\)"):
            ledger.scene_order(project_dir)

    def test_an_infinite_seq_is_not_a_number(self, project_dir):
        _set_seqs(project_dir, {'act1-sc02': 'inf'})
        with pytest.raises(ValueError, match='act1-sc02 has no numeric seq'):
            ledger.scene_order(project_dir)

    def test_a_byte_order_mark_does_not_hide_every_scene(self, project_dir):
        """A spreadsheet export's BOM made the header `\\ufeffid`: every row
        had no id, scene_order was empty, and the missing-seq stop passed."""
        path = _scenes_path(project_dir)
        with open(path, encoding='utf-8') as f:
            text = f.read()
        expected = ledger.scene_order(project_dir)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('﻿' + text)
        assert ledger.scene_order(project_dir) == expected and expected

    def test_crlf_line_endings_read_the_same(self, project_dir):
        path = _scenes_path(project_dir)
        with open(path, encoding='utf-8') as f:
            text = f.read()
        expected = ledger.scene_order(project_dir)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write('﻿' + text.replace('\n', '\r\n'))
        assert ledger.scene_order(project_dir) == expected

    def test_decimal_seqs_sort_as_numbers(self, project_dir):
        _set_seqs(project_dir, {'act2-sc01': '2.5'})
        order = ledger.scene_order(project_dir)
        assert order['act1-sc02'] < order['act2-sc01'] < order['new-x1']


class TestValidateReadsSeqsAsNumbers:
    def test_a_4_and_4_0_tie_is_reported_not_a_crash(self, project_dir):
        """`int('4.0')` in _validate_threads threw before duplicate-seq could
        say anything."""
        from storyforge.elaborate import validate_structure
        _set_seqs(project_dir, {'act2-sc01': '4.0', 'act2-sc02': '4'})
        report = validate_structure(os.path.join(project_dir, 'reference'))
        dup = [c for c in report['checks'] if c['check'] == 'duplicate-seq']
        assert not dup[0]['passed']
        assert 'act2-sc01' in dup[0]['message'] and 'act2-sc02' in dup[0]['message']

    def test_a_decimal_seq_validates(self, project_dir):
        from storyforge.elaborate import validate_structure
        _set_seqs(project_dir, {'act2-sc01': '3.5'})
        report = validate_structure(os.path.join(project_dir, 'reference'))
        assert all(c['passed'] for c in report['checks'] if c['check'] == 'duplicate-seq')

    def test_a_blank_seq_validates_without_a_crash(self, project_dir):
        from storyforge.elaborate import validate_structure
        _set_seqs(project_dir, {'act2-sc01': ''})
        validate_structure(os.path.join(project_dir, 'reference'))
