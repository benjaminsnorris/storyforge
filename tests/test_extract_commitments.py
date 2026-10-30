"""Extract phase 4: commitments by the reader-noticeable rubric (plan
decision 5) into the ledger."""

import json
import os

import pytest

from storyforge import ledger
from storyforge.extract import (COMMITMENT_RUBRIC, build_commitments_prompt,
                                parse_commitments_response)


def _reply(*items):
    return json.dumps({'commitments': [
        dict({'type': 'trait', 'subject': '', 'statement': 's', 'quote': '',
              'mutable': 'fixed', 'supersedes': ''}, **i) for i in items]})


class TestPrompt:
    def test_carries_the_rubric_the_scene_and_known_commitments(self):
        prompt = build_commitments_prompt(
            'sc1', 'Fred is Scrooge\'s nephew.', {'title': 'T', 'pov': 'scrooge'},
            registries_text='## Characters\n- fred', known=[
                {'id': 'k1', 'type': 'physical', 'subject': 'fred',
                 'statement': 'Fred has a cold.'}])
        assert COMMITMENT_RUBRIC in prompt
        assert "Fred is Scrooge's nephew." in prompt
        assert '- k1 [physical, state, registry] fred: Fred has a cold.' in prompt
        assert 'There is no cap' in prompt

    def test_says_when_nothing_is_known(self):
        assert '(none yet)' in build_commitments_prompt('sc1', 'x', {})
        assert 'already recorded for this scene' not in build_commitments_prompt('sc1', 'x', {})

    def test_lists_what_is_already_recorded_for_the_scene(self):
        """F-128: phase 4 restated the migrated rows beside them."""
        prompt = build_commitments_prompt('sc1', 'x', {}, recorded=[
            {'id': 'marley-is-dead', 'type': 'knowledge', 'subject': '',
             'statement': 'Marley is dead'}])
        assert "## Facts already recorded for this scene\n\nDon't restate these." in prompt
        assert '- marley-is-dead [knowledge, state, registry] -: Marley is dead' in prompt

    @pytest.mark.parametrize('writer', ledger.COMMITMENT_WRITERS)
    def test_a_commitment_from_any_writer_is_not_marked_registry(self, writer):
        prompt = build_commitments_prompt('sc1', 'x', {}, known=[
            {'id': 'k', 'type': 'world', 'subject': '', 'statement': 'S',
             'introduced_by': writer}])
        assert '- k [world, state] -: S' in prompt

    def test_the_rubric_leaves_out_staging_asides_and_invented_times(self):
        """F-127: on A Christmas Carol 44% of rows were incidental, mostly
        staging at scene end, and the wrong ones read a figure of speech
        literally or invented a time."""
        assert 'locations of people and objects at scene end' not in COMMITMENT_RUBRIC
        for words in ('staging:', 'set dressing:', 'jokes and asides',
                      'figurative language read literally', 'never guess one'):
            assert words in COMMITMENT_RUBRIC


class TestParse:
    def test_reads_each_commitment(self):
        got = parse_commitments_response(_reply(
            {'statement': 'Fred is the nephew.', 'subject': ' fred ', 'type': 'relationship'},
            {'statement': ''}), 'sc1')
        assert got == [{'type': 'relationship', 'subject': 'fred',
                        'statement': 'Fred is the nephew.', 'quote': '',
                        'mutable': 'fixed', 'supersedes': '', 'ends': []}]

    def test_reads_the_states_a_commitment_ends(self):
        got = parse_commitments_response(_reply(
            {'statement': 'The wound has healed.', 'ends': ['a', ' b ', '']}), 'sc1')
        assert got[0]['ends'] == ['a', 'b']

    def test_an_unreadable_reply_raises(self):
        with pytest.raises(ValueError):
            parse_commitments_response('not json', 'sc1')


class TestViews:
    def test_the_views_leave_the_rubric_pass_rows_out_and_alone(self, project_dir):
        """Briefs reference registry facts by id; a commitment isn't one, and
        a view write must not drop it as "gone"."""
        ref = os.path.join(project_dir, 'reference')
        rows = ledger.load(project_dir)
        rows.append(dict({c: '' for c in ledger.COLUMNS}, id='c-1', type='physical',
                         subject='tessa-merrin', statement='Tessa holds the key.',
                         origin='prose', status='binding', mutable='state',
                         introduced_by=ledger.COMMITMENTS_PASS, scene_id='act1-sc01'))
        ledger.save(project_dir, rows, command='test')
        assert 'c-1' not in {r['id'] for r in ledger.read_view(ref, 'physical')}
        ledger.write_view(ref, 'physical', ledger.read_view(ref, 'physical'),
                          origin='prose', introduced_by='hone')
        assert 'c-1' in {r['id'] for r in ledger.load(project_dir)}
        with pytest.raises(ValueError, match='c-1'):
            ledger.write_view(ref, 'physical',
                              ledger.read_view(ref, 'physical') + [{'id': 'c-1'}],
                              origin='prose', introduced_by='hone')


class TestPhase4:
    def _run(self, project_dir, monkeypatch, replies, force=False, only=None):
        from storyforge import cmd_extract
        calls = []

        def invoke_to_file(prompt, model, log_file, max_tokens, **kw):
            sid = os.path.basename(log_file)[len('extract-commitments-'):-len('.json')]
            calls.append((sid, prompt))
            response = {'content': [{'type': 'text', 'text': replies.get(sid, _reply())}],
                        'stop_reason': 'end_turn',
                        'usage': {'input_tokens': 1, 'output_tokens': 1}}
            with open(log_file, 'w') as f:
                json.dump(response, f)
            return response
        monkeypatch.setattr(cmd_extract, 'invoke_to_file', invoke_to_file)
        monkeypatch.setattr(cmd_extract, 'commit_and_push', lambda *a, **k: True)
        ref = os.path.join(project_dir, 'reference')
        scenes = os.path.join(project_dir, 'scenes')
        order = only or cmd_extract._build_sorted_scene_ids(scenes, ref)
        log_dir = os.path.join(project_dir, 'working', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        cmd_extract._run_phase_4(order, project_dir, scenes, ref, log_dir, force, False)
        return order, calls

    def _mine(self, project_dir):
        return [r for r in ledger.load(project_dir)
                if r['introduced_by'] == ledger.COMMITMENTS_PASS]

    def test_writes_each_commitment_with_its_scene_and_quote(
            self, project_dir, monkeypatch, capsys):
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        first = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[0]
        with open(os.path.join(project_dir, 'scenes', f'{first}.md')) as f:
            words = ' '.join(f.read().split()[:6])
        before = [r for r in ledger.load(project_dir)]
        self._run(project_dir, monkeypatch, {first: _reply(
            {'statement': 'Dorren keeps the archive key.', 'subject': 'Dorren',
             'type': 'physical', 'mutable': 'state', 'quote': words},
            {'statement': 'The vault is three floors down.', 'subject': 'nowhere',
             'type': 'world', 'quote': 'not in the scene'})})
        mine = self._mine(project_dir)
        assert [(r['scene_id'], r['type'], r['subject'], r['status'], r['origin'])
                for r in mine] == [(first, 'physical', 'dorren-hayle', 'binding', 'prose'),
                                   (first, 'world', 'nowhere', 'binding', 'prose')]
        assert mine[0]['quote'] == words and mine[0]['id'].startswith(f'{first}--')
        # The registry rows are untouched
        assert [r for r in ledger.load(project_dir) if r not in mine] == before
        out = capsys.readouterr().out
        assert '1 quote(s) not found verbatim' in out
        assert "1 subject(s) not a character or location id" in out

    def test_later_scenes_are_offered_earlier_commitments_and_supersede_them(
            self, project_dir, monkeypatch):
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        a, b = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[:2]
        self._run(project_dir, monkeypatch, {a: _reply(
            {'statement': 'Dorren keeps the key.', 'mutable': 'state', 'type': 'physical'})})
        key = self._mine(project_dir)[0]['id']
        # Forced, so scene a is re-extracted (same reply) and b supersedes
        order, calls = self._run(project_dir, monkeypatch, {
            a: _reply({'statement': 'Dorren keeps the key.', 'mutable': 'state',
                       'type': 'physical'}),
            b: _reply({'statement': 'Tessa now has the key.', 'mutable': 'state',
                       'type': 'physical', 'supersedes': key},
                      {'statement': 'x', 'supersedes': 'ghost'})}, force=True)
        prompt_b = dict(calls)[b]
        assert f'- {key} [physical, state]' in prompt_b
        assert f'- {key} [physical' not in dict(calls)[a]
        mine = self._mine(project_dir)
        assert len([r for r in mine if r['scene_id'] == a]) == 1  # replaced, not doubled
        assert [r['supersedes'] for r in mine if r['scene_id'] == b] == [key, '']

    def test_a_scene_links_to_registry_facts_and_ends_states(
            self, project_dir, monkeypatch, capsys):
        """F-128: a registry fact is offered and can be superseded; `ends`
        resolves this pass's own state there, and a registry state it names
        is left to the registry passes, with a WARNING."""
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        a, b = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[:2]
        self._run(project_dir, monkeypatch, {a: _reply(
            {'statement': 'Dorren is bleeding.', 'mutable': 'state', 'type': 'physical'})})
        bleeding = self._mine(project_dir)[0]['id']
        _, calls = self._run(project_dir, monkeypatch, {b: _reply(
            {'statement': 'The bleeding has stopped.', 'mutable': 'state',
             'type': 'physical', 'supersedes': 'map-anomaly-exists',
             'ends': [bleeding, 'scar-left-hand-kael', 'ghost']})})
        prompt_b = dict(calls)[b]
        assert '- map-anomaly-exists [knowledge, state, registry]' in prompt_b   # backstory, offered
        assert f'- {bleeding} [physical, state]' in prompt_b
        rows = {r['id']: r for r in ledger.load(project_dir)}
        assert rows[bleeding]['resolves'] == b
        assert rows['scar-left-hand-kael']['resolves'] == 'never'   # registry: untouched
        new = next(r for r in self._mine(project_dir) if r['scene_id'] == b)
        assert new['supersedes'] == 'map-anomaly-exists'
        out = capsys.readouterr().out
        assert '1 state(s) recorded by another writer (the registry or the gate)' in out
        assert 'scar-left-hand-kael (resolves: never)' in out
        assert '1 "ends" naming no offered state' in out

    def test_prose_that_disagrees_with_the_scenes_registry_fact_is_reported(
            self, project_dir, monkeypatch, capsys):
        """A registry fact recorded for the same scene is a disagreement,
        not a change over time: linking it would hide it from drafting while
        the registry views still hold it."""
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        b = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[1]
        assert b == 'act1-sc02'   # archive-key-dorren is recorded here
        _, calls = self._run(project_dir, monkeypatch, {b: _reply(
            {'statement': 'Dorren has no key.', 'mutable': 'state', 'type': 'physical',
             'supersedes': 'archive-key-dorren'})})
        assert '## Facts already recorded for this scene' in dict(calls)[b]
        new = next(r for r in self._mine(project_dir) if r['scene_id'] == b)
        assert new['supersedes'] == ''
        assert 'whose prose disagrees with a registry fact' in capsys.readouterr().out

    def test_a_gate_commitment_is_recorded_for_the_scene_and_never_edited(
            self, project_dir, monkeypatch, capsys):
        """Review of #437: phase 4 must not restate the gate's rows for a
        scene, and its `ends` must not set `resolves` on them (its --force
        reset only clears its own rows)."""
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        a, b = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[:2]
        rows = ledger.load(project_dir)
        for rid, sid in (('drafted-here', b), ('drafted-earlier', a)):
            rows.append(dict({k: '' for k in ledger.COLUMNS}, id=rid, type='physical',
                             statement=rid, origin='prose', status='binding',
                             mutable='state', introduced_by='draft', scene_id=sid))
        ledger.save(project_dir, rows, command='test')
        _, calls = self._run(project_dir, monkeypatch, {b: _reply(
            {'statement': 'It healed.', 'ends': ['drafted-earlier']})}, only=[a, b])
        recorded = dict(calls)[b].split('## Facts already recorded for this scene')[1]
        assert '- drafted-here [physical, state]' in recorded
        assert {r['id']: r for r in ledger.load(project_dir)}['drafted-earlier']['resolves'] == ''
        assert '1 state(s) recorded by another writer' in capsys.readouterr().out

    def _own(self, project_dir, rid, **fields):
        rows = ledger.load(project_dir)
        rows.append(dict({c: '' for c in ledger.COLUMNS}, id=rid, type='physical',
                         statement=rid, origin='prose', status='binding', mutable='state',
                         introduced_by=ledger.COMMITMENTS_PASS, **fields))
        ledger.save(project_dir, rows, command='test')

    def test_ends_that_are_already_so_or_already_ended_elsewhere(
            self, project_dir, monkeypatch, capsys):
        """A registry state whose resolves is this scene is no finding; this
        pass's state already ending in a later scene keeps that end, said."""
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        a, b, c = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[:3]
        rows = ledger.load(project_dir)
        rows.append(dict({k: '' for k in ledger.COLUMNS}, id='tired', type='physical',
                         statement='Tessa is tired', origin='prose', status='binding',
                         mutable='state', introduced_by='extract', scene_id=a, resolves=b))
        ledger.save(project_dir, rows, command='test')
        self._own(project_dir, 'bleeding', scene_id='', resolves=c)
        self._run(project_dir, monkeypatch, {b: _reply(
            {'statement': 'Tessa rested and the cut closed.', 'ends': ['tired', 'bleeding']})},
            only=[a, b, c])
        out = capsys.readouterr().out
        assert 'recorded by another writer' not in out
        assert '1 state(s) the prose ends that already end elsewhere' in out
        assert {r['id']: r for r in ledger.load(project_dir)}['bleeding']['resolves'] == c

    def test_a_forced_run_clears_an_end_set_in_a_scene_it_redoes(
            self, project_dir, monkeypatch):
        """A row kept from outside the run must not keep last run's end."""
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        a, b, c = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[:3]
        self._own(project_dir, 'ended-in-b', scene_id='', resolves=b)
        self._own(project_dir, 'ended-elsewhere', scene_id='', resolves=a)
        self._run(project_dir, monkeypatch, {}, force=True, only=[b, c])
        rows = {r['id']: r for r in ledger.load(project_dir)}
        assert rows['ended-in-b']['resolves'] == ''
        assert rows['ended-elsewhere']['resolves'] == a

    def test_registry_facts_tied_to_no_scene_in_the_run_are_named(
            self, project_dir, monkeypatch, capsys):
        rows = ledger.load(project_dir)
        rows[0]['scene_id'] = 'renamed-scene'
        ledger.save(project_dir, rows, command='test')
        self._run(project_dir, monkeypatch, {})
        assert f'name a scene not in this run, so no scene is offered them: {rows[0]["id"]}' \
            in capsys.readouterr().out

    def test_a_scene_already_extracted_is_skipped_without_force(
            self, project_dir, monkeypatch):
        _, calls = self._run(project_dir, monkeypatch, {})
        scenes = {sid for sid, _ in calls}
        rows = ledger.load(project_dir)
        rows.append(dict({c: '' for c in ledger.COLUMNS}, id='done-1', type='trait',
                         statement='x', origin='prose', status='binding', mutable='fixed',
                         introduced_by=ledger.COMMITMENTS_PASS, scene_id=sorted(scenes)[0]))
        ledger.save(project_dir, rows, command='test')
        _, again = self._run(project_dir, monkeypatch, {})
        assert sorted(scenes)[0] not in {sid for sid, _ in again}

    def test_an_unreadable_reply_stops_the_chain(self, project_dir, monkeypatch):
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        first = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[0]
        with pytest.raises(SystemExit):
            self._run(project_dir, monkeypatch, {first: 'garbage'})
        assert self._mine(project_dir) == []


class TestReviewFixes:
    """PR #424's review."""

    def _first_two(self, project_dir):
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        return _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[:2]

    def test_validate_accepts_a_physical_commitment_about_a_place_or_no_one(
            self, project_dir, monkeypatch):
        from storyforge.schema import _ledger_reference_problems
        a, _ = self._first_two(project_dir)
        TestPhase4()._run(project_dir, monkeypatch, {a: _reply(
            {'statement': 'The office roof leaks.', 'type': 'physical',
             'subject': 'cartography-office', 'mutable': 'state'},
            {'statement': 'The bridge is down.', 'type': 'physical', 'mutable': 'state'})})
        ref = os.path.join(project_dir, 'reference')
        problems = _ledger_reference_problems(ledger.load(project_dir), ref,
                                              set(ledger.scene_order(project_dir)))
        assert not [p for p in problems if '--' in p.split(':')[0]]

    def test_a_forced_run_that_stops_leaves_no_rows_from_the_last_run(
            self, project_dir, monkeypatch):
        """A reworded statement got a new id; later scenes kept last run's rows,
        whose supersedes named the old id."""
        a, b = self._first_two(project_dir)
        p4 = TestPhase4()
        p4._run(project_dir, monkeypatch, {
            a: _reply({'statement': 'Dorren keeps the key.', 'type': 'physical'})})
        old_key = p4._mine(project_dir)[0]['id']
        p4._run(project_dir, monkeypatch, {
            b: _reply({'statement': 'Tessa has the key.', 'type': 'physical',
                       'supersedes': old_key})})
        assert {r['scene_id'] for r in p4._mine(project_dir)} == {a, b}
        with pytest.raises(SystemExit):
            p4._run(project_dir, monkeypatch, {
                a: _reply({'statement': 'Dorren holds the brass key.', 'type': 'physical'}),
                b: 'garbage'}, force=True)
        mine = p4._mine(project_dir)
        assert [r['scene_id'] for r in mine] == [a]
        assert mine[0]['id'] != old_key
        assert ledger.validate_ledger(ledger.load(project_dir)) == []

    def test_a_commitment_with_no_quote_is_counted(self, project_dir, monkeypatch, capsys):
        a, _ = self._first_two(project_dir)
        TestPhase4()._run(project_dir, monkeypatch, {a: _reply({'statement': 'x'})})
        assert '1 commitment(s) with no quote' in capsys.readouterr().out

    def test_a_subject_with_a_pipe_or_line_break_is_written_safely(
            self, project_dir, monkeypatch):
        a, _ = self._first_two(project_dir)
        p4 = TestPhase4()
        p4._run(project_dir, monkeypatch, {a: _reply(
            {'statement': 'x', 'subject': 'the | map\ncase'})})
        assert p4._mine(project_dir)[0]['subject'] == 'the , map case'


def _ledger_row(rid, **fields):
    row = {c: '' for c in ledger.COLUMNS}
    row.update(id=rid, type='physical', statement=rid, origin='migrated',
               status='binding', mutable='state', introduced_by='migration')
    row.update(fields)
    return row


class TestKnown:
    """F-128: phase 4 is offered the registry rows too, and on a long book
    the facts about the scene's people and place first."""
    ORDER = {'s1': 0, 's2': 1, 's3': 2}

    def _known(self, rows, scene='s2', subjects=frozenset()):
        from storyforge.extract import known_for_scene
        known, recorded, _ = known_for_scene(rows, scene, self.ORDER, set(subjects))
        return [r['id'] for r in known], [r['id'] for r in recorded]

    def test_registry_and_commitment_rows_in_force_and_what_the_scene_has(self):
        rows = [_ledger_row('backstory', scene_id='', type='knowledge'),
                _ledger_row('earlier', scene_id='s1'),
                _ledger_row('mine', scene_id='s1', introduced_by=ledger.COMMITMENTS_PASS),
                _ledger_row('here', scene_id='s2', type='knowledge'),
                _ledger_row('mine-here', scene_id='s2', introduced_by=ledger.COMMITMENTS_PASS),
                _ledger_row('later', scene_id='s3'),
                _ledger_row('renamed', scene_id='old-scene'),
                _ledger_row('rejected', scene_id='s1', status='rejected')]
        assert self._known(rows) == (['backstory', 'earlier', 'mine'], ['here'])

    def test_superseded_and_resolved_states_are_not_offered(self):
        rows = [_ledger_row('old', scene_id='s1'),
                _ledger_row('new', scene_id='s1', supersedes='old'),
                _ledger_row('healed', scene_id='', resolves='s1'),
                _ledger_row('heals-here', scene_id='', resolves='s2'),
                _ledger_row('fixed', scene_id='', mutable='fixed', resolves='s1')]
        assert self._known(rows)[0] == ['heals-here', 'fixed', 'new']

    def test_past_the_limit_the_scenes_people_and_place_come_first(self, monkeypatch):
        from storyforge import extract
        monkeypatch.setattr(extract, 'MAX_KNOWN_COMMITMENTS', 3)
        from storyforge.extract import known_for_scene
        rows = [_ledger_row('tessa-early', scene_id='', subject='tessa'),
                _ledger_row('knows', scene_id='', known_by='kael;tessa'),
                _ledger_row('pell-name', scene_id='', subject='pell', mutable='fixed'),
                _ledger_row('other-1', scene_id='s1', subject='pell'),
                _ledger_row('other-2', scene_id='s1', subject='pell')]
        # about the scene first, then a fixed fact before a more recent state
        assert self._known(rows, subjects={'tessa'})[0] == ['tessa-early', 'knows', 'pell-name']
        assert known_for_scene(rows, 's2', self.ORDER, {'tessa'})[2] == 2
