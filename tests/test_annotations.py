"""Tests for annotation build integration (migrated from test-annotations.sh).

The bash tests tested shell functions for HTML injection and scene wrapping.
These are bash-specific operations — we test the Python assembly module equivalents.
"""

import pytest


@pytest.mark.skip(reason="Annotation injection is bash-only (sed/awk). No Python equivalent.")
def test_annotations_placeholder():
    pass
