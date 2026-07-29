"""Tests for `storyforge illustrate --package` — the handoff packet (#278 ph3).

The packet is assembly: it must make no API call, produce identical bytes on a
re-run over unchanged sources, carry every continuity anchor byte-identically,
and state its own gaps rather than reading as coverage it does not have.

`in_project` seeds canon files, a plan, and state transitions into a copy of the
fixture — the shared fixture has none of those (checked, not assumed).
"""

import os

import pytest

from storyforge import canon, cmd_illustrate, packet
from storyforge import illustrations as ill
from storyforge import prompts_packet as pp
from illustration_helpers import seed_packet_project


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


@pytest.fixture
def in_project(project_dir, monkeypatch):
    seed_packet_project(project_dir)
    monkeypatch.chdir(project_dir)
    return project_dir


def _read(project_dir, name):
    with open(packet.packet_file(project_dir, name), encoding='utf-8') as f:
        return f.read()


def _read_all(project_dir):
    return {name: _read(project_dir, name) for name in packet.PACKET_FILES}


# ============================================================================
# The six files
# ============================================================================

def test_package_writes_all_six_files(in_project):
    assert cmd_illustrate.main(['--package']) == 0
    for name in ('README.md', 'canon.md', 'visual-state.md',
                 'illustrations.md', 'reference-images.md', 'acceptance.md'):
        assert os.path.isfile(os.path.join(in_project, packet.PACKET_DIR, name))


def test_package_makes_no_api_call(in_project, monkeypatch):
    """Set the key so the missing-key guard cannot make this pass vacuously."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('--package is assembly, not generation')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    assert cmd_illustrate.main(['--package']) == 0


def test_dry_run_writes_nothing(in_project, capsys):
    assert cmd_illustrate.main(['--package', '--dry-run']) == 0
    assert not os.path.isdir(packet.packet_dir(in_project))
    out = capsys.readouterr().out
    assert 'illustrations.md' in out


def test_regeneration_is_idempotent(in_project):
    cmd_illustrate.main(['--package'])
    first = _read_all(in_project)
    cmd_illustrate.main(['--package'])
    assert _read_all(in_project) == first


def test_a_regenerated_packet_is_not_stale_or_drifted(in_project):
    cmd_illustrate.main(['--package'])
    assert packet.packet_stale(in_project) == []
    assert packet.anchor_copy_drift(in_project) == []


# ============================================================================
# The byte-identity invariant, on the rendering path
# ============================================================================

def test_anchors_in_the_written_packet_are_byte_identical(in_project):
    """Distinct from the `resolve`-level check in test_packet.py: this is the
    only one that would catch a renderer wrapping or re-indenting an anchor."""
    cmd_illustrate.main(['--package'])
    written = _read(in_project, 'canon.md')
    src = canon.anchor_texts(in_project)
    assert src
    for text in src.values():
        assert text in written, 'anchor text was altered on the way in'


def test_a_long_anchor_is_not_rewrapped(in_project):
    """The failure mode the file-level check exists for: a renderer that tidies
    a long line. Byte comparison catches it; a keyword check would not."""
    from illustration_helpers import write_canon_file
    long_anchor = (
        'Kael Maren: sixty-two, stooped from four decades of archive work, a '
        'grey wool coat worn shiny at the elbows, half-moon spectacles pushed '
        'up on his forehead, and ink under every fingernail of his left hand.')
    write_canon_file(in_project, canon_id='kael-maren',
                     canon_type='character', body=long_anchor,
                     subdir='characters')
    cmd_illustrate.main(['--package'])
    assert long_anchor in _read(in_project, 'canon.md')


def test_the_packet_names_its_anchors_by_display_name(in_project):
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'canon.md')
    assert '### Dorren Hayle' in body
    assert '<!-- canon-embed: dorren-hayle -->' in body


# ============================================================================
# Coverage honesty
# ============================================================================

def test_the_packet_states_its_own_gaps(in_project):
    """A thin entry is named IN the packet, not in a log line."""
    rows = ill.read_plan(in_project)
    rows[0]['beat'] = ''
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert rows[0]['id'] in _read(in_project, 'README.md')


def test_a_thin_entry_reads_as_thin(in_project):
    rows = ill.read_plan(in_project)
    rows[0]['beat'] = ''
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert packet.NOT_RECORDED in _read(in_project, 'illustrations.md')


def test_gaps_are_logged_loudly_as_well(in_project, capsys):
    cmd_illustrate.main(['--package'])
    out = capsys.readouterr().out
    # The fixture has never had an audit run, which is one of the gaps.
    assert 'WARNING' in out
    assert 'audit' in out


def test_a_never_run_audit_is_named_in_the_readme(in_project):
    cmd_illustrate.main(['--package'])
    assert 'never been run' in _read(in_project, 'README.md')


def test_a_missing_book_level_section_says_so_in_canon_md(in_project):
    os.remove(canon.resolve_canon_path(in_project, 'visual-vocabulary'))
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'canon.md')
    assert 'Visual vocabulary' in body
    assert pp._MISSING in body


def test_an_untracked_book_says_so_rather_than_rendering_an_empty_table(
        in_project):
    from storyforge import visual_state as vs
    vs.write_transitions(in_project, [])
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'visual-state.md')
    assert pp._NONE_TRACKED in body
    assert '--state' in body


def test_unpositioned_scenes_are_named_in_the_state_view(in_project):
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'visual-state.md')
    assert 'chapter-map.csv' in body
    assert 'new-x1' in body


# ============================================================================
# What lives where
# ============================================================================

def test_the_set_wide_checks_live_in_acceptance_not_in_the_entries(in_project):
    cmd_illustrate.main(['--package'])
    acceptance = _read(in_project, 'acceptance.md')
    entries = _read(in_project, 'illustrations.md')
    assert 'PORTRAIT orientation' in acceptance
    assert 'no text, no letters' in acceptance.lower()
    assert 'orientation' not in entries.lower()
    assert 'no letters' not in entries.lower()


def test_the_entries_do_not_restate_the_reference_tier(in_project):
    """A per-illustration entry that carried the anchors and the house style
    would not be a thin entry."""
    cmd_illustrate.main(['--package'])
    entries = _read(in_project, 'illustrations.md')
    for text in canon.anchor_texts(in_project).values():
        assert text not in entries
    assert 'Camera at standing eye height' not in entries


def test_entries_stay_within_the_word_budget(in_project):
    """80–120 words is the point of the packet: the shared sections carry the
    rest. This guards the renderer's own overhead, on plan cells that are
    already short."""
    cmd_illustrate.main(['--package'])
    for entry in packet.resolve(in_project)['entries']:
        assert len(pp.render_entry(entry).split()) <= 120


def test_state_appears_in_the_entry_because_it_resolves_the_matrix(in_project):
    cmd_illustrate.main(['--package'])
    entries = _read(in_project, 'illustrations.md')
    assert '**State.**' in entries
    assert 'Dorren Hayle: black waistcoat' in entries


def test_reference_images_are_pathed_not_copied(in_project):
    from illustration_helpers import make_png
    cover = os.path.join('manuscript', 'assets', 'cover-illustration.png')
    make_png(os.path.join(in_project, cover), 8, 12)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'reference-images.md')
    assert cover in body
    # Nothing was copied in beside the markdown.
    assert sorted(os.listdir(packet.packet_dir(in_project))) == \
        sorted(packet.PACKET_FILES)


def test_the_sequence_rules_are_in_the_packet(in_project):
    """Source-report item 2: independent calls converge on the same staging."""
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'acceptance.md')
    assert 'adjacent' in body
    assert 'camera distance' in body


# ============================================================================
# The renderers, driven directly
# ============================================================================

def test_a_clean_readme_claims_only_what_it_can(in_project):
    """With no gaps the README must still not promise the art will be right."""
    contents = packet.resolve(in_project)
    contents['gaps'] = []
    body = pp.render_readme(title='T', contents=contents, entry_count=2)
    assert 'Nothing was missing' in body
    assert 'not a promise that' in body


def test_canon_md_keeps_an_author_added_section(in_project):
    body = pp.render_canon(
        book_level={'Visual foundation': 'A', 'House rules': 'B'},
        anchors={}, labels={})
    assert '## House rules' in body


def test_canon_md_says_so_when_no_anchor_is_populated(in_project):
    body = pp.render_canon(book_level={}, anchors={}, labels={})
    assert body.count(pp._MISSING) == 4  # three book-level, plus the anchors


def test_illustrations_md_says_so_when_nothing_is_planned():
    assert 'No illustrations are planned' in pp.render_illustrations(entries=[])


# ============================================================================
# Dispatch
# ============================================================================

def test_package_is_listed_when_no_phase_is_given(in_project, capsys):
    assert cmd_illustrate.main([]) == 1
    assert '--package' in capsys.readouterr().out


def test_package_is_refused_for_graphic_novel_projects(project_dir_gn,
                                                       monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    assert cmd_illustrate.main(['--package']) == 1
    assert not os.path.isdir(packet.packet_dir(project_dir_gn))
