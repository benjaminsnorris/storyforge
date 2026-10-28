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
        assert 'b|timeline_day|5|2|next' in proposed and 'c|time_mode||frame|' in proposed
        assert result['assigned'] == 0 and result['proposed'] == 4

        tl.run_assignment(project_dir, 'm', logs, force=True)
        assert _column(project_dir, 'timeline_day') == {'a': '1', 'b': '2', 'c': '800'}
        assert _column(project_dir, 'time_mode')['c'] == 'frame'
        # A clean run leaves no stale proposal behind
        assert not os.path.exists(os.path.join(project_dir, tl.PROPOSED_FILE))

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
