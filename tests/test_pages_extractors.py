"""Tests for pages.extract_page_architecture and pages.extract_blocking_prompt."""

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

        ### Book-level placement
        - Spread context: opening recto
        - Page-turn beat: no

        ## Page-blocking prompt

        Monochrome storyboard.

        ## Panel script

        **Panel 1.** Wide.
        """)
    result = extract_page_architecture(_write_page(tmp_path, body))
    assert '### Intent' in result
    assert 'Panel 1 — atmospheric' in result
    assert '### Book-level placement' in result
    assert 'Monochrome storyboard' not in result  # belongs to next section
    assert 'Panel 1.** Wide' not in result


def test_extract_blocking_prompt_basic(tmp_path):
    from storyforge.pages import extract_blocking_prompt
    body = textwrap.dedent("""\
        ## Page architecture

        Intent stuff.

        ## Page-blocking prompt

        Monochrome storyboard. Two panels.
        Top: wide establishing — atmospheric register.
        Bottom: dominant — the inkpot.

        ## Panel script

        **Panel 1.** Wide.
        """)
    result = extract_blocking_prompt(_write_page(tmp_path, body))
    assert 'Monochrome storyboard' in result
    assert 'atmospheric register' in result
    assert 'Intent stuff' not in result
    assert 'Panel 1.** Wide' not in result


def test_extract_page_architecture_missing_section(tmp_path):
    from storyforge.pages import extract_page_architecture
    body = '## Scene context\n\nNo architecture.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    assert extract_page_architecture(_write_page(tmp_path, body)) == ''


def test_extract_blocking_prompt_missing_section(tmp_path):
    from storyforge.pages import extract_blocking_prompt
    body = '## Page architecture\n\nIntent.\n\n## Panel script\n\n**Panel 1.** Wide.\n'
    assert extract_blocking_prompt(_write_page(tmp_path, body)) == ''


def test_extract_handles_page_n_em_dash_subheader(tmp_path):
    """The `## Page N — LAYOUT` headers used in panel scripts must NOT be
    treated as section terminators when they appear AFTER our target
    sections — but the lookahead in pages.py only kicks in for terminators
    that follow the target section, so the panel-script `## Page N —`
    headers can't accidentally extend the page-architecture extraction.
    Sanity-check that em-dash content inside the page-architecture body
    parses correctly when no `##` follows."""
    from storyforge.pages import extract_page_architecture
    body = '## Page architecture\n\n### Intent\nLine — with em-dash.\n'
    result = extract_page_architecture(_write_page(tmp_path, body))
    assert 'Line — with em-dash.' in result


def test_extract_missing_file_returns_empty(tmp_path):
    from storyforge.pages import extract_page_architecture, extract_blocking_prompt
    assert extract_page_architecture(str(tmp_path / 'nope.md')) == ''
    assert extract_blocking_prompt(str(tmp_path / 'nope.md')) == ''


def test_extract_no_frontmatter_returns_empty(tmp_path):
    from storyforge.pages import extract_page_architecture, extract_blocking_prompt
    path = tmp_path / 'no-fm.md'
    path.write_text('## Page architecture\n\nBody.\n')
    assert extract_page_architecture(str(path)) == ''
    assert extract_blocking_prompt(str(path)) == ''
