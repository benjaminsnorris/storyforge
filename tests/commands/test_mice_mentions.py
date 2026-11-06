"""#272: MICE mentions (bare thread names) must mean the same thing to every
reader of mice_threads.

`elaborate --stage mice-fill` writes a bare name into scenes inside a dormant
stretch. Validate (schema._check_mice), dormancy (hone.detect_mice_dormancy),
structural validation and MICE health must agree on what that entry is: a
mention of a registered thread. A bare name the registry lacks is a problem
validate names and dormancy does not count.
"""

import os
import re

import pytest

from storyforge.cmd_elaborate import _run_mice_fill
from storyforge.elaborate import _read_csv_as_map, validate_structure
from storyforge import mice
from storyforge.hone import detect_mice_dormancy
from storyforge.schema import _check_mice, validate_schema

N_SCENES = 30

REGISTRY = (
    'id|name|type|aliases\n'
    'leo-guardian|Leo the Guardian|character|the guardian\n'
    # An older registry keeps the type in the id
    'inquiry:lamp-crisis|Lamp crisis|inquiry|\n'
)


def _write_project(ref, mice: dict[int, str]):
    with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
        f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|'
                'type|status|word_count|target_words\n')
        for i in range(1, N_SCENES + 1):
            f.write(f's{i:02d}|{i}|Scene {i}|1|zara|loc|1|morning|1hr|action|'
                    f'briefed|1000|1500\n')
    with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
        f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
                'turning_point|characters|on_stage|mice_threads\n')
        for i in range(1, N_SCENES + 1):
            f.write(f's{i:02d}|func|action|flat|truth|+/-|revelation|zara|zara|'
                    f'{mice.get(i, "")}\n')
    with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
        f.write(REGISTRY)


def _counted(value, reg):
    """What dormancy counts: the entries validate accepts."""
    return [r for r in mice.resolve(value, reg) if r.valid]


def _mice_errors(ref, project_dir):
    return [e for e in validate_schema(ref, project_dir)['errors']
            if e.get('column') == 'mice_threads']


@pytest.fixture
def long_threads(project_dir):
    """Two threads open in s01 and close in s20 with nothing between (a
    19-scene gap each), and an echo of one after its close, in s30."""
    ref = os.path.join(project_dir, 'reference')
    _write_project(ref, {
        1: '+leo-guardian;+inquiry:lamp-crisis',
        20: '-lamp-crisis;-character:leo-guardian',
        30: 'The Guardian',
    })
    return project_dir, ref


def _mention_middle_scene(prompt: str) -> str:
    """Stand-in model reply: mention the middle scene of the gap."""
    gap = re.findall(r'- \*\*(s\d+)\*\*', prompt)
    return f'MENTION: {gap[len(gap) // 2]}\n' if gap else 'NONE\n'


class TestMiceFillOutputValidates:
    def test_mice_fill_mentions_pass_validate_and_clear_dormancy(
            self, long_threads, mock_api, mock_git, mock_costs, monkeypatch):
        project_dir, ref = long_threads
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        mock_api.set_response_fn(_mention_middle_scene)

        assert _mice_errors(ref, project_dir) == []
        before = detect_mice_dormancy(ref).gaps
        assert {g['thread_id'] for g in before} == {'leo-guardian', 'inquiry:lamp-crisis'}

        _run_mice_fill(project_dir, ref, dry_run=False)

        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        written = {sid: row['mice_threads'] for sid, row in intent.items()
                   if row['mice_threads'] and sid not in ('s01', 's20', 's30')}
        # mice-fill wrote bare names (no +/-), the registry's bare name for
        # the type-prefixed id
        assert written
        for value in written.values():
            for entry in value.split(';'):
                assert entry in ('leo-guardian', 'lamp-crisis'), entry
        # ...only inside the open..close span: the echo in s30 opens no gap
        assert all(int(sid[1:]) < 20 for sid in written)

        assert _mice_errors(ref, project_dir) == []
        assert detect_mice_dormancy(ref).gaps == []

    def test_mentions_are_no_ops_for_structure(self, long_threads):
        _project_dir, ref = long_threads
        intent = os.path.join(ref, 'scene-intent.csv')
        with open(intent) as f:
            content = f.read()
        with open(intent, 'w') as f:
            f.write(content.replace('s10|func|action|flat|truth|+/-|revelation|zara|zara|',
                                    's10|func|action|flat|truth|+/-|revelation|zara|zara|'
                                    'leo-guardian;lamp-crisis'))
        threads = [c for c in validate_structure(ref)['checks'] if c['category'] == 'threads']
        failing = [c['message'] for c in threads if not c['passed']]
        # `+leo-guardian` and `-character:leo-guardian`, `+inquiry:lamp-crisis`
        # and `-lamp-crisis` are one thread each, opened and closed once; the
        # mentions in s10 and s30 add no operation
        assert failing == []
        assert any(c['check'] == 'mice-ops' and c['passed'] for c in threads)


class TestUnknownBareName:
    def test_rejected_with_reason(self, long_threads):
        project_dir, ref = long_threads
        _write_project(ref, {1: '+leo-guardian', 10: 'no-such-thread', 20: '-leo-guardian'})
        errors = _mice_errors(ref, project_dir)
        assert len(errors) == 1 and errors[0]['row'] == 's10'
        assert errors[0]['problems'] == [
            {'entry': 'no-such-thread',
             'reason': 'thread name "no-such-thread" not in mice-threads.csv'}]

    def test_not_counted_as_a_mention(self, long_threads):
        _project_dir, ref = long_threads
        _write_project(ref, {1: '+leo-guardian', 10: 'no-such-thread', 20: '-leo-guardian'})
        gaps = detect_mice_dormancy(ref).gaps
        assert [(g['thread_id'], g['gap_size']) for g in gaps] == [('leo-guardian', 19)]


class TestDormancyAndValidateAgree:
    """An entry dormancy counts is exactly one validate accepts."""

    ENTRIES = [
        'leo-guardian', '+leo-guardian', '-leo-guardian', 'character:leo-guardian',
        'Leo-Guardian', 'The Guardian', 'leo the guardian', 'lamp-crisis',
        'inquiry:lamp-crisis', '-lamp-crisis',
        # rejected
        'no-such-thread', '+', '-', 'event:leo-guardian', 'bogus:leo-guardian',
        ':leo-guardian', 'inquiry:', 'leo-guardian[advance: lamp]',
    ]

    def test_each_entry(self, long_threads):
        _project_dir, ref = long_threads
        reg = mice.registry_for(ref)
        for entry in self.ENTRIES:
            valid = not _check_mice(entry, reg)
            counted = bool(_counted(entry, reg))
            assert valid == counted, entry

    def test_alias_and_case_mentions_break_dormancy(self, long_threads):
        project_dir, ref = long_threads
        _write_project(ref, {1: '+leo-guardian', 10: 'The Guardian',
                             20: '-leo-guardian'})
        assert _mice_errors(ref, project_dir) == []
        assert all(g['gap_size'] < 19 for g in detect_mice_dormancy(ref).gaps)

    def test_mice_health_counts_the_same_mentions(self, long_threads):
        from storyforge.structural import score_mice_health
        _project_dir, ref = long_threads
        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))

        def dormant(mice):
            _write_project(ref, mice)
            intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
            return [f['message'] for f in score_mice_health(scenes, intent, ref)['findings']
                    if 'dormant' in f['message']]

        assert dormant({1: '+leo-guardian', 20: '-leo-guardian'}) == [
            "Thread 'leo-guardian' dormant for 19 scenes"]
        # A mention by alias, and a typed close, are the same thread
        assert dormant({1: '+leo-guardian', 10: 'The Guardian',
                        20: '-character:leo-guardian'}) == []


class TestMentionsOutsideTheSpan:
    """Before the open is foreshadowing, after the close an echo: valid,
    not reported, and not dormancy (mice-fill must not pad them)."""

    MICE = {1: 'leo-guardian', 15: '+leo-guardian', 16: '-leo-guardian', 30: 'leo-guardian'}

    def test_valid_and_not_reported(self, long_threads):
        project_dir, ref = long_threads
        _write_project(ref, self.MICE)
        assert _mice_errors(ref, project_dir) == []
        threads = [c for c in validate_structure(ref)['checks']
                   if c['category'] == 'threads' and not c['passed']]
        assert threads == []

    def test_not_dormancy(self, long_threads):
        from storyforge.structural import score_mice_health
        _project_dir, ref = long_threads
        _write_project(ref, self.MICE)
        assert detect_mice_dormancy(ref).gaps == []
        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert not [f for f in score_mice_health(scenes, intent, ref)['findings']
                    if 'dormant' in f['message']]

    def test_unopened_thread_spans_its_mentions(self, long_threads):
        # With no open or close the whole stretch is the span
        _project_dir, ref = long_threads
        _write_project(ref, {1: 'leo-guardian', 20: 'leo-guardian'})
        assert [g['gap_size'] for g in detect_mice_dormancy(ref).gaps] == [19]


class TestOtherReaders:
    def test_legacy_typed_registry_id_answers_to_its_bare_name(self, tmp_path):
        path = tmp_path / 'mice-threads.csv'
        path.write_text(REGISTRY)
        reg = mice.load_registry(str(path))
        assert reg.lookup['lamp-crisis'] == 'inquiry:lamp-crisis'
        assert reg.lookup['inquiry:lamp-crisis'] == 'inquiry:lamp-crisis'

    def test_extract_cleanup_sees_typed_and_bare_opens_as_one_thread(self, long_threads):
        from storyforge.extract import cleanup_mice_threads
        _project_dir, ref = long_threads
        _write_project(ref, {1: '+inquiry:lamp-crisis', 5: '+lamp-crisis', 20: '-lamp-crisis'})
        fixes = cleanup_mice_threads(ref)
        assert [(f['scene_id'], f['old_value']) for f in fixes] == [('s05', '+lamp-crisis')]
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert intent['s05']['mice_threads'] == 'lamp-crisis'

    def test_prior_prose_window_matches_typed_and_bare_entries(self):
        from storyforge.prompts import _threads
        assert _threads('+inquiry:who;-Lamp;guardian') == {'who', 'lamp', 'guardian'}
        assert _threads('who') & _threads('+inquiry:who')


# ============================================================================
# PR #609 review
# ============================================================================

COLLIDING = (
    'id|name|type|aliases\n'
    'inquiry:secret|The secret|inquiry|\n'
    'character:secret|Her secret|character|\n'
)


def _registry(text):
    lines = text.splitlines()
    header = lines[0].split('|')
    return mice.registry_from_rows([dict(zip(header, line.split('|'))) for line in lines[1:]])


class TestSourceBibleTypedThread:
    """T-1: the bible filed a typed thread's scenes under its bare name and
    looked them up by its full id, so `inquiry:lamp-crisis` showed none."""

    def test_typed_id_lists_its_scenes(self):
        from storyforge.source import build_source_bible
        tables = {
            'scenes.csv': (['id', 'seq', 'title'], [['s01', '1', 'A'], ['s02', '2', 'B']]),
            'scene-intent.csv': (['id', 'mice_threads'],
                                 [['s01', '+inquiry:lamp-crisis'], ['s02', '-lamp-crisis']]),
            'mice-threads.csv': (['id', 'name', 'type', 'aliases'],
                                 [['inquiry:lamp-crisis', 'Lamp crisis', 'inquiry', '']]),
        }
        bible = build_source_bible('src', tables)
        line = next(l for l in bible.splitlines() if '`inquiry:lamp-crisis`' in l)
        assert 'opens in `s01`, last in `s02` (2 scenes)' in line


class TestCleanupReopenKeys:
    """T-2/CR-2: an entry naming no thread was keyed by its raw text, so its
    close never cleared its open and a real re-open became a mention."""

    def _cleanup(self, ref, mice_by_scene):
        from storyforge.extract import cleanup_mice_threads
        _write_project(ref, mice_by_scene)
        fixes = cleanup_mice_threads(ref)
        return fixes, _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))

    def test_invalid_type_close_clears_its_open(self, long_threads):
        _project_dir, ref = long_threads
        fixes, intent = self._cleanup(ref, {1: '+myth:x', 2: '-myth:x', 3: '+myth:x'})
        assert fixes == []
        assert intent['s03']['mice_threads'] == '+myth:x'

    def test_prose_name_without_registry(self, long_threads):
        from storyforge.extract import cleanup_mice_threads
        _project_dir, ref = long_threads
        _write_project(ref, {1: '+Gatsby dream', 2: '-Gatsby dream', 3: '+Gatsby dream'})
        os.remove(os.path.join(ref, 'mice-threads.csv'))
        assert cleanup_mice_threads(ref) == []
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert intent['s03']['mice_threads'] == '+Gatsby dream'

    def test_a_true_reopen_is_still_a_mention(self, long_threads):
        _project_dir, ref = long_threads
        fixes, _intent = self._cleanup(ref, {1: '+myth:x', 3: '+myth:x'})
        assert [(f['scene_id'], f['old_value']) for f in fixes] == [('s03', '+myth:x')]

    def test_hone_lists_each_cleanup_fix(self, long_threads, monkeypatch):
        """SF-5: hone kept only a count of these."""
        from storyforge import hone
        _project_dir, ref = long_threads
        _write_project(ref, {1: '+leo-guardian', 5: '+leo-guardian', 20: '-leo-guardian'})
        logged = []
        monkeypatch.setattr(hone, 'log', logged.append)
        monkeypatch.setattr(hone, 'reconcile_mice_operations', lambda *a: (0, 0))
        hone.reconcile_domain('mice-threads', ref, 'model', str(ref))
        assert any('s05: "+leo-guardian" -> leo-guardian (already open: mention)' in m
                   for m in logged)


class TestRegistryCollisions:
    """SF-1/TD-3: a name two threads share was last-wins (names, aliases) or
    first-wins (the bare name of a typed id). No reader picks one now; the
    collision is a validate problem and a WARNING."""

    def test_shared_bare_name_is_not_in_the_lookup(self):
        reg = _registry(COLLIDING)
        assert 'secret' not in reg.lookup
        assert reg.ambiguous['secret'] == ['character:secret', 'inquiry:secret']
        assert reg.lookup['inquiry:secret'] == 'inquiry:secret'
        assert reg.lookup['character:secret'] == 'character:secret'
        assert any('"secret" names more than one thread' in f for f in reg.findings())

    def test_typed_entries_name_each_thread_without_a_false_mismatch(self):
        reg = _registry(COLLIDING)
        assert _check_mice('+character:secret;-inquiry:secret', reg) == []
        problems = _check_mice('secret', reg)
        assert problems and 'ambiguous' in problems[0]['reason']

    def test_shared_alias_and_name(self):
        reg = _registry('id|name|type|aliases\n'
                        'a|Alpha|inquiry|the case\n'
                        'b|Beta|event|the case;alpha\n')
        assert 'the case' not in reg.lookup and 'alpha' not in reg.lookup
        assert set(reg.ambiguous) == {'the case', 'alpha'}
        assert reg.lookup['inquiry:the case'] == 'a'

    def test_validate_reports_the_collision(self, long_threads):
        project_dir, ref = long_threads
        with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
            f.write(COLLIDING)
        errors = [e for e in validate_schema(ref, project_dir)['errors']
                  if e['constraint'] == 'mice-registry']
        assert len(errors) == 1 and '"secret"' in errors[0]['reason']

    def test_structure_and_cleanup_keep_the_two_threads_apart(self, long_threads):
        from storyforge.extract import cleanup_mice_threads
        _project_dir, ref = long_threads
        _write_project(ref, {1: '+inquiry:secret', 2: '+character:secret',
                             3: '-character:secret', 4: '-inquiry:secret'})
        with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
            f.write(COLLIDING)
        checks = validate_structure(ref)['checks']
        assert any(c['check'] == 'mice-ops' and c['passed'] for c in checks)
        assert any(c['check'] == 'mice-registry' for c in checks)
        assert cleanup_mice_threads(ref) == []

    def test_mice_fill_writes_a_name_that_names_one_thread(self):
        reg = _registry(COLLIDING + 'inquiry:lamp|Lamp|inquiry|\n')
        assert reg.mention_for('inquiry:lamp') == 'lamp'
        # The bare name is shared: the full id, which names one
        assert reg.mention_for('inquiry:secret') == 'inquiry:secret'


class TestOneRuleForNames:
    """TD-2: with a registry, prose counted as an (unregistered) thread and
    unregistered names kept their case."""

    def test_prose_names_no_thread_with_a_registry(self, long_threads):
        _project_dir, ref = long_threads
        r = mice.check('+gatsby dream opens', mice.registry_for(ref))
        assert r.thread == '' and r.problem == 'thread name is not a slug'

    def test_unregistered_slug_is_lower_cased(self, long_threads):
        _project_dir, ref = long_threads
        r = mice.check('+No-Such', mice.registry_for(ref))
        assert r.thread == 'no-such' and 'not in mice-threads.csv' in r.problem

    def test_without_a_registry_the_same(self):
        reg = mice.registry_for('')
        assert mice.check('+gatsby dream opens', reg).thread == ''
        assert mice.check('+No-Such', reg).thread == 'no-such'


class TestSkippedEntriesAreReported:
    """SF-2/SF-7: dormancy and mice-fill skipped entries without saying so,
    and filled gaps that existed only because of them."""

    def test_dormancy_lists_skipped_entries_and_suspects(self, long_threads):
        _project_dir, ref = long_threads
        _write_project(ref, {1: '+leo-guardian', 10: '+myth:leo-guardian;+;nope',
                             20: '-leo-guardian'})
        report = detect_mice_dormancy(ref)
        assert [(s, e) for s, e, _why in report.skipped] == [
            ('s10', '+myth:leo-guardian'), ('s10', '+'), ('s10', 'nope')]
        assert report.suspect == {'leo-guardian': ['s10: +myth:leo-guardian']}
        assert any('s10: mice_threads entry "nope" not counted' in w
                   for w in report.warnings())

    def test_mice_fill_skips_a_thread_with_an_unreadable_entry(
            self, long_threads, mock_api, mock_git, mock_costs, monkeypatch):
        from storyforge import cmd_elaborate
        project_dir, ref = long_threads
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _write_project(ref, {1: '+leo-guardian;+lamp-crisis', 10: 'event:leo-guardian',
                             20: '-leo-guardian;-lamp-crisis'})
        logged = []
        monkeypatch.setattr(cmd_elaborate, 'log', logged.append)
        mock_api.set_response_fn(_mention_middle_scene)
        _run_mice_fill(project_dir, ref, dry_run=False)
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        written = [r['mice_threads'] for sid, r in intent.items()
                   if sid not in ('s01', 's10', 's20') and r['mice_threads']]
        # lamp-crisis is filled; leo-guardian, whose s10 entry has the wrong
        # type, is left and the WARNING names the entry
        assert written and all(v == 'lamp-crisis' for v in written)
        assert any('not filling leo-guardian' in m and 's10: event:leo-guardian' in m
                   for m in logged)
        assert any('"event:leo-guardian" not counted' in m for m in logged)

    def test_no_registry_says_dormancy_was_not_checked(
            self, long_threads, mock_api, mock_git, mock_costs, monkeypatch):
        from storyforge import cmd_elaborate
        project_dir, ref = long_threads
        os.remove(os.path.join(ref, 'mice-threads.csv'))
        assert detect_mice_dormancy(ref).unchecked == 'no reference/mice-threads.csv'
        logged = []
        monkeypatch.setattr(cmd_elaborate, 'log', logged.append)
        _run_mice_fill(project_dir, ref, dry_run=False)
        assert any('MICE dormancy not checked' in m for m in logged)
        assert not any('No MICE dormancy gaps found' in m for m in logged)


class TestMiceHealthUnreadEntries:
    """SF-4: MICE health scored the surviving entries only, and called a
    book whose every entry was malformed 'No MICE threads found'."""

    def _score(self, ref, mice_by_scene):
        from storyforge.structural import score_mice_health
        _write_project(ref, mice_by_scene)
        return score_mice_health(_read_csv_as_map(os.path.join(ref, 'scenes.csv')),
                                 _read_csv_as_map(os.path.join(ref, 'scene-intent.csv')), ref)

    def test_dropped_entries_are_a_finding(self, long_threads):
        _project_dir, ref = long_threads
        result = self._score(ref, {1: '+leo-guardian;+', 20: '-leo-guardian;+:x'})
        msgs = [f['message'] for f in result['findings']]
        assert any('2 mice_threads entries name no thread' in m
                   and "s01: '+'" in m and "s20: '+:x'" in m for m in msgs)

    def test_all_malformed_is_not_none_found(self, long_threads):
        _project_dir, ref = long_threads
        result = self._score(ref, {1: '+', 5: '-', 9: 'bogus:x'})
        msgs = [f['message'] for f in result['findings']]
        assert 'No MICE threads found' not in msgs
        assert result['score'] == 0.0 and any('3 mice_threads entries' in m for m in msgs)


class TestMisorderedThread:
    """SF-3: a thread that closes before it opens had no gaps measured and
    nothing said so."""

    MICE = {2: '-leo-guardian', 15: '+leo-guardian'}

    def test_structure_reports_it(self, long_threads):
        _project_dir, ref = long_threads
        _write_project(ref, self.MICE)
        msgs = [c['message'] for c in validate_structure(ref)['checks']
                if c['check'] == 'mice-ops' and not c['passed']]
        assert any("'leo-guardian' closes in s02 before it opens in s15" in m for m in msgs)

    def test_dormancy_reports_it(self, long_threads):
        _project_dir, ref = long_threads
        _write_project(ref, self.MICE)
        report = detect_mice_dormancy(ref)
        assert report.gaps == []
        assert report.misordered == [('leo-guardian', 's02', 's15')]
        assert any('closes in s02 before it opens in s15' in w for w in report.warnings())


class TestDormancyEdges:
    """T-3."""

    def _gaps(self, ref, mice_by_scene):
        _write_project(ref, mice_by_scene)
        return [(g['before_scene'], g['after_scene']) for g in detect_mice_dormancy(ref).gaps]

    def test_never_closed_runs_to_the_last_entry(self, long_threads):
        _project_dir, ref = long_threads
        assert self._gaps(ref, {1: '+leo-guardian', 20: 'leo-guardian'}) == [('s01', 's20')]

    def test_opened_twice_spans_from_the_first_open(self, long_threads):
        _project_dir, ref = long_threads
        assert self._gaps(ref, {1: '+leo-guardian', 15: '+leo-guardian',
                                29: '-leo-guardian'}) == [('s01', 's15'), ('s15', 's29')]

    def test_mention_at_the_open_and_the_close(self, long_threads):
        _project_dir, ref = long_threads
        # A mention in the scene that opens (or closes) the thread is the
        # same position: no extra gap, none outside the span
        assert self._gaps(ref, {1: '+leo-guardian;leo-guardian', 10: 'leo-guardian',
                                20: '-leo-guardian;leo-guardian', 30: 'leo-guardian'}) == [
            ('s01', 's10'), ('s10', 's20')]

    @pytest.mark.parametrize('bad', ['+', '-', '+:x', '   ', '', ' ; '])
    def test_malformed_entries_in_each_reader(self, long_threads, bad):
        from storyforge.structural import score_mice_health
        _project_dir, ref = long_threads
        value = f'+leo-guardian;{bad}'
        _write_project(ref, {1: value, 20: '-leo-guardian'})
        resolved = mice.resolve(value, mice.registry_for(ref))
        assert [r.entry.raw for r in resolved if r.valid] == ['+leo-guardian']
        bad_entries = [r.entry.raw for r in resolved if not r.valid]
        # Validate rejects exactly those; dormancy counts the valid one and
        # lists the rest; structure and MICE health name them
        assert [p['entry'] for p in _check_mice(value, mice.registry_for(ref))] == bad_entries
        report = detect_mice_dormancy(ref)
        assert [g['thread_id'] for g in report.gaps] == ['leo-guardian']
        assert [e for _s, e, _w in report.skipped] == bad_entries
        unread = [c for c in validate_structure(ref)['checks'] if c['check'] == 'mice-unread']
        assert bool(unread) == bool(bad_entries)
        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        health = score_mice_health(scenes, intent, ref)['findings']
        assert any('name no thread' in f['message'] for f in health) == bool(bad_entries)

    def test_unknown_names_in_structural_checks(self, long_threads):
        _project_dir, ref = long_threads
        _write_project(ref, {1: '+No-Such', 5: 'no-such', 9: '-NO-SUCH'})
        checks = validate_structure(ref)['checks']
        # One thread, lower-cased: opened once, closed once
        assert any(c['check'] == 'mice-ops' and c['passed'] for c in checks)
        assert not any(c['check'] == 'unclosed-mice-threads' for c in checks)


class TestAuditThread:
    """CR-1: audit compared raw entry text, so a typed id found nothing."""

    def test_typed_id_and_alias(self, long_threads):
        from storyforge import audit
        project_dir, ref = long_threads
        _write_project(ref, {1: '+inquiry:lamp-crisis', 4: 'Lamp crisis', 9: '-lamp-crisis',
                             12: '+leo-guardian', 14: 'the guardian'})
        assert audit.thread_scenes(project_dir, 'inquiry:lamp-crisis') == {'s01', 's04', 's09'}
        assert audit.thread_scenes(project_dir, 'lamp-crisis') == {'s01', 's04', 's09'}
        assert audit.thread_scenes(project_dir, 'The Guardian') == {'s12', 's14'}


class TestEntryGrammar:
    """TD-1/TD-6: one parser, with a closed kind; normalize uses it."""

    def test_kinds(self):
        assert mice.parse('+a').kind is mice.Kind.OPEN
        assert mice.parse('-a').kind is mice.Kind.CLOSE
        assert mice.parse('a').kind is mice.Kind.MENTION
        assert mice.parse('+').kind is mice.Kind.OPEN and mice.parse('+').name == ''

    def test_normalize_keeps_a_lone_operator_and_a_note(self):
        from storyforge.enrich import normalize_mice_threads
        lookup = {'zara': 'zara-identity'}
        assert normalize_mice_threads('+;zara[advance: x];-zara', lookup) == \
            '+;zara-identity[advance: x];-zara-identity'

    def test_a_note_is_reported_by_validate(self):
        reg = mice.registry_from_rows([{'id': 'zara', 'name': 'Zara'}])
        problems = _check_mice('zara[advance: x]', reg)
        assert problems and 'note' in problems[0]['reason']

    def test_seeding_reads_entries_with_the_parser(self, project_dir):
        from storyforge.cmd_migrate import _seed_mice_threads
        ref = os.path.join(project_dir, 'reference')
        os.remove(os.path.join(ref, 'mice-threads.csv'))
        _write_project(ref, {1: '+inquiry:who;myth:no', 2: '-myth:bad;event:mention-only',
                             3: '- milieu : the-city '})
        os.remove(os.path.join(ref, 'mice-threads.csv'))
        assert _seed_mice_threads(ref, dry_run=False) == 'mice-threads.csv:done:2'
        reg = mice.registry_for(ref)
        assert reg.types == {'who': 'inquiry', 'the-city': 'milieu'}
