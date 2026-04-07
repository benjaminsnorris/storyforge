"""Tests for coaching level system (migrated from test-coaching.sh).

The coaching tests rely on bash functions (get_coaching_level) and shell script
dry-run modes. We test what is available in Python.
"""

import pytest


@pytest.mark.skip(reason="Coaching level tests are bash-only (get_coaching_level, --dry-run shell scripts). No Python equivalent.")
def test_coaching_placeholder():
    pass
