"""Source ranges: adapting part of a source (`range:` on a `source.projects`
entry). The whole source is still imported; the range decides which source
scenes the map, spine, architecture and briefs prompts, validate's coverage
and source fidelity work from. Without a range everything is what main
produced before ranges (the snapshot test at the bottom)."""

import json
import os
import shutil

import pytest

from storyforge import common, prompts_source, source, source_fidelity as sf

from source_helpers import (
    YAML, _write, import_source, make_adaptation, snapshot_outputs,
)

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The tiny source's chapters: 1 holds the first two scenes
CHAPTER_MAP = ('chapter|title|heading|part|scenes\n'
               '1|Book I|none|1|gods-debate;minerva-visits\n'
               '2|Book II|none|2|assembly-called\n'
               '3|Book III|none|3|ship-sails\n')

RANGED_YAML = """project:
  title: "Telemachus"
source:
  projects:
    - slug: odyssey
      path: ../odyssey
      range: {range}
  name_map: reference/names.csv
  mode: {mode}
"""


@pytest.fixture(autouse=True)
def _fresh_context():
    common.clear_shared_context_cache()
    yield
    common.clear_shared_context_cache()


def _set_range(proj, rng, mode='faithful'):
    _write(proj, {'storyforge.yaml': RANGED_YAML.format(range=rng, mode=mode)})


def _ranged(tmp_path, rng='chapters 1-2', mode='faithful'):
    proj = make_adaptation(tmp_path)
    _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': CHAPTER_MAP})
    _set_range(proj, rng, mode)
    import_source(proj)
    return proj


@pytest.fixture
def ranged(tmp_path):
    """Adapting chapters 1-2: gods-debate, minerva-visits, assembly-called
    (ship-sails, chapter 3, is outside)."""
    return _ranged(tmp_path)


def _map(proj, rows, scenes=('olympus-council-meets', 'athena-at-the-door')):
    _write(proj, {
        'reference/scenes.csv': 'id|seq|title\n' + ''.join(
            f'{s}|{n}|{s}\n' for n, s in enumerate(scenes, 1)),
        'reference/source-map.csv': 'scene_id|source_scenes|treatment|note\n' + rows,
    })


# ----------------------------------------------------------------------------
# The `range:` value
# ----------------------------------------------------------------------------

class TestRangeConfig:
    @pytest.mark.parametrize('text, kind, first, last, described', [
        ('chapters 1-4', 'chapters', '1', '4', 'chapters 1-4'),
        ('chapters 01 - 4', 'chapters', '1', '4', 'chapters 1-4'),
        ('chapter 3', 'chapters', '3', '3', 'chapter 3'),
        ('chapters 3', 'chapters', '3', '3', 'chapter 3'),
        ('scenes gods-debate..ship-sails', 'scenes', 'gods-debate', 'ship-sails',
         'scenes gods-debate..ship-sails'),
        ('scenes a .. b', 'scenes', 'a', 'b', 'scenes a..b'),
        ('scene ship-sails', 'scenes', 'ship-sails', 'ship-sails', 'scene ship-sails'),
    ])
    def test_parses(self, text, kind, first, last, described):
        rng = source.parse_range('odyssey', text)
        assert (rng.kind, rng.first, rng.last) == (kind, first, last)
        assert rng.describe() == described

    def test_read_from_yaml_with_comment(self, tmp_path):
        _write(tmp_path, {'storyforge.yaml': RANGED_YAML.format(
            range='chapters 1-4   # Books I-IV', mode='faithful')})
        cfg = source.read_config(str(tmp_path))
        assert cfg.project('odyssey').range == source.SourceRange('chapters', '1', '4')

    def test_no_range_is_none(self, tmp_path):
        _write(tmp_path, {'storyforge.yaml': YAML.format(extra='')})
        assert source.read_config(str(tmp_path)).project('odyssey').range is None

    @pytest.mark.parametrize('text, message', [
        ('chapters 4-1', 'inverted'),
        ('books 1-4', 'write `chapters 1-4`'),
        ('chapters 1-', 'write `chapters 1-4`'),
        ('chapters one-four', 'write `chapters 1-4`'),
        ('1-4', 'write `chapters 1-4`'),
        ('scenes a..', 'write `chapters 1-4`'),
        ('scenes a..b..c', 'write `chapters 1-4`'),
        ('scenes a b', 'write `chapters 1-4`'),
        ('seq 1-24', 'write `chapters 1-4`'),
    ])
    def test_bad_range(self, tmp_path, text, message):
        _write(tmp_path, {'storyforge.yaml': RANGED_YAML.format(range=text, mode='faithful')})
        with pytest.raises(source.SourceError, match=message):
            source.read_config(str(tmp_path))

    def test_empty_range_is_an_error(self, tmp_path):
        """`range:` with nothing after it (or a nested block under it) is not
        silently the whole source."""
        _write(tmp_path, {'storyforge.yaml': (
            'source:\n  projects:\n    - slug: odyssey\n      path: ../odyssey\n'
            '      range:\n        from: 1\n        to: 4\n')})
        with pytest.raises(source.SourceError, match='empty `range:`'):
            source.read_config(str(tmp_path))

    def test_type_checks_itself(self):
        with pytest.raises(source.SourceError, match='inverted'):
            source.SourceRange('chapters', '5', '2')
        with pytest.raises(source.SourceError, match='range kind'):
            source.SourceRange('books', '1', '2')
        with pytest.raises(source.SourceError, match='whole numbers'):
            source.SourceRange('chapters', 'I', 'IV')


# ----------------------------------------------------------------------------
# Resolving it against the source
# ----------------------------------------------------------------------------

class TestResolve:
    def test_chapters(self, ranged):
        cfg = source.read_config(ranged)
        assert source.adapted_ids(ranged, cfg, 'odyssey') == [
            'gods-debate', 'minerva-visits', 'assembly-called']
        assert source.spans(ranged, cfg) == {
            'odyssey': frozenset({'gods-debate', 'minerva-visits', 'assembly-called'})}

    def test_scenes(self, tmp_path):
        proj = _ranged(tmp_path, 'scenes minerva-visits..assembly-called')
        cfg = source.read_config(proj)
        assert [s['id'] for s in source.adapted_scenes(proj, cfg, 'odyssey')] == [
            'minerva-visits', 'assembly-called']

    def test_no_range_is_everything(self, tmp_path):
        proj = make_adaptation(tmp_path)
        import_source(proj)
        cfg = source.read_config(proj)
        assert source.adapted_ids(proj, cfg, 'odyssey') is None
        assert len(source.adapted_scenes(proj, cfg, 'odyssey')) == 4
        assert source.spans(proj, cfg) == {'odyssey': None}

    @pytest.mark.parametrize('rng, chapter_map, message', [
        ('scenes no-such..ship-sails', CHAPTER_MAP, 'no-such is not a scene'),
        ('scenes gods-debate..nope', CHAPTER_MAP, 'nope is not a scene'),
        ('scenes ship-sails..gods-debate', CHAPTER_MAP, 'is inverted'),
        ('chapters 2-5', CHAPTER_MAP, 'has no chapter 4, 5'),
        ('chapters 1-2', None, 'has none'),
        ('chapters 1', 'chapter|title|scenes\n1|I|gods-debate;ghost\n', 'not in the source'),
        ('chapters 1', 'chapter|title|scenes\n1|I|\n2|II|ship-sails\n', 'is empty'),
        ('chapters 1', 'chapter|title|scenes\n1|I|gods-debate\n1|I again|ship-sails\n',
         'chapter 1 twice'),
        ('chapters 1', 'chapter|title|scenes\n1|I|gods-debate;assembly-called\n'
                       '2|II|minerva-visits\n', 'continuous run'),
        ('chapters 1', 'chapter|title\n1|I\n', '`chapter` and `scenes` columns'),
    ])
    def test_unresolvable_range_stops_the_import(self, tmp_path, rng, chapter_map, message):
        proj = make_adaptation(tmp_path)
        if chapter_map is not None:
            _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': chapter_map})
        _set_range(proj, rng)
        with pytest.raises(source.SourceError, match=message):
            import_source(proj)
        assert not os.path.exists(source.source_dir(proj, 'odyssey'))   # nothing written

    def test_chapter_map_imported_only_for_a_chapters_range(self, tmp_path):
        proj = _ranged(tmp_path)
        assert os.path.isfile(os.path.join(source.source_dir(proj, 'odyssey'),
                                           source.CHAPTER_MAP))
        _set_range(proj, 'scenes gods-debate..assembly-called')
        import_source(proj)
        assert not os.path.exists(os.path.join(source.source_dir(proj, 'odyssey'),
                                               source.CHAPTER_MAP))

    def test_chapter_map_gone_from_the_import_is_said(self, ranged):
        os.remove(os.path.join(source.source_dir(ranged, 'odyssey'), source.CHAPTER_MAP))
        with pytest.raises(source.SourceError, match='re-run `storyforge source import`'):
            source.adapted_ids(ranged, source.read_config(ranged), 'odyssey')

    def test_outside_range(self):
        spans = {'odyssey': frozenset({'a'}), 'iliad': None}
        assert source.outside_range(('odyssey', 'b'), spans)
        assert not source.outside_range(('odyssey', 'a'), spans)
        assert not source.outside_range(('iliad', 'b'), spans)


# ----------------------------------------------------------------------------
# The source bible
# ----------------------------------------------------------------------------

def _bible(proj):
    with open(os.path.join(source.source_dir(proj, 'odyssey'), source.SOURCE_BIBLE),
              encoding='utf-8') as f:
        return f.read()


class TestBible:
    def test_marks_the_span_and_keeps_the_rest_as_context(self, tmp_path):
        proj = _ranged(tmp_path, 'scenes minerva-visits..assembly-called')
        bible = _bible(proj)
        assert ('Adapted span: scenes minerva-visits..assembly-called (2 of the source\'s 4 '
                'scenes, `minerva-visits` to `assembly-called`)') in bible
        before = bible.index('### Before the adapted span (1 scenes)')
        span = bible.index('### The adapted span (2 scenes)')
        after = bible.index('### After the adapted span (1 scenes)')
        assert before < bible.index('(`gods-debate`;') < span < bible.index('(`minerva-visits`;')
        assert after < bible.index('(`ship-sails`;')
        # Context scenes keep their one line, without outcome or value
        events = bible[:bible.index('## Cast')]
        assert events.count('Outcome:') == 2
        assert 'Zeus and Athena debate the return of Odysseus' in events   # summary kept
        assert 'Value: homecoming' not in events
        assert 'Value: authority -/+' in events

    def test_cast_counts_within_the_span(self, tmp_path):
        proj = _ranged(tmp_path, 'scenes minerva-visits..assembly-called')
        bible = _bible(proj)
        assert '## Cast (5 characters; POV and on-stage counts are within the adapted span)' in bible
        assert '**Telemachus** (`telemachus`): protagonist, POV in 2, on stage in 2' in bible
        assert '**Zeus** (`zeus`): supporting. Also' in bible      # on stage only outside
        # Threads and the timeline stay whole-source
        assert 'opens in `gods-debate`' in bible
        assert '- Day 3: `ship-sails`' in bible

    def test_no_before_heading_when_the_span_starts_the_source(self, ranged):
        bible = _bible(ranged)
        assert '### Before the adapted span' not in bible
        assert '### The adapted span (3 scenes)' in bible

    @pytest.mark.parametrize('new', ['chapters 1-3', None])
    def test_a_bible_built_for_another_range_stops_prompts(self, ranged, new):
        if new:
            _set_range(ranged, new)
        else:
            _write(ranged, {'storyforge.yaml': YAML.format(extra='  mode: faithful')})
        cfg = source.read_config(ranged)
        with pytest.raises(source.SourceError, match='imported for chapters 1-2, but'):
            source.require_imported(ranged, cfg)
        with pytest.raises(source.SourceError, match='re-run `storyforge source import`'):
            prompts_source.map_section(ranged)
        import_source(ranged)
        source.require_imported(ranged, cfg)

    def test_a_whole_source_bible_with_a_range_added_stops(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': CHAPTER_MAP})
        import_source(proj)
        _set_range(proj, 'chapters 1-2')
        with pytest.raises(source.SourceError, match='imported for the whole source'):
            source.require_imported(proj, source.read_config(proj))


# ----------------------------------------------------------------------------
# The prompt sections
# ----------------------------------------------------------------------------

class TestPrompts:
    def test_map_lists_only_the_span(self, ranged):
        p = prompts_source.map_section(ranged)
        assert '### Source scenes: odyssey (3 of 4: chapters 1-2)' in p
        for sid in ('gods-debate', 'minerva-visits', 'assembly-called'):
            assert f'|{sid}|' in p
        assert '|ship-sails|' not in p
        assert 'adapts only part of `odyssey` (chapters 1-2)' in p
        assert 'give them no row, adapted or cut' in p

    def test_spine_shows_the_span_not_the_source_spine(self, ranged):
        _write(ranged, {'reference/source/odyssey/spine.csv':
                        'id|seq|title|summary\nwhole-book|1|Home|Odysseus comes home\n'})
        p = prompts_source.spine_section(ranged)
        assert '### The adapted span (odyssey: chapters 1-2, 3 of 4 scenes)' in p
        assert '3|assembly-called|The Assembly|' in p
        assert 'ship-sails' not in p
        assert 'whole-book' not in p and 'own spine covers the whole source' in p

    def test_architecture_counts_the_span(self, tmp_path):
        proj = _ranged(tmp_path, 'scenes minerva-visits..assembly-called')
        p = prompts_source.architecture_section(proj)
        assert 'POV distribution below is the adapted span\'s' in p
        assert ('### odyssey: POV distribution (2 scenes, scenes '
                'minerva-visits..assembly-called)') in p
        assert 'Telemachus (`telemachus`): 2 scenes (100%)' in p
        assert 'Narrator' not in p        # POV only outside the span
        assert 'Athena (`athena`), supporting: on stage in 1' in p
        assert 'Zeus' not in p
        assert '3 of the source\'s characters are not on stage in the adapted span' in p

    def test_briefs_name_an_out_of_range_scene(self, ranged, capsys):
        _map(ranged, 'olympus-council-meets|gods-debate;ship-sails|compress|\n'
                     'athena-at-the-door|minerva-visits|dramatize|\n')
        p = prompts_source.briefs_section(ranged, None)
        assert ('#### Source scene ship-sails: outside the adapted range (chapters 1-2), '
                'so not shown') in p
        assert '#### Source scene odyssey:gods-debate' in p
        assert '<source-prose scene="ship-sails">' not in p
        assert 'outside the adapted range, not shown (run validate): ' \
               'olympus-council-meets (ship-sails)' in capsys.readouterr().out

    def test_shared_context_carries_the_span_bible(self, ranged):
        blocks = common.build_shared_context(ranged, 'claude-opus-5-5')
        bible = [b for b in blocks if b['text'].startswith('=== Source Bible (odyssey) ===')]
        assert len(bible) == 1 and 'Adapted span: chapters 1-2' in bible[0]['text']


# ----------------------------------------------------------------------------
# Coverage
# ----------------------------------------------------------------------------

def _coverage(proj):
    return source.check_coverage(proj, source.read_config(proj))


class TestCoverage:
    @pytest.mark.parametrize('mode', ['faithful', 'free'])
    def test_only_the_span_needs_accounting_for(self, tmp_path, mode):
        proj = _ranged(tmp_path, mode=mode)
        _map(proj, 'olympus-council-meets|gods-debate|dramatize|\n'
                   'athena-at-the-door|minerva-visits;assembly-called|compress|\n')
        result = _coverage(proj)
        assert result['findings'] == []
        assert result['lines'] == ['Source odyssey: 3 of 4 scenes adapted (chapters 1-2), '
                                   '3 mapped, 2 compressed, 0 cut']

    @pytest.mark.parametrize('mode, severity', [('faithful', 'blocking'), ('free', 'advisory')])
    def test_a_span_scene_left_out_takes_the_modes_severity(self, tmp_path, mode, severity):
        proj = _ranged(tmp_path, mode=mode)
        _map(proj, 'olympus-council-meets|gods-debate|dramatize|\n'
                   'athena-at-the-door|minerva-visits|dramatize|\n')
        result = _coverage(proj)
        assert [(f['severity'], f['message']) for f in result['findings']] == [
            (severity, 'source scene odyssey:assembly-called is not in the source map '
                       '(adapt it, or cut it with a reason)')]
        assert result['lines'][0].endswith('1 unaccounted for')

    @pytest.mark.parametrize('mode', ['faithful', 'free'])
    def test_adapting_a_scene_outside_the_range_blocks(self, tmp_path, mode):
        proj = _ranged(tmp_path, mode=mode)
        _map(proj, 'olympus-council-meets|gods-debate;minerva-visits;assembly-called|compress|\n'
                   'athena-at-the-door|ship-sails|dramatize|\n')
        found = [(f['severity'], f['scene_id'], f['message']) for f in _coverage(proj)['findings']]
        assert found == [('blocking', 'athena-at-the-door',
                          'source scene ship-sails is outside the adapted range (odyssey: '
                          'chapters 1-2); widen `range` in storyforge.yaml or adapt a scene '
                          'inside it')]

    def test_cutting_a_scene_outside_the_range_is_advisory(self, ranged):
        _map(ranged, 'olympus-council-meets|gods-debate;minerva-visits;assembly-called|compress|\n'
                     'athena-at-the-door||invent|\n'
                     '|ship-sails|cut|later book\n')
        found = [(f['severity'], f['message']) for f in _coverage(ranged)['findings']]
        assert found == [('advisory', 'source scene ship-sails is outside the adapted range '
                                      '(odyssey: chapters 1-2), so it needs no cut row')]

    def test_an_unresolvable_range_blocks_and_is_not_counted(self, ranged):
        _map(ranged, 'olympus-council-meets|gods-debate|dramatize|\n'
                     'athena-at-the-door||invent|\n')
        os.remove(os.path.join(source.source_dir(ranged, 'odyssey'), source.CHAPTER_MAP))
        result = _coverage(ranged)
        assert any(f['severity'] == 'blocking' and 'chapter-map.csv' in f['message']
                   for f in result['findings'])
        assert result['lines'] == ['Source odyssey: coverage not checked (its range can\'t '
                                   'be resolved; see the finding)']
        assert not any('not in the source map' in f['message'] for f in result['findings'])

    def test_status_shows_the_range(self, ranged, monkeypatch, capsys):
        from storyforge import cmd_source
        monkeypatch.chdir(ranged)
        monkeypatch.setattr(cmd_source, 'detect_project_root', lambda: ranged)
        cmd_source.main(['status'])
        assert 'Source odyssey: ../odyssey (imported), adapting chapters 1-2' in \
            capsys.readouterr().out


# ----------------------------------------------------------------------------
# Source fidelity and the revise hook
# ----------------------------------------------------------------------------

class TestFidelity:
    @pytest.fixture
    def mapped(self, ranged):
        _map(ranged, 'olympus-council-meets|gods-debate|dramatize|\n'
                     'athena-at-the-door|minerva-visits;ship-sails|compress|\n')
        _write(ranged, {'reference/scene-briefs.csv': (
            'id|goal|outcome\n'
            'olympus-council-meets|Athena wants Odysseus freed|yes\n'
            'athena-at-the-door|Athena wants to rouse him|yes\n')})
        return ranged

    def _plan(self, proj, sid):
        cfg = source.read_config(proj)
        rows = source.map_rows_by_scene(source.read_source_map(proj))
        return sf.plan_scene(proj, sid, 'brief', PLUGIN, cfg, rows, '')

    def test_in_range_scene_is_checked(self, mapped):
        plan = self._plan(mapped, 'olympus-council-meets')
        assert plan.prompt and 'odyssey:gods-debate' in plan.prompt

    def test_out_of_range_scene_is_broken_not_scored(self, mapped):
        plan = self._plan(mapped, 'athena-at-the-door')
        assert plan.broken and not plan.prompt
        assert plan.skip == ('its source scenes odyssey:ship-sails are outside the adapted '
                             'range (run validate)')

    def test_run_reports_it_failed_without_a_call(self, mapped, tmp_path):
        results, skipped, failed = sf.run(
            mapped, ['athena-at-the-door'], 'brief', plugin_dir=PLUGIN,
            out_dir=str(tmp_path / 'out'), log_dir=str(tmp_path / 'logs'), model='m')
        assert results == [] and skipped == {}
        assert 'outside the adapted range' in failed['athena-at-the-door']

    def test_revise_fix_refuses_an_out_of_range_scene(self, mapped):
        from storyforge import cmd_revise
        ctx = cmd_revise._SourceFixContext(mapped)
        why = cmd_revise._source_drift_fix(mapped, 'athena-at-the-door', {}, {}, {}, None,
                                           ['brief goal: drifted'], ctx)
        assert why == ('its source scenes odyssey:ship-sails are outside the adapted range '
                       '(run validate)')
        ok = cmd_revise._source_drift_fix(mapped, 'olympus-council-meets', {}, {}, {}, None,
                                          ['brief goal: drifted'], ctx)
        assert isinstance(ok, tuple)


# ----------------------------------------------------------------------------
# Without a range: what main produced before ranges
# ----------------------------------------------------------------------------

class TestNoRangeIsUnchanged:
    def test_byte_identical_to_main(self, tmp_path):
        """Generated by `snapshot_outputs` on main's package before ranges
        (the import's files and bible, the four prompt sections, coverage and
        a source-fidelity prompt). A deliberate change regenerates it."""
        golden = os.path.join(PLUGIN, 'tests', 'fixtures', 'golden-prompts',
                              'source-no-range.json')
        with open(golden, encoding='utf-8') as f:
            expected = json.load(f)
        assert snapshot_outputs(tmp_path, PLUGIN) == expected

    def test_import_copies_no_chapter_map(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': CHAPTER_MAP})
        result = import_source(proj)
        assert source.CHAPTER_MAP not in result.files
        assert source.SPAN_PREFIX not in _bible(proj)
