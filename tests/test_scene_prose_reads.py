"""Scene text that feeds analysis, scoring, word counts or a prompt never
carries illustration markers (#280).

Every site here reads through `illustrations.read_scene_prose`. Each test
writes the same scene with and without markers and asserts the consumer's
input is identical — so each fails when its site reads the file raw. The
prose is SCENE_ADVERSARIAL (see illustration_helpers for why a clean fixture
proves nothing).
"""

import os

import pytest

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


# ============================================================================
# Prompt inputs
# ============================================================================

def _mark(project_dir, sid):
    """Put markers at the start and end of a fixture scene; return its
    marker-free prose."""
    path = os.path.join(project_dir, 'scenes', f'{sid}.md')
    with open(path, encoding='utf-8') as f:
        prose = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'![[illus:{sid}-a]]\n\n{prose.rstrip()}\n\n![[illus:{sid}-b]]\n')
    return prose


def test_drafting_prompt_previous_scene(project_dir):
    from storyforge.prompts import build_scene_prompt, get_previous_scene
    prev = get_previous_scene('act1-sc02', project_dir)
    assert prev
    _mark(project_dir, prev)
    prompt = build_scene_prompt('act1-sc02', project_dir, api_mode=True)
    assert 'illus:' not in prompt


def test_story_so_far_blocks_and_word_budget(tmp_path, monkeypatch):
    from storyforge import prompts
    project_dir = _project(tmp_path, MARKED)
    monkeypatch.setattr(prompts, 'prior_scenes', lambda *a, **k: ['s1'])
    blocks = prompts.prior_prose_blocks('s2', project_dir, 'full')
    assert blocks[1]['text'] == f'<scene id="s1">\n{PROSE.strip()}\n</scene>'
    assert prompts._words(project_dir, 's1') == len(PROSE.split())


def test_a_markers_only_scene_has_no_prose(tmp_path):
    from storyforge.prompts import _has_prose
    assert not _has_prose(_project(tmp_path, '![[illus:lf-01]]\n'), 's1')


def test_scene_status_word_threshold(tmp_path):
    """get_scene_status calls a file of over 100 words drafted; markers
    don't count toward that."""
    from storyforge.prompts import get_scene_status
    prose = ' '.join(['word'] * 100) + '\n'
    markers = ''.join(f'![[illus:lf-{i}]]\n\n' for i in range(3))
    assert get_scene_status('s1', _project(tmp_path, markers + prose)) == 'pending'


def test_enrich_prompt(project_dir):
    from storyforge.enrich import build_enrich_prompt
    _mark(project_dir, 'act1-sc01')
    prompt = build_enrich_prompt('act1-sc01', project_dir)
    assert prompt and 'illus:' not in prompt


def test_enrich_time_of_day_ignores_a_marker(tmp_path):
    """A marker id is not a time cue (`lf-dawn` used to read as dawn)."""
    from storyforge.cmd_enrich import _infer_times_of_day
    project_dir = _project(tmp_path, '![[illus:lf-dawn]]\n\nShe waited in the hall.\n')
    csv_path = os.path.join(project_dir, 'scenes.csv')
    with open(csv_path, 'w') as f:
        f.write('id|location|time_of_day\ns1||\n')
    written, _ = _infer_times_of_day(csv_path, os.path.join(project_dir, 'scenes'),
                                     ['s1'], False)
    assert written == 0


def _gap_fill(sid, pd, sd):
    from storyforge.prompts_elaborate import build_gap_fill_prompt
    return build_gap_fill_prompt(sid, 'core', ['goal'], pd, sd)


def _knowledge_fix(sid, pd, sd):
    from storyforge.prompts_elaborate import build_knowledge_fix_prompt
    return build_knowledge_fix_prompt(sid, pd, sd, set())


def _physical_state_fix(sid, pd, sd):
    from storyforge.prompts_elaborate import build_physical_state_fix_prompt
    return build_physical_state_fix_prompt(sid, pd, sd, set())


@pytest.mark.parametrize('build', [_gap_fill, _knowledge_fix, _physical_state_fix])
def test_elaborate_fix_prompts(project_dir, build):
    prose = _mark(project_dir, 'act1-sc01')
    prompt = build('act1-sc01', project_dir, os.path.join(project_dir, 'scenes'))
    assert '### Prose Excerpt\n' + prose.strip()[:12] in prompt
    assert 'illus:' not in prompt


def test_hone_rewrite_name_check_ignores_marker_ids(tmp_path):
    """A name that appears only in a marker id is not in the prose."""
    from storyforge.hone import _apply_checked_rewrites
    project_dir = _project(tmp_path, '![[illus:Mallen-01]]\n\nThe warden waits at the door.\n')
    rejected = {}
    changed = _apply_checked_rewrites({}, 's1', {'goal': 'the warden, Mallen, waits'},
                                      {'goal': ''}, 'brief', project_dir, '', rejected)
    assert changed == 0 and 's1' in rejected


# ============================================================================
# Extraction
# ============================================================================

def test_extract_mark_drafted_skips_a_markers_only_scene(tmp_path):
    from storyforge.cmd_extract import _mark_drafted
    from storyforge.elaborate import _read_csv_as_map
    project_dir = _project(tmp_path, '![[illus:lf-01]]\n')
    ref_dir = os.path.join(project_dir, 'reference')
    os.makedirs(ref_dir)
    with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
        f.write('id|seq|title|status\ns1|1|One|\n')
    assert _mark_drafted(ref_dir, os.path.join(project_dir, 'scenes'), ['s1']) == 0
    assert _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))['s1']['status'] == ''


def test_extract_reads_scene_prose_only_through_the_reader():
    """Every extraction phase sends the scene to a prompt (or counts it), so
    none may open a scene file raw. Phases 1-3 need a batch API run to drive,
    so this is checked on the source; phase 4 is driven in
    test_extract_commitments."""
    import inspect
    import re
    from storyforge import cmd_extract
    src = inspect.getsource(cmd_extract)
    raw = re.findall(r'open\((?:scene_path|scene_file)\b|'
                     r'open\(os\.path\.join\(scenes_dir', src)
    assert raw == []
    assert src.count('read_scene_prose(') >= 10


# ============================================================================
# Word counts: thresholds, budgets and scenes.csv:word_count
# ============================================================================

def _words_and_markers(words, markers=3):
    return (''.join(f'![[illus:lf-{i}]]\n\n' for i in range(markers))
            + ' '.join(['word'] * words) + '\n')


def test_write_drafted_threshold(tmp_path):
    """`write` skips a scene of over 200 prose words; markers don't count
    toward them (a marked scene is kept for its markers instead:
    test_marker_write_back)."""
    from storyforge.cmd_write import _already_drafted
    project_dir = _project(tmp_path, _words_and_markers(201, markers=0))
    write_scene(project_dir, 's2', _words_and_markers(198))
    scenes_dir = os.path.join(project_dir, 'scenes')
    assert _already_drafted(scenes_dir, 's1') == 'already has 201 words'
    assert _already_drafted(scenes_dir, 's2').startswith('has 198 words and 3')


def test_write_forecast_earlier_words(project_dir):
    from storyforge.cmd_write import _forecast_earlier_words
    pending = ['act2-sc01']
    clean = _forecast_earlier_words(project_dir, pending, 'full', 1000)
    _mark(project_dir, 'act1-sc01')
    assert _forecast_earlier_words(project_dir, pending, 'full', 1000) == clean


def test_write_records_the_prose_word_count(project_dir):
    """The word_count `write` records for a drafted scene counts prose (T-3)."""
    from storyforge.cmd_write import _verify_and_commit_scene
    from storyforge.csv_cli import get_field
    from storyforge.git import _git
    prose = _mark(project_dir, 'act1-sc01')
    r = _git(project_dir, 'rev-parse', 'HEAD', check=False)
    head = r.stdout.strip() if r.returncode == 0 else 'none'
    csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    wc, ok = _verify_and_commit_scene('act1-sc01', project_dir,
                                      os.path.join(project_dir, 'scenes'), csv_path,
                                      'full', head, commit=False)
    assert ok and wc == len(prose.split())
    assert get_field(csv_path, 'act1-sc01', 'word_count') == str(wc)


def test_revise_update_word_counts_from_dir(project_dir):
    from storyforge.cmd_revise import _update_word_counts_from_dir
    from storyforge.csv_cli import get_field
    prose = _mark(project_dir, 'act1-sc01')
    _update_word_counts_from_dir(project_dir)
    csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    assert get_field(csv_path, 'act1-sc01', 'word_count') == str(len(prose.split()))


def test_revise_estimate_avg_words_file_fallback(tmp_path):
    from storyforge.cmd_revise import _estimate_avg_words
    assert _estimate_avg_words(_project(tmp_path, MARKED)) == (len(PROSE.split()), 1)


def test_revise_register_new_scene_word_count(tmp_path):
    from storyforge.cmd_revise import _register_new_scenes
    project_dir = _project(tmp_path, MARKED, sid='s-new')
    ref_dir = os.path.join(project_dir, 'reference')
    os.makedirs(ref_dir)
    meta = os.path.join(ref_dir, 'scenes.csv')
    with open(meta, 'w') as f:
        f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration'
                '|type|status|word_count|target_words\n')
    _register_new_scenes(project_dir, 'NEW:s-new', 'p')
    with open(meta) as f:
        row = f.read().splitlines()[1].split('|')
    assert row[0] == 's-new'
    assert row[row.index('drafted') + 1] == str(len(PROSE.split()))


def test_revise_upstream_fix_cost(project_dir):
    from storyforge.cmd_revise import _upstream_fix_cost
    clean = _upstream_fix_cost(project_dir, ['act1-sc01'])
    _mark(project_dir, 'act1-sc01')
    assert _upstream_fix_cost(project_dir, ['act1-sc01']) == clean > 0


def test_manuscript_word_count(tmp_path):
    from storyforge.project import _manuscript_word_count
    assert _manuscript_word_count(_project(tmp_path, MARKED)) == len(PROSE.split())


def test_assemble_dry_run_word_count(tmp_path):
    from storyforge.cmd_assemble import _word_count
    path = os.path.join(_project(tmp_path, MARKED), 'scenes', 's1.md')
    assert _word_count(path) == len(PROSE.split())


# ============================================================================
# Name checks and the bible scorer
# ============================================================================

def test_book_text_for_name_checks(tmp_path):
    """A marker id is not a name the book uses, and a markers-only scene
    has no prose."""
    from storyforge.brief_names import _book_text
    project_dir = _project(tmp_path, '![[illus:Mallen-01]]\n\nThe warden waits.\n')
    write_scene(project_dir, 's2', '![[illus:lf-02]]\n')
    text, drafted = _book_text(project_dir, ['s1', 's2'], [])
    assert 'illus' not in text and 'Mallen' not in text
    assert drafted == {'s1'}


def test_name_census_counts_prose_only(tmp_path, monkeypatch):
    from storyforge import extract_census
    project_dir = _project(tmp_path, MARKED)
    os.makedirs(os.path.join(project_dir, 'reference'))
    with open(os.path.join(project_dir, 'reference', 'scenes.csv'), 'w') as f:
        f.write('id|seq|title|status\ns1|1|One|drafted\n')
    seen = {}

    def count_names(texts, known):
        seen.update(texts)
        return []
    monkeypatch.setattr(extract_census, 'count_names', count_names)
    extract_census.run_census(project_dir, 'm', str(tmp_path / 'logs'))
    assert seen == {'s1': PROSE}


def test_bible_scorer_drafted_scenes(tmp_path):
    from storyforge.scoring_bible import _drafted_scenes
    project_dir = _project(tmp_path, MARKED)
    write_scene(project_dir, 's2', '![[illus:lf-09]]\n')
    assert _drafted_scenes(project_dir) == [('s1', PROSE)]


# ============================================================================
# Sites the read guard found (#610's review, T-2) and the reader's notes
# ============================================================================

def test_extract_acts_first_line(tmp_path):
    from storyforge.extract_acts import _first_line
    project_dir = _project(tmp_path, '![[illus:lf-01]]\n\nThe lamp was lit.\n')
    assert _first_line(os.path.join(project_dir, 'scenes'), 's1') == 'The lamp was lit.'


def test_scene_title_from_file_skips_a_marker(tmp_path):
    """A marker as the first line would have become the title, and the slug."""
    from storyforge.scenes import _title_from_file
    path = os.path.join(_project(tmp_path, '![[illus:lf-01]]\n\nThe lamp was lit.\n'),
                        'scenes', 's1.md')
    assert _title_from_file(path) == 'The lamp was lit.'


def test_gate_has_prose_agrees_with_prompts(tmp_path):
    """A file of markers alone has no prose, for the gate as for drafting."""
    from storyforge import gate, prompts
    project_dir = _project(tmp_path, '![[illus:lf-01]]\n')
    assert gate._has_prose(project_dir, 's1') is False
    assert prompts._has_prose(project_dir, 's1') is False


def test_revision_pass_prompt(project_dir):
    """An API revision pass inlines the scenes it revises without their
    markers; the reply is written back with them (test_marker_write_back)."""
    from storyforge.revision import build_revision_prompt
    prose = _mark(project_dir, 'act1-sc01')
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=True)
    assert prose.strip()[:40] in prompt and 'illus:' not in prompt


def test_scene_score_prompt(project_dir):
    from storyforge.cmd_score import _build_scene_prompt
    prose = _mark(project_dir, 'act1-sc01')
    ref = os.path.join(project_dir, 'reference')
    prompt = _build_scene_prompt('act1-sc01', '{{SCENE_TEXT}}', '', '',
                                 os.path.join(ref, 'scenes.csv'),
                                 os.path.join(ref, 'scene-intent.csv'),
                                 os.path.join(project_dir, 'scenes'))
    assert prose.splitlines()[-1].strip()[:40] in prompt and 'illus:' not in prompt


def test_reader_notes_like_read_text_noting(tmp_path):
    from storyforge.illustrations import read_scene_prose
    path = tmp_path / 's.md'
    path.write_bytes(b'caf\xe9.\n\n![[illus:lf-01]]\n')
    notes = []
    assert read_scene_prose(str(path), notes=notes, label='scenes/s.md') == 'caf�.\n'
    assert notes == ['scenes/s.md is not UTF-8: read with replacement characters']
    notes = []
    assert read_scene_prose(str(tmp_path / 'gone.md'), notes=notes) == ''
    assert 'could not be read' in notes[0]


# ============================================================================
# What can't be read, or isn't a marker, is said (#610's review, SF-1..SF-5)
# ============================================================================

NOT_UTF8 = b'The lamp \x93burned\x94 all night.\n'


def _bad_scene(project_dir, sid='s1'):
    path = os.path.join(project_dir, 'scenes', f'{sid}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(NOT_UTF8)
    return path


def test_manuscript_word_count_names_an_unreadable_scene(tmp_path, capsys):
    """SF-1: a non-UTF-8 scene was left out of the total silently."""
    from storyforge.project import _manuscript_word_count
    project_dir = _project(tmp_path, MARKED)
    _bad_scene(project_dir, 's2')
    unread = []
    assert _manuscript_word_count(project_dir, unread) == len(PROSE.split())
    assert unread == ['scenes/s2.md (UnicodeDecodeError)']
    assert _manuscript_word_count(project_dir) == len(PROSE.split())
    assert 'leaves out 1 scene file(s) it could not read: scenes/s2.md' in capsys.readouterr().err


def test_project_summary_lists_the_unread_scenes(project_dir):
    from storyforge.project import project_summary
    assert project_summary(project_dir)['word_count_unread'] == []
    _bad_scene(project_dir, 'act1-sc01')
    assert project_summary(project_dir)['word_count_unread'] == [
        'scenes/act1-sc01.md (UnicodeDecodeError)']


@pytest.mark.parametrize('bad', ['![[illus:lf 01]]', '![[illus:lf-01]', '![[illus:]]',
                                 '![[illus:-lf]]'])
def test_a_malformed_marker_is_reported(project_dir, bad):
    """SF-2: `![[illus:` that is no marker is neither stripped nor rendered."""
    from storyforge import illustrations as ill
    from storyforge.cmd_cleanup import _ILLUSTRATION_ACTIONS
    write_scene(project_dir, 'act1-sc01', f'The lamp.\n\n{bad}\n\nThe dark.\n')
    assert ill.strip_markers(f'a {bad} b') == f'a {bad} b'
    found = [f for f in ill.validate_plan(project_dir) if f['kind'] == 'malformed_marker']
    assert [f['scene_id'] for f in found] == ['act1-sc01']
    assert bad in found[0]['detail']
    assert ill.severity_of('malformed_marker') == 'error'
    assert 'malformed_marker' in _ILLUSTRATION_ACTIONS


def test_a_good_marker_is_not_malformed():
    from storyforge.illustrations import malformed_markers
    assert malformed_markers('a\n\n![[illus:lf-01]]\n\nb ![[illus:x_2]] c') == []


def test_scene_status_of_an_unreadable_scene(tmp_path):
    """SF-3: it was 'pending', so `write` drafted over a file it never read."""
    from storyforge.prompts import get_scene_status
    project_dir = str(tmp_path)
    _bad_scene(project_dir)
    assert get_scene_status('s1', project_dir) == 'unreadable'


def test_write_does_not_draft_over_an_unreadable_scene(tmp_path, capsys):
    from storyforge.cmd_write import _filter_pending
    project_dir = str(tmp_path)
    _bad_scene(project_dir)
    assert _filter_pending(['s1'], project_dir, '', False, 'all') == ([], 1)
    assert "scenes/s1.md can't be read" in capsys.readouterr().out


def test_hone_name_check_notes_replaced_bytes(tmp_path, capsys):
    """SF-4: a rejection over a name the prose spells with a bad byte says
    the prose was read with replacement characters."""
    from storyforge.hone import _apply_checked_rewrites
    project_dir = str(tmp_path)
    _bad_scene(project_dir)
    rejected = {}
    assert _apply_checked_rewrites({}, 's1', {'goal': 'Mallen waits'}, {'goal': ''},
                                   'brief', project_dir, '', rejected) == 0
    out = capsys.readouterr().out
    assert 'scenes/s1.md is not UTF-8: read with replacement characters' in out


def test_boundary_reports_an_unreadable_draft(tmp_path):
    """SF-5: a draft 6->7 can't read is a result, not only a log line."""
    from storyforge.scoring_boundary import score_boundary
    project_dir = str(tmp_path)
    _bad_scene(project_dir)
    os.makedirs(os.path.join(project_dir, 'reference'))
    with open(os.path.join(project_dir, 'reference', 'scene-briefs.csv'), 'w') as f:
        f.write('id|goal\ns1|Wait for the street\n')
    [result] = score_boundary(project_dir, '6->7', model='m', coaching_level='full',
                              dry_run=True)
    assert result['scope'] == 's1' and result['persisted'] is False
    assert result['alignment'].startswith('not checked: could not read the draft')
