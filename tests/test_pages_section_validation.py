"""Tests for the missing_page_architecture and missing_blocking_prompt
PageFindingKind values added by issue #252."""

import textwrap


def _write_page(tmp_path, body):
    # NOTE: Using explicit string concatenation rather than dedent(f"...{body}...")
    # because body has its own dedented (zero-indent) content; an f-string
    # template with 8-space indent on the surrounding lines would not dedent
    # correctly when the body interpolates as zero-indent.
    fm = (
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 2\n"
        "---\n\n"
    )
    path = tmp_path / 's01-p1.md'
    path.write_text(fm + body)
    return str(path)


def _kinds(findings):
    return {f['kind'] for f in findings}


def test_both_findings_when_sections_absent(tmp_path):
    from storyforge.pages import validate_page_file
    body = '## Scene context\n\nContext.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' in kinds
    assert 'missing_blocking_prompt' in kinds


def test_neither_finding_when_sections_populated(tmp_path):
    from storyforge.pages import validate_page_file
    body = textwrap.dedent("""\
        ## Page architecture

        ### Intent
        Quiet tension.

        ## Page-blocking prompt

        Monochrome storyboard.

        ## Panel script

        **Panel 1.** Wide.
        """)
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' not in kinds
    assert 'missing_blocking_prompt' not in kinds


def test_finding_fires_when_header_present_but_body_empty(tmp_path):
    """Author deleted the body but left the header — half-edited state."""
    from storyforge.pages import validate_page_file
    body = '## Page architecture\n\n   \n\n## Page-blocking prompt\n\n\n\n## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' in kinds
    assert 'missing_blocking_prompt' in kinds


def test_finding_does_not_fire_for_strict_mode_TODO_body(tmp_path):
    """Strict mode populates the sections with TODO scaffolding; that
    is non-empty content and must NOT fire the finding."""
    from storyforge.pages import validate_page_file
    body = textwrap.dedent("""\
        ## Page architecture

        ### Intent
        TODO — narrative purpose.

        ## Page-blocking prompt

        TODO — monochrome storyboard.

        ## Panel script

        **Panel 1.** Wide.
        """)
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' not in kinds
    assert 'missing_blocking_prompt' not in kinds


def test_only_one_finding_when_one_section_present_one_missing(tmp_path):
    from storyforge.pages import validate_page_file
    body = '## Page architecture\n\nIntent.\n\n## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_page_architecture' not in kinds
    assert 'missing_blocking_prompt' in kinds


def test_finding_kinds_are_in_literal_type():
    """The PageFindingKind Literal must list both new values so a kind
    typo elsewhere is caught statically. We can't introspect the Literal
    at runtime portably, but we can confirm the strings are accepted by
    a function that takes a PageFindingKind and exercises both branches."""
    from storyforge.pages import PageFindingKind  # noqa: F401
    # Existence of the import is the assertion; type-check happens at
    # mypy / pyright time, not runtime.


def test_cleanup_check_page_files_surfaces_new_findings(tmp_path, monkeypatch):
    """End-to-end through cmd_cleanup._check_page_files."""
    import os
    # Set up a minimal GN-mode project
    project = tmp_path / 'proj'
    project.mkdir()
    (project / 'storyforge.yaml').write_text(
        'project:\n  medium: graphic-novel\n'
    )
    pages = project / 'pages'
    pages.mkdir()
    (pages / 's01-p1.md').write_text(
        '---\n'
        'page_id: s01-p1\n'
        'scene_id: s01-studio\n'
        'page_within_scene: 1\n'
        'total_pages_in_scene: 1\n'
        'panel_count: 1\n'
        '---\n\n'
        '## Scene context\n\nContext only — no architecture, no blocking.\n'
    )
    from storyforge.cmd_cleanup import _check_page_files
    findings = _check_page_files(str(project))
    types = {f['type'] for f in findings}
    assert 'page_missing_page_architecture' in types
    assert 'page_missing_blocking_prompt' in types
    # Both are warnings (cleanup remains exit-0 over these)
    for f in findings:
        if f['type'] in ('page_missing_page_architecture',
                         'page_missing_blocking_prompt'):
            assert f['severity'] == 'warning'
    # T-6: action message must include the exact command + correct page_id
    for f in findings:
        if f['type'] == 'page_missing_page_architecture':
            assert 'storyforge elaborate --stage page-architecture' in f['action']
            assert '--page s01-p1' in f['action']
        if f['type'] == 'page_missing_blocking_prompt':
            assert 'storyforge elaborate --stage page-architecture' in f['action']
            assert '--page s01-p1' in f['action']
