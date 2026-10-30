"""Extract phase 5, steps 5a (structure) and 5b (themes and motifs) (#440).

The model only selects and names; these tests pin what code does with its
reply: every id checked against the scenes, every column copied from the
scene CSVs, and every problem collected for the one retry.
"""

import json

import pytest

from storyforge.extract_describe import (
    StructureError, build_structure_prompt, build_themes_prompt,
    motif_candidates, parse_structure, parse_themes, structure_rows,
)


def _scenes(n=20):
    return [{'id': f's{i:02d}', 'seq': str(i), 'title': f'Scene {i}',
             'summary': f'Thing {i} happens.', 'act': str(1 + (i - 1) * 3 // n),
             'pov': 'nick', 'action_sequel': 'action' if i % 2 else 'sequel',
             'emotional_arc': 'calm to dread', 'value_at_stake': 'trust',
             'value_shift': '+/-', 'turning_point': 'revelation',
             'function': f'Does {i}.', 'word_count': '1000',
             'motifs': 'green light;Green Light' if i % 4 == 0 else 'eyes'}
            for i in range(1, n + 1)]


def _spine(n=5):
    return [{'id': f'event-{k}', 'title': f'Event {k}', 'summary': f'Event {k} happens.',
             'function': f'Turns {k}.'} for k in range(1, n + 1)]


def _reply(spine=None, arch=None, genre='literary fiction'):
    spine = _spine() if spine is None else spine
    if arch is None:
        arch = [{'scene_id': f's{i:02d}', 'spine_event': f'event-{1 + (i - 1) // 4}'}
                for i in range(1, 21)]
    return json.dumps({'genre': genre, 'subgenre': '', 'spine': spine,
                       'architecture': arch})


class TestParseStructure:
    def test_a_good_reply(self):
        s = parse_structure(_reply(), _scenes())
        assert [e['id'] for e in s['spine']] == [f'event-{k}' for k in range(1, 6)]
        assert len(s['architecture']) == 20
        assert s['genre'] == 'literary fiction'

    def test_every_problem_is_collected_for_the_retry(self):
        spine = _spine()
        spine[1]['summary'] = ' '.join(['word'] * 36)
        arch = [{'scene_id': 'nowhere', 'spine_event': 'event-1'},
                {'scene_id': 's01', 'spine_event': 'event-9'},
                {'scene_id': 's02', 'spine_event': 'event-1'},
                {'scene_id': 's02', 'spine_event': 'event-1'}]
        with pytest.raises(StructureError) as e:
            parse_structure(_reply(spine, arch), _scenes())
        text = ' '.join(e.value.problems)
        assert "'nowhere' is not one of the scene ids" in text
        assert "event-9" in text
        assert 's02 is anchored twice' in text
        assert '36 words' in text
        assert 'event-3 has no anchor scene' in text
        assert 'architecture has 1 entries; expected 15-20' in text

    def test_ranges_shrink_to_a_short_book(self):
        scenes = _scenes(6)
        arch = [{'scene_id': f's{i:02d}', 'spine_event': f'event-{min(i, 5)}'}
                for i in range(1, 7)]
        s = parse_structure(_reply(arch=arch), scenes)
        assert len(s['architecture']) == 6

    def test_spine_is_ordered_by_where_it_first_lands(self):
        arch = json.loads(_reply())['architecture']
        swap = {'s01': 's17', 's02': 's18', 's03': 's19', 's04': 's20',
                's17': 's01', 's18': 's02', 's19': 's03', 's20': 's04'}
        for a in arch:   # event-1 and event-5 trade scenes: event-1 now lands last
            a['scene_id'] = swap.get(a['scene_id'], a['scene_id'])
        s = parse_structure(_reply(arch=arch), _scenes())
        assert [e['id'] for e in s['spine']][-1] == 'event-1'
        assert [a['scene_id'] for a in s['architecture']] == \
            sorted(a['scene_id'] for a in s['architecture'])

    def test_unreadable_reply_is_an_error_not_an_empty_structure(self):
        with pytest.raises(ValueError):
            parse_structure('not json', _scenes())


class TestStructureRows:
    def test_columns_come_from_the_scenes_not_the_model(self):
        scenes = _scenes()
        spine, arch = structure_rows(parse_structure(_reply(), scenes), scenes)
        first = arch[0]
        assert first['id'] == 's01'
        assert first['summary'] == 'Thing 1 happens.'
        assert first['value_shift'] == '+/-'
        assert first['act'] == '1'
        assert spine[0]['seq'] == '1'
        # A spine event's act is its first anchor's
        last_event = spine[-1]['id']
        assert spine[-1]['act'] == next(a['act'] for a in arch if a['spine_event'] == last_event)


class TestPrompts:
    def test_structure_prompt_lists_scenes_and_carries_retry_problems(self):
        prompt = build_structure_prompt({'tone': 'elegiac'}, _scenes(),
                                        problems=['spine event x has no anchor scene'])
        assert 's20' in prompt and 'elegiac' in prompt
        assert 'spine event x has no anchor scene' in prompt
        assert 'describing a finished book' in prompt

    def test_themes_prompt_says_when_no_motif_recurs(self):
        prompt = build_themes_prompt({}, _scenes(3), [])
        assert 'name no motif in more than one scene' in prompt


class TestMotifCandidates:
    def test_counted_by_scene_case_folded_and_recurring_only(self):
        scenes = _scenes(8)
        scenes[0]['motifs'] = 'the ash heap'
        got = dict(motif_candidates(scenes))
        assert got['green light'] == ['s04', 's08']   # 'Green Light' twice in a scene counts once
        assert 'the ash heap' not in got
        assert list(dict(motif_candidates(scenes)))[0] == 'eyes'   # most frequent first


def _themes_reply(scenes, **over):
    reply = {
        'themes': [{'id': f't{k}', 'name': f'T{k}', 'tier': 'primary' if k == 1 else 'secondary',
                    'description': 'd'} for k in range(1, 4)],
        'scene_themes': [{'scene_id': s['id'], 'themes': ['t1']} for s in scenes],
        'motifs': [{'id': 'green-light', 'name': 'The green light',
                    'aliases': ['green light'], 'tier': 'primary'}],
    }
    reply.update(over)
    return json.dumps(reply)


class TestParseThemes:
    def test_a_good_reply(self):
        scenes = _scenes(8)
        out = parse_themes(_themes_reply(scenes), scenes, motif_candidates(scenes))
        assert out['scene_themes']['s01'] == ['t1']
        assert out['motifs'][0]['aliases'] == ['green light']

    def test_problems(self):
        scenes = _scenes(8)
        reply = _themes_reply(
            scenes,
            scene_themes=[{'scene_id': 's01', 'themes': ['t1', 'ghost']},
                          {'scene_id': 'invented', 'themes': []}],
            motifs=[{'id': 'a', 'name': 'A', 'aliases': ['green light'], 'tier': 'primary'},
                    {'id': 'b', 'name': 'B', 'aliases': ['green light', 'moon'], 'tier': 'tertiary'}])
        with pytest.raises(StructureError) as e:
            parse_themes(reply, scenes, motif_candidates(scenes))
        text = ' '.join(e.value.problems)
        assert 'unknown theme(s): ghost' in text
        assert "'invented', which is not a scene id" in text
        assert '7 scene(s) missing from scene_themes' in text
        assert "'green light' is claimed by both a and b" in text
        assert "'moon' is not one of the listed mentions" in text
