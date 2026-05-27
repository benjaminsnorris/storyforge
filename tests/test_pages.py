"""Tests for storyforge.pages — GN per-page file parsing and validation."""

import os
import pytest


def test_page_id_prefix_extracts_s_prefix():
    from storyforge.pages import page_id_prefix_for_scene
    assert page_id_prefix_for_scene('s01-studio-finalization') == 's01'
    assert page_id_prefix_for_scene('s10-arrival') == 's10'


def test_page_id_prefix_falls_back_to_full_id():
    from storyforge.pages import page_id_prefix_for_scene
    assert page_id_prefix_for_scene('the-blank-page') == 'the-blank-page'
    assert page_id_prefix_for_scene('cartographer-speaks') == 'cartographer-speaks'


def test_page_id_prefix_no_dash_after_s_prefix():
    from storyforge.pages import page_id_prefix_for_scene
    # 'salt-flats' — 's' followed by non-digit; not the sN- pattern
    assert page_id_prefix_for_scene('salt-flats') == 'salt-flats'


def test_page_filename_for_combines_prefix_and_number():
    from storyforge.pages import page_filename_for
    assert page_filename_for('s01-studio-finalization', 1) == 's01-p1.md'
    assert page_filename_for('s01-studio-finalization', 12) == 's01-p12.md'
    assert page_filename_for('the-blank-page', 1) == 'the-blank-page-p1.md'
