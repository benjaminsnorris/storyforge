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
        'reference/outline.md',
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


# ---------------------------------------------------------------------------
# Unified outline.md rendering
# ---------------------------------------------------------------------------

def test_outline_md_renders_three_sections(tmp_path):
    """export_outline_md produces a numbered list for each populated CSV."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'spine.csv'),
        'id|seq|title|summary|function|part',
        [
            'ev-1|1|First|Lucien finds an anomaly.|inciting|1',
            'ev-2|2|Second|The Archive responds with suppression.|turning|2',
        ],
    )
    _write_csv(
        os.path.join(str(ref), 'architecture.csv'),
        'id|seq|title|summary|part|pov|spine_event|action_sequel|emotional_arc|'
        'value_at_stake|value_shift|turning_point',
        [
            'a01|1|Studio|Lucien finalizes a portrait with growing unease.|1|'
            'POV|ev-1|action|confidence to unease|vocation|+/-|revelation',
        ],
    )
    _write_csv(
        os.path.join(str(ref), 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words',
        [
            'sc-1|1|Studio|A portrait refuses to finish on a quiet morning.|'
            '1|p|loc|1|morning|2h|character|mapped|0|2500',
        ],
    )

    from storyforge.cmd_scenes_export import export_outline_md
    out = export_outline_md(str(tmp_path))
    assert out
    text = open(out).read()
    assert '# Story outline' in text
    assert '## Spine' in text
    assert '## Architecture' in text
    assert '## Scenes' in text
    # Numbered list aligned to seq
    assert '1. Lucien finds an anomaly.' in text
    assert '2. The Archive responds with suppression.' in text
    assert '1. Lucien finalizes a portrait with growing unease.' in text
    assert '1. A portrait refuses to finish on a quiet morning.' in text


def test_outline_md_marks_missing_summaries(tmp_path):
    """Empty summary cells render as _(missing)_ markers so the author can
    see exactly which rows still need to be written."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'spine.csv'),
        'id|seq|title|summary|function|part',
        [
            'ev-1|1|First|Has summary.|inciting|1',
            'ev-2|2|Second||turning|2',
        ],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    out = export_outline_md(str(tmp_path))
    text = open(out).read()
    assert '1. Has summary.' in text
    assert '2. _(missing)_' in text


def test_outline_md_handles_missing_csvs(tmp_path):
    """If only spine.csv exists, the other sections render '(no source file yet)'."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'spine.csv'),
        'id|seq|title|summary|function|part',
        ['ev-1|1|First|Just the spine for now.|inciting|1'],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    out = export_outline_md(str(tmp_path))
    text = open(out).read()
    assert '1. Just the spine for now.' in text
    assert '(no source file yet)' in text


def test_outline_md_sorts_by_seq(tmp_path):
    """Rows are rendered in seq order, not file order."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'spine.csv'),
        'id|seq|title|summary|function|part',
        [
            'ev-c|3|Third|Third in story order.|f|2',
            'ev-a|1|First|First in story order.|f|1',
            'ev-b|2|Second|Second in story order.|f|1',
        ],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    out = export_outline_md(str(tmp_path))
    text = open(out).read()
    pos1 = text.index('First in story order.')
    pos2 = text.index('Second in story order.')
    pos3 = text.index('Third in story order.')
    assert pos1 < pos2 < pos3


def test_outline_md_returns_empty_when_no_sources(tmp_path):
    """No spine.csv, no architecture.csv, no scenes.csv → no file written."""
    (tmp_path / 'reference').mkdir()
    from storyforge.cmd_scenes_export import export_outline_md
    out = export_outline_md(str(tmp_path))
    assert out == ''
    assert not os.path.isfile(str(tmp_path / 'reference' / 'outline.md'))


def test_outline_md_skips_csv_without_summary_column(tmp_path):
    """Legacy CSVs without a summary column render as empty sections — no
    crash, just '(no rows yet)'."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'spine.csv'),
        'id|seq|title|function|part',  # no summary column
        ['ev-1|1|t|f|1'],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    out = export_outline_md(str(tmp_path))
    text = open(out).read()
    # The Spine section renders but with no items (summary column absent)
    assert '## Spine' in text
    assert '(no rows yet)' in text


def test_outline_md_missing_seq_renders_with_placeholder(tmp_path):
    """A row whose seq cell is missing or non-integer renders with '?.' —
    NOT with a billion-numbered list item."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'spine.csv'),
        'id|seq|title|summary|function|part',
        [
            'ev-1|1|First|First in order.|inciting|1',
            'ev-2||Has no seq|This row has no seq cell.|turn|2',
            'ev-3|notanumber|Bad seq|This row has a non-integer seq.|midpoint|2',
        ],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    text = open(export_outline_md(str(tmp_path))).read()
    assert '1. First in order.' in text
    assert '?. This row has no seq cell.' in text
    assert '?. This row has a non-integer seq.' in text
    # Should NEVER produce a billion-numbered item
    assert '1000000000' not in text


def test_outline_md_shows_brief_promise_under_scene(tmp_path):
    """When a scene has a brief with goal + outcome, outline.md adds a
    sub-bullet showing what the brief promises."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words',
        ['sc-1|1|t|Scene one summary.|1|p|l|1|m|2h|character|briefed|0|2500'],
    )
    _write_csv(
        os.path.join(str(ref), 'scene-briefs.csv'),
        'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|'
        'key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow',
        ['sc-1|Complete the audit|Anomalous readings|Report or hide|'
         'Choose protocol|Files as error|||Reviews maps|Quote|focus|maps||false'],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    text = open(export_outline_md(str(tmp_path))).read()
    assert '1. Scene one summary.' in text
    assert 'Brief:' in text
    assert 'Complete the audit' in text
    assert 'Report or hide' in text


def test_outline_md_omits_brief_when_too_sparse(tmp_path):
    """A brief with no goal/outcome/decision doesn't render a sub-bullet."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words',
        ['sc-1|1|t|Scene one.|1|p|l|1|m|2h|character|mapped|0|2500'],
    )
    _write_csv(
        os.path.join(str(ref), 'scene-briefs.csv'),
        'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|'
        'key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow',
        ['sc-1|||||||||||||false'],  # all empty
    )
    from storyforge.cmd_scenes_export import export_outline_md
    text = open(export_outline_md(str(tmp_path))).read()
    assert '1. Scene one.' in text
    assert 'Brief:' not in text


def test_outline_md_brief_falls_back_to_decision(tmp_path):
    """Sequel-shaped scenes (no goal, but decision present) render with
    'decision \"...\"' as the brief promise."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words',
        ['sc-1|1|t|Sequel scene.|1|p|l|1|m|2h|character|mapped|0|2500'],
    )
    _write_csv(
        os.path.join(str(ref), 'scene-briefs.csv'),
        'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|'
        'key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow',
        ['sc-1||||Dilemma|Choose to act||||||||false'],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    text = open(export_outline_md(str(tmp_path))).read()
    assert 'decision "Choose to act"' in text


def test_outline_md_no_briefs_csv_does_not_crash(tmp_path):
    """When scene-briefs.csv is absent, outline still renders cleanly
    without brief sub-bullets."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    _write_csv(
        os.path.join(str(ref), 'scenes.csv'),
        'id|seq|title|summary|part|pov|location|timeline_day|time_of_day|'
        'duration|type|status|word_count|target_words',
        ['sc-1|1|t|Scene only.|1|p|l|1|m|2h|character|mapped|0|2500'],
    )
    from storyforge.cmd_scenes_export import export_outline_md
    text = open(export_outline_md(str(tmp_path))).read()
    assert '1. Scene only.' in text
    assert 'Brief:' not in text


def test_outline_md_field_count_mismatch_logs_and_skips(tmp_path, capsys):
    """A row with wrong field count is logged WARNING and skipped — not
    silently misaligned via zip()."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    spine = ref / 'spine.csv'
    with open(spine, 'w') as f:
        f.write('id|seq|title|summary|function|part\n')
        f.write('ev-1|1|Good|Good summary.|inciting|1\n')
        f.write('ev-2|2|Truncated\n')  # too few fields
    from storyforge.cmd_scenes_export import export_outline_md
    text = open(export_outline_md(str(tmp_path))).read()
    out = capsys.readouterr().out
    assert 'WARNING' in out and 'fields' in out
    assert '1. Good summary.' in text
    # Truncated row should NOT appear
    assert 'Truncated' not in text
