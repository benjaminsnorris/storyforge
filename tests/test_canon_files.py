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
    _resolve_canon_path, _embeddable_block_text, normalize_for_comparison."""
    import shutil
    from storyforge.cmd_cleanup import build_cleanup_report

    project = str(tmp_path / 'gn-project')
    shutil.copytree(fixture_dir_gn, project)

    canon_text = _embeddable_text(
        project, 'characters', 'cartographer.md',
    )
    pages_dir = os.path.join(project, 'pages')
    os.makedirs(pages_dir, exist_ok=True)
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


# ---------------------------------------------------------------------------
# Canon validation joins `validate`'s gate (issue #295)
# ---------------------------------------------------------------------------

def test_canon_errors_are_separated_from_warnings(project_dir):
    """#295: `error` severity on a canon finding meant nothing — `cleanup` was
    its only consumer and returns None on every path. `canon_gate` is what
    `cmd_validate` folds into its exit code, so only `error` blocks: info
    (`canon_unfilled_template`) and warning findings still report and pass, or
    an in-flight project could never validate."""
    from storyforge.canon import canon_gate
    project = str(project_dir)
    # An unclosed frontmatter block — an existing 'error' kind.
    write_canon(project, 'characters/nora.md', 'nora', canon_type='character',
                frontmatter='---\ncanon_id: nora\n')
    result = canon_gate(project)
    assert result['errors'], 'an error-severity canon finding must block'
    assert all(f['severity'] == 'error' for f in result['errors'])
    assert all(f['severity'] != 'error' for f in result['other'])


def test_canon_gate_is_empty_without_a_canon_directory(project_dir):
    """A project with no `reference/canon/` is valid in-flight state, matching
    `cmd_cleanup.report_canon_files`' own guard — not a reason to fail
    `validate` for every project that has never run `--direction`."""
    from storyforge.canon import canon_gate
    import shutil
    canon_dir = os.path.join(project_dir, CANON_DIR)
    if os.path.isdir(canon_dir):
        shutil.rmtree(canon_dir)
    assert canon_gate(str(project_dir)) == {'errors': [], 'other': []}


def _validate_exit_code(project, monkeypatch):
    """Run `cmd_validate.main` with the non-canon validators stubbed to passing.

    The fixture project does not pass `validate` on its own (six structural
    failures), so an unstubbed exit code would be 1 either way — the broken-canon
    assertion would pass for the wrong reason and the clean-canon one could never
    pass. Stubbing the other three contributors is what isolates the canon half
    of the gate, which is the only thing these two tests are about. `canon_gate`
    itself is exercised for real.
    """
    import storyforge.elaborate as el
    import storyforge.schema as sch
    from storyforge import cmd_validate
    monkeypatch.setattr(el, 'validate_structure',
                        lambda ref: {'passed': True, 'checks': [], 'failures': []})
    monkeypatch.setattr(sch, 'validate_schema',
                        lambda ref, proj: {'failed': 0, 'checks': [], 'results': []})
    monkeypatch.setattr(sch, 'validate_illustration_plan',
                        lambda proj: {'row_count': 0, 'errors': [], 'warnings': []})
    monkeypatch.setattr(cmd_validate, 'detect_project_root', lambda: project)
    with pytest.raises(SystemExit) as exc:
        cmd_validate.main(['--quiet'])
    return exc.value.code


def test_validate_exits_nonzero_on_a_canon_error(project_dir, monkeypatch):
    """The gate itself: a canon error must fail `storyforge validate`, which is
    where every other blocking check in this project already lives. Before #295
    an `error`-severity canon finding could not fail anything."""
    project = str(project_dir)
    write_canon(project, 'characters/nora.md', 'nora', canon_type='character',
                frontmatter='---\ncanon_id: nora\n')
    assert [f for f in validate_canon_directory(project)
            if f['severity'] == 'error'], 'fixture must really have a canon error'
    assert _validate_exit_code(project, monkeypatch) == 1


def test_validate_passes_when_canon_is_only_unfinished(project_dir, monkeypatch):
    """The negative half, and the one that decides whether this is usable: canon
    that is merely incomplete — TODO scaffolds (info), warnings — must not block,
    or a project mid-`--direction` could never validate."""
    project = str(project_dir)
    write_canon(project, 'characters/nora.md', 'nora', canon_type='character',
                body='\n## Embeddable block\n\nTODO — describe her.\n\n'
                     '## Clauses\n\n## Related canon\n\n## Iteration history\n')
    severities = {f['severity'] for f in validate_canon_directory(project)}
    assert 'error' not in severities, f'unexpected canon error: {severities}'
    assert _validate_exit_code(project, monkeypatch) == 0


def test_truncated_anchor_ids_reports_every_affected_canon_file(tmp_path):
    """#293: the shared source `validate_plan`, `--prompts` and the packet all
    read, so a truncated anchor is diagnosed the same way in each. Keyed by
    canon_id, which is what `canon_refs` matches against."""
    from storyforge.canon import truncated_anchor_ids
    project = str(tmp_path)
    write_canon(project, 'characters/nora.md', 'nora', canon_type='character',
                body=_anchor_body(block_lines='A braid.\n\n## Wardrobe\n\nCoat.'))
    write_canon(project, 'visual-vocabulary.md', 'visual-vocabulary',
                canon_type='vocabulary',
                body=_anchor_body(block_lines='Greens.\n\n## Camera\n\nLow.'))
    write_canon(project, 'locations/office.md', 'office', canon_type='location',
                body=_anchor_body(block_lines='A narrow room.'))

    found = truncated_anchor_ids(project)
    assert set(found) == {'nora', 'visual-vocabulary'}, 'clean files must not appear'
    assert [t.heading for t in found['nora']] == ['## Wardrobe']
    assert [t.heading for t in found['visual-vocabulary']] == ['## Camera']


def test_truncated_anchor_ids_skips_templates_and_missing_dir(tmp_path):
    """Walks via `_walk_canon_files` like every other reader, so a starter
    template is not reported as a broken anchor. A project with no canon
    directory is valid in-flight state, not a finding."""
    from storyforge.canon import truncated_anchor_ids
    project = str(tmp_path)
    assert truncated_anchor_ids(project) == {}
    write_canon(project, 'characters/_template.md', '_template',
                canon_type='character',
                body=_anchor_body(block_lines='X.\n\n## Sub\n\nY.'))
    assert truncated_anchor_ids(project) == {}


# ---------------------------------------------------------------------------
# An H2 heading name lives on one physical line (issue #294)
#
# `_SECTION_RE`, `_SECTION_BODY_RE` and `_EMBEDDABLE_BLOCK_RE` all separated
# `##` from the heading name with `\s+`. Without DOTALL `.` cannot cross a
# newline, but `\s+` always could — so a bare `##` line followed by a text line
# was read as a heading *named* by that text. Four consequences, all verified.
# ---------------------------------------------------------------------------

def test_bare_hash_does_not_fabricate_a_section_name(tmp_path):
    """The phantom entry. `sections` is what `canon_missing_section` checks
    `REQUIRED_SECTIONS` membership against, so a fabricated name is not
    cosmetic."""
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines='A dark braid.\n\n##\nA grey wool coat.'),
    )
    assert 'A grey wool coat.' not in parse_canon_file(path)['sections']


def test_missing_required_section_reported_despite_a_bare_hash(tmp_path):
    """The live bug (#294): a file with NO `## Clauses` heading anywhere read as
    having one, because a bare `##` sat above a line whose text was `Clauses`.
    A structural validator reporting a file as complete when a required section
    is absent is the one thing it exists to prevent."""
    project = str(tmp_path)
    path = write_canon(
        project, 'visual-foundation.md', 'visual-foundation',
        body='\n## Embeddable block\n\nStyle notes.\n\n##\nClauses\n\n'
             '## Related canon\n\n- x\n\n## Iteration history\n\n- y\n',
    )
    missing = [f for f in validate_canon_file(path, project)
               if f['type'] == 'canon_missing_section']
    assert len(missing) == 1, 'the absent ## Clauses section must be reported'
    assert 'Clauses' in missing[0]['detail']


def test_section_body_re_does_not_fabricate_a_section(tmp_path):
    """`_SECTION_BODY_RE` shared the quirk, so the unfilled-template check could
    attribute a body to a section name that does not exist."""
    from storyforge.canon import _SECTION_BODY_RE
    body = '\n## Embeddable block\n\nStyle.\n\n##\nClauses\n\n## Related canon\n\n- x\n'
    assert [m.group(1) for m in _SECTION_BODY_RE.finditer(body)] == [
        'Embeddable block', 'Related canon']


def test_embeddable_block_heading_must_be_on_one_line(tmp_path):
    """The quirk also split the extractor from the detector. A bare `##` above a
    line reading `Embeddable block` made the *extractor* report a block, while
    the detector (which matches `_SECTION_RE` per line) never opened its window
    — so a real `## Wardrobe` truncation below went unreported. Neither should
    see a block here: a heading is one line."""
    from storyforge.canon import (
        _EMBEDDABLE_BLOCK_RE, embeddable_block_truncations,
    )
    body = ('\n##\nEmbeddable block\n\nStyle notes.\n\n'
            '## Wardrobe\n\nGrey.\n\n## Clauses\n\n- c\n')
    assert _EMBEDDABLE_BLOCK_RE.search(body) is None
    assert embeddable_block_truncations(body) == []


@pytest.mark.parametrize('heading,expected', [
    ('## Wardrobe', 'Wardrobe'),
    ('##\tWardrobe', 'Wardrobe'),          # tab still separates
    ('## Wardrobe   ', 'Wardrobe'),        # trailing spaces still stripped
    ('##  Two  spaces', 'Two  spaces'),    # interior spacing preserved
])
def test_one_line_headings_still_parse(tmp_path, heading, expected):
    """The narrowing must not reject headings that were always legal."""
    from storyforge.canon import _SECTION_RE
    match = _SECTION_RE.match(heading)
    assert match is not None and match.group(1).strip() == expected


def test_bare_hash_still_reports_as_a_truncation(tmp_path):
    """Guards the per-line call site the #294 fix must not disturb: a bare `##`
    gets no name, and that empty name is what makes it report (issue #289)."""
    from storyforge.canon import embeddable_block_truncations
    assert embeddable_block_truncations(
        '\n## Embeddable block\n\nA dark braid.\n\n##\n\n') == [(6, '##')]


def test_parsed_frontmatter_can_be_the_truncated_sentinel(tmp_path):
    """`ParsedCanonFile['frontmatter']` really does hold `_Sentinel.TRUNCATED`
    for an unclosed block, so the annotation has to admit it — a caller that
    trusted `dict | None` and skipped an isinstance check was wrong."""
    from storyforge.canon import _TRUNCATED
    project = str(tmp_path)
    path = write_canon(project, 'style-foundation.md', 'style-foundation',
                       frontmatter='---\ncanon_id: style-foundation\n')
    assert parse_canon_file(path)['frontmatter'] is _TRUNCATED


# ---------------------------------------------------------------------------
# Embeddable-block truncation (issue #289)
# ---------------------------------------------------------------------------

def _anchor_body(*, block_lines: str) -> str:
    """A canon body that puts `block_lines` under `## Embeddable block`, followed
    by the other three required sections. What the extractor then *reads* back
    is often less than `block_lines` — that truncation is the point of most of
    these fixtures, so this deliberately does not promise a verbatim round-trip.
    """
    return (
        '\n## Embeddable block\n\n'
        f'{block_lines}\n\n'
        '## Clauses\n\n- clause one\n\n'
        '## Related canon\n\n- [[other]]\n\n'
        '## Iteration history\n\n- 2026-07-29 — created\n'
    )


def _truncations(findings):
    return [f for f in findings
            if f['type'] == 'canon_truncated_embeddable_block']


def test_h2_heading_inside_embeddable_block_is_reported(tmp_path):
    """Issue #289: the anchor extractor reads to the next `##`, so an author
    who sub-heads the anchor with `## Wardrobe` loses everything below it.
    The truncation must not be silent — it produces a finding naming the file
    and the offending line."""
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines=(
            '**Nora Vance**, 9 years old, a dark braid over one shoulder.\n\n'
            '## Wardrobe\n\n'
            'A grey wool coat, two buttons missing.'
        )),
    )
    findings = validate_canon_file(path, project)
    truncated = _truncations(findings)
    assert len(truncated) == 1, findings
    assert truncated[0]['severity'] == 'error'
    assert truncated[0]['file'] == os.path.join(
        'reference', 'canon', 'characters', 'nora.md')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    expected_line = lines.index('## Wardrobe') + 1
    assert f'line {expected_line}' in truncated[0]['detail']
    assert '## Wardrobe' in truncated[0]['detail']


def test_truncated_anchor_is_reported_not_silently_shortened(tmp_path):
    """The byte-identity checks in test_packet / test_illustrate_package both
    compare against anchor_texts — the truncating function — so they agree
    with each other about an already-wrong value. This asserts the chosen
    behavior directly against anchor_texts: the anchor is still cut at the
    `##` line (widening it would swallow whatever section follows), and the
    cut is always accompanied by a finding."""
    from storyforge.canon import anchor_texts
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines=(
            'A dark braid over one shoulder.\n\n'
            '## Wardrobe\n\n'
            'A grey wool coat, two buttons missing.'
        )),
    )
    anchor = anchor_texts(project)['nora']
    assert anchor == 'A dark braid over one shoulder.'
    assert 'grey wool coat' not in anchor
    assert _truncations(validate_canon_file(path, project))


def test_bare_double_hash_line_inside_embeddable_block_is_reported(tmp_path):
    """A lone `##` line truncates the block — the extractor's lookahead is
    `^##\\s` and here the `\\s` is the line's own newline — and `_SECTION_RE`
    gives it no name, so it cannot be mistaken for a section that closes the
    window. (An earlier version of this docstring claimed `_SECTION_RE` would
    *miss* this line; it does not. See
    test_section_re_is_the_wrong_enumerator_for_a_trailing_bare_hash for the
    shape where the two genuinely diverge.)"""
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines=(
            'A dark braid over one shoulder.\n\n'
            '##\n\n'
            'A grey wool coat.'
        )),
    )
    assert len(_truncations(validate_canon_file(path, project))) == 1


def test_section_re_is_the_wrong_enumerator_for_a_trailing_bare_hash(tmp_path):
    """T-5: swapping the enumerator to `_SECTION_RE` survived 294 tests, because
    `_SECTION_RE` is MULTILINE without DOTALL, so its `\\s+` crosses newlines and
    it happily reads `##\\nA grey coat.` as a heading *named* `A grey coat.`.
    The shape where the two genuinely diverge is a bare `##` with only
    whitespace after it: the terminator matches, `_SECTION_RE` does not, and an
    enumerator built on the latter reports nothing at all."""
    from storyforge.canon import (
        _BLOCK_TERMINATOR_RE, _SECTION_RE, embeddable_block_truncations,
    )
    body = '\n## Embeddable block\n\nA dark braid.\n\n##\n\n'
    assert len(_BLOCK_TERMINATOR_RE.findall(body)) == 2
    assert [m.group(1) for m in _SECTION_RE.finditer(body)] == ['Embeddable block']
    assert embeddable_block_truncations(body) == [(6, '##')]


def test_h3_subheading_inside_embeddable_block_is_not_truncation(tmp_path):
    """`### Wardrobe` is inside the block, not a terminator — it must round-trip
    whole and produce no finding. This is the fix an author is told to apply,
    so firing on it would make the remediation impossible."""
    from storyforge.canon import anchor_texts
    project = str(tmp_path)
    block = ('A dark braid over one shoulder.\n\n'
             '### Wardrobe\n\n'
             'A grey wool coat, two buttons missing.')
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines=block),
    )
    assert anchor_texts(project)['nora'] == block
    assert _truncations(validate_canon_file(path, project)) == []


def test_detector_agrees_with_the_extractor_on_a_final_bare_hash(tmp_path):
    """The invariant is one-directional: the detector must never flag a heading
    the extractor does not stop at. (It reports a strict *subset* — the window
    closes at `_SECTIONS_AFTER_ANCHOR`, so `## Clauses` is a stop the detector
    deliberately does not report. An earlier docstring here said "exactly",
    which would invite a future reader to delete that break.)

    A bare `##` on the last line with no trailing newline does NOT stop the
    extractor — the lookahead's `\\s` has no character to match — so the text
    survives and there is nothing to report. A per-line reimplementation spelled
    `^##(\\s|$)` looks equivalent and breaks exactly here."""
    from storyforge.canon import (
        embeddable_block_text, embeddable_block_truncations,
    )
    project = str(tmp_path)
    body = '\n## Embeddable block\n\nA dark braid.\n\n##'
    path = write_canon(project, 'characters/nora.md', 'nora',
                       canon_type='character', body=body)
    assert '##' in (embeddable_block_text(path) or '').splitlines()
    assert embeddable_block_truncations(body) == []
    assert _truncations(validate_canon_file(path, project)) == []


def test_duplicate_embeddable_block_heading_is_reported(tmp_path):
    """Round-2 CRITICAL. `EMBEDDABLE_SECTION` is `REQUIRED_SECTIONS[0]`, so
    breaking the window on the whole tuple made a *duplicated*
    `## Embeddable block` read as a clean terminator. The extractor stops there
    too (`.search` takes the first), so the anchor was silently halved and
    validation returned zero findings — the exact failure class #289 exists to
    close, reached through its own fix. `parsed['sections']` is a set, so no
    duplicate-heading check catches it either."""
    from storyforge.canon import anchor_texts
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines=(
            'A dark braid over one shoulder.\n\n'
            '## Embeddable block\n\n'
            'A grey wool coat, two buttons missing.'
        )),
    )
    assert anchor_texts(project)['nora'] == 'A dark braid over one shoulder.'
    truncated = _truncations(validate_canon_file(path, project))
    assert len(truncated) == 1, 'a duplicated heading halves the anchor silently'
    assert '## Embeddable block' in truncated[0]['detail']


def test_truncation_detail_has_no_pipe(tmp_path):
    """Round-2 CRITICAL. This is the first finding to interpolate a verbatim
    line of author markdown into a `detail`, and `working/cleanup-report.csv`
    is unquoted pipe-delimited — a `|` in the heading shifts every later field
    one column right, emptying the trailing `status` cell that
    `build_cleanup_report` sets to `pending` and `skills/forge/SKILL.md` scans
    for. The error-severity finding would silence itself in its only durable
    artifact. Mirrors test_illustration_canon.py's
    test_mismatch_detail_has_no_newline_or_pipe for the sibling finding that
    also quotes author prose."""
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines=(
            'A dark braid.\n\n## Wardrobe | winter\n\nA grey wool coat.'
        )),
    )
    finding = _truncations(validate_canon_file(path, project))[0]
    assert '|' not in finding['detail']
    assert '\n' not in finding['detail']
    assert 'Wardrobe' in finding['detail'], 'the heading must still be named'


def test_truncation_reported_even_without_frontmatter(tmp_path):
    """Round-2 CRITICAL. `validate_canon_file` returns early when frontmatter
    is missing or unclosed, but `embeddable_block_text`,
    `get_canon_embeddable_block`, `is_canon_block_populated` and
    `prompts_illustrate.book_level_direction` never read frontmatter — so a
    root canon file's truncated house style was still shipped to every prompt
    while the truncation went unreported. The check reads only the body and
    must run before those returns."""
    from storyforge.canon import embeddable_block_text
    project = str(tmp_path)
    body = _anchor_body(block_lines=(
        'Palette: muted greens.\n\n## Camera\n\nAt child height.'
    ))
    path = write_canon(project, 'visual-vocabulary.md', 'visual-vocabulary',
                       canon_type='vocabulary', frontmatter='', body=body)
    kinds = [f['type'] for f in validate_canon_file(path, project)]
    assert 'canon_missing_frontmatter' in kinds
    assert 'canon_truncated_embeddable_block' in kinds
    # The truncated value really is still readable — that is why it must report.
    assert embeddable_block_text(path).strip() == 'Palette: muted greens.'


def test_truncation_reported_when_frontmatter_is_unclosed(tmp_path):
    """Same early-return gap via the other branch: an unclosed `---` block."""
    project = str(tmp_path)
    path = write_canon(
        project, 'visual-vocabulary.md', 'visual-vocabulary',
        canon_type='vocabulary', frontmatter='---\ncanon_id: x\n',
        body=_anchor_body(block_lines='Palette.\n\n## Camera\n\nLow.'),
    )
    kinds = [f['type'] for f in validate_canon_file(path, project)]
    assert 'canon_truncated_frontmatter' in kinds
    assert 'canon_truncated_embeddable_block' in kinds


def test_embeddable_section_constant_matches_the_extractor(tmp_path):
    """`EMBEDDABLE_SECTION` is only load-bearing if the extractor actually keys
    on it. Without this, renaming the section in the regex but not the constant
    would make the detector return `[]` for every file forever — a findings-
    never-silent regression with no other test failing."""
    from storyforge.canon import (
        EMBEDDABLE_SECTION, REQUIRED_SECTIONS, _EMBEDDABLE_BLOCK_RE,
    )
    assert _EMBEDDABLE_BLOCK_RE.search(
        f'## {EMBEDDABLE_SECTION}\nbody text\n') is not None
    assert REQUIRED_SECTIONS[0] == EMBEDDABLE_SECTION


def test_all_offenders_are_reported_in_source_order(tmp_path):
    """T-1: a `break` after the first offender, or `return offenders[:1]`,
    passed all 5584 tests. Reporting one at a time turns an error-severity
    finding into an N-round loop on exactly the file where an author is likeliest
    to have written several sub-heads."""
    from storyforge.canon import embeddable_block_truncations
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines=(
            'A dark braid.\n\n## Wardrobe\n\nGrey coat.\n\n## Injury\n\nA scar.'
        )),
    )
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    detail = _truncations(validate_canon_file(path, project))[0]['detail']
    for heading in ('## Wardrobe', '## Injury'):
        assert heading in detail
        assert f'line {lines.index(heading) + 1}' in detail
    assert detail.index('## Wardrobe') < detail.index('## Injury'), 'source order'
    assert [t.heading for t in embeddable_block_truncations('\n'.join(lines))] == [
        '## Wardrobe', '## Injury']


def test_heading_on_the_last_line_without_a_trailing_newline(tmp_path):
    """T-2: the `eol == -1` branch. Simplifying to `body[start:eol]` survived the
    full suite, and with `eol == -1` that is `body[start:-1]` — silently dropping
    the body's last character, so the finding names `## Wardrob`, which the
    author cannot find by searching for it."""
    from storyforge.canon import embeddable_block_truncations
    assert embeddable_block_truncations(
        '\n## Embeddable block\n\nx\n\n## Wardrobe') == [(6, '## Wardrobe')]


@pytest.mark.parametrize('block_lines,expected', [
    ('x\n\n```\n## not a heading\n```', '## not a heading'),
    ('x\n\n## hash at line start in prose', '## hash at line start in prose'),
])
def test_fenced_and_prose_hashes_still_fire(tmp_path, block_lines, expected):
    """T-3: both of these DO fire, and that is correct — `_EMBEDDABLE_BLOCK_RE`
    is not fence-aware either, so the anchor really is truncated there. Tested
    because it looks like a false positive and isn't: a future "reduce noise"
    commit teaching the detector to skip fenced blocks would break the
    agreement invariant, leaving the anchor truncated and the finding gone."""
    project = str(tmp_path)
    path = write_canon(project, 'characters/nora.md', 'nora',
                       canon_type='character',
                       body=_anchor_body(block_lines=block_lines))
    truncated = _truncations(validate_canon_file(path, project))
    assert len(truncated) == 1
    assert expected in truncated[0]['detail']


def test_heading_above_the_embeddable_block_does_not_open_the_window(tmp_path):
    """T-4: every other test opens its body with `## Embeddable block`, so the
    skip-and-continue path was never exercised with a non-matching name and
    `started = True` (unconditional) survived the full suite. That mutant breaks
    both ways: a real truncation under a file with `## Overview` above the block
    goes missed, and a file with no Embeddable block at all reports spuriously."""
    from storyforge.canon import embeddable_block_truncations
    assert embeddable_block_truncations(
        '\n## Overview\n\nblah\n\n## Embeddable block\n\nx\n\n## Wardrobe\n\ny\n'
    ) == [(10, '## Wardrobe')]
    assert embeddable_block_truncations(
        '\n## Clauses\n\nc\n\n## Notes\n\nn\n') == []


def test_body_line_offset_is_zero_without_frontmatter(tmp_path):
    """T-6: `write_canon` always emits frontmatter, so the offset was only ever
    exercised at one non-zero value. This covers the `body IS text` case the
    production comment specifically defends."""
    project = str(tmp_path)
    path = write_canon(project, 'style-foundation.md', 'style-foundation',
                       frontmatter='')
    assert parse_canon_file(path)['body_line_offset'] == 0


def test_well_formed_canon_file_has_no_truncation_finding(tmp_path):
    project = str(tmp_path)
    path = write_canon(project, 'style-foundation.md', 'style-foundation')
    assert _truncations(validate_canon_file(path, project)) == []


def test_heading_after_the_required_sections_is_not_truncation(tmp_path):
    """The offending window closes at the first required section that follows
    the Embeddable block. A non-schema `## Notes` further down the file does
    not shorten the anchor, so it is not this finding."""
    project = str(tmp_path)
    path = write_canon(
        project, 'characters/nora.md', 'nora', canon_type='character',
        body=_anchor_body(block_lines='A dark braid.') + '\n## Notes\n\nlater.\n',
    )
    assert _truncations(validate_canon_file(path, project)) == []


def test_validate_filled_canon_no_unfilled_finding(tmp_path):
    """A canon file with real content in every section must not register
    as unfilled. Only a first-non-blank-line `TODO` prefix decides on one
    line; the emphasis / bare-placeholder rules are whole-body tests, so a
    section holding any substantive line is filled (see
    _section_body_is_placeholder)."""
    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    findings = validate_canon_file(
        os.path.join(project, CANON_DIR, 'style-foundation.md'), project,
    )
    assert [f for f in findings if f['type'] == 'canon_unfilled_template'] == []


@pytest.mark.parametrize('placeholder_text', [
    '_(fill this in)_', 'TBD', 'todo', '_Required: describe the palette_',
    '(you fill this in)',
])
def test_hand_typed_placeholder_shapes_are_flagged_unfilled(
        tmp_path, placeholder_text):
    """Regression: the pre-canon illustrations._is_placeholder recognized
    five hand-typed scaffold shapes (emphasized boilerplate, bare
    TBD/todo/n-a/fill-this-in) in addition to the TODO-prefixed lines the
    shipped templates themselves emit. When that detector was retired in
    favor of canon._section_body_is_placeholder (illustration-canon-adoption
    Task 7), the narrower TODO-only version silently stopped catching four
    of these five shapes — a hand-typed `_(fill this in)_` Embeddable block
    read as populated and would have been fed to an image model as house
    style. _section_body_is_placeholder now recognizes all five; this is
    the canon-level (not illustration-specific) coverage for that, since
    the widening is shared with GN's canon_unfilled_template finding and
    is_canon_block_populated gate."""
    project = str(tmp_path)
    body = f'\n## Embeddable block\n\n{placeholder_text}\n\n## Clauses\n\n## Related canon\n\n## Iteration history\n'
    write_canon(project, 'style-foundation.md', 'style-foundation', body=body)
    findings = validate_canon_file(
        os.path.join(project, CANON_DIR, 'style-foundation.md'), project,
    )
    unfilled = [f for f in findings if f['type'] == 'canon_unfilled_template']
    assert len(unfilled) == 1, (
        f'{placeholder_text!r} was not flagged as unfilled: {findings}'
    )
    assert 'Embeddable block' in unfilled[0]['detail']


@pytest.mark.parametrize('block', [
    '**Nora Vance**\n9 years old, 132 cm, a dark braid over one shoulder.',
    '_The lamp remembers._\nA squat brass lantern, dented on the left face.',
    '**Style:** cinematic, warm, hand-inked.',
    '**Dominant / transitional / rhythmic.**\nDominant panels carry the beat.',
])
def test_real_prose_is_not_mistaken_for_a_placeholder(tmp_path, block):
    """Regression for the branch's CRITICAL: the emphasis and bare-placeholder
    rules are WHOLE-BODY tests, restored from the retired
    illustrations._is_placeholder (whose negative guard,
    test_real_prose_is_not_mistaken_for_a_placeholder in test_illustrations.py,
    was deleted with it). Deciding on the first non-blank line instead made a
    filled Embeddable block whose first line happens to be wholly emphasized
    read as a scaffold — a continuity anchor opening with a bold character
    name dropped out of anchor_texts entirely, so every prompt for that
    character rendered with no anchor; on the GN side a register vocabulary
    opening `**Dominant / transitional / rhythmic.**` failed
    is_canon_block_populated and blocked `elaborate --stage
    page-architecture`.
    """
    from storyforge.canon import _section_body_is_placeholder
    project = str(tmp_path)
    body = (f'\n## Embeddable block\n\n{block}\n\n## Clauses\n\n'
            f'## Related canon\n\n## Iteration history\n')
    write_canon(project, 'characters/nora.md', 'nora',
                canon_type='character', body=body)
    assert _section_body_is_placeholder(f'\n{block}\n') is False
    findings = validate_canon_file(
        os.path.join(project, CANON_DIR, 'characters', 'nora.md'), project,
    )
    unfilled = [f for f in findings if f['type'] == 'canon_unfilled_template']
    assert unfilled == [], f'{block!r} was misread as a placeholder'


def test_first_line_todo_still_wins_over_following_prose(tmp_path):
    """The first-line TODO rule is deliberately NOT whole-body: GN's
    page-architecture gate has keyed on it since before the canon adoption,
    and a scaffold whose author started answering below the TODO line is
    still a scaffold until the TODO comes out."""
    from storyforge.canon import _section_body_is_placeholder
    assert _section_body_is_placeholder(
        '\nTODO — describe the palette.\nWarm amber and gold.\n') is True


def test_bold_anchor_survives_anchor_texts(tmp_path):
    """End-to-end for the same regression: a bold-lead anchor must reach
    anchor_texts verbatim, since that dict is what every prompt embeds."""
    from storyforge.canon import anchor_texts
    project = str(tmp_path)
    block = '**Nora Vance**\n9 years old, 132 cm, a dark braid.'
    write_canon(project, 'characters/nora.md', 'nora', canon_type='character',
                body=f'\n## Embeddable block\n\n{block}\n\n## Clauses\n\n'
                     f'## Related canon\n\n## Iteration history\n')
    assert anchor_texts(project) == {'nora': block}


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
    not register as drift. normalize_for_comparison now lstrips per line."""
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


def test_cleanup_report_validates_canon_in_novel_project(tmp_path):
    """SF-4: canon/ present in a novel project is validated the same as a
    graphic-novel project's — a broken file surfaces its real structural
    finding rather than being skipped wholesale.
    """
    from storyforge.cmd_cleanup import report_canon_files

    project = str(tmp_path)
    os.makedirs(project, exist_ok=True)
    with open(os.path.join(project, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  medium: novel\n')
    write_canon(project, 'style-foundation.md', 'mismatched-id')
    findings = report_canon_files(project)
    assert len(findings) == 1
    assert findings[0]['type'] == 'canon_id_mismatch'
    assert findings[0]['category'] == 'canon'


def test_cleanup_report_validates_canon_when_no_yaml(tmp_path):
    """SF-4: missing storyforge.yaml causes get_medium → 'novel' fallback.
    Canon validation still runs normally, so a well-formed canon file
    produces no findings even without a storyforge.yaml.
    """
    from storyforge.cmd_cleanup import report_canon_files

    project = str(tmp_path)
    write_canon(project, 'style-foundation.md', 'style-foundation')
    findings = report_canon_files(project)
    assert findings == []


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
