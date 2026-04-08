"""Tests for cmd_cover command module."""

import pytest
from storyforge.cmd_cover import parse_args
from storyforge.cover import (
    get_color_scheme, _compute_title_size, _max_chars_for_size,
    wrap_title_for_svg, _escape_xml, DEFAULT_SCHEME, COLOR_SCHEMES,
    PALETTE_OVERRIDES, _GENRE_ALIASES,
)


class TestParseArgs:
    """Argument parsing for storyforge cover."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run
        assert not args.svg_only
        assert args.output == ''

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_svg_only(self):
        args = parse_args(['--svg-only'])
        assert args.svg_only

    def test_output_path(self):
        args = parse_args(['--output', '/tmp/cover.png'])
        assert args.output == '/tmp/cover.png'

    def test_combined_flags(self):
        args = parse_args(['--svg-only', '--dry-run'])
        assert args.svg_only
        assert args.dry_run


class TestGetColorScheme:
    """get_color_scheme returns correct genre palettes."""

    def test_fantasy_scheme(self):
        scheme = get_color_scheme('fantasy')
        assert scheme['bg'] == '#1a1a2e'
        assert 'accent' in scheme

    def test_science_fiction(self):
        scheme = get_color_scheme('science-fiction')
        assert scheme['bg'] == '#0d1117'

    def test_thriller(self):
        scheme = get_color_scheme('thriller')
        assert scheme['bg'] == '#111111'

    def test_romance(self):
        scheme = get_color_scheme('romance')
        assert scheme['bg'] == '#2d1b2e'

    def test_literary_fiction(self):
        scheme = get_color_scheme('literary-fiction')
        assert scheme['bg'] == '#f5f0e8'

    def test_unknown_genre_gets_default(self):
        scheme = get_color_scheme('completely-unknown')
        assert scheme == DEFAULT_SCHEME

    def test_alias_resolution(self):
        """Genre aliases resolve to parent scheme."""
        for alias, parent in _GENRE_ALIASES.items():
            alias_scheme = get_color_scheme(alias)
            parent_scheme = get_color_scheme(parent)
            assert alias_scheme == parent_scheme, f'{alias} should resolve to {parent}'

    def test_case_insensitive(self):
        scheme = get_color_scheme('FANTASY')
        assert scheme['bg'] == '#1a1a2e'

    def test_spaces_to_hyphens(self):
        scheme = get_color_scheme('science fiction')
        assert scheme['bg'] == '#0d1117'

    def test_palette_override_warm(self):
        scheme = get_color_scheme('fantasy', 'warm')
        assert scheme == PALETTE_OVERRIDES['warm']

    def test_palette_override_cool(self):
        scheme = get_color_scheme('thriller', 'cool')
        assert scheme == PALETTE_OVERRIDES['cool']

    def test_palette_override_dark(self):
        scheme = get_color_scheme('romance', 'dark')
        assert scheme == PALETTE_OVERRIDES['dark']

    def test_palette_override_light(self):
        scheme = get_color_scheme('literary-fiction', 'light')
        assert scheme == PALETTE_OVERRIDES['light']

    def test_invalid_palette_uses_genre(self):
        scheme = get_color_scheme('fantasy', 'nonexistent')
        assert scheme['bg'] == '#1a1a2e'

    def test_returns_copy(self):
        """Should return a copy, not a reference to the original."""
        scheme = get_color_scheme('fantasy')
        scheme['bg'] = 'modified'
        fresh = get_color_scheme('fantasy')
        assert fresh['bg'] == '#1a1a2e'

    def test_all_schemes_have_required_keys(self):
        required = {'bg', 'bg2', 'accent', 'accent2', 'text', 'text_dim'}
        for genre, scheme in COLOR_SCHEMES.items():
            if scheme is None:
                continue  # alias
            assert required.issubset(scheme.keys()), f'{genre} missing keys'


class TestComputeTitleSize:
    """_compute_title_size scales font by title length."""

    def test_short_title(self):
        assert _compute_title_size('Echo') == 140

    def test_medium_title(self):
        assert _compute_title_size('The Silence') == 120

    def test_mid_length_title(self):
        # 20 chars, falls in 16-25 range -> 96
        assert _compute_title_size('The Silent Boundary') == 96

    def test_longer_title(self):
        # 26 chars, falls in 26-40 range -> 72
        assert _compute_title_size("The Cartographer's Silence") == 72

    def test_long_title(self):
        # 36 chars still in 26-40 range -> 72
        assert _compute_title_size('A Very Long Title That Stretches Far') == 72

    def test_very_long_title(self):
        assert _compute_title_size('x' * 50) == 56


class TestMaxCharsForSize:
    """_max_chars_for_size returns correct line widths."""

    def test_large_font(self):
        assert _max_chars_for_size(140) == 12

    def test_medium_large_font(self):
        assert _max_chars_for_size(96) == 16

    def test_medium_font(self):
        assert _max_chars_for_size(72) == 22

    def test_small_font(self):
        assert _max_chars_for_size(56) == 30


class TestWrapTitleForSvg:
    """wrap_title_for_svg splits at word boundaries."""

    def test_short_title_no_wrap(self):
        lines = wrap_title_for_svg('Echo', 20)
        assert lines == ['Echo']

    def test_wraps_at_word_boundary(self):
        lines = wrap_title_for_svg('The Long Title', 10)
        assert len(lines) >= 2

    def test_single_long_word(self):
        lines = wrap_title_for_svg('Supercalifragilistic', 10)
        assert len(lines) == 1  # single word never split

    def test_empty_title(self):
        lines = wrap_title_for_svg('', 20)
        assert lines == ['']

    def test_multi_word_wrapping(self):
        lines = wrap_title_for_svg('One Two Three Four Five', 10)
        for line in lines:
            assert len(line) <= 11  # small tolerance for single word


class TestEscapeXml:
    """_escape_xml handles special characters."""

    def test_ampersand(self):
        assert _escape_xml('A & B') == 'A &amp; B'

    def test_less_than(self):
        assert _escape_xml('a < b') == 'a &lt; b'

    def test_greater_than(self):
        assert _escape_xml('a > b') == 'a &gt; b'

    def test_double_quote(self):
        assert _escape_xml('say "hi"') == 'say &quot;hi&quot;'

    def test_single_quote(self):
        assert _escape_xml("it's") == "it&apos;s"

    def test_plain_text_unchanged(self):
        assert _escape_xml('Hello World') == 'Hello World'

    def test_multiple_specials(self):
        assert _escape_xml('<a & b>') == '&lt;a &amp; b&gt;'
