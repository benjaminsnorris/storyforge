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

FREE = sf.ReplyRules('free')


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
        r = sf.parse_response(REPLY, 'athena-at-the-door', 'brief', 'h', FREE)
        assert r.scores['outcome'] == 2
        assert [(d['element'], d['tag']) for d in r.departures] == [
            ('key_actions', 'deliberate'), ('outcome', 'drift')]
        assert r.count('drift') == 1 and r.count('deliberate') == 1
        assert r.departures[1]['authority'] == 'none'

    def test_no_departures(self):
        text = REPLY.split('athena-at-the-door|key_actions')[0]
        assert sf.parse_response(text, 'athena-at-the-door', 'brief', 'h', FREE).departures == []

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
            sf.parse_response(bad, 'athena-at-the-door', 'brief', 'h', FREE)


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
        (REPLY.replace('yes|none', 'yes|treatment: compress'), 'drift has none'),
        (REPLY.replace('|deliberate|the assembly is folded into the visit|',
                       '|deliberate||'), 'says nothing'),
    ])
    def test_misreadings_raise(self, bad, message):
        """TD-1/SF-12: each would put the wrong scenes, or half a drift, in revise."""
        with pytest.raises(sf.SourceFidelityError, match=message):
            sf.parse_response(bad, 'athena-at-the-door', 'brief', 'h', FREE)

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
        assert any(l.startswith('athena-at-the-door|brief|') and l.endswith('|1|1|0|0|') for l in scores)
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

    def test_drift_fix_keeps_the_authors_must_beats(self, adapted, fake_api, monkeypatch,
                                                    capsys):
        """#642: a `must` beat is the author's; the source-drift fix that
        rewrites key_actions and key_dialogue never drops or rewords one."""
        path = os.path.join(adapted, 'reference', 'scene-briefs.csv')
        text = open(path).read().replace(
            'athena-at-the-door|Athena wants to rouse him|suitors|yes|c|d|she knocks|"Go"|',
            'athena-at-the-door|Athena wants to rouse him|suitors|yes|c|d|she knocks;must: '
            'Athena takes the shape of Mentes|must: Athena: "Go"|')
        _write(adapted, {'reference/scene-briefs.csv': text})
        _run(adapted)
        (fixed, _), _ = self._fix(adapted, monkeypatch, self.FIX.replace(
            'KEY_ACTIONS: Athena arrives as Mentes;the assembly meets',
            'KEY_ACTIONS: must: Athena arrives as Mentes;the assembly meets'))
        assert fixed == ['athena-at-the-door']
        from storyforge.elaborate import _read_csv_as_map
        row = _read_csv_as_map(path)['athena-at-the-door']
        assert row['key_actions'] == ('the assembly meets; must: Athena takes the shape of '
                                      'Mentes')
        assert row['key_dialogue'] == 'must: Athena: "Go"; "Leave my house"'
        out = capsys.readouterr().out
        assert 'put back the author\'s must item(s)' in out
        assert 'left out must: item(s) the author did not write: must: Athena arrives' in out

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
        r = sf.parse_response(text, 'athena-at-the-door', 'brief', 'h', FREE)
        assert [d['element'] for d in r.departures] == ['key_actions', field]
        assert set(r.scores) == set(sf.ELEMENTS)


# ----------------------------------------------------------------------------
# #617: neighbours' sources, and the `moved` and `staging` tags
# ----------------------------------------------------------------------------

FOUR_SCENES = {
    'reference/scenes.csv': ('id|seq|title|pov\n'
                             'olympus-council-meets|1|Council|narrator\n'
                             'athena-at-the-door|2|At the Door|telemachus\n'
                             'telemachus-sails-at-night|3|Night|telemachus\n'
                             'the-ship-sails|4|Ship|telemachus\n'),
    'reference/source-map.csv': (
        'scene_id|source_scenes|treatment|note\n'
        'olympus-council-meets|gods-debate|dramatize|\n'
        'athena-at-the-door|minerva-visits;assembly-called|compress|two days in one\n'
        'telemachus-sails-at-night||invent|\n'
        'the-ship-sails|ship-sails;assembly-called|compress|the last of the assembly\n'),
}

MOVED = REPLY.replace(
    'athena-at-the-door|outcome|drift|the source\'s outcome is no-but; the brief makes it yes|none',
    'athena-at-the-door|key_dialogue|moved|"Cast off" comes from the next scene\'s source|'
    'from: the-ship-sails\n'
    'athena-at-the-door|key_actions|staging|Athena pauses at the threshold|rule: connective only')

NEAR = (('odyssey:ship-sails', 'the-ship-sails'), ('ship-sails', 'the-ship-sails'),
        ('the-ship-sails', 'the-ship-sails'))
FAITHFUL = sf.ReplyRules('faithful', neighbours=NEAR, has_note=True, has_rules=True)


def _parse(text, rules=FAITHFUL, target='prose'):
    return sf.parse_response(text, 'athena-at-the-door', target, 'h', rules)


class TestNeighbours:
    def test_the_nearest_mapped_scene_either_side(self, adapted):
        _write(adapted, FOUR_SCENES)
        rows = source.map_rows_by_scene(source.read_source_map(adapted))
        order = sf.reading_order(adapted)
        # the invented scene between is passed over
        assert sf.neighbours('athena-at-the-door', order, rows) == (
            'olympus-council-meets', 'the-ship-sails')
        assert sf.neighbours('olympus-council-meets', order, rows) == (
            None, 'athena-at-the-door')
        # not in the reading order: not known, not "none"
        assert sf.neighbours('not-a-scene', order, rows) is None

    def test_reading_order_is_by_seq_and_leaves_out_cut_scenes(self, adapted):
        _write(adapted, {
            'reference/scenes.csv': ('id|seq|title|pov|status\n'
                                     'the-ship-sails|10|Ship|telemachus|\n'
                                     'olympus-council-meets|1|Council|narrator|\n'
                                     'athena-at-the-door|2|At the Door|telemachus|\n'
                                     'cut-scene|3|Gone|telemachus|cut\n'),
            'reference/source-map.csv': FOUR_SCENES['reference/source-map.csv']
            + 'cut-scene|ship-sails|dramatize|\n'})
        rows = source.map_rows_by_scene(source.read_source_map(adapted))
        order = sf.reading_order(adapted)
        assert order == ['olympus-council-meets', 'athena-at-the-door', 'the-ship-sails']
        assert sf.neighbours('athena-at-the-door', order, rows)[1] == 'the-ship-sails'

    def test_an_unmapped_scene_is_passed_over(self, adapted):
        _write(adapted, {**FOUR_SCENES, 'reference/source-map.csv': (
            'scene_id|source_scenes|treatment|note\n'
            'athena-at-the-door|minerva-visits|dramatize|\n'
            'the-ship-sails|ship-sails|dramatize|\n')})
        rows = source.map_rows_by_scene(source.read_source_map(adapted))
        assert sf.neighbours('athena-at-the-door', sf.reading_order(adapted), rows) == (
            None, 'the-ship-sails')

    def test_the_prompt_shows_them_by_book_id(self, adapted):
        _write(adapted, FOUR_SCENES)
        plan = _plan(adapted, 'athena-at-the-door', 'prose')
        near = plan.prompt.split("## The neighbouring book scenes' sources")[1].split(
            '## How this scene adapts them')[0]
        assert '### The book scene before it: `olympus-council-meets`' in near
        assert '#### odyssey:gods-debate: The Gods Debate' in near
        assert '### The book scene after it: `the-ship-sails`' in near
        assert '**Its map row:** `compress`. the last of the assembly' in near
        assert '#### odyssey:ship-sails' in near
        # a source scene this scene adapts too is named, not shown twice
        assert 'It also adapts odyssey:assembly-called, shown above' in near
        assert '#### odyssey:assembly-called' not in near
        # only this scene's own row says Treatment
        assert plan.prompt.count('**Treatment:**') == 1
        assert '`moved`' in plan.prompt and '`staging`' in plan.prompt
        assert plan.rules.names >= {'olympus-council-meets', 'the-ship-sails',
                                    'ship-sails', 'odyssey:ship-sails'}
        assert plan.rules.neighbour_named('to: odyssey:ship-sails') == 'the-ship-sails'
        assert plan.notes == ()

    def test_a_scene_with_no_mapped_neighbour_says_so(self, adapted):
        p = _plan(adapted, 'athena-at-the-door').prompt
        assert ('### The book scene after it: none (no scene after this one adapts a '
                'source scene)') in p

    def test_a_scene_not_in_the_reading_order_says_unknown(self, adapted, fake_api, capsys):
        """SF-10: a cut scene used to get a false 'none' either side."""
        _write(adapted, {'reference/scenes.csv': (
            'id|seq|title|pov|status\n'
            'olympus-council-meets|1|Council|narrator|\n'
            'athena-at-the-door|2|At the Door|telemachus|cut\n')})
        plan = _plan(adapted, 'athena-at-the-door', 'prose')
        assert '### Neighbouring scenes: unknown' in plan.prompt
        assert 'none (no scene' not in plan.prompt and plan.rules.neighbours == ()
        _run(adapted, 'prose', ['athena-at-the-door'])
        assert ('WARNING: athena-at-the-door is not in the reading order, so its neighbours '
                'are unknown') in capsys.readouterr().out

    def test_a_neighbour_with_unresolved_sources_is_said(self, adapted, fake_api, capsys):
        _write(adapted, {**FOUR_SCENES, 'reference/source-map.csv': FOUR_SCENES[
            'reference/source-map.csv'].replace('ship-sails;assembly-called', 'no-such-scene')})
        plan = _plan(adapted, 'athena-at-the-door', 'prose')
        assert 'so they are not shown' in plan.prompt
        assert plan.rules.names == {'olympus-council-meets', 'gods-debate',
                                    'odyssey:gods-debate', 'the-ship-sails'}
        _run(adapted, 'prose', ['athena-at-the-door'])
        assert ("WARNING: athena-at-the-door: the neighbouring scene the-ship-sails's source "
                'scenes are not in the imported source') in capsys.readouterr().out

    def test_staging_follows_the_mode(self, adapted):
        assert 'mode is `faithful`, so `staging` is allowed only when' in _plan(
            adapted, 'athena-at-the-door').prompt
        assert 'start `authority` with `rule:` or `note`' in _plan(
            adapted, 'athena-at-the-door').prompt
        _write(adapted, {'storyforge.yaml': YAML.format(extra='  mode: free')})
        assert 'mode is `free`, which allows connective invention' in _plan(
            adapted, 'athena-at-the-door').prompt

    def test_the_plan_records_the_note_and_the_rules(self, adapted):
        rules = _plan(adapted, 'athena-at-the-door').rules
        assert (rules.mode, rules.has_note, rules.has_rules) == ('faithful', True, True)
        assert not _plan(adapted, 'olympus-council-meets').rules.has_note   # an empty note


class TestNewTags:
    def test_moved_and_staging_are_read_and_are_not_drift(self):
        r = _parse(MOVED)
        assert [d['tag'] for d in r.departures] == ['deliberate', 'moved', 'staging']
        assert r.count('drift') == 0 and r.count('moved') == 1 and r.count('staging') == 1
        assert r.departures[1]['authority'] == 'from: the-ship-sails'

    @pytest.mark.parametrize('authority', ['from: odyssey:ship-sails', 'to ship-sails'])
    def test_moved_may_name_the_neighbours_source_scene(self, authority):
        assert _parse(MOVED.replace('from: the-ship-sails', authority)).count('moved') == 1

    @pytest.mark.parametrize('authority, rules, message', [
        ('from: the next scene', FAITHFUL, r'names no neighbouring scene \(the-ship-sails\)'),
        ('from: the-ship-sails-two', FAITHFUL, 'names no neighbouring scene'),
        ('from: the-ship-sails', sf.ReplyRules('faithful', has_rules=True),
         'this scene has none shown'),
        ('none', FAITHFUL, 'a moved departure on key_dialogue with no authority'),
    ])
    def test_moved_must_name_a_neighbour(self, authority, rules, message):
        with pytest.raises(sf.SourceFidelityError, match=message):
            _parse(MOVED.replace('from: the-ship-sails', authority), rules)

    def test_staging_in_faithful_mode_needs_a_rule_or_the_note(self):
        text = MOVED.replace('rule: connective only', 'mode: free')
        with pytest.raises(sf.SourceFidelityError, match='only a version rule or the note'):
            _parse(text)
        free = sf.ReplyRules('free', neighbours=NEAR)
        assert _parse(text, free).count('staging') == 1
        with pytest.raises(sf.SourceFidelityError, match='staging departure .* no authority'):
            _parse(MOVED.replace('rule: connective only', 'none'))

    @pytest.mark.parametrize('authority, rules, message', [
        ('note', sf.ReplyRules('faithful', neighbours=NEAR, has_rules=True),
         "this scene's map row has no note"),
        ('rule: connective only', sf.ReplyRules('faithful', neighbours=NEAR, has_note=True),
         'this project has no version rules'),
    ])
    def test_faithful_staging_must_point_at_what_exists(self, authority, rules, message):
        """CR-1/SF-H5: `note` with no note, `rule:` with no rules, were accepted."""
        with pytest.raises(sf.SourceFidelityError, match=message):
            _parse(MOVED.replace('rule: connective only', authority), rules)

    @pytest.mark.parametrize('authority', ['`note`', '"rule: connective only"',
                                           'version rule: connective only', 'Note'])
    def test_quoted_and_spelled_out_authorities_are_read(self, authority):
        """CR-2: a backticked `note` was refused."""
        r = _parse(MOVED.replace('rule: connective only', authority))
        assert r.departures[2]['authority'] == authority.strip('`"')

    @pytest.mark.parametrize('element', ['outcome', 'knowledge_out'])
    def test_staging_is_never_on_outcome_or_knowledge(self, element):
        with pytest.raises(sf.SourceFidelityError, match=f'staging departure on {element}'):
            _parse(MOVED.replace('|key_actions|staging|', f'|{element}|staging|'))

    def test_counts_are_written_and_reported(self, adapted, fake_api, capsys):
        _write(adapted, FOUR_SCENES)
        fake_api.replies['compress'] = MOVED
        results, skipped, failed = _run(adapted, 'prose', ['athena-at-the-door'])
        assert failed == {}
        row = sf.read_scores(os.path.join(adapted, 'working', 'scores', 'cycle-1'))[0]
        assert (row['drift'], row['deliberate'], row['moved'], row['staging']) == (
            '0', '1', '1', '1')
        sf.report(results, skipped, failed, 'prose')
        out = capsys.readouterr().out
        assert '0 drift in 0 scenes; not drift: 1 deliberate, 1 moved, 1 staging' in out
        # staging on a key element is listed, not only counted
        assert 'staging athena-at-the-door key_actions: Athena pauses at the threshold' in out
        # revise reads drift only
        assert sf.latest_drift(adapted) == {}

    def test_faithful_staging_by_mode_is_asked_again_in_a_run(self, adapted, monkeypatch):
        """A real run(): faithful staging authorized by `mode: free` is not read."""
        _write(adapted, FOUR_SCENES)
        bad = MOVED.replace('rule: connective only', 'mode: free')
        replies = [bad, bad]
        monkeypatch.setattr('storyforge.api.invoke_to_file',
                            lambda *a, **k: _response(replies.pop(0)))
        monkeypatch.setattr('storyforge.costs.log_operation', lambda *a, **k: None)
        results, _skipped, failed = _run(adapted, 'prose', ['athena-at-the-door'])
        assert results == [] and 'only a version rule or the note' in failed['athena-at-the-door']

    def test_every_tag_has_a_column(self):
        assert set(sf.TAGS) <= set(sf.SCORE_COLUMNS)

    def test_results_hold_their_invariants(self):
        """TD-2."""
        scores = dict.fromkeys(sf.ELEMENTS, 5)
        for bad in ({'element': 'goal', 'tag': 'maybe', 'evidence': 'x', 'authority': 'a'},
                    {'element': 'mood', 'tag': 'drift', 'evidence': 'x', 'authority': 'none'},
                    {'element': 'goal', 'tag': 'drift', 'evidence': 'x', 'authority': 'note'},
                    {'element': 'goal', 'tag': 'moved', 'evidence': 'x', 'authority': 'none'},
                    {'element': 'goal', 'tag': 'moved', 'evidence': '', 'authority': 'to: a'}):
            with pytest.raises(ValueError):
                sf.Result('s', 'prose', 'h', scores, [bad])
        with pytest.raises(ValueError, match='tag'):
            sf.Result('s', 'prose', 'h', scores).count('Drift')
        with pytest.raises(ValueError, match='mode'):
            sf.ReplyRules('loose')


class TestMovedConfirmation:
    """SF-6: a `moved ... to:` claim is checked against the neighbour's result."""

    def _result(self, sid, *departures):
        return sf.Result(sid, 'prose', 'h', dict.fromkeys(sf.ELEMENTS, 5), list(departures))

    RULES = {'a': sf.ReplyRules('free', neighbours=(('b', 'b'), ('src-b', 'b'))),
             'b': sf.ReplyRules('free', neighbours=(('a', 'a'),))}
    TO_B = {'element': 'key_actions', 'tag': 'moved', 'evidence': 'x', 'authority': 'to: b'}
    FROM_A = {'element': 'key_actions', 'tag': 'moved', 'evidence': 'y', 'authority': 'from: a'}

    def test_a_confirmed_move_is_not_listed(self):
        assert sf.unconfirmed_moves([self._result('a', self.TO_B),
                                     self._result('b', self.FROM_A)], self.RULES) == []

    def test_a_neighbour_without_a_matching_move_is_listed(self):
        assert sf.unconfirmed_moves([self._result('a', self.TO_B), self._result('b')],
                                    self.RULES) == [
            'a key_actions to b: its result has no moved departure naming this scene']

    def test_a_neighbour_not_in_the_run_is_listed(self):
        to_src = {**self.TO_B, 'authority': 'to src-b'}
        assert sf.unconfirmed_moves([self._result('a', to_src)], self.RULES) == [
            'a key_actions to b: it has no result in this run']

    def test_from_claims_are_not_checked(self):
        assert sf.unconfirmed_moves([self._result('b', self.FROM_A)], self.RULES) == []

    def test_the_run_warns(self, adapted, fake_api, capsys):
        _write(adapted, FOUR_SCENES)
        fake_api.replies['compress'] = MOVED.replace('from: the-ship-sails', 'to: the-ship-sails')
        _run(adapted, 'prose', ['athena-at-the-door'])
        out = capsys.readouterr().out
        assert 'WARNING: 1 moved departure(s) not confirmed' in out
        assert 'athena-at-the-door key_dialogue to the-ship-sails: it has no result' in out


OLD_HEADER = ('id|target|target_hash|goal|outcome|key_actions|key_dialogue|on_stage|'
              'knowledge_out|overall|drift|deliberate')


class TestOlderCycles:
    def _old_cycle(self, adapted):
        cycle = os.path.join(adapted, 'working', 'scores', 'cycle-1')
        h = sf.target_hash(sf.target_text(adapted, 'athena-at-the-door', 'prose'))
        _write(cycle, {
            sf.SCORES_FILE: f'{OLD_HEADER}\nathena-at-the-door|prose|{h}|5|2|5|5|5|5|4.4|1|0\n',
            sf.RATIONALE_FILE: ('id|target|element|tag|evidence|authority\n'
                                'athena-at-the-door|prose|outcome|drift|x|none\n')})
        return cycle

    def test_an_older_cycle_is_read_with_the_new_counts_empty(self, adapted):
        cycle = self._old_cycle(adapted)
        row = sf.read_scores(cycle)[0]
        assert row['drift'] == '1' and row['moved'] == '' and row['staging'] == ''
        assert sf.latest_drift(adapted) == {'athena-at-the-door': ['prose outcome: x']}

    def test_drift_state_counts_results_from_before_the_tags(self, adapted, fake_api):
        """SF-12."""
        self._old_cycle(adapted)
        state = sf.drift_state(adapted)
        assert state.pretag == 1
        assert 'predate the moved/staging tags' in state.pretag_line()
        _run(adapted, 'prose', ['athena-at-the-door'])   # rescored: new counts
        assert sf.drift_state(adapted).pretag == 0

    def test_merging_into_an_older_cycle_writes_the_new_header(self, adapted, fake_api):
        cycle = self._old_cycle(adapted)
        _run(adapted, 'brief', ['athena-at-the-door'])
        lines = open(os.path.join(cycle, sf.SCORES_FILE)).read().splitlines()
        assert lines[0] == '|'.join(sf.SCORE_COLUMNS)
        old = next(l for l in lines if l.startswith('athena-at-the-door|prose|'))
        assert old.endswith('|1|0|||')       # not counted, not zero

    def test_another_header_is_refused(self, adapted):
        cycle = self._old_cycle(adapted)
        _write(cycle, {sf.SCORES_FILE: OLD_HEADER + '|moved\nx\n'})
        with pytest.raises(source.SourceError, match='the header must be'):
            sf.read_scores(cycle)

    def test_an_old_header_with_new_length_rows_is_refused(self, adapted):
        cycle = self._old_cycle(adapted)
        _write(cycle, {sf.SCORES_FILE: f'{OLD_HEADER}\n'
                                        f'athena-at-the-door|prose|h|5|2|5|5|5|5|4.4|1|0|0|0|\n'})
        with pytest.raises(source.SourceError, match='wrong number of cells'):
            sf.read_scores(cycle)


# ----------------------------------------------------------------------------
# #618: a reply naming the source scene, and one re-ask
# ----------------------------------------------------------------------------

ONE_SOURCE_MAP = ('scene_id|source_scenes|treatment|note\n'
                  'olympus-council-meets|gods-debate|dramatize|\n'
                  'athena-at-the-door|minerva-visits|dramatize|\n'
                  'telemachus-sails-at-night||invent|\n')


class TestSourceIdInTheReply:
    @pytest.fixture
    def one_source(self, adapted):
        _write(adapted, {'reference/source-map.csv': ONE_SOURCE_MAP})
        return adapted

    @pytest.mark.parametrize('named', ['minerva-visits', 'odyssey:minerva-visits'])
    def test_rows_naming_the_one_source_scene_are_the_scenes(self, one_source, named):
        plan = _plan(one_source, 'athena-at-the-door', 'prose')
        assert plan.rules.aliases == {'minerva-visits', 'odyssey:minerva-visits'}
        r = sf.parse_response(REPLY.replace('athena-at-the-door', named), 'athena-at-the-door',
                              'prose', 'h', plan.rules)
        assert r.scene_id == 'athena-at-the-door' and r.remapped == named
        assert r.count('drift') == 1

    def test_the_prompt_names_the_book_scene_first(self, one_source):
        p = _plan(one_source, 'athena-at-the-door', 'prose').prompt
        assert p.index('**The scene you are checking is `athena-at-the-door`.**') < p.index(
            '### odyssey:minerva-visits')

    def test_a_scene_adapting_several_has_no_alias(self, adapted):
        assert _plan(adapted, 'athena-at-the-door').rules.aliases == frozenset()
        with pytest.raises(sf.SourceFidelityError, match="a row for 'minerva-visits'"):
            sf.parse_response(REPLY.replace('athena-at-the-door', 'minerva-visits'),
                              'athena-at-the-door', 'brief', 'h', FREE)

    @pytest.mark.parametrize('status', ['', 'cut'])
    def test_another_book_scenes_id_is_never_an_alias(self, adapted, status):
        """A source scene sharing its id with a book scene, a cut one included
        (SF-11), is named only as slug:id."""
        _write(adapted, {
            'reference/scenes.csv': ('id|seq|title|pov|status\n'
                                     'athena-at-the-door|1|At the Door|telemachus|\n'
                                     f'ship-sails|2|Ship|telemachus|{status}\n'),
            'reference/source-map.csv': ('scene_id|source_scenes|treatment|note\n'
                                         'athena-at-the-door|ship-sails|dramatize|\n'
                                         'ship-sails|ship-sails|dramatize|\n')})
        assert _plan(adapted, 'athena-at-the-door', 'prose').rules.aliases == {
            'odyssey:ship-sails'}

    def test_the_run_reads_it_says_so_and_records_it(self, one_source, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.api.invoke_to_file',
                            lambda prompt, model, log_file, *a, **k: _response(
                                REPLY.replace('athena-at-the-door', 'minerva-visits')))
        monkeypatch.setattr('storyforge.costs.log_operation', lambda *a, **k: None)
        results, _skipped, failed = _run(one_source, 'prose', ['athena-at-the-door'])
        assert failed == {} and results[0].scene_id == 'athena-at-the-door'
        sf.report(results, {}, failed, 'prose')
        assert ('the reply named its source scene minerva-visits in place of '
                'athena-at-the-door') in capsys.readouterr().out
        row = sf.read_scores(os.path.join(one_source, 'working', 'scores', 'cycle-1'))[0]
        assert row['remapped'] == 'minerva-visits'


class TestReask:
    @pytest.fixture
    def api(self, monkeypatch):
        calls, costed, replies = [], [], []

        def invoke_to_file(prompt, model, log_file, *a, **k):
            calls.append((prompt, os.path.basename(log_file)))
            return _response(replies.pop(0))
        monkeypatch.setattr('storyforge.api.invoke_to_file', invoke_to_file)
        monkeypatch.setattr('storyforge.costs.log_operation',
                            lambda p, op, model, *a, **k: costed.append((op, k['target'])))
        return type('Api', (), {'calls': calls, 'costed': costed, 'replies': replies})

    def test_a_bad_reply_is_asked_again_once_with_what_was_wrong(self, adapted, api, capsys):
        api.replies[:] = ['I could not compare these.', REPLY]
        results, _skipped, failed = _run(adapted, 'brief', ['athena-at-the-door'])
        assert failed == {} and results[0].count('drift') == 1
        assert len(api.calls) == 2
        second, log_name = api.calls[1]
        assert log_name == 'source-fidelity-brief-athena-at-the-door-retry.json'
        assert '## Your earlier reply could not be used' in second
        assert 'no score for goal' in second and 'I could not compare these.' in second
        assert api.costed == [('score-source-fidelity-brief', 'athena-at-the-door')] * 2
        assert 'could not be read (no score for goal' in capsys.readouterr().out

    def test_a_second_bad_reply_is_a_failure(self, adapted, api):
        api.replies[:] = ['I could not compare these.', REPLY.replace('|deliberate|', '|maybe|')]
        results, _skipped, failed = _run(adapted, 'brief', ['athena-at-the-door'])
        assert results == [] and len(api.calls) == 2
        why = failed['athena-at-the-door']
        assert "departure tag 'maybe'" in why and 'asked twice' in why

    def test_a_good_reply_is_asked_once(self, adapted, api):
        api.replies[:] = [REPLY]
        _run(adapted, 'brief', ['athena-at-the-door'])
        assert len(api.calls) == 1

    def test_a_cut_off_reply_is_not_asked_again(self, adapted, monkeypatch):
        calls = []

        def invoke_to_file(*a, **k):
            calls.append(1)
            return {**_response(REPLY[:40]), 'stop_reason': 'max_tokens'}
        monkeypatch.setattr('storyforge.api.invoke_to_file', invoke_to_file)
        monkeypatch.setattr('storyforge.costs.log_operation', lambda *a, **k: None)
        results, _skipped, failed = _run(adapted, 'brief', ['athena-at-the-door'])
        assert results == [] and len(calls) == 1
        assert 'max_tokens' in failed['athena-at-the-door']


class TestCompleteCycleSourceFidelity:
    """#618: `score --complete-cycle` re-checks only the scenes an incomplete
    cycle lists, into that cycle."""

    @pytest.fixture
    def incomplete(self, adapted, fake_api, monkeypatch):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: adapted)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
        commits = []
        for name in ('create_branch', 'ensure_branch_pushed'):
            monkeypatch.setattr(cmd_score, name, lambda *a, **k: None)
        monkeypatch.setattr(cmd_score, 'commit_and_push', lambda p, msg, *a: commits.append(msg))
        monkeypatch.setattr(cmd_score, 'check_threshold', lambda cost: True)
        _write(adapted, {'scenes/olympus-council-meets.md': 'Zeus spoke. ' * 10})
        # cycle 1 has the council's result, and its incomplete.txt (written
        # below, as a run whose door reply failed would) lists the door
        _run(adapted, 'prose', ['olympus-council-meets'])
        cycle = os.path.join(adapted, 'working', 'scores', 'cycle-1')
        hashes = '\n'.join(f'{s}|{sf.target_hash(sf.target_text(adapted, s, "prose"))}'
                           for s in ('olympus-council-meets', 'athena-at-the-door'))
        _write(cycle, {'incomplete.txt': 'source fidelity (prose): athena-at-the-door\n',
                       'prose-hashes.csv': f'id|prose_hash\n{hashes}\n'})
        fake_api.calls.clear()
        return type('C', (), {'dir': cycle, 'commits': commits, 'api': fake_api})

    def test_only_the_listed_scene_is_checked(self, adapted, incomplete):
        from storyforge import cmd_score
        cmd_score.main(['--complete-cycle'])
        assert len(incomplete.api.calls) == 1
        assert '`athena-at-the-door`' in incomplete.api.calls[0]
        rows = sf.read_scores(incomplete.dir)
        assert {(r['id'], r['target']) for r in rows} == {
            ('olympus-council-meets', 'prose'), ('athena-at-the-door', 'prose')}
        assert not os.path.exists(os.path.join(incomplete.dir, 'incomplete.txt'))
        assert os.readlink(os.path.join(adapted, 'working', 'scores', 'latest')) == 'cycle-1'
        assert incomplete.commits == ['Score: complete cycle 1']

    def test_a_scene_that_fails_again_stays_listed(self, adapted, incomplete):
        from storyforge import cmd_score
        incomplete.api.replies['compress'] = 'no idea'
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--complete-cycle', '1'])
        assert e.value.code == 1
        assert open(os.path.join(incomplete.dir, 'incomplete.txt')).read() == (
            'source fidelity (prose): athena-at-the-door\n')
        assert len(incomplete.api.calls) == 2   # the call and its one re-ask, both unreadable
        assert incomplete.commits == ['Score: complete cycle 1 (still incomplete)']

    def test_without_prose_hashes_the_source_fidelity_hashes_are_checked(
            self, adapted, incomplete, capsys):
        from storyforge import cmd_score
        os.remove(os.path.join(incomplete.dir, 'prose-hashes.csv'))
        _write(adapted, {'scenes/olympus-council-meets.md': 'Zeus spoke at length. ' * 10})
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--complete-cycle'])
        assert e.value.code == 1
        assert "olympus-council-meets changed since it was scored" in capsys.readouterr().out
        assert incomplete.api.calls == []

    def test_a_scene_with_nothing_to_check_now_stays_listed(self, adapted, incomplete, capsys):
        """C4/SF-8: a scene the map now invents was cleared without being checked."""
        from storyforge import cmd_score
        _write(adapted, {'reference/source-map.csv': open(source.source_map_path(adapted))
                         .read().replace('minerva-visits;assembly-called|compress',
                                         '|invent')})
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--complete-cycle'])
        assert e.value.code == 1
        assert open(os.path.join(incomplete.dir, 'incomplete.txt')).read() == (
            'source fidelity (prose): athena-at-the-door\n')
        assert 'nothing to check now' in capsys.readouterr().out
        assert incomplete.api.calls == []

    def test_a_run_that_cannot_start_puts_the_items_back(self, adapted, incomplete,
                                                          monkeypatch, capsys):
        """C5/SF-7: the error used to replace the list of scenes."""
        from storyforge import cmd_score

        def boom(*a, **k):
            raise source.SourceError('the imported source changed')
        monkeypatch.setattr('storyforge.source_fidelity.run', boom)
        with pytest.raises(SystemExit):
            cmd_score.main(['--complete-cycle'])
        assert open(os.path.join(incomplete.dir, 'incomplete.txt')).read() == (
            'source fidelity (prose): athena-at-the-door\n')
        assert 'the imported source changed' in capsys.readouterr().out

    @pytest.mark.parametrize('break_it, message', [
        (lambda p: os.remove(source.source_map_path(p)), 'source-map'),
        (lambda p: _write(p, {'storyforge.yaml': 'project:\n  title: "T"\n'}),
         'no `source:` block'),
    ])
    def test_a_missing_map_or_source_block_is_refused_up_front(
            self, adapted, incomplete, capsys, break_it, message):
        from storyforge import cmd_score
        break_it(adapted)
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--complete-cycle'])
        assert e.value.code == 1 and message in capsys.readouterr().out
        assert incomplete.api.calls == [] and incomplete.commits == []

    def test_a_broken_source_fidelity_file_is_refused(self, adapted, incomplete, capsys):
        from storyforge import cmd_score
        _write(incomplete.dir, {sf.SCORES_FILE: 'id|nonsense\nx|y\n'})
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--complete-cycle'])
        assert e.value.code == 1 and 'the header must be' in capsys.readouterr().out
        assert incomplete.api.calls == []

    @pytest.mark.parametrize('edit_brief', [False, True])
    def test_a_brief_part_checks_the_briefs(self, adapted, incomplete, capsys, edit_brief):
        from storyforge import cmd_score
        _run(adapted, 'brief', ['olympus-council-meets'])
        incomplete.api.calls.clear()
        _write(incomplete.dir, {'incomplete.txt': 'source fidelity (brief): athena-at-the-door\n'})
        if edit_brief:
            path = os.path.join(adapted, 'reference', 'scene-briefs.csv')
            _write(adapted, {'reference/scene-briefs.csv': open(path).read().replace(
                'Athena wants Odysseus freed', 'Athena wants him home')})
            with pytest.raises(SystemExit) as e:
                cmd_score.main(['--complete-cycle'])
            assert e.value.code == 1
            assert 'olympus-council-meets (brief) changed since' in capsys.readouterr().out
            assert incomplete.api.calls == []
        else:
            cmd_score.main(['--complete-cycle'])
            assert 'Prose and briefs unchanged since cycle-1' in capsys.readouterr().out
            assert ('athena-at-the-door', 'brief') in {
                (r['id'], r['target']) for r in sf.read_scores(incomplete.dir)}


class TestCompleteCycleBeforeThisChange:
    """A cycle scored before #617/#618: the old header, no hash files, and
    incomplete.txt lines without a target."""

    def _old(self, adapted, fake_api, monkeypatch, items):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: adapted)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
        for name in ('create_branch', 'ensure_branch_pushed', 'commit_and_push'):
            monkeypatch.setattr(cmd_score, name, lambda *a, **k: None)
        monkeypatch.setattr(cmd_score, 'check_threshold', lambda cost: True)
        _write(adapted, {'scenes/olympus-council-meets.md': 'Zeus spoke. ' * 10})
        cycle = os.path.join(adapted, 'working', 'scores', 'cycle-3')
        h = sf.target_hash(sf.target_text(adapted, 'olympus-council-meets', 'prose'))
        _write(cycle, {
            sf.SCORES_FILE: f'{OLD_HEADER}\nolympus-council-meets|prose|{h}|5|5|5|5|5|5|5.0|0|0\n',
            sf.RATIONALE_FILE: 'id|target|element|tag|evidence|authority\n',
            'incomplete.txt': ''.join(f'{i}\n' for i in items)})
        return cycle

    def test_a_full_cycles_line_is_read_as_prose(self, adapted, fake_api, monkeypatch, capsys):
        from storyforge import cmd_score
        cycle = self._old(adapted, fake_api, monkeypatch,
                          ['source fidelity: athena-at-the-door'])
        cmd_score.main(['--complete-cycle'])
        out = capsys.readouterr().out
        assert 'checked the 1 results its source-fidelity file hashes' in out
        assert not os.path.exists(os.path.join(cycle, 'incomplete.txt'))
        lines = open(os.path.join(cycle, sf.SCORES_FILE)).read().splitlines()
        assert lines[0] == '|'.join(sf.SCORE_COLUMNS)
        assert any(l.startswith('athena-at-the-door|prose|') for l in lines)

    def test_a_source_only_cycles_line_is_not_guessed(self, adapted, fake_api, monkeypatch,
                                                      capsys):
        from storyforge import cmd_score
        cycle = self._old(adapted, fake_api, monkeypatch, [
            'scene scores: not run (score --source-fidelity only)',
            'source fidelity: athena-at-the-door'])
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--complete-cycle'])
        assert e.value.code == 1
        assert "doesn't say whether briefs or prose" in capsys.readouterr().out
        assert fake_api.calls == [] and os.path.exists(os.path.join(cycle, 'incomplete.txt'))
