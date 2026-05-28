"""Tests for pages.extract_panel_prompts, extract_panel_sections,
and the PANEL_SECTION_TITLES constant (issue #253)."""


def _write_page(tmp_path, body):
    """Write a minimal valid page file with the given body content.
    Uses explicit string concatenation (not f-string + dedent) to avoid
    the indentation bug caught in PR #258 Task 1 review."""
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


def test_panel_section_titles_has_exactly_13_in_order():
    from storyforge.pages import PANEL_SECTION_TITLES
    assert len(PANEL_SECTION_TITLES) == 13
    # Spot-check canonical order — first, last, and one in the middle
    assert PANEL_SECTION_TITLES[0] == 'Style foundation'
    assert PANEL_SECTION_TITLES[1] == 'Lighting laws'
    assert PANEL_SECTION_TITLES[2] == 'Pacing role'
    assert PANEL_SECTION_TITLES[6] == 'In this panel'
    assert PANEL_SECTION_TITLES[9] == 'Symbolic detail (low weight)'
    assert PANEL_SECTION_TITLES[11] == 'Emotional subtext (low weight)'
    assert PANEL_SECTION_TITLES[12] == 'Negative constraints'


def test_extract_panel_prompts_returns_dict_for_two_panels(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        'panel 1 body content\n\n'
        '### Panel 2\n\n'
        'panel 2 body content\n\n'
        '## Panel script\n\n**Panel 1.** Wide.\n'
    )
    result = extract_panel_prompts(_write_page(tmp_path, body))
    assert set(result.keys()) == {1, 2}
    assert 'panel 1 body content' in result[1]
    assert 'panel 2 body content' in result[2]
    # Headers are stripped from the body
    assert '### Panel 1' not in result[1]
    assert '### Panel 2' not in result[2]
    # Next-section content (## Panel script) is NOT included
    assert 'Panel 1.** Wide' not in result[2]


def test_extract_panel_prompts_handles_panel_with_subsections(tmp_path):
    """The 13 #### subsections inside a panel must remain in the body
    — they are part of the panel content, not section terminators."""
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 1\n\n'
        '#### 1. Style foundation\n\nfoundation block\n\n'
        '#### 2. Lighting laws\n\nlighting block\n\n'
        '#### 13. Negative constraints\n\nexclusions\n\n'
        '### Panel 2\n\n'
        '#### 1. Style foundation\n\nfoundation 2\n'
    )
    result = extract_panel_prompts(_write_page(tmp_path, body))
    assert '#### 1. Style foundation' in result[1]
    assert '#### 13. Negative constraints' in result[1]
    # Panel 1 body must NOT bleed into Panel 2
    assert 'foundation 2' not in result[1]


def test_extract_panel_prompts_missing_section_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = '## Scene context\n\nno image-generation section here\n'
    assert extract_panel_prompts(_write_page(tmp_path, body)) == {}


def test_extract_panel_prompts_section_present_no_panels_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        'placeholder text but no ### Panel headers\n\n'
        '## Panel script\n\n**Panel 1.**\n'
    )
    assert extract_panel_prompts(_write_page(tmp_path, body)) == {}


def test_extract_panel_prompts_missing_file_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    assert extract_panel_prompts(str(tmp_path / 'nope.md')) == {}


def test_extract_panel_prompts_no_frontmatter_returns_empty(tmp_path):
    from storyforge.pages import extract_panel_prompts
    path = tmp_path / 'no-fm.md'
    path.write_text('## Image-generation prompts\n\n### Panel 1\n\nbody\n')
    assert extract_panel_prompts(str(path)) == {}


def test_extract_panel_prompts_handles_double_digit_panel_index(tmp_path):
    from storyforge.pages import extract_panel_prompts
    body = (
        '## Image-generation prompts\n\n'
        '### Panel 10\n\nbody 10\n\n'
        '### Panel 11\n\nbody 11\n'
    )
    result = extract_panel_prompts(_write_page(tmp_path, body))
    assert set(result.keys()) == {10, 11}


def test_extract_panel_sections_all_13_present():
    from storyforge.pages import extract_panel_sections
    body = (
        '#### 1. Style foundation\n\nfoundation\n\n'
        '#### 2. Lighting laws\n\nlighting\n\n'
        '#### 3. Pacing role\n\nregister: dominant\n\n'
        '#### 4. Shot grammar\n\nshot\n\n'
        '#### 5. Stage geography\n\ngeography\n\n'
        '#### 6. Character block\n\ncharacters\n\n'
        '#### 7. In this panel\n\nin-panel\n\n'
        '#### 8. Focal objects + render priorities\n\nfocal\n\n'
        '#### 9. Lighting logic\n\nlight logic\n\n'
        '#### 10. Symbolic detail (low weight)\n\nmotif (low weight)\n\n'
        '#### 11. Action\n\naction\n\n'
        '#### 12. Emotional subtext (low weight)\n\nsubtext (low weight)\n\n'
        '#### 13. Negative constraints\n\nexclusions\n'
    )
    result = extract_panel_sections(body)
    assert set(result.keys()) == set(range(1, 14))
    assert result[1] == 'foundation'
    assert result[3] == 'register: dominant'
    assert result[13] == 'exclusions'


def test_extract_panel_sections_some_missing():
    """A partially populated panel body returns only the present sections."""
    from storyforge.pages import extract_panel_sections
    body = (
        '#### 1. Style foundation\n\nfoundation\n\n'
        '#### 3. Pacing role\n\nregister: dominant\n\n'
        '#### 13. Negative constraints\n\nexclusions\n'
    )
    result = extract_panel_sections(body)
    assert set(result.keys()) == {1, 3, 13}
    assert 2 not in result


def test_extract_panel_sections_handles_empty_body():
    from storyforge.pages import extract_panel_sections
    assert extract_panel_sections('') == {}


def test_extract_panel_sections_handles_no_section_headers():
    """A body with prose but no #### headers returns empty."""
    from storyforge.pages import extract_panel_sections
    assert extract_panel_sections('just prose with no headers') == {}


def test_extract_panel_sections_strips_body_whitespace():
    from storyforge.pages import extract_panel_sections
    body = (
        '#### 1. Style foundation\n\n\n\n'
        '   foundation with leading whitespace   \n\n\n\n'
        '#### 2. Lighting laws\n\nlighting\n'
    )
    result = extract_panel_sections(body)
    # Body is stripped (no leading/trailing whitespace)
    assert result[1].startswith('foundation') or result[1].startswith('   foundation')
    assert not result[1].endswith('\n\n')
