"""Tests for timeline functions (migrated from test-timeline.sh)."""

import os
import shutil

import storyforge.csv_cli as csv_cli


def _capture(fn, *args, **kwargs):
    """Call a csv_cli function and return its result as a string."""
    result = fn(*args, **kwargs)
    if result is None:
        return ''
    if isinstance(result, list):
        return '\n'.join(result)
    return str(result)


class TestTimelineCsvOperations:
    def test_read_existing_timeline_day(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'act1-sc01', 'timeline_day') == '1'

    def test_update_timeline_day(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act2-sc01', 'timeline_day', '5')
        assert _capture(csv_cli.get_field, tmp_csv, 'act2-sc01', 'timeline_day') == '5'

    def test_overwrite_existing(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act1-sc01', 'timeline_day', '99')
        assert _capture(csv_cli.get_field, tmp_csv, 'act1-sc01', 'timeline_day') == '99'


def _scenes(project_dir, rows):
    """Replace scenes.csv with *rows*: (id, day, mode) in reading order."""
    from storyforge.elaborate import _write_csv, _FILE_MAP
    _write_csv(os.path.join(project_dir, 'reference', 'scenes.csv'),
               [{'id': sid, 'seq': str(i + 1), 'title': sid, 'timeline_day': day,
                 'time_mode': mode, 'status': 'drafted'}
                for i, (sid, day, mode) in enumerate(rows)],
               _FILE_MAP['scenes.csv'])


def _column(project_dir, col):
    from storyforge.elaborate import _read_csv_as_map
    return {sid: r.get(col, '') for sid, r in
            _read_csv_as_map(os.path.join(project_dir, 'reference', 'scenes.csv')).items()}


class TestCues:
    """F-035: phase 1 asked each scene, alone, for an absolute day. On The
    Great Gatsby the shooting landed on day 73 and the funeral on day 68.
    Scenes now give cues; the pass places them."""

    def test_parse_cues(self):
        from storyforge.timeline import parse_cues
        cues = parse_cues('TITLE: x\nTIME_RELATION: earlier — Nick recalls 1917\n'
                          'TIME_GAP: "five years"\nTIME_ANCHOR: (none)\n'
                          'TIME_SPAN:\nTIME_DATE: 1917\n')
        assert cues == {'relation': 'earlier', 'gap': 'five years', 'anchor': '',
                        'refers': '', 'span': '', 'date': '1917'}

    def test_refers_cue_reaches_the_assignment_prompt(self):
        """Gatsby VII: "that June night three months before" pins the
        hottest day, but no cue carried it."""
        from storyforge.timeline import parse_cues, build_assignment_prompt
        cues = parse_cues('TIME_RELATION: continues\n'
                          'TIME_REFERS: that June night three months before\n')
        assert cues['refers'] == 'that June night three months before'
        prompt = build_assignment_prompt([{'id': 's', 'cues': cues, 'provisional': None}],
                                         10, 10, [])
        assert 'refers "that June night three months before"' in prompt

    def test_derived_date_and_day_one_calendar(self):
        """Gatsby (research: Bruccoli, Pendleton): "In two weeks it'll be the
        longest day" fixes the dinner at about June 7, but the cue prompt
        forbade deriving it, so day 1 had no date and the assigner put "a few
        days before the Fourth of July" on day 2, 24 days early."""
        from storyforge.timeline import CUE_INSTRUCTIONS, parse_cues, build_assignment_prompt
        assert '"XXXX-06-07~"' in CUE_INSTRUCTIONS
        assert parse_cues('TIME_DATE: XXXX-06-07~\n')['date'] == 'XXXX-06-07~'
        prompt = build_assignment_prompt([{'id': 's', 'cues': {}, 'provisional': None}],
                                         None, None, [])
        assert 'work out which calendar date day 1 falls on' in prompt
        assert "give day 1's calendar date" in prompt

    def test_recollection_inside_a_present_scene_is_placed_by_weight(self):
        """Gatsby: Jordan's Louisville story and the reporter scene (Cody's
        backstory after a one-line lead-in) flipped between the past and the
        present from run to run, and the flashback gauge with them."""
        from storyforge.timeline import CUE_INSTRUCTIONS, build_assignment_prompt
        assert 'only a line or a short lead-in before it mostly tells the past' in CUE_INSTRUCTIONS
        prompt = build_assignment_prompt([{'id': 's', 'cues': {}, 'provisional': None}],
                                         None, None, [])
        assert 'placed by weight, the same way every time' in prompt

    def test_unknown_relation_is_unclear_and_bad_date_dropped(self):
        from storyforge.timeline import parse_cues
        cues = parse_cues('TIME_RELATION: sometime\nTIME_DATE: July 4th, 1922\n')
        assert cues['relation'] == 'unclear' and cues['date'] == ''

    def test_cues_round_trip(self, project_dir):
        from storyforge.timeline import write_cues, read_cues
        write_cues(project_dir, {'a': {'relation': 'later', 'gap': 'two weeks'}})
        write_cues(project_dir, {'b': {'relation': 'continues'}})
        cues = read_cues(project_dir)
        assert cues['a']['gap'] == 'two weeks' and cues['b']['relation'] == 'continues'

    def test_skeleton_prompt_asks_for_cues_not_a_day(self):
        from storyforge.extract import build_skeleton_prompt
        prompt = build_skeleton_prompt('s1', 'Text.', {}, previous_tail='...the end of it.')
        assert 'TIMELINE_DAY' not in prompt
        assert 'TIME_RELATION' in prompt and 'TIME_DATE' in prompt
        assert '...the end of it.' in prompt

    def test_skeleton_parser_keeps_only_the_date(self):
        from storyforge.extract import parse_skeleton_response
        result = parse_skeleton_response('TITLE: T\nTIMELINE_DAY: 73\nTIME_RELATION: later\n'
                                         'TIME_DATE: XXXX-07-04\n', 's1')
        assert 'timeline_day' not in result
        assert result['timeline_date'] == 'XXXX-07-04'


class TestGaps:
    def test_an_explained_gap_is_not_a_gap(self):
        """F-066 (The Plastic Age): 'three days" (vacation between terms)'
        was the length of a vacation, read as the gap."""
        from storyforge.timeline import gap_to_days
        assert gap_to_days('three days" (vacation between terms)') is None
        assert gap_to_days('three days (the vacation)') is None

    def test_gap_to_days(self):
        from storyforge.timeline import gap_to_days
        cases = {
            'an hour': 0, 'later that evening': 0, 'moments later': 0,
            'the next morning': 1, 'the following day': 1,
            'three days': 3, '2 weeks': 14, 'a fortnight': 14, 'a month': 30,
            'five years': 1825, 'two years later': 730,
            'some time later': None, 'a few weeks': None, '': None,
            # Gatsby: an explanation in the gap field, not a gap
            'The text indicates this occurs some days after the previous scene, the next day': None,
        }
        for text, days in cases.items():
            assert gap_to_days(text) == days, text


class TestEdtf:
    def test_valid(self):
        from storyforge.timeline import is_valid_edtf
        for value in ('1922-07-04', 'XXXX-07-04', '1922', '1922-07', '1922-22',
                      '1917~', 'XXXX-10?', '1922-06/1922-09', '../1922', '19XX'):
            assert is_valid_edtf(value), value

    def test_invalid(self):
        from storyforge.timeline import is_valid_edtf
        for value in ('July 4', '1922-13', '1922-07-32', '1922-22-01', 'XXXX',
                      'XXXX-XX-XX', '22', '1922/July', ''):
            assert not is_valid_edtf(value), value

    def test_described_in_words_for_prompts(self):
        """Gatsby: the model read 1922-22 (summer 1922) as June 22."""
        from storyforge.timeline import describe_edtf
        assert describe_edtf('1922-22') == 'summer 1922'
        assert describe_edtf('XXXX-07-04') == '4 July (year not stated)'
        assert describe_edtf('1917~') == '1917, approximately'
        assert describe_edtf('1922-06/1922-09') == 'from June 1922 to September 1922'
        assert describe_edtf('XXXX-XX-04') == 'day 4 of an unstated month (year not stated)'

    def test_schema_validates_new_columns(self, project_dir):
        from storyforge.schema import validate_schema
        ref = os.path.join(project_dir, 'reference')
        _scenes(project_dir, [('a', '1', 'scene'), ('b', '2', 'sometimes')])
        import csv as _csv
        path = os.path.join(ref, 'scenes.csv')
        with open(path) as f:
            rows = list(_csv.DictReader(f, delimiter='|'))
        rows[0]['timeline_date'], rows[1]['timeline_date'] = 'XXXX-07-04', 'July 4'
        from storyforge.elaborate import _write_csv, _FILE_MAP
        _write_csv(path, rows, _FILE_MAP['scenes.csv'])
        errors = validate_schema(ref, project_dir)['errors']
        bad = {(e['row'], e['column']) for e in errors}
        assert ('b', 'timeline_date') in bad and ('b', 'time_mode') in bad
        assert ('a', 'timeline_date') not in bad and ('a', 'time_mode') not in bad


class TestWalk:
    def test_relations(self):
        from storyforge.timeline import walk
        cues = {
            'a': {'relation': 'continues'},
            'b': {'relation': 'later', 'gap': 'the next morning'},
            'c': {'relation': 'earlier', 'gap': 'five years'},
            'd': {'relation': 'continues'},
            'e': {'relation': 'frame'},
            'f': {'relation': 'later', 'gap': 'some time later'},
        }
        days = walk(list(cues), cues)
        assert days == {'a': 1, 'b': 2, 'c': 2 - 1825, 'd': 2 - 1825, 'e': None, 'f': None}

    def test_after_a_flashback(self):
        """Review of #324: "the next morning" after a memory counted from the
        memory and put the present years in the past."""
        from storyforge.timeline import walk
        cues = {'a': {'relation': 'later'}, 'b': {'relation': 'later', 'gap': 'ten days'},
                'memory': {'relation': 'earlier', 'gap': 'five years'},
                'more': {'relation': 'continues'},
                'back': {'relation': 'later', 'gap': 'the next morning'}}
        days = walk(list(cues), cues)
        assert days['memory'] == days['more'] == 11 - 1825
        assert days['back'] is None  # the model decides

    def test_scene_after_a_mid_book_frame(self):
        from storyforge.timeline import walk
        cues = {'a': {'relation': 'later'}, 'b': {'relation': 'later', 'gap': 'a week'},
                'frame': {'relation': 'frame'},
                'c': {'relation': 'earlier', 'gap': 'two years'}}
        assert walk(list(cues), cues) == {'a': 1, 'b': 8, 'frame': None, 'c': 8}

    def test_continues_from_an_earlier_batch(self):
        from storyforge.timeline import walk
        cues = {'x': {'relation': 'later', 'gap': 'two days'}}
        assert walk(['x'], cues, last=40, present=40) == {'x': 42}

    def test_clock_starts_after_an_opening_frame(self):
        """Gatsby opens with Nick looking back; nothing was placed at all."""
        from storyforge.timeline import walk
        cues = {'frame': {'relation': 'frame'}, 'a': {'relation': 'later'},
                'b': {'relation': 'later', 'gap': 'the next day'}}
        assert walk(list(cues), cues) == {'frame': None, 'a': 1, 'b': 2}

    def test_first_scene_flashback_is_left_for_the_model(self):
        from storyforge.timeline import walk
        assert walk(['a'], {'a': {'relation': 'earlier', 'gap': 'a year'}}) == {'a': None}


class TestAssignment:
    def _items(self, n, relation='later', gap='the next day'):
        return [{'id': f's{i}', 'title': f'S{i}', 'cues': {'relation': relation, 'gap': gap}}
                for i in range(n)]

    def test_parse_assignments(self):
        from storyforge.timeline import parse_assignments
        result = parse_assignments(
            's1 | 3 | scene | next day\n- s2 | -1825 | summary | 1917\n'
            's3 | 90 | odd | x\nother | 1 | scene\ns4 | soon | scene\n', ['s1', 's2', 's3', 's4'])
        assert result == {'s1': (3, 'scene', 'next day'), 's2': (-1825, 'summary', '1917'),
                          's3': (90, '', 'x')}

    def test_only_lines_after_calendar_count(self):
        from storyforge.timeline import parse_assignments
        result = parse_assignments('REASONING:\ns1 | 76 | scene | first try\n'
                                   'CALENDAR:\ns1 | 87 | scene | three months on\n', ['s1'])
        assert result == {'s1': (87, 'scene', 'three months on')}

    def test_calendar_marker_on_the_answer_line(self):
        """Second review of #324: "CALENDAR: a | 5 | ..." parsed the drafts."""
        from storyforge.timeline import parse_assignments
        for response in ('REASONING:\ns1 | 2 | scene | try\nCALENDAR: s1 | 5 | scene | x\n',
                         'REASONING:\ns1 | 2 | scene | try\n**CALENDAR:**\ns1 | 5 | scene | x\n',
                         'CALENDAR:\ns1 | 2 | scene | early\nCALENDAR:\ns1 | 5 | scene | x\n'):
            assert parse_assignments(response, ['s1']) == {'s1': (5, 'scene', 'x')}, response

    def test_batches_carry_the_present(self, tmp_path, monkeypatch):
        import storyforge.timeline as tl
        monkeypatch.setattr(tl, '_BATCH_SIZE', 2)
        prompts = []

        def invoke(prompt, log_file, label):
            prompts.append(prompt)
            # The model moves every scene a week on from the provisional
            ids = [l.split(' — ')[0] for l in prompt.split('## Scenes')[1].split('\n')
                   if ' — ' in l]
            n = len(prompts)
            return '\n'.join(f'{sid} | {10 * n + i} | scene | test' for i, sid in enumerate(ids))

        placed = tl.assign_calendar(self._items(5), invoke, str(tmp_path))
        assert len(prompts) == 3
        assert 'present (latest day the main story has reached): 11' in prompts[1]
        assert placed['s4'] == (30, 'scene', 'test')

    def test_failed_batch_is_asked_again_for_the_answer_only(self, tmp_path):
        from storyforge.timeline import assign_calendar
        prompts = []

        def invoke(prompt, log_file, label):
            prompts.append(prompt)
            return None if len(prompts) == 1 else 'CALENDAR:\ns0 | 5 | scene | x\n'
        placed = assign_calendar(self._items(1), invoke, str(tmp_path))
        assert len(prompts) == 2 and 'REASONING' not in prompts[1]
        assert placed['s0'] == (5, 'scene', 'x')

    def test_truncated_batch_keeps_provisional_days(self, tmp_path):
        from storyforge.timeline import assign_calendar
        items = self._items(3)
        items[2]['cues'] = {'relation': 'unclear'}
        placed = assign_calendar(items, lambda *a: None, str(tmp_path))
        assert placed == {'s0': (1, 'scene', 'from cues'), 's1': (2, 'scene', 'from cues')}

    def test_run_assignment_fills_empty_and_proposes_changes(self, project_dir, monkeypatch, capsys):
        import storyforge.timeline as tl
        _scenes(project_dir, [('a', '', ''), ('b', '5', 'scene'), ('c', '', '')])
        tl.write_cues(project_dir, {'a': {'relation': 'continues'},
                                    'b': {'relation': 'later', 'gap': 'next morning'},
                                    'c': {'relation': 'frame'}})
        monkeypatch.setattr(tl, '_invoke_assignment', lambda model: (
            lambda prompt, log_file, label: 'a | 1 | scene | start\nb | 2 | scene | next\n'
                                            'c | 800 | frame | two years on\n'))
        logs = os.path.join(project_dir, 'working', 'logs')
        result = tl.run_assignment(project_dir, 'm', logs, force=False)
        # One authored day: the whole calendar is only proposed
        assert _column(project_dir, 'timeline_day') == {'a': '', 'b': '5', 'c': ''}
        assert _column(project_dir, 'time_mode')['c'] == ''
        with open(os.path.join(project_dir, tl.PROPOSED_FILE)) as f:
            proposed = f.read()
        # Aligned to the author's day: b (5) agrees once shifted by +3
        assert 'b|timeline_day' not in proposed
        assert 'a|timeline_day||4|start' in proposed and 'c|time_mode||frame|' in proposed
        assert result['assigned'] == 0 and result['proposed'] == 3

        tl.run_assignment(project_dir, 'm', logs, force=True)
        assert _column(project_dir, 'timeline_day') == {'a': '1', 'b': '2', 'c': '800'}
        assert _column(project_dir, 'time_mode')['c'] == 'frame'
        # A clean run leaves no stale proposal behind
        assert not os.path.exists(os.path.join(project_dir, tl.PROPOSED_FILE))

    def test_proposals_are_aligned_to_the_authors_day_one(self, project_dir, monkeypatch):
        import storyforge.timeline as tl
        _scenes(project_dir, [('a', '-2', 'scene'), ('b', '0', 'scene'), ('c', '9', 'scene')])
        tl.write_cues(project_dir, {'a': {'relation': 'later'}})
        monkeypatch.setattr(tl, '_invoke_assignment', lambda model: (
            lambda prompt, log_file, label: 'CALENDAR:\na | 1 | scene | x\nb | 3 | scene | x\n'
                                            'c | 7 | scene | x\n'))
        result = tl.run_assignment(project_dir, 'm', os.path.join(project_dir, 'working', 'logs'),
                                   force=False)
        # Shifted by -3: a and b agree; only c (6 vs the author's 9) is proposed
        with open(os.path.join(project_dir, tl.PROPOSED_FILE)) as f:
            assert f.read().splitlines()[1:] == ['c|timeline_day|9|4|x']
        assert result['proposed'] == 1

    def test_unplaced_book_is_written_when_nothing_was_authored(self, project_dir, monkeypatch):
        import storyforge.timeline as tl
        _scenes(project_dir, [('a', '', ''), ('b', '', '')])
        tl.write_cues(project_dir, {'a': {'relation': 'later'}, 'b': {'relation': 'continues'}})
        monkeypatch.setattr(tl, '_invoke_assignment', lambda model: (
            lambda prompt, log_file, label: 'CALENDAR:\na | 1 | scene | x\nb | 1 | frame narration\n'))
        tl.run_assignment(project_dir, 'm', os.path.join(project_dir, 'working', 'logs'), force=False)
        assert _column(project_dir, 'timeline_day') == {'a': '1', 'b': '1'}
        # "frame narration" is no mode; the cue says continues, so scene
        assert _column(project_dir, 'time_mode') == {'a': 'scene', 'b': 'scene'}

    def test_failed_batch_keeps_provisional_days(self, project_dir, monkeypatch):
        import storyforge.timeline as tl

        def boom(*a, **k):
            raise RuntimeError('HTTP 529')
        monkeypatch.setattr('storyforge.api.invoke_to_file', boom)
        invoke = tl._invoke_assignment('m')
        assert invoke('p', os.path.join(project_dir, 'x.json'), 'timeline (batch 1 of 1)') is None


class TestMonthAnchors:
    """F-071 (The Plastic Age): the model read "early in May" right and
    counted days from it wrong; code pins month anchors after its pass."""

    def test_anchor_windows(self):
        from storyforge.timeline import anchor_window
        assert anchor_window('early in May')[:3] == (120, 129, 'early May')
        assert anchor_window('One evening in early spring')[2] == 'early spring'
        assert anchor_window('late February')[:2] == (51, 58)
        assert anchor_window("Fall's here")[2] == 'autumn'
        winter = anchor_window('cold winter air')
        assert winter[0] > winter[1]  # across the new year

    def test_anchors_that_are_not_the_scenes_month(self):
        from storyforge.timeline import anchor_window
        assert anchor_window('golden haze of Indian summer') is None
        assert anchor_window("I think I'll pray to-morrow; I may need it") is None
        assert anchor_window('between March and May') is None
        assert anchor_window('dawn; "that still October night" (in the flashback)') is None
        assert anchor_window('Saturday morning') is None

    def _book(self, rows):
        """(id, day, mode, relation, gap, anchor) → items and placements."""
        items = [{'id': sid, 'cues': {'relation': rel, 'gap': gap, 'anchor': anchor}}
                 for sid, _day, _mode, rel, gap, anchor in rows]
        placed = {sid: (day, mode, '') for sid, day, mode, *_ in rows}
        return items, placed

    def test_the_plastic_age_prom_is_pinned_to_may(self):
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([
            ('stroll', 7, 'scene', 'continues', '', "Fall's here"),
            ('carl', 395, 'scene', 'later', '', 'one night in October'),
            ('bull', 440, 'scene', 'later', '', 'late November'),
            ('tucker', 550, 'scene', 'later', '', 'In March'),
            ('junior', 730, 'summary', 'later', '', ''),
            ('winsor', 820, 'scene', 'later', '', 'One evening in early spring'),
            ('poker', 820, 'scene', 'continues', '', ''),
            ('anticipates', 840, 'scene', 'later', '', 'early in May'),
            ('station', 848, 'scene', 'later', 'some days', ''),
            ('prom', 848, 'scene', 'continues', '', ''),
            ('morning', 849, 'scene', 'later', 'the next morning', ''),
            ('memory', -30, 'scene', 'earlier', '', 'one night in August'),
            ('race', 905, 'scene', 'later', '', ''),
            ('senior', 1200, 'summary', 'later', '', ''),
        ])
        pinned, moves, day_one = pin_month_anchors(items, placed)
        day = {sid: d for sid, (d, _m, _b) in pinned.items()}
        # Day 1 in early September, from the anchors that agree
        assert 235 <= day_one <= 275
        # Early spring and early May, the runs joined to them moving along
        assert 59 <= (day_one + day['winsor'] - 1) % 365 <= 66
        assert day['poker'] == day['winsor']
        assert 120 <= (day_one + day['anticipates'] - 1) % 365 <= 129
        assert day['prom'] == day['station'] and day['morning'] == day['prom'] + 1
        # The race moves only as far as order needs; a vague gap ahead of
        # the senior year takes up the rest; nothing before or in the past moves
        assert day['race'] == day['morning'] + 1
        assert day['senior'] == 1200 and day['memory'] == -30
        assert {sid for sid, *_ in moves} >= {'winsor', 'anticipates', 'race'}
        assert not {'stroll', 'carl', 'bull', 'tucker', 'junior'} & {sid for sid, *_ in moves}

    def test_a_calendar_that_keeps_its_anchors_is_left_alone(self):
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([
            ('a', 1, 'scene', 'continues', '', 'early June'),
            ('b', 30, 'scene', 'later', '', 'July'),
            ('c', 90, 'scene', 'later', '', 'autumn flavour in the air'),
        ])
        assert pin_month_anchors(items, placed)[1] == []

    def test_too_few_or_disagreeing_anchors_change_nothing(self):
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([('a', 1, 'scene', 'continues', '', 'May'),
                                    ('b', 9, 'scene', 'later', '', '')])
        assert pin_month_anchors(items, placed) == (placed, [], None)
        # Every anchor a month off from the one before: no calendar keeps most
        items, placed = self._book([
            (f's{i}', 1 + i, 'scene', 'later', '', month)
            for i, month in enumerate(['January', 'March', 'May', 'July', 'September'])])
        assert pin_month_anchors(items, placed)[1] == []

    def test_a_stated_gap_is_kept_when_its_run_moves(self):
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([
            ('a', 1, 'scene', 'continues', '', 'early June'),
            ('b', 20, 'scene', 'later', '', 'late June'),
            ('c', 30, 'scene', 'later', '', 'early August'),
            ('d', 33, 'scene', 'later', 'three days', ''),
            ('e', 120, 'scene', 'later', '', 'early October'),
        ])
        pinned, moves, _ = pin_month_anchors(items, placed)
        assert pinned['d'][0] - pinned['c'][0] == 3
        assert pinned['c'][0] > 30

    def test_a_first_run_never_moves_before_day_one(self):
        """Review of #350: the first run had no lower bound going back."""
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([
            ('a', 1, 'scene', 'continues', '', 'early in May'),
            ('b', 10, 'scene', 'later', '', 'August'),
            ('c', 40, 'scene', 'later', '', 'September'),
            ('d', 70, 'scene', 'later', '', 'October')])
        pinned, _moves, _ = pin_month_anchors(items, placed)
        assert min(d for d, _m, _b in pinned.values()) >= 1

    def test_a_blocked_move_back_is_not_a_year_forward(self):
        """Review of #350: a run a month past its window, with no room to go
        back, jumped most of a year forward."""
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([
            ('a', 1, 'scene', 'continues', '', 'early June'),
            ('b', 30, 'scene', 'later', '', 'early July'),
            ('c', 65, 'scene', 'later', '', 'early August'),
            ('d', 70, 'scene', 'later', '', 'early July')])
        pinned, moves, _ = pin_month_anchors(items, placed)
        assert pinned['d'][0] == 70 and not moves

    def test_a_near_flashback_moves_with_its_present(self):
        """Review of #350: a memory three weeks back stayed put while the
        present moved months away from it."""
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([
            ('stroll', 7, 'scene', 'continues', '', "Fall's here"),
            ('carl', 395, 'scene', 'later', '', 'one night in October'),
            ('tucker', 550, 'scene', 'later', '', 'In March'),
            ('junior', 730, 'summary', 'later', '', ''),
            ('anticipates', 840, 'scene', 'later', '', 'early in May'),
            ('recalled', 825, 'scene', 'earlier', 'two weeks', ''),
            ('freshman', 100, 'scene', 'earlier', '', ''),
            ('next', 850, 'scene', 'later', '', '')])
        pinned, _moves, _ = pin_month_anchors(items, placed)
        shift = pinned['anticipates'][0] - 840
        assert shift > 0
        assert pinned['recalled'][0] == 825 + shift
        assert pinned['freshman'][0] == 100

    def test_an_overshoot_does_not_make_later_scenes_flashbacks(self):
        """Review of #350: one scene far ahead made every later scene look
        like a flashback by its day, so none of them anchored; and the model's
        own step back must not set off a push a year long."""
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([
            ('a', 1, 'scene', 'continues', '', 'early September'),
            ('b', 420, 'scene', 'later', '', 'late October'),
            ('c', 60, 'scene', 'later', '', 'November'),
            ('d', 150, 'scene', 'later', '', 'early January')])
        pinned, moves, _ = pin_month_anchors(items, placed)
        assert pinned['c'][0] == 60
        assert pinned['d'][0] < 150 and 'd' in {m[0] for m in moves}

    def test_names_and_other_times_are_not_anchors(self):
        from storyforge.timeline import anchor_window
        assert anchor_window('Aunt May arrives') is None
        assert anchor_window('Miss June at tea') is None
        assert anchor_window('planning to marry next June') is None
        assert anchor_window('last spring') is None
        assert anchor_window('in May, with Aunt May')[2] == 'May'

    def test_the_fit_picks_the_middle_of_a_tie(self):
        """Review of #350: with every anchor kept, the lowest day of the
        year won; moves were then measured from an edge."""
        from storyforge.timeline import pin_month_anchors
        items, placed = self._book([('a', 10, 'scene', 'continues', '', 'May'),
                                    ('b', 40, 'scene', 'later', '', 'June')])
        _pinned, _moves, day_one = pin_month_anchors(items, placed)
        # Day 10 in mid-May and day 40 in mid-June: day 1 about May 5
        assert 118 <= day_one <= 132

    def test_the_pass_writes_pinned_days(self, project_dir, monkeypatch):
        import storyforge.timeline as tl
        _scenes(project_dir, [('a', '', ''), ('b', '', ''), ('c', '', ''), ('d', '', '')])
        tl.write_cues(project_dir, {
            'a': {'relation': 'later', 'anchor': 'early September'},
            'b': {'relation': 'later', 'anchor': 'late October'},
            'c': {'relation': 'later', 'anchor': 'In March'},
            'd': {'relation': 'later', 'anchor': 'early in May'}})
        monkeypatch.setattr(tl, '_invoke_assignment', lambda model: (
            lambda prompt, log_file, label:
                'CALENDAR:\na | 1 | scene | x\nb | 50 | scene | x\nc | 185 | scene | x\n'
                'd | 200 | scene | x\n'))
        tl.run_assignment(project_dir, 'm', os.path.join(project_dir, 'working', 'logs'), force=False)
        days = {k: int(v) for k, v in _column(project_dir, 'timeline_day').items()}
        assert days['a'] == 1 and days['b'] == 50 and days['c'] == 185
        assert 230 <= days['d'] <= 250


class TestSpikes:
    """F-072 (The Plastic Age): the model put the freshman exams on day 900,
    between scenes on days 180 and 270."""

    def _book(self, rows):
        """(id, day, mode, relation, gap) → items and placements."""
        items = [{'id': sid, 'cues': {'relation': rel, 'gap': gap}}
                 for sid, _day, _mode, rel, gap in rows]
        placed = {sid: (day, mode, '') for sid, day, mode, *_ in rows}
        return items, placed

    def test_the_freshman_exams_go_back_between_their_neighbours(self):
        from storyforge.timeline import repair_spikes
        items, placed = self._book([
            ('track', 230, 'summary', 'later', ''),
            ('sings', 180, 'summary', 'later', 'several months'),
            ('exams', 900, 'summary', 'later', 'some time after'),
            ('part', 270, 'scene', 'later', ''),
            ('summer', 275, 'summary', 'later', '')])
        repaired, moves = repair_spikes(items, placed)
        assert moves == [('exams', 900, 225)]
        assert repaired['sings'][0] == 180 and repaired['part'][0] == 270

    def test_a_stated_gap_places_the_run_and_its_run_moves_whole(self):
        from storyforge.timeline import repair_spikes
        items, placed = self._book([
            ('a', 10, 'scene', 'later', ''),
            ('b', 500, 'scene', 'later', 'three days'),
            ('c', 501, 'scene', 'later', 'the next morning'),
            ('d', 40, 'scene', 'later', '')])
        # b's "three days" is stated, so a and b are one run: nothing
        # before it to measure from; the repair needs a run on each side
        assert repair_spikes(items, placed)[1] == []
        items, placed = self._book([
            ('a', 10, 'scene', 'later', ''),
            ('b', 500, 'scene', 'later', 'some weeks'),
            ('c', 501, 'scene', 'later', 'the next morning'),
            ('d', 40, 'scene', 'later', '')])
        repaired, _moves = repair_spikes(items, placed)
        assert repaired['b'][0] == 25 and repaired['c'][0] == 26

    def test_what_is_not_a_spike_is_left_alone(self):
        from storyforge.timeline import repair_spikes
        for rows in (
            # Far behind both: maybe a flashback its cue missed
            [('a', 300, 'scene', 'later', ''), ('b', 5, 'scene', 'later', ''),
             ('c', 310, 'scene', 'later', '')],
            # Ahead of the scene before, not of the one after: a time jump
            [('a', 10, 'scene', 'later', ''), ('b', 400, 'scene', 'later', ''),
             ('c', 405, 'scene', 'later', '')],
            # Neighbours that disagree with each other
            [('a', 300, 'scene', 'later', ''), ('b', 900, 'scene', 'later', ''),
             ('c', 100, 'scene', 'later', '')],
            # Within SPIKE_DAYS
            [('a', 10, 'scene', 'later', ''), ('b', 35, 'scene', 'later', ''),
             ('c', 20, 'scene', 'later', '')],
            # The last run has no neighbour after it
            [('a', 10, 'scene', 'later', ''), ('b', 900, 'scene', 'later', '')],
        ):
            items, placed = self._book(rows)
            assert repair_spikes(items, placed)[1] == [], rows

    def test_frames_visions_and_flashbacks_are_not_neighbours(self):
        from storyforge.timeline import repair_spikes
        items, placed = self._book([
            ('a', 10, 'scene', 'later', ''),
            ('frame', 5000, 'frame', 'frame', ''),
            ('b', 900, 'scene', 'later', ''),
            ('memory', 870, 'scene', 'earlier', 'a month'),
            ('old', -2000, 'scene', 'continues', ''),
            ('c', 40, 'scene', 'later', '')])
        repaired, _moves = repair_spikes(items, placed)
        assert repaired['b'][0] == 25 and repaired['frame'][0] == 5000
        # The memory of the spike's own stretch moves with it; the memory
        # carried on into the distant past stays
        assert repaired['memory'][0] == 870 - 875 and repaired['old'][0] == -2000

    def test_review_of_352_cases_are_left_alone(self):
        from storyforge.timeline import repair_spikes
        for rows in (
            # A flash-forward its cue explains in years
            [('a', 180, 'scene', 'later', ''), ('b', 7300, 'scene', 'later', 'years later'),
             ('c', 270, 'scene', 'later', '')],
            # Wider than the room between its neighbours (900-1000 in 180-270)
            [('a', 180, 'scene', 'later', ''), ('b', 900, 'scene', 'later', ''),
             ('b2', 1000, 'scene', 'later', 'a hundred days'), ('c', 270, 'scene', 'later', '')],
            # Two spikes in a row
            [('a', 180, 'scene', 'later', ''), ('b', 900, 'scene', 'later', ''),
             ('c', 910, 'scene', 'later', ''), ('d', 270, 'scene', 'later', '')],
        ):
            items, placed = self._book(rows)
            assert repair_spikes(items, placed)[1] == [], rows

    def test_a_memory_of_ordinary_story_time_stays(self):
        """Review of #352: a flashback inside the spike that remembers day
        200, between its neighbours, was thrown back 675 days with it."""
        from storyforge.timeline import repair_spikes
        items, placed = self._book([
            ('a', 180, 'scene', 'later', ''),
            ('b', 900, 'scene', 'later', ''),
            ('memory', 200, 'scene', 'earlier', ''),
            ('c', 270, 'scene', 'later', '')])
        repaired, _moves = repair_spikes(items, placed)
        assert repaired['b'][0] == 225 and repaired['memory'][0] == 200

    def test_the_pass_puts_a_spike_back(self, project_dir, monkeypatch):
        import storyforge.timeline as tl
        _scenes(project_dir, [('a', '', ''), ('b', '', ''), ('c', '', '')])
        tl.write_cues(project_dir, {'a': {'relation': 'later'}, 'b': {'relation': 'later'},
                                    'c': {'relation': 'later'}})
        monkeypatch.setattr(tl, '_invoke_assignment', lambda model: (
            lambda prompt, log_file, label:
                'CALENDAR:\na | 180 | summary | x\nb | 900 | summary | x\nc | 270 | scene | x\n'))
        tl.run_assignment(project_dir, 'm', os.path.join(project_dir, 'working', 'logs'), force=False)
        assert _column(project_dir, 'timeline_day') == {'a': '180', 'b': '225', 'c': '270'}


class TestChecks:
    def _rows(self, *rows):
        return [{'id': sid, 'timeline_day': day, 'time_mode': mode, 'timeline_date': date}
                for sid, day, mode, date in rows]

    def test_consistent_book_has_no_findings(self):
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '1', 'scene', ''), ('b', '2', 'scene', ''),
                          ('c', '-1825', 'scene', ''), ('d', '-1825', 'scene', ''),
                          ('e', '3', 'scene', ''), ('f', '900', 'frame', ''))
        cues = {'b': {'relation': 'later', 'gap': 'the next morning'},
                'c': {'relation': 'earlier', 'gap': 'five years'},
                'd': {'relation': 'continues'}, 'e': {'relation': 'later'},
                'f': {'relation': 'frame'}}
        assert check_timeline(rows, cues) == []

    def test_present_backwards_without_flashback(self):
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '10', 'scene', ''), ('b', '3', 'scene', ''))
        found = check_timeline(rows, {'b': {'relation': 'later'}})
        assert [f['check'] for f in found] == ['present_backwards']

    def test_gap_mismatch(self):
        """Gatsby: "the next morning" on a scene the calendar put a week on."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '1', 'scene', ''), ('b', '8', 'scene', ''))
        found = check_timeline(rows, {'b': {'relation': 'later', 'gap': 'the next morning'}})
        assert [f['check'] for f in found] == ['gap_mismatch']

    def test_dates_and_weekdays_against_days(self):
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '30', 'scene', 'XXXX-07-04'), ('b', '31', 'scene', 'XXXX-07-08'),
                          ('c', '40', 'scene', ''), ('d', '44', 'scene', ''))
        cues = {'c': {'anchor': 'that Sunday'}, 'd': {'anchor': 'on Sunday'}}
        checks = [f['check'] for f in check_timeline(rows, cues)]
        assert checks == ['date_mismatch', 'weekday_mismatch']

    def test_derived_date_is_checked_against_the_days(self):
        """A derived (~) day-1 date checks later dates: Gatsby's dinner at
        about June 7 on day 1 and July 4 on day 3 contradict."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '1', 'scene', 'XXXX-06-07~'), ('b', '3', 'scene', 'XXXX-07-04~'))
        assert [f['check'] for f in check_timeline(rows, {})] == ['date_mismatch']

    def test_a_year_less_date_that_steps_back_says_so(self):
        """F-059: a Christmas Eve after a Christmas Day, with the year
        unstated, read as "364 day(s) after"; it is one day before."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('wakes', '1', 'scene', 'XXXX-12-25'),
                          ('fezziwig', '1', 'scene', 'XXXX-12-24'))
        found = check_timeline(rows, {})
        assert [f['check'] for f in found] == ['date_mismatch']
        message = found[0]['message']
        assert message.startswith('its date (24 December) is 1 day(s) before wakes\'s (25 December)')
        assert '364 day(s) after if the year turned' in message

    def test_a_year_less_date_across_new_year_reads_forward(self):
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '1', 'scene', 'XXXX-12-30'), ('b', '3', 'scene', 'XXXX-01-02'))
        assert check_timeline(rows, {}) == []

    def test_month_and_season_dates_are_checked_against_the_days(self):
        """The Plastic Age: junior year opened in September on day 730, and
        the prom "early in May" (XXXX-05) landed on day 840, about January.
        Month-only and season dates were never compared, so nothing said so."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('tucker', '550', 'scene', 'XXXX-03'),
                          ('prom', '840', 'scene', 'XXXX-05'))
        found = check_timeline(rows, {})
        assert [f['check'] for f in found] == ['date_mismatch']
        assert 'May' in found[0]['message'] and 'March' in found[0]['message']

    def test_a_season_the_days_contradict_is_found(self):
        """F-070: "early spring" coded autumn (XXXX-23) 90 days after a
        March scene."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('march', '550', 'scene', 'XXXX-03'),
                          ('poker', '640', 'scene', 'XXXX-23~'))
        assert [f['check'] for f in check_timeline(rows, {})] == ['date_mismatch']

    def test_month_and_season_dates_years_apart_still_agree(self):
        """With the year unstated a month recurs every year: October of the
        second year and May of the fourth fit the days between them."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '395', 'scene', 'XXXX-10'), ('b', '455', 'scene', 'XXXX-11'),
                          ('c', '550', 'scene', 'XXXX-03'), ('d', '965', 'scene', 'XXXX-21'),
                          ('e', '1335', 'scene', 'XXXX-05'),
                          ('f', '1369', 'scene', 'XXXX-06-20~'))
        assert check_timeline(rows, {}) == []

    def test_weekdays_far_apart_are_not_compared(self):
        """F-067 (The Plastic Age): a Thursday 884 days after a Saturday was
        flagged; over years the calendar is too rough for weekday math."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('game', '81', 'scene', ''), ('station', '965', 'scene', ''))
        cues = {'game': {'anchor': 'Saturday morning'}, 'station': {'anchor': 'Thursday'}}
        assert check_timeline(rows, cues) == []

    def test_a_weekday_of_another_day_is_not_the_scenes_own(self):
        """F-068 (The Plastic Age): the smoker's anchor named the game's
        "Saturday afternoon", "the day after to-morrow", and the smoker was
        taken for a Saturday."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('smoker', '80', 'scene', ''), ('fever', '81', 'scene', ''))
        cues = {'smoker': {'anchor': 'the big game "Saturday afternoon"; "day after to-morrow"'},
                'fever': {'anchor': 'Friday night'}}
        assert check_timeline(rows, cues) == []

    def test_weekdays_close_together_are_still_compared(self):
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '80', 'scene', ''), ('b', '80', 'scene', ''))
        cues = {'a': {'anchor': 'Saturday'}, 'b': {'anchor': 'Friday night'}}
        assert [f['check'] for f in check_timeline(rows, cues)] == ['weekday_mismatch']

    def test_a_flashback_may_move_on_through_the_past(self):
        """F-059: Carol's Stave II, each memory cued "earlier" but later than
        the memory before it, gave 3-4 flashback_not_earlier findings."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('night', '1', 'scene', ''), ('boyhood', '-18250', 'scene', ''),
                          ('fan', '-17885', 'scene', ''), ('fezziwig', '-14600', 'scene', ''),
                          ('christmas', '2', 'scene', ''))
        cues = {'boyhood': {'relation': 'earlier'}, 'fan': {'relation': 'earlier'},
                'fezziwig': {'relation': 'earlier'}, 'christmas': {'relation': 'later'}}
        assert check_timeline(rows, cues) == []

    def test_an_earlier_scene_that_leaves_the_flashback_is_found(self):
        """Review of #338: inside a flashback, an "earlier" scene placed at
        or after the present is still wrong."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '10', 'scene', ''), ('memory', '-1825', 'scene', ''),
                          ('more', '12', 'scene', ''))
        found = check_timeline(rows, {'memory': {'relation': 'earlier'},
                                      'more': {'relation': 'earlier'}})
        assert [f['check'] for f in found] == ['flashback_not_earlier']

    def test_a_flashback_that_does_not_go_back_is_found(self):
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '5', 'scene', ''), ('memory', '5', 'scene', ''))
        found = check_timeline(rows, {'memory': {'relation': 'earlier'}})
        assert [f['check'] for f in found] == ['flashback_not_earlier']

    def test_gap_after_a_flashback_counts_from_the_present(self):
        """Gatsby VIII: the Louisville memory, then "the next morning"."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('dawn', '77', 'scene', ''), ('louisville', '-1676', 'scene', ''),
                          ('next', '78', 'scene', ''))
        cues = {'louisville': {'relation': 'earlier', 'gap': 'five years'},
                'next': {'relation': 'later', 'gap': 'the next morning'}}
        assert check_timeline(rows, cues) == []

    def test_summary_gap_frame_and_year_wrap(self):
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '10', 'summary', ''), ('b', '71', 'scene', 'XXXX-12-30'),
                          ('f', '900', 'frame', ''), ('c', '74', 'scene', 'XXXX-01-02'))
        cues = {'b': {'relation': 'later', 'gap': 'the next morning'},
                'c': {'relation': 'earlier', 'gap': 'two years'}}
        assert check_timeline(rows, cues) == []

    def test_habitual_weekdays_are_not_anchors(self):
        """Gatsby's guest catalogue: "on Sunday mornings" is a habit."""
        from storyforge.timeline import check_timeline
        rows = self._rows(('a', '1', 'scene', ''), ('b', '3', 'summary', ''),
                          ('c', '9', 'scene', ''))
        cues = {'a': {'anchor': 'Friday'}, 'b': {'anchor': 'on Sunday mornings'},
                'c': {'anchor': 'Saturday and Sunday'}}
        assert check_timeline(rows, cues) == []

    def test_drift_check_skips_a_book_without_days(self, project_dir, monkeypatch):
        import storyforge.timeline as tl
        _scenes(project_dir, [('a', '', ''), ('b', '', '')])
        monkeypatch.setattr(tl, 'check_scenes', lambda *a: (_ for _ in ()).throw(AssertionError))
        assert tl.drift_check(project_dir, ['a']) == []

    def test_drift_check_never_raises(self, project_dir, monkeypatch):
        import storyforge.timeline as tl
        _scenes(project_dir, [('a', '1', 'scene')])

        def boom(*a):
            raise RuntimeError('API down')
        monkeypatch.setattr(tl, 'check_scenes', boom)
        assert tl.drift_check(project_dir, ['a']) == []


class TestFlashbacksAndCleanup:
    def test_frame_scenes_are_not_the_present(self):
        from storyforge.structural import assess_flashbacks
        scenes = {sid: {'seq': str(i), 'timeline_day': day, 'time_mode': mode, 'word_count': '100'}
                  for i, (sid, day, mode) in enumerate([
                      ('frame-open', '800', 'frame'), ('a', '1', 'scene'), ('b', '5', 'scene'),
                      ('louisville', '-1825', 'scene'), ('c', '6', 'scene')])}
        passages = assess_flashbacks(scenes, {})
        assert [p['scenes'] for p in passages] == [['louisville']]

    def test_cleanup_never_fills_from_a_flashback(self, project_dir):
        from storyforge.extract import cleanup_timeline
        _scenes(project_dir, [('a', '10', 'scene'), ('gap', '', ''), ('b', '12', 'scene'),
                              ('memory', '-1825', 'scene'), ('inside', '', ''),
                              ('memory2', '-1820', 'scene'), ('frame', '', 'frame')])
        fixes = cleanup_timeline(os.path.join(project_dir, 'reference'))
        assert [(f['scene_id'], f['new_value']) for f in fixes] == [('gap', '10')]


class TestVisions:
    """F-054: A Christmas Carol's Stave IV shows a future the story then
    averts. Placed on day 4 as if it were the present, it made Stave V's
    Christmas morning (day 2) read as a flashback: 6 timeline-order
    advisories and 2 timeline-check findings, all wrong. A vision is never
    the story's present."""

    # Christmas night, the future shown, waking "moments later"
    ROWS = [('night', '2', 'scene'), ('dead-man', '4', 'vision'),
            ('gravestone', '4', 'vision'), ('wakes', '2', 'scene'), ('salary', '3', 'scene')]

    def test_vision_is_a_relation_and_a_mode(self):
        from storyforge.timeline import parse_cues, TIME_MODES
        from storyforge.schema import VALID_TIME_MODES
        assert parse_cues('TIME_RELATION: vision (a future that may be)')['relation'] == 'vision'
        assert 'vision' in TIME_MODES and 'vision' in VALID_TIME_MODES

    def test_a_past_shown_in_a_vision_is_earlier(self):
        """First Carol run on this branch: the cue model marked all of Stave
        II (the Ghost of Christmas Past) as vision on day 1, losing every
        past day and the flashback gauge. The past is fixed; it stays earlier."""
        from storyforge.timeline import CUE_INSTRUCTIONS, build_assignment_prompt
        assert 'the past is always earlier, even when a spirit' in CUE_INSTRUCTIONS
        prompt = build_assignment_prompt([{'id': 'a', 'cues': {}}], None, None, [])
        assert 'The past is never a vision' in prompt

    def test_a_relation_in_the_mode_column_is_a_scene(self, tmp_path):
        """Second Carol run: the assignment answered "| -18250 | earlier |"
        for Stave II, and the fallback took the cue's "vision"."""
        from storyforge.timeline import assign_calendar
        items = [{'id': 'night', 'cues': {'relation': 'later'}},
                 {'id': 'boyhood', 'cues': {'relation': 'vision'}}]
        placed = assign_calendar(
            items, lambda *a: 'CALENDAR:\nnight | 1 | scene | x\nboyhood | -18250 | earlier | past\n',
            str(tmp_path))
        assert placed['boyhood'] == (-18250, 'scene', 'past')

    def test_later_in_the_mode_column_keeps_the_cue(self, tmp_path):
        """Review of #338: mapping "later" to scene would make a vision line
        that lost its mode the story's present."""
        from storyforge.timeline import assign_calendar
        items = [{'id': 'night', 'cues': {'relation': 'later'}},
                 {'id': 'future', 'cues': {'relation': 'vision'}}]
        placed = assign_calendar(
            items, lambda *a: 'CALENDAR:\nnight | 2 | scene | x\nfuture | 400 | later | a year on\n',
            str(tmp_path))
        assert placed['future'] == (400, 'vision', 'a year on')

    def test_walk_reads_the_scene_after_a_vision_against_the_viewer(self):
        from storyforge.timeline import walk
        cues = {'night': {'relation': 'later'}, 'dead-man': {'relation': 'vision'},
                'gravestone': {'relation': 'vision'}, 'wakes': {'relation': 'continues'}}
        assert walk(list(cues), cues) == {'night': 1, 'dead-man': None,
                                          'gravestone': None, 'wakes': 1}

    def test_check_does_not_treat_a_vision_as_the_present(self):
        from storyforge.timeline import check_timeline
        rows = [{'id': sid, 'timeline_day': day, 'time_mode': mode, 'timeline_date': ''}
                for sid, day, mode in self.ROWS]
        cues = {'dead-man': {'relation': 'vision'}, 'gravestone': {'relation': 'vision'},
                'wakes': {'relation': 'continues', 'gap': 'moments later'},
                'salary': {'relation': 'later', 'gap': 'the next morning'}}
        assert check_timeline(rows, cues) == []

    def test_validate_raises_no_flashback_after_a_vision(self):
        from storyforge.elaborate import _validate_timeline
        scenes = {sid: {'seq': str(i), 'timeline_day': day, 'time_mode': mode, 'pov': 'scrooge'}
                  for i, (sid, day, mode) in enumerate(self.ROWS)}
        checks = []
        _validate_timeline(scenes, checks)
        assert [c['message'] for c in checks if not c['passed']] == []

    def test_flashback_gauge_skips_visions(self):
        from storyforge.structural import assess_flashbacks
        scenes = {sid: {'seq': str(i), 'timeline_day': day, 'time_mode': mode, 'word_count': '100'}
                  for i, (sid, day, mode) in enumerate(self.ROWS)}
        assert assess_flashbacks(scenes, {}) == []

    def test_assignment_keeps_the_present_through_a_vision(self, tmp_path):
        from storyforge.timeline import assign_calendar
        items = [{'id': 'night', 'cues': {'relation': 'later'}},
                 {'id': 'future', 'cues': {'relation': 'vision'}},
                 {'id': 'lost-mode', 'cues': {'relation': 'vision'}},
                 {'id': 'wakes', 'cues': {'relation': 'continues'}}]
        prompts = []

        def invoke(prompt, log_file, label):
            prompts.append(prompt)
            return ('CALENDAR:\nnight | 2 | scene | x\nfuture | 400 | vision | a year on\n'
                    'lost-mode | 400 | the future\nwakes | 2 | scene | moments later\n')
        placed = assign_calendar(items, invoke, str(tmp_path))
        assert placed['future'] == (400, 'vision', 'a year on')
        # A line that lost its mode falls back on the cue, not on "scene"
        assert placed['lost-mode'][1] == 'vision'
        assert '- vision:' in prompts[0]

    def test_cleanup_never_fills_from_a_vision(self, project_dir):
        from storyforge.extract import cleanup_timeline
        _scenes(project_dir, [('a', '2', 'scene'), ('future', '400', 'vision'), ('gap', '', '')])
        fixes = cleanup_timeline(os.path.join(project_dir, 'reference'))
        assert [(f['scene_id'], f['new_value']) for f in fixes] == [('gap', '2')]

    def test_expansion_gaps_skip_visions(self, project_dir):
        """Review of #338: a vision 400 days out read as a 398-day gap."""
        from storyforge.extract import analyze_expansion_opportunities
        _scenes(project_dir, [('a', '1', 'scene'), ('future', '400', 'vision'), ('b', '2', 'scene')])
        opps = analyze_expansion_opportunities(os.path.join(project_dir, 'reference'))
        assert [o for o in opps if o['type'] == 'timeline_gap'] == []
