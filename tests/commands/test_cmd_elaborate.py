"""Tests for cmd_elaborate command module."""

import pytest
from storyforge.cmd_elaborate import parse_args, VALID_STAGES


class TestParseArgs:
    """Argument parsing for storyforge elaborate."""

    def test_stage_spine(self):
        args = parse_args(['--stage', 'spine'])
        assert args.stage == 'spine'

    def test_stage_architecture(self):
        args = parse_args(['--stage', 'architecture'])
        assert args.stage == 'architecture'

    def test_stage_map(self):
        args = parse_args(['--stage', 'map'])
        assert args.stage == 'map'

    def test_stage_briefs(self):
        args = parse_args(['--stage', 'briefs'])
        assert args.stage == 'briefs'

    def test_stage_gap_fill(self):
        args = parse_args(['--stage', 'gap-fill'])
        assert args.stage == 'gap-fill'

    def test_stage_mice_fill(self):
        args = parse_args(['--stage', 'mice-fill'])
        assert args.stage == 'mice-fill'

    def test_no_stage_errors(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_direct_flag_spine(self):
        args = parse_args(['--spine'])
        assert args.stage == 'spine'

    def test_direct_flag_briefs(self):
        args = parse_args(['--briefs'])
        assert args.stage == 'briefs'

    def test_direct_flag_gap_fill(self):
        args = parse_args(['--gap-fill'])
        assert args.stage == 'gap-fill'

    def test_direct_flag_mice_fill(self):
        args = parse_args(['--mice-fill'])
        assert args.stage == 'mice-fill'

    def test_dry_run_default_false(self):
        args = parse_args(['--stage', 'spine'])
        assert not args.dry_run

    def test_dry_run_flag(self):
        args = parse_args(['--stage', 'spine', '--dry-run'])
        assert args.dry_run

    def test_interactive_default_false(self):
        args = parse_args(['--stage', 'spine'])
        assert not args.interactive

    def test_interactive_flag(self):
        args = parse_args(['--stage', 'spine', '--interactive'])
        assert args.interactive

    def test_interactive_short_flag(self):
        args = parse_args(['--stage', 'spine', '-i'])
        assert args.interactive

    def test_seed_default_empty(self):
        args = parse_args(['--stage', 'spine'])
        assert args.seed == ''

    def test_seed_value(self):
        args = parse_args(['--stage', 'spine', '--seed', 'A story about maps'])
        assert args.seed == 'A story about maps'

    def test_coaching_default_none(self):
        args = parse_args(['--stage', 'spine'])
        assert args.coaching is None

    def test_coaching_full(self):
        args = parse_args(['--stage', 'spine', '--coaching', 'full'])
        assert args.coaching == 'full'

    def test_coaching_coach(self):
        args = parse_args(['--stage', 'spine', '--coaching', 'coach'])
        assert args.coaching == 'coach'

    def test_coaching_strict(self):
        args = parse_args(['--stage', 'spine', '--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_coaching_invalid(self):
        with pytest.raises(SystemExit):
            parse_args(['--stage', 'spine', '--coaching', 'invalid'])

    def test_stage_flag_overrides_direct(self):
        """--stage takes precedence when combined with direct flags."""
        args = parse_args(['--stage', 'map', '--spine'])
        assert args.stage == 'map'


class TestValidStages:
    """VALID_STAGES constant covers all expected stages."""

    def test_all_stages_present(self):
        expected = {'spine', 'architecture', 'map', 'briefs', 'gap-fill', 'mice-fill'}
        assert VALID_STAGES == expected

    def test_stage_count(self):
        assert len(VALID_STAGES) == 6
