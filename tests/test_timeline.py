"""Tests for timeline functions (migrated from test-timeline.sh)."""

import io
import os
import shutil
import sys

import storyforge.csv_cli as csv_cli


def _capture(fn, *args, **kwargs):
    """Call a csv_cli function and return its stdout output, stripped."""
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue().rstrip('\n')


class TestTimelineCsvOperations:
    def test_read_existing_timeline_day(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'act1-sc01', 'timeline_day') == '1'

    def test_update_timeline_day(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act2-sc01', 'timeline_day', '5')
        assert _capture(csv_cli.get_field, tmp_csv, 'act2-sc01', 'timeline_day') == '5'

    def test_overwrite_existing(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act1-sc01', 'timeline_day', '99')
        assert _capture(csv_cli.get_field, tmp_csv, 'act1-sc01', 'timeline_day') == '99'


class TestTimelineParsing:
    def test_parse_timeline_assignments(self):
        from storyforge.timeline import parse_timeline_assignments
        response = (
            'Some preamble text here.\n\n'
            'TIMELINE:\nid|timeline_day\n'
            'act1-sc01|1\nact1-sc02|1\nnew-x1|2\nact2-sc01|3\n\n'
            'Some trailing text.'
        )
        result = parse_timeline_assignments(response)
        assert result.get('act1-sc01') == 1
        assert result.get('new-x1') == 2
        assert result.get('act2-sc01') == 3

    def test_parse_indicators(self):
        from storyforge.timeline import parse_indicators
        response = 'DELTA: next_day\nEVIDENCE: "The sun rose over the archive"\nANCHOR: none\n'
        result = parse_indicators(response, 'test-scene')
        assert 'next_day' in str(result)
        assert 'sun rose' in str(result)
