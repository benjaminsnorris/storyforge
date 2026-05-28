"""Tests for canon.get_canon_embeddable_block — the public helper added
to replace cmd_elaborate's private import of _embeddable_block_text (CR-3)."""

import textwrap


def _write_canon(project_dir, canon_id, body):
    import os
    canon_dir = os.path.join(str(project_dir), 'reference', 'canon')
    os.makedirs(canon_dir, exist_ok=True)
    path = os.path.join(canon_dir, f'{canon_id}.md')
    with open(path, 'w') as f:
        f.write(body)
    return path


def test_returns_embeddable_block_text(tmp_path):
    from storyforge.canon import get_canon_embeddable_block
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        ---

        ## Embeddable block

        Dominant: emotional fulcrum.
        Transitional: rhythmic bridge.

        ## Clauses

        Other content here.
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    result = get_canon_embeddable_block(str(tmp_path), 'panel-registers')
    assert 'Dominant: emotional fulcrum' in result
    assert 'Transitional: rhythmic bridge' in result
    # Content from other sections is NOT included
    assert 'Other content here' not in result


def test_returns_empty_for_missing_file(tmp_path):
    from storyforge.canon import get_canon_embeddable_block
    result = get_canon_embeddable_block(str(tmp_path), 'panel-registers')
    assert result == ''


def test_returns_empty_for_missing_embeddable_section(tmp_path):
    from storyforge.canon import get_canon_embeddable_block
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        ---

        ## Clauses

        - dominant
        - transitional
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert get_canon_embeddable_block(str(tmp_path), 'panel-registers') == ''


def test_strips_whitespace(tmp_path):
    """The returned text should be stripped (no leading/trailing whitespace)."""
    from storyforge.canon import get_canon_embeddable_block
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        ---

        ## Embeddable block


            content with leading whitespace


        """)
    _write_canon(tmp_path, 'panel-registers', body)
    result = get_canon_embeddable_block(str(tmp_path), 'panel-registers')
    assert result.startswith('content with leading whitespace') or result.startswith('    content')
    assert not result.endswith('\n\n')
