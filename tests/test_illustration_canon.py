"""Tests for canon validation running on novel (prose) projects, not just
graphic-novel ones. See .superpowers/sdd/2026-07-28-illustration-canon-adoption/
task-1-brief.md."""

import os

from storyforge.cmd_cleanup import report_canon_files

CANON_BODY = """---
canon_id: nora
canon_type: character
canon_updated: 2026-07-28
appears_in: village-reveal
embeds_as: Character
first_appearance: village-reveal
---

## Embeddable block

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.

## Clauses

- Always barefoot indoors.

## Related canon

- leo

## Iteration history

- 2026-07-28 initial
"""


def _write_canon(project_dir, relpath, body=CANON_BODY):
    path = os.path.join(project_dir, 'reference', 'canon', relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


def _set_medium(project_dir, medium):
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path, encoding='utf-8') as f:
        text = f.read()
    if 'medium:' in text:
        lines = [
            f'  medium: {medium}' if line.strip().startswith('medium:') else line
            for line in text.splitlines()
        ]
        text = '\n'.join(lines) + '\n'
    else:
        text = text.replace('project:', f'project:\n  medium: {medium}', 1)
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_novel_project_canon_is_validated_not_skipped(project_dir):
    """A novel project with valid canon produces no findings at all."""
    _set_medium(project_dir, 'novel')
    # characters.csv must carry a matching row or canon_missing_registry_entry fires
    reg = os.path.join(project_dir, 'reference', 'characters.csv')
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    with open(reg, 'w', encoding='utf-8') as f:
        f.write('id|name\nnora|Nora\n')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    findings = report_canon_files(project_dir)

    assert findings == [], f'expected no findings, got {findings}'


def test_novel_project_canon_errors_are_reported(project_dir):
    """A novel project with a broken canon file gets the real finding,
    not a blanket skip warning."""
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                 body='no frontmatter here\n')

    kinds = {f['type'] for f in report_canon_files(project_dir)}

    assert 'canon_present_in_novel_project' not in kinds
    assert 'canon_missing_frontmatter' in kinds


CANON_NO_EMBEDS_AS = """---
canon_id: nora
canon_type: character
canon_updated: 2026-07-28
appears_in: village-reveal
first_appearance: village-reveal
---

## Embeddable block

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.

## Clauses

- Always barefoot indoors.

## Related canon

- leo

## Iteration history

- 2026-07-28 initial
"""


def test_embeds_as_not_required_for_novel(project_dir):
    from storyforge.canon import validate_canon_file
    _set_medium(project_dir, 'novel')
    path = _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                        body=CANON_NO_EMBEDS_AS)

    findings = validate_canon_file(path, project_dir)
    missing = [f for f in findings if f['type'] == 'canon_missing_key']

    assert missing == [], f'embeds_as should be optional for novel: {missing}'


def test_embeds_as_still_required_for_graphic_novel(project_dir):
    from storyforge.canon import validate_canon_file
    _set_medium(project_dir, 'graphic-novel')
    path = _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                        body=CANON_NO_EMBEDS_AS)

    findings = validate_canon_file(path, project_dir)
    details = [f['detail'] for f in findings if f['type'] == 'canon_missing_key']

    assert any('embeds_as' in d for d in details), \
        f'embeds_as must stay required for GN: {findings}'


def test_anchor_texts_returns_entity_anchors_verbatim(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    anchors = anchor_texts(project_dir)

    assert set(anchors) == {'nora'}
    assert anchors['nora'] == (
        'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
        'grey-green eyes.'
    )


def test_anchor_texts_omits_placeholder_blocks(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'ghost.md'),
                 body=CANON_BODY.replace(
                     'Nora, 9 years old, 132 cm, dark brown hair in a short '
                     'bob, grey-green eyes.',
                     'TODO: describe this character',
                 ).replace('canon_id: nora', 'canon_id: ghost'))

    assert 'ghost' not in anchor_texts(project_dir)


def test_anchor_texts_excludes_non_entity_types(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))

    assert anchor_texts(project_dir) == {}


def test_resolve_canon_path_finds_root_and_subdir(project_dir):
    from storyforge.canon import resolve_canon_path
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))

    assert resolve_canon_path(project_dir, 'nora').endswith(
        os.path.join('characters', 'nora.md'))
    assert resolve_canon_path(project_dir, 'visual-foundation').endswith(
        'visual-foundation.md')
    assert resolve_canon_path(project_dir, 'nobody') is None
