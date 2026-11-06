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
from storyforge.enrich import load_mice_registry, resolve_mice_entries
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
        before = detect_mice_dormancy(ref)
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
        assert detect_mice_dormancy(ref) == []

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
        gaps = detect_mice_dormancy(ref)
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
        alias, types = load_mice_registry(os.path.join(ref, 'mice-threads.csv'))
        for entry in self.ENTRIES:
            valid = not _check_mice(entry, alias, types)
            counted = bool(resolve_mice_entries(entry, alias, types))
            assert valid == counted, entry

    def test_alias_and_case_mentions_break_dormancy(self, long_threads):
        project_dir, ref = long_threads
        _write_project(ref, {1: '+leo-guardian', 10: 'The Guardian',
                             20: '-leo-guardian'})
        assert _mice_errors(ref, project_dir) == []
        assert all(g['gap_size'] < 19 for g in detect_mice_dormancy(ref))

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
        assert detect_mice_dormancy(ref) == []
        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert not [f for f in score_mice_health(scenes, intent, ref)['findings']
                    if 'dormant' in f['message']]

    def test_unopened_thread_spans_its_mentions(self, long_threads):
        # With no open or close the whole stretch is the span
        _project_dir, ref = long_threads
        _write_project(ref, {1: 'leo-guardian', 20: 'leo-guardian'})
        assert [g['gap_size'] for g in detect_mice_dormancy(ref)] == [19]


class TestOtherReaders:
    def test_legacy_typed_registry_id_answers_to_its_bare_name(self, tmp_path):
        path = tmp_path / 'mice-threads.csv'
        path.write_text(REGISTRY)
        alias, _types = load_mice_registry(str(path))
        assert alias['lamp-crisis'] == 'inquiry:lamp-crisis'
        assert alias['inquiry:lamp-crisis'] == 'inquiry:lamp-crisis'

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
