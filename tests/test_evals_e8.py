import copy
import subprocess
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import e8  # noqa: E402
from test_evals_e1 import CASE  # noqa: E402


def _tool_case(**changes):
    case = copy.deepcopy(CASE)
    case.update(subsets=['tool-introduced'],
                introduced_by={'kind': 'tool', 'pass': 'redraft-from-corrected-briefs',
                               'commit': 'abc1234'})
    case.update(changes)
    return case


@pytest.mark.parametrize('name, expected', [
    ('redraft-from-corrected-briefs', 'redraft-from-brief'),
    ('write (04-07 full redraft)', 'redraft-from-brief'),
    ('naturalness-craft-polish', 'revision-plan'),
    ('continuity-audit', 'revision-plan'),
])
def test_family(name, expected):
    assert e8.family(_tool_case(introduced_by={'kind': 'tool', 'pass': name})) == expected


def test_select_reports_every_exclusion():
    cases = [
        _tool_case(id='book-001'),
        _tool_case(id='book-002'),
        _tool_case(id='book-003', level='csv'),
        _tool_case(id='book-004', introduced_by={'kind': 'tool', 'pass': 'hone (registries)'}),
        _tool_case(id='book-005', introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': ''}),
        copy.deepcopy(CASE),  # not tool-introduced: not E8's at all
    ]
    sel = e8.select(cases, holdout=['book-002'])
    assert [c['id'] for c in sel.cases] == ['book-001']
    assert sel.excluded == {
        'holdout': ['book-002'],
        'csv-level (no prose to redraft)': ['book-003'],
        'pass not replayable yet: hone (registries)': ['book-004'],
        'no introducing commit recorded': ['book-005'],
    }


@pytest.mark.parametrize('text, verdict', [
    ('{"verdict": "reintroduced", "evidence": "Five hours."}', 'reintroduced'),
    ('Sure.\n{"verdict": "not_present", "evidence": ""}', 'not_present'),
])
def test_parse_verdict(text, verdict):
    assert e8.parse_verdict(text)['verdict'] == verdict


@pytest.mark.parametrize('text', ['no json here', '{"verdict": "maybe"}', '{"verdict": '])
def test_unreadable_verdict_raises_never_counts_as_safe(text):
    with pytest.raises(ValueError):
        e8.parse_verdict(text)


def test_judge_prompt_carries_both_sides():
    prompt = e8.judge_prompt(CASE, 'NEW PROSE')
    assert 'Three hours. Bend to Portland.' in prompt
    assert '"Five hours," he said.' in prompt and 'NEW PROSE' in prompt
    absent = e8.judge_prompt({**CASE, 'established': [], 'established_by_absence': 'never told'}, 'x')
    assert 'never told' in absent


@pytest.fixture(params=[True])
def book(tmp_path, request):
    repo = tmp_path / 'corpus' / 'book'
    (repo / 'scenes').mkdir(parents=True)
    (repo / 'reference').mkdir()
    git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'scenes' / 'phone-call.md').write_text('Three hours.\n')
    (repo / 'reference' / 'scene-briefs.csv').write_text('id|goal\nphone-call|x\n')
    if request.param:
        (repo / 'reference' / 'scenes.csv').write_text('id|seq\nphone-call|1\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'before'], check=True)
    (repo / 'scenes' / 'phone-call.md').write_text('"Five hours," he said.\n')
    subprocess.run(git + ['commit', '-qam', 'redraft'], check=True)
    sha = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    return tmp_path / 'corpus', sha


def test_prepare_materializes_the_pre_pass_tree(book, tmp_path):
    root, sha = book
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': sha})
    project, scene = e8.prepare(case, str(tmp_path / 'work'), str(root))
    assert scene == 'phone-call'
    with open(f'{project}/scenes/phone-call.md') as f:
        assert f.read() == 'Three hours.\n'  # the state the pass saw, not its output


def test_prepare_refuses_when_the_commit_did_not_touch_the_scene(book, tmp_path):
    root, sha = book
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': sha},
                      contradicted=[{**CASE['contradicted'][0], 'scene': 'other', 'path': 'scenes/other.md'}])
    with pytest.raises(LookupError, match='changed none'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_the_e8_suite_loads():
    import harness
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'e8-revision-safety' in names


@pytest.mark.parametrize('name, expected', [
    ('naturalness (upstream brief fixes)', 'naturalness-upstream'),
    ('stakes-and-history', 'revision-plan'),
    ('hone (registries/physical-states)', 'hone-physical-states'),
    ('hone-registries-physical-states', 'hone-physical-states'),
    ('hone (briefs)', ''),
    ('illustrate --state', 'illustrate-state'),
    ('illustrate --prompts', 'illustrate-prompts'),
    ('illustrate --embed', ''),
    ('upstream-brief-fixes', 'brief-fix'),
])
def test_more_families(name, expected):
    assert e8.family(_tool_case(introduced_by={'kind': 'tool', 'pass': name})) == expected


def test_pass_block_mirrors_cmd_revise():
    row = {'name': 'p', 'purpose': 'u', 'scope': 'scene-level', 'targets': 'a;b',
           'guidance': 'g', 'protection': '', 'findings': 'scores'}
    assert e8._pass_block(row) == ('- name: p\n    purpose: u\n    scope: scene-level'
                                   '\n    targets: a;b\n    guidance: g\n    findings: scores')


def test_plan_row_prefers_the_newest_plan(tmp_path):
    plans = tmp_path / 'working' / 'plans'
    plans.mkdir(parents=True)
    header = 'pass|name|purpose|scope|targets|guidance|protection|findings|status|model_tier|fix_location\n'
    (plans / 'revision-plan-2.csv').write_text(header + '1|polish|old|full||||||opus|craft\n')
    (plans / 'revision-plan-10.csv').write_text(header + '1|polish|new|full||||||opus|craft\n')
    assert e8.plan_row(str(tmp_path), 'polish')['purpose'] == 'new'
    with pytest.raises(LookupError, match='no CSV plan'):
        e8.plan_row(str(tmp_path), 'missing')


@pytest.mark.parametrize('book', [False], indirect=True)
def test_prepare_refuses_a_project_older_than_scenes_csv(book, tmp_path):
    root, sha = book
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': sha})
    with pytest.raises(LookupError, match='predates reference/scenes.csv'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_a_naturalness_redraft_that_halts_is_pass_halted(monkeypatch):
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, '_fix_upstream_briefs', lambda p, ids: (['s'], {}))

    def halt(p, ids):
        raise cmd_revise.RedraftError('1 scene(s) not re-drafted: s (cut off)')
    monkeypatch.setattr(cmd_revise, '_redraft_scenes', halt)
    with pytest.raises(e8.PassHalted, match='cut off'):
        e8.naturalness_upstream('/nowhere', 's')


def test_a_naturalness_fix_that_rewrites_nothing_is_pass_halted_with_why(monkeypatch):
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, '_fix_upstream_briefs',
                        lambda p, ids: ([], {'s': 'named Mallen'}))
    monkeypatch.setattr(cmd_revise, '_redraft_scenes',
                        lambda p, ids: pytest.fail('nothing to redraft'))
    with pytest.raises(e8.PassHalted, match='rewrote nothing for s: named Mallen'):
        e8.naturalness_upstream('/nowhere', 's')


def test_the_suite_notes_name_the_cases_prepare_could_not_replay(monkeypatch, tmp_path):
    import importlib
    suite = importlib.import_module('suites.e8_revision_safety')
    sel = e8.Selection(cases=[_tool_case(id='book-001')])
    sel.exclude('holdout', 'book-002')
    monkeypatch.setattr(suite, 'select', lambda cases, holdout: sel)

    def unreplayable(case, work_dir):
        raise LookupError('pre-pass project predates reference/scenes.csv')
    monkeypatch.setattr(suite, 'prepare', unreplayable)
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    assert ('excluded 1: unreplayable: pre-pass project predates reference/scenes.csv (book-001)'
            in out.notes)
    assert 'excluded 1: holdout (book-002)' in out.notes
    assert out.metrics['unreplayable'] == 1


def _rename_book(tmp_path, *, established_only=False):
    """A book whose pass rewrote s09-ledger.md, later renamed garrens-ledger.md."""
    repo = tmp_path / 'corpus' / 'book'
    (repo / 'scenes').mkdir(parents=True)
    (repo / 'reference').mkdir()
    git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'scenes' / 's09-ledger.md').write_text('Still five.\n')
    (repo / 'scenes' / 's02-letter.md').write_text('Five.\n')
    (repo / 'reference' / 'scene-metadata.csv').write_text(
        'id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words\n'
        's09-ledger|1|Ledger|kael|hall|1|scene|3|night|revised|1188|\n'
        's02-letter|2|Letter|kael|hall|1|scene|3|night||0|900\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'before'], check=True)
    changed = 's02-letter.md' if established_only else 's09-ledger.md'
    (repo / 'scenes' / changed).write_text('Six.\n')
    subprocess.run(git + ['commit', '-qam', 'quick-fixes'], check=True)
    sha = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    maps = tmp_path / 'id-maps'
    maps.mkdir()
    (maps / 'book.csv').write_text('old_path|slug|commit|method|notes\n'
                                   'scenes/s09-ledger.md|garrens-ledger|abc|rename|\n'
                                   'scenes/s02-letter.md|four-at-table|abc|rename|\n')
    case = _tool_case(
        repo='book', introduced_by={'kind': 'tool', 'pass': 'quick-fixes', 'commit': sha},
        established=[{'scene': 'four-at-table', 'path': 'scenes/four-at-table.md',
                      'commit': 'abc', 'quote': 'Five.'}],
        contradicted=[{'scene': 'garrens-ledger', 'path': 'scenes/garrens-ledger.md',
                       'commit': 'abc', 'quote': 'Six.'}])
    return tmp_path / 'corpus', maps, case


def test_a_scene_renamed_after_the_pass_is_found_through_the_id_map(tmp_path, monkeypatch):
    root, maps, case = _rename_book(tmp_path)
    monkeypatch.setattr(e8, 'ID_MAPS_DIR', str(maps))
    monkeypatch.setattr(e8, 'plan_row', lambda p, name: {'name': name})
    project, scene = e8.prepare(case, str(tmp_path / 'work'), str(root))
    assert scene == 's09-ledger'  # the pre-pass id, which the replay runs on


def test_a_pass_that_wrote_only_the_established_side_says_so(tmp_path, monkeypatch):
    root, maps, case = _rename_book(tmp_path, established_only=True)
    monkeypatch.setattr(e8, 'ID_MAPS_DIR', str(maps))
    with pytest.raises(LookupError, match=r'wrote only the established side \(four-at-table\)'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_scene_metadata_is_migrated_in_the_copy_as_storyforge_migrated_it(tmp_path, monkeypatch):
    root, maps, case = _rename_book(tmp_path)
    monkeypatch.setattr(e8, 'ID_MAPS_DIR', str(maps))
    monkeypatch.setattr(e8, 'plan_row', lambda p, name: {'name': name})
    project, _ = e8.prepare(case, str(tmp_path / 'work'), str(root))
    with open(f'{project}/reference/scenes.csv') as f:
        lines = f.read().splitlines()
    assert lines == ['id|seq|title|part|pov|location|timeline_day|time_of_day|duration|status|'
                     'word_count|target_words',
                     's09-ledger|1|Ledger|1|kael||3|night||revised|1188|',
                     's02-letter|2|Letter|1|kael||3|night||mapped|0|900']
    assert not (root / 'book' / 'reference' / 'scenes.csv').exists()  # never the book repo
    assert not (tmp_path / 'work' / case['id'] / 'reference' / 'scene-briefs.csv').exists()


def test_a_yaml_project_is_unreplayable_with_the_reason(tmp_path, monkeypatch):
    root, maps, case = _rename_book(tmp_path)
    repo = root / 'book'
    git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(git + ['rm', '-q', 'reference/scene-metadata.csv'], check=True)
    (repo / 'scenes' / 'scene-index.yaml').write_text('- id: s09-ledger\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'yaml'], check=True)
    (repo / 'scenes' / 's09-ledger.md').write_text('Seven.\n')
    subprocess.run(git + ['commit', '-qam', 'pass'], check=True)
    sha = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    case['introduced_by']['commit'] = sha
    monkeypatch.setattr(e8, 'ID_MAPS_DIR', str(maps))
    with pytest.raises(LookupError, match='refuses YAML plans'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_a_csv_level_case_is_selected_when_its_pass_writes_data():
    hone = _tool_case(id='b-1', level='csv',
                      introduced_by={'kind': 'tool', 'pass': 'hone-registries-physical-states',
                                     'commit': 'abc'})
    other = _tool_case(id='b-2', level='csv')
    sel = e8.select([hone, other], [])
    assert [c['id'] for c in sel.cases] == ['b-1']
    assert sel.excluded == {'csv-level (no prose to redraft)': ['b-2']}


def test_written_gives_the_header_and_the_new_lines_only():
    before = {'reference/physical-states.csv': 'id|character\nscar-kael|Kael\n'}
    after = {'reference/physical-states.csv': 'id|character\nscar-kael|Kael\nbraid-kael|Kael\n',
             'reference/illustration-prompts/LF-13.md': 'every lantern out\n'}
    assert e8.written(before, after) == (
        'reference/illustration-prompts/LF-13.md (new file):\nevery lantern out\n\n'
        'reference/physical-states.csv:\nid|character\nbraid-kael|Kael')
    assert e8.written(before, before) == ''


def test_a_data_case_is_judged_on_what_the_pass_wrote():
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'upstream-brief-fixes', 'commit': 'a'})
    prompt = e8.judge_prompt(case, 'shell-breaks-open|Director Tessamine')
    assert '<written>\nshell-breaks-open|Director Tessamine\n</written>' in prompt
    assert '<scene>' not in prompt
    # the prose judge prompt is unchanged, so recorded verdicts still replay
    assert '<scene>' in e8.judge_prompt(_tool_case(), 'x')


def test_a_brief_fix_that_rewrites_nothing_is_pass_halted_with_why(monkeypatch, tmp_path):
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, '_fix_upstream_briefs',
                        lambda p, ids: ([], {'s': 'names Tessamine, found nowhere'}))
    with pytest.raises(e8.PassHalted, match='found nowhere'):
        e8.brief_fix(str(tmp_path), 's')


def test_a_data_pass_that_writes_nothing_is_not_present_without_a_judge(monkeypatch, tmp_path):
    import importlib
    suite = importlib.import_module('suites.e8_revision_safety')
    case = _tool_case(id='b-1', introduced_by={'kind': 'tool', 'pass': 'hone (registries/physical-states)',
                                               'commit': 'abc'})
    monkeypatch.setattr(suite, 'select', lambda cases, holdout: e8.Selection(cases=[case]))
    monkeypatch.setattr(suite, 'prepare', lambda c, w: (str(tmp_path), 's'))
    monkeypatch.setattr(suite, 'replay', lambda c, p, s: '')
    monkeypatch.setattr(suite, 'judge', lambda c, t: pytest.fail('judged empty output'))
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    assert out.metrics['replayed'] == 1 and out.metrics['reintroduced'] == 0
    assert 'b-1 (s): not_present' in out.notes
