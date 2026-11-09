"""#643 (plan D6): checks of conformity to a craft framework (value shift,
turning point, action/sequel, emotional arc, goal/conflict/crisis/decision,
MICE nesting, scene-type rhythm, action/sequel balance) are advisory
everywhere: validate, the elaborate stage gates, status's ladder, `score
--level`, hone. Errors (a missing required column, duplicate seqs, a broken
told_by chain) still block."""

import os

import pytest

from storyforge.csv_cli import update_field
from storyforge.scoring_levels import LEVEL_NAMES


SCENES_HEADER = ('id|seq|title|act|pov|location|timeline_day|time_of_day|duration|'
                 'status')
INTENT_HEADER = ('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
                 'turning_point|characters|on_stage|mice_threads')
BRIEFS_HEADER = 'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out'


def _ref(tmp_path, scenes, intent, briefs=()):
    ref = tmp_path / 'reference'
    ref.mkdir(parents=True, exist_ok=True)
    (ref / 'scenes.csv').write_text('\n'.join([SCENES_HEADER, *scenes]) + '\n')
    (ref / 'scene-intent.csv').write_text('\n'.join([INTENT_HEADER, *intent]) + '\n')
    (ref / 'scene-briefs.csv').write_text('\n'.join([BRIEFS_HEADER, *briefs]) + '\n')
    return str(ref)


def _failures(report, check_prefix):
    return [f for f in report['failures'] if f['check'].startswith(check_prefix)]


# ============================================================================
# validate_structure
# ============================================================================

class TestValidateCraftColumns:
    def test_a_mapped_scene_with_no_craft_columns_passes(self, tmp_path):
        from storyforge.elaborate import validate_structure
        ref = _ref(tmp_path,
                   ['a-scene-happens-here|1|T|1|hero|loc|1|morning|1h|mapped'],
                   ['a-scene-happens-here|does a thing||||||hero|hero|'])
        report = validate_structure(ref)
        assert report['passed'] is True
        [craft] = _failures(report, 'craft-columns-')
        assert craft['severity'] == 'advisory'
        assert craft['category'] == 'completeness'
        assert craft['fields'] == ['action_sequel', 'emotional_arc', 'value_at_stake',
                                   'value_shift', 'turning_point']
        assert "needn't fit a framework" in craft['message']
        assert not _failures(report, 'required-columns-')

    def test_a_briefed_scene_needs_its_outcome_not_its_goal_or_conflict(self, tmp_path):
        from storyforge.elaborate import validate_structure
        scene = 'a-scene-happens-here|1|T|1|hero|loc|1|morning|1h|briefed'
        intent = 'a-scene-happens-here|does a thing|action|calm to fear|truth|+/-|action|hero|hero|'
        ok = validate_structure(_ref(tmp_path / 'ok', [scene], [intent],
                                     ['a-scene-happens-here|||yes|||k|k']))
        assert ok['passed'] is True
        assert _failures(ok, 'craft-columns-')[0]['fields'] == ['goal', 'conflict']

        bad = validate_structure(_ref(tmp_path / 'bad', [scene], [intent],
                                      ['a-scene-happens-here|g|c||||k|k']))
        assert bad['passed'] is False
        [missing] = _failures(bad, 'required-columns-')
        assert missing['fields'] == ['outcome']
        assert missing['severity'] == 'blocking'

    def test_a_missing_required_column_still_blocks(self, tmp_path):
        from storyforge.elaborate import validate_structure
        report = validate_structure(_ref(
            tmp_path, ['a-scene-happens-here|1|T|1|hero||1|morning|1h|mapped'],
            ['a-scene-happens-here|does a thing||||||hero|hero|']))
        assert report['passed'] is False
        [missing] = _failures(report, 'required-columns-')
        assert missing['fields'] == ['location']
        # the craft columns are still their own, advisory finding
        assert _failures(report, 'craft-columns-')[0]['severity'] == 'advisory'

    def test_framework_patterns_never_block(self, tmp_path):
        """Flat polarity, scene-type and turning-point runs, MICE threads
        interleaving or closing out of order: diagnostics only."""
        from storyforge.elaborate import validate_structure
        scenes, intent = [], []
        mice = ['+inquiry:who', '+inquiry:what', '-who', '-what']
        for i in range(1, 5):
            sid = f'scene-number-{"abcd"[i - 1]}-here'
            scenes.append(f'{sid}|{i}|T|1|hero|loc|1|morning|1h|mapped')
            intent.append(f'{sid}|does a thing|action|calm to calm|truth|+/+|action|'
                          f'hero|hero|{mice[i - 1]}')
        report = validate_structure(_ref(tmp_path, scenes, intent))
        checks = {f['check'] for f in report['failures']}
        assert {'flat-polarity', 'scene-type-rhythm', 'turning-point-variety',
                'mice-interleaving'} <= checks
        assert all(f['severity'] == 'advisory' for f in report['failures'])
        assert report['passed'] is True

    def test_errors_still_block(self, tmp_path):
        """A duplicate seq and an orphaned intent row are errors."""
        from storyforge.elaborate import validate_structure, split_failures
        report = validate_structure(_ref(
            tmp_path,
            ['first-scene-happens-here|1|T|1|hero|loc|1|morning|1h|mapped',
             'second-scene-happens-here|1|T|1|hero|loc|1|morning|1h|mapped'],
            ['first-scene-happens-here|f|action|a to b|v|+/-|action|hero|hero|',
             'second-scene-happens-here|f|action|a to b|v|+/-|action|hero|hero|',
             'nobody-has-this-scene|f|action|a to b|v|+/-|action|hero|hero|']))
        blocking, _advisory = split_failures(report['failures'])
        assert {f['check'] for f in blocking} == {'duplicate-seq', 'orphaned-intent-rows'}
        assert report['passed'] is False

    def test_gap_fill_still_sees_the_craft_columns(self, tmp_path):
        """analyze_gaps reads both a scene's blocking and advisory gaps."""
        from storyforge.elaborate import analyze_gaps
        result = analyze_gaps(_ref(
            tmp_path, ['a-scene-happens-here|1|T|1|hero|loc||morning|1h|mapped'],
            ['a-scene-happens-here|does a thing||||||hero|hero|']))
        assert result['groups']['intent-fields']['scenes'] == {
            'a-scene-happens-here': ['action_sequel', 'emotional_arc', 'value_at_stake',
                                     'value_shift', 'turning_point']}
        assert result['groups']['location-timeline']['scenes'] == {
            'a-scene-happens-here': ['timeline_day']}


# ============================================================================
# storyforge validate: two groups, exit code
# ============================================================================

class TestValidateCommand:
    def _run(self, project_dir, monkeypatch, capsys):
        from storyforge import cmd_validate
        monkeypatch.setattr(cmd_validate, 'detect_project_root', lambda: project_dir)
        with pytest.raises(SystemExit) as exc:
            cmd_validate.main(['--no-schema'])
        return exc.value.code, capsys.readouterr().out

    def test_craft_gaps_alone_exit_zero_in_the_advisory_group(
            self, project_dir, monkeypatch, capsys):
        intent = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        for field in ('value_shift', 'turning_point', 'emotional_arc'):
            update_field(intent, 'act1-sc01', field, '')
        code, out = self._run(project_dir, monkeypatch, capsys)
        assert code == 0
        assert 'Blocking (errors to fix):' not in out
        advisory = out.split('Advisory (diagnostics, not blocking')[1]
        assert 'craft-framework notes in' in advisory.split('---')[0]

    def test_an_error_is_in_the_blocking_group(self, project_dir, monkeypatch, capsys):
        ref = os.path.join(project_dir, 'reference')
        update_field(os.path.join(ref, 'scene-intent.csv'), 'act1-sc01', 'value_shift', '')
        update_field(os.path.join(ref, 'scenes.csv'), 'act1-sc01', 'location', '')
        code, out = self._run(project_dir, monkeypatch, capsys)
        assert code == 1
        blocking, advisory = out.split('Blocking (errors to fix):')[1].split(
            'Advisory (diagnostics, not blocking')
        assert "missing required columns: ['location']" in blocking
        assert 'value_shift' not in blocking
        assert "craft-framework notes in: ['value_shift']" in advisory


# ============================================================================
# elaborate's stage report
# ============================================================================

def test_the_stage_report_groups_blocking_before_advisory(tmp_path, capsys):
    from storyforge import cmd_elaborate
    failures = [{'severity': 'advisory', 'scene_id': 's1', 'message': 'no value shift'},
                {'severity': 'blocking', 'scene_id': 's2', 'message': 'no location'}]
    cmd_elaborate._log_failures(failures)
    out = capsys.readouterr().out
    assert out.index('Blocking (errors to fix):') < out.index('[blocking] s2: no location')
    assert out.index('[blocking] s2') < out.index('Advisory (diagnostics') < out.index(
        '[advisory] s1: no value shift')
    path = tmp_path / 'report.md'
    with open(path, 'w') as f:
        cmd_elaborate._write_failures(f, failures)
    text = path.read_text()
    assert text.index('## Blocking') < text.index('s2: no location') < text.index(
        '## Advisory') < text.index('s1: no value shift')
    cmd_elaborate._log_advisory_count(failures)
    assert '1 advisory finding(s), not blocking' in capsys.readouterr().out


# ============================================================================
# Floor checks, status and score --level
# ============================================================================

ARCH_HEADER = ('id|seq|title|summary|act|pov|spine_event|action_sequel|emotional_arc|'
               'value_at_stake|value_shift|turning_point')


def _architecture(project_dir, rows):
    path = os.path.join(project_dir, 'reference', 'architecture.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join([ARCH_HEADER, *rows]) + '\n')


class TestFloorChecks:
    def test_architecture_craft_columns_are_advisory(self, tmp_path):
        from storyforge.scoring_levels import blocking_failed, score_architecture
        _architecture(str(tmp_path), [
            f'anchor-number-{i}-here|{i}|T|s|1|hero||{"action" if i % 2 else "sequel"}'
            f'||||' for i in range(1, 17)])
        result = score_architecture(str(tmp_path))
        by_check = {c['check']: c for c in result['checks']}
        craft = next(c for name, c in by_check.items() if name.startswith('craft-framework'))
        assert craft['passed'] is False and craft['advisory'] is True
        assert 'emotional_arc' in craft['detail']
        assert by_check['all required columns populated (act, pov)']['passed'] is True
        assert result['advisory'] == 1
        assert blocking_failed(result) == 0

    def test_a_missing_pov_still_counts(self, tmp_path):
        from storyforge.scoring_levels import blocking_failed, score_architecture
        _architecture(str(tmp_path), [
            f'anchor-number-{i}-here|{i}|T|s|1|||{"action" if i % 2 else "sequel"}'
            f'|a to b|v|+/-|action' for i in range(1, 17)])
        result = score_architecture(str(tmp_path))
        assert blocking_failed(result) == 1
        assert result['advisory'] == 0

    def test_action_sequel_balance_is_advisory(self, tmp_path):
        from storyforge.scoring_levels import blocking_failed, score_architecture
        _architecture(str(tmp_path), [
            f'anchor-number-{i}-here|{i}|T|s|1|hero||action|a to b|v|+/-|action'
            for i in range(1, 17)])
        result = score_architecture(str(tmp_path))
        balance = next(c for c in result['checks'] if c['check'].startswith('both action'))
        assert balance['passed'] is False and balance['advisory'] is True
        assert blocking_failed(result) == 0

    def test_briefs_need_outcome_not_crisis_or_decision(self, tmp_path):
        from storyforge.scoring_levels import blocking_failed, score_briefs
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scene-briefs.csv').write_text(f'{BRIEFS_HEADER}\ns|||yes||||\n')
        result = score_briefs(str(tmp_path))
        assert blocking_failed(result) == 0 and result['advisory'] == 1
        (ref / 'scene-briefs.csv').write_text(f'{BRIEFS_HEADER}\ns|g|c||cr|d||\n')
        assert blocking_failed(score_briefs(str(tmp_path))) == 1

    def test_an_accepted_advisory_check_is_counted_once(self, tmp_path):
        from storyforge.scoring_levels import _check, _result, blocking_failed
        check = _check('c', False, advisory=True)
        check['accepted'] = True
        result = _result(4, 'architecture', [check])
        assert (result['failed'], result['accepted'], result['advisory']) == (1, 1, 0)
        assert blocking_failed(result) == 0

    def test_accepting_an_advisory_check_recomputes_its_count(self, tmp_path):
        """#643's review T3: through `score_level`, so `_apply_overrides`
        recomputes `advisory` (left alone it would make blocking_failed -1)."""
        from storyforge.scoring_levels import _BRIEF_CRAFT_CHECK, blocking_failed, score_level
        from storyforge.scoring_state import append_override
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scene-briefs.csv').write_text(f'{BRIEFS_HEADER}\ns|||yes||||\n')
        before = score_level(str(tmp_path), 6)
        assert (before['accepted'], before['advisory']) == (0, 1)
        append_override('level-6', 'level-quality', _BRIEF_CRAFT_CHECK, 'accepted',
                        'no goals on purpose', '2026-11-09', project_dir=str(tmp_path))
        after = score_level(str(tmp_path), 6)
        assert (after['failed'], after['accepted'], after['advisory']) == (1, 1, 0)
        assert blocking_failed(after) == 0

    @pytest.mark.parametrize('level,old,rows', [
        (4, 'all required columns populated',
         [f'anchor-number-{i}-here|{i}|T|s|1|||{"action" if i % 2 else "sequel"}||||'
          for i in range(1, 17)]),
        (6, 'goal/conflict/outcome/crisis/decision populated', None),
    ])
    def test_an_override_on_a_checks_former_name_still_applies(self, tmp_path, level, old,
                                                                 rows):
        """#643's review C4, CR-2, TD-1: #643 split one check at L4 and at L6
        into a blocking and an advisory half; an author's acceptance of the
        old check still covers both."""
        from storyforge.scoring_levels import blocking_failed, score_level
        from storyforge.scoring_state import append_override
        if rows is None:
            ref = tmp_path / 'reference'
            ref.mkdir()
            (ref / 'scene-briefs.csv').write_text(f'{BRIEFS_HEADER}\ns||||||||\n')
        else:
            _architecture(str(tmp_path), rows)
        before = score_level(str(tmp_path), level)
        assert blocking_failed(before) >= 1
        append_override(f'level-{level}', 'level-quality', old, 'accepted', 'on purpose',
                        '2026-11-09', project_dir=str(tmp_path))
        after = score_level(str(tmp_path), level)
        split = [c for c in after['checks']
                 if c['check'].startswith(('all required', 'outcome', 'craft-framework'))]
        assert len(split) == 2 and all(c['accepted'] for c in split)
        assert blocking_failed(after) == blocking_failed(before) - 1

    def test_each_split_checks_name_lists_its_columns(self):
        """#643's review TD-3: the names are fixed strings, the split comes
        from CRAFT_FRAMEWORK_COLUMNS; they must agree."""
        from storyforge import scoring_levels as sl
        for columns, required_name, craft_name in (
                (sl._ARCHITECTURE_COLUMNS, sl._ARCH_REQUIRED_CHECK, sl._ARCH_CRAFT_CHECK),
                (sl._BRIEF_COLUMNS, sl._BRIEF_REQUIRED_CHECK, sl._BRIEF_CRAFT_CHECK)):
            required, craft = sl._split_craft(columns)
            assert craft_name.endswith(f"({', '.join(craft)})")
            assert all(c in required_name for c in required)

    def test_score_level_prints_advisory_apart(self, capsys):
        from storyforge.cmd_score import _print_level_result
        _print_level_result({'level': 6, 'name': 'briefs', 'passed': 1, 'failed': 1,
                             'accepted': 0, 'advisory': 1, 'checks': [
                                 {'check': 'outcome populated', 'passed': True},
                                 {'check': 'craft-framework fields populated', 'passed': False,
                                  'detail': 'x', 'advisory': True}]})
        out = capsys.readouterr().out
        assert '1 passed, 0 failed (+ 1 advisory)' in out
        assert '! craft-framework fields populated (advisory) — x' in out


class TestStatus:
    def _floors(self, advisory_passed):
        return [{'level': lvl, 'name': name, 'passed': 1, 'failed': int(not advisory_passed),
                 'accepted': 0, 'advisory': int(not advisory_passed), 'checks': [
                     {'check': 'ok', 'passed': True, 'detail': ''},
                     {'check': 'craft-framework fields populated', 'passed': advisory_passed,
                      'detail': '' if advisory_passed else '1 brief(s) missing fields',
                      'advisory': True}]}
                for lvl, name in sorted(LEVEL_NAMES.items())]

    def test_a_rung_with_only_advisory_failures_is_solid(self, tmp_path, monkeypatch):
        from storyforge import status
        monkeypatch.setattr(status, 'score_all_levels',
                            lambda pd, medium='novel': self._floors(False))
        monkeypatch.setattr(status, 'artifact_present', lambda pd, level: True)
        assert {r['state'] for r in status.ladder_states(str(tmp_path))} == {'solid'}

    def test_craft_failures_are_advisory_lines_not_blockers(self, project_dir, monkeypatch):
        from storyforge import cmd_status, status
        verdict = status.build_status(project_dir)
        craft = [a for a in verdict['advisory'] if a['source'] == status.CRAFT_ADVISORY_SOURCE]
        # #643's review TD-2: records in gate.read_advisory's shape, not prefixed strings
        assert craft == [{
            'scene_id': '', 'command': 'storyforge score --level 6',
            'source': status.CRAFT_ADVISORY_SOURCE, 'quote': '', 'stale': '',
            'finding': ('L6 briefs: craft-framework fields populated (goal, conflict, '
                        'crisis, decision) (1 brief(s) missing fields; first: new-x1 missing '
                        'goal, conflict, crisis, decision)')}]
        assert not any('craft-framework' in b['detail'] for b in verdict['blockers'])
        l6 = next(r for r in verdict['ladder'] if r['level'] == 6)
        assert 'goal' not in l6['detail']   # the rung's detail is its blocking failure
        out = cmd_status.render_human(verdict)
        assert "ADVISORY: 1 craft-framework check(s) not met" in out
        assert '  L6 briefs: craft-framework fields populated' in out
        assert '[storyforge score --level 6]' in out
        assert 'broken promise' not in out

    def test_an_absent_rungs_craft_checks_are_not_listed(self, tmp_path):
        from storyforge import status
        assert status.craft_advisory([]) == []
        floors = self._floors(False)
        assert len(status.craft_advisory(floors)) == len(floors)
        assert status.craft_advisory(self._floors(True)) == []


# ============================================================================
# hone
# ============================================================================

class TestHone:
    def test_detect_gaps_marks_craft_fields_advisory(self):
        from storyforge.hone import detect_gaps
        gaps = detect_gaps({'s': {'id': 's', 'status': 'briefed'}}, {}, {})
        by_field = {g['field']: g['advisory'] for g in gaps}
        assert by_field['function'] is False and by_field['outcome'] is False
        assert all(by_field[f] for f in ('value_at_stake', 'value_shift', 'emotional_arc',
                                         'goal', 'conflict', 'crisis', 'decision'))

    def test_hone_intent_reports_a_flat_arc_without_rewriting_it(
            self, tmp_path, monkeypatch, capsys):
        from storyforge import api
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.hone import hone_intent

        def no_call(*a, **kw):
            raise AssertionError('hone rewrote a craft-framework diagnostic')
        monkeypatch.setattr(api, 'invoke_to_file', no_call)
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scene-intent.csv').write_text(
            f'{INTENT_HEADER}\n'
            's|Kael reads the letter and refuses|action|static dread|truth|-/-|action|'
            'kael|kael|\n')
        (ref / 'scenes.csv').write_text(f'{SCENES_HEADER}\ns|1|T|1|kael|here|1|morning|1h|drafted\n')
        (ref / 'scene-briefs.csv').write_text(f'{BRIEFS_HEADER}\ns|g|c|yes|||k|k\n')
        before = (ref / 'scene-intent.csv').read_text()
        result = hone_intent(str(ref), str(tmp_path), model='m',
                             log_dir=str(tmp_path / 'logs'), coaching_level='full')
        assert result['fields_rewritten'] == 0
        assert (ref / 'scene-intent.csv').read_text() == before
        assert _read_csv_as_map(str(ref / 'scene-intent.csv'))['s']['emotional_arc'] == 'static dread'
        out = capsys.readouterr().out
        assert 'craft-framework finding(s) reported, not rewritten' in out
        assert 's.emotional_arc (flat)' in out

    def test_diagnose_lists_craft_fields_apart_from_gaps(self, project_dir, capsys):
        from storyforge.cmd_hone import _run_diagnose
        briefs = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
        for field in ('goal', 'outcome', 'crisis'):
            update_field(briefs, 'act1-sc01', field, '')
        _run_diagnose(os.path.join(project_dir, 'reference'), project_dir, None)
        gaps = capsys.readouterr().out.split('=== Gaps ===')[1].split('===')[0]
        required, craft = gaps.split('Craft-framework fields empty (advisory, not gaps')
        assert 'act1-sc01: missing outcome' in required
        assert 'goal' not in required
        assert 'act1-sc01: goal, crisis' in craft
