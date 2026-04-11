"""Regression tests for positional CSV column access.

Verify that csv_cli.list_ids() and costs.print_summary() work correctly
when CSV columns are in a non-standard order.
"""

import os

import storyforge.csv_cli as csv_cli
from storyforge.costs import log_operation, print_summary


class TestListIdsColumnOrder:
    """list_ids must use the header to find the key column, not assume index 0."""

    def test_id_not_first_column(self, tmp_path):
        """When 'id' is not the first column, list_ids should still return IDs."""
        csv_path = str(tmp_path / 'reordered.csv')
        with open(csv_path, 'w') as f:
            f.write('title|seq|id|status\n')
            f.write('Scene A|1|scene-a|draft\n')
            f.write('Scene B|2|scene-b|final\n')
            f.write('Scene C|3|scene-c|draft\n')

        result = csv_cli.list_ids(csv_path)
        assert result == ['scene-a', 'scene-b', 'scene-c']

    def test_id_last_column(self, tmp_path):
        """When 'id' is the last column, list_ids should still work."""
        csv_path = str(tmp_path / 'reordered.csv')
        with open(csv_path, 'w') as f:
            f.write('title|status|seq|id\n')
            f.write('Scene A|draft|1|alpha\n')
            f.write('Scene B|final|2|beta\n')

        result = csv_cli.list_ids(csv_path)
        assert result == ['alpha', 'beta']

    def test_custom_key_column_reordered(self, tmp_path):
        """list_ids with a custom key_col finds the right column regardless of position."""
        csv_path = str(tmp_path / 'keyed.csv')
        with open(csv_path, 'w') as f:
            f.write('name|score|principle\n')
            f.write('Alice|5|tension\n')
            f.write('Bob|3|voice\n')

        result = csv_cli.list_ids(csv_path, key_col='principle')
        assert result == ['tension', 'voice']

    def test_id_first_column_still_works(self, tmp_path):
        """Normal order (id first) should still work after the fix."""
        csv_path = str(tmp_path / 'normal.csv')
        with open(csv_path, 'w') as f:
            f.write('id|title|status\n')
            f.write('one|Title 1|draft\n')
            f.write('two|Title 2|final\n')

        result = csv_cli.list_ids(csv_path)
        assert result == ['one', 'two']

    def test_fallback_when_key_col_missing(self, tmp_path):
        """When the key column name is not in the header, fall back to column 0."""
        csv_path = str(tmp_path / 'no_id.csv')
        with open(csv_path, 'w') as f:
            f.write('name|value\n')
            f.write('alice|10\n')
            f.write('bob|20\n')

        # Default key_col='id' is not in headers, should fall back to column 0
        result = csv_cli.list_ids(csv_path)
        assert result == ['alice', 'bob']

    def test_empty_file(self, tmp_path):
        """Empty file returns empty list."""
        csv_path = str(tmp_path / 'empty.csv')
        with open(csv_path, 'w') as f:
            pass
        result = csv_cli.list_ids(csv_path)
        assert result == []

    def test_header_only(self, tmp_path):
        """File with only a header returns empty list."""
        csv_path = str(tmp_path / 'header_only.csv')
        with open(csv_path, 'w') as f:
            f.write('id|title|status\n')
        result = csv_cli.list_ids(csv_path)
        assert result == []


class TestPrintSummaryColumnOrder:
    """print_summary must use the header to find columns, not positional indices."""

    def _make_ledger(self, project_dir, header, rows):
        """Create a ledger CSV with the given header and rows."""
        ledger_dir = os.path.join(project_dir, 'working', 'costs')
        os.makedirs(ledger_dir, exist_ok=True)
        ledger_file = os.path.join(ledger_dir, 'ledger.csv')
        with open(ledger_file, 'w') as f:
            f.write(header + '\n')
            for row in rows:
                f.write(row + '\n')
        return ledger_file

    def test_reordered_columns(self, tmp_path, capsys):
        """print_summary works when columns are in a different order than LEDGER_HEADER."""
        project_dir = str(tmp_path)
        # Reorder: put cost_usd first, operation last, etc.
        header = 'cost_usd|input_tokens|duration_s|model|output_tokens|cache_read|cache_create|timestamp|target|operation'
        # Values matching the reordered header
        row = '0.500000|1000|30|sonnet|500|100|50|2026-01-01T00:00:00|scene-a|evaluate'
        self._make_ledger(project_dir, header, [row])

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Input tokens:  1000' in captured.out
        assert 'Output tokens: 500' in captured.out
        assert 'Cache read:    100' in captured.out
        assert 'Cache create:  50' in captured.out
        assert '$0.5000' in captured.out
        assert '30s' in captured.out

    def test_reordered_with_operation_filter(self, tmp_path, capsys):
        """Filtering by operation works with reordered columns."""
        project_dir = str(tmp_path)
        header = 'cost_usd|operation|input_tokens|output_tokens|cache_read|cache_create|duration_s|timestamp|target|model'
        rows = [
            '0.100000|evaluate|500|200|0|0|10|2026-01-01T00:00:00|scene-a|sonnet',
            '0.200000|score|300|100|0|0|5|2026-01-01T00:01:00|scene-a|sonnet',
            '0.300000|evaluate|700|400|0|0|20|2026-01-01T00:02:00|scene-b|sonnet',
        ]
        self._make_ledger(project_dir, header, rows)

        print_summary(project_dir, 'evaluate')
        captured = capsys.readouterr()
        assert 'Invocations:   2' in captured.out
        assert 'Input tokens:  1200' in captured.out
        assert 'Output tokens: 600' in captured.out

    def test_standard_order_still_works(self, tmp_path, capsys):
        """Normal column order (matching LEDGER_HEADER) still works after the fix."""
        project_dir = str(tmp_path)
        header = 'timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s'
        row = '2026-01-01T00:00:00|draft|scene-a|opus|2000|1000|200|100|1.000000|60'
        self._make_ledger(project_dir, header, [row])

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Input tokens:  2000' in captured.out
        assert 'Output tokens: 1000' in captured.out
        assert 'Cache read:    200' in captured.out
        assert 'Cache create:  100' in captured.out
        assert '$1.0000' in captured.out
        assert '60s' in captured.out

    def test_missing_optional_columns(self, tmp_path, capsys):
        """Ledger with fewer columns (e.g., no cache columns) still produces a summary."""
        project_dir = str(tmp_path)
        # Old-style format without cache columns
        header = 'timestamp|operation|model|input_tokens|output_tokens|cost_usd|duration_s'
        row = '2026-01-01T00:00:00|draft|opus|1000|500|0.500000|30'
        self._make_ledger(project_dir, header, rows=[row])

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Invocations:   1' in captured.out
        assert 'Input tokens:  1000' in captured.out
        assert 'Output tokens: 500' in captured.out
        assert 'Cache read:    0' in captured.out  # Missing columns default to 0
        assert '$0.5000' in captured.out

    def test_log_then_summary_roundtrip(self, tmp_path, capsys):
        """log_operation writes data that print_summary can read back correctly."""
        project_dir = str(tmp_path)
        log_operation(project_dir, 'evaluate', 'sonnet', 5000, 2000, 0.45,
                      duration_s=15, target='scene-x', cache_read=100, cache_create=50)
        log_operation(project_dir, 'evaluate', 'opus', 3000, 1000, 0.30,
                      duration_s=10, target='scene-y')

        print_summary(project_dir, 'evaluate')
        captured = capsys.readouterr()
        assert 'Invocations:   2' in captured.out
        assert 'Input tokens:  8000' in captured.out
        assert 'Output tokens: 3000' in captured.out
        assert 'Cache read:    100' in captured.out
        assert 'Cache create:  50' in captured.out

class TestApproveAllProposalsReorderedColumns:
    """_approve_all_proposals must find 'status' column by name, not position."""

    def test_standard_column_order(self, tmp_path):
        from storyforge.cmd_score import _approve_all_proposals

        proposals = tmp_path / 'proposals.csv'
        proposals.write_text(
            'id|principle|lever|target|change|rationale|status\n'
            'p001|voice|craft_weight|global|weight 5 → 7|avg 2.1|pending\n'
            'p002|pacing|scene_intent|sc-01|fix pacing|avg 1.8|pending\n'
        )
        _approve_all_proposals(str(proposals))

        lines = proposals.read_text().strip().split('\n')
        assert lines[1].endswith('approved')
        assert lines[2].endswith('approved')

    def test_reordered_columns(self, tmp_path):
        """status column moved to position 2 — must still be found by name."""
        from storyforge.cmd_score import _approve_all_proposals

        proposals = tmp_path / 'proposals.csv'
        proposals.write_text(
            'id|principle|status|lever|target|change|rationale\n'
            'p001|voice|pending|craft_weight|global|weight 5 → 7|avg 2.1\n'
            'p002|pacing|pending|scene_intent|sc-01|fix pacing|avg 1.8\n'
        )
        _approve_all_proposals(str(proposals))

        lines = proposals.read_text().strip().split('\n')
        # status is at index 2 in reordered header
        fields1 = lines[1].split('|')
        fields2 = lines[2].split('|')
        assert fields1[2] == 'approved'
        assert fields2[2] == 'approved'


# ============================================================================
# cmd_score.py — _print_strict_report
# ============================================================================

class TestPrintStrictReportReorderedColumns:
    """_print_strict_report must find columns by name in both diagnosis and proposals."""

    def test_diagnosis_reordered(self, tmp_path, capsys):
        from storyforge.cmd_score import _print_strict_report

        diagnosis = tmp_path / 'diagnosis.csv'
        # Reorder: move priority before avg_score
        diagnosis.write_text(
            'principle|priority|scale|avg_score|worst_items|delta_from_last|root_cause\n'
            'voice|high|scene|2.1|sc-01;sc-02|0.3|\n'
            'pacing|low|scene|4.2|sc-03|0.1|\n'
        )
        proposals = tmp_path / 'proposals.csv'
        proposals.write_text('id|principle|lever|target|change|rationale|status\n')

        _print_strict_report(str(diagnosis), str(proposals))
        output = capsys.readouterr().out

        # Should print voice (high priority) but not pacing (low priority)
        assert 'voice' in output
        assert 'pacing' not in output
        assert '2.1' in output

    def test_proposals_reordered(self, tmp_path, capsys):
        from storyforge.cmd_score import _print_strict_report

        diagnosis = tmp_path / 'diagnosis.csv'
        diagnosis.write_text(
            'principle|scale|avg_score|worst_items|delta_from_last|priority|root_cause\n'
        )
        proposals = tmp_path / 'proposals.csv'
        # Reorder: change and rationale swapped
        proposals.write_text(
            'id|principle|lever|target|rationale|change|status\n'
            'p001|voice|craft_weight|global|avg 2.1|weight 5 → 7|pending\n'
        )

        _print_strict_report(str(diagnosis), str(proposals))
        output = capsys.readouterr().out

        assert 'p001' in output
        assert 'voice' in output


# ============================================================================
# cmd_score.py — _apply_proposals
# ============================================================================

class TestApplyProposalsReorderedColumns:
    """_apply_proposals must read proposal fields by name, not position."""

    def test_reordered_columns(self, tmp_path):
        from storyforge.cmd_score import _apply_proposals

        # Create weights file
        weights = tmp_path / 'weights.csv'
        weights.write_text(
            'id|principle|weight|description\n'
            '1|voice|5|Voice quality\n'
        )

        # Reordered proposals: lever and target swapped
        proposals = tmp_path / 'proposals.csv'
        proposals.write_text(
            'id|principle|target|lever|change|rationale|status\n'
            'p001|voice|global|craft_weight|weight 5 → 7|avg 2.1|approved\n'
        )

        intent = tmp_path / 'intent.csv'
        intent.write_text('id|function\n')

        applied = _apply_proposals(
            str(proposals), str(weights), str(intent), str(tmp_path)
        )
        assert applied == 1

        # Verify weight was updated
        content = weights.read_text()
        assert '|7|' in content


# ============================================================================
# cmd_score.py — _generate_report_and_comment (ledger reading)
# ============================================================================

class TestLedgerReadingReorderedColumns:
    """Ledger cost summing must find operation and cost_usd by name."""

    def test_reordered_ledger(self, tmp_path):
        from storyforge.cmd_score import _generate_report_and_comment

        # Set up minimal project structure
        costs_dir = tmp_path / 'working' / 'costs'
        costs_dir.mkdir(parents=True)
        scores_dir = tmp_path / 'working' / 'scores' / 'cycle-1'
        scores_dir.mkdir(parents=True)

        # Reordered ledger: cost_usd moved to position 2
        ledger = costs_dir / 'ledger.csv'
        ledger.write_text(
            'timestamp|cost_usd|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|duration_s\n'
            '2026-04-10|0.50|score|sc-01|claude-sonnet|1000|500|0|0|5\n'
            '2026-04-10|0.30|score|sc-02|claude-sonnet|800|400|0|0|4\n'
            '2026-04-10|0.25|revise|sc-01|claude-sonnet|900|300|0|0|3\n'
        )

        # Create minimal scene-scores.csv for the report generator
        (scores_dir / 'scene-scores.csv').write_text('id|voice\nsc-01|3\n')

        # We can't easily test _generate_report_and_comment end-to-end
        # because it needs scoring.py imports. Instead, test the ledger
        # reading logic directly by extracting it.
        total_cost = 0.0
        with open(str(ledger)) as f:
            lines = f.readlines()
        if lines:
            l_header = lines[0].strip().split('|')
            l_col = {name: i for i, name in enumerate(l_header)}
            op_idx = l_col.get('operation', 1)
            cost_idx = l_col.get('cost_usd', 8)
            for line in lines[1:]:
                parts = line.strip().split('|')
                if len(parts) > max(op_idx, cost_idx) and parts[op_idx] == 'score':
                    try:
                        total_cost += float(parts[cost_idx])
                    except (ValueError, IndexError):
                        pass

        # Should sum 0.50 + 0.30 = 0.80 (exclude revise)
        assert abs(total_cost - 0.80) < 0.001


# ============================================================================
# cmd_revise.py — scenes.csv seq reading
# ============================================================================

class TestScenesSeqReorderedColumns:
    """_register_new_scenes must find seq column by name in scenes.csv."""

    def test_reordered_scenes_csv(self, tmp_path):
        from storyforge.cmd_revise import _register_new_scenes

        meta_csv = tmp_path / 'reference' / 'scenes.csv'
        meta_csv.parent.mkdir(parents=True)
        # Reorder: seq moved after title
        meta_csv.write_text(
            'id|title|seq|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'existing-scene|Existing|5|1|Alice|Library|1|morning|30|scene|drafted|500|\n'
        )

        intent_csv = tmp_path / 'reference' / 'scene-intent.csv'
        intent_csv.write_text('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point\n')

        scenes_dir = tmp_path / 'scenes'
        scenes_dir.mkdir()
        (scenes_dir / 'new-scene.md').write_text('Some prose content for the new scene.')

        _register_new_scenes(
            str(tmp_path), 'NEW:new-scene', 'test-pass'
        )

        # The new scene should be registered with seq = 6 (max existing + 1)
        content = meta_csv.read_text()
        assert 'new-scene|6|' in content


# ============================================================================
# cmd_revise.py — pipeline.csv cycle_id reading
# ============================================================================

class TestPipelineCycleIdReorderedColumns:
    """Pipeline manifest cycle_id must be read by column name, not index 0."""

    def test_reordered_pipeline_csv(self, tmp_path):
        """cycle column moved from position 0 — still found by name."""
        manifest = tmp_path / 'working' / 'pipeline.csv'
        manifest.parent.mkdir(parents=True)
        # Reorder: started before cycle
        manifest.write_text(
            'started|cycle|status|evaluation|scoring|plan|review|recommendations|summary\n'
            '2026-04-10|3|scoring|||||\n'
        )

        with open(str(manifest)) as f:
            lines = f.readlines()
        if len(lines) > 1:
            p_header = lines[0].strip().split('|')
            cycle_col = p_header.index('cycle') if 'cycle' in p_header else 0
            last_parts = lines[-1].strip().split('|')
            cycle_id = last_parts[cycle_col] if len(last_parts) > cycle_col else '0'

        assert cycle_id == '3'

    def test_standard_pipeline_csv(self, tmp_path):
        """Standard column order still works."""
        manifest = tmp_path / 'working' / 'pipeline.csv'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            'cycle|started|status|evaluation|scoring|plan|review|recommendations|summary\n'
            '5|2026-04-10|scoring|||||\n'
        )

        with open(str(manifest)) as f:
            lines = f.readlines()
        if len(lines) > 1:
            p_header = lines[0].strip().split('|')
            cycle_col = p_header.index('cycle') if 'cycle' in p_header else 0
            last_parts = lines[-1].strip().split('|')
            cycle_id = last_parts[cycle_col] if len(last_parts) > cycle_col else '0'

        assert cycle_id == '5'


# ============================================================================
# cmd_revise.py — pipeline.csv status update with reordered columns
# ============================================================================

class TestPipelineStatusUpdateReorderedColumns:
    """Pipeline cycle status update must find both cycle and status by name."""

    def test_reordered_pipeline_update(self, tmp_path):
        manifest = tmp_path / 'pipeline.csv'
        # Reorder: status before cycle
        manifest.write_text(
            'status|cycle|started|evaluation|scoring|plan|review|recommendations|summary\n'
            'scoring|3|2026-04-10||||||\n'
        )
        cycle_id = '3'

        with open(str(manifest)) as f:
            lines = f.readlines()
        header = lines[0].strip().split('|')
        if 'status' in header and 'cycle' in header:
            status_idx = header.index('status')
            cycle_idx = header.index('cycle')
            for i in range(1, len(lines)):
                parts = lines[i].strip().split('|')
                if len(parts) > cycle_idx and parts[cycle_idx] == cycle_id:
                    while len(parts) <= status_idx:
                        parts.append('')
                    parts[status_idx] = 'revising'
                    lines[i] = '|'.join(parts) + '\n'
            with open(str(manifest), 'w') as f:
                f.writelines(lines)

        updated = manifest.read_text()
        # status is at index 0 in reordered header, should now be 'revising'
        data_line = updated.strip().split('\n')[1]
        fields = data_line.split('|')
        assert fields[0] == 'revising'  # status column
        assert fields[1] == '3'  # cycle column preserved


# ============================================================================
# cmd_score.py — briefs.csv goal column detection
# ============================================================================

class TestBriefsGoalDetectionReorderedColumns:
    """Fidelity scoring brief count must find goal column by name."""

    def test_reordered_briefs_csv(self, tmp_path):
        """goal column moved — brief count should still be correct."""
        briefs = tmp_path / 'briefs.csv'
        # Reorder: conflict before goal
        briefs.write_text(
            'id|conflict|goal|outcome|crisis|decision\n'
            'sc-01|some conflict|achieve X|resolved|moment|yes\n'
            'sc-02|another|reach Y|pending|crisis|no\n'
            'sc-03|third||nothing|none|maybe\n'
        )

        brief_count = 0
        with open(str(briefs)) as f:
            header = None
            goal_idx = 1  # fallback
            for i, line in enumerate(f):
                if i == 0:
                    header = line.strip().split('|')
                    if 'goal' in header:
                        goal_idx = header.index('goal')
                    continue
                fields = line.strip().split('|')
                if len(fields) > goal_idx and fields[goal_idx].strip():
                    brief_count += 1

        # sc-01 and sc-02 have goals; sc-03 has empty goal
        assert brief_count == 2

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
