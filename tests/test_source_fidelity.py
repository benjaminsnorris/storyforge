"""Adaptation (#477): source fidelity scoring, the deliberate/drift tagging,
and the revise hook that sends drift upstream."""

import os

import pytest

from storyforge import source, source_fidelity as sf

from source_helpers import YAML, _write, import_source, make_adaptation

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def adapted(tmp_path):
    proj = make_adaptation(tmp_path)
    import_source(proj)
    _write(proj, {
        'storyforge.yaml': YAML.format(
            extra='  mode: faithful\n  rules: reference/key-decisions.md#version-rules'),
        'reference/scenes.csv': ('id|seq|title|pov\n'
                                 'olympus-council-meets|1|Council|narrator\n'
                                 'athena-at-the-door|2|At the Door|telemachus\n'
                                 'telemachus-sails-at-night|3|Night|telemachus\n'),
        'reference/scene-intent.csv': ('id|function|on_stage\n'
                                       'olympus-council-meets|x|zeus;athena\n'
                                       'athena-at-the-door|y|athena;telemachus\n'
                                       'telemachus-sails-at-night|z|telemachus\n'),
        'reference/scene-briefs.csv': (
            'id|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|knowledge_out\n'
            'olympus-council-meets|Athena wants Odysseus freed|Poseidon|yes|c|d|Zeus agrees|"Free him"|\n'
            'athena-at-the-door|Athena wants to rouse him|suitors|yes|c|d|she knocks|"Go"|\n'
            'telemachus-sails-at-night|He wants news|night|yes|c|d|sails|"Cast off"|\n'),
        'reference/source-map.csv': (
            'scene_id|source_scenes|treatment|note\n'
            'olympus-council-meets|gods-debate|dramatize|\n'
            'athena-at-the-door|minerva-visits;assembly-called|compress|two days in one\n'
            'telemachus-sails-at-night||invent|\n'
            '|ship-sails|cut|told in a line\n'),
        'scenes/athena-at-the-door.md': 'Athena came to the door. ' * 10,
    })
    return proj


def _cfg(p):
    return source.read_config(p)


def _plan(p, sid, target='brief'):
    cfg = _cfg(p)
    rows = source.map_rows_by_scene(source.read_source_map(p))
    return sf.plan_scene(p, sid, target, PLUGIN, cfg, rows, source.read_rules(p, cfg))


REPLY = """SCORES
id|goal|outcome|key_actions|key_dialogue|on_stage|knowledge_out
athena-at-the-door|5|2|4|5|5|5

DEPARTURES
id|element|tag|departure|authority
athena-at-the-door|key_actions|deliberate|the assembly is folded into the visit|treatment: compress
athena-at-the-door|outcome|drift|the source's outcome is no-but; the brief makes it yes|none
"""


CLEAN = REPLY.split('athena-at-the-door|key_actions')[0]


class TestPrompt:
    def test_brief_prompt(self, adapted):
        plan = _plan(adapted, 'athena-at-the-door')
        assert not plan.skip
        p = plan.prompt
        assert '### odyssey:minerva-visits: Athena Visits' in p
        assert '### odyssey:assembly-called' in p
        assert '**Treatment:** compress' in p and '**Note:** two days in one' in p
        assert 'softens the killing' in p
        assert '**goal:** Athena wants to rouse him' in p
        assert '{' not in p.split('## Output Format')[0]      # every placeholder filled
        assert plan.target_hash == sf.target_hash(
            sf.target_text(adapted, 'athena-at-the-door', 'brief'))

    def test_prose_prompt(self, adapted):
        p = _plan(adapted, 'athena-at-the-door', 'prose').prompt
        assert "## The adaptation's prose" in p and 'Athena came to the door.' in p

    @pytest.mark.parametrize('sid, target, why', [
        ('telemachus-sails-at-night', 'brief', 'invented'),
        ('olympus-council-meets', 'prose', 'no prose'),
        ('no-such-scene', 'brief', 'not in the source map'),
    ])
    def test_skips(self, adapted, sid, target, why):
        assert why in _plan(adapted, sid, target).skip


class TestParse:
    def test_tags(self):
        r = sf.parse_response(REPLY, 'athena-at-the-door', 'brief', 'h')
        assert r.scores['outcome'] == 2
        assert [(d['element'], d['tag']) for d in r.departures] == [
            ('key_actions', 'deliberate'), ('outcome', 'drift')]
        assert r.count('drift') == 1 and r.count('deliberate') == 1
        assert r.departures[1]['authority'] == 'none'

    def test_no_departures(self):
        text = REPLY.split('athena-at-the-door|key_actions')[0]
        assert sf.parse_response(text, 's', 'brief', 'h').departures == []

    @pytest.mark.parametrize('bad, message', [
        (REPLY.replace('|deliberate|', '|maybe|'), 'tag'),
        (REPLY.replace('treatment: compress', ''), 'no authority'),
        (REPLY.replace('|5|2|4|5|5|5', '|5|2|4|5|5'), 'cells'),
        (REPLY.replace('|5|2|4|', '|5|9|4|'), 'not 1-5'),
        (REPLY.replace('|key_actions|', '|mood|'), 'element'),
        ('I could not compare these.', 'no score'),
    ])
    def test_bad_replies_raise(self, bad, message):
        with pytest.raises(sf.SourceFidelityError, match=message):
            sf.parse_response(bad, 'athena-at-the-door', 'brief', 'h')


def _response(text):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 10, 'output_tokens': 5}}


@pytest.fixture
def fake_api(monkeypatch):
    calls = []
    replies = {}

    def invoke_to_file(prompt, model, log_file, max_tokens=4096, **kw):
        sid = os.path.basename(log_file).rsplit('-', 1)[0]
        calls.append(prompt)
        for key, text in replies.items():
            if f'Treatment:** {key}' in prompt:
                return _response(text)
        if 'Treatment:** compress' in prompt:
            return _response(REPLY)
        return _response(CLEAN)
    monkeypatch.setattr('storyforge.api.invoke_to_file', invoke_to_file)
    monkeypatch.setattr('storyforge.costs.log_operation', lambda *a, **k: None)
    return type('Api', (), {'calls': calls, 'replies': replies})


def _run(p, target='brief', ids=None):
    out = os.path.join(p, 'working', 'scores', 'cycle-1')
    return sf.run(p, ids or ['olympus-council-meets', 'athena-at-the-door',
                             'telemachus-sails-at-night'], target, plugin_dir=PLUGIN,
                  out_dir=out, log_dir=os.path.join(p, 'working', 'logs'),
                  model='claude-sonnet-5-5', parallel=1)


class TestRun:
    def test_writes_files_and_reports(self, adapted, fake_api):
        results, skipped, failed = _run(adapted)
        assert skipped == {'telemachus-sails-at-night': 'invented (no source scene)'}
        assert failed == {}
        cycle = os.path.join(adapted, 'working', 'scores', 'cycle-1')
        scores = open(os.path.join(cycle, sf.SCORES_FILE)).read().splitlines()
        assert scores[0] == '|'.join(sf.SCORE_COLUMNS)
        assert any(l.startswith('athena-at-the-door|brief|') and l.endswith('|1|1') for l in scores)
        rat = open(os.path.join(cycle, sf.RATIONALE_FILE)).read()
        assert 'athena-at-the-door|brief|outcome|drift|' in rat
        assert 'athena-at-the-door|brief|key_actions|deliberate|' in rat

    def test_a_bad_reply_is_a_failure_not_a_result(self, adapted, fake_api):
        fake_api.replies['compress'] = 'no idea'
        _results, _skipped, failed = _run(adapted)
        assert 'athena-at-the-door' in failed and 'no score' in failed['athena-at-the-door']

    def test_brief_and_prose_runs_merge(self, adapted, fake_api):
        _run(adapted, 'brief')
        _run(adapted, 'prose', ['athena-at-the-door'])
        rows = sf._read(os.path.join(adapted, 'working', 'scores', 'cycle-1', sf.SCORES_FILE))
        assert {(r['id'], r['target']) for r in rows} == {
            ('olympus-council-meets', 'brief'), ('athena-at-the-door', 'brief'),
            ('athena-at-the-door', 'prose')}

    def test_no_map_stops(self, adapted, fake_api):
        os.remove(source.source_map_path(adapted))
        with pytest.raises(source.SourceError, match='source-map'):
            _run(adapted)


class TestLatestDrift:
    def test_drift_is_returned_until_the_brief_changes(self, adapted, fake_api):
        _run(adapted)
        drift = sf.latest_drift(adapted)
        assert list(drift) == ['athena-at-the-door']
        assert drift['athena-at-the-door'][0].startswith('brief outcome: ')
        _write(adapted, {'reference/scene-briefs.csv': open(
            os.path.join(adapted, 'reference', 'scene-briefs.csv')).read().replace(
                'Athena wants to rouse him', 'Athena wants to wake him')})
        assert sf.latest_drift(adapted) == {}

    def test_newer_cycle_wins(self, adapted, fake_api):
        _run(adapted)
        fake_api.replies['compress'] = CLEAN
        sf.run(adapted, ['athena-at-the-door'], 'brief', plugin_dir=PLUGIN,
               out_dir=os.path.join(adapted, 'working', 'scores', 'cycle-2'),
               log_dir=os.path.join(adapted, 'working', 'logs'), model='m', parallel=1)
        assert sf.latest_drift(adapted) == {}

    def test_no_source_block(self, project_dir):
        assert sf.latest_drift(project_dir) == {}


class TestReviseHook:
    def test_drift_scenes_are_upstream(self, adapted, fake_api):
        from storyforge.cmd_revise import _detect_upstream_scenes
        _run(adapted)
        assert _detect_upstream_scenes(adapted, []) == ['athena-at-the-door']
        diag = [{'root_cause': 'brief', 'worst_items': 'olympus-council-meets'}]
        assert _detect_upstream_scenes(adapted, diag) == ['athena-at-the-door',
                                                         'olympus-council-meets']

    def test_without_source_nothing_changes(self, project_dir):
        from storyforge.cmd_revise import _detect_upstream_scenes
        assert _detect_upstream_scenes(project_dir, []) == []

    def _fix(self, adapted, monkeypatch, reply):
        from storyforge import cmd_revise
        prompts = []
        monkeypatch.setattr(cmd_revise, 'invoke_api',
                            lambda prompt, *a, **k: prompts.append(prompt) or reply)
        return cmd_revise._fix_upstream_briefs(adapted, ['athena-at-the-door']), prompts

    FIX = ('GOAL: Athena wants Telemachus to call the assembly\n'
           'CONFLICT: The suitors | jeer\n'
           'OUTCOME: no-but\n'
           'CRISIS: speak or stay silent\n'
           'DECISION: he calls the assembly\n'
           'KEY_ACTIONS: Athena arrives as Mentes;the assembly meets\n'
           'KEY_DIALOGUE: "Leave my house"\n')

    def test_drift_fix_rewrites_toward_the_source(self, adapted, fake_api, monkeypatch):
        _run(adapted)
        (fixed, skipped), prompts = self._fix(adapted, monkeypatch, self.FIX)
        assert fixed == ['athena-at-the-door'] and skipped == {}
        assert 'brief outcome: ' in prompts[0]                    # the drift found
        assert 'odyssey:minerva-visits' in prompts[0]             # the source scene
        assert 'softens the killing' in prompts[0]                # the version rules
        assert 'KEY_ACTIONS: [rewritten key_actions]' in prompts[0]
        from storyforge.elaborate import _read_csv_as_map
        row = _read_csv_as_map(os.path.join(adapted, 'reference', 'scene-briefs.csv'))[
            'athena-at-the-door']
        assert row['outcome'] == 'no-but'
        assert row['key_actions'] == 'Athena arrives as Mentes;the assembly meets'
        assert row['conflict'] == 'The suitors / jeer'           # no | reaches the CSV

    def test_drift_fix_with_a_bad_outcome_is_refused(self, adapted, fake_api, monkeypatch):
        _run(adapted)
        (fixed, skipped), _ = self._fix(adapted, monkeypatch,
                                        self.FIX.replace('OUTCOME: no-but', 'OUTCOME: maybe'))
        assert fixed == [] and 'outcome' in skipped['athena-at-the-door']

    def test_drift_fix_may_name_the_source_cast(self, adapted, fake_api, monkeypatch):
        _run(adapted)
        (fixed, _), _ = self._fix(adapted, monkeypatch,
                                  self.FIX.replace('as Mentes', 'as Mentes, sent by Zeus'))
        assert fixed == ['athena-at-the-door']   # Zeus is in the source, not invented

    def test_a_scene_without_drift_gets_the_old_fix(self, adapted, monkeypatch):
        (fixed, skipped), prompts = self._fix(adapted, monkeypatch,
                                              'GOAL: g\nCONFLICT: c\nCRISIS: x\nDECISION: d\n')
        assert 'genuine dramatic opposition' in prompts[0]
        assert 'source' not in prompts[0].lower()
        assert fixed == ['athena-at-the-door']


class TestScoreCommand:
    def test_dry_run(self, adapted, monkeypatch, capsys):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: adapted)
        cmd_score.main(['--source-fidelity', 'briefs', '--dry-run'])
        out = capsys.readouterr().out
        assert 'Source fidelity (briefs): 2 of 3 scenes to check' in out
        assert 'not checked: telemachus-sails-at-night (invented (no source scene))' in out

    def test_without_source_block_exits_1(self, project_dir, monkeypatch):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: project_dir)
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--source-fidelity', 'prose', '--dry-run'])
        assert e.value.code == 1
