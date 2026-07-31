"""Tests for canon validation running on novel (prose) projects, not just
graphic-novel ones. See .superpowers/sdd/2026-07-28-illustration-canon-adoption/
task-1-brief.md."""

import os

import pytest

from storyforge import canon
from storyforge.cmd_cleanup import report_canon_files

CANON_BODY = """---
canon_id: nora
canon_type: character
canon_updated: 2026-07-28
appears_in: village-reveal
embeds_as: Character
first_appearance: village-reveal
---

## Embeddable block

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.

## Clauses

- Always barefoot indoors.

## Related canon

- leo

## Iteration history

- 2026-07-28 initial
"""


def _write_canon(project_dir, relpath, body=CANON_BODY):
    path = os.path.join(project_dir, 'reference', 'canon', relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


def _set_medium(project_dir, medium):
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path, encoding='utf-8') as f:
        text = f.read()
    if 'medium:' in text:
        lines = [
            f'  medium: {medium}' if line.strip().startswith('medium:') else line
            for line in text.splitlines()
        ]
        text = '\n'.join(lines) + '\n'
    else:
        text = text.replace('project:', f'project:\n  medium: {medium}', 1)
    with open(yaml_path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_novel_project_canon_is_validated_not_skipped(project_dir):
    """A novel project with valid canon produces no findings at all."""
    _set_medium(project_dir, 'novel')
    # characters.csv must carry a matching row or canon_missing_registry_entry fires
    reg = os.path.join(project_dir, 'reference', 'characters.csv')
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    with open(reg, 'w', encoding='utf-8') as f:
        f.write('id|name\nnora|Nora\n')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    findings = report_canon_files(project_dir)

    assert findings == [], f'expected no findings, got {findings}'


def test_novel_project_canon_errors_are_reported(project_dir):
    """A novel project with a broken canon file gets the real finding,
    not a blanket skip warning."""
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                 body='no frontmatter here\n')

    kinds = {f['type'] for f in report_canon_files(project_dir)}

    assert 'canon_present_in_novel_project' not in kinds
    assert 'canon_missing_frontmatter' in kinds


CANON_NO_EMBEDS_AS = """---
canon_id: nora
canon_type: character
canon_updated: 2026-07-28
appears_in: village-reveal
first_appearance: village-reveal
---

## Embeddable block

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.

## Clauses

- Always barefoot indoors.

## Related canon

- leo

## Iteration history

- 2026-07-28 initial
"""


def test_embeds_as_not_required_for_novel(project_dir):
    from storyforge.canon import validate_canon_file
    _set_medium(project_dir, 'novel')
    path = _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                        body=CANON_NO_EMBEDS_AS)

    findings = validate_canon_file(path, project_dir)
    missing = [f for f in findings if f['type'] == 'canon_missing_key']

    assert missing == [], f'embeds_as should be optional for novel: {missing}'


def test_embeds_as_still_required_for_graphic_novel(project_dir):
    from storyforge.canon import validate_canon_file
    _set_medium(project_dir, 'graphic-novel')
    path = _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                        body=CANON_NO_EMBEDS_AS)

    findings = validate_canon_file(path, project_dir)
    details = [f['detail'] for f in findings if f['type'] == 'canon_missing_key']

    assert any('embeds_as' in d for d in details), \
        f'embeds_as must stay required for GN: {findings}'


def test_anchor_texts_returns_entity_anchors_verbatim(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    anchors = anchor_texts(project_dir)

    assert set(anchors) == {'nora'}
    assert anchors['nora'] == (
        'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
        'grey-green eyes.'
    )


def test_anchor_texts_omits_placeholder_blocks(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'ghost.md'),
                 body=CANON_BODY.replace(
                     'Nora, 9 years old, 132 cm, dark brown hair in a short '
                     'bob, grey-green eyes.',
                     'TODO: describe this character',
                 ).replace('canon_id: nora', 'canon_id: ghost'))

    assert 'ghost' not in anchor_texts(project_dir)


def test_anchor_texts_excludes_non_entity_types(project_dir):
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))

    assert anchor_texts(project_dir) == {}


def test_resolve_canon_path_finds_root_and_subdir(project_dir):
    from storyforge.canon import resolve_canon_path
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))

    assert resolve_canon_path(project_dir, 'nora').endswith(
        os.path.join('characters', 'nora.md'))
    assert resolve_canon_path(project_dir, 'visual-foundation').endswith(
        'visual-foundation.md')
    assert resolve_canon_path(project_dir, 'nobody') is None


def test_anchor_texts_excludes_starter_templates(project_dir, plugin_dir):
    """`skills/init/SKILL.md` copies templates/reference/canon/ into every
    new project, so characters/_template.md is present and permanent in
    normal projects. Its Embeddable block is instructional prose (not a
    TODO stub), so only a template guard — not the placeholder check —
    keeps it out of anchor_texts. Regression for the round-1 review
    finding: a hand-rolled os.walk without _walk_canon_files's
    _is_template_file guard let this scaffold through as a real anchor
    keyed by the literal string '<character-slug>'."""
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    template_path = os.path.join(
        plugin_dir, 'templates', 'reference', 'canon', 'characters',
        '_template.md',
    )
    with open(template_path, encoding='utf-8') as f:
        template_body = f.read()
    _write_canon(
        project_dir, os.path.join('characters', '_template.md'),
        body=template_body,
    )
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    anchors = anchor_texts(project_dir)

    assert set(anchors) == {'nora'}
    assert '<character-slug>' not in anchors


def test_anchor_texts_deterministic_on_duplicate_canon_id(project_dir):
    """Nothing currently validates against a duplicate canon_id across
    directories, so anchor_texts must resolve collisions the same way on
    every machine rather than depend on os.walk's filesystem-dependent
    directory order. _walk_canon_files sorts by full path, so of two
    entity files sharing a canon_id under characters/ and locations/,
    'characters/...' sorts before 'locations/...' and is processed
    first — the locations file is written second and wins."""
    from storyforge.canon import anchor_texts
    _set_medium(project_dir, 'novel')
    _write_canon(
        project_dir, os.path.join('characters', 'dup.md'),
        body=CANON_BODY.replace('canon_id: nora', 'canon_id: dup').replace(
            'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
            'grey-green eyes.',
            'Character-canon version of dup.',
        ),
    )
    _write_canon(
        project_dir, os.path.join('locations', 'dup.md'),
        body=CANON_BODY
        .replace('canon_id: nora', 'canon_id: dup')
        .replace('canon_type: character', 'canon_type: location')
        .replace(
            'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
            'grey-green eyes.',
            'Location-canon version of dup.',
        ),
    )

    anchors = anchor_texts(project_dir)

    assert anchors['dup'] == 'Location-canon version of dup.'


# ============================================================================
# Task 4: --prompts reads and writes canon anchors
# ============================================================================

def test_prompts_anchors_come_from_canon(project_dir):
    from storyforge.prompts_illustrate import anchors_for_prompt
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    anchors = anchors_for_prompt(project_dir)

    assert anchors['nora'].startswith('Nora, 9 years old, 132 cm')


def test_relevant_anchors_matches_canon_ids(project_dir):
    from storyforge.cmd_illustrate import _relevant_anchors
    anchors = {'nora': 'Nora anchor', 'leo': 'Leo anchor',
               'great-lamp': 'Lamp anchor'}

    row = {'canon_refs': 'nora;great-lamp'}
    assert set(_relevant_anchors(anchors, row)) == {'nora', 'great-lamp'}


def test_relevant_anchors_falls_back_when_nothing_matches(project_dir):
    """An unfiltered anchor set is a smaller failure than a missing one, so a
    canon_refs value that matches no canon_id sends everything."""
    from storyforge.cmd_illustrate import _relevant_anchors
    anchors = {'nora': 'Nora anchor', 'leo': 'Leo anchor'}

    row = {'canon_refs': 'somebody-else'}
    assert set(_relevant_anchors(anchors, row)) == {'nora', 'leo'}


def test_relevant_anchors_warns_on_a_partial_mismatch(project_dir, capsys):
    """The migration hole for a real book: a row naming two entities where
    only one has a canon anchor narrows to that one and renders the other
    with no anchor at all. Nothing else catches it — an id with no canon
    anchor is deliberately not a _direction_anchor_mismatches finding, and
    canon_unfilled_template is info severity, which build_cleanup_report
    excludes from action items. Only the total-failure case used to warn."""
    from storyforge.cmd_illustrate import _relevant_anchors
    anchors = {'nora': 'Nora anchor', 'village': 'Village anchor'}

    row = {'id': 'LF-01', 'canon_refs': 'nora;great-lamp'}
    assert set(_relevant_anchors(anchors, row)) == {'nora'}
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'great-lamp' in out
    assert 'LF-01' in out
    assert 'nora' not in out.replace('great-lamp', '')  # matched one is silent


def test_append_anchor_stubs_routes_by_type(project_dir):
    from storyforge.prompts_illustrate import append_anchor_stubs
    from storyforge.canon import anchor_texts, resolve_canon_path

    written = append_anchor_stubs(project_dir, {
        'Nora': ('character', 'A nine-year-old in a green cardigan.'),
        'Old Oak': ('location', 'A hollow oak whose roots form streets.'),
        'Great Lamp': ('motif', 'A bronze bowl with several wicks.'),
    })

    assert sorted(written) == ['great-lamp', 'nora', 'old-oak']
    assert resolve_canon_path(project_dir, 'nora').endswith(
        os.path.join('characters', 'nora.md'))
    assert resolve_canon_path(project_dir, 'old-oak').endswith(
        os.path.join('locations', 'old-oak.md'))
    assert resolve_canon_path(project_dir, 'great-lamp').endswith(
        os.path.join('motifs', 'great-lamp.md'))
    assert anchor_texts(project_dir)['great-lamp'] == (
        'A bronze bowl with several wicks.')


def test_append_anchor_stubs_unknown_type_falls_back_to_character(project_dir):
    from storyforge.prompts_illustrate import append_anchor_stubs
    from storyforge.canon import resolve_canon_path

    written = append_anchor_stubs(project_dir,
                                  {'Murkwolf': ('creature', 'Cold blue mist.')})

    assert written == ['murkwolf']
    assert resolve_canon_path(project_dir, 'murkwolf').endswith(
        os.path.join('characters', 'murkwolf.md'))


def test_append_anchor_stubs_never_revises_existing(project_dir):
    from storyforge.prompts_illustrate import append_anchor_stubs
    from storyforge.canon import anchor_texts
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    original = anchor_texts(project_dir)['nora']

    written = append_anchor_stubs(
        project_dir, {'Nora': ('character', 'Something different.')})

    assert written == []
    assert anchor_texts(project_dir)['nora'] == original


def test_split_anchor_block_parses_type_and_keeps_hyphenated_names():
    from storyforge.prompts_illustrate import split_anchor_block

    body, anchors = split_anchor_block(
        'Prompt text here.\n\n'
        'ANCHORS\n'
        '- Jean-Luc | character — a tall man in a grey coat\n'
        '- Old Oak | location — a hollow oak\n'
        '- Untyped Thing — no type given\n'
    )

    assert body.strip() == 'Prompt text here.'
    assert anchors['Jean-Luc'] == ('character', 'a tall man in a grey coat')
    assert anchors['Old Oak'] == ('location', 'a hollow oak')
    assert anchors['Untyped Thing'] == ('', 'no type given')


# ============================================================================
# Fix round 1: existence check must key on canon_id, not filename stem (C-1,
# C-2). resolve_canon_path (and its underlying index) keys on the filename
# stem, which is only right when a file's declared canon_id matches its own
# name — canon_id_mismatch and canon_id_invalid merely warn about that, they
# don't block. append_anchor_stubs must not trust the stem.
# ============================================================================

def test_append_anchor_stubs_never_touches_a_case_differing_existing_file(
        project_dir):
    """C-1: characters/Nora.md declares canon_id: nora. The stem-keyed
    resolve_canon_path index stores it under key 'Nora', not 'nora', so
    resolve_canon_path(project_dir, 'nora') returned None — "no such file" —
    and append_anchor_stubs then wrote characters/nora.md to "add" the
    anchor. On a case-insensitive filesystem that path IS Nora.md, so
    open(path, 'w') truncated the author's file in place with no warning at
    all. The fix must key existence on the canon_id declared in frontmatter,
    case-insensitively, so this is caught regardless of filesystem case
    sensitivity. Asserting only `written == []` would pass even if the file
    had been clobbered first — this reads bytes before and after and
    compares them exactly."""
    from storyforge.prompts_illustrate import append_anchor_stubs
    path = _write_canon(project_dir, os.path.join('characters', 'Nora.md'))
    with open(path, 'rb') as f:
        before = f.read()

    written = append_anchor_stubs(
        project_dir, {'Nora': ('character', 'A totally different girl.')})

    with open(path, 'rb') as f:
        after = f.read()
    assert written == []
    assert after == before


def test_append_anchor_stubs_never_shadows_a_differently_stemmed_file(
        project_dir):
    """C-2: characters/nora-smith.md declares canon_id: nora — a stem that
    doesn't match its own id. The stem-keyed existence check looked for a
    file literally named nora.md, found none, and append_anchor_stubs wrote
    one alongside the original. anchor_texts's last-sorted-path tie-break
    ('nora-smith.md' sorts before 'nora.md') then let the model's guess
    shadow the author's real anchor. The fix must recognize the existing
    canon_id regardless of the stem it lives under, so no second file gets
    written and the author's text keeps resolving."""
    from storyforge.prompts_illustrate import append_anchor_stubs
    from storyforge.canon import anchor_texts
    _write_canon(project_dir, os.path.join('characters', 'nora-smith.md'),
                body=CANON_BODY.replace(
                    'Nora, 9 years old, 132 cm, dark brown hair in a short '
                    'bob, grey-green eyes.',
                    'AUTHOR ORIGINAL: Nora, 9 years old, 132 cm.',
                ))

    written = append_anchor_stubs(
        project_dir, {'Nora': ('character', 'MODEL GUESS text.')})

    assert written == []
    assert not os.path.isfile(os.path.join(
        project_dir, 'reference', 'canon', 'characters', 'nora.md'))
    assert anchor_texts(project_dir)['nora'] == (
        'AUTHOR ORIGINAL: Nora, 9 years old, 132 cm.')


def test_canon_id_index_is_case_insensitive_and_keys_on_frontmatter(
        project_dir):
    """canon_id_index must answer 'nora' from a file's declared canon_id
    even when the filename stem is differently cased or doesn't match at
    all — the two shapes append_anchor_stubs has to guard against."""
    from storyforge.canon import canon_id_index
    _write_canon(project_dir, os.path.join('characters', 'Nora.md'))

    index = canon_id_index(project_dir)

    assert index['nora'] == os.path.join(
        'reference', 'canon', 'characters', 'Nora.md')


@pytest.mark.parametrize('label,body', [
    ('no frontmatter', 'Just some prose, no frontmatter block at all.\n'),
    ('truncated frontmatter',
     '---\ncanon_id: nora\ncanon_type: character\n'),
    ('no canon_id key',
     '---\ncanon_type: character\ncanon_updated: 2026-07-28\n'
     'appears_in: vigil\nfirst_appearance: vigil\n---\n\n'
     '## Embeddable block\n\nSomething.\n'),
])
def test_append_anchor_stubs_never_touches_a_malformed_file_at_the_candidate_path(
        project_dir, label, body):
    """Regression (fix round 2): canon_id_index only sees files whose
    frontmatter it can parse a canon_id out of. A file sitting at the exact
    path a proposal's slug would candidate — no frontmatter, truncated
    frontmatter, or frontmatter missing the canon_id key — is invisible to
    that index alone, so append_anchor_stubs truncated a real (if malformed)
    file the moment 'Nora' slugified to a path that already existed. The old
    stem-keyed resolve_canon_path saw every .md file regardless of whether
    its frontmatter parsed, and correctly skipped all three shapes; the fix
    restores that guarantee with a plain path-exists check ahead of the
    write, alongside (not instead of) the canon_id_index check."""
    path = _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                        body=body)
    with open(path, 'rb') as f:
        before = f.read()

    from storyforge.prompts_illustrate import append_anchor_stubs
    written = append_anchor_stubs(
        project_dir, {'Nora': ('character', 'A totally different girl.')})

    with open(path, 'rb') as f:
        after = f.read()
    assert written == [], label
    assert after == before, label


# ============================================================================
# Task 5: the direction_anchor_mismatch hand-edit safety net
# ============================================================================

DIRECTION_DOC = """# Illustration art direction

## Continuity anchors

### nora

Nora, 9 years old, 132 cm, dark brown hair in a short bob, grey-green eyes.
"""


def _write_direction(project_dir, body=DIRECTION_DOC):
    path = os.path.join(project_dir, 'reference', 'illustration-direction.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)


def test_matching_anchor_produces_no_mismatch(project_dir):
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_direction(project_dir)

    kinds = {f['kind'] for f in validate_plan(project_dir)}

    assert 'direction_anchor_mismatch' not in kinds


def test_changed_anchor_is_reported(project_dir):
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_direction(project_dir, DIRECTION_DOC.replace('132 cm', '140 cm'))

    findings = [f for f in validate_plan(project_dir)
                if f['kind'] == 'direction_anchor_mismatch']

    assert len(findings) == 1
    assert findings[0]['id'] == 'nora'
    assert '140 cm' in findings[0]['detail'] or '132 cm' in findings[0]['detail']


def test_no_direction_document_means_silence(project_dir):
    """Once the old file is deleted the check goes quiet forever."""
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))

    kinds = {f['kind'] for f in validate_plan(project_dir)}

    assert 'direction_anchor_mismatch' not in kinds


def test_mismatch_is_a_warning_not_blocking(project_dir):
    from storyforge.illustrations import severity_of
    assert severity_of('direction_anchor_mismatch') == 'warning'


def test_anchor_absent_from_canon_is_skipped_not_reported(project_dir):
    """Mid-hand-edit is normal in-flight state: an anchor still sitting in
    the direction document that has no corresponding canon file at all
    (not even a placeholder one) is the author's call, not a finding."""
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    # No canon file written at all — 'nora' resolves to nothing.
    _write_direction(project_dir)

    findings = [f for f in validate_plan(project_dir)
                if f['kind'] == 'direction_anchor_mismatch']

    assert findings == []


def test_direction_heading_is_slugified_before_matching_canon_id(project_dir):
    """The one real project's headings are human names ('Great Lamp') while
    canon ids are slugs ('great-lamp'). An exact-key lookup would match
    nothing and the safety net would be silent everywhere it matters, so the
    heading must be slugified with the same function
    prompts_illustrate._slugify uses elsewhere for this exact translation."""
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(
        project_dir, os.path.join('motifs', 'great-lamp.md'),
        body=CANON_BODY
        .replace('canon_id: nora', 'canon_id: great-lamp')
        .replace('canon_type: character', 'canon_type: motif')
        .replace(
            'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
            'grey-green eyes.',
            'A bronze bowl with several wicks, always lit at dusk.',
        ),
    )
    _write_direction(project_dir, """# Illustration art direction

## Continuity anchors

### Great Lamp

A bronze bowl with several wicks, always lit at dusk but for one flame gone dark.
""")

    findings = [f for f in validate_plan(project_dir)
                if f['kind'] == 'direction_anchor_mismatch']

    assert len(findings) == 1
    assert findings[0]['id'] == 'great-lamp'


def test_direction_anchors_heading_is_matched_case_insensitively(project_dir):
    """M6 (Task 7 fix round 1): find_section's case-insensitive lookup is
    what _direction_anchor_mismatches relies on to locate the anchors
    section at all — a hand-edited document that writes '## Continuity
    Anchors' (capital A) rather than the exact '## Continuity anchors' must
    still be found, or the safety net goes silent on every document that
    doesn't match the case exactly. This restores, at the safety net's real
    entry point, the integration-level coverage
    test_anchors_section_is_read_case_insensitively gave the retired
    read_continuity_anchors/missing_direction_sections pair before Task 7
    deleted them — find_section itself is still load-bearing here.

    Asserts the mismatch (not the no-mismatch case): if find_section failed
    to match the mis-cased heading, anchors_body would be '' and
    _direction_anchor_mismatches would return [] regardless of whether the
    anchor text actually changed — a no-mismatch assertion alone wouldn't
    distinguish 'correctly matched, texts agree' from 'silently found
    nothing.' Asserting the finding fires when the text HAS changed proves
    the heading was actually located."""
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    _write_direction(project_dir, DIRECTION_DOC
                     .replace('## Continuity anchors', '## Continuity Anchors')
                     .replace('132 cm', '140 cm'))

    findings = [f for f in validate_plan(project_dir)
                if f['kind'] == 'direction_anchor_mismatch']

    assert len(findings) == 1
    assert findings[0]['id'] == 'nora'


def test_normalize_for_comparison_matches_extracted_canon_behavior():
    """common.normalize_for_comparison must be byte-identical to the
    behavior canon._normalize_for_drift had before the extraction — a
    multi-line block with trailing spaces and a doubled blank line is the
    shape that behavior exists to handle."""
    from storyforge.common import normalize_for_comparison

    text = (
        "  Line one.   \n"
        "Line two.  \n"
        "\n"
        "\n"
        "   Line three.\n"
    )

    assert normalize_for_comparison(text) == (
        "Line one.\nLine two.\n\nLine three."
    )


def test_mismatch_detail_has_no_newline_or_pipe(project_dir):
    """Fix round 1: working/cleanup-report.csv (cmd_cleanup._write_report) is
    unquoted pipe-delimited CSV written one row per '\\n' — a multi-line or
    pipe-carrying `detail` shatters the row into several malformed ones with
    no `status` field, exactly the shape skills/cleanup and skills/forge read
    by column. The anchor text here deliberately carries both a newline and
    a `|` so a regression that reintroduces either would be caught."""
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(
        project_dir, os.path.join('characters', 'nora.md'),
        body=CANON_BODY.replace(
            'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
            'grey-green eyes.',
            'Nora, 9 years old, 132 cm | 52 kg, dark brown hair.',
        ),
    )
    _write_direction(project_dir, """# Illustration art direction

## Continuity anchors

### nora

Nora, 9 years old,
140 cm | 52 kg, dark brown hair.
""")

    findings = [f for f in validate_plan(project_dir)
                if f['kind'] == 'direction_anchor_mismatch']

    assert len(findings) == 1
    detail = findings[0]['detail']
    assert '\n' not in detail
    assert '|' not in detail
    # Flattened content must still be present and readable, just not as a
    # literal pipe or physical newline.
    assert '140 cm' in detail or '132 cm' in detail


def test_placeholder_canon_file_is_skipped_not_reported(project_dir):
    """The skip-don't-report branch also covers a canon file that EXISTS but
    whose Embeddable block is still placeholder text — a different mechanism
    than 'no canon file at all' (this one runs through
    canon.anchor_texts's placeholder filter, which excludes the id from the
    dict entirely). Both collapse into new.get(canon_id) is None, so the
    direction document's original text survives unreported, same as
    mid-hand-edit with no canon file yet."""
    from storyforge.illustrations import validate_plan
    _set_medium(project_dir, 'novel')
    _write_canon(
        project_dir, os.path.join('characters', 'nora.md'),
        body=CANON_BODY.replace(
            'Nora, 9 years old, 132 cm, dark brown hair in a short bob, '
            'grey-green eyes.',
            'TODO: describe this character',
        ),
    )
    _write_direction(project_dir)

    findings = [f for f in validate_plan(project_dir)
                if f['kind'] == 'direction_anchor_mismatch']

    assert findings == []


# ============================================================================
# Task 6: --direction writes canon files
# ============================================================================

def test_direction_writes_the_three_book_level_canon_files(project_dir):
    from storyforge.cmd_illustrate import run_direction
    _set_medium(project_dir, 'novel')

    run_direction(project_dir, coaching='strict', dry_run=False)

    from storyforge.canon import resolve_canon_path
    for canon_id in ('visual-foundation', 'visual-vocabulary',
                     'content-limits'):
        assert resolve_canon_path(project_dir, canon_id) is not None, canon_id


def test_direction_never_overwrites_an_existing_canon_file(project_dir):
    from storyforge.cmd_illustrate import run_direction
    from storyforge.canon import resolve_canon_path, embeddable_block_text
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))
    before = embeddable_block_text(
        resolve_canon_path(project_dir, 'visual-foundation'))

    run_direction(project_dir, coaching='strict', dry_run=False)

    after = embeddable_block_text(
        resolve_canon_path(project_dir, 'visual-foundation'))
    assert after == before


@pytest.mark.parametrize('label,body', [
    ('no frontmatter', 'Just some prose, no frontmatter block at all.\n'),
    ('truncated frontmatter',
     '---\ncanon_id: visual-foundation\ncanon_type: foundation\n'),
    ('no canon_id key',
     '---\ncanon_type: foundation\ncanon_updated: 2026-07-28\n'
     'appears_in:\nfirst_appearance:\n---\n\n'
     '## Embeddable block\n\nSomething.\n'),
])
def test_direction_never_touches_a_malformed_file_at_the_candidate_path(
        project_dir, capsys, label, body):
    """Both overwrite tests above use well-formed files, which trip the
    canon_id_index check before the os.path.exists check is ever reached —
    that second check has no coverage without this. Same regression shape
    as Task 4's test_append_anchor_stubs_never_touches_a_malformed_file_at_the_candidate_path:
    a file sitting at the exact path --direction would write
    (reference/canon/visual-foundation.md) whose frontmatter
    canon_id_index cannot parse a canon_id out of — absent, truncated, or
    missing the canon_id key — is invisible to that index alone. Asserting
    only that the run succeeds would pass even if the file had been
    clobbered first; this reads bytes before and after and compares them
    exactly, and asserts the WARNING that names the file."""
    from storyforge.cmd_illustrate import run_direction
    _set_medium(project_dir, 'novel')
    path = os.path.join(project_dir, 'reference', 'canon',
                        'visual-foundation.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    with open(path, 'rb') as f:
        before = f.read()

    run_direction(project_dir, coaching='strict', dry_run=False)

    with open(path, 'rb') as f:
        after = f.read()
    assert after == before, label
    out = capsys.readouterr().out
    assert 'WARNING' in out, label
    assert 'visual-foundation.md' in out, label


def test_direction_strict_makes_no_api_call(project_dir, monkeypatch):
    """run_direction's only API path is cmd_illustrate._invoke (which calls
    api.invoke, not api.invoke_api) — patching api.invoke_api, as the brief's
    own snippet did, never intercepts anything real: run_direction(..., coaching='full')
    still reaches the network under that patch. Patch _invoke itself, the
    same target test_direction_full_writes_the_model_output and
    test_direction_reports_incomplete_sections already patch, so this test
    actually fails if the coaching == 'full' gate at the top of the API
    branch is ever removed or widened.

    ANTHROPIC_API_KEY is set deliberately (fix round 1): without it, the
    `if coaching == 'full':` branch's own `if not
    os.environ.get('ANTHROPIC_API_KEY'): return 1` guard would fire first if
    that gate were ever buggily widened to include 'strict' — the run would
    return 1 without ever reaching `_invoke`, and this test would pass
    without the _boom trap ever springing, protecting nothing. With a key
    present, a widened gate reaches `_invoke` and `_boom` raises for real."""
    from storyforge import cmd_illustrate
    from storyforge.cmd_illustrate import run_direction
    _set_medium(project_dir, 'novel')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*args, **kwargs):
        raise AssertionError('strict coaching must not call the API')

    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    assert run_direction(project_dir, coaching='strict', dry_run=False) == 0


# ============================================================================
# Task 7: has_reference_tier / missing_reference_sections replace the
# direction-document readers
# ============================================================================

def test_has_reference_tier_requires_all_three(project_dir):
    from storyforge.illustrations import has_reference_tier
    _set_medium(project_dir, 'novel')
    assert has_reference_tier(project_dir) is False

    for canon_id, canon_type in (('visual-foundation', 'foundation'),
                                 ('visual-vocabulary', 'vocabulary'),
                                 ('content-limits', 'rules')):
        _write_canon(project_dir, f'{canon_id}.md',
                     body=CANON_BODY
                     .replace('canon_id: nora', f'canon_id: {canon_id}')
                     .replace('canon_type: character',
                              f'canon_type: {canon_type}'))

    assert has_reference_tier(project_dir) is True


def test_missing_reference_sections_reports_placeholders(project_dir):
    from storyforge.illustrations import missing_reference_sections
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation')
                 .replace('Nora, 9 years old, 132 cm, dark brown hair in a '
                          'short bob, grey-green eyes.',
                          'TODO — fill this in'))

    missing = missing_reference_sections(project_dir)

    assert 'visual-foundation' in missing
    assert 'content-limits' in missing


@pytest.mark.parametrize('placeholder_text', [
    '_(fill this in)_', 'TBD', 'todo', '_Required: describe the palette_',
    '(you fill this in)',
])
def test_missing_reference_sections_catches_every_hand_typed_placeholder(
        project_dir, placeholder_text):
    """The five shapes the retired illustrations._is_placeholder recognized
    (emphasized boilerplate, bare TBD/todo/n-a/fill-this-in), now routed
    through canon._section_body_is_placeholder. A hand-typed
    '_(fill this in)_' Embeddable block must not read as populated house
    style — that's exactly what would have been fed to the image model as
    though it were direction."""
    from storyforge.illustrations import missing_reference_sections
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation')
                 .replace('Nora, 9 years old, 132 cm, dark brown hair in a '
                          'short bob, grey-green eyes.', placeholder_text))

    assert 'visual-foundation' in missing_reference_sections(project_dir)


def test_missing_reference_sections_catches_an_empty_embeddable_block(
        project_dir):
    """canon._section_body_is_placeholder deliberately treats an empty
    Embeddable block as populated (is_canon_block_populated's documented
    behavior, which GN's page-architecture gate relies on) — but an empty
    book-level direction section is still useless to a prompt, same as the
    retired illustration-direction reader. missing_reference_sections adds
    that check on its own side rather than the shared function's behavior
    changing under every caller."""
    from storyforge.illustrations import missing_reference_sections
    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation')
                 .replace('Nora, 9 years old, 132 cm, dark brown hair in a '
                          'short bob, grey-green eyes.', ''))

    assert 'visual-foundation' in missing_reference_sections(project_dir)


def test_read_continuity_anchors_is_gone():
    import storyforge.illustrations as ill
    assert not hasattr(ill, 'read_continuity_anchors')


def test_missing_direction_sections_and_has_direction_are_gone():
    """Deleted alongside read_continuity_anchors — has_reference_tier and
    missing_reference_sections replace them."""
    import storyforge.illustrations as ill
    assert not hasattr(ill, 'missing_direction_sections')
    assert not hasattr(ill, 'has_direction')
    assert not hasattr(ill, 'anchors_section_headings')


def test_prompts_carry_canon_house_style_end_to_end(project_dir, monkeypatch):
    """The defect this task closes: --prompts must read the three CANON_PLAN
    files, not the retired illustration-direction.md, and a populated
    reference tier must actually reach the generated prompt text — not just
    the reader function in isolation. Exercises cmd_illustrate.run_prompts
    directly (as the rest of this module does for run_direction), rather than
    cmd_illustrate.main, so it does not depend on the process cwd."""
    from storyforge import cmd_illustrate
    from storyforge.illustrations import write_plan, blank_row

    _set_medium(project_dir, 'novel')
    _write_canon(project_dir, 'visual-foundation.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation')
                 .replace('Nora, 9 years old, 132 cm, dark brown hair in a '
                          'short bob, grey-green eyes.',
                          'Full-color, cinematic photorealistic storybook '
                          'imagery for ages 6-8.'))
    _write_canon(project_dir, 'content-limits.md',
                 body=CANON_BODY
                 .replace('canon_id: nora', 'canon_id: content-limits')
                 .replace('canon_type: character', 'canon_type: rules')
                 .replace('Nora, 9 years old, 132 cm, dark brown hair in a '
                          'short bob, grey-green eyes.',
                          'Never horror imagery. No blood or gore.'))

    scene_path = os.path.join(project_dir, 'scenes', 'vigil.md')
    os.makedirs(os.path.dirname(scene_path), exist_ok=True)
    with open(scene_path, 'w', encoding='utf-8') as f:
        f.write('She set it on the sill and waited.\n')

    row = blank_row('lantern-vigil')
    row.update({'scene_id': 'vigil', 'anchor': 'She set it on the sill',
               'placement': 'after_anchor', 'beat': 'A woman waits',
               'rationale': 'holds the waiting'})
    write_plan(project_dir, [row])

    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    seen = {}
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda pd, prompt, op, **kw: (
                            seen.update(prompt=prompt) or
                            '### Scene\n\nX.\n'))

    assert cmd_illustrate.run_prompts(
        project_dir, coaching='full', ids=None, dry_run=False) == 0
    prompt = seen['prompt']
    assert 'Book-level art direction' in prompt
    assert 'cinematic photorealistic' in prompt
    assert 'Never horror imagery' in prompt


# ============================================================================
# The --direction request/response contract
#
# Fix round 2, item 2: the request demonstrated its blocks as `###` while its
# own instruction said "use these exact `##` headings", and the parser matched
# only an exact-lowercase `##` id. Three of four plausible model outputs
# yielded {}, and run_direction then paid for the call and silently wrote TODO
# scaffolds over the discarded response. There were zero tests for either
# function.
# ============================================================================

_DIRECTION_BODIES = (
    'Full-color photorealism for ages 6-8.',
    'Warm amber against cool blue.',
    'Never horror imagery.',
)


@pytest.mark.parametrize('label,heading_fmt', [
    ('h2 exact id', '## {id}'),
    ('h3 exact id', '### {id}'),
    ('h2 title case', '## {Title}'),
    ('h2 spaced words', '## {spaced}'),
    ('h2 title-cased words', '## {Spaced}'),
    ('h2 trailing colon', '## {id}:'),
])
def test_parse_canon_direction_response_accepts_each_shape(label, heading_fmt):
    from storyforge.prompts_illustrate import (
        CANON_PLAN, parse_canon_direction_response,
    )
    chunks = []
    for (canon_id, _t, _p), body in zip(CANON_PLAN, _DIRECTION_BODIES):
        spaced = canon_id.replace('-', ' ')
        heading = heading_fmt.format(
            id=canon_id, Title=canon_id.title(), spaced=spaced,
            Spaced=spaced.title())
        chunks.append(f'{heading}\n\n{body}\n')
    parsed = parse_canon_direction_response('\n'.join(chunks))

    assert parsed == {
        canon_id: body
        for (canon_id, _t, _p), body in zip(CANON_PLAN, _DIRECTION_BODIES)
    }, label


def test_parse_canon_direction_response_keeps_h3_subheadings_in_the_body():
    """`###` is accepted as a section delimiter only as a fallback: an h2
    section whose body contains h3 sub-headings must keep them, or accepting
    h3 outright would truncate the body at the first one."""
    from storyforge.prompts_illustrate import parse_canon_direction_response
    text = ('## visual-vocabulary\n\n### Palette\n\nWarm amber.\n\n'
            '### Camera\n\nEye level.\n')

    parsed = parse_canon_direction_response(text)

    assert '### Camera' in parsed['visual-vocabulary']
    assert 'Eye level.' in parsed['visual-vocabulary']


def test_parse_canon_direction_response_ignores_unknown_headings():
    from storyforge.prompts_illustrate import parse_canon_direction_response
    parsed = parse_canon_direction_response(
        '## visual-foundation\n\nPhotorealism.\n\n'
        '## bonus-thoughts\n\nSomething the model made up.\n')
    assert set(parsed) == {'visual-foundation'}


def test_parse_canon_direction_response_warns_on_unyielded_ids(capsys):
    """The response is always asked for all three blocks, so a missing one
    means the caller is about to write a TODO scaffold over a paid-for
    response — which used to be reported only as `needs your input` on a
    file --direction had just created."""
    from storyforge.prompts_illustrate import parse_canon_direction_response
    parse_canon_direction_response('## visual-foundation\n\nPhotorealism.\n')

    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'visual-vocabulary' in out
    assert 'content-limits' in out
    assert 'visual-foundation' not in out.replace('WARNING', '')


def test_parse_canon_direction_response_silent_when_complete(capsys):
    from storyforge.prompts_illustrate import (
        CANON_PLAN, parse_canon_direction_response,
    )
    text = '\n'.join(
        f'## {canon_id}\n\n{body}\n'
        for (canon_id, _t, _p), body in zip(CANON_PLAN, _DIRECTION_BODIES))
    parse_canon_direction_response(text)
    assert 'WARNING' not in capsys.readouterr().out


def test_canon_direction_request_demonstrates_the_heading_level_it_asks_for():
    """Regression: the briefs were rendered as `### <id>` under an
    instruction to "use these exact `##` headings". A model that copied the
    demonstration produced a response the parser discarded wholesale."""
    from storyforge.prompts_illustrate import (
        CANON_PLAN, build_canon_direction_request,
    )
    prompt = build_canon_direction_request(
        title='T', genre='', audience='', canon_context='C',
        story_context='S')

    for canon_id, _t, _p in CANON_PLAN:
        assert f'## {canon_id}' in prompt
        assert f'### {canon_id}' not in prompt


def test_canon_direction_request_headings_round_trip_through_the_parser():
    """The two halves of the contract must agree: whatever heading shape the
    request demonstrates has to be a shape the parser accepts. Echoing the
    request's own briefs back as a response must parse to all three ids."""
    from storyforge.prompts_illustrate import (
        CANON_PLAN, build_canon_direction_request,
        parse_canon_direction_response,
    )
    prompt = build_canon_direction_request(
        title='T', genre='', audience='', canon_context='C',
        story_context='S')
    start = prompt.index(f'## {CANON_PLAN[0][0]}')
    echoed = prompt[start:prompt.index('## How to write it')]

    assert set(parse_canon_direction_response(echoed)) == {
        canon_id for canon_id, _t, _p in CANON_PLAN}


# ============================================================================
# Fix round 2, item 4: _canon_stub stamps canon_updated
#
# render_canon_template (coach/strict) stamped today's date; _canon_stub — the
# shape render_filled_canon and append_anchor_stubs both write, i.e. the FULL
# coaching path — left it blank, so full coaching produced three extra
# canon_missing_key warnings coach coaching did not.
# ============================================================================

def test_filled_canon_and_anchor_stubs_stamp_canon_updated(project_dir):
    from datetime import date

    from storyforge.canon import (
        parse_canon_file, resolve_canon_path, validate_canon_file,
    )
    from storyforge.prompts_illustrate import (
        append_anchor_stubs, render_filled_canon,
    )
    _set_medium(project_dir, 'novel')
    today = date.today().isoformat()

    path = os.path.join(project_dir, 'reference', 'canon',
                        'visual-foundation.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_filled_canon(canon_id='visual-foundation',
                                    canon_type='foundation',
                                    body='Full-color photorealism.'))
    assert parse_canon_file(path)['frontmatter']['canon_updated'] == today
    keys = [f['detail'] for f in validate_canon_file(path, project_dir)
            if f['type'] == 'canon_missing_key']
    assert not any('canon_updated' in d for d in keys), keys

    append_anchor_stubs(project_dir, {'Nora': ('character', 'Nora, 9, 132 cm.')})
    stub = resolve_canon_path(project_dir, 'nora')
    fm = parse_canon_file(stub)['frontmatter']
    assert fm['canon_updated'] == today
    # appears_in / first_appearance stay blank deliberately — guessing
    # first_appearance would misorder the render sequence.
    assert fm['appears_in'] == ''
    assert fm['first_appearance'] == ''


# ============================================================================
# The canon cutoff and anchor display names (prompt items 3 and 4)
#
# The cutoff answers "was this render directed by the canon that governs it
# now?" — the question _references_for had no way to ask, which is how three
# pre-canon renders ended up as the style references for the image meant to
# replace them. The display names answer "what should a human-facing document
# call this anchor?", which is why a model echoed `leo` back in prose.
# ============================================================================

def test_iso_date_or_empty_accepts_a_date_and_a_timestamp():
    from storyforge.canon import iso_date_or_empty
    assert iso_date_or_empty('2026-07-28') == '2026-07-28'
    assert iso_date_or_empty('2026-07-28T09:14:00') == '2026-07-28'
    assert iso_date_or_empty(' 2026-07-28 ') == '2026-07-28'
    assert iso_date_or_empty('July 28 2026') == ''
    assert iso_date_or_empty('2026-7-8') == ''
    assert iso_date_or_empty('') == ''


def test_newest_canon_updated_takes_the_latest_date(project_dir):
    from storyforge.canon import newest_canon_updated
    _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                 CANON_BODY.replace('canon_updated: 2026-07-28',
                                    'canon_updated: 2026-07-01'))
    _write_canon(project_dir, os.path.join('characters', 'leo.md'),
                 CANON_BODY.replace('canon_id: nora', 'canon_id: leo')
                 .replace('canon_updated: 2026-07-28',
                          'canon_updated: 2026-07-20'))
    assert newest_canon_updated(project_dir) == '2026-07-20'


def test_newest_canon_updated_is_empty_without_canon(project_dir):
    from storyforge.canon import newest_canon_updated
    assert newest_canon_updated(project_dir) == ''


def test_newest_canon_updated_reports_an_unparseable_date(project_dir, capsys):
    """A date it cannot read cannot raise the cutoff, so a canon edit can look
    older than it is. That has to be said out loud, not skipped."""
    from storyforge.canon import newest_canon_updated
    _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                 CANON_BODY.replace('canon_updated: 2026-07-28',
                                    'canon_updated: last Tuesday'))
    assert newest_canon_updated(project_dir) == ''
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'last Tuesday' in out
    assert 'canon cutoff' in out


def test_anchor_display_names_prefer_frontmatter(project_dir):
    from storyforge.canon import anchor_display_names
    _write_canon(project_dir, os.path.join('characters', 'nora.md'),
                 CANON_BODY.replace('canon_type: character',
                                    'canon_type: character\n'
                                    'display_name: Nora Vance'))
    entry = anchor_display_names(project_dir)['nora']
    assert entry == {'label': 'Nora Vance', 'source': 'frontmatter'}


def test_anchor_display_names_fall_back_to_the_registry(project_dir):
    """reference/characters.csv already carries the canonical spelling — the
    same source --direction names its stubs from."""
    from storyforge.canon import anchor_display_names
    _write_canon(project_dir, os.path.join('characters', 'dorren-hayle.md'),
                 CANON_BODY.replace('canon_id: nora',
                                    'canon_id: dorren-hayle'))
    entry = anchor_display_names(project_dir)['dorren-hayle']
    assert entry == {'label': 'Dorren Hayle', 'source': 'registry'}


def test_anchor_display_names_fall_back_to_the_humanized_slug(project_dir):
    from storyforge.canon import anchor_display_names, humanize_canon_id
    _write_canon(project_dir, os.path.join('motifs', 'great-lamp.md'),
                 CANON_BODY.replace('canon_id: nora', 'canon_id: great-lamp')
                 .replace('canon_type: character', 'canon_type: motif'))
    entry = anchor_display_names(project_dir)['great-lamp']
    assert entry == {'label': 'Great Lamp', 'source': 'slug'}
    assert humanize_canon_id('great-lamp') == 'Great Lamp'


def test_anchor_display_names_keys_line_up_with_anchor_texts(project_dir):
    """The label dict is looked up by anchor key, so the two must agree."""
    from storyforge.canon import anchor_display_names, anchor_texts
    _write_canon(project_dir, os.path.join('characters', 'nora.md'))
    assert set(anchor_texts(project_dir)) <= set(
        anchor_display_names(project_dir))


def test_anchor_display_names_ignore_book_level_canon(project_dir):
    """Foundation/vocabulary/rules describe the book, not an entity in it."""
    from storyforge.canon import anchor_display_names
    _write_canon(project_dir, 'visual-foundation.md',
                 CANON_BODY.replace('canon_id: nora',
                                    'canon_id: visual-foundation')
                 .replace('canon_type: character', 'canon_type: foundation'))
    assert 'visual-foundation' not in anchor_display_names(project_dir)


# ============================================================================
# predates_canon — the one comparison every canon-cutoff staleness check makes
# ============================================================================

@pytest.mark.parametrize('when,cutoff,expected', [
    ('2026-07-01', '2026-07-20', True),             # strictly older
    ('2026-07-20', '2026-07-20', False),            # same day is the ordinary loop
    ('2026-07-21', '2026-07-20', False),
    ('2026-07-01T10:00:00', '2026-07-20', True),    # a timestamp head compares
    ('2026-07-01', '2026-07-20T23:59:59', True),
    ('', '2026-07-20', False),                      # unknown left says nothing
    ('2026-07-01', '', False),                      # unknown right disables it
    ('not-a-date', '2026-07-20', False),
    ('2026-07-01', 'nonsense', False),
    ('', '', False),
])
def test_predates_canon(when, cutoff, expected):
    """Each caller states its own policy for an unusable date, so this returns
    False for one rather than guessing — including the right-hand-side case,
    which is what silently switches a whole staleness check off."""
    assert canon.predates_canon(when=when, cutoff=cutoff) is expected


def test_predates_canon_is_keyword_only():
    """Two ISO-date arguments where swapping them inverts the result with no
    crash, and the two sides carry deliberately different unknown-value
    policies."""
    with pytest.raises(TypeError):
        canon.predates_canon('2026-07-01', '2026-07-20')
