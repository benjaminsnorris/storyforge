"""Tests for canon file parsing and validation (issue #254).

Canon files under `reference/canon/` are the source-of-truth for visual
blocks that embed inline into per-panel prompts. These tests cover the
deterministic foundation: parsing, structural validation, and registry
cross-references. Drift detection between canonical source and inline
copies is deferred until per-page files (#251) land.
"""

import os
import textwrap

import pytest

from storyforge.canon import (
    CANON_DIR,
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

def test_shipped_templates_pass_validation(plugin_dir, tmp_path):
    """The starter canon files in templates/reference/canon/ are author-facing
    scaffolding; they should pass structural validation as-is (the TODO
    markers live in body sections, not in fields the validator inspects)."""
    import shutil
    src = os.path.join(plugin_dir, 'templates', 'reference', 'canon')
    project = str(tmp_path)
    dst = os.path.join(project, 'reference', 'canon')
    shutil.copytree(src, dst)
    findings = validate_canon_directory(project)
    # SF-7: assert directly on the empty list rather than filtering by
    # severity; the filter would silently widen if info-level findings
    # were added in future.
    assert findings == [], f'shipped templates failed validation: {findings}'
