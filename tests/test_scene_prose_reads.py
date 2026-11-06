"""Scene text that feeds analysis, scoring, word counts or a prompt never
carries illustration markers (#280).

Every site here reads through `illustrations.read_scene_prose`. Each test
writes the same scene with and without markers and asserts the consumer's
input is identical — so each fails when its site reads the file raw. The
prose is SCENE_ADVERSARIAL (see illustration_helpers for why a clean fixture
proves nothing).
"""

import os

from illustration_helpers import SCENE_ADVERSARIAL, write_scene

#: Long enough that word-count floors (timeline's 100) don't mask a marker.
PROSE = '\n'.join([SCENE_ADVERSARIAL] * 4)

#: The same prose with an own-line marker at the start, one between two
#: paragraphs, and one at the end — the three places --embed puts them.
MARKED = ('![[illus:lf-01]]\n\n'
          + PROSE.replace('By morning', '![[illus:lf-02]]\n\nBy morning', 1)
          + '\n![[illus:lf-03]]\n')


def _project(root, text, sid='s1'):
    project_dir = str(root)
    write_scene(project_dir, sid, text)
    return project_dir


def test_fixture_markers_are_present_and_strip_to_the_prose():
    from storyforge.illustrations import strip_markers
    assert MARKED.count('![[illus:') == 3
    assert strip_markers(MARKED) == PROSE


def test_score_load_scene_texts(tmp_path):
    from storyforge.cmd_score import _load_scene_texts
    project_dir = _project(tmp_path, MARKED)
    assert _load_scene_texts(['s1'], project_dir) == {'s1': PROSE}


def test_score_avg_word_count_fallback(tmp_path):
    from storyforge.cmd_score import _avg_word_count
    project_dir = _project(tmp_path, MARKED)
    no_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    assert _avg_word_count(no_csv, ['s1'], os.path.join(project_dir, 'scenes')) \
        == len(PROSE.split())


def test_text_fidelity_prose(tmp_path):
    from storyforge.scoring_text_fidelity import _prose
    assert _prose(_project(tmp_path, MARKED), 's1') == PROSE.strip()


def test_boundary_brief_vs_draft(tmp_path):
    from storyforge.scoring_boundary import _collect_per_brief_vs_draft
    project_dir = _project(tmp_path, MARKED)
    os.makedirs(os.path.join(project_dir, 'reference'))
    with open(os.path.join(project_dir, 'reference', 'scene-briefs.csv'), 'w') as f:
        f.write('id|goal\ns1|Wait for the street\n')
    [(sid, _upstream, downstream)] = _collect_per_brief_vs_draft(project_dir, None)
    assert (sid, downstream) == ('s1', PROSE)


def test_extract_acts_opening(tmp_path):
    from storyforge.extract_acts import _opening
    clean = _opening(os.path.join(_project(tmp_path / 'c', PROSE), 'scenes'), 's1')
    marked = _opening(os.path.join(_project(tmp_path / 'm', MARKED), 'scenes'), 's1')
    assert marked == clean
    assert 'illus' not in marked


def test_timeline_scene_text(tmp_path):
    from storyforge.timeline import scene_text
    assert scene_text(_project(tmp_path, MARKED), 's1') == (PROSE, False)


def test_extract_read_all_scenes(tmp_path):
    from storyforge.extract import _read_all_scenes
    assert _read_all_scenes(_project(tmp_path, MARKED)) == {'s1': PROSE}
