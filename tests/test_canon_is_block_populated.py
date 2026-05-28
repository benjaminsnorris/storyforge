"""Tests for canon.is_canon_block_populated — the precondition helper
used by elaborate --stage page-architecture."""

import textwrap


def _write_canon(project_dir, canon_id, body):
    import os
    canon_dir = os.path.join(str(project_dir), 'reference', 'canon')
    os.makedirs(canon_dir, exist_ok=True)
    path = os.path.join(canon_dir, f'{canon_id}.md')
    with open(path, 'w') as f:
        f.write(body)
    return path


def test_populated_block_returns_true(tmp_path):
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Embeddable block

        Dominant panel: the page's emotional fulcrum.
        Transitional panel: a rhythmic beat between dominants.
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is True


def test_unpopulated_block_returns_false(tmp_path):
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Embeddable block

        TODO — fill in the panel-register vocabulary.
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is False


def test_missing_canon_file_returns_false(tmp_path):
    from storyforge.canon import is_canon_block_populated
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is False


def test_missing_embeddable_block_returns_false(tmp_path):
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Clauses

        - dominant
        - transitional
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is False
