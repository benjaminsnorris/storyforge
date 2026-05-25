"""Tests for the story-summary.md parser in common.py.

Spec: docs/superpowers/specs/2026-05-24-elaboration-levels-design.md
"""

import os

from storyforge.common import parse_story_summary


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def test_returns_none_when_file_missing(tmp_path):
    assert parse_story_summary(str(tmp_path)) is None


def test_parses_all_four_sections(tmp_path):
    _write(str(tmp_path / 'reference' / 'story-summary.md'), '''\
---
logline_updated: 2026-05-01
synopsis_updated: 2026-05-02
act_shape_updated: 2026-05-03
theme_updated: 2026-05-04
---

# Story summary

## Logline

A cartographer who maps the unmappable loses his daughter to a country no map contains.

## Synopsis

Lucien Vey, master cartographer of the Imperial Archives, builds his
reputation by drawing maps of places no one else can find. When his
daughter Mira vanishes into a country whose existence he himself
documented, he must navigate between two truths to bring her back.

## Act-shape

### Act 1
Lucien's competence is the world. His daughter disappears.

### Act 2
The maps lie. Lucien learns to read between his own lines.

### Act 3
He chooses Mira over the empire.

## Theme

What does it mean to recover what was never recorded? The story argues
that some absences leave a shape, and that the shape is the map.
''')

    result = parse_story_summary(str(tmp_path))
    assert result is not None
    assert result['frontmatter']['logline_updated'] == '2026-05-01'
    assert result['frontmatter']['synopsis_updated'] == '2026-05-02'
    assert result['frontmatter']['act_shape_updated'] == '2026-05-03'
    assert result['frontmatter']['theme_updated'] == '2026-05-04'
    assert 'A cartographer who maps the unmappable' in result['logline']
    assert 'Lucien Vey, master cartographer' in result['synopsis']
    assert '### Act 1' in result['act_shape']
    assert '### Act 3' in result['act_shape']
    assert 'shape is the map' in result['theme']


def test_missing_sections_return_empty(tmp_path):
    _write(str(tmp_path / 'reference' / 'story-summary.md'), '''\
---
logline_updated: 2026-05-01
---

# Story summary

## Logline

Just the logline.
''')
    result = parse_story_summary(str(tmp_path))
    assert result['logline'] == 'Just the logline.'
    assert result['synopsis'] == ''
    assert result['act_shape'] == ''
    assert result['theme'] == ''
    assert result['frontmatter']['logline_updated'] == '2026-05-01'
    assert result['frontmatter']['synopsis_updated'] == ''


def test_strips_leading_html_comment(tmp_path):
    """The template starts with an HTML comment explaining what the file is.
    That comment must not appear as part of any section body."""
    _write(str(tmp_path / 'reference' / 'story-summary.md'), '''\
<!--
This is a template comment that should be stripped.
-->
---
logline_updated: 2026-05-01
---

# Story summary

## Logline

Real content.
''')
    result = parse_story_summary(str(tmp_path))
    assert result['logline'] == 'Real content.'
    assert 'template comment' not in (result['logline'] + result['synopsis'])


def test_handles_no_frontmatter(tmp_path):
    """Frontmatter is optional. Without it, all timestamps return ''."""
    _write(str(tmp_path / 'reference' / 'story-summary.md'), '''\
# Story summary

## Logline

No-frontmatter content.

## Synopsis

Whatever.
''')
    result = parse_story_summary(str(tmp_path))
    assert result['logline'] == 'No-frontmatter content.'
    assert result['synopsis'] == 'Whatever.'
    assert all(v == '' for v in result['frontmatter'].values())


def test_act_shape_includes_sub_headings(tmp_path):
    """The Act-shape section's `### Act N` sub-headings stay in the body."""
    _write(str(tmp_path / 'reference' / 'story-summary.md'), '''\
# Story summary

## Act-shape

### Act 1
First act.

### Act 2
Second act.

### Act 3
Third act.
''')
    result = parse_story_summary(str(tmp_path))
    assert '### Act 1' in result['act_shape']
    assert '### Act 2' in result['act_shape']
    assert 'First act.' in result['act_shape']
    assert 'Third act.' in result['act_shape']


def test_unknown_sections_are_ignored(tmp_path):
    """A section that isn't one of the four known names is dropped silently."""
    _write(str(tmp_path / 'reference' / 'story-summary.md'), '''\
# Story summary

## Logline
A logline.

## Notes for myself
This shouldn't make it into any section field.

## Theme
The theme.
''')
    result = parse_story_summary(str(tmp_path))
    assert result['logline'] == 'A logline.'
    assert result['theme'] == 'The theme.'
    assert 'Notes for myself' not in result['logline']
    assert 'Notes for myself' not in result['theme']
