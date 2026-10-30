"""F-130: reference docs still identical to their template never reach a prompt.

Extraction doesn't write the prose reference docs, so on an extracted book
character-bible.md, world-bible.md, voice-guide.md and story-architecture.md
stay the template init copied in. The scorer used to send that template text
as if it were the book's own bible.
"""

import os
import shutil

from storyforge.common import (
    _shared_context_cache, build_shared_context, get_plugin_dir,
    is_unfilled_template,
)
from storyforge.cmd_score import _read_reference
from storyforge.scoring_bible import _load_bibles

DOCS = ('character-bible.md', 'world-bible.md', 'voice-guide.md',
        'story-architecture.md')


def _project(tmp_path, filled=()):
    """A project whose reference docs are the templates, except `filled`."""
    ref = tmp_path / 'reference'
    ref.mkdir()
    templates = os.path.join(get_plugin_dir(), 'templates', 'reference')
    for name in DOCS:
        if name in filled:
            (ref / name).write_text(f'# {name}\n\nThe real thing for this book.\n')
        else:
            shutil.copy(os.path.join(templates, name), ref / name)
    return str(tmp_path)


def test_template_copy_is_unfilled(tmp_path):
    project = _project(tmp_path)
    for name in DOCS:
        assert is_unfilled_template(os.path.join(project, 'reference', name))


def test_whitespace_difference_still_unfilled(tmp_path):
    project = _project(tmp_path)
    path = os.path.join(project, 'reference', 'voice-guide.md')
    with open(path, 'a') as f:
        f.write('\n\n')
    assert is_unfilled_template(path)


def test_edited_or_unknown_file_is_not_unfilled(tmp_path):
    project = _project(tmp_path, filled=('character-bible.md',))
    assert not is_unfilled_template(os.path.join(project, 'reference', 'character-bible.md'))
    other = tmp_path / 'reference' / 'notes.md'
    other.write_text('no template for this one')
    assert not is_unfilled_template(str(other))
    assert not is_unfilled_template(str(tmp_path / 'reference' / 'missing.md'))


def test_score_read_reference_skips_template(tmp_path):
    project = _project(tmp_path, filled=('story-architecture.md',))
    assert _read_reference(project, ['reference/character-bible.md']) == ''
    assert 'The real thing' in _read_reference(project, ['reference/story-architecture.md'])


def test_bible_check_skips_template(tmp_path):
    project = _project(tmp_path, filled=('world-bible.md',))
    assert list(_load_bibles(project)) == ['world-bible.md']


def test_shared_context_skips_template(tmp_path):
    project = _project(tmp_path, filled=('voice-guide.md',))
    _shared_context_cache.clear()
    try:
        text = '\n'.join(b['text'] for b in build_shared_context(project))
    finally:
        _shared_context_cache.clear()
    assert '=== Voice Guide ===' in text
    assert '=== Character Bible ===' not in text
    assert '=== World Bible ===' not in text
