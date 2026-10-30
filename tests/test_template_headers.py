"""Template CSV headers match the schema the writers use (#440).

init copies templates/reference/ into a new project, and every writer
(elaborate, migrate, extract) writes the columns in elaborate._FILE_MAP. A
template that lags them starts a project on a header no writer produces:
spine.csv and architecture.csv had no `summary`, scenes.csv no `summary` or
`architecture_scene`, scene-intent.csv no `theme_threads`.
"""

import os

import pytest

from storyforge.common import get_plugin_dir
from storyforge.elaborate import _FILE_MAP


@pytest.mark.parametrize('name', sorted(_FILE_MAP))
def test_template_header_is_the_canonical_columns(name):
    path = os.path.join(get_plugin_dir(), 'templates', 'reference', name)
    with open(path, encoding='utf-8') as f:
        header = f.readline().rstrip('\n')
    assert header.split('|') == _FILE_MAP[name]


def test_a_fresh_project_from_the_templates_has_no_column_findings(tmp_path, monkeypatch):
    """Review T-3 on #442: cleanup's expected schemas lagged the templates,
    so a project init had just created was reported as having unexpected
    columns. Every template CSV cleanup knows is checked, registries too."""
    import shutil
    from storyforge import cmd_cleanup
    shutil.copytree(os.path.join(get_plugin_dir(), 'templates', 'reference'),
                    tmp_path / 'reference')
    monkeypatch.setattr(cmd_cleanup, 'get_medium', lambda d: 'novel')
    column_issues = [i for i in cmd_cleanup.report_csv_schema(str(tmp_path))
                     if i.startswith(('MISSING_COLUMN:', 'EXTRA_COLUMN:'))]
    assert column_issues == []


def test_cleanup_reads_scene_schemas_from_the_one_column_list():
    from storyforge.cmd_cleanup import EXPECTED_CSV_SCHEMAS, GN_ONLY_COLUMNS
    for name in ('scenes.csv', 'scene-intent.csv', 'scene-briefs.csv'):
        rel = f'reference/{name}'
        assert EXPECTED_CSV_SCHEMAS[rel] == \
            [c for c in _FILE_MAP[name] if c not in GN_ONLY_COLUMNS.get(rel, ())]
