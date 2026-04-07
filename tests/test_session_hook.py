"""Tests for session-end hook (migrated from test-session-hook.sh).

The session hook tests rely on running a bash hook script with JSON input.
These are bash-specific operations.
"""

import pytest


@pytest.mark.skip(reason="Session hook tests are bash-only (hooks/session-end shell script). No Python equivalent.")
def test_session_hook_placeholder():
    pass
