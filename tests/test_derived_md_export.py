"""Tests for spine.md / architecture.md derived markdown rendering (#229)."""

import os

from storyforge.cmd_scenes_export import (
    export_architecture_md,
    export_spine_md,
)


def _write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(header + '\n')
        for r in rows:
            f.write(r + '\n')


# ---------------------------------------------------------------------------
# Spine rendering
# ---------------------------------------------------------------------------

def test_export_spine_md_returns_empty_when_csv_absent(tmp_path):
    result = export_spine_md(str(tmp_path))
    assert result == ''
    assert not os.path.isfile(os.path.join(str(tmp_path), 'reference', 'spine.md'))


def test_export_spine_md_renders_each_row_as_section(tmp_path):
    _write_csv(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|function|part',
        [
            'event-1|1|The Discovery|inciting incident|1',
            'event-2|2|The Reckoning|midpoint|2',
            'event-3|3|The Resolution|climax|3',
        ],
    )
    out = export_spine_md(str(tmp_path))
    assert out.endswith('spine.md')
    content = open(out).read()
    assert content.startswith('# Spine')
    assert '## event-1' in content
    assert '## event-2' in content
    assert '## event-3' in content
    assert 'seq: 1' in content
    assert 'title: The Discovery' in content
    assert 'function: inciting incident' in content


def test_export_spine_md_includes_derived_notice(tmp_path):
    _write_csv(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
        'id|seq|title|function|part',
        ['e|1|T|fn|1'],
    )
    out = export_spine_md(str(tmp_path))
    content = open(out).read()
    # Should warn readers that this is derived
    assert 'Derived from reference/spine.csv' in content


# ---------------------------------------------------------------------------
# Architecture rendering
# ---------------------------------------------------------------------------

def test_export_architecture_md_skips_when_csv_absent(tmp_path):
    result = export_architecture_md(str(tmp_path))
    assert result == ''


def test_export_architecture_md_includes_spine_event_column(tmp_path):
    """Architecture rendering must show the spine_event reference so the
    relationship between architecture and spine is visible in the diff."""
    _write_csv(
        os.path.join(str(tmp_path), 'reference', 'architecture.csv'),
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point',
        [
            'arch-1|1|T1|1|hero|event-1|action|hope to dread|truth|+/-|action',
            'arch-2|2|T2|1|hero|event-1|sequel|dread to resolve|truth|-/+|revelation',
        ],
    )
    out = export_architecture_md(str(tmp_path))
    content = open(out).read()
    assert '## arch-1' in content
    assert 'spine_event: event-1' in content
    assert 'action_sequel: action' in content


# ---------------------------------------------------------------------------
# Sync integration
# ---------------------------------------------------------------------------

def test_sync_renders_spine_and_architecture_when_csv_present(tmp_path):
    """The sync helper should regenerate spine.md and architecture.md when
    the underlying CSVs exist."""
    ref = os.path.join(str(tmp_path), 'reference')

    # Seed minimal scenes.csv etc so scenes-export works
    _write_csv(
        os.path.join(ref, 'scenes.csv'),
        'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|'
        'type|status|word_count|target_words|target_pages|panel_count|page_count|'
        'architecture_scene',
        ['sc-1|1|First|1|hero|home|1|day|short|action|mapped||||||'],
    )
    _write_csv(
        os.path.join(ref, 'scene-intent.csv'),
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage|mice_threads|theme_threads',
        ['sc-1|opening|action|||+/-|action|||||'],
    )
    _write_csv(
        os.path.join(ref, 'spine.csv'),
        'id|seq|title|function|part',
        ['e-1|1|Title|inciting|1'],
    )
    _write_csv(
        os.path.join(ref, 'architecture.csv'),
        'id|seq|title|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point',
        ['arch-1|1|Title|1|hero|e-1|action|||+/-|action'],
    )

    from storyforge.cmd_sync import _export_all_derived
    md_path = os.path.join(ref, 'scenes-review.md')
    _export_all_derived(str(tmp_path), md_path)

    assert os.path.isfile(md_path), 'main scenes-review.md should be written'
    assert os.path.isfile(os.path.join(ref, 'spine.md')), \
        'derived spine.md should be written'
    assert os.path.isfile(os.path.join(ref, 'architecture.md')), \
        'derived architecture.md should be written'


def test_sync_skips_structural_renderings_when_csvs_absent(tmp_path):
    """A project with scenes but no spine.csv/architecture.csv (e.g., a
    novel-mode project still at the briefs stage with no structural
    extraction yet) should skip the derived renderings silently."""
    ref = os.path.join(str(tmp_path), 'reference')
    _write_csv(
        os.path.join(ref, 'scenes.csv'),
        'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|'
        'type|status|word_count|target_words|target_pages|panel_count|page_count|'
        'architecture_scene',
        ['sc-1|1|First|1|hero|home|1|day|short|action|briefed||||||'],
    )
    _write_csv(
        os.path.join(ref, 'scene-intent.csv'),
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage|mice_threads|theme_threads',
        ['sc-1|opening|action|||+/-|action|||||'],
    )

    from storyforge.cmd_sync import _export_all_derived
    md_path = os.path.join(ref, 'scenes-review.md')
    _export_all_derived(str(tmp_path), md_path)

    assert os.path.isfile(md_path), 'main scenes-review.md still gets written'
    assert not os.path.isfile(os.path.join(ref, 'spine.md'))
    assert not os.path.isfile(os.path.join(ref, 'architecture.md'))


def test_sync_handles_empty_scenes_csv(tmp_path):
    """A fresh-init project (scenes.csv header-only, no data rows) must
    NOT abort sync — that would refuse the first commit. _export_all_derived
    skips the scenes-review.md write but still runs the structural-anchor
    renderings if their CSVs exist."""
    ref = os.path.join(str(tmp_path), 'reference')
    _write_csv(
        os.path.join(ref, 'scenes.csv'),
        'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|'
        'type|status|word_count|target_words|target_pages|panel_count|page_count|'
        'architecture_scene',
        [],  # header only, no data
    )
    _write_csv(
        os.path.join(ref, 'scene-intent.csv'),
        'id|function|action_sequel|emotional_arc|value_at_stake|value_shift|'
        'turning_point|characters|on_stage|mice_threads|theme_threads',
        [],
    )
    # Seed a spine.csv to confirm the structural-anchor rendering still runs
    _write_csv(
        os.path.join(ref, 'spine.csv'),
        'id|seq|title|function|part',
        ['e-1|1|Title|inciting|1'],
    )

    from storyforge.cmd_sync import _export_all_derived
    md_path = os.path.join(ref, 'scenes-review.md')
    # MUST NOT SystemExit
    _export_all_derived(str(tmp_path), md_path)

    # No scenes-review.md because there are no scenes
    assert not os.path.isfile(md_path)
    # But spine.md still got rendered
    assert os.path.isfile(os.path.join(ref, 'spine.md'))


def test_hook_path_filter_matches_new_paths():
    """The sync hook's path regex should fire on spine.csv / architecture.csv
    edits and on the derived MDs."""
    import re
    from storyforge.cmd_sync import HOOK_PATH_FILTER

    rx = re.compile(HOOK_PATH_FILTER, re.MULTILINE)
    for good in (
        'reference/spine.csv',
        'reference/architecture.csv',
        'reference/spine.md',
        'reference/architecture.md',
        'reference/scenes.csv',  # existing — should still match
        'reference/scenes-review.md',
    ):
        assert rx.search(good), f'expected hook to fire for {good!r}'
    for bad in (
        'reference/voice-profile.csv',  # not a sync-tracked file
        'spine.csv',  # wrong directory
        'reference/spine.csv.bak',  # extension boundary
    ):
        assert not rx.search(bad), f'hook must not fire for {bad!r}'
