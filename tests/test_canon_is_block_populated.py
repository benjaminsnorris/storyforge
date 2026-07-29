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


def test_empty_embeddable_block_returns_true(tmp_path):
    """A present-but-empty '## Embeddable block' (header exists, no body
    text follows) is deliberately treated as populated, NOT placeholder —
    see is_canon_block_populated's docstring. This is distinct from
    missing-file and missing-section, which do return False, and from a
    TODO-stub body, which _section_body_is_placeholder catches. Task 7
    (.superpowers/sdd/2026-07-28-illustration-canon-adoption/) widened
    _section_body_is_placeholder for other placeholder shapes but was
    explicitly told to leave this empty-body behavior alone, because
    elaborate --stage page-architecture gates on it. Pinning it here
    guards against a future widening silently breaking that gate.
    """
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Embeddable block

        ## Clauses
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is True


def test_emphasized_first_line_with_prose_under_it_is_populated(tmp_path):
    """Regression for the branch's CRITICAL: a register vocabulary whose
    first line is a bold summary (`**Dominant / transitional / rhythmic.**`)
    read as a TODO scaffold once placeholder detection decided on the first
    non-blank line, and `elaborate --stage page-architecture` refused to run
    on a live book. The emphasis rule is a whole-body test again."""
    from storyforge.canon import is_canon_block_populated
    body = textwrap.dedent("""\
        ---
        canon_id: panel-registers
        canon_type: vocabulary
        ---

        ## Embeddable block

        **Dominant / transitional / rhythmic.**

        Dominant panels carry the page's emotional fulcrum. Transitional
        panels move the eye. Rhythmic panels hold the beat.
        """)
    _write_canon(tmp_path, 'panel-registers', body)
    assert is_canon_block_populated(str(tmp_path), 'panel-registers') is True


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
