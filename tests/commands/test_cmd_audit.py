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
        assert 'storyforge audit --mark seen all --act 1' in out

    def test_nothing_to_review(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr(cmd_audit, 'detect_project_root', lambda: str(project_dir))
        cmd_audit.main([])
        assert 'nothing to review' in capsys.readouterr().out


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

    def test_unknown_thread_says_so(self, project, capsys):
        result = _json(capsys, '--thread', 'nothing')
        assert result['facts'] == []
        assert any("no scene in scene-intent.csv carries the thread 'nothing'" in n
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
                            ['reference/commitments.csv', 'working/audit-log.csv'])]
        assert ('ensure_on_branch', 'audit') in mock_git.calls

    def test_rejected_sets_status_and_lists_scenes_to_recheck(self, project, capsys):
        result = _json(capsys, '--mark', 'rejected', 'archive-key-dorren')
        row = self._row(project, 'archive-key-dorren')
        assert row['status'] == 'rejected' and row['reviewed'].startswith('rejected:')
        assert result['recheck']['archive-key-dorren']   # briefs name it
        entry = audit.read_log(project)[-1]
        assert (entry['fact_id'], entry['change']) == ('archive-key-dorren', 'rejected')

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
