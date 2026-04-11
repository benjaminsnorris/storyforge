"""Regression tests for clean_scene_content in parsing.py.

Issue #152: Write pipeline should strip scene titles and continuity tracker
blocks from output before committing scene files.
"""

from storyforge.parsing import clean_scene_content


class TestStripLeadingHeaders:
    """Strip H1/H2 scene title headers from the start of scene content."""

    def test_strip_h1_title(self):
        text = "# The Third Drawer Stays Closed\n\nThe drawer had been sealed.\n"
        result = clean_scene_content(text)
        assert result == "The drawer had been sealed.\n"

    def test_strip_h2_title(self):
        text = "## The Third Drawer Stays Closed\n\nThe drawer had been sealed.\n"
        result = clean_scene_content(text)
        assert result == "The drawer had been sealed.\n"

    def test_strip_h1_with_leading_blanks(self):
        text = "\n\n# The Third Drawer Stays Closed\n\nThe drawer had been sealed.\n"
        result = clean_scene_content(text)
        assert result == "The drawer had been sealed.\n"

    def test_strip_h1_no_trailing_blank(self):
        text = "# Scene Title\nThe prose starts here.\n"
        result = clean_scene_content(text)
        assert result == "The prose starts here.\n"

    def test_no_header_unchanged(self):
        text = "The drawer had been sealed for years.\n"
        result = clean_scene_content(text)
        assert result == "The drawer had been sealed for years.\n"

    def test_h3_not_stripped(self):
        """H3 and below are not scene titles — they should be kept."""
        text = "### A Section Header\n\nSome prose.\n"
        result = clean_scene_content(text)
        assert result == "### A Section Header\n\nSome prose.\n"

    def test_midfile_header_not_stripped(self):
        """Only leading headers are stripped; mid-file headers are kept."""
        text = "Some prose.\n\n# A Later Section\n\nMore prose.\n"
        result = clean_scene_content(text)
        assert result == "Some prose.\n\n# A Later Section\n\nMore prose.\n"

    def test_header_must_have_content_after_hash(self):
        """A line that is just '#' or '## ' is not a header to strip."""
        text = "#\n\nSome prose.\n"
        result = clean_scene_content(text)
        assert result == "#\n\nSome prose.\n"


class TestStripContinuityTracker:
    """Strip trailing Continuity Tracker Update blocks."""

    def test_strip_continuity_block_with_separator(self):
        text = (
            "The drawer had been sealed.\n"
            "\n"
            "---\n"
            "\n"
            "# Continuity Tracker Update\n"
            "\n"
            "## Character States\n"
            "- Elara: frustrated\n"
            "\n"
            "## Established Details\n"
            "- The drawer is locked\n"
        )
        result = clean_scene_content(text)
        assert result == "The drawer had been sealed.\n"

    def test_strip_continuity_block_h2(self):
        text = (
            "Some prose here.\n"
            "\n"
            "---\n"
            "\n"
            "## Continuity Tracker Update\n"
            "\n"
            "- Detail one\n"
        )
        result = clean_scene_content(text)
        assert result == "Some prose here.\n"

    def test_strip_continuity_block_h3(self):
        text = (
            "Some prose here.\n"
            "\n"
            "---\n"
            "\n"
            "### Continuity tracker update\n"
            "\n"
            "- Detail one\n"
        )
        result = clean_scene_content(text)
        assert result == "Some prose here.\n"

    def test_strip_continuity_block_no_separator(self):
        """Continuity block without --- separator should still be stripped."""
        text = (
            "Some prose here.\n"
            "\n"
            "# Continuity Tracker Update\n"
            "\n"
            "- Character states\n"
        )
        result = clean_scene_content(text)
        assert result == "Some prose here.\n"

    def test_no_continuity_block_unchanged(self):
        text = "The drawer had been sealed.\n\nShe turned the key.\n"
        result = clean_scene_content(text)
        assert result == "The drawer had been sealed.\n\nShe turned the key.\n"

    def test_separator_without_continuity_header_kept(self):
        """A trailing --- that is NOT followed by a Continuity header stays."""
        text = "Some prose.\n\n---\n\nMore prose.\n"
        result = clean_scene_content(text)
        assert result == "Some prose.\n\n---\n\nMore prose.\n"


class TestBothArtifacts:
    """Strip both title header and continuity block together."""

    def test_strip_title_and_continuity(self):
        text = (
            "# The Third Drawer Stays Closed\n"
            "\n"
            "The drawer had been sealed for years.\n"
            "\n"
            "She reached for it anyway.\n"
            "\n"
            "---\n"
            "\n"
            "# Continuity Tracker Update\n"
            "\n"
            "## Character States\n"
            "- Elara: anxious\n"
        )
        result = clean_scene_content(text)
        expected = (
            "The drawer had been sealed for years.\n"
            "\n"
            "She reached for it anyway.\n"
        )
        assert result == expected


class TestEdgeCases:
    """Edge cases for clean_scene_content."""

    def test_empty_string(self):
        assert clean_scene_content("") == ""

    def test_whitespace_only(self):
        assert clean_scene_content("   \n\n  ") == "   \n\n  "

    def test_none_passthrough(self):
        """None input should pass through without error."""
        # The function checks for falsy input first
        assert clean_scene_content(None) is None

    def test_only_header_then_empty(self):
        text = "# Just a Title\n"
        result = clean_scene_content(text)
        assert result == ""

    def test_preserves_internal_structure(self):
        """Internal section breaks and formatting should be preserved."""
        text = (
            "She opened the door.\n"
            "\n"
            "---\n"
            "\n"
            "Hours later, the sun set.\n"
            "\n"
            "The end.\n"
        )
        result = clean_scene_content(text)
        assert result == text.strip() + "\n"

    def test_ensures_single_trailing_newline(self):
        text = "Some prose.\n\n\n"
        result = clean_scene_content(text)
        assert result == "Some prose.\n"
        assert result.endswith("\n")
        assert not result.endswith("\n\n")
