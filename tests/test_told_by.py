"""`told_by`: an embedded tale marked with the scene that tells it (#548).

Beowulf's digressions (Breca, Finnsburh, the herald's Swedish wars) and the
Odyssey's Books IX-XII are scenes told inside another scene. Before #548
nothing marked them: the calendar read a tale cued "continues" as the
present going backwards, validate called a tale with another pov a
crosscut, and drafting never heard it was told.
"""

import json
import os

import pytest

from conftest import PLUGIN_DIR


def _row(sid, day, told='', pov='', mode='scene'):
    return {'id': sid, 'timeline_day': day, 'time_mode': mode, 'timeline_date': '',
            'told_by': told, 'pov': pov}


def _write(path, header, rows):
    with open(path, 'w') as f:
        f.write('|'.join(header) + '\n')
        for r in rows:
            f.write('|'.join(r.get(c, '') for c in header) + '\n')


def _structural(scenes, intent=None):
    from storyforge.elaborate import _validate_told
    scenes_map = {r['id']: r for r in scenes}
    checks = []
    _validate_told(scenes_map, {r['id']: r for r in intent or []}, checks)
    return {c['check']: c for c in checks}


class TestSchema:
    def test_the_column_is_in_scenes_csv_last(self):
        from storyforge.elaborate import _FILE_MAP
        assert _FILE_MAP['scenes.csv'][-1] == 'told_by'

    def test_it_names_scene_ids(self):
        from storyforge.schema import COLUMN_SCHEMA
        assert COLUMN_SCHEMA['told_by']['type'] == 'scene_ids'
        assert COLUMN_SCHEMA['told_by']['file'] == 'scenes.csv'

    def test_a_project_without_the_column_is_not_a_cleanup_finding(self):
        from storyforge.cmd_cleanup import OPTIONAL_CSV_COLUMNS
        assert 'told_by' in OPTIONAL_CSV_COLUMNS['reference/scenes.csv']

    def test_the_template_has_it(self):
        with open(os.path.join(PLUGIN_DIR, 'templates', 'reference', 'scenes.csv')) as f:
            assert f.readline().strip().split('|')[-1] == 'told_by'

    def test_an_unknown_scene_fails_the_schema(self, project_dir):
        from storyforge.elaborate import update_scene
        from storyforge.schema import validate_schema
        ref = os.path.join(project_dir, 'reference')
        update_scene('act1-sc02', ref, {'told_by': 'no-such-scene'})
        bad = [e for e in validate_schema(ref, project_dir)['errors'] if e['column'] == 'told_by']
        assert [(e['row'], e['unresolved']) for e in bad] == [('act1-sc02', ['no-such-scene'])]

    def test_a_known_scene_passes_the_schema(self, project_dir):
        from storyforge.elaborate import update_scene
        from storyforge.schema import validate_schema
        ref = os.path.join(project_dir, 'reference')
        update_scene('act1-sc02', ref, {'told_by': 'act1-sc01'})
        assert not [e for e in validate_schema(ref, project_dir)['errors']
                    if e['column'] == 'told_by']


class TestValidate:
    def test_a_book_with_no_told_scenes_gets_no_checks(self):
        assert _structural([_row('a', '1'), _row('b', '2')]) == {}

    def test_a_tale_told_in_one_scene_passes(self):
        checks = _structural(
            [_row('court', '10', pov='odysseus'), _row('cyclops', '-3000', 'court', 'odysseus')],
            [{'id': 'court', 'characters': 'odysseus;alcinous', 'on_stage': 'odysseus;alcinous'}])
        assert all(c['passed'] for c in checks.values())

    def test_two_telling_scenes_block(self):
        checks = _structural([_row('a', '1'), _row('b', '1'), _row('c', '0', 'a;b')])
        assert not checks['told-by-one-scene']['passed']
        assert checks['told-by-one-scene']['severity'] == 'blocking'

    def test_a_scene_told_by_itself_blocks(self):
        checks = _structural([_row('a', '1', 'a')])
        assert not checks['told-by-self']['passed']

    def test_a_cycle_blocks_once(self):
        checks = _structural([_row('a', '1', 'c'), _row('b', '1', 'a'), _row('c', '1', 'b'),
                              _row('d', '1')])
        cycle = checks['told-by-cycle']
        assert not cycle['passed'] and cycle['severity'] == 'blocking'
        assert cycle['message'].count('->') == 3   # one cycle, a -> c -> b -> a

    def test_a_tale_inside_a_tale_is_no_cycle(self):
        checks = _structural([_row('court', '10'), _row('menelaus', '-20', 'court'),
                              _row('proteus', '-25', 'menelaus')])
        assert checks['told-by-cycle']['passed']

    def test_a_teller_missing_from_the_telling_scene_is_advisory(self):
        checks = _structural(
            [_row('feast', '5', pov='hrothgar'), _row('pyre', '-7300', 'feast', 'hengest')],
            [{'id': 'feast', 'characters': 'hrothgar', 'on_stage': 'hrothgar'}])
        teller = checks['teller-in-telling-scene']
        assert not teller['passed'] and teller['severity'] == 'advisory'
        assert 'pyre (teller hengest' in teller['message']

    def test_a_teller_discussed_in_the_telling_scene_counts(self):
        checks = _structural(
            [_row('feast', '5', pov='hrothgar'), _row('pyre', '-7300', 'feast', 'hengest')],
            [{'id': 'feast', 'characters': 'hrothgar;hengest', 'on_stage': 'hrothgar'}])
        assert checks['teller-in-telling-scene']['passed']

    @pytest.mark.parametrize('pov', ['', 'narrator'])
    def test_the_narrator_or_no_pov_is_not_checked(self, pov):
        checks = _structural([_row('hall', '8', pov='hygelac'),
                              _row('thryth', '-7300', 'hall', pov)],
                             [{'id': 'hall', 'characters': 'hygelac'}])
        assert checks['teller-in-telling-scene']['passed']

    def test_a_tale_told_in_a_cut_scene_blocks(self):
        scenes = [dict(_row('feast', '5'), status='cut'), _row('pyre', '-7300', 'feast')]
        checks = _structural(scenes)
        assert not checks['told-by-cut-scene']['passed']
        assert checks['told-by-cut-scene']['severity'] == 'blocking'
        assert 'pyre (told in feast, cut)' in checks['told-by-cut-scene']['message']

    def test_a_tale_before_its_telling_is_advisory(self):
        scenes = [dict(_row('pyre', '-7300', 'feast'), seq='1'), dict(_row('feast', '5'), seq='2')]
        checks = _structural(scenes)
        later = checks['told-by-later-scene']
        assert not later['passed'] and later['severity'] == 'advisory'
        assert checks['told-by-cut-scene']['passed']

    def test_validate_structure_runs_it(self, project_dir):
        from storyforge.elaborate import update_scene, validate_structure
        ref = os.path.join(project_dir, 'reference')
        update_scene('act1-sc02', ref, {'told_by': 'act1-sc02'})
        result = validate_structure(ref)
        assert not result['passed']
        assert any(c['check'] == 'told-by-self' and not c['passed'] for c in result['checks'])


class TestTimelineOrder:
    """validate's timeline-order finding for a run of scenes set before the present."""

    def _messages(self, rows):
        from storyforge.elaborate import _validate_timeline
        checks = []
        _validate_timeline({r['id']: dict(r, seq=str(i)) for i, r in enumerate(rows, 1)}, checks)
        return [c['message'] for c in checks if not c['passed']]

    def test_a_tale_with_another_pov_is_told_not_a_crosscut(self):
        """Finnsburh's pyre (pov hengest) at Hrothgar's feast: a told tale,
        not a crosscut to Hengest's story."""
        found = self._messages([_row('feast', '5', pov='hrothgar'),
                                _row('pyre', '-7300', 'feast', 'hengest')])
        assert found == ["Told tale: pyre (day -7300) is set before the story's present "
                         "(day 5, reached in feast), told in feast"]

    def test_a_run_of_told_scenes_names_its_telling_scene(self):
        found = self._messages([_row('court', '10', pov='odysseus'),
                                _row('cicones', '-3650', 'court', 'odysseus'),
                                _row('lotus', '-3640', 'court', 'odysseus')])
        assert len(found) == 1
        assert found[0].startswith('Told tale: 2 scenes, cicones')
        assert found[0].endswith('; told in court')

    def test_a_run_mixing_told_scenes_and_a_flashback_says_both(self):
        found = self._messages([_row('court', '10', pov='odysseus'),
                                _row('memory', '-20', pov='odysseus'),
                                _row('cicones', '-3650', 'court', 'odysseus')])
        assert len(found) == 1
        assert found[0].startswith('Flashback: 2 scenes, memory')
        assert found[0].endswith('; 1 flashback, 1 told; told in court')

    def test_an_untold_flashback_reads_as_before(self):
        found = self._messages([_row('a', '10', pov='x'), _row('b', '3', pov='x')])
        assert found == ["Flashback: b (day 3) is set before the story's present "
                         "(day 10, reached in a)"]


class TestToldCues:
    def test_the_step_into_a_tale_is_earlier(self):
        from storyforge.timeline import told_cues
        rows = [_row('court', '10'), _row('cicones', '', 'court'), _row('lotus', '', 'court'),
                _row('home', '11')]
        cues = {'cicones': {'relation': 'continues'}, 'lotus': {'relation': 'later', 'gap': 'nine days'},
                'home': {'relation': 'later'}}
        out = told_cues(rows, cues)
        assert out['cicones'] == {'relation': 'earlier'}
        assert out['lotus'] == cues['lotus']   # going on through the tale
        assert out['home'] == cues['home']
        assert cues['cicones'] == {'relation': 'continues'}   # not changed in place

    def test_a_forward_gap_is_dropped_and_a_backward_one_kept(self):
        """Review of #587: "later, the next day" counted back would put
        the tale a day before its telling."""
        from storyforge.timeline import told_cues, walk
        rows = [_row('court', '10'), _row('cicones', '', 'court'), _row('x', '11'),
                _row('pyre', '', 'x')]
        out = told_cues(rows, {'cicones': {'relation': 'later', 'gap': 'the next day'},
                               'pyre': {'relation': 'continues', 'gap': 'years before'}})
        assert out['cicones'] == {'relation': 'earlier'}
        assert out['pyre'] == {'relation': 'earlier', 'gap': 'years before'}
        days = walk(['court', 'cicones'], out, last=10, present=10)
        assert days['cicones'] is None   # left for the model, not day 9

    def test_a_scene_with_no_cue_still_steps_back(self):
        from storyforge.timeline import told_cues
        assert told_cues([_row('a', '1'), _row('b', '', 'a')], {})['b'] == {'relation': 'earlier'}

    def test_a_told_vision_stays_a_vision(self):
        from storyforge.timeline import told_cues
        rows = [_row('a', '1'), _row('b', '', 'a')]
        assert told_cues(rows, {'b': {'relation': 'vision'}})['b'] == {'relation': 'vision'}

    def test_a_tale_inside_a_tale_steps_back_again(self):
        from storyforge.timeline import told_cues
        rows = [_row('court', '10'), _row('menelaus', '', 'court'), _row('proteus', '', 'menelaus')]
        out = told_cues(rows, {'menelaus': {'relation': 'continues'},
                               'proteus': {'relation': 'continues'}})
        assert out['proteus']['relation'] == 'earlier'


class TestCheckTimeline:
    def test_a_tale_cued_continues_is_not_the_present_going_backwards(self):
        """The regression: before #548 a told scene the cue read as
        "continues" or "later" was the present going backwards."""
        from storyforge.timeline import check_timeline
        rows = [_row('court', '10'), _row('cicones', '-3650', 'court'),
                _row('lotus', '-3640', 'court'), _row('ithaca', '11')]
        cues = {'cicones': {'relation': 'later'}, 'lotus': {'relation': 'later'},
                'ithaca': {'relation': 'later', 'gap': 'the next day'}}
        assert check_timeline(rows, cues) == []

    def test_the_same_scene_untold_is_still_found(self):
        from storyforge.timeline import check_timeline
        rows = [_row('court', '10'), _row('cicones', '-3650')]
        found = check_timeline(rows, {'cicones': {'relation': 'later'}})
        assert [f['check'] for f in found] == ['present_backwards']

    def test_a_tale_on_its_telling_day_with_a_long_gap_is_found(self):
        """B-006: Finnsburh's told scenes were put on the feast's own day."""
        from storyforge.timeline import check_timeline
        rows = [_row('feast', '5'), _row('pyre', '5', 'feast')]
        found = check_timeline(rows, {'pyre': {'relation': 'continues', 'gap': 'years before'}})
        assert [f['check'] for f in found] == ['flashback_not_earlier']

    def test_a_tale_set_after_its_telling_is_found(self):
        from storyforge.timeline import check_timeline
        rows = [_row('feast', '5'), _row('later', '9', 'feast'), _row('dawn', '10')]
        found = check_timeline(rows, {'later': {'relation': 'earlier'},
                                      'dawn': {'relation': 'later'}})
        # Once, not again as flashback_not_earlier (review of #587)
        assert [f['check'] for f in found] == ['told_after_telling']
        assert found[0]['scene_id'] == 'later' and 'day 5' in found[0]['message']

    def test_a_summary_telling_is_measured_from_its_stretchs_end(self):
        from storyforge.timeline import check_timeline
        rows = [_row('winter', '5', mode='summary'), _row('raid', '9', 'winter'),
                _row('spring', '20')]
        rows[0]['duration'] = '10 days'
        cues = {'raid': {'relation': 'earlier'}, 'spring': {'relation': 'later'}}
        assert [f['check'] for f in check_timeline(rows, cues)] == []
        rows[1]['timeline_day'] = '17'
        assert [f['check'] for f in check_timeline(rows, cues)] == ['told_after_telling']

    def test_a_summary_telling_of_unknown_length_is_not_measured(self):
        from storyforge.timeline import check_timeline
        rows = [_row('winter', '5', mode='summary'), _row('raid', '40', 'winter')]
        rows[0]['duration'] = 'all winter'
        found = check_timeline(rows, {'raid': {'relation': 'earlier'}})
        assert 'told_after_telling' not in [f['check'] for f in found]

    def test_a_told_vision_after_its_telling_is_not_found(self):
        from storyforge.timeline import check_timeline
        rows = [_row('seer', '5'), _row('doom', '900', 'seer', mode='vision')]
        assert check_timeline(rows, {'doom': {'relation': 'vision'}}) == []


class TestAssignment:
    def _project(self, project_dir, told):
        from storyforge.elaborate import update_scene
        ref = os.path.join(project_dir, 'reference')
        for sid, frame in told.items():
            update_scene(sid, ref, {'told_by': frame})

    def test_a_told_item_steps_back_and_says_where_it_is_told(self, project_dir):
        from storyforge.timeline import build_assignment_prompt, scene_items
        self._project(project_dir, {'act1-sc02': 'act1-sc01'})
        items = scene_items(project_dir, {'act1-sc02': {'relation': 'continues'}})
        told = [it for it in items if it['id'] == 'act1-sc02'][0]
        assert told['cues']['relation'] == 'earlier'
        assert told['told_by'] == 'act1-sc01'
        assert 'a tale told in act1-sc01' in build_assignment_prompt([told], 1, 1, [])

    def test_an_untold_item_has_no_key(self, project_dir):
        """So every book without told scenes sends the same prompt as before."""
        from storyforge.timeline import scene_items
        assert all('told_by' not in it for it in scene_items(project_dir, {}))


class TestDrafting:
    def test_the_calendar_says_where_a_scene_is_told(self):
        from storyforge.prompts import scene_when
        assert scene_when({'timeline_day': '-3650', 'told_by': 'court'}) == 'day -3650, told in court'
        assert scene_when({'timeline_day': '3'}) == 'day 3'

    def test_the_task_says_who_tells_it_and_where(self, project_dir):
        from storyforge.elaborate import update_scene
        from storyforge.prompts import build_scene_prompt_from_briefs
        ref = os.path.join(project_dir, 'reference')
        before = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN_DIR, 'full')
        assert 'This scene is told' not in before
        update_scene('act1-sc02', ref, {'told_by': 'act1-sc01'})
        prompt = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN_DIR, 'full')
        assert 'This scene is told by Dorren Hayle in act1-sc01: a tale inside that scene' in prompt


class TestElaboratePrompts:
    def test_the_map_writes_the_column(self, project_dir):
        from storyforge.prompts_elaborate import build_map_prompt
        prompt = build_map_prompt(project_dir, PLUGIN_DIR)
        assert '|architecture_scene|told_by\n' in prompt
        assert '- told_by: for an embedded tale' in prompt

    def test_the_briefs_know_a_told_scene(self, project_dir):
        from storyforge.prompts_elaborate import build_briefs_prompt
        assert 'A scene with told_by is a tale told inside that scene' in build_briefs_prompt(
            project_dir, PLUGIN_DIR)


class TestExtraction:
    def test_phase_1_asks_whether_a_scene_is_told(self):
        from storyforge.extract import SKELETON_SCHEMA, build_skeleton_prompt
        assert SKELETON_SCHEMA['properties']['told'] == {'type': 'boolean'}
        assert '- told: true when' in build_skeleton_prompt('s', 'text', {})

    def test_the_answer_is_read(self):
        from storyforge.extract import SKELETON_SCHEMA, skeleton_told
        reply = {k: [] if SKELETON_SCHEMA['properties'][k].get('type') == 'array' else ''
                 for k in SKELETON_SCHEMA['required']}
        assert skeleton_told(json.dumps(dict(reply, told=True))) is True
        assert skeleton_told(json.dumps(dict(reply, told=False))) is False

    def test_told_by_comes_from_reading_order(self):
        from storyforge.extract import told_by_from_answers
        order = ['court', 'cicones', 'lotus', 'interlude', 'hades', 'ithaca']
        assert told_by_from_answers(order, {'cicones', 'lotus', 'hades'}) == ({
            'cicones': 'court', 'lotus': 'court', 'hades': 'interlude'}, [])

    def test_the_first_scene_is_never_told(self):
        """Nothing tells it, and the tale it begins has lost its frame."""
        from storyforge.extract import told_by_from_answers
        assert told_by_from_answers(['a', 'b', 'c', 'd'], {'a', 'b', 'd'}) == (
            {'d': 'c'}, ['a', 'b'])

    def test_a_scene_with_no_answer_is_no_frame(self):
        """Review of #587: a told scene after one whose phase 1 reply
        failed must not name it as the frame, nor may the rest of its tale."""
        from storyforge.extract import told_by_from_answers
        order = ['court', 'failed', 'cicones', 'lotus', 'ithaca', 'tale']
        frames, unframed = told_by_from_answers(
            order, {'cicones', 'lotus', 'tale'}, set(order) - {'failed'})
        assert frames == {'tale': 'ithaca'}
        assert unframed == ['cicones', 'lotus']

    def _scenes(self, ref, told_by):
        header = ['id', 'seq', 'title', 'told_by']
        _write(os.path.join(ref, 'scenes.csv'), header,
               [{'id': sid, 'seq': str(i), 'title': sid, 'told_by': told_by.get(sid, '')}
                for i, sid in enumerate(['feast', 'pyre', 'vengeance', 'dawn'], 1)])

    def _column(self, ref):
        from storyforge.elaborate import _read_csv_as_map
        return {sid: r.get('told_by', '') for sid, r in
                _read_csv_as_map(os.path.join(ref, 'scenes.csv')).items()}

    def test_phase_1_writes_told_by(self, tmp_path):
        from storyforge.cmd_extract import _set_told_by
        self._scenes(str(tmp_path), {})
        _set_told_by(str(tmp_path), {'feast': False, 'pyre': True, 'vengeance': True,
                                     'dawn': False}, force=False)
        assert self._column(str(tmp_path)) == {'feast': '', 'pyre': 'feast',
                                               'vengeance': 'feast', 'dawn': ''}

    def test_an_authored_cell_is_kept_unless_forced(self, tmp_path):
        from storyforge.cmd_extract import _set_told_by
        self._scenes(str(tmp_path), {'dawn': 'feast'})
        answers = {'feast': False, 'pyre': True, 'vengeance': False, 'dawn': False}
        _set_told_by(str(tmp_path), answers, force=False)
        assert self._column(str(tmp_path))['dawn'] == 'feast'
        _set_told_by(str(tmp_path), answers, force=True)
        assert self._column(str(tmp_path))['dawn'] == ''

    def test_unframed_and_absent_tellers_are_logged(self, tmp_path, capsys):
        from storyforge.cmd_extract import _set_told_by
        ref = str(tmp_path)
        self._scenes(ref, {})
        _write(os.path.join(ref, 'scene-intent.csv'), ['id', 'characters', 'on_stage'],
               [{'id': 'feast', 'characters': 'hrothgar', 'on_stage': 'hrothgar'}])
        with open(os.path.join(ref, 'scenes.csv')) as f:
            lines = f.read().splitlines()
        lines[0] += '|pov'
        lines[2] += '|scop'
        lines[1] += '|'
        lines[3] += '|'
        lines[4] += '|'
        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('\n'.join(lines) + '\n')
        _set_told_by(ref, {'feast': True, 'pyre': False, 'vengeance': True, 'dawn': False},
                     force=False)
        out = capsys.readouterr().out
        assert 'no scene before them to tell them' in out and 'feast' in out
        _set_told_by(ref, {'feast': False, 'pyre': True, 'vengeance': False, 'dawn': False},
                     force=True)
        assert 'pyre (scop, not in feast)' in capsys.readouterr().out

    def test_an_unanswered_scene_is_left_alone(self, tmp_path):
        from storyforge.cmd_extract import _set_told_by
        self._scenes(str(tmp_path), {'vengeance': 'feast'})
        _set_told_by(str(tmp_path), {'feast': False}, force=True)
        assert self._column(str(tmp_path))['vengeance'] == 'feast'


class TestPresence:
    """Review of #587: a told scene's teller is in the telling scene, not
    in the tale, so they carry no physical states and count on no stage
    there unless the cast lists them."""

    def test_the_teller_is_not_present_in_the_tale(self):
        from storyforge.elaborate import present_in_scene
        scene = {'pov': 'scop', 'told_by': 'feast'}
        assert present_in_scene(scene, {'on_stage': 'hengest;finn'}) == {'hengest', 'finn'}

    def test_a_teller_in_their_own_tale_is_present(self):
        from storyforge.elaborate import present_in_scene
        scene = {'pov': 'odysseus', 'told_by': 'court'}
        assert present_in_scene(scene, {'on_stage': 'odysseus;polyphemus'}) == {
            'odysseus', 'polyphemus'}

    def test_an_untold_scenes_pov_is_present(self):
        from storyforge.elaborate import present_in_scene
        assert present_in_scene({'pov': 'scop'}, {'on_stage': 'hrothgar'}) == {'scop', 'hrothgar'}


class TestSceneMapScore:
    def test_a_told_scenes_teller_need_not_be_on_stage_in_the_tale(self, project_dir):
        from storyforge.elaborate import update_scene
        from storyforge.scoring_levels import score_scene_map
        ref = os.path.join(project_dir, 'reference')

        def pov_check():
            checks = score_scene_map(project_dir)['checks']
            return [c for c in checks if c['check'].startswith('POV is on-stage')][0]

        update_scene('act1-sc02', ref, {'pov': 'Tessa Merrin', 'status': 'mapped'})
        assert not pov_check()['passed']
        update_scene('act1-sc02', ref, {'told_by': 'act1-sc01'})
        assert pov_check()['passed']


class TestNarratorTeller:
    """After #584: the narrator (any reserved spelling) has no body to be in
    a cast, so a narrator-told digression gets no teller warning, and still
    counts toward narrator_pov's limit."""

    @pytest.mark.parametrize('pov', ['narrator', 'Omniscient narrator', 'omniscient'])
    def test_no_teller_warning_for_the_narrator(self, pov):
        checks = _structural([_row('hall', '8', pov='hygelac'),
                              _row('thryth', '-7300', 'hall', pov)],
                             [{'id': 'hall', 'characters': 'hygelac'}])
        assert checks['teller-in-telling-scene']['passed']

    def test_a_narrator_told_scene_counts_toward_the_limit(self):
        from storyforge.narrator import narrator_scenes
        assert narrator_scenes([_row('hall', '8', pov='hygelac'),
                                _row('thryth', '-7300', 'hall', 'narrator')]) == ['thryth']

    def test_the_narrator_teller_is_not_present(self):
        from storyforge.elaborate import present_in_scene
        assert present_in_scene({'pov': 'narrator', 'told_by': 'hall'},
                                {'on_stage': 'thryth'}) == {'thryth'}
