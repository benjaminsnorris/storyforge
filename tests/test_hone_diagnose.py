"""`hone --diagnose` is read-only and calls no model, so it must run on a
machine with no API key. It chose a model first, which lists the API's
models, and crashed with 'ANTHROPIC_API_KEY not set' (found preparing the
books for their rewrite, 2026-11-02)."""

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
