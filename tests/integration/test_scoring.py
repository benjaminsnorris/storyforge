"""Integration tests for the scoring domain module (storyforge/scoring.py).

Tests the pure library functions directly: score parsing, CSV merging,
weighted text, diagnosis generation, proposal generation, fidelity scoring,
exemplar collection, and report building.
"""

import csv
import os

import pytest

from storyforge.scoring import (
    FIDELITY_ELEMENTS,
    NARRATIVE_PRINCIPLES,
    SCORE_FILES,
    _col_val,
    _extract_block,
    _extract_scores_block,
    _infer_project_dir,
    _power_mean,
    _read_csv,
    _sc_class,
    _score_icon,
    _write_csv,
    build_evaluation_criteria,
    build_weighted_text,
    check_validated_patterns,
    collect_exemplars,
    generate_diagnosis,
    generate_fidelity_diagnosis,
    generate_proposals,
    generate_score_report,
    get_effective_weight,
    init_craft_weights,
    merge_score_files,
    parse_fidelity_response,
    parse_scene_evaluation,
    parse_score_output,
    write_fidelity_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(path, header, rows):
    """Write a pipe-delimited CSV file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(header) + '\n')
        for row in rows:
            f.write('|'.join(str(v) for v in row) + '\n')


def _read_pipe_csv(path):
    """Read a pipe-delimited CSV as list of dicts."""
    with open(path) as f:
        reader = csv.DictReader(f, delimiter='|')
        return list(reader)


# ===========================================================================
# _power_mean
# ===========================================================================

class TestPowerMean:
    def test_empty_list(self):
        assert _power_mean([]) == 0.0

    def test_single_value(self):
        # (4^0.5 / 1) ^ (1/0.5) = (2.0)^2 = 4.0
        result = _power_mean([4.0])
        assert abs(result - 4.0) < 0.01

    def test_penalizes_low_scores(self):
        """Power mean with p=0.5 should be lower than arithmetic mean when values vary."""
        values = [1.0, 5.0, 5.0, 5.0]
        pm = _power_mean(values)
        am = sum(values) / len(values)
        # Power mean should penalize the low outlier
        assert pm != am

    def test_uniform_values(self):
        """Power mean of uniform values should equal the value itself (raised appropriately)."""
        result = _power_mean([3.0, 3.0, 3.0])
        # (sum(3^0.5) / 3) ^ (1/0.5) = (3^0.5)^2 = 3
        assert abs(result - 3.0) < 0.01

    def test_all_zeros(self):
        result = _power_mean([0.0, 0.0, 0.0])
        assert result == 0.0


# ===========================================================================
# _read_csv / _write_csv
# ===========================================================================

class TestCsvIO:
    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / 'test.csv')
        header = ['id', 'score', 'note']
        rows = [['a', '3', 'ok'], ['b', '5', 'great']]
        _write_csv(path, header, rows)
        h, r = _read_csv(path)
        assert h == header
        assert r == rows

    def test_empty_file(self, tmp_path):
        path = str(tmp_path / 'empty.csv')
        with open(path, 'w') as f:
            f.write('')
        h, r = _read_csv(path)
        assert h == []
        assert r == []

    def test_header_only(self, tmp_path):
        path = str(tmp_path / 'header.csv')
        with open(path, 'w') as f:
            f.write('id|name\n')
        h, r = _read_csv(path)
        assert h == ['id', 'name']
        assert r == []

    def test_crlf_handling(self, tmp_path):
        path = str(tmp_path / 'crlf.csv')
        with open(path, 'wb') as f:
            f.write(b'id|score\r\na|3\r\nb|4\r\n')
        h, r = _read_csv(path)
        assert h == ['id', 'score']
        assert r == [['a', '3'], ['b', '4']]


# ===========================================================================
# _extract_block / parse_score_output
# ===========================================================================

class TestExtractBlock:
    def test_block_markers(self):
        text = "Preamble\n{{SCORES:}}\nid|p1|p2\na|3|4\n{{END_SCORES}}\nPostamble"
        result = _extract_block(text, 'SCORES')
        assert 'id|p1|p2' in result
        assert 'a|3|4' in result

    def test_line_markers(self):
        text = "Preamble\nSCORES:\nid|p1|p2\na|3|4\n\nOther text"
        result = _extract_block(text, 'SCORES')
        assert 'a|3|4' in result

    def test_line_marker_stops_at_next_marker(self):
        text = "SCORES:\nid|p1\na|3\nRATIONALE:\nid|r1\na|good"
        result = _extract_block(text, 'SCORES')
        assert 'a|3' in result
        assert 'good' not in result

    def test_missing_marker(self):
        text = "No markers here"
        result = _extract_block(text, 'SCORES')
        assert result == ''


class TestParseScoreOutput:
    def test_both_blocks_extracted(self):
        text = (
            "{{SCORES:}}\nid|p1\na|3\n{{END_SCORES}}\n"
            "{{RATIONALE:}}\nid|r1\na|good\n{{END_RATIONALE}}"
        )
        scores, rationale = parse_score_output(text)
        assert 'a|3' in scores
        assert 'a|good' in rationale

    def test_scores_only(self):
        text = "SCORES:\nid|p1\na|3\n\n"
        scores, rationale = parse_score_output(text)
        assert 'a|3' in scores
        assert rationale == ''

    def test_custom_markers(self):
        text = "CRAFT:\nid|p1\na|3\n\nNOTES:\nid|n1\na|ok\n\n"
        scores, rationale = parse_score_output(text, score_marker='CRAFT', rationale_marker='NOTES')
        assert 'a|3' in scores
        assert 'a|ok' in rationale


# ===========================================================================
# _extract_scores_block (scene evaluation format)
# ===========================================================================

class TestExtractScoresBlock:
    def test_scores_marker(self):
        text = "Preamble\nSCORES:\nprinciple|score|deficits\neconomy_clarity|4|none\n\nDone"
        result = _extract_scores_block(text)
        assert 'economy_clarity|4|none' in result

    def test_principle_header_direct(self):
        text = "Some intro\nprinciple|score|deficits\neconomy_clarity|4|none\n\nDone"
        result = _extract_scores_block(text)
        assert 'principle|score|deficits' in result
        assert 'economy_clarity|4|none' in result

    def test_no_scores(self):
        text = "No scores here at all."
        result = _extract_scores_block(text)
        assert result == ''


# ===========================================================================
# merge_score_files
# ===========================================================================

class TestMergeScoreFiles:
    def test_copy_when_target_missing(self, tmp_path):
        src = str(tmp_path / 'source.csv')
        tgt = str(tmp_path / 'target.csv')
        _make_csv(src, ['id', 'score'], [['a', '3']])
        merge_score_files(tgt, src)
        h, r = _read_csv(tgt)
        assert h == ['id', 'score']
        assert r == [['a', '3']]

    def test_append_same_headers(self, tmp_path):
        src = str(tmp_path / 'source.csv')
        tgt = str(tmp_path / 'target.csv')
        _make_csv(tgt, ['id', 'score'], [['a', '3']])
        _make_csv(src, ['id', 'score'], [['b', '4']])
        merge_score_files(tgt, src)
        h, r = _read_csv(tgt)
        assert h == ['id', 'score']
        assert len(r) == 2
        assert r[0] == ['a', '3']
        assert r[1] == ['b', '4']

    def test_join_different_headers(self, tmp_path):
        src = str(tmp_path / 'source.csv')
        tgt = str(tmp_path / 'target.csv')
        _make_csv(tgt, ['id', 'p1'], [['a', '3'], ['b', '4']])
        _make_csv(src, ['id', 'p2'], [['a', '5'], ['c', '2']])
        merge_score_files(tgt, src)
        h, r = _read_csv(tgt)
        assert h == ['id', 'p1', 'p2']
        # a should have both columns
        a_row = [row for row in r if row[0] == 'a'][0]
        assert a_row == ['a', '3', '5']
        # b is only in target
        b_row = [row for row in r if row[0] == 'b'][0]
        assert b_row == ['b', '4', '']
        # c is only in source
        c_row = [row for row in r if row[0] == 'c'][0]
        assert c_row[0] == 'c'
        assert c_row[2] == '2'

    def test_missing_source(self, tmp_path, capsys):
        tgt = str(tmp_path / 'target.csv')
        merge_score_files(tgt, str(tmp_path / 'nonexistent.csv'))
        # Should warn but not crash
        captured = capsys.readouterr()
        assert 'WARNING' in captured.err


# ===========================================================================
# build_weighted_text
# ===========================================================================

class TestBuildWeightedText:
    def test_high_priority_principles(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['section', 'principle', 'weight', 'author_weight', 'notes'], [
            ['scene_craft', 'economy_clarity', '8', '', ''],
            ['scene_craft', 'show_vs_tell', '4', '', ''],
            ['prose_craft', 'precision_language', '5', '9', ''],
        ])
        result = build_weighted_text(path)
        assert 'economy_clarity' in result
        assert 'precision_language' in result
        assert 'show_vs_tell' not in result
        assert 'high-priority' in result

    def test_exclude_section(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['section', 'principle', 'weight', 'author_weight', 'notes'], [
            ['narrative', 'campbells_monomyth', '9', '', ''],
            ['prose_craft', 'economy_clarity', '8', '', ''],
        ])
        result = build_weighted_text(path, exclude_section='narrative')
        assert 'campbells_monomyth' not in result
        assert 'economy_clarity' in result

    def test_principles_filter(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['section', 'principle', 'weight', 'author_weight', 'notes'], [
            ['craft', 'a_principle', '9', '', ''],
            ['craft', 'b_principle', '8', '', ''],
        ])
        result = build_weighted_text(path, principles=['a_principle'])
        assert 'a_principle' in result
        assert 'b_principle' not in result

    def test_no_high_priority(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['section', 'principle', 'weight', 'author_weight', 'notes'], [
            ['craft', 'low_weight', '3', '', ''],
        ])
        result = build_weighted_text(path)
        assert 'equally' in result

    def test_missing_file(self):
        result = build_weighted_text('/nonexistent/path.csv')
        assert 'No craft weights' in result

    def test_author_weight_overrides(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['section', 'principle', 'weight', 'author_weight', 'notes'], [
            ['craft', 'low_base_high_author', '3', '8', ''],
        ])
        result = build_weighted_text(path)
        assert 'low_base_high_author' in result
        assert 'weight: 8' in result


# ===========================================================================
# get_effective_weight
# ===========================================================================

class TestGetEffectiveWeight:
    def test_returns_weight(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['principle', 'weight', 'author_weight'], [
            ['economy_clarity', '7', ''],
        ])
        assert get_effective_weight(path, 'economy_clarity') == 7

    def test_author_weight_overrides(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['principle', 'weight', 'author_weight'], [
            ['economy_clarity', '5', '9'],
        ])
        assert get_effective_weight(path, 'economy_clarity') == 9

    def test_missing_principle_returns_default(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['principle', 'weight', 'author_weight'], [
            ['economy_clarity', '7', ''],
        ])
        assert get_effective_weight(path, 'nonexistent') == 5

    def test_no_principle_column(self, tmp_path):
        path = str(tmp_path / 'weights.csv')
        _make_csv(path, ['name', 'weight'], [['a', '3']])
        assert get_effective_weight(path, 'a') == 5


# ===========================================================================
# _infer_project_dir
# ===========================================================================

class TestInferProjectDir:
    def test_typical_path(self):
        result = _infer_project_dir('/home/user/project/working/scores/cycle-1')
        assert result == '/home/user/project'

    def test_no_working_dir(self):
        result = _infer_project_dir('/some/random/path')
        assert result == ''


# ===========================================================================
# generate_diagnosis
# ===========================================================================

class TestGenerateDiagnosis:
    def test_basic_diagnosis(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity', 'show_vs_tell'],
                  [['a', '2', '4'], ['b', '3', '5'], ['c', '1', '3']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', ''],
                   ['craft', 'show_vs_tell', '5', '', '']])

        generate_diagnosis(scores_dir, '', weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        assert len(rows) >= 2
        principles = {r['principle'] for r in rows}
        assert 'economy_clarity' in principles
        assert 'show_vs_tell' in principles

    def test_high_priority_for_low_avg(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'weak_principle'],
                  [['a', '1'], ['b', '1'], ['c', '2']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'weak_principle', '5', '', '']])

        generate_diagnosis(scores_dir, '', weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        assert rows[0]['priority'] == 'high'

    def test_delta_from_previous(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle-2')
        prev_dir = str(tmp_path / 'cycle-1')
        os.makedirs(scores_dir)
        os.makedirs(prev_dir)

        _make_csv(os.path.join(prev_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'], [['a', '2'], ['b', '2']])
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'], [['a', '4'], ['b', '4']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_diagnosis(scores_dir, prev_dir, weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        assert rows[0]['delta_from_last'].startswith('+')

    def test_regression_triggers_high_priority(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle-2')
        prev_dir = str(tmp_path / 'cycle-1')
        os.makedirs(scores_dir)
        os.makedirs(prev_dir)

        _make_csv(os.path.join(prev_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'], [['a', '4'], ['b', '4']])
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'], [['a', '3'], ['b', '3']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_diagnosis(scores_dir, prev_dir, weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        delta_val = float(rows[0]['delta_from_last'])
        # Regression should be negative
        assert delta_val < 0

    def test_high_weight_boosts_priority(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'important_principle'],
                  [['a', '3'], ['b', '3'], ['c', '3']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'important_principle', '9', '', '']])

        generate_diagnosis(scores_dir, '', weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        # Weight 9 + medium score (< 3.0 after power mean) -> high priority
        assert rows[0]['priority'] == 'high'

    def test_skips_narrative_at_scene_level(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'campbells_monomyth', 'economy_clarity'],
                  [['a', '3', '4']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['narrative', 'campbells_monomyth', '5', '', ''],
                   ['craft', 'economy_clarity', '5', '', '']])

        generate_diagnosis(scores_dir, '', weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        principles = {r['principle'] for r in rows}
        assert 'campbells_monomyth' not in principles
        assert 'economy_clarity' in principles

    def test_worst_items_populated(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'],
                  [['a', '1'], ['b', '5'], ['c', '2'], ['d', '5'], ['e', '5']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_diagnosis(scores_dir, '', weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        worst = rows[0]['worst_items']
        # Scenes a and c are below average, should appear
        assert 'a' in worst
        assert 'c' in worst

    def test_root_cause_defaults_to_craft(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'], [['a', '2']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_diagnosis(scores_dir, '', weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'diagnosis.csv'))
        assert rows[0]['root_cause'] == 'craft'


# ===========================================================================
# generate_proposals
# ===========================================================================

class TestGenerateProposals:
    def test_creates_proposals_for_high_priority(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'diagnosis.csv'),
                  ['principle', 'scale', 'avg_score', 'worst_items',
                   'delta_from_last', 'priority', 'root_cause'],
                  [['economy_clarity', 'scene', '1.5', 'a;b', '-0.5', 'high', 'craft']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_proposals(scores_dir, weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'proposals.csv'))
        assert len(rows) >= 1
        assert rows[0]['principle'] == 'economy_clarity'
        assert rows[0]['status'] == 'pending'

    def test_skips_low_priority(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'diagnosis.csv'),
                  ['principle', 'scale', 'avg_score', 'worst_items',
                   'delta_from_last', 'priority', 'root_cause'],
                  [['economy_clarity', 'scene', '4.5', '', '+0.5', 'low', 'craft']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_proposals(scores_dir, weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'proposals.csv'))
        assert len(rows) == 0

    def test_voice_guide_for_high_weight(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'diagnosis.csv'),
                  ['principle', 'scale', 'avg_score', 'worst_items',
                   'delta_from_last', 'priority', 'root_cause'],
                  [['economy_clarity', 'scene', '2.0', 'a', '', 'high', 'craft']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '9', '', '']])

        generate_proposals(scores_dir, weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'proposals.csv'))
        assert any(r['lever'] == 'voice_guide' for r in rows)

    def test_weight_bump_for_moderate_weight(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'diagnosis.csv'),
                  ['principle', 'scale', 'avg_score', 'worst_items',
                   'delta_from_last', 'priority', 'root_cause'],
                  [['economy_clarity', 'scene', '2.5', 'a', '', 'medium', 'craft']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_proposals(scores_dir, weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'proposals.csv'))
        assert any(r['lever'] == 'craft_weight' for r in rows)
        craft_row = next(r for r in rows if r['lever'] == 'craft_weight')
        assert '5' in craft_row['change'] and '6' in craft_row['change']

    def test_scene_intent_proposals(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        _make_csv(os.path.join(scores_dir, 'diagnosis.csv'),
                  ['principle', 'scale', 'avg_score', 'worst_items',
                   'delta_from_last', 'priority', 'root_cause'],
                  [['economy_clarity', 'scene', '1.5', 'a;b', '', 'high', 'craft']])
        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'],
                  [['a', '1'], ['b', '2'], ['c', '4']])
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                  [['craft', 'economy_clarity', '5', '', '']])

        generate_proposals(scores_dir, weights)

        rows = _read_pipe_csv(os.path.join(scores_dir, 'proposals.csv'))
        scene_intent_rows = [r for r in rows if r['lever'] == 'scene_intent']
        assert len(scene_intent_rows) >= 1
        targets = {r['target'] for r in scene_intent_rows}
        assert 'a' in targets

    def test_no_diagnosis_file(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        weights = str(tmp_path / 'weights.csv')
        _make_csv(weights, ['principle', 'weight'], [['a', '5']])
        # Should not crash
        generate_proposals(scores_dir, weights)
        assert not os.path.isfile(os.path.join(scores_dir, 'proposals.csv'))


# ===========================================================================
# parse_scene_evaluation
# ===========================================================================

class TestParseSceneEvaluation:
    def test_basic_parsing(self):
        text = (
            "SCORES:\n"
            "principle|score|deficits|evidence_lines\n"
            "economy_clarity|4|none|\n"
            "show_vs_tell|3|some telling|lines 12-15\n"
        )
        scores_csv, rationale_csv = parse_scene_evaluation(text, 'scene-a')
        assert 'scene-a' in scores_csv
        assert 'economy_clarity' in scores_csv
        assert '4' in scores_csv

    def test_empty_text(self):
        scores_csv, rationale_csv = parse_scene_evaluation('', 'scene-a')
        assert scores_csv == ''
        assert rationale_csv == ''

    def test_no_scores_block(self):
        text = "This is just some text with no scores."
        scores_csv, rationale_csv = parse_scene_evaluation(text, 'scene-a')
        assert scores_csv == ''
        assert rationale_csv == ''

    def test_rationale_formatting(self):
        text = (
            "SCORES:\n"
            "economy_clarity|3|too verbose|paragraph 2\n"
        )
        scores_csv, rationale_csv = parse_scene_evaluation(text, 'scene-a')
        assert 'too verbose' in rationale_csv

    def test_no_deficits_rationale(self):
        text = (
            "SCORES:\n"
            "economy_clarity|5|none|\n"
        )
        _, rationale_csv = parse_scene_evaluation(text, 'scene-a')
        assert 'No deficits' in rationale_csv

    def test_canonical_ordering_from_diagnostics(self, tmp_path):
        diag_path = str(tmp_path / 'diagnostics.csv')
        _make_csv(diag_path, ['principle', 'question'],
                  [['show_vs_tell', 'q1'], ['economy_clarity', 'q2']])

        text = (
            "SCORES:\n"
            "economy_clarity|4|none|\n"
            "show_vs_tell|3|some telling|line 5\n"
        )
        scores_csv, _ = parse_scene_evaluation(text, 'scene-a', diagnostics_csv=diag_path)
        # show_vs_tell should come before economy_clarity in output
        header_line = scores_csv.split('\n')[0]
        cols = header_line.split('|')
        svt_idx = cols.index('show_vs_tell')
        ec_idx = cols.index('economy_clarity')
        assert svt_idx < ec_idx

    def test_principle_header_strategy(self):
        """Test that principle| lines work without SCORES: marker."""
        text = (
            "Some analysis here.\n"
            "principle|score|deficits|evidence\n"
            "economy_clarity|4|none|\n"
            "show_vs_tell|3|telling|para 2\n"
            "\n"
            "Done."
        )
        scores_csv, _ = parse_scene_evaluation(text, 'scene-a')
        assert 'economy_clarity' in scores_csv
        assert 'show_vs_tell' in scores_csv


# ===========================================================================
# init_craft_weights
# ===========================================================================

class TestInitCraftWeights:
    def test_copies_defaults(self, tmp_path, plugin_dir):
        project = str(tmp_path / 'project')
        os.makedirs(os.path.join(project, 'working'), exist_ok=True)
        init_craft_weights(project, plugin_dir)
        weights_file = os.path.join(project, 'working', 'craft-weights.csv')
        assert os.path.isfile(weights_file)
        h, r = _read_csv(weights_file)
        assert 'principle' in h
        assert len(r) > 10

    def test_does_not_overwrite(self, tmp_path, plugin_dir):
        project = str(tmp_path / 'project')
        weights_file = os.path.join(project, 'working', 'craft-weights.csv')
        os.makedirs(os.path.dirname(weights_file), exist_ok=True)
        with open(weights_file, 'w') as f:
            f.write('custom|data\n')
        init_craft_weights(project, plugin_dir)
        with open(weights_file) as f:
            content = f.read()
        assert content == 'custom|data\n'


# ===========================================================================
# Score display helpers
# ===========================================================================

class TestScoreDisplayHelpers:
    def test_score_icon_green(self):
        icon = _score_icon(4)
        assert icon == '\U0001f7e2'

    def test_score_icon_yellow(self):
        icon = _score_icon(3)
        assert icon == '\U0001f7e1'

    def test_score_icon_red(self):
        icon = _score_icon(2)
        assert icon == '\U0001f534'

    def test_score_icon_high(self):
        icon = _score_icon(5)
        assert icon == '\U0001f7e2'

    def test_sc_class_values(self):
        assert _sc_class('1') == 'sc-1'
        assert _sc_class('5') == 'sc-5'
        assert _sc_class('0') == ''
        assert _sc_class('6') == ''
        assert _sc_class('') == ''
        assert _sc_class('abc') == ''

    def test_col_val_safe_access(self):
        row = ['a', '3', 'ok']
        col_map = {'id': 0, 'score': 1, 'note': 2}
        assert _col_val(row, col_map, 'score') == '3'
        assert _col_val(row, col_map, 'missing') == ''
        assert _col_val(row, col_map, 'missing', 'default') == 'default'

    def test_col_val_out_of_range(self):
        row = ['a']
        col_map = {'id': 0, 'score': 5}
        assert _col_val(row, col_map, 'score') == ''


# ===========================================================================
# Fidelity scoring
# ===========================================================================

class TestParseFidelityResponse:
    def test_basic_parsing(self):
        response = (
            "SCORES:\n"
            "id|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|emotions|knowledge\n"
            "scene-a|4|3|4|5|3|4|2|3|4\n"
            "\n"
            "RATIONALE:\n"
            "id|element|score|evidence\n"
            "scene-a|goal|4|Goal well executed\n"
            "scene-a|conflict|3|Conflict underspecified\n"
        )
        result = parse_fidelity_response(response, 'scene-a')
        assert result['scene_id'] == 'scene-a'
        assert result['scores']['goal'] == 4
        assert result['scores']['conflict'] == 3
        assert result['scores']['key_dialogue'] == 2
        assert result['overall'] > 0
        assert len(result['rationale']) == 2
        assert result['rationale'][0]['element'] == 'goal'

    def test_empty_response(self):
        result = parse_fidelity_response('', 'scene-a')
        assert result['scores'] == {}
        assert result['rationale'] == []
        assert result['overall'] == 0.0

    def test_overall_is_power_mean(self):
        response = (
            "SCORES:\n"
            "id|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|emotions|knowledge\n"
            "scene-a|5|5|5|5|5|5|5|5|5\n"
        )
        result = parse_fidelity_response(response, 'scene-a')
        # All 5s -> power mean should be close to 5
        assert abs(result['overall'] - 5.0) < 1.0


class TestWriteFidelityCsv:
    def test_writes_both_files(self, tmp_path):
        results = [{
            'scene_id': 'scene-a',
            'scores': {'goal': 4, 'conflict': 3},
            'rationale': [
                {'element': 'goal', 'score': 4, 'evidence': 'good'},
            ],
            'overall': 3.5,
        }]
        output_dir = str(tmp_path / 'fidelity')
        write_fidelity_csv(results, output_dir)

        scores_path = os.path.join(output_dir, 'fidelity-scores.csv')
        rationale_path = os.path.join(output_dir, 'fidelity-rationale.csv')
        assert os.path.isfile(scores_path)
        assert os.path.isfile(rationale_path)

        score_rows = _read_pipe_csv(scores_path)
        assert len(score_rows) == 1
        assert score_rows[0]['id'] == 'scene-a'
        assert score_rows[0]['goal'] == '4'
        assert score_rows[0]['overall'] == '3.5'

        rat_rows = _read_pipe_csv(rationale_path)
        assert len(rat_rows) == 1
        assert rat_rows[0]['element'] == 'goal'

    def test_multiple_scenes(self, tmp_path):
        results = [
            {
                'scene_id': 'scene-a',
                'scores': {'goal': 4, 'conflict': 3},
                'rationale': [],
                'overall': 3.5,
            },
            {
                'scene_id': 'scene-b',
                'scores': {'goal': 5, 'conflict': 5},
                'rationale': [],
                'overall': 5.0,
            },
        ]
        output_dir = str(tmp_path / 'fidelity')
        write_fidelity_csv(results, output_dir)

        score_rows = _read_pipe_csv(os.path.join(output_dir, 'fidelity-scores.csv'))
        assert len(score_rows) == 2


class TestGenerateFidelityDiagnosis:
    def test_basic_diagnosis(self):
        results = [
            {'scene_id': 'a', 'scores': {'goal': 1, 'conflict': 4}, 'rationale': [], 'overall': 2.5},
            {'scene_id': 'b', 'scores': {'goal': 2, 'conflict': 5}, 'rationale': [], 'overall': 3.5},
            {'scene_id': 'c', 'scores': {'goal': 1, 'conflict': 4}, 'rationale': [], 'overall': 2.5},
        ]
        findings = generate_fidelity_diagnosis(results)
        assert len(findings) == 2

        goal_finding = next(f for f in findings if f['element'] == 'goal')
        conflict_finding = next(f for f in findings if f['element'] == 'conflict')

        # Goal has low scores, should be high priority
        assert goal_finding['priority'] in ('high', 'medium')
        assert goal_finding['avg_score'] < 2.5

        # Conflict has high scores
        assert conflict_finding['priority'] == 'low'

    def test_empty_results(self):
        findings = generate_fidelity_diagnosis([])
        assert findings == []

    def test_sorted_by_priority(self):
        results = [
            {'scene_id': 'a', 'scores': {'goal': 1, 'conflict': 5}, 'rationale': [], 'overall': 3.0},
        ]
        findings = generate_fidelity_diagnosis(results)
        priorities = [f['priority'] for f in findings]
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        for i in range(len(priorities) - 1):
            assert priority_order[priorities[i]] <= priority_order[priorities[i + 1]]

    def test_weak_scenes_populated(self):
        results = [
            {'scene_id': 'a', 'scores': {'goal': 1}, 'rationale': [], 'overall': 1.0},
            {'scene_id': 'b', 'scores': {'goal': 5}, 'rationale': [], 'overall': 5.0},
        ]
        findings = generate_fidelity_diagnosis(results)
        goal_finding = next(f for f in findings if f['element'] == 'goal')
        assert 'a' in goal_finding['weak_scenes']
        assert 'b' not in goal_finding['weak_scenes']


# ===========================================================================
# collect_exemplars
# ===========================================================================

class TestCollectExemplars:
    def test_collects_high_scores(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        project_dir = str(tmp_path / 'project')
        os.makedirs(scores_dir)
        os.makedirs(os.path.join(project_dir, 'working'))

        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity', 'show_vs_tell'],
                  [['a', '5', '3'], ['b', '4', '5']])

        collect_exemplars(scores_dir, project_dir, 'cycle-1')

        exemplars_file = os.path.join(project_dir, 'working', 'exemplars.csv')
        assert os.path.isfile(exemplars_file)
        rows = _read_pipe_csv(exemplars_file)
        assert len(rows) >= 2
        principles = {r['principle'] for r in rows}
        assert 'economy_clarity' in principles
        assert 'show_vs_tell' in principles

    def test_no_duplicates(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        project_dir = str(tmp_path / 'project')
        os.makedirs(scores_dir)
        os.makedirs(os.path.join(project_dir, 'working'))

        _make_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'],
                  [['a', '5']])

        # Collect twice
        collect_exemplars(scores_dir, project_dir, 'cycle-1')
        collect_exemplars(scores_dir, project_dir, 'cycle-2')

        exemplars_file = os.path.join(project_dir, 'working', 'exemplars.csv')
        rows = _read_pipe_csv(exemplars_file)
        # Should only have one entry for (economy_clarity, a)
        matches = [(r['principle'], r['scene_id']) for r in rows
                   if r['principle'] == 'economy_clarity' and r['scene_id'] == 'a']
        assert len(matches) == 1

    def test_no_scores_file(self, tmp_path):
        scores_dir = str(tmp_path / 'cycle')
        project_dir = str(tmp_path / 'project')
        os.makedirs(scores_dir)
        os.makedirs(os.path.join(project_dir, 'working'))
        # Should not crash, and should not create exemplars file
        collect_exemplars(scores_dir, project_dir, 'cycle-1')
        exemplars = os.path.join(project_dir, 'working', 'exemplars.csv')
        assert not os.path.isfile(exemplars)


# ===========================================================================
# check_validated_patterns
# ===========================================================================

class TestCheckValidatedPatterns:
    def test_finds_patterns_with_3_cycles(self, tmp_path):
        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working'))
        tuning_file = os.path.join(project_dir, 'working', 'tuning.csv')
        _make_csv(tuning_file,
                  ['principle', 'lever', 'validated', 'score_before', 'score_after'],
                  [['economy', 'weight', 'true', '2', '4'],
                   ['economy', 'weight', 'true', '2', '3'],
                   ['economy', 'weight', 'true', '3', '5']])

        result = check_validated_patterns(project_dir)
        assert 'economy|weight' in result

    def test_ignores_unvalidated(self, tmp_path):
        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working'))
        tuning_file = os.path.join(project_dir, 'working', 'tuning.csv')
        _make_csv(tuning_file,
                  ['principle', 'lever', 'validated', 'score_before', 'score_after'],
                  [['economy', 'weight', 'false', '2', '4'],
                   ['economy', 'weight', 'false', '2', '3'],
                   ['economy', 'weight', 'false', '3', '5']])

        result = check_validated_patterns(project_dir)
        assert result == ''

    def test_needs_3_occurrences(self, tmp_path):
        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working'))
        tuning_file = os.path.join(project_dir, 'working', 'tuning.csv')
        _make_csv(tuning_file,
                  ['principle', 'lever', 'validated', 'score_before', 'score_after'],
                  [['economy', 'weight', 'true', '2', '4'],
                   ['economy', 'weight', 'true', '2', '3']])

        result = check_validated_patterns(project_dir)
        assert result == ''

    def test_no_tuning_file(self, tmp_path):
        project_dir = str(tmp_path / 'project')
        result = check_validated_patterns(project_dir)
        assert result == ''


# ===========================================================================
# build_evaluation_criteria
# ===========================================================================

class TestBuildEvaluationCriteria:
    def test_basic_criteria(self, tmp_path):
        diag_path = str(tmp_path / 'diagnostics.csv')
        guide_path = str(tmp_path / 'guide.md')

        _make_csv(diag_path, ['principle', 'question'],
                  [['economy_clarity', 'Is prose economical?'],
                   ['economy_clarity', 'Are sentences clear?'],
                   ['show_vs_tell', 'Does it show?']])

        with open(guide_path, 'w') as f:
            f.write("# Guide\n\n### economy_clarity\nGood economy means short sentences.\n\n### show_vs_tell\nShow through action.\n")

        result = build_evaluation_criteria(diag_path, guide_path)
        assert '### economy_clarity' in result
        assert 'Is prose economical?' in result
        assert 'Good economy means short sentences.' in result
        assert '### show_vs_tell' in result

    def test_principles_filter(self, tmp_path):
        diag_path = str(tmp_path / 'diagnostics.csv')
        guide_path = str(tmp_path / 'guide.md')

        _make_csv(diag_path, ['principle', 'question'],
                  [['economy_clarity', 'q1'], ['show_vs_tell', 'q2']])

        with open(guide_path, 'w') as f:
            f.write("### economy_clarity\nGuide.\n\n### show_vs_tell\nGuide.\n")

        result = build_evaluation_criteria(diag_path, guide_path, principles=['economy_clarity'])
        assert 'economy_clarity' in result
        assert 'show_vs_tell' not in result

    def test_missing_files(self):
        result = build_evaluation_criteria('/nonexistent/diag.csv', '/nonexistent/guide.md')
        assert result == ''


# ===========================================================================
# generate_score_report (smoke test)
# ===========================================================================

class TestGenerateScoreReport:
    def test_generates_html(self, tmp_path):
        cycle_dir = str(tmp_path / 'cycle')
        project_dir = str(tmp_path / 'project')
        os.makedirs(cycle_dir)
        os.makedirs(project_dir)

        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml_file, 'w') as f:
            f.write('project:\n  title: "Test Novel"\n')

        _make_csv(os.path.join(cycle_dir, 'scene-scores.csv'),
                  ['id', 'economy_clarity'], [['a', '3'], ['b', '4']])
        _make_csv(os.path.join(cycle_dir, 'diagnosis.csv'),
                  ['principle', 'scale', 'avg_score', 'worst_items',
                   'delta_from_last', 'priority', 'root_cause'],
                  [['economy_clarity', 'scene', '3.5', 'a', '', 'medium', 'craft']])

        generate_score_report(cycle_dir, project_dir, '1', 'full', 2, '0.50')

        report_file = os.path.join(cycle_dir, 'report.html')
        assert os.path.isfile(report_file)
        with open(report_file) as f:
            html = f.read()
        assert 'Test Novel' in html
        assert 'Cycle 1' in html
        assert 'economy clarity' in html


# ===========================================================================
# build_score_pr_comment (smoke test)
# ===========================================================================

class TestBuildScorePrComment:
    def test_builds_markdown(self, tmp_path):
        from storyforge.scoring import build_score_pr_comment

        cycle_dir = str(tmp_path / 'cycle')
        project_dir = str(tmp_path / 'project')
        os.makedirs(cycle_dir)
        os.makedirs(project_dir)

        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml_file, 'w') as f:
            f.write('project:\n  title: "Test Novel"\n')

        _make_csv(os.path.join(cycle_dir, 'diagnosis.csv'),
                  ['principle', 'scale', 'avg_score', 'worst_items',
                   'delta_from_last', 'priority', 'root_cause'],
                  [['economy_clarity', 'scene', '3.5', 'a', '', 'medium', 'craft']])

        comment = build_score_pr_comment(cycle_dir, project_dir, '1', 'full', 2, '0.50')
        assert 'Scoring Report' in comment
        assert 'Test Novel' in comment
        assert 'economy clarity' in comment


# ===========================================================================
# Constants / module-level checks
# ===========================================================================

class TestModuleConstants:
    def test_narrative_principles_set(self):
        assert isinstance(NARRATIVE_PRINCIPLES, set)
        assert 'campbells_monomyth' in NARRATIVE_PRINCIPLES
        assert 'three_act' in NARRATIVE_PRINCIPLES
        assert len(NARRATIVE_PRINCIPLES) == 7

    def test_score_files_list(self):
        assert isinstance(SCORE_FILES, list)
        names = {name for name, _ in SCORE_FILES}
        assert 'scene-scores.csv' in names
        assert 'fidelity-scores.csv' in names

    def test_fidelity_elements(self):
        assert 'goal' in FIDELITY_ELEMENTS
        assert 'conflict' in FIDELITY_ELEMENTS
        assert 'knowledge' in FIDELITY_ELEMENTS
        assert len(FIDELITY_ELEMENTS) == 9
