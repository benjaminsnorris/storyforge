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


def test_load_annotations_csv_empty(tmp_path):
    """load_annotations_csv returns empty dict when file missing."""
    from storyforge.annotations import load_annotations_csv
    result = load_annotations_csv(str(tmp_path))
    assert result == {}


def test_load_annotations_csv_with_data(tmp_path):
    """load_annotations_csv returns dict keyed by annotation ID."""
    from storyforge.annotations import load_annotations_csv, ANNOTATIONS_HEADER
    csv_path = tmp_path / 'working' / 'annotations.csv'
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(
        '|'.join(ANNOTATIONS_HEADER) + '\n'
        'abc-123|arrival|1|pink|Needs Revision|the wagon lurched|pacing drags|Alice|2026-04-10|new|craft|2026-04-14\n'
    )
    result = load_annotations_csv(str(tmp_path))
    assert 'abc-123' in result
    assert result['abc-123']['scene_id'] == 'arrival'
    assert result['abc-123']['status'] == 'new'


def test_save_annotations_csv(tmp_path):
    """save_annotations_csv writes valid pipe-delimited CSV."""
    from storyforge.annotations import save_annotations_csv, load_annotations_csv
    rows = {
        'abc-123': {
            'id': 'abc-123', 'scene_id': 'arrival', 'chapter': '1',
            'color': 'pink', 'color_label': 'Needs Revision',
            'text': 'the wagon lurched', 'note': 'pacing drags',
            'reader': 'Alice', 'created_at': '2026-04-10',
            'status': 'new', 'fix_location': 'craft',
            'fetched_at': '2026-04-14',
        }
    }
    save_annotations_csv(str(tmp_path), rows)
    loaded = load_annotations_csv(str(tmp_path))
    assert 'abc-123' in loaded
    assert loaded['abc-123']['note'] == 'pacing drags'


def test_reconcile_new_annotation():
    """reconcile adds new annotations with status 'new'."""
    from storyforge.annotations import reconcile
    existing = {}
    api_annotations = [
        {
            'id': 'new-1',
            'scene': {'slug': 'arrival', 'scene_number': 1},
            'chapter': {'number': 1, 'title': 'Chapter 1'},
            'text': 'the dust rose',
            'note': 'too generic',
            'color': 'pink',
            'color_label': 'Needs Revision',
            'user': {'display_name': 'Alice'},
            'created_at': '2026-04-10T00:00:00Z',
        }
    ]
    result, summary = reconcile(existing, api_annotations)
    assert 'new-1' in result
    assert result['new-1']['status'] == 'new'
    assert result['new-1']['fix_location'] == 'craft'
    assert summary['new'] == 1


def test_reconcile_preserves_existing_status():
    """reconcile preserves status of already-tracked annotations."""
    from storyforge.annotations import reconcile
    existing = {
        'old-1': {
            'id': 'old-1', 'scene_id': 'arrival', 'chapter': '1',
            'color': 'pink', 'color_label': 'Needs Revision',
            'text': 'the dust rose', 'note': 'fixed this',
            'reader': 'Alice', 'created_at': '2026-04-10',
            'status': 'addressed', 'fix_location': 'craft',
            'fetched_at': '2026-04-13',
        }
    }
    api_annotations = [
        {
            'id': 'old-1',
            'scene': {'slug': 'arrival', 'scene_number': 1},
            'chapter': {'number': 1, 'title': 'Chapter 1'},
            'text': 'the dust rose',
            'note': 'fixed this',
            'color': 'pink',
            'color_label': 'Needs Revision',
            'user': {'display_name': 'Alice'},
            'created_at': '2026-04-10T00:00:00Z',
        }
    ]
    result, summary = reconcile(existing, api_annotations)
    assert result['old-1']['status'] == 'addressed'
    assert summary['new'] == 0
    assert summary['existing'] == 1


def test_reconcile_marks_removed():
    """reconcile marks annotations not in API as 'removed'."""
    from storyforge.annotations import reconcile
    existing = {
        'gone-1': {
            'id': 'gone-1', 'scene_id': 'arrival', 'chapter': '1',
            'color': 'pink', 'color_label': 'Needs Revision',
            'text': 'deleted text', 'note': '',
            'reader': 'Alice', 'created_at': '2026-04-10',
            'status': 'new', 'fix_location': 'craft',
            'fetched_at': '2026-04-13',
        }
    }
    api_annotations = []
    result, summary = reconcile(existing, api_annotations)
    assert result['gone-1']['status'] == 'removed'
    assert summary['removed'] == 1


def test_generate_revision_findings():
    """generate_revision_findings aggregates annotations per scene."""
    from storyforge.annotations import generate_revision_findings
    annotations = {
        'a1': {'id': 'a1', 'scene_id': 'arrival', 'color': 'pink',
               'color_label': 'Needs Revision', 'text': 'the wagon lurched',
               'note': 'pacing drags', 'status': 'new', 'fix_location': 'craft'},
        'a2': {'id': 'a2', 'scene_id': 'arrival', 'color': 'pink',
               'color_label': 'Needs Revision', 'text': 'she counted again',
               'note': 'repetitive', 'status': 'new', 'fix_location': 'craft'},
        'a3': {'id': 'a3', 'scene_id': 'field-book', 'color': 'orange',
               'color_label': 'Cut / Reconsider', 'text': 'long description',
               'note': '', 'status': 'new', 'fix_location': 'structural'},
        'a4': {'id': 'a4', 'scene_id': 'arrival', 'color': 'green',
               'color_label': 'Strong Passage', 'text': 'beautiful line',
               'note': 'love this', 'status': 'new', 'fix_location': 'protection'},
        'a5': {'id': 'a5', 'scene_id': 'arrival', 'color': 'pink',
               'color_label': 'Needs Revision', 'text': 'old fix',
               'note': 'done', 'status': 'addressed', 'fix_location': 'craft'},
    }
    craft, structural, protection = generate_revision_findings(annotations)

    # Craft findings: 2 pink for 'arrival' (a5 is addressed, excluded)
    assert len(craft) == 1  # one finding per scene
    assert craft[0]['scene_id'] == 'arrival'
    assert 'pacing drags' in craft[0]['guidance']
    assert 'repetitive' in craft[0]['guidance']

    # Structural: 1 orange for 'field-book'
    assert len(structural) == 1
    assert structural[0]['scene_id'] == 'field-book'

    # Protection: 1 green for 'arrival'
    assert len(protection) == 1
    assert protection[0]['scene_id'] == 'arrival'
    assert 'beautiful line' in protection[0]['text']


def test_generate_revision_findings_excludes_skipped():
    """Skipped and removed annotations are excluded from findings."""
    from storyforge.annotations import generate_revision_findings
    annotations = {
        'a1': {'id': 'a1', 'scene_id': 'arrival', 'color': 'pink',
               'text': 'text', 'note': '', 'status': 'skipped', 'fix_location': 'craft'},
        'a2': {'id': 'a2', 'scene_id': 'arrival', 'color': 'pink',
               'text': 'text', 'note': '', 'status': 'removed', 'fix_location': 'craft'},
    }
    craft, structural, protection = generate_revision_findings(annotations)
    assert craft == []
    assert structural == []
    assert protection == []


def test_promote_exemplars_full(tmp_path):
    """In full mode, exemplar candidates are added to exemplars.csv."""
    from storyforge.annotations import promote_exemplars
    os.makedirs(tmp_path / 'working', exist_ok=True)
    os.makedirs(tmp_path / 'scenes', exist_ok=True)
    (tmp_path / 'scenes' / 'arrival.md').write_text(
        'The wagon lurched forward. Beautiful prose here that readers loved.'
    )
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'color_label': 'Strong Passage',
               'text': 'Beautiful prose here that readers loved',
               'note': 'this is stunning', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars(str(tmp_path), annotations, coaching_level='full')
    assert len(promoted) == 1
    assert promoted[0] == 'g1'
    ex_path = tmp_path / 'working' / 'exemplars.csv'
    assert ex_path.exists()
    content = ex_path.read_text()
    assert 'arrival' in content
    assert 'reader-validated' in content


def test_promote_exemplars_coach(tmp_path):
    """In coach mode, exemplar candidates are written to coaching brief."""
    from storyforge.annotations import promote_exemplars
    os.makedirs(tmp_path / 'working' / 'coaching', exist_ok=True)
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'color_label': 'Strong Passage',
               'text': 'Beautiful prose',
               'note': 'love this', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars(str(tmp_path), annotations, coaching_level='coach')
    assert promoted == []
    brief_path = tmp_path / 'working' / 'coaching' / 'exemplar-candidates.md'
    assert brief_path.exists()
    content = brief_path.read_text()
    assert 'arrival' in content
    assert 'Beautiful prose' in content


def test_promote_exemplars_strict(tmp_path):
    """In strict mode, nothing is written — candidates are returned for display."""
    from storyforge.annotations import promote_exemplars
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'text': 'text', 'note': 'nice', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars(str(tmp_path), annotations, coaching_level='strict')
    assert promoted == []


def test_promote_exemplars_skips_no_note():
    """Green annotations without notes are not exemplar candidates."""
    from storyforge.annotations import promote_exemplars
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'text': 'text', 'note': '', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars('/tmp/fake', annotations, coaching_level='full')
    assert promoted == []


def test_save_sanitizes_pipes(tmp_path):
    """Pipe characters in text/note fields are replaced to prevent CSV corruption."""
    from storyforge.annotations import save_annotations_csv, load_annotations_csv
    annotations = {
        'p1': {'id': 'p1', 'scene_id': 'arrival', 'chapter': '1',
               'color': 'pink', 'color_label': 'Needs Revision',
               'text': 'she said "yes|no" loudly', 'note': 'pipes|in|notes',
               'reader': 'Alice', 'created_at': '2026-04-10',
               'status': 'new', 'fix_location': 'craft', 'fetched_at': '2026-04-14'},
    }
    save_annotations_csv(str(tmp_path), annotations)
    loaded = load_annotations_csv(str(tmp_path))
    assert 'p1' in loaded
    assert '|' not in loaded['p1']['text']
    assert '|' not in loaded['p1']['note']
    assert loaded['p1']['scene_id'] == 'arrival'


def test_load_annotation_findings_for_revise(tmp_path):
    """Annotations CSV with new entries produces revision findings."""
    from storyforge.annotations import (
        load_annotations_csv, save_annotations_csv, generate_revision_findings,
    )
    annotations = {
        'a1': {'id': 'a1', 'scene_id': 'arrival', 'chapter': '1',
               'color': 'pink', 'color_label': 'Needs Revision',
               'text': 'the wagon lurched', 'note': 'pacing issue',
               'reader': 'Alice', 'created_at': '2026-04-10',
               'status': 'new', 'fix_location': 'craft', 'fetched_at': '2026-04-14'},
    }
    save_annotations_csv(str(tmp_path), annotations)

    loaded = load_annotations_csv(str(tmp_path))
    craft, structural, protection = generate_revision_findings(loaded)
    assert len(craft) == 1
    assert craft[0]['scene_id'] == 'arrival'
