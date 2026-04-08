"""Tests for cmd_enrich command module."""

import pytest
from storyforge.cmd_enrich import (
    parse_args, ALL_FIELDS, METADATA_FIELDS, INTENT_FIELDS, BRIEFS_FIELDS,
    _csv_for_field, _infer_time_of_day,
)


class TestParseArgs:
    """Argument parsing for storyforge enrich."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.direct
        assert not args.interactive
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None
        assert args.parallel is None
        assert args.fields == ALL_FIELDS
        assert not args.force
        assert not args.skip_timeline
        assert not args.skip_dashboard
        assert not args.dry_run

    def test_direct_mode(self):
        args = parse_args(['--direct'])
        assert args.direct

    def test_interactive_mode(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'scene-1,scene-2'])
        assert args.scenes == 'scene-1,scene-2'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_filter(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_from_seq_range(self):
        args = parse_args(['--from-seq', '3-8'])
        assert args.from_seq == '3-8'

    def test_parallel_workers(self):
        args = parse_args(['--parallel', '12'])
        assert args.parallel == 12

    def test_fields_override(self):
        args = parse_args(['--fields', 'pov,location'])
        assert args.fields == 'pov,location'

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force

    def test_skip_timeline(self):
        args = parse_args(['--skip-timeline'])
        assert args.skip_timeline

    def test_skip_dashboard(self):
        args = parse_args(['--skip-dashboard'])
        assert args.skip_dashboard

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run


class TestFieldConstants:
    """Field categorization constants are consistent."""

    def test_all_fields_non_empty(self):
        fields = ALL_FIELDS.split(',')
        assert len(fields) > 0
        assert all(f.strip() for f in fields)

    def test_metadata_fields_are_subset(self):
        all_set = set(ALL_FIELDS.split(','))
        assert METADATA_FIELDS.issubset(all_set)

    def test_intent_fields_are_subset(self):
        all_set = set(ALL_FIELDS.split(','))
        assert INTENT_FIELDS.issubset(all_set)

    def test_briefs_fields_are_subset(self):
        all_set = set(ALL_FIELDS.split(','))
        assert BRIEFS_FIELDS.issubset(all_set)

    def test_no_overlap_metadata_intent(self):
        assert METADATA_FIELDS.isdisjoint(INTENT_FIELDS)

    def test_no_overlap_metadata_briefs(self):
        assert METADATA_FIELDS.isdisjoint(BRIEFS_FIELDS)

    def test_no_overlap_intent_briefs(self):
        assert INTENT_FIELDS.isdisjoint(BRIEFS_FIELDS)


class TestCsvForField:
    """_csv_for_field returns correct CSV path per field."""

    def test_metadata_field(self):
        result = _csv_for_field('pov', '/proj')
        assert result.endswith('scenes.csv')

    def test_intent_field(self):
        result = _csv_for_field('value_at_stake', '/proj')
        assert result.endswith('scene-intent.csv')

    def test_briefs_field(self):
        result = _csv_for_field('goal', '/proj')
        assert result.endswith('scene-briefs.csv')

    def test_unknown_field_returns_empty(self):
        result = _csv_for_field('nonexistent', '/proj')
        assert result == ''


class TestInferTimeOfDay:
    """_infer_time_of_day heuristic keyword matching."""

    def test_dawn(self):
        assert _infer_time_of_day('The sunrise painted the sky.') == 'dawn'

    def test_morning(self):
        assert _infer_time_of_day('She poured her morning coffee.') == 'morning'

    def test_afternoon(self):
        assert _infer_time_of_day('They met for lunch at the cafe.') == 'afternoon'

    def test_dusk(self):
        assert _infer_time_of_day('The sunset faded over the hills.') == 'dusk'

    def test_evening(self):
        assert _infer_time_of_day('At dinner, they discussed the plan.') == 'evening'

    def test_night(self):
        assert _infer_time_of_day('The streetlight flickered at midnight.') == 'night'

    def test_no_match(self):
        assert _infer_time_of_day('They walked through the forest.') == ''

    def test_first_light(self):
        assert _infer_time_of_day('At first light they departed.') == 'dawn'

    def test_moonlight(self):
        assert _infer_time_of_day('The moonlight cast long shadows.') == 'night'
