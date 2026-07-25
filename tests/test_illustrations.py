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
