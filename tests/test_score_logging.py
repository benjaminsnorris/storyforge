"""Tests for improvement cycle logging in cmd_score."""

import os
from unittest.mock import patch, MagicMock

from storyforge.cmd_score import _count_high_priority, _run_improvement_cycle


def test_count_high_priority_with_mixed_priorities(tmp_path):
    diag = tmp_path / 'diagnosis.csv'
    diag.write_text(
        'principle|scale|avg_score|worst_items|delta_from_last|priority|root_cause\n'
        'prose_repetition|scene|1.8|s1;s2||high|craft\n'
        'avoid_passive|scene|2.5|s3||medium|craft\n'
        'economy_clarity|scene|1.5|s1||high|craft\n'
    )
    assert _count_high_priority(str(diag)) == 2


def test_count_high_priority_no_high(tmp_path):
    diag = tmp_path / 'diagnosis.csv'
    diag.write_text(
        'principle|scale|avg_score|worst_items|delta_from_last|priority|root_cause\n'
        'avoid_passive|scene|3.5|s3||low|craft\n'
    )
    assert _count_high_priority(str(diag)) == 0


def test_count_high_priority_missing_file():
    assert _count_high_priority('/nonexistent/diagnosis.csv') == 0


def test_count_high_priority_empty_file(tmp_path):
    diag = tmp_path / 'diagnosis.csv'
    diag.write_text('')
    assert _count_high_priority(str(diag)) == 0


@patch('storyforge.scoring.check_validated_patterns', return_value='')
@patch('storyforge.scoring.collect_exemplars')
@patch('storyforge.scoring.generate_proposals')
@patch('storyforge.scoring.generate_diagnosis')
@patch('storyforge.cmd_score.get_coaching_level', return_value='full')
def test_improvement_cycle_logs_all_phases(
    mock_coaching, mock_diag, mock_proposals, mock_exemplars,
    mock_patterns, tmp_path, capsys
):
    """Verify that every phase of the improvement cycle produces log output."""
    cycle_dir = str(tmp_path / 'cycle-1')
    os.makedirs(cycle_dir)
    project_dir = str(tmp_path / 'project')
    os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)

    weights_file = str(tmp_path / 'craft-weights.csv')
    with open(weights_file, 'w') as f:
        f.write('principle|weight\nprose_repetition|5\n')

    intent_csv = str(tmp_path / 'scene-intent.csv')
    with open(intent_csv, 'w') as f:
        f.write('id|function\n')

    # generate_diagnosis writes diagnosis.csv
    def fake_diagnosis(cd, pd, wf):
        with open(os.path.join(cd, 'diagnosis.csv'), 'w') as f:
            f.write(
                'principle|scale|avg_score|worst_items|delta_from_last|priority|root_cause\n'
                'prose_repetition|scene|1.8|s1||high|craft\n'
            )
    mock_diag.side_effect = fake_diagnosis

    # generate_proposals writes proposals.csv
    def fake_proposals(cd, wf):
        with open(os.path.join(cd, 'proposals.csv'), 'w') as f:
            f.write(
                'id|principle|lever|target|change|rationale|status\n'
                'p001|prose_repetition|craft_weight|global|weight 5 → 7|avg_score 1.8, priority high|pending\n'
            )
    mock_proposals.side_effect = fake_proposals

    # Storyforge YAML for coaching level detection
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_file, 'w') as f:
        f.write('project:\n  title: Test\n  coaching_level: full\n')

    _run_improvement_cycle(
        cycle=1, cycle_dir=cycle_dir, project_dir=project_dir,
        weights_file=weights_file, plugin_dir='/fake',
        intent_csv=intent_csv, title='Test',
    )

    captured = capsys.readouterr().out
    assert 'Improvement cycle: generating diagnosis...' in captured
    assert 'Improvement cycle: diagnosis complete' in captured
    assert 'Improvement cycle: generating proposals...' in captured
    assert '1 proposals generated (1 high-priority principles)' in captured
    assert 'Improvement cycle: applying proposals...' in captured
    assert 'proposals applied' in captured
    assert 'Improvement cycle: collecting exemplars...' in captured
    assert 'Improvement cycle: exemplars collected' in captured
    assert 'Improvement cycle: complete' in captured


@patch('storyforge.scoring.generate_proposals')
@patch('storyforge.scoring.generate_diagnosis')
def test_improvement_cycle_no_proposals_logs_cleanly(
    mock_diag, mock_proposals, tmp_path, capsys
):
    """When no proposals are generated, the cycle logs and exits cleanly."""
    cycle_dir = str(tmp_path / 'cycle-1')
    os.makedirs(cycle_dir)
    project_dir = str(tmp_path / 'project')
    os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)

    weights_file = str(tmp_path / 'craft-weights.csv')
    with open(weights_file, 'w') as f:
        f.write('principle|weight\n')

    intent_csv = str(tmp_path / 'scene-intent.csv')
    with open(intent_csv, 'w') as f:
        f.write('id|function\n')

    def fake_diagnosis(cd, pd, wf):
        with open(os.path.join(cd, 'diagnosis.csv'), 'w') as f:
            f.write('principle|scale|avg_score|worst_items|delta_from_last|priority|root_cause\n')
    mock_diag.side_effect = fake_diagnosis

    # generate_proposals does NOT write a proposals file
    mock_proposals.side_effect = lambda cd, wf: None

    _run_improvement_cycle(
        cycle=1, cycle_dir=cycle_dir, project_dir=project_dir,
        weights_file=weights_file, plugin_dir='/fake',
        intent_csv=intent_csv, title='Test',
    )

    captured = capsys.readouterr().out
    assert 'Improvement cycle: generating diagnosis...' in captured
    assert 'Improvement cycle: no proposals generated' in captured
    # Should NOT reach later phases
    assert 'applying proposals' not in captured
    assert 'collecting exemplars' not in captured
