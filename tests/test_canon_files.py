"""Tests for canon.py — parsing, structural validation, registry
cross-references."""

import os
import re
import textwrap

import pytest

from storyforge.canon import (
    CANON_DIR,
    check_canon_drift,
    find_canon_embeds,
    parse_canon_file,
    validate_canon_directory,
    validate_canon_file,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

VALID_FRONTMATTER = textwrap.dedent("""\
    ---
    canon_id: {canon_id}
    canon_type: {canon_type}
    canon_updated: 2026-05-27
    appears_in: all panels
    embeds_as: Test Block
    first_appearance: scene-1
    ---
""")

VALID_BODY = textwrap.dedent("""\

    ## Embeddable block

    The verbatim canonical text.

    ## Clauses

    - clause one

    ## Related canon

    - [[other-canon]]

    ## Iteration history

    - 2026-05-27 — created
""")


def write_canon(project_dir, rel_path, canon_id, canon_type='foundation',
                body=VALID_BODY, frontmatter=None):
    """Write a canon file at `reference/canon/<rel_path>`."""
    path = os.path.join(project_dir, CANON_DIR, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if frontmatter is None:
        frontmatter = VALID_FRONTMATTER.format(
            canon_id=canon_id, canon_type=canon_type,
        )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(frontmatter + body)
    return path


def write_registry(project_dir, filename, ids):
    """Write a minimal pipe-delimited registry CSV with an id column."""
    path = os.path.join(project_dir, 'reference', filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('id|name|aliases\n')
        for slug in ids:
            f.write(f'{slug}|{slug}|\n')


# ---------------------------------------------------------------------------
# parse_canon_file
# ---------------------------------------------------------------------------

def test_parse_valid_canon_file(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'style-foundation.md', 'style-foundation')
    parsed = parse_canon_file(path)
    assert parsed['exists'] is True
    assert parsed['frontmatter'] is not None
    assert parsed['frontmatter']['canon_id'] == 'style-foundation'
    assert parsed['frontmatter']['canon_type'] == 'foundation'
    assert 'Embeddable block' in parsed['sections']
    assert 'Clauses' in parsed['sections']
    assert 'Related canon' in parsed['sections']
    assert 'Iteration history' in parsed['sections']


def test_parse_canon_file_without_frontmatter(tmp_path):
    project = str(tmp_path)
    canon_dir = os.path.join(project, CANON_DIR)
    os.makedirs(canon_dir)
    path = os.path.join(canon_dir, 'broken.md')
    with open(path, 'w') as f:
        f.write('No frontmatter here.\n## Embeddable block\nbody')
    parsed = parse_canon_file(path)
    assert parsed['exists'] is True
    assert parsed['frontmatter'] is None
    # Body sections still extracted even without frontmatter
    assert 'Embeddable block' in parsed['sections']


def test_parse_missing_file(tmp_path):
    parsed = parse_canon_file(str(tmp_path / 'absent.md'))
    assert parsed['exists'] is False
    assert parsed['frontmatter'] is None
    assert parsed['sections'] == set()


def test_parse_frontmatter_strips_quotes(tmp_path):
    project = str(tmp_path)
    fm = textwrap.dedent("""\
        ---
        canon_id: "quoted-id"
        canon_type: 'foundation'
        canon_updated: 2026-05-27
        appears_in: all panels
        embeds_as: Test
        first_appearance: scene-1
        ---
    """)
    path = write_canon(project, 'quoted-id.md', 'quoted-id', frontmatter=fm)
    parsed = parse_canon_file(path)
    assert parsed['frontmatter']['canon_id'] == 'quoted-id'
    assert parsed['frontmatter']['canon_type'] == 'foundation'


# ---------------------------------------------------------------------------
# validate_canon_file
# ---------------------------------------------------------------------------

def test_validate_valid_root_canon_no_findings(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'style-foundation.md', 'style-foundation')
    findings = validate_canon_file(path, project)
    assert findings == []


def test_validate_truncated_frontmatter(tmp_path):
    """SF-5: a file that opens `---` but never closes the block must report
    canon_truncated_frontmatter, not canon_missing_frontmatter — the author's
    fix is different (close the block vs add a block)."""
    project = str(tmp_path)
    canon_dir = os.path.join(project, CANON_DIR)
    os.makedirs(canon_dir)
    path = os.path.join(canon_dir, 'truncated.md')
    with open(path, 'w') as f:
        f.write('---\ncanon_id: truncated\ncanon_type: foundation\n')
        f.write('## Embeddable block\nbody text\n')
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert types == ['canon_truncated_frontmatter']


def test_validate_bom_prefixed_frontmatter_parses(tmp_path):
    """CR-3: BOM-prefixed files (common when authors copy from Notion/Word)
    must still parse — we strip the BOM before frontmatter detection.
    """
    project = str(tmp_path)
    canon_dir = os.path.join(project, CANON_DIR)
    os.makedirs(canon_dir)
    path = os.path.join(canon_dir, 'style-foundation.md')
    fm = VALID_FRONTMATTER.format(
        canon_id='style-foundation', canon_type='foundation',
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write('﻿' + fm + VALID_BODY)
    findings = validate_canon_file(path, project)
    assert findings == []


def test_validate_nested_canon_flagged(tmp_path):
    """CR-2: a canon file under canon/characters/<dir>/<file>.md is deeper
    than the schema defines. Without an explicit finding it would silently
    bypass both the subdir/type rule and the registry cross-reference.
    """
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/lucien/portrait.md', 'portrait',
        canon_type='character',
    )
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert 'canon_unexpected_nesting' in types


def test_validate_directory_emits_one_registry_finding_for_malformed_csv(tmp_path):
    """CR-1 / SF-1 / T-2: a registry CSV without an `id` column previously
    caused every canon file in the corresponding subdir to be flagged as a
    missing-registry-entry orphan. The author would chase a non-bug in canon
    files while the real bug is the CSV header. Fix: one finding per bad CSV,
    no per-canon-file noise.
    """
    project = str(tmp_path)
    write_canon(project, 'characters/lucien-vey.md', 'lucien-vey',
                canon_type='character')
    write_canon(project, 'characters/other.md', 'other',
                canon_type='character')
    # Registry exists but lacks `id` column.
    chars_path = os.path.join(project, 'reference', 'characters.csv')
    os.makedirs(os.path.dirname(chars_path), exist_ok=True)
    with open(chars_path, 'w') as f:
        f.write('name|description\n')
        f.write('Lucien|the cartographer\n')
    findings = validate_canon_directory(project)
    unreadable = [f for f in findings if f['type'] == 'canon_registry_unreadable']
    orphan = [f for f in findings if f['type'] == 'canon_missing_registry_entry']
    assert len(unreadable) == 1
    assert unreadable[0]['file'] == 'reference/characters.csv'
    assert orphan == []


def test_validate_directory_emits_one_registry_finding_for_empty_csv(tmp_path):
    """An empty/zero-byte registry CSV must produce the same single
    project-level finding as a header-without-id CSV."""
    project = str(tmp_path)
    write_canon(project, 'characters/lucien-vey.md', 'lucien-vey',
                canon_type='character')
    chars_path = os.path.join(project, 'reference', 'characters.csv')
    os.makedirs(os.path.dirname(chars_path), exist_ok=True)
    open(chars_path, 'w').close()
    findings = validate_canon_directory(project)
    types = [f['type'] for f in findings]
    assert 'canon_registry_unreadable' in types
    assert 'canon_missing_registry_entry' not in types


def test_validate_missing_frontmatter(tmp_path):
    project = str(tmp_path)
    canon_dir = os.path.join(project, CANON_DIR)
    os.makedirs(canon_dir)
    path = os.path.join(canon_dir, 'broken.md')
    with open(path, 'w') as f:
        f.write('body only\n')
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert types == ['canon_missing_frontmatter']


def test_validate_missing_required_key(tmp_path):
    project = str(tmp_path)
    fm = textwrap.dedent("""\
        ---
        canon_id: style-foundation
        canon_type: foundation
        appears_in: all panels
        embeds_as: Test
        first_appearance: scene-1
        ---
    """)
    path = write_canon(project, 'style-foundation.md', 'style-foundation',
                       frontmatter=fm)
    findings = validate_canon_file(path, project)
    keys_flagged = [f['detail'] for f in findings if f['type'] == 'canon_missing_key']
    assert any('canon_updated' in d for d in keys_flagged)


def test_validate_id_mismatch(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'style-foundation.md', 'wrong-slug')
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert 'canon_id_mismatch' in types


def test_validate_invalid_id_slug(tmp_path):
    project = str(tmp_path)
    fm = textwrap.dedent("""\
        ---
        canon_id: NotASlug
        canon_type: foundation
        canon_updated: 2026-05-27
        appears_in: all panels
        embeds_as: Test
        first_appearance: scene-1
        ---
    """)
    canon_dir = os.path.join(project, CANON_DIR)
    os.makedirs(canon_dir)
    path = os.path.join(canon_dir, 'NotASlug.md')
    with open(path, 'w') as f:
        f.write(fm + VALID_BODY)
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert 'canon_id_invalid' in types


def test_validate_invalid_canon_type(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'style-foundation.md', 'style-foundation',
                       canon_type='nonsense')
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert 'canon_type_invalid' in types


def test_validate_missing_required_section(tmp_path):
    project = str(tmp_path)
    body_no_history = textwrap.dedent("""\

        ## Embeddable block

        text

        ## Clauses

        - one

        ## Related canon

        - [[other]]
    """)
    path = write_canon(project, 'style-foundation.md', 'style-foundation',
                       body=body_no_history)
    findings = validate_canon_file(path, project)
    detail = [f['detail'] for f in findings if f['type'] == 'canon_missing_section']
    assert any('Iteration history' in d for d in detail)


def test_validate_character_type_in_root_flagged(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'lucien-vey.md', 'lucien-vey',
                       canon_type='character')
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert 'canon_type_wrong_location' in types


def test_validate_foundation_type_in_characters_subdir_flagged(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'characters/lucien-vey.md', 'lucien-vey',
                       canon_type='foundation')
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert 'canon_type_wrong_location' in types


def test_validate_unknown_subdir_flagged(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'props/candle.md', 'candle',
                       canon_type='motif')
    findings = validate_canon_file(path, project)
    types = [f['type'] for f in findings]
    assert 'canon_unknown_subdir' in types


def test_validate_character_in_characters_subdir_clean(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'characters/lucien-vey.md', 'lucien-vey',
                       canon_type='character')
    findings = validate_canon_file(path, project)
    assert findings == []


# ---------------------------------------------------------------------------
# validate_canon_directory
# ---------------------------------------------------------------------------

def test_parse_preserves_colons_in_value(tmp_path):
    """T-4: partition() splits on the first colon, keeping `:` inside values
    intact. A future `.split(':')` regression would silently truncate fields
    like `embeds_as: scene-3: panel-2 (zoom: tight)`.
    """
    project = str(tmp_path)
    fm = textwrap.dedent("""\
        ---
        canon_id: style-foundation
        canon_type: foundation
        canon_updated: 2026-05-27
        appears_in: scene-3: panel-2 (zoom: tight)
        embeds_as: Test
        first_appearance: scene-1
        ---
    """)
    path = write_canon(project, 'style-foundation.md', 'style-foundation',
                       frontmatter=fm)
    parsed = parse_canon_file(path)
    assert parsed['frontmatter']['appears_in'] == 'scene-3: panel-2 (zoom: tight)'


def test_walk_skips_non_markdown_and_dotfiles(tmp_path):
    """T-3: filter rules cover non-.md, dotfiles, and _ prefix. Without
    coverage a regression in the filter would silently start trying to
    validate image/dotfile contents and produce confusing findings."""
    project = str(tmp_path)
    canon_dir = os.path.join(project, CANON_DIR)
    os.makedirs(canon_dir)
    # Real canon file — should validate.
    write_canon(project, 'style-foundation.md', 'style-foundation')
    # Non-md — must be ignored.
    with open(os.path.join(canon_dir, 'cover.png'), 'wb') as f:
        f.write(b'\x89PNG\r\n')
    # Dotfile — must be ignored.
    with open(os.path.join(canon_dir, '.DS_Store.md'), 'w') as f:
        f.write('not canon')
    findings = validate_canon_directory(project)
    assert findings == []


def test_read_registry_ids_with_trailing_pipes(tmp_path):
    """T-3: rows with extra trailing `|` characters parse correctly. The
    registry CSV format allows variable trailing columns; canon must read
    only the `id` column robustly."""
    project = str(tmp_path)
    write_canon(project, 'characters/lucien-vey.md', 'lucien-vey',
                canon_type='character')
    chars_path = os.path.join(project, 'reference', 'characters.csv')
    os.makedirs(os.path.dirname(chars_path), exist_ok=True)
    with open(chars_path, 'w') as f:
        f.write('id|name|aliases\n')
        f.write('lucien-vey|Lucien|the cartographer||extra|trailing|fields\n')
    findings = validate_canon_directory(project)
    assert [f for f in findings if 'registry' in f['type']] == []


def test_cleanup_report_skips_canon_with_unset_medium_no_canon_dir(tmp_path):
    """T-5: project with no medium and no canon/ — fully clean, no findings.
    Locks in the fallback behavior so a future change to get_medium can't
    silently start emitting findings on novel projects."""
    from storyforge.cmd_cleanup import report_canon_files

    project = str(tmp_path)
    # storyforge.yaml without project.medium
    with open(os.path.join(project, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  title: Test\n')
    findings = report_canon_files(project)
    assert findings == []


def test_build_cleanup_report_clean_canon_plus_pages_zero_findings(
    fixture_dir_gn, tmp_path,
):
    """T2-2: end-to-end happy-path integration. A GN project with a valid
    canon tree (the committed fixture) plus a pages/ file containing a
    canon-embed of the actual Embeddable block text produces zero canon
    findings in the full cleanup report pipeline. Guards against a
    regression in any of the layers: list_page_files, _walk_canon_files,
    _resolve_canon_path, _embeddable_block_text, _normalize_for_drift."""
    import shutil
    from storyforge.cmd_cleanup import build_cleanup_report

    project = str(tmp_path / 'gn-project')
    shutil.copytree(fixture_dir_gn, project)

    canon_text = _embeddable_text(
        project, 'characters', 'cartographer.md',
    )
    pages_dir = os.path.join(project, 'pages')
    os.makedirs(pages_dir)
    with open(os.path.join(pages_dir, 's01-p1.md'), 'w') as f:
        f.write(
            '<!-- canon-embed: cartographer -->\n'
            f'{canon_text.strip()}\n'
            '<!-- /canon-embed -->\n'
        )

    report = build_cleanup_report(project)
    canon_findings = [
        f for f in report['findings'] if f.get('category') == 'canon'
    ]
    assert canon_findings == [], (
        f'expected zero canon findings on clean canon+pages project, '
        f'got: {canon_findings}'
    )


def _embeddable_text(project_dir, subdir, filename):
    """Read the Embeddable block body of a canon file in the fixture."""
    path = os.path.join(project_dir, CANON_DIR, subdir, filename)
    with open(path) as f:
        body = f.read()
    match = re.search(
        r'^##\s+Embeddable block\s*\n(.*?)(?=^##\s|\Z)',
        body, re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else ''


def test_build_cleanup_report_round_trips_canon_findings(tmp_path):
    """T-1: the integration risk flagged by pr-test-analyzer. Builds a GN
    project with a known-bad canon file, runs build_cleanup_report ->
    _write_report, and asserts the CSV round-trips a canon-category row
    with all REPORT_COLUMNS populated. A regression in category routing
    or column shape would silently ship without this test.
    """
    from storyforge.cmd_cleanup import (
        REPORT_COLUMNS,
        _write_report,
        build_cleanup_report,
    )

    project = str(tmp_path)
    with open(os.path.join(project, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  medium: graphic-novel\n')
    write_canon(project, 'style-foundation.md', 'wrong-id-slug')
    report = build_cleanup_report(project)
    canon_findings = [f for f in report['findings'] if f.get('category') == 'canon']
    assert canon_findings, 'expected at least one canon finding in report'
    for f in canon_findings:
        assert f['type'].startswith('canon_')
        assert f['severity'] in ('info', 'warning', 'error')

    report_path = _write_report(report, project)
    with open(report_path) as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    assert header == REPORT_COLUMNS
    canon_rows = [line for line in lines[1:] if line.startswith('canon|')]
    assert canon_rows, 'expected at least one canon row in the cleanup CSV'
    for row in canon_rows:
        cells = row.split('|')
        assert len(cells) == len(REPORT_COLUMNS), (
            f'row has {len(cells)} cells, expected {len(REPORT_COLUMNS)}: {row}'
        )


def test_validate_unfilled_template_flagged(tmp_path):
    """CR2-6 / SF2-10: canon files that still have TODO placeholders in
    section bodies surface a canon_unfilled_template info finding so the
    forge skill can recommend filling them. One finding per file (not
    per section) keeps the report actionable."""
    project = str(tmp_path)
    body_with_todos = textwrap.dedent("""\

        ## Embeddable block

        TODO — fill this in.

        ## Clauses

        TODO — one bullet per clause.

        ## Related canon

        - [[other]]

        ## Iteration history

        TODO — record changes here.
    """)
    write_canon(project, 'style-foundation.md', 'style-foundation',
                body=body_with_todos)
    findings = validate_canon_file(
        os.path.join(project, CANON_DIR, 'style-foundation.md'), project,
    )
    unfilled = [f for f in findings if f['type'] == 'canon_unfilled_template']
    assert len(unfilled) == 1
    assert unfilled[0]['severity'] == 'info'
    # Three sections have TODOs (Related canon has real content).
    assert 'Embeddable block' in unfilled[0]['detail']
    assert 'Clauses' in unfilled[0]['detail']
    assert 'Iteration history' in unfilled[0]['detail']
    assert 'Related canon' not in unfilled[0]['detail']


def test_validate_filled_canon_no_unfilled_finding(tmp_path):
    """A canon file with real content in every section must not register
    as unfilled — the placeholder check looks only at the first non-blank
    line of each section body."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    findings = validate_canon_file(
        os.path.join(project, CANON_DIR, 'style-foundation.md'), project,
    )
    assert [f for f in findings if f['type'] == 'canon_unfilled_template'] == []


def test_validate_directory_skips_template_files(tmp_path):
    project = str(tmp_path)
    canon_dir = os.path.join(project, CANON_DIR, 'characters')
    os.makedirs(canon_dir)
    template_path = os.path.join(canon_dir, '_template.md')
    with open(template_path, 'w') as f:
        f.write('---\ncanon_id: <slug>\n---\nbroken template')
    findings = validate_canon_directory(project)
    assert findings == []


def test_validate_directory_returns_empty_when_canon_missing(tmp_path):
    findings = validate_canon_directory(str(tmp_path))
    assert findings == []


def test_validate_directory_cross_refs_character_registry(tmp_path):
    project = str(tmp_path)
    write_canon(project, 'characters/lucien-vey.md', 'lucien-vey',
                canon_type='character')
    write_canon(project, 'characters/missing-from-registry.md',
                'missing-from-registry', canon_type='character')
    write_registry(project, 'characters.csv', ['lucien-vey'])
    findings = validate_canon_directory(project)
    types = [f['type'] for f in findings]
    files_flagged = [
        f['file'] for f in findings
        if f['type'] == 'canon_missing_registry_entry'
    ]
    assert types.count('canon_missing_registry_entry') == 1
    assert any('missing-from-registry.md' in p for p in files_flagged)


def test_validate_directory_skips_registry_check_when_csv_absent(tmp_path):
    project = str(tmp_path)
    write_canon(project, 'characters/lucien-vey.md', 'lucien-vey',
                canon_type='character')
    # No characters.csv at all — registry check should be skipped silently.
    findings = validate_canon_directory(project)
    types = [f['type'] for f in findings]
    assert 'canon_missing_registry_entry' not in types


def test_validate_directory_cross_refs_locations_and_motifs(tmp_path):
    project = str(tmp_path)
    write_canon(project, 'locations/archive.md', 'archive',
                canon_type='location')
    write_canon(project, 'motifs/candle.md', 'candle',
                canon_type='motif')
    write_registry(project, 'locations.csv', ['archive'])
    write_registry(project, 'motif-taxonomy.csv', ['candle'])
    findings = validate_canon_directory(project)
    assert [f for f in findings if f['type'] == 'canon_missing_registry_entry'] == []


def test_validate_directory_aggregates_findings_across_files(tmp_path):
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'wrong-slug')
    write_canon(project, 'lighting-laws.md', 'lighting-laws',
                canon_type='nonsense')
    findings = validate_canon_directory(project)
    types = [f['type'] for f in findings]
    assert 'canon_id_mismatch' in types
    assert 'canon_type_invalid' in types
    # Each finding has a category-less shape from canon.py; cleanup wires
    # category='canon' downstream.
    for f in findings:
        assert 'category' not in f


# ---------------------------------------------------------------------------
# Canon embed convention + drift detection
# ---------------------------------------------------------------------------

def write_page(project_dir, filename, body):
    """Write a minimal pages/<filename> file with the given body."""
    pages_dir = os.path.join(project_dir, 'pages')
    os.makedirs(pages_dir, exist_ok=True)
    path = os.path.join(pages_dir, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


def test_find_canon_embeds_returns_blocks_in_order():
    body = textwrap.dedent("""\
        ### Style Foundation
        <!-- canon-embed: style-foundation -->
        Warm earth tones, ink-and-wash medium.
        <!-- /canon-embed -->

        ### Lighting
        <!-- canon-embed: lighting-laws -->
        Single warm source, soft falloff.
        <!-- /canon-embed -->
    """)
    embeds, unclosed, invalid = find_canon_embeds(body)
    assert [e['canon_id'] for e in embeds] == ['style-foundation', 'lighting-laws']
    assert 'Warm earth tones' in embeds[0]['text']
    assert 'Single warm source' in embeds[1]['text']
    assert unclosed == []
    assert invalid == []


def test_find_canon_embeds_handles_no_embeds():
    embeds, unclosed, invalid = find_canon_embeds(
        'plain markdown body, no markers here',
    )
    assert embeds == [] and unclosed == [] and invalid == []


def test_find_canon_embeds_detects_unclosed_opener_before_next_opener():
    """CR2-1: an unclosed `b` opener followed by a well-formed `c` block
    previously caused the regex to silently swallow `c` as the body of
    `b`. The fix detects the unclosed opener and surfaces both `b` as
    unclosed and `c` as a tracked embed.
    """
    body = textwrap.dedent("""\
        <!-- canon-embed: a -->
        first
        <!-- /canon-embed -->

        <!-- canon-embed: b -->
        text without a closer here

        <!-- canon-embed: c -->
        third
        <!-- /canon-embed -->
    """)
    embeds, unclosed, invalid = find_canon_embeds(body)
    assert [e['canon_id'] for e in embeds] == ['a', 'c']
    assert [u['canon_id'] for u in unclosed] == ['b']
    assert invalid == []


def test_find_canon_embeds_detects_unclosed_opener_at_eof():
    body = '<!-- canon-embed: a -->\nno closer ever\n'
    embeds, unclosed, invalid = find_canon_embeds(body)
    assert embeds == []
    assert [u['canon_id'] for u in unclosed] == ['a']


def test_find_canon_embeds_flags_invalid_slug_id():
    """CR2-2: a typoed canon_id (uppercase or underscore) previously
    failed the embed regex and disappeared silently. Now the permissive
    opener captures the id and we flag it as invalid."""
    body = textwrap.dedent("""\
        <!-- canon-embed: Style-Foundation -->
        body
        <!-- /canon-embed -->

        <!-- canon-embed: style_foundation -->
        more body
        <!-- /canon-embed -->
    """)
    embeds, unclosed, invalid = find_canon_embeds(body)
    assert embeds == []
    assert unclosed == []
    assert [i['raw_id'] for i in invalid] == [
        'Style-Foundation', 'style_foundation',
    ]


def test_find_canon_embeds_duplicate_id_in_one_page():
    """T2-1: the same canon block legitimately embeds in multiple panels
    on one page. Each occurrence must surface as its own embed so drift
    detection can compare each independently."""
    body = textwrap.dedent("""\
        <!-- canon-embed: style-foundation -->
        clean copy
        <!-- /canon-embed -->

        <!-- canon-embed: style-foundation -->
        drifted copy
        <!-- /canon-embed -->
    """)
    embeds, _u, _i = find_canon_embeds(body)
    assert [e['canon_id'] for e in embeds] == [
        'style-foundation', 'style-foundation',
    ]
    assert 'clean copy' in embeds[0]['text']
    assert 'drifted copy' in embeds[1]['text']


def test_check_canon_drift_no_pages_returns_empty(tmp_path):
    """No pages/ directory means nothing to compare against."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    assert check_canon_drift(project) == []


def test_check_canon_drift_no_canon_returns_empty(tmp_path):
    """No canon/ directory means there's no source to drift from."""
    project = str(tmp_path)
    write_page(project, 's01-p1.md', 'body without embeds')
    assert check_canon_drift(project) == []


def test_check_canon_drift_clean_embed_no_findings(tmp_path):
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    # Match the VALID_BODY's embeddable-block content exactly.
    page_body = (
        '## Panel script\n\n'
        '### Style Foundation\n'
        '<!-- canon-embed: style-foundation -->\n'
        'The verbatim canonical text.\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', page_body)
    findings = check_canon_drift(project)
    assert findings == []


def test_check_canon_drift_orphan_embed_flagged(tmp_path):
    """An embed citing a non-existent canon_id is structurally broken
    and must surface as canon_embed_orphan with severity=error."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    page_body = (
        '<!-- canon-embed: does-not-exist -->\n'
        'some text\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', page_body)
    findings = check_canon_drift(project)
    assert len(findings) == 1
    assert findings[0]['type'] == 'canon_embed_orphan'
    assert findings[0]['severity'] == 'error'


def test_check_canon_drift_diverged_text_flagged(tmp_path):
    """When embed text differs from the source canon's Embeddable block
    (beyond whitespace), emit canon_drift."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    page_body = (
        '<!-- canon-embed: style-foundation -->\n'
        'Drifted text that does NOT match the canon source.\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', page_body)
    findings = check_canon_drift(project)
    types = [f['type'] for f in findings]
    assert 'canon_drift' in types


def test_check_canon_drift_tolerates_whitespace_shifts(tmp_path):
    """An embed with cosmetic extra blank lines or trailing spaces should
    NOT register as drift — authors copy/paste and editors mutate
    whitespace, but the canonical text hasn't actually changed."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    page_body = (
        '<!-- canon-embed: style-foundation -->\n'
        '\n\n'
        'The verbatim canonical text.   \n'
        '\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', page_body)
    findings = check_canon_drift(project)
    drift = [f for f in findings if f['type'] == 'canon_drift']
    assert drift == []


def test_check_canon_drift_canon_without_embeddable_section_no_duplicate(tmp_path):
    """SF2-3: when a canon file is missing its `## Embeddable block`,
    validate_canon_file already emits canon_missing_section. The drift
    pass must NOT re-emit it (otherwise the same root cause shows up
    twice in the report and inflates the finding count)."""
    project = str(tmp_path)
    body_no_embed = textwrap.dedent("""\

        ## Clauses

        - one

        ## Related canon

        - [[other]]

        ## Iteration history

        - 2026-05-27 — created
    """)
    write_canon(project, 'style-foundation.md', 'style-foundation',
                body=body_no_embed)
    page_body = (
        '<!-- canon-embed: style-foundation -->\n'
        'some text\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', page_body)
    # check_canon_drift in isolation must not emit canon_missing_section
    drift_findings = check_canon_drift(project)
    assert [f for f in drift_findings if f['type'] == 'canon_missing_section'] == []
    # validate_canon_directory (which composes both checks) must produce
    # exactly one canon_missing_section finding total.
    all_findings = validate_canon_directory(project)
    missing = [f for f in all_findings if f['type'] == 'canon_missing_section']
    assert len(missing) == 1
    assert 'style-foundation.md' in missing[0]['file']


def test_check_canon_drift_unreadable_page_flagged(tmp_path):
    """SF2-1: a single page file with a decode error must not abort the
    cleanup run. Emit canon_page_unreadable and continue to the next
    page so authors get a triagable report."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    pages_dir = os.path.join(project, 'pages')
    os.makedirs(pages_dir, exist_ok=True)
    # Write a page with invalid UTF-8 bytes.
    bad_path = os.path.join(pages_dir, 's01-p1.md')
    with open(bad_path, 'wb') as f:
        f.write(b'\xff\xfeinvalid utf-8 bytes')
    # And a perfectly good page with a clean embed.
    good_page = (
        '<!-- canon-embed: style-foundation -->\n'
        'The verbatim canonical text.\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's02-p1.md', good_page)
    findings = check_canon_drift(project)
    types = [f['type'] for f in findings]
    assert 'canon_page_unreadable' in types
    assert 's01-p1.md' in next(
        f['file'] for f in findings if f['type'] == 'canon_page_unreadable'
    )


def test_check_canon_drift_unclosed_in_page_flagged(tmp_path):
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    page_body = '<!-- canon-embed: style-foundation -->\nno closer\n'
    write_page(project, 's01-p1.md', page_body)
    findings = check_canon_drift(project)
    types = [f['type'] for f in findings]
    assert 'canon_embed_unclosed' in types
    unclosed = next(f for f in findings if f['type'] == 'canon_embed_unclosed')
    assert unclosed['severity'] == 'error'


def test_check_canon_drift_invalid_id_in_page_flagged(tmp_path):
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    page_body = (
        '<!-- canon-embed: Style_Foundation -->\n'
        'body\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', page_body)
    findings = check_canon_drift(project)
    types = [f['type'] for f in findings]
    assert 'canon_embed_invalid_id' in types
    # Drift comparison should NOT have fired for the invalid embed.
    assert 'canon_drift' not in types


def test_check_canon_drift_normalize_tolerates_indentation(tmp_path):
    """CR2-5: a markdown formatter that re-indents the embed body must
    not register as drift. _normalize_for_drift now lstrips per line."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    indented_page = (
        '1. Step one\n\n'
        '   <!-- canon-embed: style-foundation -->\n'
        '   The verbatim canonical text.\n'
        '   <!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', indented_page)
    findings = check_canon_drift(project)
    drift = [f for f in findings if f['type'] == 'canon_drift']
    assert drift == []


def test_validate_canon_directory_runs_drift(tmp_path):
    """validate_canon_directory should also run drift checks when both
    canon/ and pages/ exist, so cleanup picks them up via the same
    Canon Files report category."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    page_body = (
        '<!-- canon-embed: style-foundation -->\n'
        'Drifted text.\n'
        '<!-- /canon-embed -->\n'
    )
    write_page(project, 's01-p1.md', page_body)
    findings = validate_canon_directory(project)
    types = [f['type'] for f in findings]
    assert 'canon_drift' in types


# ---------------------------------------------------------------------------
# Integration: cmd_cleanup wires canon findings into the report
# ---------------------------------------------------------------------------

def test_cleanup_report_includes_canon_findings_for_gn(tmp_path):
    from storyforge.cmd_cleanup import report_canon_files

    project = str(tmp_path)
    os.makedirs(project, exist_ok=True)
    with open(os.path.join(project, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  medium: graphic-novel\n')
    write_canon(project, 'style-foundation.md', 'mismatched-id')
    findings = report_canon_files(project)
    assert findings, 'expected at least one canon finding'
    for f in findings:
        assert f['category'] == 'canon'


def test_cleanup_report_skips_canon_for_novel_medium_without_canon_dir(tmp_path):
    """When canon/ is genuinely absent, novel-medium projects skip cleanly."""
    from storyforge.cmd_cleanup import report_canon_files

    project = str(tmp_path)
    os.makedirs(project, exist_ok=True)
    with open(os.path.join(project, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  medium: novel\n')
    findings = report_canon_files(project)
    assert findings == []


def test_cleanup_report_warns_when_canon_dir_in_novel_project(tmp_path):
    """SF-4: canon/ present but medium isn't graphic-novel should warn rather
    than silently skip — otherwise a deleted-yaml or misconfigured-medium
    project ships with unvalidated canon and a green cleanup report.
    """
    from storyforge.cmd_cleanup import report_canon_files

    project = str(tmp_path)
    os.makedirs(project, exist_ok=True)
    with open(os.path.join(project, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  medium: novel\n')
    write_canon(project, 'style-foundation.md', 'mismatched-id')
    findings = report_canon_files(project)
    assert len(findings) == 1
    assert findings[0]['type'] == 'canon_present_in_novel_project'
    assert findings[0]['category'] == 'canon'


def test_cleanup_report_warns_when_canon_dir_present_no_yaml(tmp_path):
    """SF-4: missing storyforge.yaml causes get_medium → 'novel' fallback. If
    canon/ is populated, we surface a finding rather than silently skipping.
    """
    from storyforge.cmd_cleanup import report_canon_files

    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    findings = report_canon_files(project)
    assert len(findings) == 1
    assert findings[0]['type'] == 'canon_present_in_novel_project'


# ---------------------------------------------------------------------------
# Templates ship valid canon files (foundation set)
# ---------------------------------------------------------------------------

def test_gn_fixture_canon_tree_is_clean(fixture_dir_gn):
    """The committed canon tree in tests/fixtures/test-project-gn/ is the
    reference example for what a healthy GN project's canon looks like.
    It must pass validation with zero findings so future contributors
    have a working baseline to compare against."""
    findings = validate_canon_directory(fixture_dir_gn)
    assert findings == [], f'GN fixture canon has findings: {findings}'


def test_shipped_templates_pass_structural_validation(plugin_dir, tmp_path):
    """The starter canon files in templates/reference/canon/ are author-
    facing scaffolding. Structurally they must be valid (no missing
    sections, no frontmatter errors), but they DO carry TODO placeholders
    which surface as info-severity canon_unfilled_template findings —
    that's intentional, the forge skill consumes those findings to
    recommend filling them in. Assert no error/warning findings; info
    is allowed and expected on shipped templates."""
    import shutil
    src = os.path.join(plugin_dir, 'templates', 'reference', 'canon')
    project = str(tmp_path)
    dst = os.path.join(project, 'reference', 'canon')
    shutil.copytree(src, dst)
    findings = validate_canon_directory(project)
    blocking = [f for f in findings if f['severity'] != 'info']
    assert blocking == [], f'shipped templates have blocking findings: {blocking}'
    # And: every root file SHOULD have an unfilled-template info finding,
    # because every shipped template has TODO placeholders.
    unfilled = [f for f in findings if f['type'] == 'canon_unfilled_template']
    assert len(unfilled) == 4, (
        f'expected 4 unfilled-template findings (one per shipped root '
        f'canon), got {len(unfilled)}: {unfilled}'
    )
