"""Tests for the interior-illustration module (#278).

Covers the plan CSV, the scene marker, anchor matching, per-target resolution,
the selection pre-pass, image inspection, and plan validation.
"""

import os
import struct
import subprocess
import zlib

import pytest

from storyforge import illustrations as ill


# ============================================================================
# Helpers
# ============================================================================

def make_png(path: str, width: int, height: int) -> str:
    """Write a real minimal PNG of the given dimensions."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + b'\x00\x00\x00' * width for _ in range(height))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
                + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return path


def make_jpeg(path: str, width: int, height: int) -> str:
    """Write a minimal JPEG with an APP0 segment before the SOF0.

    The APP0 is deliberate: it exercises the segment walk skipping a
    payload-bearing marker before reaching the dimensions.
    """
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00' + b'\x00' * 9
    sof0 = (b'\xff\xc0' + struct.pack('>H', 17) + b'\x08'
            + struct.pack('>HH', height, width) + b'\x03' + b'\x00' * 9)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\xff\xd8' + app0 + sof0 + b'\xff\xd9')
    return path


def make_webp(path: str, width: int, height: int) -> str:
    """Write a minimal VP8X-form WebP."""
    payload = (b'VP8X' + struct.pack('<I', 10) + b'\x00' * 4
               + (width - 1).to_bytes(3, 'little')
               + (height - 1).to_bytes(3, 'little'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 4 + len(payload)) + b'WEBP'
                + payload)
    return path


def write_scene(project_dir: str, scene_id: str, text: str) -> str:
    """Write a scene file and return its path."""
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def pandoc_html(markdown: str) -> str:
    """Convert markdown to HTML the same way the manifest builder does."""
    result = subprocess.run(
        ['pandoc', '-f', 'markdown', '-t', 'html', '--no-highlight'],
        input=markdown, capture_output=True, text=True,
    )
    return result.stdout


SCENE = (
    'The lantern guttered once and held.\n'
    '\n'
    'She set it on the sill and waited for the street to answer.\n'
    '\n'
    'Nothing came. The cold worked up through the floorboards.\n'
    '\n'
    'By morning she had decided.\n'
)


def plan_row(**overrides) -> dict[str, str]:
    """A complete plan row with sane defaults."""
    row = ill.blank_row('lantern-vigil')
    row.update({
        'scene_id': 'vigil',
        'anchor': 'She set it on the sill',
        'placement': 'after_anchor',
        'beat': 'A woman waits at a lit window',
        'rationale': 'The image holds the waiting the prose spends three '
                     'paragraphs on',
    })
    row.update(overrides)
    return row


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

def write_csv(project_dir: str, name: str, header: str, rows: list[str]) -> None:
    """Write a pipe-delimited CSV under reference/."""
    path = os.path.join(project_dir, 'reference', name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(header + '\n')
        for row in rows:
            f.write(row + '\n')


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

def write_direction_file(project_dir: str, body: str) -> str:
    """Write a raw direction document."""
    path = ill.direction_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


SAMPLE_DIRECTION = """# The Lantern Folk — Illustration Plan

## Format

Full-color, cinematic photorealistic storybook imagery for ages 6-8.

## Visual promise

The ordinary world should feel completely real.

## Recurring visual language

- Warm amber and gold for the Lantern Folk.
- Cool moonlit blue for the woods.

## Content limits

Never horror imagery. No blood or gore.

## Continuity anchors

### Leo

Ten years old; tall and lean for his age; warm light-brown skin.

### Murkwolves

Large wolf-shaped concentrations of cold shadow and blue-gray mist.

### The village and Great Lamp

The village sits among the enormous exposed roots of the Old Oak.
"""


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
    assert ill.has_direction(project_dir) is False


def test_anchors_cover_characters_creatures_and_locations(project_dir):
    """The sample plan anchors a creature and a location, not just a cast."""
    write_direction_file(project_dir, SAMPLE_DIRECTION)
    anchors = ill.read_continuity_anchors(project_dir)
    assert set(anchors) == {'Leo', 'Murkwolves', 'The village and Great Lamp'}
    assert anchors['Murkwolves'].startswith('Large wolf-shaped')


def test_missing_direction_sections_when_absent(project_dir):
    assert ill.missing_direction_sections(project_dir) == \
        list(ill.DIRECTION_SECTIONS)


def test_missing_direction_sections_when_complete(project_dir):
    write_direction_file(project_dir, SAMPLE_DIRECTION)
    assert ill.missing_direction_sections(project_dir) == []


def test_missing_direction_sections_reports_empty_ones(project_dir):
    write_direction_file(project_dir,
                         '# D\n\n## Format\n\nPhotoreal.\n\n'
                         '## Visual promise\n\n')
    missing = ill.missing_direction_sections(project_dir)
    assert 'Format' not in missing
    assert 'Visual promise' in missing
    assert ill.ANCHORS_SECTION in missing


@pytest.mark.parametrize('body', [
    '_(fill this in)_', 'TBD', 'todo', '_Required: describe the palette_',
    '(you fill this in)',
])
def test_placeholder_sections_count_as_missing(project_dir, body):
    """A scaffold left unfilled must not be fed to an image model as direction."""
    write_direction_file(project_dir, f'# D\n\n## Format\n\n{body}\n')
    assert 'Format' in ill.missing_direction_sections(project_dir)


def test_real_prose_is_not_mistaken_for_a_placeholder(project_dir):
    write_direction_file(
        project_dir,
        '# D\n\n## Format\n\nDescribed in full color, photorealistic.\n')
    assert 'Format' not in ill.missing_direction_sections(project_dir)


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

def truncated_png(path: str, width: int, height: int) -> str:
    """Write a header-valid PNG with no IDAT and no IEND.

    This is what an aborted render download leaves behind: `image_dimensions`
    reads 32 bytes and reports plausible dimensions, so every naive guard
    passes it.
    """
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height,
                                             8, 2, 0, 0, 0)))
    return path


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

SCENE_WITH_FRONTMATTER = (
    '---\n'
    'id: "vigil"\n'
    'status: "drafted"\n'
    'drafted_at: "2026-02-28T14:30:00Z"\n'
    '---\n'
    '\n'
    + SCENE
)


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


def make_webp_vp8(path: str, width: int, height: int) -> str:
    """Write a lossy VP8 WebP — what plain `cwebp` emits."""
    body = (b'\x00\x00\x00' + b'\x9d\x01\x2a'
            + struct.pack('<HH', width, height) + b'\x00' * 8)
    payload = b'VP8 ' + struct.pack('<I', len(body)) + body
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 4 + len(payload)) + b'WEBP'
                + payload)
    return path


def make_webp_vp8l(path: str, width: int, height: int) -> str:
    """Write a lossless VP8L WebP."""
    body = b'\x2f' + struct.pack('<I', (width - 1) | ((height - 1) << 14)) \
        + b'\x00' * 4
    payload = b'VP8L' + struct.pack('<I', len(body)) + body
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 4 + len(payload)) + b'WEBP'
                + payload)
    return path


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
