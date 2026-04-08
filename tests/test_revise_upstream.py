"""Tests for revise upstream delegation and validation gate."""

import os


class TestFileHash:
    def test_consistent_hash(self, tmp_path):
        from storyforge.cmd_revise import _file_hash
        f = tmp_path / 'test.csv'
        f.write_text('id|goal\nscene-a|something\n')
        h1 = _file_hash(str(f))
        h2 = _file_hash(str(f))
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_detects_change(self, tmp_path):
        from storyforge.cmd_revise import _file_hash
        f = tmp_path / 'test.csv'
        f.write_text('id|goal\nscene-a|old\n')
        h1 = _file_hash(str(f))
        f.write_text('id|goal\nscene-a|new\n')
        h2 = _file_hash(str(f))
        assert h1 != h2

    def test_missing_file(self):
        from storyforge.cmd_revise import _file_hash
        assert _file_hash('/nonexistent/file.csv') == ''


class TestWriteHoneFindings:
    def test_writes_correct_format(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'brief', 'scene-a;scene-b', 'Fix the briefs')

        with open(path) as f:
            content = f.read()
        assert 'scene_id|target_file|fields|guidance' in content
        assert 'scene-a|scene-briefs.csv||Fix the briefs' in content
        assert 'scene-b|scene-briefs.csv||Fix the briefs' in content

    def test_intent_target_file(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'intent', 'scene-a', 'Fix intent')

        with open(path) as f:
            content = f.read()
        assert 'scene-intent.csv' in content

    def test_empty_targets(self, tmp_path):
        from storyforge.cmd_revise import _write_hone_findings
        path = str(tmp_path / 'findings.csv')
        _write_hone_findings(path, 'brief', '', 'General fix')

        with open(path) as f:
            lines = f.read().strip().split('\n')
        assert len(lines) == 1  # Only header, no data rows
