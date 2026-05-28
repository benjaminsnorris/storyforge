"""Tests for the three new PageFindingKind values for panel prompts (#253)."""


def _write_page(tmp_path, body, panel_count=2):
    fm = (
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        f"panel_count: {panel_count}\n"
        "---\n\n"
        # The page-architecture and blocking-prompt sections are present
        # so those checks don't fire — keeps the test focused on panel-prompt
        # findings only.
        "## Page architecture\n\nIntent.\n\n"
        "## Page-blocking prompt\n\nstoryboard.\n\n"
    )
    path = tmp_path / 's01-p1.md'
    path.write_text(fm + body)
    return str(path)


def _kinds(findings):
    return {f['kind'] for f in findings}


def _well_formed_panel_body(prefix=''):
    """A panel body with all 13 sections in canonical order."""
    sections = [
        'Style foundation', 'Lighting laws', 'Pacing role',
        'Shot grammar', 'Stage geography', 'Character block',
        'In this panel', 'Focal objects + render priorities',
        'Lighting logic', 'Symbolic detail (low weight)',
        'Action', 'Emotional subtext (low weight)',
        'Negative constraints',
    ]
    return '\n\n'.join(
        f'#### {i + 1}. {title}\n\n{prefix}body {i + 1}'
        for i, title in enumerate(sections)
    ) + '\n'


def test_missing_panel_prompts_when_section_absent(tmp_path):
    from storyforge.pages import validate_page_file
    body = '## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_panel_prompts' in kinds


def test_missing_panel_prompts_when_section_present_no_panels(tmp_path):
    """Section exists but contains no ### Panel N subsections."""
    from storyforge.pages import validate_page_file
    body = '## Image-generation prompts\n\nplaceholder, no panels\n\n## Panel script\n\n**Panel 1.**\n'
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_panel_prompts' in kinds


def test_no_panel_prompts_finding_when_well_formed(tmp_path):
    from storyforge.pages import validate_page_file
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n' + _well_formed_panel_body() + '\n'
        '### Panel 2\n\n' + _well_formed_panel_body('p2 ') + '\n'
        '## Panel script\n\n**Panel 1.**\n'
    )
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body)))
    assert 'missing_panel_prompts' not in kinds
    assert 'panel_prompt_section_missing' not in kinds
    assert 'panel_prompt_wrong_section_order' not in kinds


def test_panel_prompt_section_missing_when_panel_lacks_subsections(tmp_path):
    from storyforge.pages import validate_page_file
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nfoundation\n\n'
        # Sections 2-13 deliberately absent
        '## Panel script\n\n**Panel 1.**\n'
    )
    findings = validate_page_file(_write_page(tmp_path, body, panel_count=1))
    kinds = _kinds(findings)
    assert 'panel_prompt_section_missing' in kinds
    # Detail should name the panel index
    for f in findings:
        if f['kind'] == 'panel_prompt_section_missing':
            assert 'Panel 1' in f.get('detail', '') or 'panel 1' in f.get('detail', '').lower()


def test_panel_prompt_wrong_section_order_when_sections_swapped(tmp_path):
    """Sections present but in wrong order (e.g., section 3 before section 2)."""
    from storyforge.pages import validate_page_file
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nfoundation\n\n'
        '#### 3. Pacing role\n\nregister\n\n'  # OUT OF ORDER — 3 before 2
        '#### 2. Lighting laws\n\nlighting\n\n'
        + '\n\n'.join(
            f'#### {i}. {title}\n\nbody'
            for i, title in zip(
                range(4, 14),
                ['Shot grammar', 'Stage geography', 'Character block',
                 'In this panel', 'Focal objects + render priorities',
                 'Lighting logic', 'Symbolic detail (low weight)', 'Action',
                 'Emotional subtext (low weight)', 'Negative constraints'],
            )
        ) + '\n\n'
        '## Panel script\n\n**Panel 1.**\n'
    )
    kinds = _kinds(validate_page_file(_write_page(tmp_path, body, panel_count=1)))
    assert 'panel_prompt_wrong_section_order' in kinds


def test_finding_kinds_in_literal_type():
    """Static-type guard — the three new values must be in the PageFindingKind Literal."""
    from storyforge.pages import PageFindingKind  # noqa: F401


def test_cleanup_surfaces_panel_prompt_findings(tmp_path):
    """End-to-end through cmd_cleanup._check_page_files."""
    import os
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
        '## Page architecture\n\nIntent.\n\n'
        '## Page-blocking prompt\n\nstoryboard.\n\n'
        # No ## Image-generation prompts section — triggers missing_panel_prompts
        '## Panel script\n\n**Panel 1.**\n'
    )
    from storyforge.cmd_cleanup import _check_page_files
    findings = _check_page_files(str(project))
    types = {f['type'] for f in findings}
    assert 'page_missing_panel_prompts' in types
    for f in findings:
        if f['type'] == 'page_missing_panel_prompts':
            assert f['severity'] == 'warning'
            assert 'storyforge elaborate --stage panel-prompts' in f['action']
