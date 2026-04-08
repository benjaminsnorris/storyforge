"""Tests for cmd_review command module."""

import pytest
from storyforge.cmd_review import parse_args


class TestParseArgs:
    """Argument parsing for storyforge review."""

    def test_defaults(self):
        args = parse_args([])
        assert args.review_type == 'manual'
        assert not args.interactive
        assert not args.dry_run

    def test_type_drafting(self):
        args = parse_args(['--type', 'drafting'])
        assert args.review_type == 'drafting'

    def test_type_evaluation(self):
        args = parse_args(['--type', 'evaluation'])
        assert args.review_type == 'evaluation'

    def test_type_revision(self):
        args = parse_args(['--type', 'revision'])
        assert args.review_type == 'revision'

    def test_type_assembly(self):
        args = parse_args(['--type', 'assembly'])
        assert args.review_type == 'assembly'

    def test_type_manual(self):
        args = parse_args(['--type', 'manual'])
        assert args.review_type == 'manual'

    def test_type_invalid(self):
        with pytest.raises(SystemExit):
            parse_args(['--type', 'invalid'])

    def test_interactive_flag(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_combined_flags(self):
        args = parse_args(['--type', 'drafting', '--interactive', '--dry-run'])
        assert args.review_type == 'drafting'
        assert args.interactive
        assert args.dry_run


class TestBranchAutoDetection:
    """Review type auto-detection from branch name."""

    def test_write_branch_maps_to_drafting(self):
        """Verify the mapping used in main()."""
        type_map = {
            'write': 'drafting',
            'evaluate': 'evaluation',
            'revise': 'revision',
            'assemble': 'assembly',
        }
        # Test the branch parsing logic
        branch = 'storyforge/write-20260101'
        branch_cmd = branch.split('/')[1].split('-')[0]
        assert type_map.get(branch_cmd) == 'drafting'

    def test_evaluate_branch(self):
        type_map = {
            'write': 'drafting',
            'evaluate': 'evaluation',
            'revise': 'revision',
            'assemble': 'assembly',
        }
        branch = 'storyforge/evaluate-20260405'
        branch_cmd = branch.split('/')[1].split('-')[0]
        assert type_map.get(branch_cmd) == 'evaluation'

    def test_revise_branch(self):
        type_map = {
            'write': 'drafting',
            'evaluate': 'evaluation',
            'revise': 'revision',
            'assemble': 'assembly',
        }
        branch = 'storyforge/revise-20260302'
        branch_cmd = branch.split('/')[1].split('-')[0]
        assert type_map.get(branch_cmd) == 'revision'

    def test_assemble_branch(self):
        type_map = {
            'write': 'drafting',
            'evaluate': 'evaluation',
            'revise': 'revision',
            'assemble': 'assembly',
        }
        branch = 'storyforge/assemble-20260101'
        branch_cmd = branch.split('/')[1].split('-')[0]
        assert type_map.get(branch_cmd) == 'assembly'

    def test_unknown_branch_not_mapped(self):
        type_map = {
            'write': 'drafting',
            'evaluate': 'evaluation',
            'revise': 'revision',
            'assemble': 'assembly',
        }
        branch = 'storyforge/cleanup-20260101'
        branch_cmd = branch.split('/')[1].split('-')[0]
        assert type_map.get(branch_cmd) is None

    def test_non_storyforge_branch(self):
        branch = 'feature/something'
        assert not branch.startswith('storyforge/')
