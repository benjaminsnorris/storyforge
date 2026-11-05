"""#550: in a faithful adaptation the source fixes most outcomes, and the
outcome advice says so instead of asking for relabels that source fidelity
then flags as drift (Gawain G-025)."""

import os

from storyforge import source_fidelity as sf
from storyforge.structural import score_function_variety, structural_score

from source_helpers import YAML, _write, make_adaptation

MAP = ('scene_id|source_scenes|treatment|note\n'
       'council|gods-debate|dramatize|\n'          # single source: fixed
       'door-one|minerva-visits|dramatize|\n'      # split: earlier part, open
       'door-two|minerva-visits|dramatize|\n'      # split: last part, fixed
       'night|ship-sails;assembly-called|compress|\n'  # ends on assembly-called: fixed
       'dream||invent|\n')                          # invented: open
SCENES = ('id|seq|title\n'
          'council|1|a\ndoor-one|2|b\ndoor-two|3|c\nnight|4|d\ndream|5|e\n')


def _project(tmp_path, mode='faithful'):
    proj = make_adaptation(tmp_path)
    _write(proj, {'storyforge.yaml': YAML.format(extra=f'  mode: {mode}'),
                  'reference/source-map.csv': MAP,
                  'reference/scenes.csv': SCENES})
    return proj


def test_the_source_fixes_single_source_scenes_and_the_last_part_of_a_split(tmp_path):
    assert sf.source_fixed_outcomes(_project(tmp_path)) == ['council', 'door-two', 'night']


def test_free_mode_and_no_source_fix_nothing(tmp_path, project_dir):
    assert sf.source_fixed_outcomes(_project(tmp_path, 'free')) == []
    assert sf.source_fixed_outcomes(project_dir) == []


def _maps(outcomes):
    intent = {sid: {'action_sequel': 'action', 'turning_point': 'action'} for sid in outcomes}
    briefs = {sid: {'outcome': o} for sid, o in outcomes.items()}
    return intent, briefs


def test_the_dominant_outcome_finding_names_the_fixed_scenes():
    intent, briefs = _maps({'council': 'yes-but', 'door-two': 'yes-but', 'night': 'yes-but',
                            'door-one': 'yes-but', 'dream': 'no'})
    plain = score_function_variety(intent, briefs)
    faithful = score_function_variety(intent, briefs, ['council', 'door-two', 'night'])
    assert faithful['score'] == plain['score']
    msg = [f['message'] for f in faithful['findings'] if 'Dominant outcome' in f['message']][0]
    assert ("3 of them keep the source's outcome (faithful mode) and stay: "
            "vary only the other 1") in msg


def test_structural_score_reads_the_adaptation(tmp_path):
    proj = _project(tmp_path)
    _write(proj, {
        'reference/scene-intent.csv': 'id|action_sequel|turning_point\n'
        + ''.join(f'{s}|action|action\n' for s in ('council', 'door-one', 'door-two',
                                                   'night', 'dream')),
        'reference/scene-briefs.csv': 'id|outcome\n'
        + ''.join(f'{s}|yes-but\n' for s in ('council', 'door-one', 'door-two', 'night'))
        + 'dream|no\n'})
    report = structural_score(os.path.join(proj, 'reference'))
    dim = next(d for d in report['dimensions'] if d['name'] == 'function_variety')
    assert any('vary only the other 1' in f['message'] for f in dim['findings'])
