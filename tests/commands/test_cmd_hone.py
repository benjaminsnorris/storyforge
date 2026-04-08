"""Command-level tests for storyforge.cmd_hone module.

Tests parse_args, _resolve_domains, _resolve_scene_filter, domain constants,
loop/diagnose incompatibilities, and _count_brief_issues.
"""

import os

import pytest

from storyforge.cmd_hone import (
    parse_args,
    _resolve_domains,
    _resolve_scene_filter,
    _count_brief_issues,
    _log_brief_counts,
    ALL_DOMAINS,
    PHASE1_REGISTRY,
    PHASE2_REGISTRY,
    PHASE3_REGISTRY,
    ALL_REGISTRY_SUBS,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.domain is None
        assert args.phase is None
        assert args.scenes is None
        assert args.act is None
        assert args.threshold == 3.5
        assert args.coaching is None
        assert args.diagnose is False
        assert args.dry_run is False
        assert args.loop is False
        assert args.max_loops == 5

    def test_domain(self):
        args = parse_args(['--domain', 'briefs'])
        assert args.domain == 'briefs'

    def test_domain_comma_separated(self):
        args = parse_args(['--domain', 'briefs,gaps'])
        assert args.domain == 'briefs,gaps'

    def test_phase(self):
        args = parse_args(['--phase', '2'])
        assert args.phase == 2

    def test_scenes(self):
        args = parse_args(['--scenes', 'sc1,sc2'])
        assert args.scenes == 'sc1,sc2'

    def test_act(self):
        args = parse_args(['--act', '1'])
        assert args.act == '1'

    def test_threshold(self):
        args = parse_args(['--threshold', '5.0'])
        assert args.threshold == 5.0

    def test_coaching(self):
        args = parse_args(['--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_diagnose(self):
        args = parse_args(['--diagnose'])
        assert args.diagnose is True

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_loop(self):
        args = parse_args(['--loop'])
        assert args.loop is True

    def test_max_loops(self):
        args = parse_args(['--max-loops', '10'])
        assert args.max_loops == 10


# ============================================================================
# _resolve_domains
# ============================================================================

class TestResolveDomains:
    def test_default_all_domains(self):
        args = parse_args([])
        domains = _resolve_domains(args)
        assert domains == list(ALL_DOMAINS)

    def test_single_domain(self):
        args = parse_args(['--domain', 'briefs'])
        domains = _resolve_domains(args)
        assert domains == ['briefs']

    def test_comma_separated_domains(self):
        args = parse_args(['--domain', 'briefs,gaps'])
        domains = _resolve_domains(args)
        assert domains == ['briefs', 'gaps']

    def test_phase_1(self):
        args = parse_args(['--phase', '1'])
        domains = _resolve_domains(args)
        assert domains == PHASE1_REGISTRY

    def test_phase_2(self):
        args = parse_args(['--phase', '2'])
        domains = _resolve_domains(args)
        assert domains == PHASE2_REGISTRY

    def test_phase_3(self):
        args = parse_args(['--phase', '3'])
        domains = _resolve_domains(args)
        assert domains == PHASE3_REGISTRY

    def test_invalid_phase(self):
        args = parse_args(['--phase', '9'])
        domains = _resolve_domains(args)
        assert domains == []


# ============================================================================
# _resolve_scene_filter
# ============================================================================

class TestResolveSceneFilter:
    def test_no_filter_returns_none(self):
        args = parse_args([])
        result = _resolve_scene_filter(args, '/fake/ref')
        assert result is None

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'sc1,sc2,sc3'])
        result = _resolve_scene_filter(args, '/fake/ref')
        assert result == ['sc1', 'sc2', 'sc3']

    def test_act_filter_with_fixture(self, fixture_dir):
        args = parse_args(['--act', '1'])
        ref_dir = os.path.join(fixture_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        # Act 1 scenes from fixture: act1-sc01, act1-sc02, new-x1
        assert 'act1-sc01' in result
        assert 'act1-sc02' in result


# ============================================================================
# Domain constants
# ============================================================================

class TestDomainConstants:
    def test_all_domains(self):
        assert 'registries' in ALL_DOMAINS
        assert 'gaps' in ALL_DOMAINS
        assert 'structural' in ALL_DOMAINS
        assert 'briefs' in ALL_DOMAINS

    def test_phase1_has_core_registries(self):
        assert 'characters' in PHASE1_REGISTRY
        assert 'locations' in PHASE1_REGISTRY

    def test_phase2_has_values(self):
        assert 'values' in PHASE2_REGISTRY
        assert 'mice-threads' in PHASE2_REGISTRY

    def test_phase3_has_knowledge(self):
        assert 'knowledge' in PHASE3_REGISTRY
        assert 'outcomes' in PHASE3_REGISTRY
        assert 'physical-states' in PHASE3_REGISTRY

    def test_all_registry_subs_covers_all_phases(self):
        all_phases = set(PHASE1_REGISTRY + PHASE2_REGISTRY + PHASE3_REGISTRY)
        assert all_phases == set(ALL_REGISTRY_SUBS)


# ============================================================================
# _count_brief_issues
# ============================================================================

class TestCountBriefIssues:
    def test_counts_from_fixture(self, fixture_dir):
        ref_dir = os.path.join(fixture_dir, 'reference')
        counts = _count_brief_issues(ref_dir, None)
        # Should return a dict with expected keys
        assert 'total' in counts
        assert 'scenes' in counts
        assert 'abstract' in counts
        assert 'overspecified' in counts
        assert 'verbose' in counts
        assert isinstance(counts['total'], int)

    def test_with_scene_filter(self, fixture_dir):
        ref_dir = os.path.join(fixture_dir, 'reference')
        counts = _count_brief_issues(ref_dir, ['act1-sc01'])
        # With a single scene filter, counts should be <= unfiltered
        assert isinstance(counts['total'], int)
        assert counts['scenes'] <= 1


# ============================================================================
# _log_brief_counts
# ============================================================================

class TestLogBriefCounts:
    def test_logs_counts(self, capsys):
        counts = {'total': 5, 'scenes': 3, 'abstract': 2,
                  'overspecified': 1, 'verbose': 2, 'conflict_free': 0}
        _log_brief_counts(counts, '  ')
        captured = capsys.readouterr()
        assert '5 brief issues' in captured.out
        assert '3 scenes' in captured.out

    def test_zero_counts(self, capsys):
        counts = {'total': 0, 'scenes': 0, 'abstract': 0,
                  'overspecified': 0, 'verbose': 0, 'conflict_free': 0}
        _log_brief_counts(counts, '')
        captured = capsys.readouterr()
        assert '0 brief issues' in captured.out


# ============================================================================
# Loop incompatibilities (tested via main entrypoint logic)
# ============================================================================

class TestLoopIncompatibilities:
    def test_loop_args_set(self):
        """Verify args parse correctly for loop."""
        args = parse_args(['--loop', '--max-loops', '3'])
        assert args.loop is True
        assert args.max_loops == 3

    def test_diagnose_and_loop_both_set(self):
        """Both flags can be parsed (validation is in main())."""
        args = parse_args(['--loop', '--diagnose'])
        assert args.loop is True
        assert args.diagnose is True
