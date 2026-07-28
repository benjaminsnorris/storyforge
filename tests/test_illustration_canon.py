"""Tests for canon validation running on novel (prose) projects, not just
graphic-novel ones. See .superpowers/sdd/2026-07-28-illustration-canon-adoption/
task-1-brief.md."""

import os

import pytest

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
