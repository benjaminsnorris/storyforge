import csv, os


def _write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(header) + '\n')
        for row in rows:
            f.write('|'.join(str(v) for v in row) + '\n')


def test_diagnosis_has_root_cause_column(tmp_path):
    from storyforge.scoring import generate_diagnosis
    scores_dir = str(tmp_path / 'cycle')
    os.makedirs(scores_dir)
    _write_csv(os.path.join(scores_dir, 'scene-scores.csv'),
               ['id', 'prose_naturalness'], [['scene-a', '2'], ['scene-b', '4']])
    weights_file = str(tmp_path / 'weights.csv')
    _write_csv(weights_file, ['principle', 'weight'], [['prose_naturalness', '5']])
    generate_diagnosis(scores_dir, '', weights_file)
    with open(os.path.join(scores_dir, 'diagnosis.csv')) as f:
        reader = csv.DictReader(f, delimiter='|')
        rows = list(reader)
    assert len(rows) > 0
    assert 'root_cause' in rows[0]


def test_root_cause_defaults_to_craft(tmp_path):
    from storyforge.scoring import generate_diagnosis
    scores_dir = str(tmp_path / 'cycle')
    os.makedirs(scores_dir)
    _write_csv(os.path.join(scores_dir, 'scene-scores.csv'),
               ['id', 'prose_naturalness'], [['scene-a', '2']])
    weights_file = str(tmp_path / 'weights.csv')
    _write_csv(weights_file, ['principle', 'weight'], [['prose_naturalness', '5']])
    generate_diagnosis(scores_dir, '', weights_file)
    with open(os.path.join(scores_dir, 'diagnosis.csv')) as f:
        reader = csv.DictReader(f, delimiter='|')
        rows = list(reader)
    for row in rows:
        assert row.get('root_cause') == 'craft'
