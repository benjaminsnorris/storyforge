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
