"""Tests for the interior-illustration module (#278).

Covers the plan CSV, the scene marker, anchor matching, per-target resolution,
the selection pre-pass, image inspection, and plan validation.
"""

import os
import struct

import pytest

from illustration_helpers import (
    scene_split,
    SAMPLE_DIRECTION, SCENE, SCENE_ADVERSARIAL, SCENE_WITH_FRONTMATTER,
    make_jpeg, make_png, make_webp, make_webp_vp8, make_webp_vp8l, pandoc_html,
    plan_row, truncated_png, write_csv, write_direction_file,
    write_scene,
)
from storyforge import illustrations as ill


# ============================================================================
# Helpers
# ============================================================================

# ============================================================================
# Plan CSV
# ============================================================================

def test_plan_round_trips(project_dir):
    rows = [plan_row(), plan_row(id='second', scene_id='other')]
    ill.write_plan(project_dir, rows)

    read_back = ill.read_plan(project_dir)
    assert [r['id'] for r in read_back] == ['lantern-vigil', 'second']
    assert read_back[0]['anchor'] == 'She set it on the sill'
    assert read_back[0]['placement'] == 'after_anchor'


def test_read_plan_missing_file_is_empty(project_dir):
    assert ill.read_plan(project_dir) == []
    assert ill.read_plan_as_map(project_dir) == {}


def test_read_plan_strips_crlf(project_dir):
    path = ill.plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = '|'.join(ill.PLAN_COLUMNS)
    with open(path, 'w', newline='') as f:
        f.write(f'{header}\r\nlantern-vigil|vigil|anchor text'
                + '|' * (len(ill.PLAN_COLUMNS) - 3) + '\r\n')

    rows = ill.read_plan(project_dir)
    assert rows[0]['id'] == 'lantern-vigil'
    assert '\r' not in rows[0]['anchor']


def test_read_plan_skips_rows_with_no_id(project_dir):
    path = ill.plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(ill.PLAN_COLUMNS) + '\n')
        f.write('|' * (len(ill.PLAN_COLUMNS) - 1) + '\n')
    assert ill.read_plan(project_dir) == []


def test_read_plan_as_map_first_row_wins_on_duplicate(project_dir):
    ill.write_plan(project_dir, [
        plan_row(beat='first'), plan_row(beat='second'),
    ])
    assert ill.read_plan_as_map(project_dir)['lantern-vigil']['beat'] == 'first'


def test_upsert_preserves_existing_cells(project_dir):
    existing = [plan_row(beat='author wrote this')]
    incoming = [plan_row(beat='model wrote this', palette='cold blue')]

    merged = ill.upsert_rows(existing, incoming)
    assert len(merged) == 1
    # An author edit survives a second planning pass...
    assert merged[0]['beat'] == 'author wrote this'
    # ...but an empty cell gets filled.
    assert merged[0]['palette'] == 'cold blue'


def test_upsert_appends_new_rows_in_order():
    merged = ill.upsert_rows([plan_row()], [plan_row(id='later')])
    assert [r['id'] for r in merged] == ['lantern-vigil', 'later']


def test_upsert_ignores_rows_with_no_id():
    assert ill.upsert_rows([], [{'id': '', 'beat': 'x'}]) == []


# ============================================================================
# Markers
# ============================================================================

def test_marker_for():
    assert ill.marker_for('lantern-vigil') == '![[illus:lantern-vigil]]'


def test_find_markers_reports_position_and_line():
    text = 'One.\n\n![[illus:a]]\n\nTwo.\n'
    hits = ill.find_markers(text)
    assert len(hits) == 1
    assert hits[0]['id'] == 'a'
    assert hits[0]['line'] == 3
    assert text[hits[0]['start']:hits[0]['end']] == '![[illus:a]]'


def test_marker_ids_in_document_order():
    text = 'a\n\n![[illus:second]]\n\nb\n\n![[illus:first]]\n'
    assert ill.marker_ids(text) == ['second', 'first']


def test_indented_marker_is_recognized():
    assert ill.marker_ids('One.\n\n   ![[illus:a]]   \n\nTwo.\n') == ['a']


def test_strip_markers_restores_original_prose():
    inserted = ill.insert_marker(SCENE, plan_row())['text']
    assert ill.strip_markers(inserted).strip() == SCENE.strip()


def test_strip_markers_handles_inline_marker():
    text = 'She waited ![[illus:x]] a long time.\n'
    assert ill.strip_markers(text) == 'She waited  a long time.\n'


def test_strip_markers_is_noop_without_markers():
    assert ill.strip_markers(SCENE) == SCENE


def test_strip_markers_collapses_blank_line_runs():
    text = 'One.\n\n![[illus:a]]\n\nTwo.\n'
    assert ill.strip_markers(text) == 'One.\n\nTwo.\n'


def test_count_prose_words_excludes_markers():
    inserted = ill.insert_marker(SCENE, plan_row())['text']
    assert len(inserted.split()) == len(SCENE.split()) + 1
    assert ill.count_prose_words(inserted) == len(SCENE.split())


def test_remove_marker():
    inserted = ill.insert_marker(SCENE, plan_row())['text']
    text, changed = ill.remove_marker(inserted, 'lantern-vigil')
    assert changed
    assert ill.marker_ids(text) == []
    assert text.strip() == SCENE.strip()


def test_remove_marker_absent_is_noop():
    text, changed = ill.remove_marker(SCENE, 'nope')
    assert not changed
    assert text == SCENE


def test_remove_marker_leaves_other_markers():
    text = 'a\n\n![[illus:keep]]\n\nb\n\n![[illus:drop]]\n\nc\n'
    out, changed = ill.remove_marker(text, 'drop')
    assert changed
    assert ill.marker_ids(out) == ['keep']


# ============================================================================
# Anchor matching
# ============================================================================

def test_find_anchor_exact_hit():
    match = ill.find_anchor(SCENE, 'She set it on the sill')
    assert match is not None
    assert match['count'] == 1
    assert SCENE[match['start']:match['end']] == 'She set it on the sill'


def test_find_anchor_tolerates_rewrapped_whitespace():
    wrapped = 'The lantern\nguttered. She set it\non the sill and waited.\n'
    match = ill.find_anchor(wrapped, 'She set it on the sill')
    assert match is not None
    assert match['count'] == 1


def test_find_anchor_missing_returns_none():
    assert ill.find_anchor(SCENE, 'a phrase that was revised away') is None


def test_find_anchor_counts_duplicates():
    text = 'Same words here.\n\nAnd again: Same words here.\n'
    match = ill.find_anchor(text, 'Same words here')
    assert match is not None
    assert match['count'] == 2


def test_find_anchor_empty_anchor_is_none():
    assert ill.find_anchor(SCENE, '') is None
    assert ill.find_anchor(SCENE, '   ') is None


def test_find_anchor_ignores_an_intervening_marker():
    """A marker inside the candidate span must not break the match."""
    text = 'She set it\n\n![[illus:other]]\n\non the sill and waited.\n'
    assert ill.find_anchor(text, 'She set it on the sill') is not None


# ============================================================================
# Marker insertion
# ============================================================================

def test_insert_after_anchor_lands_after_the_whole_paragraph():
    text = ill.insert_marker(SCENE, plan_row())['text']
    lines = [ln for ln in text.split('\n') if ln.strip()]
    anchor_idx = next(i for i, ln in enumerate(lines) if 'sill' in ln)
    assert lines[anchor_idx + 1] == '![[illus:lantern-vigil]]'


def test_insert_before_anchor():
    text = ill.insert_marker(SCENE, plan_row(placement='before_anchor'))['text']
    lines = [ln for ln in text.split('\n') if ln.strip()]
    marker_idx = lines.index('![[illus:lantern-vigil]]')
    assert 'sill' in lines[marker_idx + 1]


def test_insert_before_anchor_on_first_paragraph_has_no_leading_blanks():
    row = plan_row(anchor='The lantern guttered', placement='before_anchor')
    text = ill.insert_marker(SCENE, row)['text']
    assert text.startswith('![[illus:lantern-vigil]]\n\n')


def test_insert_scene_open_and_close_need_no_anchor():
    opened = ill.insert_marker(SCENE, plan_row(placement='scene_open',
                                               anchor=''))['text']
    assert opened.startswith('![[illus:lantern-vigil]]\n\n')

    closed = ill.insert_marker(SCENE, plan_row(placement='scene_close',
                                              anchor=''))['text']
    assert closed.rstrip('\n').endswith('![[illus:lantern-vigil]]')


def test_insert_is_idempotent():
    once = ill.insert_marker(SCENE, plan_row())
    twice = ill.insert_marker(once['text'], plan_row())
    assert once['changed'] is True
    assert twice['changed'] is False
    assert twice['error'] == ''
    assert twice['text'] == once['text']


def test_insert_refuses_on_drifted_anchor():
    result = ill.insert_marker(SCENE, plan_row(anchor='no longer present'))
    assert result['changed'] is False
    assert 'anchor not found' in result['error']
    assert result['text'] == SCENE


def test_insert_refuses_on_ambiguous_anchor():
    text = 'Same words here.\n\nAnd: Same words here.\n'
    result = ill.insert_marker(text, plan_row(anchor='Same words here'))
    assert result['changed'] is False
    assert 'ambiguous' in result['error']
    assert 'appears 2 times' in result['error']
    assert result['text'] == text


def test_insert_requires_an_anchor_for_anchored_placement():
    result = ill.insert_marker(SCENE, plan_row(anchor=''))
    assert result['changed'] is False
    assert 'requires an anchor' in result['error']


def test_insert_rejects_unknown_placement():
    result = ill.insert_marker(SCENE, plan_row(placement='sideways'))
    assert result['changed'] is False
    assert 'invalid placement' in result['error']


def test_insert_rejects_row_with_no_id():
    result = ill.insert_marker(SCENE, plan_row(id=''))
    assert result['changed'] is False
    assert 'no id' in result['error']


def test_insert_defaults_to_after_anchor_when_placement_blank():
    result = ill.insert_marker(SCENE, plan_row(placement=''))
    assert result['changed'] is True


# ============================================================================
# Reading position and the scene split (#308)
# ============================================================================

def test_reading_position_lands_after_the_anchors_paragraph():
    position = ill.reading_position(SCENE, plan_row())
    assert position['error'] == ''
    assert SCENE[:position['offset']].rstrip().endswith(
        'waited for the street to answer.')


def test_reading_position_puts_the_anchor_sentence_after_a_before_anchor_image():
    """`before_anchor` means the reader has *not* read the anchor sentence yet.

    Placement is relative to the whole paragraph, so the anchor's own paragraph
    falls on the unread side — which is what makes an image placed before it
    unable to show what it says.
    """
    position = ill.reading_position(SCENE, plan_row(placement='before_anchor'))
    assert 'She set it on the sill' not in SCENE[:position['offset']]


@pytest.mark.parametrize('placement,offset', [
    ('scene_open', 0),
    ('scene_close', len(SCENE)),
])
def test_reading_position_of_the_anchorless_placements(placement, offset):
    assert ill.reading_position(
        SCENE, plan_row(placement=placement))['offset'] == offset


@pytest.mark.parametrize('row,expected', [
    (plan_row(anchor='a phrase the prose does not contain'), 'anchor not found'),
    (plan_row(anchor=''), 'requires an anchor'),
    (plan_row(placement='sideways'), 'invalid placement'),
])
def test_reading_position_refuses_to_guess(row, expected):
    """`None`, never a sentinel offset.

    A `-1` would slice to `body[:-1]` — nearly the whole scene, which is exactly
    the failure #308 describes. `None` raises out of the slice instead.
    """
    position = ill.reading_position(SCENE, row)
    assert position['offset'] is None
    assert expected in position['error']


def test_reading_position_refuses_an_ambiguous_anchor():
    doubled = SCENE + '\nShe set it on the sill again.\n'
    position = ill.reading_position(
        doubled, plan_row(anchor='She set it on the sill'))
    assert position['offset'] is None
    assert 'ambiguous' in position['error']


def test_insert_marker_lands_exactly_at_the_reading_position():
    """The shared predicate, asserted as shared.

    `--prompts` splits the prose at `reading_position` and `--embed` places the
    marker there. If those two ever disagree, the model is shown a different
    scene than the reader reads, which is #308 with no way to detect it.
    """
    for placement in ('before_anchor', 'after_anchor', 'scene_open',
                      'scene_close'):
        row = plan_row(placement=placement)
        offset = ill.reading_position(SCENE, row)['offset']
        marked = ill.insert_marker(SCENE, row)['text']
        before_marker = marked.split(ill.marker_for(row['id']))[0]
        assert (' '.join(before_marker.split())
                == ' '.join(SCENE[:offset].split())), placement


def test_scene_open_normalizes_the_first_paragraphs_indentation():
    """A consequence of collapsing the placement branches onto one offset: the
    anchorless placements now route through the same lstrip as the anchored ones.
    Pinned so it is not rediscovered as a mystery."""
    indented = '    Indented opening block.\n\nA second paragraph.\n'
    text = ill.insert_marker(indented, plan_row(placement='scene_open'))['text']
    assert text.startswith(ill.marker_for('lantern-vigil'))
    assert '\n\nIndented opening block.' in text


def test_split_at_position_separates_read_from_unread():
    split = ill.split_at_position(SCENE, plan_row())
    assert 'She set it on the sill' in split['read']
    assert 'Nothing came' not in split['read']
    assert split['unread'].startswith('Nothing came')
    assert split['error'] == ''


def test_split_at_a_scene_close_has_no_unread_prose_and_no_error():
    """The vacuous case, which consumers must not render as a check.

    An image at the end of a scene has nothing after it to spoil. That is
    different from a position nobody could resolve, and `SceneSplit` documents
    the difference as `unread == '' and error == ''`.
    """
    split = ill.split_at_position(SCENE, plan_row(placement='scene_close'))
    assert split['unread'] == ''
    assert split['next_sentence'] == ''
    assert split['error'] == ''
    assert 'By morning she had decided' in split['read']


def test_split_at_a_scene_open_has_read_nothing():
    split = ill.split_at_position(SCENE, plan_row(placement='scene_open'))
    assert split['read'] == ''
    assert split['unread'].startswith('The lantern guttered')


def test_split_reports_an_unresolved_position_instead_of_guessing():
    split = ill.split_at_position(SCENE, plan_row(anchor='not in this prose'))
    assert 'anchor not found' in split['error']
    assert split['unread'] == ''
    assert split['next_sentence'] == ''
    # A leading window, so the request still has prose to work from.
    assert split['read'].startswith('The lantern guttered')


def test_split_caps_the_unread_side_at_a_few_paragraphs():
    body = SCENE + ''.join(f'\nParagraph number {i} follows on.\n'
                           for i in range(10))
    split = ill.split_at_position(body, plan_row())
    assert split['unread'].count('\n\n') < ill.UNREAD_BLOCKS
    assert 'Paragraph number 9' not in split['unread']


def test_split_read_window_is_bounded_but_keeps_the_anchor():
    body = ('Filler sentence that goes on. ' * 400) + '\n\n' + SCENE
    split = ill.split_at_position(body, plan_row())
    assert len(split['read']) <= ill.READ_CHARS
    assert 'She set it on the sill' in split['read']


def test_the_read_window_snaps_to_a_paragraph_boundary():
    """The loop this pins could be deleted with the rest of the suite green.

    Asserted structurally: the window must begin exactly where some paragraph
    begins. An unsnapped window opens mid-sentence, which reads to a model as
    prose it is invited to complete.
    """
    body = ('Opening paragraph, short.\n\n'
            + ('Second paragraph filler that runs on. ' * 60).strip() + '\n\n'
            + SCENE)
    split = ill.split_at_position(body, plan_row())

    starts = {s for s, _e in ill._paragraph_blocks(body)}
    assert body.index(split['read']) in starts


def test_a_long_paragraph_before_the_split_still_yields_read_prose():
    """#308 restored by the code fixing #308.

    Without a `start < offset` bound the snapping loop matched a paragraph AFTER
    the split, sliced backwards to '', and left `state == 'normal'` — so the
    request carried no scene prose at all and its only prose was the block the
    model is told to avoid. Nothing warned.
    """
    long_para = 'She set it on the sill. ' + 'The cold pressed at the glass. ' * 90
    body = long_para.strip() + '\n\nNothing came.\n\nBy morning she had decided.\n'
    assert len(long_para) > ill.READ_CHARS

    split = ill.split_at_position(body, plan_row())
    assert split['state'] == 'normal'
    assert split['read'] != ''
    assert 'the cold pressed at the glass' in split['read'].lower()
    assert split['unread'].startswith('Nothing came')


def test_a_single_giant_paragraph_falls_back_to_the_raw_window():
    """No paragraph starts inside the window at all — the loop finds nothing and
    the mid-sentence slice is strictly better than no prose."""
    body = 'She set it on the sill. ' + 'Filler that runs on. ' * 200
    split = ill.split_at_position(body, plan_row(placement='before_anchor'))
    assert split['read'] == '' or len(split['read']) <= ill.READ_CHARS


def test_read_is_empty_only_at_the_start_of_a_scene():
    """The invariant `offset` was added to make assertable."""
    for placement in ('before_anchor', 'after_anchor', 'scene_open', 'scene_close'):
        split = ill.split_at_position(SCENE, plan_row(placement=placement))
        if split['read'] == '':
            assert split['offset'] == 0, placement


def test_the_unread_cap_cannot_manufacture_an_empty_unread_side():
    """A gap to the next paragraph wider than UNREAD_CHARS made `end` fall before
    the block started — a reversed slice reading as "nothing follows this"."""
    body = (SCENE.rstrip() + '\n' + ('   \n' * 400)
            + 'The last paragraph arrives late.\n')
    split = ill.split_at_position(body, plan_row())
    assert split['unread'] != ''


def test_the_unread_side_is_capped_by_characters_too():
    body = (SCENE.rstrip() + '\n\n'
            + '\n\n'.join('Long unread paragraph. ' * 40 for _ in range(3)))
    split = ill.split_at_position(body, plan_row())
    assert len(split['unread']) <= ill.UNREAD_CHARS + 200


@pytest.mark.parametrize('placement,state', [
    ('after_anchor', 'normal'),
    ('before_anchor', 'normal'),
    ('scene_open', 'establishing'),
    ('scene_close', 'at_scene_end'),
])
def test_the_split_state_is_named_not_derived(placement, state):
    assert ill.split_at_position(
        SCENE, plan_row(placement=placement))['state'] == state


def test_an_unresolvable_anchor_is_the_unknown_state():
    split = ill.split_at_position(SCENE, plan_row(anchor='not in this prose'))
    assert split['state'] == 'unknown'
    assert split['offset'] is None


def test_only_the_normal_state_carries_a_next_sentence():
    """Invariant 3, which nothing asserted while three consumers relied on it.

    An opener's following prose is what it depicts, so a quoted "next sentence"
    there would ask the author to reject a correct image.
    """
    for placement in ('before_anchor', 'after_anchor', 'scene_open',
                      'scene_close'):
        split = ill.split_at_position(SCENE, plan_row(placement=placement))
        assert bool(split['next_sentence']) == (split['state'] == 'normal'), \
            placement


def test_reading_position_sets_exactly_one_of_offset_and_error():
    """The one invariant `ReadingPosition` cannot state in its own types."""
    rows = [plan_row(), plan_row(placement='scene_open'),
            plan_row(placement='scene_close'), plan_row(placement='sideways'),
            plan_row(anchor=''), plan_row(anchor='absent from the prose')]
    for row in rows:
        position = ill.reading_position(SCENE, row)
        assert (position['offset'] is None) == bool(position['error']), row


def test_the_split_strips_frontmatter_so_the_predicate_is_actually_shared():
    """`--prompts` did not strip it while `--embed` and the spoiler check did, so
    three consumers computed three offsets for one row and the author was shown
    YAML quoted as "the next sentence the reader reads"."""
    split = ill.split_at_position(SCENE_WITH_FRONTMATTER, plan_row())
    assert '---' not in split['read']
    assert 'title:' not in split['read'] and 'title:' not in split['unread']
    assert 'title:' not in split['next_sentence']


def test_first_sentence_keeps_a_closing_quote():
    """Dialogue ending a sentence is ubiquitous; without the quote branch the
    check quotes two sentences and points past the beat that matters."""
    assert ill.first_sentence('She said, "Go now." He did not move. More.') == \
        'She said, "Go now."'


def test_first_sentence_without_a_terminator_returns_the_whole_text():
    assert ill.first_sentence('no terminator here') == 'no terminator here'


def test_first_sentence_collapses_whitespace():
    """The quote lands in a markdown bullet, where a newline ends the bullet."""
    assert ill.first_sentence('Dawn\ncame  slowly. Then more.') == \
        'Dawn came slowly.'


def test_first_sentence_caps_a_runaway_sentence():
    sentence = ill.first_sentence('word ' * 200)
    assert len(sentence) <= ill.NEXT_SENTENCE_CHARS + 1
    assert sentence.endswith('…')


def test_first_sentence_of_nothing_is_nothing():
    assert ill.first_sentence('') == ''
    assert ill.first_sentence('   \n  ') == ''


# ============================================================================
# Art direction that already quotes the next page (#308 item 4)
# ============================================================================

def _write_prompt_body(project_dir, illus_id, body):
    """Write a minimal prompt file whose body `parse_prompt_file` recovers."""
    from storyforge import prompts_illustrate as pi
    rel = ill.default_prompt_rel(illus_id)
    path = os.path.join(project_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(pi.render_prompt_file(split=scene_split(), row=plan_row(id=illus_id), body=body,
                                      references=[]))
    return rel


def test_a_prompt_quoting_unread_prose_is_reported(project_dir):
    """How all three of #308's rows were found by hand."""
    write_scene(project_dir, 'vigil', SCENE)
    rel = _write_prompt_body(
        project_dir, 'lantern-vigil',
        '## Scene\n\nNothing came. The cold worked up through the '
        'floorboards, and she stood in it.\n')
    row = plan_row(prompt_file=rel)

    findings = ill.spoiler_findings(project_dir, row, SCENE)
    assert len(findings) == 1
    assert findings[0]['kind'] == 'prompt_spoils_unread'
    assert findings[0]['id'] == 'lantern-vigil'
    assert findings[0]['file'] == rel
    assert '--prompts --ids lantern-vigil' in findings[0]['detail']


def test_a_prompt_describing_only_read_prose_is_clean(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    rel = _write_prompt_body(
        project_dir, 'lantern-vigil',
        '## Scene\n\nShe set it on the sill and waited for the street to '
        'answer, in a cold room.\n')
    assert ill.spoiler_findings(
        project_dir, plan_row(prompt_file=rel), SCENE) == []


def test_language_shared_with_the_read_side_is_not_a_spoiler(project_dir):
    """"Distinctive" is a set difference. A phrase the reader has already read is
    what the body is *supposed* to describe, even if it recurs later."""
    scene = ('She set it on the sill and waited.\n\n'
             'The cold worked up through the floorboards.\n\n'
             'She set it on the sill and waited.\n')
    write_scene(project_dir, 'vigil', scene)
    rel = _write_prompt_body(project_dir, 'lantern-vigil',
                             '## Scene\n\nShe set it on the sill and waited.\n')
    row = plan_row(prompt_file=rel, anchor='The cold worked up',
                   placement='after_anchor')
    assert ill.spoiler_findings(project_dir, row, scene) == []


def test_no_prompt_file_is_not_a_finding(project_dir):
    """Unprompted is valid in-flight state — the one genuinely empty path."""
    write_scene(project_dir, 'vigil', SCENE)
    assert ill.spoiler_findings(project_dir, plan_row(), SCENE) == []


def test_the_shingle_length_discriminates(project_dir):
    """The threshold is a correctness boundary, not a tuning knob: the docstring
    cites it to justify reporting a finding rather than a hint. Both 4 and 9 left
    the whole suite green."""
    scene = ('She set it on the sill.\n\n'
             'The cold worked up through the floorboards of the house.\n')
    write_scene(project_dir, 'vigil', scene)

    five = _write_prompt_body(project_dir, 'lantern-vigil',
                             '## Scene\n\nthe cold worked up through in a room.\n')
    assert ill.spoiler_findings(
        project_dir, plan_row(prompt_file=five), scene) == []

    six = _write_prompt_body(project_dir, 'lantern-vigil',
                            '## Scene\n\nthe cold worked up through the '
                            'floorboards of a room.\n')
    found = ill.spoiler_findings(project_dir, plan_row(prompt_file=six), scene)
    assert [f['kind'] for f in found] == ['prompt_spoils_unread']


def test_an_opener_is_never_a_spoiler(project_dir):
    """`scene_open` had `read == ''`, which made the set difference vacuous — so
    every correct full-page opener was flagged, and the remedy told the author to
    re-render it. A permanent pending row in cleanup-report.csv on every book."""
    write_scene(project_dir, 'vigil', SCENE)
    rel = _write_prompt_body(
        project_dir, 'lantern-vigil',
        '## Scene\n\nThe lantern guttered once and held on a cold sill.\n')
    row = plan_row(prompt_file=rel, placement='scene_open', layout='full_page')
    assert ill.spoiler_findings(project_dir, row, SCENE) == []


def test_a_phrase_read_early_in_a_long_scene_is_not_a_spoiler(project_dir):
    """The subtrahend must be all the prose before the split, not the capped
    read window — a refrain met early and met again after the anchor was flagged
    because it had fallen outside READ_CHARS."""
    refrain = 'the lamp would not answer her at all'
    scene = ((refrain + '. ') * 3 + 'Filler prose that runs on and on. ' * 70
             + '\n\nShe set it on the sill.\n\n' + refrain + '.\n')
    write_scene(project_dir, 'vigil', scene)
    rel = _write_prompt_body(project_dir, 'lantern-vigil',
                             f'## Scene\n\nA room where {refrain}.\n')
    row = plan_row(prompt_file=rel)

    assert refrain not in ill.split_at_position(scene, row)['read']
    assert ill.spoiler_findings(project_dir, row, scene) == []


def test_a_prompt_file_that_is_not_on_disk_is_unchecked_not_clean(project_dir):
    """`[]` put "could not check" and "checked and clean" in the same cell of
    working/cleanup-report.csv, where the difference is invisible forever."""
    write_scene(project_dir, 'vigil', SCENE)
    row = plan_row(prompt_file='reference/illustration-prompts/gone.md')
    found = ill.spoiler_findings(project_dir, row, SCENE)
    assert [f['kind'] for f in found] == ['prompt_spoiler_unchecked']
    assert 'not on disk' in found[0]['detail']


def test_an_unresolved_position_is_unchecked_not_clean(project_dir):
    """Guessing a position would warn about prose that may not be after the image.
    Reporting nothing would say the row was checked. Neither is true."""
    write_scene(project_dir, 'vigil', SCENE)
    rel = _write_prompt_body(project_dir, 'lantern-vigil',
                             '## Scene\n\nNothing came. The cold worked up '
                             'through the floorboards here.\n')
    row = plan_row(prompt_file=rel, anchor='a phrase that is not in the prose')
    found = ill.spoiler_findings(project_dir, row, SCENE)
    assert [f['kind'] for f in found] == ['prompt_spoiler_unchecked']
    assert 'anchor not found' in found[0]['detail']


def test_an_unrecoverable_prompt_body_is_unchecked_not_clean(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    rel = ill.default_prompt_rel('lantern-vigil')
    path = os.path.join(project_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# Illustration prompt — lantern-vigil\n\nno prompt section\n')
    found = ill.spoiler_findings(project_dir, plan_row(prompt_file=rel), SCENE)
    assert [f['kind'] for f in found] == ['prompt_spoiler_unchecked']
    assert 'no_prompt_section' in found[0]['detail']


def test_an_unreadable_prompt_file_reports_rather_than_raising(project_dir):
    """`validate_plan` is the single finding collector; an error out of it takes
    every other check down with it — the #298 regression shape."""
    write_scene(project_dir, 'vigil', SCENE)
    rel = _write_prompt_body(project_dir, 'lantern-vigil', '## Scene\n\nX.\n')
    path = os.path.join(project_dir, rel)
    os.chmod(path, 0o000)
    try:
        if os.access(path, os.R_OK):        # running as root
            pytest.skip('cannot make a file unreadable as root')
        found = ill.spoiler_findings(
            project_dir, plan_row(prompt_file=rel), SCENE)
        assert [f['kind'] for f in found] == ['prompt_spoiler_unchecked']
        assert 'could not read' in found[0]['detail']
    finally:
        os.chmod(path, 0o644)


def test_an_undecodable_prompt_file_does_not_escape_validate_plan(project_dir):
    """UnicodeDecodeError is a ValueError, not an OSError, so it walked straight
    out of the single finding collector. A prompt body hand-edited and saved as
    latin-1 does it, and hand-editing is the documented working fix."""
    write_scene(project_dir, 'vigil', SCENE)
    rel = ill.default_prompt_rel('lantern-vigil')
    path = os.path.join(project_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'## Prompt\n\nA caf\xe9 at dusk \x97 warm light.\n')
    ill.write_plan(project_dir, [plan_row(prompt_file=rel)])

    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'prompt_spoiler_unchecked' in kinds


def test_the_spoiler_finding_reaches_validate_plan(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    rel = _write_prompt_body(
        project_dir, 'lantern-vigil',
        '## Scene\n\nNothing came. The cold worked up through the '
        'floorboards.\n')
    ill.write_plan(project_dir, [plan_row(prompt_file=rel)])

    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'prompt_spoils_unread' in kinds


def test_the_spoiler_finding_leaves_a_publishable_book():
    assert ill.severity_of('prompt_spoils_unread') == 'warning'
    assert 'prompt_spoils_unread' not in ill.BLOCKING_FINDINGS


# ============================================================================
# Resolution — epub / PDF
# ============================================================================

def test_resolve_for_local_emits_markdown_image(project_dir):
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='ingested',
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])

    inserted = ill.insert_marker(SCENE, plan_row())['text']
    resolved = ill.resolve_for_local(project_dir, inserted,
                                     relative_to=project_dir)

    assert '![A woman waits at a lit window](manuscript/assets/illustrations/' \
           'lantern-vigil.png)' in resolved
    assert '![[illus:' not in resolved


def test_resolve_for_local_drops_unrendered_illustrations(project_dir):
    """An in-flight book must still assemble."""
    ill.write_plan(project_dir, [plan_row()])  # planned, no file
    inserted = ill.insert_marker(SCENE, plan_row())['text']

    resolved = ill.resolve_for_local(project_dir, inserted)
    assert '![[illus:' not in resolved
    assert 'lantern-vigil' not in resolved
    assert 'She set it on the sill' in resolved


def test_resolve_for_local_drops_markers_with_no_plan_row(project_dir):
    ill.write_plan(project_dir, [plan_row(id='other', scene_id='x')])
    resolved = ill.resolve_for_local(project_dir, 'a\n\n![[illus:ghost]]\n\nb\n')
    assert '![[illus:' not in resolved


def test_resolve_for_local_with_no_plan_strips_markers(project_dir):
    resolved = ill.resolve_for_local(project_dir, 'a\n\n![[illus:x]]\n\nb\n')
    assert resolved == 'a\n\nb\n'


def test_resolve_alt_text_escapes_brackets(project_dir):
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 4, 4)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', beat='A window [at night]',
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])
    resolved = ill.resolve_for_local(
        project_dir, '![[illus:lantern-vigil]]\n', relative_to=project_dir)
    assert '![A window (at night)]' in resolved


def test_resolve_falls_back_to_subject_then_id(project_dir):
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 4, 4)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', beat='', subject='A lit sill',
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])
    resolved = ill.resolve_for_local(
        project_dir, '![[illus:lantern-vigil]]\n', relative_to=project_dir)
    assert '![A lit sill]' in resolved


# ============================================================================
# Resolution — publish manifest placements
# ============================================================================

def test_count_top_level_paragraphs_ignores_nested():
    html = ('<p>one</p><blockquote><p>quoted</p></blockquote>'
            '<hr /><p>two</p>')
    assert ill.count_top_level_paragraphs(html) == 2


def test_count_top_level_paragraphs_ignores_void_elements():
    assert ill.count_top_level_paragraphs('<p>a</p><br /><img src="x"><p>b</p>') == 2


@pytest.mark.parametrize('markdown,expected', [
    ('![[illus:a]]\n\nOne.\n\nTwo.\n', 0),
    ('One.\n\n![[illus:a]]\n\nTwo.\n', 1),
    ('One.\n\nTwo.\n\n![[illus:a]]\n', 2),
    ('# Heading\n\nOne.\n\n![[illus:a]]\n\nTwo.\n', 1),
    ('One.\n\n> A quotation.\n\n![[illus:a]]\n\nTwo.\n', 1),
    ('One.\n\n---\n\n![[illus:a]]\n\nTwo.\n', 1),
    ('One.\n\n- a\n- b\n\n![[illus:a]]\n\nTwo.\n', 1),
])
def test_scene_placements_across_block_types(markdown, expected):
    placements = ill.scene_placements(markdown, pandoc_html)
    assert placements == [{'key': 'a', 'after_paragraph': expected}]


def test_scene_placements_multiple_markers():
    markdown = ('One.\n\n![[illus:a]]\n\nTwo.\n\nThree.\n\n'
                '![[illus:b]]\n\nFour.\n')
    assert ill.scene_placements(markdown, pandoc_html) == [
        {'key': 'a', 'after_paragraph': 1},
        {'key': 'b', 'after_paragraph': 3},
    ]


def test_scene_placements_empty_without_markers():
    assert ill.scene_placements(SCENE, pandoc_html) == []


def test_scene_placements_ignores_earlier_markers_in_the_count():
    """An earlier marker must not shift a later marker's paragraph index."""
    markdown = 'One.\n\n![[illus:a]]\n\nTwo.\n\n![[illus:b]]\n\nThree.\n'
    placements = ill.scene_placements(markdown, pandoc_html)
    assert placements[1] == {'key': 'b', 'after_paragraph': 2}


def test_manifest_assets_only_includes_ingested_rows(project_dir):
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 12, 20)
    ill.write_plan(project_dir, [
        plan_row(status='ingested', sha256='a' * 64, width='12', height='20',
                 asset_file=ill.default_asset_rel('lantern-vigil')),
        plan_row(id='not-yet', status='planned'),
    ])

    assets = ill.manifest_assets(project_dir)
    assert assets == [{
        'key': 'lantern-vigil', 'role': 'illustration',
        'sha256': 'a' * 64, 'extension': 'png',
        'width': 12, 'height': 20,
        'alt_text': 'A woman waits at a lit window',
    }]


def test_manifest_assets_skips_rows_without_a_digest(project_dir):
    ill.write_plan(project_dir, [plan_row(
        status='ingested', asset_file=ill.default_asset_rel('lantern-vigil'),
    )])
    assert ill.manifest_assets(project_dir) == []


def test_manifest_assets_respects_used_keys(project_dir):
    ill.write_plan(project_dir, [
        plan_row(status='ingested', sha256='a' * 64,
                 asset_file=ill.default_asset_rel('lantern-vigil')),
        plan_row(id='unused', status='ingested', sha256='b' * 64,
                 asset_file=ill.default_asset_rel('unused')),
    ])
    assets = ill.manifest_assets(project_dir, used_keys={'lantern-vigil'})
    assert [a['key'] for a in assets] == ['lantern-vigil']


def test_manifest_assets_carries_non_png_extension(project_dir):
    ill.write_plan(project_dir, [plan_row(
        status='ingested', sha256='c' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil', '.webp'),
    )])
    assert ill.manifest_assets(project_dir)[0]['extension'] == 'webp'


def test_manifest_assets_omits_non_numeric_dimensions(project_dir):
    ill.write_plan(project_dir, [plan_row(
        status='ingested', sha256='d' * 64, width='wide', height='',
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])
    asset = ill.manifest_assets(project_dir)[0]
    assert 'width' not in asset and 'height' not in asset


# ============================================================================
# Image inspection
# ============================================================================

def test_sha256_of_matches_hashlib(tmp_path):
    import hashlib
    path = make_png(str(tmp_path / 'a.png'), 4, 4)
    with open(path, 'rb') as f:
        expected = hashlib.sha256(f.read()).hexdigest()
    assert ill.sha256_of(path) == expected


def test_png_dimensions(tmp_path):
    assert ill.image_dimensions(make_png(str(tmp_path / 'a.png'), 37, 91)) == (37, 91)


def test_jpeg_dimensions_skips_app0(tmp_path):
    assert ill.image_dimensions(make_jpeg(str(tmp_path / 'a.jpg'), 64, 48)) == (64, 48)


def test_webp_vp8x_dimensions(tmp_path):
    assert ill.image_dimensions(make_webp(str(tmp_path / 'a.webp'), 100, 200)) == (100, 200)


def test_dimensions_of_non_image_is_none(tmp_path):
    path = tmp_path / 'notanimage.png'
    path.write_bytes(b'this is not a png')
    assert ill.image_dimensions(str(path)) is None


def test_dimensions_of_truncated_png_is_none(tmp_path):
    path = tmp_path / 'trunc.png'
    path.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00')
    assert ill.image_dimensions(str(path)) is None


def test_dimensions_of_missing_file_is_none(tmp_path):
    assert ill.image_dimensions(str(tmp_path / 'nope.png')) is None


def test_dimensions_of_empty_file_is_none(tmp_path):
    path = tmp_path / 'empty.png'
    path.write_bytes(b'')
    assert ill.image_dimensions(str(path)) is None


@pytest.mark.parametrize('name,supported', [
    ('a.png', True), ('a.PNG', True), ('a.jpg', True), ('a.jpeg', True),
    ('a.webp', True), ('a.gif', False), ('a.svg', False), ('a', False),
])
def test_is_supported_image(name, supported):
    assert ill.is_supported_image(name) is supported


# ============================================================================
# Reporting
# ============================================================================

def test_plan_report_counts_by_status_and_embedding(project_dir):
    write_scene(project_dir, 'vigil',
                ill.insert_marker(SCENE, plan_row())['text'])
    write_scene(project_dir, 'other', SCENE)
    ill.write_plan(project_dir, [
        plan_row(status='ingested'),
        plan_row(id='pending', scene_id='other', status='planned'),
        plan_row(id='dropped', scene_id='other', status='superseded'),
    ])

    report = ill.plan_report(project_dir)
    assert report['total'] == 3
    assert report['by_status'] == {'ingested': 1, 'planned': 1, 'superseded': 1}
    assert report['ingested'] == ['lantern-vigil']
    assert report['awaiting_render'] == ['pending']
    assert report['next_unrendered'] == 'pending'
    assert report['embedded'] == ['lantern-vigil']
    assert report['unembedded'] == ['pending']


def test_plan_report_on_empty_plan(project_dir):
    report = ill.plan_report(project_dir)
    assert report['total'] == 0
    assert report['next_unrendered'] == ''


# ============================================================================
# Validation
# ============================================================================

def test_validate_clean_plan_has_no_findings(project_dir):
    write_scene(project_dir, 'vigil',
                ill.insert_marker(SCENE, plan_row())['text'])
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])
    assert ill.validate_plan(project_dir) == []


def test_unrendered_row_is_not_a_finding(project_dir):
    """In-flight state, matching the GN unrendered-page posture."""
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(status='planned')])
    assert ill.validate_plan(project_dir) == []


def test_validate_orphan_marker(project_dir):
    write_scene(project_dir, 'vigil', 'One.\n\n![[illus:ghost]]\n\nTwo.\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'orphan_marker' in kinds


def test_validate_duplicate_marker(project_dir):
    write_scene(project_dir, 'vigil',
                'One.\n\n![[illus:lantern-vigil]]\n\nTwo.\n\n'
                '![[illus:lantern-vigil]]\n\nThree.\n')
    ill.write_plan(project_dir, [plan_row(anchor='')])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'duplicate_marker']
    assert len(findings) == 1
    assert 'appears 2' in findings[0]['detail']


def test_validate_missing_file(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'missing_file']
    assert len(findings) == 1


def test_validate_ingested_row_with_no_asset_file(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(status='ingested')])
    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'missing_file']
    assert 'asset_file is empty' in findings[0]['detail']


def test_validate_missing_digest(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', asset_file=ill.default_asset_rel('lantern-vigil'),
    )])

    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'missing_digest' in kinds


def test_validate_orphan_file(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'nobody-claims-me.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(status='planned')])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'orphan_file']
    assert len(findings) == 1
    assert 'nobody-claims-me.png' in findings[0]['file']


def test_validate_anchor_drift(project_dir):
    write_scene(project_dir, 'vigil', 'Entirely rewritten prose.\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'anchor_drift']
    assert len(findings) == 1
    assert findings[0]['scene_id'] == 'vigil'


def test_validate_anchor_ambiguous(project_dir):
    write_scene(project_dir, 'vigil',
                'She set it on the sill.\n\nAgain: She set it on the sill.\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'anchor_ambiguous']
    assert len(findings) == 1


def test_validate_duplicate_id(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(), plan_row()])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'duplicate_id' in kinds


def test_validate_invalid_id(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(id='Lantern Vigil')])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'invalid_id' in kinds


def test_validate_invalid_status_and_placement(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(status='rendering',
                                         placement='diagonally')])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'invalid_status' in kinds
    assert 'invalid_placement' in kinds


def test_validate_unknown_and_missing_scene(project_dir):
    ill.write_plan(project_dir, [
        plan_row(scene_id='nonexistent'),
        plan_row(id='no-scene', scene_id=''),
    ])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'unknown_scene' in kinds
    assert 'missing_scene' in kinds


def test_superseded_rows_skip_file_and_anchor_checks(project_dir):
    write_scene(project_dir, 'vigil', 'Entirely rewritten prose.\n')
    ill.write_plan(project_dir, [plan_row(
        status='superseded', asset_file=ill.default_asset_rel('lantern-vigil'),
    )])
    assert ill.validate_plan(project_dir) == []


def test_validate_empty_project_has_no_findings(project_dir):
    assert ill.validate_plan(project_dir) == []


@pytest.mark.parametrize('kind,severity', [
    ('anchor_drift', 'warning'),
    ('anchor_ambiguous', 'warning'),
    ('orphan_file', 'warning'),
    ('orphan_marker', 'error'),
    ('missing_file', 'error'),
    ('duplicate_marker', 'error'),
    ('something_new', 'error'),
])
def test_severity_of(kind, severity):
    assert ill.severity_of(kind) == severity


# ============================================================================
# Selection pre-pass
# ============================================================================

def test_prepass_reports_uncovered_spine_events(project_dir):
    write_csv(project_dir, 'spine.csv', 'id|seq|title|summary|function|part', [
        'e1|1|The Assignment|A crown order arrives.|inciting|1',
        'e2|2|The Blank|The village is missing.|turn|1',
    ])
    prepass = ill.selection_prepass(project_dir)
    assert {e['id'] for e in prepass['uncovered_spine_events']} == {'e1', 'e2'}


def test_prepass_marks_spine_event_covered_through_architecture(project_dir):
    write_csv(project_dir, 'spine.csv', 'id|seq|title|summary', [
        'e1|1|The Assignment|A crown order arrives.',
        'e2|2|The Blank|The village is missing.',
    ])
    write_csv(project_dir, 'architecture.csv', 'id|seq|title|summary|spine_event', [
        'a1|1|Office|She measures.|e1',
    ])
    write_csv(project_dir, 'scenes.csv', 'id|seq|title|architecture_scene', [
        'vigil|1|Vigil|a1',
    ])
    ill.write_plan(project_dir, [plan_row(status='planned')])

    prepass = ill.selection_prepass(project_dir)
    assert [e['id'] for e in prepass['uncovered_spine_events']] == ['e2']
    assert prepass['covered_scenes'] == ['vigil']


def test_prepass_collects_turning_points_and_value_shifts(project_dir):
    write_csv(
        project_dir, 'architecture.csv',
        'id|seq|title|summary|turning_point|value_shift', [
            'a1|1|Office|She measures.|revelation|',
            'a2|2|Study|She reads.||positive-to-negative',
            'a3|3|Road|She walks.||',
        ])
    prepass = ill.selection_prepass(project_dir)
    assert {t['architecture_scene'] for t in prepass['turning_point_scenes']} \
        == {'a1', 'a2'}


def test_prepass_attaches_emotional_arc_to_turning_points(project_dir):
    write_csv(project_dir, 'architecture.csv',
              'id|seq|title|summary|turning_point', ['a1|1|Office|x|revelation'])
    write_csv(project_dir, 'scenes.csv', 'id|seq|architecture_scene',
              ['vigil|1|a1'])
    write_csv(project_dir, 'scene-intent.csv', 'id|emotional_arc',
              ['vigil|pride to dread'])

    turning = ill.selection_prepass(project_dir)['turning_point_scenes'][0]
    assert turning['emotional_arc'] == 'pride to dread'
    assert turning['scene_id'] == 'vigil'


def test_prepass_detects_motif_payoff_at_third_appearance(project_dir):
    write_csv(project_dir, 'scene-briefs.csv', 'id|goal|motifs', [
        's1|x|lantern;ink',
        's2|x|lantern',
        's3|x|lantern',
        's4|x|lantern',
    ])
    prepass = ill.selection_prepass(project_dir)
    payoff = {p['motif']: p for p in prepass['motif_payoffs']}
    assert payoff['lantern']['appearances'] == '4'
    assert payoff['lantern']['payoff_scene'] == 's3'
    assert 'ink' in prepass['motif_singletons']


def test_prepass_reports_motifs_never_used_in_a_brief(project_dir):
    write_csv(project_dir, 'motif-taxonomy.csv', 'id|name|description',
              ['m1|compass|A brass compass.'])
    write_csv(project_dir, 'scene-briefs.csv', 'id|goal|motifs', ['s1|x|lantern'])
    assert 'compass' in ill.selection_prepass(project_dir)['motif_singletons']


def test_prepass_reports_chapter_gaps_and_clustering(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|title|heading|part|scenes', [
        '1|One|numbered|1|s1;s2;s3',
        '2|Two|numbered|1|s4',
    ])
    ill.write_plan(project_dir, [
        plan_row(id='i1', scene_id='s1'),
        plan_row(id='i2', scene_id='s2'),
        plan_row(id='i3', scene_id='s3'),
    ])
    prepass = ill.selection_prepass(project_dir)
    assert prepass['uncovered_chapters'] == ['2']
    assert prepass['clustered_chapters'] == ['1']
    assert prepass['chapter_count'] == 2


def test_prepass_ignores_superseded_rows(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes', ['1|s1'])
    ill.write_plan(project_dir, [
        plan_row(id='dropped', scene_id='s1', status='superseded'),
    ])
    prepass = ill.selection_prepass(project_dir)
    assert prepass['planned_count'] == 0
    assert prepass['uncovered_chapters'] == ['1']


@pytest.mark.parametrize('chapters,spine,scenes,expected', [
    (0, 0, 0, 0),      # empty project
    (15, 7, 40, 7),    # a novel — roughly one every 2.5 chapters
    (3, 5, 8, 3),      # a novella floors at 3
    (60, 10, 200, 24),
])
def test_recommend_count(chapters, spine, scenes, expected):
    assert ill._recommend_count(chapters, spine, scenes) == expected


def test_prepass_is_empty_with_no_structural_data(tmp_path):
    """Nothing to argue about means nothing to spend an LLM call on."""
    bare = tmp_path / 'bare'
    (bare / 'reference').mkdir(parents=True)
    assert ill.prepass_is_empty(ill.selection_prepass(str(bare))) is True


def test_prepass_is_not_empty_when_chapters_lack_illustrations(project_dir):
    """The fixture has a chapter map and no plan — every chapter is a gap."""
    prepass = ill.selection_prepass(project_dir)
    assert prepass['uncovered_chapters']
    assert ill.prepass_is_empty(prepass) is False


def test_prepass_is_not_empty_when_a_gap_exists(project_dir):
    write_csv(project_dir, 'spine.csv', 'id|title|summary', ['e1|One|x'])
    assert ill.prepass_is_empty(ill.selection_prepass(project_dir)) is False


# ============================================================================
# Art-direction document
# ============================================================================

def test_read_direction_parses_every_section(project_dir):
    write_direction_file(project_dir, SAMPLE_DIRECTION)
    direction = ill.read_direction(project_dir)
    assert set(direction) == set(ill.DIRECTION_SECTIONS)
    assert direction['Format'].startswith('Full-color, cinematic')
    assert 'Never horror imagery' in direction['Content limits']


def test_read_direction_keeps_author_added_sections(project_dir):
    write_direction_file(project_dir, SAMPLE_DIRECTION
                         + '\n## Endpaper treatment\n\nMarbled paper.\n')
    assert ill.read_direction(project_dir)['Endpaper treatment'] == \
        'Marbled paper.'


def test_read_direction_with_no_file(project_dir):
    assert ill.read_direction(project_dir) == {}


# Continuity anchors and book-level placeholder detection now live in
# `reference/canon/` (see storyforge.canon and prompts_illustrate.CANON_PLAN):
# `read_continuity_anchors`, `has_direction`, and `missing_direction_sections`
# are gone. Equivalent coverage: canon.anchor_texts in
# test_illustration_canon.py, and canon._section_body_is_placeholder in
# test_canon_files.py. `read_direction` itself survives above only for
# `illustrations._direction_anchor_mismatches`, the hand-edit safety net.


# ============================================================================
# Layout and the published asset key
# ============================================================================

@pytest.mark.parametrize('layout,valid', [
    ('full_page', True), ('half_page', True), ('double_page', True),
    ('inline', True), ('quarter_page', False),
])
def test_layout_validation(project_dir, layout, valid):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(layout=layout, status='planned')])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert ('invalid_layout' in kinds) is (not valid)


def test_empty_layout_is_allowed(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(layout='', status='planned')])
    assert ill.validate_plan(project_dir) == []


@pytest.mark.parametrize('illus_id', ['LF-01', 'lf-01', 'the-first-lantern',
                                      'LF_01', 'A1'])
def test_ids_the_marker_accepts_also_validate(project_dir, illus_id):
    """The sample plan uses `LF-01`; validation must not reject what parses."""
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(id=illus_id, status='planned')])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'invalid_id' not in kinds
    assert ill.MARKER_LINE_RE.fullmatch(ill.marker_for(illus_id)) is not None


@pytest.mark.parametrize('illus_id', ['Lantern Vigil', 'lantern.vigil',
                                      '-leading-dash', ''])
def test_ids_the_marker_rejects_are_flagged(project_dir, illus_id):
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(id=illus_id, status='planned')])
    rows = ill.read_plan(project_dir)
    if not rows:           # an empty id is dropped at read time
        return
    assert 'invalid_id' in {f['kind'] for f in ill.validate_plan(project_dir)}


def test_asset_key_lowercases_but_the_plan_keeps_case():
    assert ill.asset_key('LF-01') == 'lf-01'
    assert ill.asset_key('  LF-01 ') == 'lf-01'


def test_placement_and_asset_keys_agree(project_dir):
    """A mismatch here would publish a placement pointing at no asset."""
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR, 'LF-01.png'),
             8, 8)
    ill.write_plan(project_dir, [plan_row(
        id='LF-01', status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('LF-01'),
    )])
    marked = ill.insert_marker(SCENE, plan_row(id='LF-01'))['text']

    placements = ill.scene_placements(marked, pandoc_html)
    assets = ill.manifest_assets(project_dir)
    assert placements[0]['key'] == 'lf-01'
    assert assets[0]['key'] == 'lf-01'


def test_used_keys_accepts_either_namespace(project_dir):
    """Passing plan ids used to silently yield zero assets — and then a
    misleading "not ingested" warning from generate_publish_manifest."""
    ill.write_plan(project_dir, [plan_row(
        id='LF-01', status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('LF-01'),
    )])
    assert len(ill.manifest_assets(project_dir, used_keys={'lf-01'})) == 1
    assert len(ill.manifest_assets(project_dir, used_keys={'LF-01'})) == 1
    assert ill.manifest_assets(project_dir, used_keys={'other'}) == []


def test_ids_differing_only_in_case_are_a_duplicate(project_dir):
    """Both would publish to the same asset key."""
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(id='LF-01', anchor=''),
                                 plan_row(id='lf-01', anchor='')])
    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'duplicate_id']
    assert len(findings) == 1
    assert 'only in case' in findings[0]['detail']


# ============================================================================
# Render order
# ============================================================================

def test_render_order_follows_the_chapter_map(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              ['1|s1;s2', '2|s3'])
    ill.write_plan(project_dir, [
        plan_row(id='third', scene_id='s3'),
        plan_row(id='first', scene_id='s1'),
        plan_row(id='second', scene_id='s2'),
    ])
    assert [s['id'] for s in ill.render_order(project_dir)] == \
        ['first', 'second', 'third']


def test_render_order_falls_back_to_scene_seq(project_dir):
    os.remove(os.path.join(project_dir, 'reference', 'chapter-map.csv'))
    write_csv(project_dir, 'scenes.csv', 'id|seq|title',
              ['b|2|Second', 'a|1|First'])
    ill.write_plan(project_dir, [plan_row(id='i2', scene_id='b'),
                                 plan_row(id='i1', scene_id='a')])
    assert [s['id'] for s in ill.render_order(project_dir)] == ['i1', 'i2']


def test_visual_key_establishes_the_most_and_renders_first(project_dir):
    """The sample plan renders LF-03 first because it establishes the most."""
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              ['1|s1', '2|s2', '3|s3'])
    ill.write_plan(project_dir, [
        plan_row(id='LF-01', scene_id='s1', canon_refs='Nora'),
        plan_row(id='LF-02', scene_id='s2', canon_refs='Leo;Nora'),
        plan_row(id='LF-03', scene_id='s3',
                 canon_refs='Leo;Nora;Old Oak;village'),
    ])
    steps = ill.render_order(project_dir)

    assert steps[0]['id'] == 'LF-03'
    assert steps[0]['is_visual_key'] is True
    assert sum(1 for s in steps if s['is_visual_key']) == 1
    # Everything after the key stays in story order.
    assert [s['id'] for s in steps[1:]] == ['LF-01', 'LF-02']


def test_visual_key_tie_breaks_to_the_earlier_illustration(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              ['1|s1', '2|s2'])
    ill.write_plan(project_dir, [
        plan_row(id='early', scene_id='s1', canon_refs='Leo;Nora'),
        plan_row(id='late', scene_id='s2', canon_refs='Leo;Nora'),
    ])
    assert ill.render_order(project_dir)[0]['id'] == 'early'


def test_render_order_reports_what_each_illustration_locks(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              ['1|s1', '2|s2'])
    ill.write_plan(project_dir, [
        plan_row(id='LF-01', scene_id='s1', canon_refs='Leo;Nora'),
        plan_row(id='LF-02', scene_id='s2', canon_refs='Nora;Murkwolves'),
    ])
    steps = {s['id']: s for s in ill.render_order(project_dir)}
    # Each entity is locked by its first appearance only.
    assert steps['LF-01']['locks'] == ['Leo', 'Nora']
    assert steps['LF-02']['locks'] == ['Murkwolves']


def test_render_order_locks_are_case_insensitive(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes', ['1|s1;s2'])
    ill.write_plan(project_dir, [
        plan_row(id='a', scene_id='s1', canon_refs='Leo'),
        plan_row(id='b', scene_id='s2', canon_refs='leo'),
    ])
    steps = {s['id']: s for s in ill.render_order(project_dir)}
    assert steps['b']['locks'] == []


def test_render_order_with_no_canon_refs_has_no_visual_key(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes', ['1|s1;s2'])
    ill.write_plan(project_dir, [plan_row(id='a', scene_id='s1'),
                                 plan_row(id='b', scene_id='s2')])
    steps = ill.render_order(project_dir)
    assert [s['id'] for s in steps] == ['a', 'b']
    assert not any(s['is_visual_key'] for s in steps)


def test_render_order_skips_superseded(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes', ['1|s1;s2'])
    ill.write_plan(project_dir, [
        plan_row(id='keep', scene_id='s1'),
        plan_row(id='dropped', scene_id='s2', status='superseded'),
    ])
    assert [s['id'] for s in ill.render_order(project_dir)] == ['keep']


def test_render_order_is_empty_without_a_plan(project_dir):
    assert ill.render_order(project_dir) == []
    assert ill.next_to_render(project_dir) == ''


def test_next_to_render_follows_the_render_order(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              ['1|s1', '2|s2', '3|s3'])
    ill.write_plan(project_dir, [
        plan_row(id='LF-01', scene_id='s1', canon_refs='Nora',
                 status='ingested'),
        plan_row(id='LF-02', scene_id='s2'),
        plan_row(id='LF-03', scene_id='s3', canon_refs='Leo;Nora;Oak'),
    ])
    # The visual key comes first and is unrendered, so it is next.
    assert ill.next_to_render(project_dir) == 'LF-03'


def test_next_to_render_is_empty_when_all_are_ingested(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes', ['1|s1'])
    ill.write_plan(project_dir, [plan_row(scene_id='s1', status='ingested')])
    assert ill.next_to_render(project_dir) == ''


def test_illustration_with_an_unmapped_scene_sorts_last(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes', ['1|s1'])
    ill.write_plan(project_dir, [plan_row(id='orphan', scene_id='unmapped'),
                                 plan_row(id='mapped', scene_id='s1')])
    assert [s['id'] for s in ill.render_order(project_dir)] == \
        ['mapped', 'orphan']


def test_visual_key_is_never_the_climax(project_dir):
    """The biggest establisher is usually the climax; the key must still be early.

    Regression from the real lantern-folk plan: the double-page climax names
    the most entities because it is where everyone converges, and the first
    implementation picked it. Rendering the payoff before anything is
    established is backwards — the key exists so later images can reference it.
    """
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              [f'{i}|s{i}' for i in range(1, 13)])
    rows = [plan_row(id=f'LF-{i:02}', scene_id=f's{i}', canon_refs='Nora')
            for i in range(1, 13)]
    rows[2]['canon_refs'] = 'Leo;Nora;Oak'          # early establisher
    rows[10]['canon_refs'] = 'Leo;Nora;Oak;Ember;Wick;Murkwolves'  # climax

    ill.write_plan(project_dir, rows)
    steps = ill.render_order(project_dir)

    assert steps[0]['id'] == 'LF-03'
    assert steps[0]['is_visual_key'] is True
    climax = next(s for s in steps if s['id'] == 'LF-11')
    assert climax['is_visual_key'] is False


def test_visual_key_horizon_still_chooses_on_a_short_plan(project_dir):
    """A three-illustration plan has no 'first third' worth the name."""
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              ['1|s1', '2|s2', '3|s3'])
    ill.write_plan(project_dir, [
        plan_row(id='a', scene_id='s1', canon_refs='Nora'),
        plan_row(id='b', scene_id='s2', canon_refs='Leo;Nora;Oak'),
        plan_row(id='c', scene_id='s3', canon_refs='Leo'),
    ])
    steps = ill.render_order(project_dir)
    assert steps[0]['id'] == 'b'
    assert steps[0]['is_visual_key'] is True


def test_visual_key_horizon_scales_with_plan_length(project_dir):
    """A late establisher outside the horizon is not eligible."""
    write_csv(project_dir, 'chapter-map.csv', 'chapter|scenes',
              [f'{i}|s{i}' for i in range(1, 31)])
    rows = [plan_row(id=f'i{i:02}', scene_id=f's{i}')
            for i in range(1, 31)]
    rows[0]['canon_refs'] = 'Leo'
    rows[29]['canon_refs'] = 'Leo;Nora;Oak;Ember'

    ill.write_plan(project_dir, rows)
    steps = ill.render_order(project_dir)
    assert steps[0]['id'] == 'i01'
    assert steps[0]['is_visual_key'] is True


# ============================================================================
# Data-destruction regressions
# ============================================================================

def test_upsert_collapses_a_duplicate_id_without_aliasing():
    """Regression: two comprehensions disagreed — the dict collapsed duplicates
    and the list did not — so the result held the same dict object twice and
    silently replaced the first row's cells with the duplicate's."""
    existing = [dict(plan_row(), beat='author wrote this'),
                dict(plan_row(id='other'), beat='second'),
                dict(plan_row(), beat='a later duplicate')]

    out = ill.upsert_rows(existing, [dict(plan_row(id='new'), beat='new')])

    assert [r['id'] for r in out] == ['lantern-vigil', 'other', 'new']
    # First row wins, matching read_plan_as_map.
    assert out[0]['beat'] == 'author wrote this'
    # No two entries are the same object.
    assert len({id(r) for r in out}) == len(out)


def test_incomplete_image_reason_detects_a_truncated_png(tmp_path):
    path = truncated_png(str(tmp_path / 'stub.png'), 800, 1200)
    # The naive guards both pass it — that is the whole problem.
    assert os.path.getsize(path) > 0
    assert ill.image_dimensions(path) == (800, 1200)
    reason = ill.incomplete_image_reason(path)
    assert reason is not None
    assert 'IEND' in reason


def test_incomplete_image_reason_accepts_a_complete_png(tmp_path):
    assert ill.incomplete_image_reason(
        make_png(str(tmp_path / 'ok.png'), 8, 8)) is None


def test_incomplete_image_reason_accepts_a_complete_jpeg(tmp_path):
    assert ill.incomplete_image_reason(
        make_jpeg(str(tmp_path / 'ok.jpg'), 8, 8)) is None


def test_incomplete_image_reason_detects_a_truncated_jpeg(tmp_path):
    path = tmp_path / 'stub.jpg'
    path.write_bytes(b'\xff\xd8' + b'\x00' * 40)   # SOI, no EOI
    reason = ill.incomplete_image_reason(str(path))
    assert reason is not None and 'EOI' in reason


@pytest.mark.parametrize('body,expected_fragment', [
    (b'', 'empty'),
    (b'\x89PNG\r\n\x1a\n', 'truncated'),
])
def test_incomplete_image_reason_edge_cases(tmp_path, body, expected_fragment):
    path = tmp_path / 'x.png'
    path.write_bytes(body)
    reason = ill.incomplete_image_reason(str(path))
    assert reason is not None and expected_fragment in reason


def test_incomplete_image_reason_on_a_missing_file(tmp_path):
    reason = ill.incomplete_image_reason(str(tmp_path / 'nope.png'))
    assert reason is not None


def test_replace_file_is_atomic_on_failure(tmp_path):
    """An interrupted copy must not truncate the destination."""
    dest = make_png(str(tmp_path / 'dest.png'), 40, 60)
    original = open(dest, 'rb').read()

    with pytest.raises(FileNotFoundError):
        ill.replace_file(str(tmp_path / 'does-not-exist.png'), dest)

    assert open(dest, 'rb').read() == original
    # No temp files left behind.
    assert not [p for p in os.listdir(tmp_path) if p.endswith('.part')]


def test_replace_file_replaces_on_success(tmp_path):
    dest = make_png(str(tmp_path / 'dest.png'), 40, 60)
    src = make_png(str(tmp_path / 'src.png'), 10, 20)
    ill.replace_file(src, dest)
    assert ill.image_dimensions(dest) == (10, 20)


# ============================================================================
# write_plan / read_plan fidelity
# ============================================================================

def test_write_plan_preserves_author_added_columns(project_dir):
    """The plan is a file authors are told to hand-edit."""
    path = ill.plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = '|'.join(ill.PLAN_COLUMNS + ['author_note'])
    with open(path, 'w') as f:
        f.write(header + '\n')
        f.write('lantern-vigil' + '|' * (len(ill.PLAN_COLUMNS) - 1)
                + '|keep me\n')

    rows = ill.read_plan(project_dir)
    assert rows[0]['author_note'] == 'keep me'

    ill.write_plan(project_dir, rows)          # a round-trip must not drop it
    assert ill.read_plan(project_dir)[0]['author_note'] == 'keep me'
    with open(path) as f:
        assert 'author_note' in f.readline()


def test_write_plan_sanitizes_pipes_and_newlines(project_dir):
    """An unescaped pipe shatters the row and its overflow is dropped on read."""
    ill.write_plan(project_dir, [plan_row(beat='a beat with | a pipe',
                                         rationale='line one\nline two')])
    with open(ill.plan_path(project_dir)) as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]

    assert len(lines) == 2                     # header + exactly one data row
    assert '"' not in lines[1]                 # no RFC-4180 quoting
    for line in lines:
        assert line.count('|') == len(ill.PLAN_COLUMNS) - 1

    row = ill.read_plan(project_dir)[0]
    assert row['beat'] == 'a beat with / a pipe'
    assert row['rationale'] == 'line one line two'


def test_read_plan_flags_a_shattered_row(project_dir):
    path = ill.plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(ill.PLAN_COLUMNS) + '\n')
        f.write('lantern-vigil|vigil|anchor'
                + '|' * (len(ill.PLAN_COLUMNS) - 3) + '|one extra\n')

    rows = ill.read_plan(project_dir)
    assert rows[0][ill._SHATTERED_FLAG] == '1'


def test_the_shattered_flag_never_becomes_a_column(project_dir):
    path = ill.plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(ill.PLAN_COLUMNS) + '\n')
        f.write('lantern-vigil' + '|' * (len(ill.PLAN_COLUMNS) - 1)
                + '|extra\n')

    ill.write_plan(project_dir, ill.read_plan(project_dir))
    with open(ill.plan_path(project_dir)) as f:
        assert ill._SHATTERED_FLAG not in f.readline()


def test_sanitize_cell():
    assert ill.sanitize_cell('a|b') == 'a/b'
    assert ill.sanitize_cell('a\nb\r') == 'a b'
    assert ill.sanitize_cell('  spaced  ') == 'spaced'


# ============================================================================
# Marker integrity
# ============================================================================

@pytest.mark.parametrize('placement,anchor', [
    ('scene_open', ''),
    ('scene_close', ''),
    ('after_anchor', 'She set it on the sill'),
    ('before_anchor', 'She set it on the sill'),
])
def test_insert_never_lands_above_yaml_frontmatter(placement, anchor):
    """Regression: a scene_open marker went above the frontmatter, so the file
    no longer started with `---`. Every frontmatter stripper tests exactly
    that, so the whole YAML block landed in the epub and inflated word_count."""
    result = ill.insert_marker(SCENE_WITH_FRONTMATTER,
                               plan_row(placement=placement, anchor=anchor))
    assert result['changed'], result['error']
    assert result['text'].startswith('---\n')
    assert 'drafted_at' in result['text']          # frontmatter intact
    # And the marker is in the prose, not inside the frontmatter block.
    _, body = ill._split_frontmatter(result['text'])
    assert ill.marker_ids(body) == ['lantern-vigil']


def test_frontmatter_scene_prose_has_no_yaml_after_insertion(tmp_path):
    from storyforge.assembly import extract_scene_prose
    path = tmp_path / 's.md'
    path.write_text(ill.insert_marker(
        SCENE_WITH_FRONTMATTER, plan_row(placement='scene_open',
                                        anchor=''))['text'])
    prose = extract_scene_prose(str(path))
    assert 'drafted_at' not in prose
    assert 'The lantern guttered' in prose


@pytest.mark.parametrize('text,expected', [
    ('no frontmatter here\n', ('', 'no frontmatter here\n')),
    ('---\na: 1\n---\nbody\n', ('---\na: 1\n---\n', 'body\n')),
    ('---\nunterminated\n', ('', '---\nunterminated\n')),
])
def test_split_frontmatter(text, expected):
    assert ill._split_frontmatter(text) == expected


def test_has_marker_sees_an_inline_marker(project_dir):
    """Otherwise --embed adds a second marker and the book shows it twice."""
    text = 'She waited ![[illus:lantern-vigil]] a long time.\n'
    assert ill.has_marker(text, 'lantern-vigil') is True
    assert ill.insert_marker(text, plan_row())['changed'] is False


def test_inline_marker_ids_excludes_own_line_markers():
    text = ('One ![[illus:inline-one]] here.\n\n'
            '![[illus:on-its-own-line]]\n\nTwo.\n')
    assert ill.inline_marker_ids(text) == ['inline-one']
    assert ill.marker_ids(text) == ['on-its-own-line']
    assert sorted(ill.all_marker_ids(text)) == ['inline-one',
                                                'on-its-own-line']


def test_resolve_strips_an_inline_marker_rather_than_leaking_it(project_dir):
    """A literal ![[illus:x]] in an epub is the visible defect the resolver
    exists to prevent — but it only substituted own-line markers."""
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', asset_file=ill.default_asset_rel('lantern-vigil'))])

    resolved = ill.resolve_for_local(
        project_dir, 'She waited ![[illus:lantern-vigil]] a long time.\n',
        relative_to=project_dir)
    assert '![[illus:' not in resolved
    assert 'She waited' in resolved


def test_superseded_illustrations_do_not_render(project_dir):
    """The epub shipped retired art while manifest_assets excluded it, so the
    two targets disagreed — the thing the single-marker design prevents."""
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='superseded', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'))])
    marked = ill.insert_marker(SCENE, plan_row())['text']

    resolved = ill.resolve_for_local(project_dir, marked,
                                     relative_to=project_dir)
    assert 'lantern-vigil.png' not in resolved
    assert '![[illus:' not in resolved
    # And the manifest agrees.
    assert ill.manifest_assets(project_dir) == []


# ============================================================================
# preserve_markers
# ============================================================================

def test_preserve_restores_a_marker_a_rewrite_dropped(project_dir):
    """A polish pass sends prose to a model and writes the response back. The
    model has no reason to reproduce a marker, and nothing downstream could
    tell the difference between dropped and never-embedded."""
    ill.write_plan(project_dir, [plan_row()])
    original = ill.insert_marker(SCENE, plan_row())['text']
    rewritten = SCENE                       # the model omitted the marker

    result = ill.preserve_markers(project_dir, original, rewritten)
    assert result['restored'] == ['lantern-vigil']
    assert result['lost'] == []
    assert ill.marker_ids(result['text']) == ['lantern-vigil']


def test_preserve_is_a_noop_when_the_marker_survived(project_dir):
    ill.write_plan(project_dir, [plan_row()])
    original = ill.insert_marker(SCENE, plan_row())['text']

    result = ill.preserve_markers(project_dir, original, original)
    assert result == {'text': original, 'restored': [], 'lost': []}


def test_preserve_reports_a_marker_it_cannot_restore(project_dir):
    """The rewrite dropped the marker AND changed the anchor prose."""
    ill.write_plan(project_dir, [plan_row()])
    original = ill.insert_marker(SCENE, plan_row())['text']

    result = ill.preserve_markers(project_dir, original,
                                  'Entirely rewritten prose.\n')
    assert result['restored'] == []
    assert result['lost'] == ['lantern-vigil']
    assert '![[illus:' not in result['text']


def test_preserve_reports_a_marker_with_no_plan_row(project_dir):
    result = ill.preserve_markers(project_dir,
                                  'a\n\n![[illus:ghost]]\n\nb\n', 'a\n\nb\n')
    assert result['lost'] == ['ghost']


def test_preserve_on_a_scene_with_no_markers(project_dir):
    result = ill.preserve_markers(project_dir, SCENE, 'rewritten\n')
    assert result == {'text': 'rewritten\n', 'restored': [], 'lost': []}


# ============================================================================
# New findings
# ============================================================================

def test_validate_reports_an_inline_marker(project_dir):
    write_scene(project_dir, 'vigil',
                'She waited ![[illus:lantern-vigil]] a long time.\n')
    ill.write_plan(project_dir, [plan_row(anchor='', status='planned')])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'inline_marker']
    assert len(findings) == 1
    assert 'own line' in findings[0]['detail']
    assert ill.severity_of('inline_marker') == 'warning'


def test_validate_reports_an_ingested_illustration_with_no_marker(project_dir):
    """The art exists and the plan points at it, so this is not in-flight
    state — the marker was never embedded or a rewrite dropped it."""
    write_scene(project_dir, 'vigil', SCENE)
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'))])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'unembedded_ingested']
    assert len(findings) == 1
    assert 'will not appear in the book' in findings[0]['detail']


def test_an_embedded_ingested_illustration_is_not_flagged(project_dir):
    write_scene(project_dir, 'vigil',
                ill.insert_marker(SCENE, plan_row())['text'])
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'))])
    assert ill.validate_plan(project_dir) == []


def test_validate_reports_a_shattered_row(project_dir):
    write_scene(project_dir, 'vigil', SCENE)
    path = ill.plan_path(project_dir)
    with open(path, 'w') as f:
        f.write('|'.join(ill.PLAN_COLUMNS) + '\n')
        f.write('lantern-vigil|vigil|She set it on the sill|after_anchor'
                + '|' * (len(ill.PLAN_COLUMNS) - 4) + '|overflow\n')

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'shattered_row']
    assert len(findings) == 1
    assert 'unescaped' in findings[0]['detail']


# ============================================================================
# A truncated continuity anchor blocks (issue #293)
# ============================================================================

def test_truncated_entity_anchor_is_a_blocking_finding(project_dir):
    """#293: `canon_truncated_embeddable_block` diagnoses the file, but it lands
    in `cleanup`, which gates nothing — so `--prompts` and `--package` still
    embedded a half anchor in every request. Emitting from `validate_plan` is
    what buys `validate` exit 1, `--diagnose`, and cleanup's Interior
    Illustrations section from one placement."""
    from illustration_helpers import write_canon_file
    write_canon_file(project_dir, canon_id='nora', canon_type='character',
                     subdir='characters',
                     body='A dark braid.\n\n## Wardrobe\n\nA grey wool coat.')
    ill.write_plan(project_dir, [plan_row(canon_refs='nora')])

    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'canon_anchor_truncated']
    assert len(findings) == 1, 'a truncated anchor must block'
    assert ill.severity_of('canon_anchor_truncated') == 'error'
    assert 'nora' in findings[0]['detail']
    assert '## Wardrobe' in findings[0]['detail']


def test_truncated_book_level_canon_is_a_blocking_finding(project_dir):
    """A truncated `visual-vocabulary` is worse than one short character anchor:
    the rules that repeat are gone from every prompt in the book. It is reported
    even though no plan row references it by id, and `missing_reference_sections`
    reports it clean because the block is populated — just short."""
    from illustration_helpers import write_canon_file
    write_canon_file(project_dir, canon_id='visual-vocabulary',
                     canon_type='vocabulary',
                     body='Palette: muted greens.\n\n## Camera\n\nChild height.')
    ill.write_plan(project_dir, [plan_row()])

    assert 'visual-vocabulary' not in ill.missing_reference_sections(project_dir)
    findings = [f for f in ill.validate_plan(project_dir)
                if f['kind'] == 'canon_anchor_truncated']
    assert len(findings) == 1
    assert 'visual-vocabulary' in findings[0]['detail']


def test_clean_canon_produces_no_truncation_finding(project_dir):
    from illustration_helpers import seed_canon
    seed_canon(project_dir)
    ill.write_plan(project_dir, [plan_row(canon_refs='dorren-hayle')])
    assert [f for f in ill.validate_plan(project_dir)
            if f['kind'] == 'canon_anchor_truncated'] == []


# ============================================================================
# The finding-kind domain, enforced
# ============================================================================

def test_finding_kinds_are_partitioned_by_severity():
    """BLOCKING_FINDINGS is documentation unless something checks it. Without
    this, a new kind silently becomes blocking and the two sets drift."""
    from typing import get_args
    kinds = set(get_args(ill.IllustrationFindingKind))
    assert ill.BLOCKING_FINDINGS | ill.WARNING_FINDINGS == kinds
    assert not (ill.BLOCKING_FINDINGS & ill.WARNING_FINDINGS)


def test_every_finding_kind_has_a_cleanup_action():
    """A kind with no action falls back to generic remediation text."""
    from typing import get_args
    from storyforge.cmd_cleanup import _ILLUSTRATION_ACTIONS
    assert set(_ILLUSTRATION_ACTIONS) == set(
        get_args(ill.IllustrationFindingKind))


def test_every_kind_validate_can_emit_is_in_the_domain(project_dir):
    """Drive validate_plan into as many findings as one project can hold and
    assert every kind it produced is declared."""
    from typing import get_args
    declared = set(get_args(ill.IllustrationFindingKind))

    write_scene(project_dir, 'vigil', 'Rewritten.\n\n![[illus:ghost]]\n')
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR, 'stray.png'),
             8, 8)
    ill.write_plan(project_dir, [
        plan_row(status='ingested', layout='bad', placement='sideways',
                 asset_file=ill.default_asset_rel('lantern-vigil')),
        plan_row(id='Bad Id', scene_id='nowhere', status='nonsense'),
        plan_row(id='no-scene', scene_id=''),
    ])
    emitted = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert emitted            # the fixture really did produce findings
    assert emitted <= declared


def test_schema_reads_plan_columns_from_the_module():
    """The duplicate list had no enforcing test and its justification was
    refuted by an unconditional import three lines below it."""
    import storyforge.schema as schema
    assert not hasattr(schema, 'ILLUSTRATION_PLAN_COLUMNS')


# ============================================================================
# Chapter ordering
# ============================================================================

def test_render_order_follows_the_chapter_number_not_the_row_order(project_dir):
    """Regression: _scene_order trusted physical row order, so an out-of-order
    chapter map put the visual key in chapter 3 with four earlier-chapter
    illustrations after it. Every other consumer addresses chapters by number."""
    write_csv(project_dir, 'chapter-map.csv', 'chapter|title|heading|part|scenes',
              ['3|C|numbered|1|s3', '1|A|numbered|1|s1', '2|B|numbered|1|s2'])
    ill.write_plan(project_dir, [
        dict(plan_row(id='i3', scene_id='s3'), canon_refs='X'),
        dict(plan_row(id='i1', scene_id='s1'), canon_refs='X'),
        dict(plan_row(id='i2', scene_id='s2'), canon_refs='X'),
    ])

    assert ill._scene_order(project_dir) == {'s1': 0, 's2': 1, 's3': 2}
    steps = ill.render_order(project_dir)
    assert [s['id'] for s in steps] == ['i1', 'i2', 'i3']
    assert steps[0]['is_visual_key'] is True


def test_chapter_sort_key_falls_back_and_never_reorders_silently():
    assert ill._chapter_sort_key({'chapter': '7'})[0] == 7
    assert ill._chapter_sort_key({'seq': '3'})[0] == 3
    # A malformed row sorts last rather than landing at position zero.
    assert ill._chapter_sort_key({'chapter': 'nine'})[0] == ill._SORTS_LAST


def test_a_seq_only_chapter_map_still_orders_correctly(project_dir):
    write_csv(project_dir, 'chapter-map.csv', 'seq|title|scenes',
              ['2|B|s2', '1|A|s1'])
    assert ill._scene_order(project_dir) == {'s1': 0, 's2': 1}


# ============================================================================
# Actionable image-probe reasons
# ============================================================================

def test_probe_names_a_complete_image(tmp_path):
    probe = ill.probe_image(make_png(str(tmp_path / 'ok.png'), 40, 60))
    assert probe == {'dimensions': (40, 60), 'reason': ''}


@pytest.mark.parametrize('name,body,fragment', [
    ('missing.png', None, 'does not exist'),
    ('empty.png', b'', 'empty'),
    ('art.gif', b'GIF89a', 'not a supported format'),
    ('mislabeled.png', b'this is plain text', 'magic bytes'),
    ('stub.jpg', b'\xff\xd8' + b'\x00' * 30, 'truncated'),
])
def test_probe_reasons_are_specific(tmp_path, name, body, fragment):
    """Collapsing every failure into "not a readable PNG, JPEG, or WebP" tells
    an author with a valid file that it is broken; they re-export, see the same
    message, and conclude the tool is broken."""
    path = tmp_path / name
    if body is not None:
        path.write_bytes(body)
    probe = ill.probe_image(str(path))
    assert probe['dimensions'] is None
    assert fragment in probe['reason']


def test_probe_distinguishes_an_unsupported_webp_variant(tmp_path):
    path = tmp_path / 'alpha.webp'
    payload = b'ALPH' + struct.pack('<I', 4) + b'\x00' * 4
    path.write_bytes(b'RIFF' + struct.pack('<I', 4 + len(payload)) + b'WEBP'
                     + payload)
    reason = ill.probe_image(str(path))['reason']
    assert 'does not read' in reason
    assert 're-export' in reason


def test_probe_distinguishes_a_malformed_known_webp_chunk(tmp_path):
    """A chunk we *do* read that is truncated must not be reported as an
    unsupported variant — that sends the author to re-export a valid file."""
    path = tmp_path / 'trunc.webp'
    path.write_bytes(b'RIFF' + struct.pack('<I', 20) + b'WEBP'
                     + b'VP8L' + struct.pack('<I', 9) + b'\x00' * 9)
    reason = ill.probe_image(str(path))['reason']
    assert 'malformed or truncated' in reason


def test_truncated_vp8l_is_not_read_as_one_by_one(tmp_path):
    """Without the 0x2F signature check, an all-zero VP8L payload reads as a
    valid 1x1 image, and those dimensions get published as the layout hint."""
    path = tmp_path / 'trunc.webp'
    path.write_bytes(b'RIFF' + struct.pack('<I', 20) + b'WEBP'
                     + b'VP8L' + struct.pack('<I', 9) + b'\x00' * 9)
    assert ill.image_dimensions(str(path)) is None


def test_vp8_webp_dimensions(tmp_path):
    """The form plain cwebp emits — VP8X is only for alpha/animation/EXIF."""
    assert ill.image_dimensions(
        make_webp_vp8(str(tmp_path / 'a.webp'), 100, 200)) == (100, 200)


def test_vp8l_webp_dimensions(tmp_path):
    assert ill.image_dimensions(
        make_webp_vp8l(str(tmp_path / 'a.webp'), 100, 200)) == (100, 200)


@pytest.mark.parametrize('body', [
    b'\xff\xd8\xff\xe0\x00',                                  # short length
    b'\xff\xd8\xff\xc0' + struct.pack('>H', 17) + b'\x08\x00',  # short SOF
    b'\xff\xd8\xff\xe0' + struct.pack('>H', 1) + b'\x00' * 20,  # length < 2
])
def test_jpeg_failure_branches_return_none(tmp_path, body):
    """The length<2 branch is the only thing stopping a malformed JPEG from
    seeking backwards forever."""
    path = tmp_path / 'x.jpg'
    path.write_bytes(body)
    assert ill.image_dimensions(str(path)) is None


def test_jpeg_skips_a_standalone_marker_before_the_sof(tmp_path):
    path = tmp_path / 'x.jpg'
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00' + b'\x00' * 9
    sof0 = (b'\xff\xc0' + struct.pack('>H', 17) + b'\x08'
            + struct.pack('>HH', 48, 64) + b'\x03' + b'\x00' * 9)
    path.write_bytes(b'\xff\xd8' + b'\xff\x01' + app0 + sof0 + b'\xff\xd9')
    assert ill.image_dimensions(str(path)) == (64, 48)


def test_jpeg_with_no_sof_before_eof(tmp_path):
    path = tmp_path / 'x.jpg'
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00' + b'\x00' * 9
    path.write_bytes(b'\xff\xd8' + app0 + b'\xff\xd9')
    assert ill.image_dimensions(str(path)) is None


# ============================================================================
# Dropped-illustration reporting
# ============================================================================

def test_resolve_reports_what_it_dropped(project_dir):
    """An author who planned eight and got five should be told which three,
    not left to count images in the finished epub."""
    ill.write_plan(project_dir, [
        plan_row(id='rendered', status='ingested',
                 asset_file=ill.default_asset_rel('rendered')),
        plan_row(id='unrendered', status='planned'),
    ])
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'rendered.png'), 8, 8)
    text = ('One.\n\n![[illus:rendered]]\n\nTwo.\n\n'
            '![[illus:unrendered]]\n\nThree.\n\n![[illus:ghost]]\n')

    dropped: list[str] = []
    resolved = ill.resolve_for_local(project_dir, text,
                                     relative_to=project_dir, dropped=dropped)
    assert sorted(dropped) == ['ghost', 'unrendered']
    assert 'rendered.png' in resolved
    assert '![[illus:' not in resolved


def test_resolve_reports_drops_when_there_is_no_plan(project_dir):
    dropped: list[str] = []
    ill.resolve_for_local(project_dir, 'a\n\n![[illus:x]]\n\nb\n',
                          dropped=dropped)
    assert dropped == ['x']


@pytest.mark.parametrize('placement,anchor', [
    ('scene_open', ''),
    ('scene_close', ''),
    ('after_anchor', 'She set it on the sill'),
    ('before_anchor', 'She set it on the sill'),
])
def test_strip_is_byte_identical_for_every_placement(placement, anchor):
    """A marker removed from the very start or end used to leave the blank line
    that separated it from the prose, shifting every character offset the
    detectors report by two."""
    marked = ill.insert_marker(SCENE_ADVERSARIAL,
                               plan_row(placement=placement, anchor=anchor))
    assert marked['changed'], marked['error']
    assert ill.strip_markers(marked['text']) == SCENE_ADVERSARIAL


# ============================================================================
# The visual-state finding kinds (#278 phase 2)
# ============================================================================

@pytest.mark.parametrize('kind,expected', [
    ('state_unknown_scene', 'error'),
    ('state_unmapped_scene', 'warning'),
    ('evidence_not_found', 'warning'),
    ('state_unspecified', 'warning'),
    ('prose_changed', 'warning'),
    ('audit_stale', 'warning'),
    # #308. All four leave a publishable book: two are about art not yet
    # rendered, one reports a gap in our own knowledge, and `missing_anchor`
    # matches `anchor_drift` — the same row in the same in-flight condition.
    ('state_mid_scene_change', 'warning'),
    ('prompt_spoils_unread', 'warning'),
    ('prompt_spoiler_unchecked', 'warning'),
    ('missing_anchor', 'warning'),
])
def test_new_finding_kinds_have_the_intended_severity(kind, expected):
    """A transition pointing at a scene that exists nowhere silently stops
    applying, so it blocks. A scene the chapter map merely omits still exists —
    that row is fine and the map needs fixing, so it warns, as do the rest."""
    assert ill.severity_of(kind) == expected


def test_new_finding_kinds_are_bare_not_prefixed():
    """cmd_cleanup adds the illus_ prefix; a prefixed member renders doubled."""
    from typing import get_args
    for kind in get_args(ill.IllustrationFindingKind):
        assert not kind.startswith('illus_'), kind
