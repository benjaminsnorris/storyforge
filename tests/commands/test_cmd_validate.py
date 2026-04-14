"""Tests for storyforge validate — structural and schema validation.

Covers: parse_args (all flags), main() orchestration with mocked validation
functions, JSON output, quiet mode, human-readable output, structural scoring,
knowledge granularity, voice profile validation, exit codes, and error handling.
"""

import json
import os
import sys

import pytest

from storyforge.cmd_validate import parse_args, main, _print_human_readable


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.no_schema
        assert not args.structural
        assert not args.json_output
        assert not args.quiet

    def test_no_schema(self):
        args = parse_args(['--no-schema'])
        assert args.no_schema

    def test_structural(self):
        args = parse_args(['--structural'])
        assert args.structural

    def test_json_output(self):
        args = parse_args(['--json'])
        assert args.json_output

    def test_quiet(self):
        args = parse_args(['--quiet'])
        assert args.quiet

    def test_combined_flags(self):
        args = parse_args(['--no-schema', '--structural', '--json'])
        assert args.no_schema
        assert args.structural
        assert args.json_output

    def test_quiet_with_no_schema(self):
        args = parse_args(['--quiet', '--no-schema'])
        assert args.quiet
        assert args.no_schema

    def test_all_flags(self):
        args = parse_args(['--no-schema', '--structural', '--json', '--quiet'])
        assert args.no_schema
        assert args.structural
        assert args.json_output
        assert args.quiet


# ============================================================================
# Helpers for building mock return values
# ============================================================================


def _passing_structural():
    """Return a validate_structure result that passes."""
    return {
        'passed': True,
        'checks': [
            {'category': 'identity', 'name': 'orphaned-intent-rows',
             'passed': True, 'message': 'All intent rows have matching scenes'},
        ],
        'failures': [],
    }


def _failing_structural():
    """Return a validate_structure result that fails."""
    return {
        'passed': False,
        'checks': [
            {'category': 'identity', 'name': 'orphaned-intent-rows',
             'passed': True, 'message': 'All intent rows have matching scenes'},
            {'category': 'completeness', 'name': 'required-columns-act1-sc01',
             'passed': False, 'message': 'Scene act1-sc01 missing required columns: [goal]',
             'scene_id': 'act1-sc01', 'severity': 'blocking'},
        ],
        'failures': [
            {'category': 'completeness', 'name': 'required-columns-act1-sc01',
             'passed': False, 'message': 'Scene act1-sc01 missing required columns: [goal]',
             'scene_id': 'act1-sc01', 'severity': 'blocking'},
        ],
    }


def _passing_schema():
    """Return a validate_schema result that passes."""
    return {'passed': 10, 'failed': 0, 'skipped': 2, 'errors': []}


def _failing_schema():
    """Return a validate_schema result that fails."""
    return {
        'passed': 8,
        'failed': 2,
        'skipped': 1,
        'errors': [
            {'file': 'scenes.csv', 'row': 'act1-sc01', 'column': 'type',
             'constraint': 'enum', 'value': 'bogus',
             'allowed': ['action', 'character', 'plot']},
            {'file': 'scenes.csv', 'row': 'act1-sc02', 'column': 'word_count',
             'constraint': 'integer', 'value': 'abc'},
        ],
    }


def _no_errors_voice_profile():
    """Return a voice profile validation result with no errors."""
    return {'has_project_row': True, 'character_count': 3, 'errors': []}


def _errors_voice_profile():
    """Return a voice profile validation result with errors."""
    return {
        'has_project_row': False,
        'character_count': 0,
        'errors': [
            {'row': 'header', 'message': 'Voice profile has wrong columns.'},
        ],
    }


def _knowledge_result():
    """Return a validate_knowledge_granularity result."""
    return {
        'total_facts': 20,
        'total_scenes': 6,
        'facts_per_scene': 3.3,
        'warnings': [],
    }


def _knowledge_with_warnings():
    """Return a knowledge granularity result with warnings."""
    return {
        'total_facts': 30,
        'total_scenes': 6,
        'facts_per_scene': 5.0,
        'warnings': [
            {'type': 'long_name', 'id': 'fact-1', 'name': 'a very long fact name with many words',
             'word_count': 8},
            {'type': 'too_many_new_facts', 'scene_id': 'act1-sc01', 'new_fact_count': 7},
        ],
    }


def _structural_scores():
    """Return a structural_score result."""
    return {
        'overall_score': 0.82,
        'dimensions': [
            {'name': 'completeness', 'label': 'Completeness', 'score': 0.90,
             'weight': 0.15, 'target': 0.70, 'findings': []},
            {'name': 'pacing_shape', 'label': 'Pacing Shape', 'score': 0.60,
             'weight': 0.10, 'target': 0.70, 'findings': []},
            {'name': 'mice_health', 'label': 'MICE Health', 'score': 0.50,
             'weight': 0.15, 'target': 0.60,
             'findings': [{'message': 'Thread X is dormant for 5 scenes', 'severity': 'important'}]},
        ],
        'top_findings': [
            {'dimension': 'mice_health', 'message': 'Thread X is dormant for 5 scenes'},
        ],
    }


# ============================================================================
# main — missing scenes.csv
# ============================================================================


class TestMainMissingScenesCSV:
    """Test main() when scenes.csv does not exist."""

    def test_exits_with_error_when_no_scenes_csv(self, tmp_path, monkeypatch):
        """main() should sys.exit(1) if reference/scenes.csv is missing."""
        project_dir = str(tmp_path)
        os.makedirs(os.path.join(project_dir, 'reference'), exist_ok=True)
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_error_message_printed(self, tmp_path, monkeypatch, capsys):
        project_dir = str(tmp_path)
        os.makedirs(os.path.join(project_dir, 'reference'), exist_ok=True)
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit):
            main([])
        output = capsys.readouterr().out
        assert 'scenes.csv' in output


# ============================================================================
# main — default mode (structural + schema)
# ============================================================================


class TestMainDefault:
    """Test main() default mode — structural + schema validation."""

    def test_passing_both_exits_zero(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0

    def test_failing_structural_exits_one(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _failing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_failing_schema_exits_one(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _failing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_both_failing_exits_one(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _failing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _failing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1


# ============================================================================
# main — --no-schema
# ============================================================================


class TestMainNoSchema:
    """Test main() with --no-schema flag."""

    def test_skips_schema_validation(self, project_dir, monkeypatch):
        schema_called = []
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: schema_called.append(1) or _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main(['--no-schema'])
        assert exc_info.value.code == 0
        assert len(schema_called) == 0

    def test_no_schema_still_checks_structural(self, project_dir, monkeypatch):
        structural_called = []
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: (structural_called.append(1), _passing_structural())[1])
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit):
            main(['--no-schema'])
        assert len(structural_called) == 1

    def test_schema_none_treated_as_pass(self, project_dir, monkeypatch):
        """When --no-schema, schema is None and should be treated as pass."""
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main(['--no-schema'])
        assert exc_info.value.code == 0


# ============================================================================
# main — --json
# ============================================================================


class TestMainJson:
    """Test main() with --json flag."""

    def test_json_output_is_valid(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        # Suppress log() output so it doesn't mix with JSON
        monkeypatch.setattr('storyforge.cmd_validate.log', lambda msg: None)
        with pytest.raises(SystemExit):
            main(['--json'])
        output = capsys.readouterr().out
        data = json.loads(output)
        assert 'structural' in data
        assert 'schema' in data

    def test_json_contains_structural_result(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        monkeypatch.setattr('storyforge.cmd_validate.log', lambda msg: None)
        with pytest.raises(SystemExit):
            main(['--json'])
        data = json.loads(capsys.readouterr().out)
        assert data['structural']['passed'] is True

    def test_json_contains_schema_result(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _failing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        monkeypatch.setattr('storyforge.cmd_validate.log', lambda msg: None)
        with pytest.raises(SystemExit):
            main(['--json'])
        data = json.loads(capsys.readouterr().out)
        assert data['schema']['failed'] == 2


# ============================================================================
# main — --quiet
# ============================================================================


class TestMainQuiet:
    """Test main() with --quiet flag."""

    def test_quiet_no_output_on_pass(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main(['--quiet'])
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        # Quiet mode should not print human-readable output
        assert 'Structural validation' not in output

    def test_quiet_exit_code_one_on_failure(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _failing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc_info:
            main(['--quiet'])
        assert exc_info.value.code == 1


# ============================================================================
# main — --structural (scoring)
# ============================================================================


class TestMainStructuralScoring:
    """Test main() with --structural flag for structural scoring."""

    def test_structural_scoring_called(self, project_dir, monkeypatch):
        scoring_called = []
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        monkeypatch.setattr('storyforge.structural.structural_score',
                            lambda ref_dir: (scoring_called.append(1), _structural_scores())[1])
        monkeypatch.setattr('storyforge.structural.save_structural_scores',
                            lambda report, pd: None)
        monkeypatch.setattr('storyforge.structural.load_previous_scores',
                            lambda pd: None)
        monkeypatch.setattr('storyforge.structural.generate_structural_proposals',
                            lambda report, output_dir: None)
        with pytest.raises(SystemExit):
            main(['--structural'])
        assert len(scoring_called) == 1

    def test_structural_scoring_in_json_output(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        monkeypatch.setattr('storyforge.structural.structural_score',
                            lambda ref_dir: _structural_scores())
        monkeypatch.setattr('storyforge.structural.save_structural_scores',
                            lambda report, pd: None)
        monkeypatch.setattr('storyforge.structural.load_previous_scores',
                            lambda pd: None)
        monkeypatch.setattr('storyforge.structural.generate_structural_proposals',
                            lambda report, output_dir: None)
        monkeypatch.setattr('storyforge.cmd_validate.log', lambda msg: None)
        with pytest.raises(SystemExit):
            main(['--structural', '--json'])
        data = json.loads(capsys.readouterr().out)
        assert data['scores'] is not None
        assert data['scores']['overall_score'] == 0.82

    def test_previous_scores_loaded(self, project_dir, monkeypatch):
        prev_called = []
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        monkeypatch.setattr('storyforge.structural.structural_score',
                            lambda ref_dir: _structural_scores())
        monkeypatch.setattr('storyforge.structural.save_structural_scores',
                            lambda report, pd: None)
        monkeypatch.setattr('storyforge.structural.load_previous_scores',
                            lambda pd: (prev_called.append(1), None)[1])
        monkeypatch.setattr('storyforge.structural.generate_structural_proposals',
                            lambda report, output_dir: None)
        with pytest.raises(SystemExit):
            main(['--structural'])
        assert len(prev_called) == 1


# ============================================================================
# main — knowledge granularity
# ============================================================================


class TestMainKnowledgeGranularity:
    """Test main() behavior with knowledge.csv present."""

    def test_knowledge_validated_when_present(self, project_dir, monkeypatch, capsys):
        # knowledge.csv already exists in the fixture
        knowledge_path = os.path.join(project_dir, 'reference', 'knowledge.csv')
        assert os.path.isfile(knowledge_path), "fixture should have knowledge.csv"

        knowledge_called = []
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_knowledge_granularity',
                            lambda ref_dir, project_dir=None: (knowledge_called.append(1), _knowledge_result())[1])
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit):
            main([])
        assert len(knowledge_called) == 1

    def test_knowledge_skipped_when_missing(self, tmp_path, monkeypatch):
        """When knowledge.csv does not exist, validation is skipped."""
        project_dir = str(tmp_path)
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(ref_dir, exist_ok=True)
        # Create minimal scenes.csv
        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title\nsc1|1|Test\n')

        knowledge_called = []
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda rd: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda rd, pd=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_knowledge_granularity',
                            lambda rd, pd=None: (knowledge_called.append(1), _knowledge_result())[1])
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit):
            main([])
        assert len(knowledge_called) == 0


# ============================================================================
# main — voice profile
# ============================================================================


class TestMainVoiceProfile:
    """Test main() voice profile validation output."""

    def test_voice_profile_errors_logged(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _errors_voice_profile())
        with pytest.raises(SystemExit):
            main([])
        # Voice profile errors are logged via log(), check stdout
        output = capsys.readouterr().out
        assert 'Voice profile' in output or '1 issues' in output

    def test_voice_profile_valid_logged(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit):
            main([])
        output = capsys.readouterr().out
        assert 'Voice profile' in output or '3 characters' in output


# ============================================================================
# _print_human_readable — structural
# ============================================================================


class TestPrintHumanReadableStructural:
    """Test human-readable output for structural validation."""

    def test_passing_structural(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'Structural validation' in output
        assert 'Passed' in output

    def test_failing_structural(self, capsys):
        combined = {
            'structural': _failing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'Failed' in output
        assert 'act1-sc01' in output

    def test_failure_severity_displayed(self, capsys):
        combined = {
            'structural': _failing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert '[blocking]' in output


# ============================================================================
# _print_human_readable — schema
# ============================================================================


class TestPrintHumanReadableSchema:
    """Test human-readable output for schema validation."""

    def test_passing_schema(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': _passing_schema(),
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'Schema validation' in output
        assert 'Passed' in output

    def test_failing_schema_enum_error(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': _failing_schema(),
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'Failed' in output
        assert 'bogus' in output
        assert 'not in' in output

    def test_failing_schema_integer_error(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': _failing_schema(),
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'expected integer' in output

    def test_schema_errors_grouped_by_file(self, capsys):
        schema = {
            'passed': 5, 'failed': 2, 'skipped': 0,
            'errors': [
                {'file': 'scenes.csv', 'row': 'r1', 'column': 'c1',
                 'constraint': 'enum', 'value': 'x', 'allowed': ['a', 'b']},
                {'file': 'scene-intent.csv', 'row': 'r2', 'column': 'c2',
                 'constraint': 'enum', 'value': 'y', 'allowed': ['c', 'd']},
            ],
        }
        combined = {
            'structural': _passing_structural(),
            'schema': schema,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'scenes.csv' in output
        assert 'scene-intent.csv' in output

    def test_schema_registry_error(self, capsys):
        schema = {
            'passed': 5, 'failed': 1, 'skipped': 0,
            'errors': [
                {'file': 'scenes.csv', 'row': 'r1', 'column': 'pov',
                 'constraint': 'registry', 'value': 'Unknown',
                 'unresolved': ['Unknown'], 'registry': 'characters.csv'},
            ],
        }
        combined = {
            'structural': _passing_structural(),
            'schema': schema,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'not in' in output
        assert 'characters.csv' in output

    def test_schema_boolean_error(self, capsys):
        schema = {
            'passed': 5, 'failed': 1, 'skipped': 0,
            'errors': [
                {'file': 'scene-briefs.csv', 'row': 'r1', 'column': 'has_overflow',
                 'constraint': 'boolean', 'value': 'maybe'},
            ],
        }
        combined = {
            'structural': _passing_structural(),
            'schema': schema,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'expected true/false' in output

    def test_schema_mice_error(self, capsys):
        schema = {
            'passed': 5, 'failed': 1, 'skipped': 0,
            'errors': [
                {'file': 'scene-intent.csv', 'row': 'r1', 'column': 'mice_threads',
                 'constraint': 'mice', 'value': 'bad-entry',
                 'problems': [{'entry': 'bad-entry', 'reason': 'unknown thread'}]},
            ],
        }
        combined = {
            'structural': _passing_structural(),
            'schema': schema,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'unknown thread' in output

    def test_schema_scene_ids_error(self, capsys):
        schema = {
            'passed': 5, 'failed': 1, 'skipped': 0,
            'errors': [
                {'file': 'scene-briefs.csv', 'row': 'r1', 'column': 'continuity_deps',
                 'constraint': 'scene_ids', 'value': 'nonexistent',
                 'unresolved': ['nonexistent']},
            ],
        }
        combined = {
            'structural': _passing_structural(),
            'schema': schema,
            'knowledge': None,
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'not in scenes.csv' in output


# ============================================================================
# _print_human_readable — knowledge
# ============================================================================


class TestPrintHumanReadableKnowledge:
    """Test human-readable output for knowledge granularity."""

    def test_knowledge_healthy(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': _knowledge_result(),
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'Knowledge granularity' in output
        assert 'healthy' in output

    def test_knowledge_with_warnings(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': _knowledge_with_warnings(),
            'scores': None,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'has warnings' in output
        assert 'Long fact names' in output
        assert '5+ new facts' in output


# ============================================================================
# _print_human_readable — structural scoring
# ============================================================================


class TestPrintHumanReadableScoring:
    """Test human-readable output for structural scoring."""

    def test_scores_displayed(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': _structural_scores(),
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'Structural scoring' in output
        assert '0.82' in output

    def test_scores_with_previous_delta(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': _structural_scores(),
            'scores_previous': {'overall': 0.75, 'completeness': 0.85, 'pacing_shape': 0.60, 'mice_health': 0.50},
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        # Should show delta for overall
        assert '+' in output or '\u25b2' in output

    def test_top_findings_displayed(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': _structural_scores(),
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'Top findings' in output
        assert 'dormant' in output

    def test_below_target_dimensions(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': _structural_scores(),
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert '(below target)' in output

    def test_dormancy_recommendation(self, capsys):
        scores = _structural_scores()
        # Ensure a dormancy finding exists
        scores['dimensions'][2]['findings'] = [
            {'message': 'Thread X is dormant for 5 scenes', 'severity': 'important'}
        ]
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': scores,
            'scores_previous': None,
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'MICE dormancy' in output
        assert 'storyforge elaborate --mice-fill' in output

    def test_no_change_delta(self, capsys):
        combined = {
            'structural': _passing_structural(),
            'schema': None,
            'knowledge': None,
            'scores': _structural_scores(),
            'scores_previous': {'overall': 0.82, 'completeness': 0.90, 'pacing_shape': 0.60, 'mice_health': 0.50},
        }
        _print_human_readable(combined)
        output = capsys.readouterr().out
        assert 'no change' in output
