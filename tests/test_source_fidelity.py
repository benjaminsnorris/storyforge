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
        assert sf.parse_response(text, 'athena-at-the-door', 'brief', 'h').departures == []

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
        # source-fidelity-<target>-<scene>.json
        sid = os.path.basename(log_file)[:-len('.json')].split('-', 3)[3]
        calls.append(prompt)
        text = next((t for key, t in replies.items() if f'Treatment:** {key}' in prompt), None)
        if text is None:
            text = REPLY if 'Treatment:** compress' in prompt else CLEAN
        return _response(text.replace('athena-at-the-door', sid))
    monkeypatch.setattr('storyforge.api.invoke_to_file', invoke_to_file)
    monkeypatch.setattr('storyforge.costs.log_operation', lambda *a, **k: None)
    return type('Api', (), {'calls': calls, 'replies': replies})


def _run(p, target='brief', ids=None):
    out = os.path.join(p, 'working', 'scores', 'cycle-1')
    return sf.run(p, ids or ['olympus-council-meets', 'athena-at-the-door',
                             'telemachus-sails-at-night'], target, plugin_dir=PLUGIN,
                  out_dir=out, log_dir=os.path.join(p, 'working', 'logs'),
                  model='claude-sonnet-5-5', parallel=1)


class TestParseFixes:
    @pytest.mark.parametrize('bad, message', [
        (REPLY.replace('athena-at-the-door|5|2|4|5|5|5',
                       'athena-at-the-door|5|5|5|5|5|5\nathena-at-the-door|1|1|1|1|1|1'),
         'more than one SCORES row'),
        (REPLY.replace('athena-at-the-door|5|2', 'other-scene|5|2'), "a row for 'other-scene'"),
        (REPLY.replace('yes|none', 'yes | really|none'), 'cells, not 5'),
        (REPLY.replace('yes|none', 'yes|treatment: compress'), 'deliberate or drift'),
        (REPLY.replace('|deliberate|the assembly is folded into the visit|',
                       '|deliberate||'), 'says nothing'),
    ])
    def test_misreadings_raise(self, bad, message):
        """TD-1/SF-12: each would put the wrong scenes, or half a drift, in revise."""
        with pytest.raises(sf.SourceFidelityError, match=message):
            sf.parse_response(bad, 'athena-at-the-door', 'brief', 'h')

    def test_types_hold_their_invariants(self):
        """TD-5/TD-6."""
        with pytest.raises(ValueError):
            sf.Plan('s')
        with pytest.raises(ValueError):
            sf.Plan('s', prompt='p', skip='why', target_hash='h')
        with pytest.raises(ValueError):
            sf.Result('s', 'brief', 'h', {'goal': 5})
        with pytest.raises(ValueError):
            sf.Result('s', 'draft', 'h', dict.fromkeys(sf.ELEMENTS, 5))


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
        rows = sf._read(os.path.join(adapted, 'working', 'scores', 'cycle-1', sf.SCORES_FILE),
                        sf.SCORE_COLUMNS)
        assert {(r['id'], r['target']) for r in rows} == {
            ('olympus-council-meets', 'brief'), ('athena-at-the-door', 'brief'),
            ('athena-at-the-door', 'prose')}

    def test_broken_map_data_is_a_failure_not_a_skip(self, adapted, fake_api):
        """SF-8: a scene whose map data is wrong makes the run incomplete."""
        _results, skipped, failed = _run(adapted, ids=['athena-at-the-door', 'no-such-scene'])
        assert 'no-such-scene' in failed and 'no-such-scene' not in skipped

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

    def test_rescoring_the_same_cycle_clears_drift(self, adapted, fake_api):
        """T-5: a clean re-score replaces the old rationale rows."""
        _run(adapted)
        fake_api.replies['compress'] = CLEAN
        _run(adapted, ids=['athena-at-the-door'])
        assert sf.latest_drift(adapted) == {}
        rat = open(os.path.join(adapted, 'working', 'scores', 'cycle-1', sf.RATIONALE_FILE)).read()
        assert 'athena-at-the-door' not in rat

    def test_cycle_10_is_newer_than_cycle_9(self, adapted, fake_api):
        """T-12: numeric, not text, order."""
        def run_into(cycle):
            sf.run(adapted, ['athena-at-the-door'], 'brief', plugin_dir=PLUGIN,
                   out_dir=os.path.join(adapted, 'working', 'scores', cycle),
                   log_dir=os.path.join(adapted, 'working', 'logs'), model='m', parallel=1)
        run_into('cycle-9')
        fake_api.replies['compress'] = CLEAN
        run_into('cycle-10')
        assert sf.latest_drift(adapted) == {}

    def test_a_malformed_results_file_raises(self, adapted, fake_api):
        """SF-11: drift read from it would be wrong."""
        _run(adapted)
        path = os.path.join(adapted, 'working', 'scores', 'cycle-1', sf.RATIONALE_FILE)
        with open(path, 'w') as f:
            f.write('id|element\n')
        with pytest.raises(source.SourceError, match='header'):
            sf.latest_drift(adapted)

    def test_a_count_mismatch_raises(self, adapted, fake_api):
        _run(adapted)
        path = os.path.join(adapted, 'working', 'scores', 'cycle-1', sf.RATIONALE_FILE)
        text = open(path).read()
        with open(path, 'w') as f:
            f.write('\n'.join(l for l in text.splitlines() if '|drift|' not in l) + '\n')
        with pytest.raises(source.SourceError, match='counts 1 drift'):
            sf.latest_drift(adapted)


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

    def test_drift_fix_may_name_what_only_the_source_names(self, adapted, fake_api,
                                                           monkeypatch):
        """T-8: Pylos is in the source briefs only, not the reference files."""
        _write(adapted, {'reference/source/odyssey/scene-briefs.csv': open(os.path.join(
            adapted, 'reference', 'source', 'odyssey', 'scene-briefs.csv')).read().replace(
                'Athena as Mentes', 'Athena as Mentes;she names Pylos')})
        _run(adapted)
        (fixed, _), _ = self._fix(adapted, monkeypatch,
                                  self.FIX.replace('as Mentes', 'as Mentes, bound for Pylos'))
        assert fixed == ['athena-at-the-door']

    def test_drift_fix_naming_an_unknown_is_refused(self, adapted, fake_api, monkeypatch):
        _run(adapted)
        (fixed, skipped), _ = self._fix(adapted, monkeypatch,
                                        self.FIX.replace('as Mentes', 'as Mentes, sent by Quetzal'))
        assert fixed == [] and 'Quetzal' in skipped['athena-at-the-door']

    def test_drift_fix_without_a_map_row_is_skipped_not_sent(self, adapted, fake_api,
                                                             monkeypatch):
        """SF-5: never send a fix with no source text."""
        _run(adapted)
        _write(adapted, {'reference/source-map.csv': (
            'scene_id|source_scenes|treatment|note\n'
            'olympus-council-meets|gods-debate|dramatize|\n')})
        # drift is read before the map changes, as revise would
        from storyforge import cmd_revise
        monkeypatch.setattr(cmd_revise, '_source_drift_scenes',
                            lambda p, quiet=False: {'athena-at-the-door': ['brief outcome: x']})
        (fixed, skipped), prompts = self._fix(adapted, monkeypatch, self.FIX)
        assert prompts == [] and fixed == []
        assert 'no row in the source map' in skipped['athena-at-the-door']

    def test_free_mode_reports_drift_but_does_not_fix_it(self, adapted, fake_api, capsys):
        from storyforge.cmd_revise import _detect_upstream_scenes
        _run(adapted)
        _write(adapted, {'storyforge.yaml': YAML.format(extra='  mode: free')})
        assert _detect_upstream_scenes(adapted, []) == []
        assert 'left as it is (mode: free): athena-at-the-door' in capsys.readouterr().out

    def test_no_results_and_stale_results_are_said(self, adapted, fake_api, capsys):
        from storyforge.cmd_revise import _detect_upstream_scenes
        _detect_upstream_scenes(adapted, [])
        assert 'no results yet' in capsys.readouterr().out
        _run(adapted)
        _write(adapted, {'reference/scene-briefs.csv': open(
            os.path.join(adapted, 'reference', 'scene-briefs.csv')).read().replace(
                'Athena wants to rouse him', 'Athena wakes him')})
        assert _detect_upstream_scenes(adapted, []) == []
        assert '1 result(s) scored on a brief or prose changed since' in capsys.readouterr().out

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

    def test_nothing_to_check_exits_1(self, adapted, monkeypatch, capsys):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: adapted)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--source-fidelity', 'prose', '--scenes', 'telemachus-sails-at-night'])
        assert e.value.code == 1 and 'nothing to check' in capsys.readouterr().out

    def test_without_source_block_exits_1(self, project_dir, monkeypatch):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: project_dir)
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--source-fidelity', 'prose', '--dry-run'])
        assert e.value.code == 1


class TestKnowledgeAndNotedFields:
    """#549: the briefs' knowledge carry-forward is not drift (Gawain G-024),
    and a departure on a brief field the target shows doesn't lose the scene
    (Beowulf B-023)."""

    def test_only_the_scenes_new_facts_are_compared(self, adapted):
        _write(adapted, {'reference/scene-briefs.csv': (
            'id|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|'
            'knowledge_in|knowledge_out\n'
            'olympus-council-meets|g|c|yes|c|d|a|"x"||odysseus-on-ogygia\n'
            'athena-at-the-door|Athena wants to rouse him|suitors|yes|c|d|she knocks|"Go"|'
            'odysseus-on-ogygia|odysseus-on-ogygia;suitors-waste-the-house\n'
            'telemachus-sails-at-night|He wants news|night|yes|c|d|sails|"Cast off"||\n')})
        text = sf.target_text(adapted, 'athena-at-the-door', 'brief')
        assert '**knowledge_out (new in this scene):** suitors-waste-the-house' in text
        assert 'odysseus-on-ogygia' not in text

    def test_a_scene_that_adds_no_fact_shows_none(self, adapted):
        _write(adapted, {'reference/scene-briefs.csv': (
            'id|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|'
            'knowledge_in|knowledge_out\n'
            'athena-at-the-door|g|c|yes|c|d|a|"x"|odysseus-on-ogygia|odysseus-on-ogygia\n')})
        assert 'knowledge_out' not in sf.target_text(adapted, 'athena-at-the-door', 'brief')

    def test_the_prompt_says_carried_facts_are_left_out(self, adapted):
        assert 'facts carried in from earlier scenes are left out' in \
            _plan(adapted, 'athena-at-the-door').prompt

    @pytest.mark.parametrize('field', sf.NOTED_FIELDS)
    def test_a_departure_on_a_shown_brief_field_is_kept(self, field):
        text = REPLY.replace('|outcome|drift|', f'|{field}|drift|')
        r = sf.parse_response(text, 'athena-at-the-door', 'brief', 'h')
        assert [d['element'] for d in r.departures] == ['key_actions', field]
        assert set(r.scores) == set(sf.ELEMENTS)
