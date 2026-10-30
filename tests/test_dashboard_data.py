"""The dashboard_data contract with Bookshelf (storyforge#371,
benjaminsnorris/bookshelf#30). Bookshelf renders the data and refuses a
schema_version it can't draw, so changing a key or a value's type must bump
DASHBOARD_SCHEMA_VERSION in the same commit (and in docs/agent-reference.md)."""

import os

from storyforge.visualize import DASHBOARD_SCHEMA_VERSION, csv_to_records, load_dashboard_data

V1_KEYS = {
    'schema_version', 'project', 'scenes', 'intents', 'briefs', 'characters',
    'motif_taxonomy', 'locations', 'values', 'mice_threads', 'knowledge', 'scores',
    'weights', 'narrative_scores', 'scene_rationales', 'act_scores', 'act_rationales',
    'character_scores', 'character_rationales', 'genre_scores', 'genre_rationales',
    'narrative_rationales', 'fidelity_scores', 'fidelity_rationales', 'structural_scores',
    'repetition_scores', 'brief_quality',
}
PROJECT_KEYS = {'title', 'genre', 'phase', 'scene_count', 'total_words', 'target_words',
                'generated'}


def test_v1_keys_and_version(project_dir):
    data = load_dashboard_data(project_dir)
    assert DASHBOARD_SCHEMA_VERSION == 1 and data['schema_version'] == 1
    assert set(data) == V1_KEYS
    assert set(data['project']) == PROJECT_KEYS


def test_row_and_project_values_are_strings(project_dir):
    """Bookshelf's schema takes only strings in rows and project fields (a
    number would stop the whole page); brief_quality's counts are the
    exception."""
    data = load_dashboard_data(project_dir)
    assert all(isinstance(v, str) for v in data['project'].values())
    for key in V1_KEYS - {'schema_version', 'project', 'brief_quality'}:
        for row in data[key]:
            assert all(isinstance(v, str) for v in row.values()), key
    assert data['scenes'], 'the fixture has scenes'
    # Bookshelf: scene_id, field and issue are strings; the counts strings or
    # numbers, never None
    assert data['brief_quality'], 'the fixture has brief issues'
    for row in data['brief_quality']:
        assert all(isinstance(row[k], str) for k in ('scene_id', 'field', 'issue'))
        assert all(isinstance(v, (str, int, float)) and not isinstance(v, bool)
                   for v in row.values())


def test_score_rows_are_strings(project_dir):
    """The fixture has no scores, so the check above never saw a score row."""
    latest = os.path.join(project_dir, 'working', 'scores', 'latest')
    os.makedirs(latest, exist_ok=True)
    with open(os.path.join(latest, 'scene-scores.csv'), 'w') as f:
        f.write('id|prose_naturalness|economy_clarity\nact1-sc01|4|n/a\n')
    data = load_dashboard_data(project_dir)
    assert data['scores'] == [{'id': 'act1-sc01', 'prose_naturalness': '4',
                               'economy_clarity': 'n/a'}]


def test_brief_quality_that_cannot_be_checked_says_so(project_dir, monkeypatch, capsys):
    """SF2: a crash returned [], which the dashboard shows as no brief issues."""
    import storyforge.hone as hone

    def boom(*a, **kw):
        raise KeyError('goal')
    monkeypatch.setattr(hone, 'detect_brief_issues', boom)
    assert load_dashboard_data(project_dir)['brief_quality'] == []
    assert 'WARNING: brief quality not checked' in capsys.readouterr().out


def test_values_are_not_escaped(tmp_path):
    """csv_to_records replaced < and > with the text \\u003c / \\u003e, which
    reached both renderers as literal text. Escaping is the renderer's job."""
    path = tmp_path / 'x.csv'
    path.write_text('id|note\ns1|a<b & c>d\n')
    assert csv_to_records(str(path)) == [{'id': 's1', 'note': 'a<b & c>d'}]


def test_contract_is_documented():
    doc = open(os.path.join(os.path.dirname(__file__), '..', 'docs', 'agent-reference.md')).read()
    section = doc[doc.index('## Dashboard data'):doc.index('## Architecture')]
    assert f'schema version {DASHBOARD_SCHEMA_VERSION}' in section
    for key in V1_KEYS - {'schema_version', 'project'}:
        assert f'`{key}`' in section, key
