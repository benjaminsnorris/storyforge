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


def _scene_dir(tmp_path, text='old prose'):
    (tmp_path / 'scenes').mkdir()
    (tmp_path / 'scenes' / 's.md').write_text(text)
    return str(tmp_path)


def test_a_naturalness_redraft_that_halts_is_pass_halted(monkeypatch, tmp_path):
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, '_fix_upstream_briefs', lambda p, ids: (['s'], {}))

    def halt(p, ids):
        raise cmd_revise.RedraftError('1 scene(s) not re-drafted: s (cut off)')
    monkeypatch.setattr(cmd_revise, '_redraft_scenes', halt)
    with pytest.raises(e8.PassHalted, match='cut off'):
        e8.naturalness_upstream(_scene_dir(tmp_path), 's')


def test_a_naturalness_redraft_the_gate_failed_is_judged(monkeypatch, tmp_path):
    """revise keeps a redraft the gate didn't pass, so E8 judges it."""
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, '_fix_upstream_briefs', lambda p, ids: (['s'], {}))
    project = _scene_dir(tmp_path)

    def gate_failed(p, ids):
        (tmp_path / 'scenes' / 's.md').write_text('new prose')
        raise cmd_revise.RedraftError('s (redrafted, but the gate did not pass it')
    monkeypatch.setattr(cmd_revise, '_redraft_scenes', gate_failed)
    assert e8.naturalness_upstream(project, 's') == 'new prose'


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
        assert e8.read_gate_counts(project) == {'new': 1, 'plan_conflicts': 0,
                                                'extraction': 0, 'inherited': 0}

    def test_gate_counts_sort_what_the_gate_found(self):
        from storyforge import gate
        from storyforge.checker import Finding
        r = _gate_result(False)
        conflict = Finding('contradiction', 'TRT', 'q', 'y', 'z', '', 'why')
        old = Finding('contradiction', 'TIM', 'o', 'y', 'z', '', 'why')
        r.check.findings += [conflict, old]
        r.plan_conflicts, r.inherited = [conflict], [old]
        r.problems = {'quote': ['s: x'], 'rejected': ['s: restates y']}
        counts = e8.gate_counts(r)
        assert counts == {'new': 2, 'plan_conflicts': 1, 'extraction': 1, 'inherited': 1}
        assert counts['new'] == len(gate.problems_to_fix(r))   # what the fix is sent
        assert tuple(counts) == e8.GATE_COUNT_KEYS

    def test_no_counts_when_the_gate_could_not_finish(self, monkeypatch, tmp_path):
        from storyforge import gate

        def fail(*a, **k):
            raise gate.GateError('extraction failed')
        project = _scene_dir(tmp_path)
        monkeypatch.setattr(gate, 'gate_and_fix', fail)
        e8.gate_as_revise(project, 's', 'redraft', 'Prose.')
        assert e8.read_gate_counts(project) is None

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

    def _revision_pass(self, monkeypatch, tmp_path, coaching):
        from storyforge import gate
        project = _scene_dir(tmp_path)
        monkeypatch.setattr('storyforge.common.select_revision_model', lambda *a: 'm')
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        monkeypatch.setattr('storyforge.common.get_coaching_level', lambda p: coaching)
        monkeypatch.setattr('storyforge.revision.build_revision_prompt', lambda *a, **k: 'p')
        monkeypatch.setattr('storyforge.api.invoke', lambda *a, **k: {
            'content': [{'type': 'text', 'text': 'x'}]})

        def write(text, scenes_dir):
            with open(os.path.join(scenes_dir, 's.md'), 'w') as f:
                f.write('Revised prose.')
        monkeypatch.setattr('storyforge.parsing.extract_scenes_from_response', write)
        seen = []
        monkeypatch.setattr(gate, 'gate_and_fix', lambda p, sid, *, command, prose, **k: (
            seen.append(command) or seen.append(k.get('before')) or gate.GatedScene('Fixed.', _gate_result(True),
                                                    _gate_result(True))))
        return e8.revision_pass(project, 's', {'name': 'polish'}), seen

    def test_a_revision_pass_is_gated_at_full(self, monkeypatch, tmp_path):
        out, seen = self._revision_pass(monkeypatch, tmp_path, 'full')
        assert out == 'Fixed.' and seen[0] == 'revise'
        assert seen[1].scenes['s'] == 'old prose'   # the book before the pass wrote

    def test_a_revision_pass_is_not_gated_below_full(self, monkeypatch, tmp_path):
        out, seen = self._revision_pass(monkeypatch, tmp_path, 'coach')
        assert out == 'Revised prose.' and seen == []


def test_reintroductions_the_gate_listed_are_flagged_not_unflagged(monkeypatch, tmp_path):
    import importlib
    from storyforge import gate
    suite = importlib.import_module('suites.e8_revision_safety')
    data = _tool_case(id='d-1', introduced_by={'kind': 'tool', 'pass': 'illustrate --state',
                                               'commit': 'a'})
    cases = [_tool_case(id='p-1'), _tool_case(id='p-2'), data]
    monkeypatch.setattr(suite, 'select', lambda c, h: e8.Selection(cases=cases))
    dirs = {}

    def prepare(case, work_dir):
        d = tmp_path / case['id']
        d.mkdir()
        dirs[case['id']] = str(d)
        return str(d), 's'

    def replay(case, project, sid):
        if case['id'] in ('p-1', 'd-1'):   # a data case is never flagged
            gate.mark_pending(project, sid, 'revise', 'the gate did not pass it')
        return 'prose'
    monkeypatch.setattr(suite, 'prepare', prepare)
    monkeypatch.setattr(suite, 'replay', replay)
    monkeypatch.setattr(suite, 'judge', lambda c, t: {'verdict': 'reintroduced', 'evidence': ''})
    monkeypatch.setattr(suite, 'read_gate_counts', lambda p: None)
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    assert out.metrics['reintroduced'] == 3
    assert out.metrics['reintroduced_unflagged'] == 2   # p-2 and the data case
    assert any(n.startswith('p-1 (s): reintroduced (the gate did not pass it: listed pending)')
               for n in out.notes)
    gates = {g.name: g for g in out.gates}
    assert 'reintroduced' not in gates    # reported, not gated (2026-11-01)
    assert (gates['reintroduced_unflagged'].op, gates['reintroduced_unflagged'].threshold) == (
        '<=', suite.MAX_UNFLAGGED)
    assert gates['reintroduced_unflagged'].passed     # 2 is within the gate


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
    assert 'b-1 (s): not_present (wrote nothing; not judged)' in out.notes



def test_a_prose_replay_that_returns_nothing_errors(monkeypatch, tmp_path):
    import importlib
    suite = importlib.import_module('suites.e8_revision_safety')
    monkeypatch.setattr(suite, 'select', lambda cases, holdout: e8.Selection(cases=[_tool_case(id='b-1')]))
    monkeypatch.setattr(suite, 'prepare', lambda c, w: (str(tmp_path), 's'))
    monkeypatch.setattr(suite, 'replay', lambda c, p, s: '  ')
    with pytest.raises(RuntimeError, match='no prose'):
        suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())


def test_errors_per_10k_words_counts_prose_hits_over_prose_words(monkeypatch, tmp_path):
    import importlib
    suite = importlib.import_module('suites.e8_revision_safety')
    prose = _tool_case(id='p-1')
    data = _tool_case(id='d-1', introduced_by={'kind': 'tool', 'pass': 'illustrate --state', 'commit': 'a'})
    monkeypatch.setattr(suite, 'select', lambda cases, holdout: e8.Selection(cases=[prose, data]))
    monkeypatch.setattr(suite, 'prepare', lambda c, w: (str(tmp_path), 's'))
    monkeypatch.setattr(suite, 'replay', lambda c, p, s: ' '.join(['word'] * 1000))
    monkeypatch.setattr(suite, 'judge', lambda c, t: {'verdict': 'reintroduced' if c['id'] == 'd-1'
                                                      else 'consistent', 'evidence': ''})
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    assert out.metrics['reintroduced'] == 1
    assert out.metrics['errors_per_10k_words'] == 0.0  # the data hit is not a prose error
    excluded = [i for i, n in enumerate(out.notes) if n.startswith('excluded')]
    assert excluded == list(range(len(excluded)))  # exclusions come first


def test_written_csv_rows_by_id_ignore_added_empty_columns():
    before = {'reference/scene-briefs.csv': 'id|goal\na|keep\nb|old\nc|gone\n'}
    after = {'reference/scene-briefs.csv': 'id|goal|panels\na|keep|\nb|new|\n'}
    assert e8.written(before, after) == ('reference/scene-briefs.csv:\nid|goal|panels\nb|new|\n'
                                         '(removed) c|gone')


def test_written_reports_removed_lines_a_changed_first_line_and_deleted_files():
    before = {'p/LF-13.md': '# Old title\nkeep\ndrop\n', 'p/LF-02.md': 'x\n'}
    after = {'p/LF-13.md': '# New title\nkeep\n'}
    assert e8.written(before, after) == ('p/LF-02.md (deleted)\n\np/LF-13.md:\n# New title\n'
                                         '(first line was) # Old title\n(removed) drop')


def test_snapshot_walks_directories_with_relative_paths(tmp_path):
    (tmp_path / 'reference' / 'illustration-prompts' / 'sub').mkdir(parents=True)
    (tmp_path / 'reference' / 'illustration-prompts' / 'sub' / 'LF-1.md').write_text('a')
    (tmp_path / 'reference' / 'x.csv').write_text('id\n')
    assert e8._snapshot(str(tmp_path), 'reference/illustration-prompts', 'reference/x.csv') == {
        'reference/illustration-prompts/sub/LF-1.md': 'a', 'reference/x.csv': 'id\n'}


def test_brief_fix_returns_only_the_rewritten_row(monkeypatch, tmp_path):
    from storyforge import cmd_revise
    (tmp_path / 'reference').mkdir()
    briefs = tmp_path / 'reference' / 'scene-briefs.csv'
    briefs.write_text('id|goal\na|keep\nb|old\n')

    def fix(project, ids):
        briefs.write_text('id|goal|panels\na|keep|\nb|Director Tessamine|\n')
        return ids, {}
    monkeypatch.setattr(cmd_revise, '_fix_upstream_briefs', fix)
    assert e8.brief_fix(str(tmp_path), 'b') == ('reference/scene-briefs.csv:\nid|goal|panels\n'
                                                'b|Director Tessamine|')


def test_hone_reconciles_physical_states_and_reports_registry_and_brief_changes(monkeypatch, tmp_path):
    from storyforge import common, hone
    ref = tmp_path / 'reference'
    ref.mkdir()
    (ref / 'commitments.csv').write_text('id|character\nscar-kael|Kael\n')
    (ref / 'scene-briefs.csv').write_text('id|physical_state_in\ns1|\n')
    calls = []

    def reconcile(domain, ref_dir, model, log_dir):
        calls.append((domain, ref_dir, model))
        (ref / 'commitments.csv').write_text('id|character\nscar-kael|Kael\nburns-tessa|Tessa\n')
        (ref / 'scene-briefs.csv').write_text('id|physical_state_in\ns1|burns-tessa\n')
    monkeypatch.setattr(hone, 'reconcile_domain', reconcile)
    monkeypatch.setattr(common, 'select_model', lambda task: f'model-for-{task}')
    out = e8.hone_physical_states(str(tmp_path))
    assert calls == [('physical-states', str(ref), 'model-for-synthesis')]
    assert out == ('reference/commitments.csv:\nid|character\nburns-tessa|Tessa\n\n'
                   'reference/scene-briefs.csv:\nid|physical_state_in\ns1|burns-tessa')


def test_a_cut_off_hone_batch_halts(monkeypatch, tmp_path):
    from storyforge import hone
    (tmp_path / 'reference').mkdir()
    monkeypatch.setattr(hone, '_invoke_batch', lambda *a: None)

    def reconcile(domain, ref_dir, model, log_dir):
        hone._invoke_batch('p', model, 'log', 'hone registries/physical-states (batch 1 of 1)')
    monkeypatch.setattr(hone, 'reconcile_domain', reconcile)
    with pytest.raises(e8.PassHalted, match='1 hone batch'):
        e8.hone_physical_states(str(tmp_path))


@pytest.mark.parametrize('family_name, spans, expected_ids', [
    ('illustrate --prompts', [{'path': 'reference/illustration-prompts/LF-13.md'}], {'LF-13'}),
    ('illustrate --prompts', [{'path': 'reference/visual-state.csv'}], None),
])
def test_illustrate_prompts_runs_the_quoted_prompt_ids(monkeypatch, tmp_path, family_name, spans, expected_ids):
    from storyforge import cmd_illustrate
    seen = []
    monkeypatch.setattr(cmd_illustrate, 'run_prompts',
                        lambda p, coaching, ids, dry_run: seen.append((coaching, ids, dry_run)) or 0)
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': family_name, 'commit': 'a'},
                      contradicted=[{**CASE['contradicted'][0], **s} for s in spans])
    assert e8.replay(case, str(tmp_path), 's') == ''
    assert seen == [('full', expected_ids, False)]


def test_illustrate_runs_keyless_under_a_cassette_and_errors_on_failure(monkeypatch, tmp_path):
    from storyforge import cmd_illustrate
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setenv('STORYFORGE_CASSETTE', str(tmp_path))
    keys = []
    monkeypatch.setattr(cmd_illustrate, 'run_state',
                        lambda p, coaching, dry_run: keys.append(os.environ.get('ANTHROPIC_API_KEY')) or 0)
    assert e8.illustrate(str(tmp_path), 'illustrate-state') == ''
    assert keys == ['cassette-replay'] and 'ANTHROPIC_API_KEY' not in os.environ
    monkeypatch.setattr(cmd_illustrate, 'run_state', lambda p, coaching, dry_run: 1)
    with pytest.raises(RuntimeError, match='exited 1'):
        e8.illustrate(str(tmp_path), 'illustrate-state')


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


@pytest.mark.parametrize('command, reason, listing', [
    ('revise', 'the gate did not pass it', 'failed'),
    ('redraft', '2 problem(s) after one fix: TIM contradiction ...', 'failed'),
    ('redraft', '2 problem(s) after 2 fixes: TIM contradiction ...', 'failed'),
    ('revise', 'the gate could not finish: the check was cut off', 'unfinished'),
    ('revise', 'the gate failed unexpectedly (OSError: disk)', 'unfinished'),
    ('recheck', 'changed facts it depends on', 'other'),
    ('revise', 'revised by pass polish but not gated', 'other'),
])
def test_only_a_gate_that_checked_and_failed_flags_a_scene(tmp_path, command, reason, listing):
    """#478's review: a gate that couldn't finish, or a re-check listing,
    must not count a reintroduction as flagged."""
    import importlib
    from storyforge import gate
    suite = importlib.import_module('suites.e8_revision_safety')
    assert suite._gate_listing(str(tmp_path), 's') == ''
    gate.mark_pending(str(tmp_path), 's', command, reason)
    assert suite._gate_listing(str(tmp_path), 's') == listing


def test_a_gate_that_could_not_finish_fails_e8(monkeypatch, tmp_path):
    import importlib
    from storyforge import gate
    suite = importlib.import_module('suites.e8_revision_safety')
    monkeypatch.setattr(suite, 'select', lambda c, h: e8.Selection(cases=[_tool_case(id='p-1')]))
    monkeypatch.setattr(suite, 'prepare', lambda c, w: (str(tmp_path), 's'))

    def replay(case, project, sid):
        gate.mark_pending(project, sid, 'revise', 'the gate could not finish: boom')
        return 'prose'
    monkeypatch.setattr(suite, 'replay', replay)
    monkeypatch.setattr(suite, 'judge', lambda c, t: {'verdict': 'reintroduced', 'evidence': ''})
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    gates = {g.name: g for g in out.gates}
    assert out.metrics['reintroduced_unflagged'] == 1 and out.metrics['gate_unfinished'] == 1
    assert not gates['gate_unfinished'].passed and gates['reintroduced_unflagged'].passed
    assert 'p-1 (s): reintroduced (the gate could not finish: counted unflagged)' in out.notes[0]


def test_clean_replays_the_gate_failed_are_counted_with_what_it_found(monkeypatch, tmp_path):
    """2026-11-01: #478's 14 "false alarms" were mostly real errors the
    replay made; the suite reports what the gate found instead of a bare
    count."""
    import importlib
    from storyforge import gate
    suite = importlib.import_module('suites.e8_revision_safety')
    cases = [_tool_case(id='p-1'), _tool_case(id='p-2')]
    monkeypatch.setattr(suite, 'select', lambda c, h: e8.Selection(cases=cases))

    def prepare(case, work_dir):
        d = tmp_path / case['id']
        d.mkdir()
        return str(d), 's'

    def replay(case, project, sid):
        if case['id'] == 'p-1':
            gate.mark_pending(project, sid, 'revise', 'the gate did not pass it')
        return 'prose'
    counts = {'p-1': {'new': 2, 'plan_conflicts': 1, 'extraction': 0, 'inherited': 1},
              'p-2': {'new': 0, 'plan_conflicts': 0, 'extraction': 0, 'inherited': 3}}
    monkeypatch.setattr(suite, 'prepare', prepare)
    monkeypatch.setattr(suite, 'replay', replay)
    monkeypatch.setattr(suite, 'read_gate_counts', lambda p: counts[os.path.basename(p)])
    monkeypatch.setattr(suite, 'judge', lambda c, t: {'verdict': 'not_present', 'evidence': ''})
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    assert out.metrics['clean_gate_failed'] == 1
    assert (out.metrics['gate_new'], out.metrics['gate_plan_conflicts'],
            out.metrics['gate_inherited']) == (2, 1, 4)
    assert any(n.startswith('p-1 (s): not_present (the gate did not pass it: listed pending) '
                            '[gate: 2 new, 1 plan conflict, 1 already in the book]')
               for n in out.notes)
    assert any(n == 'p-2 (s): not_present [gate: 3 already in the book]' for n in out.notes)
    assert out.metrics['gate_counts_missing'] == 0


def test_a_prose_replay_with_no_gate_counts_says_so(monkeypatch, tmp_path):
    """#480's review (SF-11): "the gate found nothing" and "not collected"
    must read differently."""
    import importlib
    suite = importlib.import_module('suites.e8_revision_safety')
    monkeypatch.setattr(suite, 'select', lambda c, h: e8.Selection(cases=[_tool_case(id='p-1')]))
    monkeypatch.setattr(suite, 'prepare', lambda c, w: (str(tmp_path), 's'))
    monkeypatch.setattr(suite, 'replay', lambda c, p, s: 'prose')
    monkeypatch.setattr(suite, 'read_gate_counts', lambda p: None)
    monkeypatch.setattr(suite, 'judge', lambda c, t: {'verdict': 'not_present', 'evidence': ''})
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    assert out.metrics['gate_counts_missing'] == 1
    assert 'p-1 (s): not_present [gate counts not collected]' in out.notes


def test_an_earlier_runs_counts_are_never_read(monkeypatch, tmp_path):
    """#480's review: a gate that can't finish leaves no counts, not stale ones."""
    from storyforge import gate
    project = _scene_dir(tmp_path)
    os.makedirs(os.path.join(project, 'working'))
    with open(os.path.join(project, e8.GATE_COUNTS), 'w') as f:
        f.write('{"new": 9}')

    def fail(*a, **k):
        raise gate.GateError('extraction failed')
    monkeypatch.setattr(gate, 'gate_and_fix', fail)
    e8.gate_as_revise(project, 's', 'redraft', 'Prose.')
    assert e8.read_gate_counts(project) is None
