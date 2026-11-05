"""#550: in a faithful adaptation the source fixes most outcomes, and the
outcome advice says so instead of asking for relabels that source fidelity
then flags as drift (Gawain G-025)."""

import os

import pytest

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


def test_faithful_scores_only_the_outcomes_the_source_leaves_open():
    """Ben's call on #550: the source's outcomes are not marked down."""
    intent, briefs = _maps({'council': 'yes-but', 'door-two': 'yes-but', 'night': 'yes-but',
                            'door-one': 'yes', 'dream': 'no'})
    fixed = ['council', 'door-two', 'night']
    faithful = score_function_variety(intent, briefs, fixed)
    open_only = score_function_variety(
        {k: v for k, v in intent.items() if k not in fixed},
        {k: v for k, v in briefs.items() if k not in fixed})
    plain = score_function_variety(intent, briefs)
    # outcome variety is over door-one and dream alone (two kinds, even: 1.0)
    assert faithful['score'] == open_only['score']
    assert faithful['score'] > plain['score']


def test_a_dominant_outcome_among_the_open_scenes_is_still_found():
    outcomes = {f'open-{n}': 'yes-but' for n in range(4)}
    outcomes.update({'open-4': 'no', 'fixed-1': 'no', 'fixed-2': 'yes'})
    intent, briefs = _maps(outcomes)
    msg = [f['message'] for f in
           score_function_variety(intent, briefs, ['fixed-1', 'fixed-2'])['findings']
           if 'Dominant outcome' in f['message']][0]
    assert msg == ("Dominant outcome 'yes-but' in 4/5 scenes (80%) of those the source "
                   "leaves open; the 2 that keep the source's outcome (faithful mode) "
                   "are not counted")


def test_when_the_source_fixes_every_outcome_only_type_and_turns_count():
    intent, briefs = _maps({'a': 'yes-but', 'b': 'yes-but'})
    intent['b'] = {'action_sequel': 'sequel', 'turning_point': 'revelation'}
    r = score_function_variety(intent, briefs, ['a', 'b'])
    # type balance 1.0 and turning-point variety 0.5, outcome left out
    assert r['score'] == pytest.approx((1.0 * 0.35 + 0.5 * 0.30) / 0.65)
    assert not any('Dominant outcome' in f['message'] for f in r['findings'])


def _variety(report):
    return next(d for d in report['dimensions'] if d['name'] == 'function_variety')


def _outcome_files(proj, outcomes):
    _write(proj, {
        'reference/scene-intent.csv': 'id|action_sequel|turning_point\n'
        + ''.join(f'{s}|action|action\n' for s in outcomes),
        'reference/scene-briefs.csv': 'id|outcome\n'
        + ''.join(f'{s}|{o}\n' for s, o in outcomes.items())})


OUTCOMES = {'council': 'yes-but', 'door-one': 'yes-but', 'door-two': 'yes-but',
            'night': 'yes-but', 'dream': 'no'}


def test_structural_score_reads_the_adaptation(tmp_path):
    proj = _project(tmp_path)
    _outcome_files(proj, OUTCOMES)
    dim = _variety(structural_score(os.path.join(proj, 'reference')))
    intent, briefs = _maps(OUTCOMES)
    assert dim['score'] == score_function_variety(
        intent, briefs, ['council', 'door-two', 'night'])['score']
    assert dim['score'] != score_function_variety(intent, briefs)['score']


def test_free_mode_scores_every_outcome_as_before(tmp_path):
    proj = _project(tmp_path, 'free')
    _outcome_files(proj, OUTCOMES)
    dim = _variety(structural_score(os.path.join(proj, 'reference')))
    intent, briefs = _maps(OUTCOMES)
    plain = score_function_variety(intent, briefs)
    assert dim['score'] == plain['score'] and dim['findings'] == plain['findings']


def test_a_book_without_a_source_scores_as_before(project_dir):
    from storyforge.elaborate import _read_csv_as_map
    ref = os.path.join(project_dir, 'reference')
    plain = score_function_variety(_read_csv_as_map(os.path.join(ref, 'scene-intent.csv')),
                                   _read_csv_as_map(os.path.join(ref, 'scene-briefs.csv')))
    dim = _variety(structural_score(ref))
    assert dim['score'] == plain['score'] and dim['findings'] == plain['findings']
    assert score_function_variety({}, {}, []) == score_function_variety({}, {})
