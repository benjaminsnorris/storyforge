"""storyforge audit: the digest, its scopes, marking, and the immediate tier."""

import json
import os

import pytest

from storyforge import audit, cmd_audit, ledger


def _fact(rid, scene_id, type_, subject='', mutable='state', **kw):
    row = {c: '' for c in ledger.COLUMNS}
    row.update(id=rid, scene_id=scene_id, type=type_, subject=subject,
               statement=f'{rid} holds', origin='prose', status='binding',
               mutable=mutable, introduced_by='draft')
    row.update(kw)
    return row


#: Fixture scenes: act1-sc01, act1-sc02, new-x1 (act 1); act2-sc01..03 (act 2).
#: Every fixture fact is origin=migrated.
NEW = [
    _fact('eyes', 'act1-sc01', 'trait', 'dorren-hayle', 'fixed'),
    _fact('cousin', 'act1-sc02', 'relationship', 'tessa-merrin', 'fixed'),
    _fact('pell-knows', 'act1-sc01', 'knowledge', known_by='pell'),
    _fact('cloak', 'new-x1', 'physical', 'kael-maren'),
    _fact('day-two', 'new-x1', 'timeline'),
    _fact('ridge', 'act2-sc02', 'world'),
    _fact('backstory', '', 'trait', 'kael-maren', 'fixed'),
]


@pytest.fixture
def project(project_dir, monkeypatch, mock_git):
    ledger.save(project_dir, ledger.load(project_dir) + [dict(r) for r in NEW],
                command='test')
    monkeypatch.setattr(cmd_audit, 'detect_project_root', lambda: str(project_dir))
    return str(project_dir)


def _json(capsys, *argv):
    cmd_audit.main(['--json', *argv])
    return json.loads(capsys.readouterr().out)


def _ids(result):
    return [f['id'] for f in result['facts']]


class TestDigest:
    def test_default_is_the_earliest_act_with_unreviewed_facts(self, project, capsys):
        result = _json(capsys)
        assert result['act'] == '1'
        # Backstory (no scene) belongs to the first digest; act 2's fact waits
        assert set(_ids(result)) == {'backstory', 'eyes', 'cousin', 'pell-knows',
                                     'cloak', 'day-two'}
        assert result['remaining'] == {'2': 1}

    def test_tiers_fixed_then_relationship_knowledge_then_physical(self, project, capsys):
        result = _json(capsys)
        assert [g['tier'] for g in result['groups']] == [
            'fixed', 'relationship-knowledge', 'physical', 'other']
        fixed = result['groups'][0]['subjects']
        assert {s['subject']: s['facts'] for s in fixed} == {
            'kael-maren': ['backstory'], 'dorren-hayle': ['eyes'],
            'tessa-merrin': ['cousin']}

    def test_migrated_facts_are_left_out_and_said_so(self, project, capsys):
        result = _json(capsys)
        assert not any(f['origin'] == 'migrated' for f in result['facts'])
        assert any('migrated fact(s) left out' in n for n in result['notes'])
        assert 'archive-key-dorren' in _ids(_json(capsys, '--include-migrated'))

    def test_marking_the_act_moves_the_digest_on(self, project, capsys):
        cmd_audit.main(['--mark', 'seen', 'all'])
        capsys.readouterr()
        result = _json(capsys)
        assert result['act'] == '2' and _ids(result) == ['ridge']

    def test_human_output(self, project, capsys):
        cmd_audit.main([])
        out = capsys.readouterr().out
        assert out.startswith('Audit: act 1 — 6 facts to review')
        assert out.index('FIXED FACTS') < out.index('RELATIONSHIP AND KNOWLEDGE') \
            < out.index('PHYSICAL STATE') < out.index('OTHER STATE FACTS')
        assert 'Still to review after this act — act 2: 1' in out
        assert 'Mark them: storyforge audit --mark seen all   (' in out

    def test_nothing_to_review(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr(cmd_audit, 'detect_project_root', lambda: str(project_dir))
        cmd_audit.main([])
        assert capsys.readouterr().out.startswith('Audit: every act — nothing to review')


class TestScopes:
    def test_act(self, project, capsys):
        assert _ids(_json(capsys, '--act', '2')) == ['ridge']

    def test_all(self, project, capsys):
        assert len(_ids(_json(capsys, '--all'))) == len(NEW)

    def test_character_matches_subject_or_known_by(self, project, capsys):
        assert _ids(_json(capsys, '--character', 'kael-maren')) == ['backstory', 'cloak']
        assert _ids(_json(capsys, '--character', 'pell')) == ['pell-knows']

    def test_scene_range_in_reading_order(self, project, capsys):
        assert _ids(_json(capsys, '--scenes', 'act1-sc02..new-x1')) == [
            'cousin', 'cloak', 'day-two']
        # Either end first
        assert _ids(_json(capsys, '--scenes', 'new-x1..act1-sc02')) == [
            'cousin', 'cloak', 'day-two']
        assert _ids(_json(capsys, '--scenes', 'act2-sc02')) == ['ridge']

    def test_unknown_scene_is_an_error(self, project):
        with pytest.raises(SystemExit) as e:
            cmd_audit.main(['--scenes', 'nope..new-x1'])
        assert e.value.code == 1

    def test_thread_through_its_scenes(self, project, capsys):
        # scene-intent: +inquiry:map-anomaly in act1-sc01, -inquiry:map-anomaly
        # in act2-sc03 (one of several entries)
        assert audit.thread_scenes(project, 'map-anomaly') == {'act1-sc01', 'act2-sc03'}
        assert _ids(_json(capsys, '--thread', 'map-anomaly')) == ['eyes', 'pell-knows']
        assert _ids(_json(capsys, '--thread', 'uncharted-reaches')) == ['ridge']

    def test_a_registered_thread_no_scene_carries_says_so(self, project, capsys):
        path = os.path.join(project, 'reference', 'mice-threads.csv')
        with open(path, 'a') as f:
            f.write('quiet-thread|Quiet thread|event|\n')
        result = _json(capsys, '--thread', 'quiet-thread')
        assert result['facts'] == []
        assert any("no scene in scene-intent.csv carries the thread 'quiet-thread'" in n
                   for n in result['notes'])

    def test_scopes_combine(self, project, capsys):
        assert _ids(_json(capsys, '--act', '1', '--character', 'kael-maren')) == ['cloak']

    def test_include_reviewed(self, project, capsys):
        cmd_audit.main(['--mark', 'seen', 'eyes'])
        capsys.readouterr()
        assert 'eyes' not in _ids(_json(capsys, '--all'))
        assert 'eyes' in _ids(_json(capsys, '--all', '--include-reviewed'))


class TestMark:
    def _row(self, project, rid):
        return {r['id']: r for r in ledger.load(project)}[rid]

    def test_seen_sets_reviewed_logs_and_commits(self, project, capsys, mock_git):
        cmd_audit.main(['--mark', 'seen', 'eyes,cousin'])
        assert self._row(project, 'eyes')['reviewed'].startswith('seen:')
        assert self._row(project, 'eyes')['status'] == 'binding'
        log = [e for e in audit.read_log(project) if e['command'] == 'audit']
        assert [(e['fact_id'], e['change']) for e in log] == [
            ('eyes', 'reviewed'), ('cousin', 'reviewed')]
        commits = [c for c in mock_git.calls if c[0] == 'commit_and_push']
        assert commits == [('commit_and_push', 'Audit: mark 2 facts seen',
                            ['reference/commitments.csv', 'working/audit-log.csv',
                             'working/.audit-snapshot.csv', 'working/gate-pending.csv'])]
        assert ('ensure_on_branch', 'audit') in mock_git.calls

    def test_rejected_sets_status_and_lists_scenes_to_recheck(self, project, capsys):
        result = _json(capsys, '--mark', 'rejected', 'archive-key-dorren')
        row = self._row(project, 'archive-key-dorren')
        assert row['status'] == 'rejected' and row['reviewed'].startswith('rejected:')
        info = result['recheck']['archive-key-dorren']
        assert info['scene'] == 'act1-sc02'
        assert info['recheck'] == ['new-x1']                  # its brief names it; has prose
        assert info['not_listed'] == ['act2-sc03 (no prose yet)']
        entry = audit.read_log(project)[-1]
        assert (entry['fact_id'], entry['change']) == ('archive-key-dorren', 'rejected')
        from storyforge import gate
        row = gate.pending(project)['new-x1']
        assert row['command'] == gate.RECHECK and 'archive-key-dorren rejected' in row['reason']

    def test_a_rejected_facts_dependents_by_subject_are_listed(self, project, capsys):
        ledger.save(project, ledger.load(project) + [
            _fact('cloak-later', 'act2-sc01', 'physical', 'kael-maren')], command='test')
        result = _json(capsys, '--mark', 'rejected', 'cloak')
        assert result['recheck']['cloak']['recheck'] == ['act2-sc01']

    def test_a_dry_run_lists_nothing_pending(self, project, capsys):
        from storyforge import gate
        cmd_audit.main(['--mark', 'rejected', 'archive-key-dorren', '--dry-run'])
        out = capsys.readouterr().out
        assert 'would list for a re-check' in out and gate.pending(project) == {}

    def test_a_scene_waiting_for_another_reason_is_not_listed(self, project, capsys):
        from storyforge import gate
        gate.mark_pending(project, 'new-x1', 'draft', 'its own problem')
        result = _json(capsys, '--mark', 'rejected', 'archive-key-dorren')
        assert result['recheck']['archive-key-dorren']['recheck'] == []
        assert 'new-x1 (already waiting on the gate: draft)' in \
            result['recheck']['archive-key-dorren']['not_listed']
        assert gate.pending(project)['new-x1']['reason'] == 'its own problem'

    def test_a_fact_with_no_subject_and_no_link_is_said(self, project, capsys):
        result = _json(capsys, '--mark', 'rejected', 'day-two')
        assert 'no subject' in result['recheck']['day-two']['unrelated']

    def test_explicit_ids_are_not_limited_to_the_current_act(self, project, capsys):
        cmd_audit.main(['--mark', 'seen', 'ridge'])
        assert self._row(project, 'ridge')['reviewed'].startswith('seen:')

    def test_all_follows_the_scope(self, project, capsys):
        cmd_audit.main(['--mark', 'seen', 'all', '--character', 'kael-maren'])
        rows = {r['id']: r for r in ledger.load(project)}
        assert rows['cloak']['reviewed'] and rows['backstory']['reviewed']
        assert not rows['eyes']['reviewed']

    def test_unknown_id_changes_nothing(self, project, mock_git):
        before = ledger.load(project)
        with pytest.raises(SystemExit):
            cmd_audit.main(['--mark', 'seen', 'eyes', 'no-such-fact'])
        assert ledger.load(project) == before
        assert not [c for c in mock_git.calls if c[0] == 'commit_and_push']

    def test_seen_on_a_rejected_fact_is_refused(self, project, capsys):
        cmd_audit.main(['--mark', 'rejected', 'eyes'])
        with pytest.raises(SystemExit):
            cmd_audit.main(['--mark', 'seen', 'eyes'])
        assert self._row(project, 'eyes')['status'] == 'rejected'

    def test_dry_run_changes_nothing(self, project, capsys, mock_git):
        before = ledger.load(project)
        cmd_audit.main(['--mark', 'seen', 'all', '--dry-run'])
        assert 'Would mark 6 facts seen' in capsys.readouterr().out
        assert ledger.load(project) == before
        assert not [c for c in mock_git.calls if c[0] == 'commit_and_push']

    def test_ids_need_mark(self, project):
        with pytest.raises(SystemExit):
            cmd_audit.parse_args(['eyes'])
        with pytest.raises(SystemExit):
            cmd_audit.parse_args(['--mark', 'seen'])

    def test_mark_helper_stamps_the_date(self):
        rows = [_fact('a', 's', 'trait')]
        assert audit.mark(rows, ['a'], 'seen', date='2026-10-30') == ['a']
        assert rows[0]['reviewed'] == 'seen:2026-10-30'


class TestRegistered:
    def test_in_commands(self):
        from storyforge.__main__ import COMMANDS
        assert COMMANDS['audit'] == 'storyforge.cmd_audit'


class TestHaltingConditions:
    LEDGER = [_fact('eyes', 'act1-sc01', 'trait', 'dorren-hayle', 'fixed',
                    statement='Dorren has grey eyes'),
              _fact('cloak', 'new-x1', 'physical', 'kael-maren'),
              _fact('old-fixed', 'act1-sc01', 'trait', 'pell', 'fixed',
                    status='superseded')]

    def test_none(self):
        proposed = [_fact('new', 'act2-sc01', 'physical', 'kael-maren',
                          supersedes='cloak')]
        assert audit.halting_conditions(proposed, self.LEDGER) == []

    def test_superseding_a_binding_fixed_fact(self):
        halts = audit.halting_conditions(
            [_fact('new-eyes', 'act2-sc01', 'trait', 'dorren-hayle', 'fixed',
                   supersedes='eyes')], self.LEDGER)
        assert [(h.kind, h.fact_id) for h in halts] == [('supersedes-fixed', 'new-eyes')]
        assert 'grey eyes' in halts[0].detail

    def test_a_fixed_fact_that_is_no_longer_binding_does_not_halt(self):
        assert audit.halting_conditions(
            [_fact('n', 's', 'trait', supersedes='old-fixed')], self.LEDGER) == []

    def test_changing_a_fixed_fact_in_place(self):
        halts = audit.halting_conditions(
            [_fact('eyes', 'act1-sc01', 'trait', 'dorren-hayle', 'fixed',
                   statement='Dorren has brown eyes')], self.LEDGER)
        assert [h.kind for h in halts] == ['changes-fixed']
        # The same statement re-extracted is not a change
        assert audit.halting_conditions([dict(self.LEDGER[0])], self.LEDGER) == []

    def test_low_confidence(self):
        halts = audit.halting_conditions(
            [_fact('maybe', 's', 'trait', confidence='Low')], self.LEDGER)
        assert [h.kind for h in halts] == ['low-confidence']
        assert audit.halting_conditions(
            [_fact('sure', 's', 'trait', confidence='high')], self.LEDGER) == []


def _hint(out):
    line = next(l for l in out.splitlines() if l.startswith('Mark them: '))
    return line[len('Mark them: '):].split('   (')[0]


class TestMarkHint:
    """The listing's `Mark them:` command marks exactly what it listed."""

    @pytest.mark.parametrize('scope', [[], ['--act', '2'], ['--character', 'kael-maren'],
                                       ['--scenes', 'act1-sc02..new-x1'],
                                       ['--include-migrated']])
    def test_running_the_hint_leaves_nothing_shown_unreviewed(self, project, capsys, scope):
        import shlex
        cmd_audit.main(scope)
        out = capsys.readouterr().out
        shown = [line.split(':')[0].strip() for line in out.splitlines()
                 if line.startswith('    ') and not line.startswith('      ')]
        assert shown
        words = shlex.split(_hint(out))
        assert words[:2] == ['storyforge', 'audit']
        cmd_audit.main(words[2:])
        capsys.readouterr()
        rows = {r['id']: r for r in ledger.load(project)}
        assert [i for i in shown if not rows[i]['reviewed']] == []
        if not scope:
            assert 'backstory' in shown   # the no-scene fact the default lists

    def test_hint_carries_the_scope(self, project, capsys):
        cmd_audit.main(['--character', 'Kael', '--include-migrated'])
        assert _hint(capsys.readouterr().out) == (
            'storyforge audit --mark seen all --character Kael --include-migrated')


class TestJsonIsPure:
    def test_a_push_warning_goes_to_stderr(self, project, capsys, monkeypatch):
        from storyforge.common import log

        def commit(project_dir, message, paths=None):
            log('WARNING: could not push storyforge/x; the commit is only local')
            return True
        monkeypatch.setattr(cmd_audit, 'commit_and_push', commit)
        cmd_audit.main(['--json', '--mark', 'seen', 'eyes'])
        captured = capsys.readouterr()
        assert json.loads(captured.out)['marked'] == ['eyes']
        assert 'WARNING: could not push' in captured.err

    def test_an_error_goes_to_stderr(self, project, capsys):
        with pytest.raises(SystemExit):
            cmd_audit.main(['--json', '--act', '9'])
        captured = capsys.readouterr()
        assert captured.out == '' and 'ERROR' in captured.err


class TestScopeErrors:
    def _scenes(self, project, transform):
        path = os.path.join(project, 'reference', 'scenes.csv')
        with open(path) as f:
            lines = f.read().splitlines()
        with open(path, 'w') as f:
            f.write('\n'.join(transform(lines)) + '\n')

    def _fails(self, capsys, *argv, says):
        with pytest.raises(SystemExit) as e:
            cmd_audit.main(list(argv))
        assert e.value.code == 1
        assert says in capsys.readouterr().out

    def test_act_with_no_scenes(self, project, capsys):
        self._fails(capsys, '--act', '9',
                    says="no scene in reference/scenes.csv has act '9' (acts: 1, 2)")

    def test_part_stands_in_for_a_missing_act_column(self, project, capsys):
        # thornwall: scenes.csv has `part`, no `act`. Fixture: part == act here
        def drop_act(lines):
            header = lines[0].split('|')
            i = header.index('act')
            return ['|'.join(c for n, c in enumerate(l.split('|')) if n != i) for l in lines]
        self._scenes(project, drop_act)
        result = _json(capsys, '--act', '2')
        assert _ids(result) == ['ridge']
        assert 'acts read from scenes.csv `part` (it has no `act` column)' in result['notes']

    def test_act_with_neither_column(self, project, capsys):
        def drop(lines):
            header = lines[0].split('|')
            keep = [n for n, h in enumerate(header) if h not in ('act', 'part')]
            return ['|'.join(l.split('|')[n] for n in keep) for l in lines]
        self._scenes(project, drop)
        self._fails(capsys, '--act', '1', says='has no `act` or `part` column')
        result = _json(capsys)     # the default digest says why it isn't per act
        assert any('not split per act' in n for n in result['notes'])

    def test_unknown_character(self, project, capsys):
        self._fails(capsys, '--character', 'nobody',
                    says="'nobody' is not a character id, name or alias")

    def test_character_by_name_or_alias(self, project, capsys):
        assert _ids(_json(capsys, '--character', 'Kael')) == ['backstory', 'cloak']

    def test_scene_endpoints(self, project, capsys):
        self._fails(capsys, '--scenes', 'act1-sc01..nope',
                    says="'nope' is not a scene in reference/scenes.csv")

    def test_unknown_thread(self, project, capsys):
        self._fails(capsys, '--thread', 'zzz', says="'zzz' is not a thread")

    def test_scope_flags_with_explicit_ids_warn(self, project, capsys):
        cmd_audit.main(['--mark', 'seen', 'ridge', '--act', '1'])
        out = capsys.readouterr().out
        assert 'WARNING: --act 1 ignored: explicit ids are marked' in out
        assert {r['id']: r for r in ledger.load(project)}['ridge']['reviewed']


class TestHandEdits:
    def _edit(self, project, old, new):
        path = ledger.ledger_path(project)
        with open(path) as f:
            text = f.read()
        assert old in text
        with open(path, 'w') as f:
            f.write(text.replace(old, new))

    def test_an_audit_run_logs_a_hand_edit(self, project, capsys):
        self._edit(project, 'eyes holds', 'eyes are grey')
        result = _json(capsys, '--all')
        entry = audit.read_log(project)[-1]
        assert (entry['fact_id'], entry['change'], entry['command'], entry['columns']) == (
            'eyes', 'changed', 'hand-edit', 'statement')
        assert any('outside Storyforge' in n for n in result['notes'])
        # Logged once: the next run finds nothing new
        n = len(audit.read_log(project))
        _json(capsys, '--all')
        assert len(audit.read_log(project)) == n

    def test_a_ledger_write_logs_the_hand_edit_first(self, project):
        self._edit(project, 'eyes holds', 'eyes are grey')
        rows = ledger.load(project)
        rows[-1]['statement'] = 'backstory changed by hone'
        ledger.save(project, rows, command='hone')
        tail = [(e['fact_id'], e['command']) for e in audit.read_log(project)[-2:]]
        assert tail == [('eyes', 'hand-edit'), ('backstory', 'hone')]

    def test_an_added_row_is_a_hand_edit_whatever_its_introduced_by(self, project, capsys):
        path = ledger.ledger_path(project)
        row = _fact('typed-in', 'act1-sc01', 'trait', introduced_by='draft')
        with open(path, 'a') as f:
            f.write('|'.join(row[c] for c in ledger.COLUMNS) + '\n')
        _json(capsys)
        entry = audit.read_log(project)[-1]
        assert (entry['fact_id'], entry['change'], entry['command']) == (
            'typed-in', 'added', 'hand-edit')

    def test_no_snapshot_starts_one_and_logs_nothing(self, project, capsys):
        os.remove(audit.snapshot_path(project))
        self._edit(project, 'eyes holds', 'eyes are grey')
        n = len(audit.read_log(project))
        _json(capsys)
        assert len(audit.read_log(project)) == n
        assert os.path.isfile(audit.snapshot_path(project))

    def test_marking_commits_the_snapshot(self, project, capsys, mock_git):
        cmd_audit.main(['--mark', 'seen', 'eyes'])
        commit = [c for c in mock_git.calls if c[0] == 'commit_and_push'][-1]
        assert audit.SNAPSHOT_PATH in commit[2]


class TestMarkEdges:
    def test_re_rejecting_is_a_no_op(self, project, capsys):
        cmd_audit.main(['--mark', 'rejected', 'eyes'])
        n = len(audit.read_log(project))
        cmd_audit.main(['--mark', 'rejected', 'eyes'])
        assert 'Marked 0 facts rejected (already marked)' in capsys.readouterr().out
        assert len(audit.read_log(project)) == n

    def test_rejecting_a_superseded_fact_is_refused(self, project, capsys):
        rows = ledger.load(project)
        for r in rows:
            if r['id'] == 'cloak':
                r['status'] = 'superseded'
        ledger.save(project, rows, command='test')
        with pytest.raises(SystemExit):
            cmd_audit.main(['--mark', 'rejected', 'cloak'])
        assert 'superseded, so no longer binding: cloak' in capsys.readouterr().out
        assert {r['id']: r for r in ledger.load(project)}['cloak']['status'] == 'superseded'

    def test_a_failed_commit_is_reported(self, project, capsys, mock_git):
        mock_git.commit_success = False
        with pytest.raises(SystemExit) as e:
            cmd_audit.main(['--mark', 'seen', 'eyes'])
        assert e.value.code == 1
        assert 'but the commit failed' in capsys.readouterr().out
