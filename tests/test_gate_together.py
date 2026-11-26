"""The gate's independent model calls run at once (`runner.together`):
extraction, the blocking read and the typed state; the questions' askings,
and the facts' questions beside the promises'; the blocking readings."""

import json
import os
import threading
from unittest.mock import patch

import pytest

from storyforge import gate, runner

SCENE = 'act1-sc02'


def _text(payload):
    return {'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}


class TestTogether:
    def test_results_come_back_in_the_order_given(self):
        assert runner.together(lambda: 1, lambda: 2, lambda: 3) == [1, 2, 3]

    def test_the_calls_overlap(self):
        meet = threading.Barrier(3, timeout=5)
        assert runner.together(*(lambda: meet.wait() >= 0 for _ in range(3))) == [True] * 3

    def test_the_first_error_in_order_is_raised_after_all_have_run(self):
        ran = []

        def fail(what):
            def call():
                ran.append(what)
                raise ValueError(what)
            return call
        with pytest.raises(ValueError, match='second'):
            runner.together(lambda: ran.append('first'), fail('second'), fail('third'))
        assert sorted(ran) == ['first', 'second', 'third']

    def test_one_at_a_time_when_parallel_is_one(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_PARALLEL', '1')
        seen = []
        assert runner.together(lambda: seen.append(threading.get_ident()) or 'a',
                               lambda: seen.append(threading.get_ident()) or 'b') == ['a', 'b']
        assert set(seen) == {threading.get_ident()}

    def test_the_callers_meter_sees_every_call(self):
        from storyforge import api
        reply = _text({})
        with api.metered() as meter, patch('storyforge.api._api_request', return_value=reply):
            runner.together(*(lambda: api.invoke('p', 'claude-opus-5-5') for _ in range(3)))
        assert len(meter.replies) == 3


@pytest.mark.continuity
@pytest.mark.blocking_read
def test_extraction_the_blocking_read_and_the_typed_state_run_at_once(project_dir, tmp_path,
                                                                       monkeypatch):
    # iliad-adult, 2026-11-17: one after the other they were most of a gate
    # run's four minutes. Each waits here for the other two: one after the
    # other, the first would wait alone and the barrier break
    monkeypatch.setattr(gate, 'GATE_CHECK_METHOD', 'questions')
    # each call's schema names what it reads: extraction, the typed state,
    # the blocking read (each of its readings, which run at once too)
    from storyforge.blocking import BLOCKING_READINGS
    first = ('commitments', 'records', 'findings')
    meet = threading.Barrier(2 + BLOCKING_READINGS, timeout=10)
    met = []

    def fake(path, body, **k):
        props = ((body.get('output_config') or {}).get('format', {})
                 .get('schema', {}).get('properties', {}))
        key = next((p for p in first if p in props), None)
        if key:
            met.append(key)
            meet.wait()
            return _text({key: []})
        return _text({'verdicts': []} if 'verdicts' in props else {'answers': []})
    with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'w') as f:
        f.write('Tessa mocked Dorren until he left the study.')
    with patch('storyforge.api._api_request', side_effect=fake):
        try:
            gate.gate_scene(project_dir, SCENE, command='advisor',
                            log_dir=str(tmp_path / 'logs'), extract_model='m', check_model='m')
        except gate.GateError:
            pass   # the questions' fake answers nothing; the calls before it are the test
    assert sorted(met) == sorted(['commitments', 'records'] + ['findings'] * BLOCKING_READINGS)
