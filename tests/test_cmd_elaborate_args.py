"""Tests for cmd_elaborate argument parsing — covers the page-architecture
stage addition and its --page / --scene / --force flags."""

import pytest


def test_page_architecture_stage_recognized():
    from storyforge.cmd_elaborate import parse_args, VALID_STAGES
    assert 'page-architecture' in VALID_STAGES
    args = parse_args(['--stage', 'page-architecture'])
    assert args.stage == 'page-architecture'


def test_page_architecture_direct_flag():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--page-architecture'])
    assert args.stage == 'page-architecture'


def test_page_flag_passed_through():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--stage', 'page-architecture', '--page', 's01-p1'])
    assert args.page == 's01-p1'


def test_scene_flag_passed_through():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--stage', 'page-architecture', '--scene', 's01-studio'])
    assert args.scene == 's01-studio'


def test_force_flag_passed_through():
    from storyforge.cmd_elaborate import parse_args
    args = parse_args(['--stage', 'page-architecture', '--force'])
    assert args.force is True


def test_page_and_scene_mutually_exclusive():
    from storyforge.cmd_elaborate import parse_args
    with pytest.raises(SystemExit):
        parse_args(['--stage', 'page-architecture',
                    '--page', 's01-p1', '--scene', 's01-studio'])
