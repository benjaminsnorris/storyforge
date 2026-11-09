"""Source ranges: adapting part of a source (`range:` on a `source.projects`
entry). The whole source is still imported; the range decides which source
scenes the map, spine, architecture and briefs prompts, validate's coverage
and source fidelity work from. Without a range everything is what the code
produced before source ranges were added in #517 (the snapshot test at the
bottom)."""

import json
import os
import shutil

import pytest

from storyforge import common, prompts_source, source, source_fidelity as sf

from source_helpers import (
    SOURCE_FILES, YAML, _write, import_source, make_adaptation, snapshot_outputs,
    snapshot_outputs_multi,
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
        ('scenes a..', 'is not a scene id'),
        ('scenes a..b..c', 'is not a scene id'),
        ('scenes a...c', 'is not a scene id'),
        ('scenes Gods-Debate', 'is not a scene id'),
        ('chapters ²', 'write `chapters 1-4`'),
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

    @pytest.mark.parametrize('text', ['chapters 1-4', 'chapter 3', 'scenes a..b', 'scene a'])
    def test_describe_round_trips(self, text):
        """TD-1: check_bible_span compares describe() strings."""
        rng = source.parse_range('odyssey', text)
        assert source.parse_range('odyssey', rng.describe()) == rng

    def test_type_holds_its_canonical_form(self):
        """TD-1: a directly built range is the same value parse_range gives."""
        assert source.SourceRange('chapters', '01', '004') == source.parse_range(
            'odyssey', 'chapters 1-4')
        assert source.SourceRange('chapters', '01', '3').describe() == 'chapters 1-3'
        for bad in (('scenes', 'a b', 'c'), ('scenes', 'a..b', 'c'), ('scenes', ' ', 'c'),
                    ('chapters', '\u00b2', '3'), ('chapters', 1, 3)):
            with pytest.raises(source.SourceError):
                source.SourceRange(*bad)

    @pytest.mark.parametrize('entry, message', [
        ('      ranges: chapters 1-4\n', 'no key `ranges`'),
        ('      chapters: 1-4\n', 'no key `chapters`'),
        ('      range : chapters 1-4\n', "can't read 'range : chapters 1-4'"),
        ('      range: chapters 1-4\n      range: chapters 9-12\n', '`range` twice'),
        ('  range: chapters 1-4\n', 'the `source:` block has no key `range`'),
    ])
    def test_a_misplaced_or_misspelled_range_is_refused(self, tmp_path, entry, message):
        """SF-1/SF-2: a range the parser can't attribute is never silently
        the whole source."""
        _write(tmp_path, {'storyforge.yaml': (
            'source:\n  projects:\n    - slug: odyssey\n      path: ../odyssey\n' + entry)})
        with pytest.raises(source.SourceError, match=message):
            source.read_config(str(tmp_path))

    def test_projects_items_at_the_block_indent_still_read(self, tmp_path):
        _write(tmp_path, {'storyforge.yaml': (
            'source:\n  projects:\n  - slug: odyssey\n    path: ../odyssey\n'
            '    range: chapter 2\n  mode: free\n')})
        cfg = source.read_config(str(tmp_path))
        assert cfg.project('odyssey').range.describe() == 'chapter 2' and cfg.mode == 'free'

    def test_quoted_range(self, tmp_path):
        _write(tmp_path, {'storyforge.yaml': RANGED_YAML.format(range='"chapters 1-2"',
                                                                mode='faithful')})
        assert source.read_config(str(tmp_path)).project('odyssey').range.describe() == \
            'chapters 1-2'

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
        ('chapters 1-2', 'chapter|title|scenes\n1|I|gods-debate;minerva-visits\n'
                         '2|II|minerva-visits\n', 'lists minerva-visits twice'),
        ('chapters 1-2', 'chapter|title|scenes\n', 'has no chapter 1, 2'),
        ('chapters 1-2', 'chapter|title|scenes\n1|I|gods-debate\nP|Interlude|minerva-visits\n'
                         '2|II|assembly-called\n',
         "skips minerva-visits.*rows a range can't name \\(no chapter number\\): P"),
        ('scene gods-debate-ship-sails', CHAPTER_MAP, 'written `first-id..last-id`'),
    ])
    def test_unresolvable_range_stops_the_import(self, tmp_path, rng, chapter_map, message):
        """(also T-7: a scene listed twice, a header-only map, an unnumbered row)"""
        proj = make_adaptation(tmp_path)
        if chapter_map is not None:
            _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': chapter_map})
        _set_range(proj, rng)
        with pytest.raises(source.SourceError, match=message):
            import_source(proj)
        assert not os.path.exists(source.source_dir(proj, 'odyssey'))   # nothing written

    def test_unnumbered_rows_outside_the_range_are_fine(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': (
            'chapter|title|scenes\nP|Prologue|gods-debate\n1|I|minerva-visits;assembly-called\n'
            '2|II|ship-sails\n')})
        _set_range(proj, 'chapter 1')
        import_source(proj)
        assert source.adapted_ids(proj, source.read_config(proj), 'odyssey') == [
            'minerva-visits', 'assembly-called']

    def test_an_inactive_source_scene_inside_the_chapters_is_in_the_span(self, tmp_path):
        """CR-2: a chapter map lists active scenes only; a cut scene between
        two of them doesn't break the run."""
        proj = make_adaptation(tmp_path)
        scenes = SOURCE_FILES['reference/scenes.csv'].replace(
            'id|seq|title|summary|pov|location|timeline_day\n',
            'id|seq|title|summary|pov|location|timeline_day|status\n')
        lines = scenes.rstrip('\n').split('\n')
        lines = [lines[0]] + [l + ('|cut' if l.startswith('minerva-visits') else '|drafted')
                              for l in lines[1:]]
        _write(str(tmp_path / 'odyssey'), {
            'reference/scenes.csv': '\n'.join(lines) + '\n',
            'reference/chapter-map.csv': 'chapter|title|scenes\n1|I|gods-debate;assembly-called\n'
                                         '2|II|ship-sails\n'})
        _set_range(proj, 'chapter 1')
        import_source(proj)
        assert source.adapted_ids(proj, source.read_config(proj), 'odyssey') == [
            'gods-debate', 'minerva-visits', 'assembly-called']

    def test_chapter_map_imported_only_for_a_chapters_range(self, tmp_path):
        proj = _ranged(tmp_path)
        assert os.path.isfile(os.path.join(source.source_dir(proj, 'odyssey'),
                                           source.CHAPTER_MAP))
        _set_range(proj, 'scenes gods-debate..assembly-called')
        import_source(proj)
        assert not os.path.exists(os.path.join(source.source_dir(proj, 'odyssey'),
                                               source.CHAPTER_MAP))

    def test_chapter_map_gone_from_the_import_is_said(self, ranged):
        """SF-5: require_imported resolves the range, so every up-front check
        (elaborate, score, revise) stops before any spend."""
        os.remove(os.path.join(source.source_dir(ranged, 'odyssey'), source.CHAPTER_MAP))
        cfg = source.read_config(ranged)
        with pytest.raises(source.SourceError, match='re-run `storyforge source import`'):
            source.adapted_ids(ranged, cfg, 'odyssey')
        with pytest.raises(source.SourceError, match='chapter-map.csv'):
            source.require_imported(ranged, cfg)

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

    def test_a_longer_range_does_not_match_a_shorter_ones_bible(self, tmp_path):
        """T-7: the span line is matched up to ` (`, so `scenes a..b` never
        satisfies `scenes a..bc`."""
        proj = _ranged(tmp_path, 'scenes gods-debate..minerva-visits')
        path = os.path.join(source.source_dir(proj, 'odyssey'), source.SOURCE_BIBLE)
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace('gods-debate..minerva-visits (',
                                 'gods-debate..minerva-visit ('))
        with pytest.raises(source.SourceError, match='imported for scenes gods-debate..'
                                                     'minerva-visit,'):
            source.require_imported(proj, source.read_config(proj))

    def test_an_unreadable_bible_is_said(self, ranged):
        path = os.path.join(source.source_dir(ranged, 'odyssey'), source.SOURCE_BIBLE)
        with open(path, 'wb') as f:
            f.write(b'\xff\xfe bad')
        with pytest.raises(source.SourceError, match='could not be read'):
            source.require_imported(ranged, source.read_config(ranged))

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
        assert 'within the adapted span, for a source with a range' in p
        assert ('### odyssey: POV distribution (2 scenes, scenes '
                'minerva-visits..assembly-called)') in p
        assert 'Telemachus (`telemachus`): 2 scenes (100%)' in p
        assert 'Narrator' not in p        # POV only outside the span
        assert 'Athena (`athena`), supporting: on stage in 1' in p
        assert 'Zeus' not in p
        assert '3 of the source\'s characters are not on stage in the adapted span' in p

    def test_briefs_stop_on_an_out_of_range_scene(self, ranged):
        """SF-4: a brief written without its source would be wrong, so the
        briefs prompt refuses before any spend instead of warning on."""
        _map(ranged, 'olympus-council-meets|gods-debate;ship-sails|compress|\n'
                     'athena-at-the-door|minerva-visits|dramatize|\n')
        with pytest.raises(source.SourceError,
                           match=r'olympus-council-meets \(ship-sails: odyssey adapts '
                                 r'chapters 1-2\); widen `range`'):
            prompts_source.briefs_section(ranged, None)
        # Briefing only the other scene is fine
        p = prompts_source.briefs_section(ranged, ['athena-at-the-door'])
        assert '#### Source scene odyssey:minerva-visits' in p
        # #644's review C5: the model is told what to do, not the author
        assert "Write no dialogue, and never copy the translation's wording." in p
        assert '#644' not in p and 'by hand' not in p

    def test_header_says_only_part_is_adapted(self, ranged):
        p = prompts_source.map_section(ranged)
        assert ('Only part of the source is adapted (`odyssey`: chapters 1-2): "every source '
                'event" means every event in the adapted span.') in p

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
        assert result['lines'] == ['Source odyssey: coverage not checked (its import or '
                                   'range can\'t be used; see the finding)']
        assert not any('not in the source map' in f['message'] for f in result['findings'])

    @pytest.mark.parametrize('change', ['range', 'bible'])
    def test_an_import_for_another_range_blocks(self, ranged, change):
        """CR-1/SF-3: validate never says clean while every prompt refuses."""
        _map(ranged, 'olympus-council-meets|gods-debate;minerva-visits;assembly-called|compress|\n'
                     'athena-at-the-door|ship-sails|dramatize|\n')
        if change == 'range':
            _set_range(ranged, 'chapters 1-3')
            message = 'imported for chapters 1-2, but storyforge.yaml now adapts chapters 1-3'
        else:
            os.remove(os.path.join(source.source_dir(ranged, 'odyssey'), source.SOURCE_BIBLE))
            message = 'source-bible.md is missing'
        result = _coverage(ranged)
        assert [(f['severity'], message in f['message']) for f in result['findings']] == [
            ('blocking', True)]
        assert 'coverage not checked' in result['lines'][0]

    def test_validate_command_fails_an_out_of_range_row(self, ranged):
        """T-6: validate carries the finding and exits 1."""
        import subprocess
        import sys
        _map(ranged, 'olympus-council-meets|gods-debate;minerva-visits;assembly-called|compress|\n'
                     'athena-at-the-door|ship-sails|dramatize|\n')
        env = dict(os.environ, PYTHONPATH=os.path.join(PLUGIN, 'scripts', 'lib', 'python'))
        r = subprocess.run([sys.executable, '-m', 'storyforge', 'validate', '--no-schema'],
                           cwd=ranged, env=env, capture_output=True, text=True)
        assert 'source scene ship-sails is outside the adapted range' in r.stdout
        assert '3 of 4 scenes adapted (chapters 1-2)' in r.stdout
        assert r.returncode == 1

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

    def test_score_dry_run_names_it(self, mapped, monkeypatch, capsys):
        """T-5: `score --source-fidelity --dry-run` with a range."""
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: mapped)
        cmd_score.main(['--source-fidelity', 'briefs', '--dry-run'])
        out = capsys.readouterr().out
        assert 'Source fidelity (briefs): 1 of 2 scenes to check' in out
        assert ('ERROR: athena-at-the-door (its source scenes odyssey:ship-sails are outside '
                'the adapted range') in out

    def test_score_stops_on_an_unresolvable_range(self, mapped, monkeypatch, capsys):
        from storyforge import cmd_score
        monkeypatch.setattr(cmd_score, 'detect_project_root', lambda: mapped)
        os.remove(os.path.join(source.source_dir(mapped, 'odyssey'), source.CHAPTER_MAP))
        with pytest.raises(SystemExit) as e:
            cmd_score.main(['--source-fidelity', 'briefs', '--dry-run'])
        assert e.value.code == 1 and 'ERROR:' in capsys.readouterr().out

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
        # #513: the fix rewrites KEY_ACTIONS (never key_dialogue since #644),
        # which may quote a line: it gets the cast and keeps speaker labels,
        # adding one only from the text it has (P-2)
        from storyforge.speaker_labels import LABEL_KEEP, LABEL_RULE
        assert LABEL_KEEP in ok[0] and LABEL_RULE not in ok[0]
        assert '## Cast (characters.csv)' in ok[0]


# ----------------------------------------------------------------------------
# Without a range: what the code produced before source ranges (#517)
# ----------------------------------------------------------------------------

class TestNoRangeIsUnchanged:
    def test_byte_identical_to_pre_range_snapshot(self, tmp_path):
        """Generated by `snapshot_outputs` and `snapshot_outputs_multi` on the
        package as it was before source ranges (the import's files and bible,
        the four prompt sections, coverage and a source-fidelity prompt, for
        one source in faithful mode and two in free mode with slug:id refs).
        A deliberate change regenerates it (see source_helpers)."""
        golden = os.path.join(PLUGIN, 'tests', 'fixtures', 'golden-prompts',
                              'source-no-range.json')
        with open(golden, encoding='utf-8') as f:
            expected = json.load(f)
        (tmp_path / 'one').mkdir()
        (tmp_path / 'two').mkdir()
        got = {**snapshot_outputs(tmp_path / 'one', PLUGIN),
               **snapshot_outputs_multi(tmp_path / 'two', PLUGIN)}
        assert got == expected

    def test_import_copies_no_chapter_map(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': CHAPTER_MAP})
        result = import_source(proj)
        assert source.CHAPTER_MAP not in result.files
        assert source.SPAN_PREFIX not in _bible(proj)


# ----------------------------------------------------------------------------
# Two sources, one with a range (T-4)
# ----------------------------------------------------------------------------

TWO_YAML = """source:
  projects:
    - slug: odyssey
      path: ../odyssey
      range: chapter 1
    - slug: iliad
      path: ../iliad
  name_map: reference/names.csv
  mode: faithful
"""


@pytest.fixture
def two(tmp_path):
    proj = make_adaptation(tmp_path)
    _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': CHAPTER_MAP})
    _write(str(tmp_path / 'iliad'), SOURCE_FILES)
    _write(proj, {'storyforge.yaml': TWO_YAML})
    cfg = source.read_config(proj)
    for slug in cfg.slugs():
        source.import_source(proj, cfg, slug)
    return proj


class TestTwoSources:
    def test_the_range_touches_only_its_source(self, two):
        cfg = source.read_config(two)
        assert source.spans(two, cfg) == {
            'odyssey': frozenset({'gods-debate', 'minerva-visits'}), 'iliad': None}

    def test_coverage(self, two):
        _map(two, 'olympus-council-meets|odyssey:gods-debate;odyssey:minerva-visits|compress|\n'
                  'athena-at-the-door|iliad:gods-debate;iliad:minerva-visits;'
                  'iliad:assembly-called;iliad:ship-sails;odyssey:ship-sails|compress|\n')
        result = _coverage(two)
        assert result['lines'] == [
            'Source odyssey: 2 of 4 scenes adapted (chapter 1), 2 mapped, 2 compressed, 0 cut',
            'Source iliad: 4 scenes, 4 mapped, 4 compressed, 0 cut']
        assert [f['message'] for f in result['findings']] == [
            'source scene odyssey:ship-sails is outside the adapted range (odyssey: chapter '
            '1); widen `range` in storyforge.yaml or adapt a scene inside it']

    def test_an_unresolvable_range_leaves_the_other_source_counted(self, two):
        _map(two, 'olympus-council-meets|iliad:gods-debate;iliad:minerva-visits;'
                  'iliad:assembly-called;iliad:ship-sails|compress|\n'
                  'athena-at-the-door||invent|\n')
        os.remove(os.path.join(source.source_dir(two, 'odyssey'), source.CHAPTER_MAP))
        lines = _coverage(two)['lines']
        assert lines[0].startswith('Source odyssey: coverage not checked')
        assert lines[1] == 'Source iliad: 4 scenes, 4 mapped, 4 compressed, 0 cut'

    def test_map_and_architecture_label_each_source(self, two):
        m = prompts_source.map_section(two)
        assert '### Source scenes: odyssey (2 of 4: chapter 1)' in m
        assert '### Source scenes: iliad (4)' in m
        assert 'adapts only part of `odyssey` (chapter 1)' in m and 'part of `iliad`' not in m
        a = prompts_source.architecture_section(two)
        assert 'the source\'s (within the adapted span, for a source with a range)' in a
        assert '### odyssey: POV distribution (2 scenes, chapter 1)' in a
        assert '### iliad: POV distribution (4 scenes)' in a

    def test_briefs_with_slug_refs(self, two):
        _map(two, 'olympus-council-meets|odyssey:gods-debate;iliad:ship-sails|compress|\n'
                  'athena-at-the-door|odyssey:ship-sails|dramatize|\n')
        p = prompts_source.briefs_section(two, ['olympus-council-meets'])
        assert '#### Source scene iliad:ship-sails' in p
        with pytest.raises(source.SourceError, match='athena-at-the-door \\(odyssey:ship-sails'):
            prompts_source.briefs_section(two, None)



def _seed(proj):
    seeded, notes = source.seed_registries(proj, source.read_config(proj))
    return {sd.path: (sd.written, sd.available) for sd in seeded}, notes


def _ids(proj, name):
    with open(os.path.join(proj, 'reference', name)) as f:
        return [l.split('|')[0] for l in f.read().splitlines()[1:]]


class TestSeedRegistriesRange:
    """A ranged source seeds only the registry rows its adapted scenes use
    (Telemachy pilot: Books I-IV was seeded with the whole Odyssey's 195)."""

    def test_only_rows_the_range_uses(self, tmp_path):
        proj = _ranged(tmp_path, rng='chapters 2-3')   # assembly-called, ship-sails
        seeded, notes = _seed(proj)
        assert seeded == {'reference/characters.csv': (2, 5),
                          'reference/locations.csv': (2, 3)}
        assert notes == []
        assert sorted(_ids(proj, 'characters.csv')) == ['athena', 'telemachus']
        assert sorted(_ids(proj, 'locations.csv')) == ['harbor', 'ithaca-hall']

    def test_characters_only_and_pov_only_count(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {
            'reference/chapter-map.csv': CHAPTER_MAP,
            'reference/scene-intent.csv': (
                'id|function|value_at_stake|value_shift|characters|on_stage|mice_threads\n'
                'gods-debate|x|homecoming|-/+|jove|jove|\n'
                'minerva-visits|x|courage|-/+|minerva|minerva|\n'
                'assembly-called|x|authority|-/+| ulysses ;;|telemachus|\n'   # told of only
                'ship-sails|x|courage|+/++|telemachus|telemachus|\n')})
        _set_range(proj, 'chapters 2-2')   # assembly-called: pov telemachus
        import_source(proj)
        seeded, notes = _seed(proj)
        assert sorted(_ids(proj, 'characters.csv')) == ['odysseus', 'telemachus']
        assert seeded['reference/characters.csv'] == (2, 5) and notes == []

    def test_values_follow_value_at_stake(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {
            'reference/chapter-map.csv': CHAPTER_MAP,
            'reference/values.csv': 'id|name|aliases\nhomecoming|Homecoming|\n'
                                    'courage|Courage|\nauthority|Authority|\n'})
        _set_range(proj, 'chapters 3-3')   # ship-sails: courage
        import_source(proj)
        assert _seed(proj)[0]['reference/values.csv'] == (1, 3)
        assert _ids(proj, 'values.csv') == ['courage']

    def test_cast_cells_holding_names_or_aliases_count(self, tmp_path):
        """CR-2: a project that keeps names in the cast columns."""
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {
            'reference/chapter-map.csv': CHAPTER_MAP,
            'reference/scene-intent.csv': (
                'id|function|value_at_stake|value_shift|characters|on_stage|mice_threads\n'
                'gods-debate|x|Homecoming|-/+|jove|jove|\n'
                'minerva-visits|x|courage|-/+|minerva|minerva|\n'
                'assembly-called|x|authority|-/+|Pallas;Nobody|Telemachus|\n'
                'ship-sails|x|courage|+/++|telemachus|telemachus|\n')})
        _set_range(proj, 'chapters 2-2')
        import_source(proj)
        _seeded, notes = _seed(proj)
        assert sorted(_ids(proj, 'characters.csv')) == ['athena', 'telemachus']
        assert notes == ['NOTE: source odyssey: characters.csv: the range\'s scenes name '
                         'Nobody, which no row has as its id, name or alias; not seeded']

    def test_the_ledger_counts_for_the_cast(self, tmp_path):
        """CR-4: someone the range knows only from its ledger is kept."""
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {
            'reference/chapter-map.csv': CHAPTER_MAP,
            'reference/commitments.csv': (
                'id|scene_id|type|subject|statement|quote|known_by\n'
                'a|assembly-called|knowledge|suitors-plot|x|"y"|ulysses\n')})
        _set_range(proj, 'chapters 2-2')
        import_source(proj)
        _seeded, notes = _seed(proj)
        assert sorted(_ids(proj, 'characters.csv')) == ['odysseus', 'telemachus']
        assert notes == []   # a topic subject isn't a missing person

    def test_a_missing_column_seeds_everything_and_says_so(self, tmp_path):
        """SF-1/SF-2: a range that can't be checked doesn't quietly shrink."""
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {
            'reference/chapter-map.csv': CHAPTER_MAP,
            'reference/scene-intent.csv': 'id|function\ngods-debate|x\nminerva-visits|x\n'
                                          'assembly-called|x\nship-sails|x\n'})
        _set_range(proj, 'chapters 2-2')
        import_source(proj)
        seeded, notes = _seed(proj)
        assert seeded['reference/characters.csv'] == (5, 5)
        assert ('WARNING: source odyssey: characters.csv: reference/source/odyssey/'
                'scene-intent.csv has no `characters` column (or is missing), so the '
                'range can\'t be checked; every row is seeded') in notes

    def test_a_range_using_none_of_a_registry_says_so(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {
            'reference/chapter-map.csv': CHAPTER_MAP,
            'reference/values.csv': 'id|name|aliases\nhope|Hope|\n'})
        _set_range(proj, 'chapters 2-2')
        import_source(proj)
        seeded, notes = _seed(proj)
        assert 'reference/values.csv' not in seeded
        assert ('NOTE: source odyssey: no scene in its range (chapter 2) names any of '
                'values.csv\'s 1 row(s), so it gives none') in notes

    def test_cli_says_what_was_left_out(self, tmp_path, monkeypatch, capsys):
        from storyforge import cmd_source
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': CHAPTER_MAP})
        _set_range(proj, 'chapters 2-3')
        monkeypatch.setattr(cmd_source, 'detect_project_root', lambda: proj)
        assert cmd_source.main(['import', '--no-commit']) == 0
        out = capsys.readouterr()
        assert ('Seeded reference/characters.csv with 2 row(s) from the source (it had '
                'none) (3 of its 5 aren\'t named by any scene in the range, so left '
                'out)') in out.out + out.err

    def test_cli_stops_when_the_range_cant_be_resolved(self, ranged, monkeypatch, capsys):
        """T-2: written, not committed, and said so."""
        from storyforge import cmd_source

        def broken(*_a, **_k):
            raise source.SourceError('source odyssey: range broken')
        monkeypatch.setattr(cmd_source, 'detect_project_root', lambda: ranged)
        monkeypatch.setattr(source, 'adapted_ids', broken)
        assert cmd_source.main(['import', '--no-commit']) == 1
        out = capsys.readouterr()
        text = out.out + out.err
        assert 'ERROR: source odyssey: range broken' in text
        assert 'written but not committed' in text
        assert not os.path.exists(os.path.join(ranged, 'reference', 'characters.csv'))


class TestSeedTwoSources:
    def test_each_source_uses_its_own_range(self, two):
        """T-1: odyssey (chapter 1) leaves the harbor out; the unranged iliad
        gives it, and the first source still wins for shared ids."""
        seeded, notes = _seed(two)
        assert seeded['reference/locations.csv'] == (3, 3) and notes == []
        assert _ids(two, 'locations.csv') == ['olympus', 'ithaca-hall', 'harbor']

    def test_importing_one_source_while_the_other_isnt(self, tmp_path):
        """CR-1: a ranged source not imported yet is passed over, not an error."""
        proj = make_adaptation(tmp_path)
        _write(str(tmp_path / 'odyssey'), {'reference/chapter-map.csv': CHAPTER_MAP})
        _write(str(tmp_path / 'iliad'), SOURCE_FILES)
        _write(proj, {'storyforge.yaml': TWO_YAML})
        cfg = source.read_config(proj)
        source.write_import(source.import_source(proj, cfg, 'iliad'))
        seeded, notes = _seed(proj)
        assert seeded['reference/characters.csv'] == (5, 5) and notes == []
