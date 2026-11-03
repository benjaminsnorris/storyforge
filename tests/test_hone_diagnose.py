"""`hone --diagnose` is read-only and calls no model, so it must run on a
machine with no API key. It chose a model first, which lists the API's
models, and crashed with 'ANTHROPIC_API_KEY not set' (found preparing the
books for their rewrite, 2026-11-02)."""

import pytest

from storyforge import cmd_hone


def test_diagnose_needs_no_api_key(project_dir, monkeypatch, capsys):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_MODEL', raising=False)
    # the suite stubs the model catalog; a real machine without a key has none
    monkeypatch.setattr('storyforge.common._catalog', None)
    monkeypatch.setattr(cmd_hone, 'detect_project_root', lambda: project_dir)

    def no_api(*a, **k):
        raise AssertionError('diagnose reached the API')
    monkeypatch.setattr('storyforge.api._api_request', no_api)
    cmd_hone.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Diagnose complete (read-only, no files changed)' in out
    assert 'Model:' not in out


def test_a_dry_run_without_a_key_stops_with_what_to_set(project_dir, monkeypatch, capsys):
    """A dry run names its model, so it needs a key or STORYFORGE_MODEL; it
    said so with a traceback."""
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_MODEL', raising=False)
    # strict coaching calls no model; another test's coaching mustn't leak in
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
    monkeypatch.setattr('storyforge.common._catalog', None)
    monkeypatch.setattr(cmd_hone, 'detect_project_root', lambda: project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_hone.main(['--dry-run'])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert 'hone could not choose a model' in out and 'STORYFORGE_MODEL' in out


def test_a_dry_run_with_a_named_model_needs_no_key(project_dir, monkeypatch, capsys):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setenv('STORYFORGE_MODEL', 'claude-opus-5-5')
    monkeypatch.setattr(cmd_hone, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.api._api_request',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('API')))
    cmd_hone.main(['--dry-run', '--domain', 'outcomes'])
    assert 'Model: claude-opus-5-5' in capsys.readouterr().out


@pytest.mark.parametrize('argv', [['--domain', 'outcomes'], ['--coaching', 'strict', '--dry-run']])
def test_a_run_that_calls_no_model_needs_no_key(project_dir, monkeypatch, capsys, argv):
    """Outcomes alone and strict coaching call no model (the key check
    always exempted them); choosing one crashed them without a key."""
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_MODEL', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)
    monkeypatch.setattr('storyforge.common._catalog', None)
    monkeypatch.setattr(cmd_hone, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr(cmd_hone, 'ensure_on_branch', lambda *a, **k: None)
    # no key: any API request raises, as on a machine without one
    try:
        cmd_hone.main(argv + (['--dry-run'] if '--dry-run' not in argv else []))
    finally:
        import os
        os.environ.pop('STORYFORGE_COACHING', None)
    assert 'Model: none (this run calls no model)' in capsys.readouterr().out
