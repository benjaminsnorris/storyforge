"""Tests for pages.extract_page_architecture and pages.extract_image_workflow."""

import textwrap


def _write_page(tmp_path, body):
    """Write a minimal valid page file with the given body content."""
    text = (
        "---\n"
        "page_id: s01-p1\n"
        "scene_id: s01-studio\n"
        "page_within_scene: 1\n"
        "total_pages_in_scene: 1\n"
        "panel_count: 2\n"
        "---\n"
        "\n"
        + body
    )
    path = tmp_path / 's01-p1.md'
    path.write_text(text)
    return str(path)


def test_extract_page_architecture_basic(tmp_path):
    from storyforge.pages import extract_page_architecture
    body = textwrap.dedent("""\
        ## Scene context

        Some context.

        ## Page architecture

        ### Intent
        Open the scene with quiet tension.

        ### Panel hierarchy
        - Panel 1 — atmospheric: establishing
        - Panel 2 — dominant: the inkpot

        ### Layout
        Two-row grid, eye flow left-to-right.

        ## Panel script

        **Panel 1.** Wide.
        """)
    result = extract_page_architecture(_write_page(tmp_path, body))
    assert '### Intent' in result
    assert 'Panel 1 — atmospheric' in result
    assert '### Layout' in result
    assert 'Panel 1.** Wide' not in result  # belongs to next section


def test_extract_page_architecture_tolerates_parenthetical(tmp_path):
    """The v3 hand-authored convention uses '## Page architecture (authoring
    context)'; the extractor must match it as well as the plain header."""
    from storyforge.pages import extract_page_architecture
    body = ('## Page architecture (authoring context)\n\n'
            '### Intent\nThe work begins.\n\n'
            '## Panel script\n\n**Panel 1.** Wide.\n')
    result = extract_page_architecture(_write_page(tmp_path, body))
    assert 'The work begins.' in result
    assert 'Panel 1.** Wide' not in result


def test_extract_image_workflow_basic(tmp_path):
    from storyforge.pages import extract_image_workflow
    body = textwrap.dedent("""\
        ## Panel script

        **Panel 1.** Wide.

        ## Image-generation workflow

        **Approach (GPT Image 2):** Whole-page generation.

        ### Page prompt (paste into ChatGPT alongside the references)

        > **Scene:** A studio at dusk.

        ## Page-specific notes for the artist

        - note
        """)
    result = extract_image_workflow(_write_page(tmp_path, body))
    assert 'Whole-page generation' in result
    assert '**Scene:** A studio at dusk.' in result
    assert 'Panel 1.** Wide' not in result  # prior section
    assert '- note' not in result  # next section


def test_extract_page_architecture_missing_section(tmp_path):
    from storyforge.pages import extract_page_architecture
    body = '## Scene context\n\nNo architecture.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    assert extract_page_architecture(_write_page(tmp_path, body)) == ''


def test_extract_image_workflow_missing_section(tmp_path):
    from storyforge.pages import extract_image_workflow
    body = '## Page architecture\n\nIntent.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    assert extract_image_workflow(_write_page(tmp_path, body)) == ''


def test_extract_handles_em_dash_in_body(tmp_path):
    from storyforge.pages import extract_page_architecture
    body = '## Page architecture\n\n### Intent\nLine — with em-dash.\n'
    result = extract_page_architecture(_write_page(tmp_path, body))
    assert 'Line — with em-dash.' in result


def test_extract_missing_file_returns_empty(tmp_path):
    from storyforge.pages import extract_page_architecture, extract_image_workflow
    assert extract_page_architecture(str(tmp_path / 'nope.md')) == ''
    assert extract_image_workflow(str(tmp_path / 'nope.md')) == ''


def test_extract_no_frontmatter_returns_empty(tmp_path):
    from storyforge.pages import extract_page_architecture, extract_image_workflow
    path = tmp_path / 'no-fm.md'
    path.write_text('## Page architecture\n\nBody.\n')
    assert extract_page_architecture(str(path)) == ''
    assert extract_image_workflow(str(path)) == ''
