"""Regression tests for positional CSV column access bugs.

Verifies that prompts._get_scene_overrides and revision._build_overrides_section
work correctly when CSV columns are reordered, rather than relying on column
position.
"""

import os


def _write_csv(tmp_path, filename, content):
    """Write text content to a file, returning the path."""
    path = str(tmp_path / filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


# ============================================================================
# prompts._get_scene_overrides
# ============================================================================

class TestGetSceneOverridesColumnOrder:
    """prompts._get_scene_overrides accesses columns by name, not position."""

    def _setup_project(self, tmp_path, csv_content):
        """Create a minimal project dir with an overrides.csv."""
        project_dir = str(tmp_path / 'project')
        scores_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(scores_dir)
        overrides_path = os.path.join(scores_dir, 'overrides.csv')
        with open(overrides_path, 'w', encoding='utf-8') as f:
            f.write(csv_content)
        return project_dir

    def test_standard_column_order(self, tmp_path):
        """Works with the standard id|principle|directive|source order."""
        from storyforge.prompts import _get_scene_overrides

        project_dir = self._setup_project(tmp_path,
            'id|principle|directive|source\n'
            'sc-01|pacing|Slow the opening|evaluator\n'
            'sc-01|voice|Add more interiority|evaluator\n'
            'sc-02|pacing|Speed up the chase|evaluator\n'
        )
        result = _get_scene_overrides('sc-01', project_dir)
        assert '- Slow the opening' in result
        assert '- Add more interiority' in result
        assert 'Speed up the chase' not in result

    def test_reordered_columns(self, tmp_path):
        """Works when columns are reordered (directive before id)."""
        from storyforge.prompts import _get_scene_overrides

        project_dir = self._setup_project(tmp_path,
            'source|directive|principle|id\n'
            'evaluator|Slow the opening|pacing|sc-01\n'
            'evaluator|Speed up the chase|pacing|sc-02\n'
        )
        result = _get_scene_overrides('sc-01', project_dir)
        assert '- Slow the opening' in result
        assert 'Speed up the chase' not in result

    def test_extra_columns(self, tmp_path):
        """Works when extra columns are present."""
        from storyforge.prompts import _get_scene_overrides

        project_dir = self._setup_project(tmp_path,
            'id|principle|directive|source|notes|priority\n'
            'sc-01|pacing|Slow the opening|evaluator|important|high\n'
        )
        result = _get_scene_overrides('sc-01', project_dir)
        assert '- Slow the opening' in result

    def test_missing_directive_column(self, tmp_path):
        """Returns empty string when directive column is missing."""
        from storyforge.prompts import _get_scene_overrides

        project_dir = self._setup_project(tmp_path,
            'id|principle|source\n'
            'sc-01|pacing|evaluator\n'
        )
        result = _get_scene_overrides('sc-01', project_dir)
        assert result == ''

    def test_no_file(self, tmp_path):
        """Returns empty string when overrides file does not exist."""
        from storyforge.prompts import _get_scene_overrides

        project_dir = str(tmp_path / 'project')
        os.makedirs(project_dir, exist_ok=True)
        result = _get_scene_overrides('sc-01', project_dir)
        assert result == ''


# ============================================================================
# revision._build_overrides_section
# ============================================================================

class TestBuildOverridesSectionColumnOrder:
    """revision._build_overrides_section accesses columns by name, not position."""

    def _setup_project(self, tmp_path, csv_content):
        """Create a minimal project dir with an overrides.csv."""
        project_dir = str(tmp_path / 'project')
        scores_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(scores_dir)
        overrides_path = os.path.join(scores_dir, 'overrides.csv')
        with open(overrides_path, 'w', encoding='utf-8') as f:
            f.write(csv_content)
        return project_dir

    def test_standard_column_order(self, tmp_path):
        """Works with the standard id|principle|directive|source order."""
        from storyforge.revision import _build_overrides_section

        project_dir = self._setup_project(tmp_path,
            'id|principle|directive|source\n'
            'sc-01|pacing|Slow the opening|evaluator\n'
            'sc-02|voice|Add more interiority|evaluator\n'
        )
        result = _build_overrides_section(project_dir, pass_config='')
        assert '- [sc-01] pacing: Slow the opening' in result
        assert '- [sc-02] voice: Add more interiority' in result

    def test_reordered_columns(self, tmp_path):
        """Works when columns are reordered (directive before id)."""
        from storyforge.revision import _build_overrides_section

        project_dir = self._setup_project(tmp_path,
            'source|directive|principle|id\n'
            'evaluator|Slow the opening|pacing|sc-01\n'
            'evaluator|Add more interiority|voice|sc-02\n'
        )
        result = _build_overrides_section(project_dir, pass_config='')
        assert '- [sc-01] pacing: Slow the opening' in result
        assert '- [sc-02] voice: Add more interiority' in result

    def test_reordered_columns_with_targets(self, tmp_path):
        """Works when columns are reordered and targets filter is applied."""
        from storyforge.revision import _build_overrides_section

        project_dir = self._setup_project(tmp_path,
            'source|directive|principle|id\n'
            'evaluator|Slow the opening|pacing|sc-01\n'
            'evaluator|Add more interiority|voice|sc-02\n'
        )
        result = _build_overrides_section(
            project_dir, pass_config='targets: sc-01')
        assert '- [sc-01] pacing: Slow the opening' in result
        assert 'sc-02' not in result

    def test_extra_columns(self, tmp_path):
        """Works when extra columns are present."""
        from storyforge.revision import _build_overrides_section

        project_dir = self._setup_project(tmp_path,
            'id|principle|directive|source|notes|priority\n'
            'sc-01|pacing|Slow the opening|evaluator|important|high\n'
        )
        result = _build_overrides_section(project_dir, pass_config='')
        assert '- [sc-01] pacing: Slow the opening' in result

    def test_no_file(self, tmp_path):
        """Returns empty string when overrides file does not exist."""
        from storyforge.revision import _build_overrides_section

        project_dir = str(tmp_path / 'project')
        os.makedirs(project_dir, exist_ok=True)
        result = _build_overrides_section(project_dir, pass_config='')
        assert result == ''
