# tests/test_reader_annotations.py
import os


def test_color_labels():
    """COLOR_LABELS maps all five colors to labels."""
    from storyforge.annotations import COLOR_LABELS
    assert COLOR_LABELS['pink'] == 'Needs Revision'
    assert COLOR_LABELS['orange'] == 'Cut / Reconsider'
    assert COLOR_LABELS['blue'] == 'Research Needed'
    assert COLOR_LABELS['green'] == 'Strong Passage'
    assert COLOR_LABELS['yellow'] == 'Important'


def test_color_to_fix_location():
    """COLOR_TO_FIX_LOCATION maps colors to revision intent."""
    from storyforge.annotations import COLOR_TO_FIX_LOCATION
    assert COLOR_TO_FIX_LOCATION['pink'] == 'craft'
    assert COLOR_TO_FIX_LOCATION['orange'] == 'structural'
    assert COLOR_TO_FIX_LOCATION['blue'] == 'research'
    assert COLOR_TO_FIX_LOCATION['green'] == 'protection'
    assert COLOR_TO_FIX_LOCATION['yellow'] == 'craft'


def test_route_annotation_pink():
    """Pink annotation routes to craft with status new."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'pink', 'note': 'pacing drags here'}
    status, fix_loc = route_annotation(ann)
    assert status == 'new'
    assert fix_loc == 'craft'


def test_route_annotation_green():
    """Green annotation routes to protection."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'green', 'note': 'beautiful passage'}
    status, fix_loc = route_annotation(ann)
    assert status == 'new'
    assert fix_loc == 'protection'


def test_route_annotation_yellow_no_note():
    """Yellow annotation without note is skipped."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'yellow', 'note': ''}
    status, fix_loc = route_annotation(ann)
    assert status == 'skipped'
    assert fix_loc == 'craft'


def test_route_annotation_yellow_with_note():
    """Yellow annotation with note routes to craft."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'yellow', 'note': 'interesting choice here'}
    status, fix_loc = route_annotation(ann)
    assert status == 'new'
    assert fix_loc == 'craft'
