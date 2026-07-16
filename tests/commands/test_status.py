import os
from storyforge import status


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_artifact_present_prose_and_csv(tmp_path):
    pd = str(tmp_path)
    # No story-summary.md, no CSVs → nothing present.
    assert status.artifact_present(pd, 0) is False
    assert status.artifact_present(pd, 3) is False

    _write(os.path.join(pd, 'reference', 'story-summary.md'),
           "## Logline\nA mapmaker who cannot lie must chart a lie.\n\n"
           "## Synopsis\n\n## Act-shape\n\n## Theme\n")
    assert status.artifact_present(pd, 0) is True   # logline has body
    assert status.artifact_present(pd, 1) is False  # synopsis empty

    # CSV present only counts when it has a data row beyond the header.
    _write(os.path.join(pd, 'reference', 'spine.csv'), "id|seq|title\n")
    assert status.artifact_present(pd, 3) is False
    _write(os.path.join(pd, 'reference', 'spine.csv'),
           "id|seq|title\ne1|1|Opening\n")
    assert status.artifact_present(pd, 3) is True


def test_ladder_states_empty_project(tmp_path):
    ladder = status.ladder_states(str(tmp_path))
    assert [r['level'] for r in ladder] == [0, 1, 2, 3, 4, 5, 6]
    assert all(r['state'] == 'not_started' for r in ladder)
    assert ladder[0]['name'] == 'logline'
