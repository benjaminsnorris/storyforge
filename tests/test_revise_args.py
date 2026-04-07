"""Tests for _build_revision_config in cmd_revise.py."""

import pytest


class TestBuildRevisionConfig:
    def test_empty_plan_row_returns_empty_string(self):
        from storyforge.cmd_revise import _build_revision_config
        result = _build_revision_config({})
        assert result == ''

    def test_all_empty_fields_returns_empty_string(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {
            'guidance': '',
            'protection': '',
            'findings': '',
            'targets': '',
        }
        result = _build_revision_config(row)
        assert result == ''

    def test_guidance_included(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {'guidance': 'Tighten prose and remove redundancy.'}
        result = _build_revision_config(row)
        assert 'guidance:' in result
        assert 'Tighten prose and remove redundancy.' in result

    def test_protection_included(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {'protection': 'Do not edit the opening paragraph.'}
        result = _build_revision_config(row)
        assert 'protection:' in result
        assert 'Do not edit the opening paragraph.' in result

    def test_findings_included(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {'findings': 'Sentence variation is low. Passive voice overused.'}
        result = _build_revision_config(row)
        assert 'findings:' in result
        assert 'Sentence variation is low.' in result

    def test_targets_included(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {'targets': 's01;s03;s07'}
        result = _build_revision_config(row)
        assert 'targets:' in result
        assert 's01;s03;s07' in result

    def test_multiple_fields_all_present(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {
            'guidance': 'Remove AI tells.',
            'protection': 'Keep the metaphors.',
            'findings': 'Too many filler adverbs.',
            'targets': 's01;s02',
        }
        result = _build_revision_config(row)
        assert 'guidance:' in result
        assert 'protection:' in result
        assert 'findings:' in result
        assert 'targets:' in result

    def test_empty_fields_skipped(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {
            'guidance': 'Remove AI tells.',
            'protection': '',
            'findings': '',
            'targets': 's01;s02',
        }
        result = _build_revision_config(row)
        assert 'guidance:' in result
        assert 'targets:' in result
        assert 'protection:' not in result
        assert 'findings:' not in result

    def test_extra_kwargs_included(self):
        """Additional optional data (e.g. rationale from Task 9) can be passed."""
        from storyforge.cmd_revise import _build_revision_config
        row = {'guidance': 'Tighten prose.'}
        result = _build_revision_config(row, extra={'rationale': 'Score dropped 0.4 points.'})
        assert 'rationale:' in result
        assert 'Score dropped 0.4 points.' in result

    def test_extra_empty_values_skipped(self):
        from storyforge.cmd_revise import _build_revision_config
        row = {'guidance': 'Tighten prose.'}
        result = _build_revision_config(row, extra={'rationale': ''})
        assert 'rationale:' not in result

    def test_result_is_valid_yaml_structure(self):
        """Output lines should be key: value format."""
        from storyforge.cmd_revise import _build_revision_config
        row = {
            'guidance': 'Do this.',
            'targets': 's01;s03',
        }
        result = _build_revision_config(row)
        lines = [l for l in result.strip().splitlines() if l.strip()]
        for line in lines:
            assert ': ' in line or line.endswith(':'), f"Not a valid YAML line: {line!r}"

    def test_unknown_fields_in_row_ignored(self):
        """Fields not in the known set should not appear in config."""
        from storyforge.cmd_revise import _build_revision_config
        row = {
            'guidance': 'Fix prose.',
            'name': 'prose-polish',   # not a config field
            'status': 'pending',      # not a config field
        }
        result = _build_revision_config(row)
        assert 'name:' not in result
        assert 'status:' not in result
        assert 'guidance:' in result
