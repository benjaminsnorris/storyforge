import copy
import os
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


def _scene_dir(tmp_path, text='old prose'):
    (tmp_path / 'scenes').mkdir()
    (tmp_path / 'scenes' / 's.md').write_text(text)
    return str(tmp_path)


def test_a_redraft_is_gated_and_the_gates_prose_judged(monkeypatch, tmp_path):
    from storyforge import gate
    project = _scene_dir(tmp_path)
    monkeypatch.setattr('storyforge.common.select_model', lambda t: 'm')
    monkeypatch.setattr('storyforge.common.build_shared_context', lambda p, model='': [])
    monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda *a, **k: 'prompt')
    monkeypatch.setattr('storyforge.api.invoke', lambda *a, **k: {
        'content': [{'type': 'text', 'text': 'Drafted prose.'}]})
    seen, befores = [], []

    def gate_and_fix(p, sid, *, command, prose, log_dir, before=None):
        seen.append((sid, command, prose))
        befores.append(before)
        return gate.GatedScene('Fixed prose.', _gate_result(True), _gate_result(False),
                               fixed=True)
    monkeypatch.setattr(gate, 'gate_and_fix', gate_and_fix)
    assert e8.redraft(project, 's') == 'Fixed prose.'
    assert [(s, c, p.strip()) for s, c, p in seen] == [('s', 'redraft', 'Drafted prose.')]
    # the book before the redraft, as revise takes it (#480's review)
    assert [b.scenes['s'] for b in befores] == ['old prose']
    assert gate.pending(project) == {}   # it passed: nothing listed


def _gate_result(passed):
    from storyforge import gate
    from storyforge.checker import CheckResult, Finding
    bad = Finding('contradiction', 'TIM', 'x', 'y', 'z', '', 'why')
    r = gate.GateResult('s', check=CheckResult('s', findings=[] if passed else [bad]))
    r.committed = passed
    return r


class TestGateAsRevise:
    """E8's gated replays list what the gate didn't pass, as write and
    revise do, so the suite can tell it from what the gate passed (PR #475's
    review: `reintroduced_unflagged` was blind to two of three families)."""

    def test_a_scene_the_gate_does_not_pass_is_listed(self, monkeypatch, tmp_path):
        from storyforge import gate
        project = _scene_dir(tmp_path)
        monkeypatch.setattr(gate, 'gate_and_fix', lambda p, sid, **k: gate.GatedScene(
            'Fixed.', _gate_result(False), _gate_result(False), fixed=True))
        assert e8.gate_as_revise(project, 's', 'revise', 'Prose.') == 'Fixed.'
        assert gate.pending(project)['s']['command'] == 'revise'


    def test_a_gate_that_cannot_finish_keeps_the_prose_listed(self, monkeypatch, tmp_path):
        from storyforge import gate

        def fail(*a, **k):
            raise gate.GateError('extraction failed')
        project = _scene_dir(tmp_path)
        monkeypatch.setattr(gate, 'gate_and_fix', fail)
        assert e8.gate_as_revise(project, 's', 'redraft', 'Prose.') == 'Prose.'
        assert 'extraction failed' in gate.pending(project)['s']['reason']

    def test_a_bug_in_the_gate_errors_the_suite(self, monkeypatch, tmp_path):
        from storyforge import gate

        def bug(*a, **k):
            raise KeyError('id')
        monkeypatch.setattr(gate, 'gate_and_fix', bug)
        with pytest.raises(KeyError):
            e8.gate_as_revise(_scene_dir(tmp_path), 's', 'revise', 'Prose.')


def test_every_excluded_case_is_a_real_case():
    """The ceiling is calibrated with these exclusions: a renamed or
    relabelled case would silently stop being excluded."""
    from e1 import load_cases
    ids = {c['id'] for c in load_cases()}
    assert set(e8.EXCLUDED_CASES) <= ids, set(e8.EXCLUDED_CASES) - ids


def test_cases_whose_pre_pass_book_carries_the_error_are_excluded():
    """#614: governor-016, thornwall-026 and thornwall-030 write what the
    pre-pass book already says; they are excluded with why, never replayed."""
    for case_id in ('governor-016', 'thornwall-026', 'thornwall-030'):
        assert case_id in e8.EXCLUDED_CASES
        assert 'pre-pass' in e8.EXCLUDED_CASES[case_id]
        with pytest.raises(LookupError, match='pre-pass'):
            e8.prepare({'id': case_id, 'repo': 'nowhere'}, '/nowhere')


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
    (repo / 'working' / 'plans').mkdir(parents=True)
    (repo / 'working' / 'plans' / 'revision-plan.yaml').write_text('passes: []\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'yaml'], check=True)
    (repo / 'scenes' / 's09-ledger.md').write_text('Seven.\n')
    subprocess.run(git + ['commit', '-qam', 'pass'], check=True)
    sha = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    case['introduced_by']['commit'] = sha
    monkeypatch.setattr(e8, 'ID_MAPS_DIR', str(maps))
    with pytest.raises(LookupError, match='refuses YAML plans'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_a_data_case_is_judged_on_what_the_pass_wrote():
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'upstream-brief-fixes', 'commit': 'a'})
    prompt = e8.judge_prompt(case, 'shell-breaks-open|Director Tessamine')
    assert '<written>\nshell-breaks-open|Director Tessamine\n</written>' in prompt
    assert '<scene>' not in prompt
    # the prose judge prompt is unchanged, so recorded verdicts still replay
    assert '<scene>' in e8.judge_prompt(_tool_case(), 'x')


def _data_book(tmp_path, *, briefs=True):
    """A book whose introducing commit changes only reference data."""
    repo = tmp_path / 'corpus' / 'book'
    (repo / 'scenes').mkdir(parents=True)
    (repo / 'reference').mkdir()
    git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'scenes' / 'road.md').write_text('Director Corvin.\n')
    (repo / 'reference' / 'scenes.csv').write_text('id|seq\nroad|1\nshell|2\n')
    if briefs:
        (repo / 'reference' / 'scene-briefs.csv').write_text('id|goal\nshell|x\n')
    (repo / 'reference' / 'visual-state.csv').write_text('entity|scene\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'before'], check=True)
    (repo / 'reference' / 'visual-state.csv').write_text('entity|scene\nlamp|road\n')
    subprocess.run(git + ['commit', '-qam', 'data pass'], check=True)
    sha = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    return tmp_path / 'corpus', sha


@pytest.mark.parametrize('pass_name, contradicted, scene', [
    ('upstream-brief-fixes', [{'scene': 'road', 'path': 'scenes/road.md'},
                              {'scene': 'shell', 'path': 'reference/scene-briefs.csv'}], 'shell'),
    ('illustrate --state', [{'scene': 'road', 'path': 'reference/visual-state.csv'}], 'road'),
])
def test_a_data_case_prepares_though_its_commit_changed_no_scene(tmp_path, pass_name, contradicted, scene):
    root, sha = _data_book(tmp_path)
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': pass_name, 'commit': sha},
                      contradicted=[{**CASE['contradicted'][0], **s} for s in contradicted])
    assert e8.prepare(case, str(tmp_path / 'work'), str(root))[1] == scene


@pytest.mark.parametrize('pass_name, needs', [
    ('illustrate --state', False), ('upstream-brief-fixes', True),
    ('hone (registries/physical-states)', True),
])
def test_only_the_families_that_read_briefs_need_them(tmp_path, pass_name, needs):
    root, sha = _data_book(tmp_path, briefs=False)
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': pass_name, 'commit': sha},
                      contradicted=[{**CASE['contradicted'][0], 'scene': 'shell',
                                     'path': 'reference/scene-briefs.csv'}])
    if needs:
        with pytest.raises(LookupError, match='no scene-briefs.csv'):
            e8.prepare(case, str(tmp_path / 'work'), str(root))
    else:
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_a_brief_fix_for_a_scene_with_no_brief_row_is_unreplayable(tmp_path):
    root, sha = _data_book(tmp_path)
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'upstream-brief-fixes', 'commit': sha},
                      contradicted=[{**CASE['contradicted'][0], 'scene': 'nowhere',
                                     'path': 'reference/scene-briefs.csv'}])
    with pytest.raises(LookupError, match='no row for nowhere'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_an_excluded_case_is_unreplayable_with_its_reason(tmp_path):
    with pytest.raises(LookupError, match='stale'):
        e8.prepare(_tool_case(id='lantern-folk-032'), str(tmp_path))


@pytest.mark.parametrize('status, words, expected', [
    ('', '1188', 'drafted'), ('', '0', 'mapped'), ('outlined', '', 'mapped'), ('polished', '0', 'polished'),
])
def test_migration_keeps_four_statuses_and_recomputes_the_rest(tmp_path, status, words, expected):
    (tmp_path / 'reference').mkdir()
    (tmp_path / 'reference' / 'scene-metadata.csv').write_text(
        f'id|status|word_count\ns|{status}|{words}\n')
    assert e8.migrate_scene_metadata(str(tmp_path))
    with open(tmp_path / 'reference' / 'scenes.csv') as f:
        assert f.read().splitlines()[1].split('|')[9] == expected


def test_migration_without_scene_metadata_does_nothing(tmp_path):
    (tmp_path / 'reference').mkdir()
    assert not e8.migrate_scene_metadata(str(tmp_path))
    assert not (tmp_path / 'reference' / 'scenes.csv').exists()


def test_old_ids_without_an_id_map_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(e8, 'ID_MAPS_DIR', str(tmp_path))
    assert e8.old_ids('book', 'slug') == []
    (tmp_path / 'book.csv').write_text('old_path|slug\nscenes/lonely.md\nscenes/s1.md|slug\n')
    assert e8.old_ids('book', 'slug') == ['s1']


def test_an_ungated_redraft_is_the_draft_alone(monkeypatch, tmp_path):
    from storyforge import gate
    monkeypatch.setattr(gate, 'gate_and_fix', lambda *a, **k: pytest.fail('gated'))
    monkeypatch.setattr('storyforge.common.select_model', lambda t: 'm')
    monkeypatch.setattr('storyforge.common.build_shared_context', lambda p, model='': [])
    monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda *a, **k: 'prompt')
    monkeypatch.setattr('storyforge.api.invoke', lambda *a, **k: {
        'content': [{'type': 'text', 'text': 'Drafted prose.'}]})
    assert e8.redraft(_scene_dir(tmp_path), 's', gated=False).strip() == 'Drafted prose.'


