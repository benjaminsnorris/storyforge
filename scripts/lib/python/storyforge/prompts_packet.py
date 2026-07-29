"""The six renderers for `manuscript/illustration-packet/`.

Deterministic assembly — no API calls, no timestamps. `--package` regenerates
the packet wholesale, so it is a render and never hand-edited, and two runs over
unchanged sources must produce identical bytes (there is a test).

Why a packet at all. Today's `--prompts` writes a standalone 250–400 word prompt
per illustration, each pasted into an image model on its own. Lived experience on
a twenty-illustration book is that hyper-detailed leaf prompts underperform and
that one long-running session working from shared reference material does better
— the same conclusion GN reached in #260 when per-panel generation failed. So
the shared sections carry the house style, the anchors, the resolved state, and
every acceptance check that is identical across the set, and a per-illustration
entry drops to 80–120 words of what is specific to *that* image.

Two things the renderers must not do:

- **Alter an anchor.** Anchor copies go through `packet.anchor_block`, which
  writes the text byte-for-byte between markers `packet.anchor_copy_drift` reads
  back. Re-wrapping a long anchor to look tidy would break likeness continuity
  across every image that references it.
- **Imply coverage.** A section with nothing behind it says so where the author
  is reading, rather than rendering blank and letting silence read as "fine".
"""

import os
from typing import Final

from storyforge import prompts_illustrate as pi
from storyforge.packet import Entry, PacketContents, StateGrid, anchor_block

#: What a section says when the data behind it is absent. The packet's coverage
#: contract lives in these two strings as much as in README.md's gap list.
_MISSING: Final[str] = '_Not written — see "What this packet cannot tell you" ' \
                       'in README.md._'
_NONE_TRACKED: Final[str] = '_Nothing is tracked yet._'


def _heading_for(canon_id: str) -> str:
    """Section heading for a book-level canon id.

    Mirrors `prompts_illustrate.book_level_direction`, which keys its result
    this way; kept as one function so the lookup below cannot drift from the
    dict it is looking things up in.
    """
    return canon_id.replace('-', ' ').capitalize()


# ============================================================================
# README.md
# ============================================================================

def render_readme(*, title: str, contents: PacketContents,
                  entry_count: int) -> str:
    """The two phases, how to work the packet, and what it cannot tell you."""
    gaps = contents['gaps']
    if gaps:
        gap_block = '\n'.join(f'- {gap}' for gap in gaps)
        gap_intro = (
            f'{len(gaps)} thing(s) below were missing from the data this packet '
            f'was assembled from. Each one is a place the packet is thinner '
            f'than it looks — read them before you generate, not after:')
    else:
        gap_block = ''
        gap_intro = ('Nothing was missing from the data this packet was '
                     'assembled from. That is a statement about the plan, the '
                     'canon files, and the state matrix — not a promise that '
                     'the art will be right.')

    return f"""# Illustration handoff packet — {title}

{entry_count} illustration(s). **This packet is a render.** Every file in it is
regenerated wholesale by `storyforge illustrate --package`, so an edit here is
lost on the next run and never reaches the plan. Change
`reference/illustration-plan.csv`, `reference/visual-state.csv`, or
`reference/canon/` instead, then regenerate.

## The files

| File | What it is |
|---|---|
| `README.md` | This file: the two phases, and what the packet cannot tell you |
| `canon.md` | The reference tier — house style and the continuity anchors |
| `visual-state.md` | Scene x entity: what is visibly true when |
| `illustrations.md` | One thin entry per illustration |
| `reference-images.md` | What to upload, in what order, and what each is for |
| `acceptance.md` | The checks that are the same for every image |

## Two phases

**Phase 1 — the anchor batch.** Render and approve a small set first, then
`storyforge illustrate --ingest <dir>` them. Those images become reference
images for everything after, which is the difference between a set that agrees
with itself and twenty images that each invented their own version of a
character. `storyforge illustrate --diagnose` names the render order and which
of them are still unrendered.

**Phase 2 — the churn.** Work `illustrations.md` top to bottom. Read `canon.md`
once at the start of the session and keep it in context; it is not repeated per
entry. For each entry: upload the images `reference-images.md` names, generate,
then check the result against `acceptance.md` before you accept it.

## What to return

One image file per illustration, named for its id (`{{id}}.png`, `.jpg`, or
`.webp`), in one directory. Then:

```bash
storyforge illustrate --ingest <that directory>
```

Ingest matches files to plan rows by filename stem, records each file's sha256
and dimensions, and embeds the scene markers. A file whose stem matches no plan
row is reported, never guessed at.

## What this packet cannot tell you

{gap_intro}

{gap_block}

Plan health — a marker with no row, a file no row claims, an anchor that no
longer matches the prose — is not in this list. Run `storyforge illustrate
--diagnose` for that.
"""


# ============================================================================
# canon.md
# ============================================================================

def render_canon(*, book_level: dict[str, str], anchors: dict[str, str],
                 labels: dict[str, str]) -> str:
    """The reference tier: house style, then the continuity anchors.

    Anchors are emitted through `packet.anchor_block` so their text is
    byte-identical to the canon source and machine-checkable afterwards.
    """
    parts = [
        '# The reference tier',
        '',
        'Read this once at the start of the session and keep it in context. It '
        'is not repeated in the per-illustration entries — an entry says only '
        'what is specific to that image, which is why the entries are short.',
        '',
    ]

    rendered: set[str] = set()
    for canon_id, _canon_type, purpose in pi.CANON_PLAN:
        heading = _heading_for(canon_id)
        rendered.add(heading)
        body = (book_level.get(heading) or '').strip()
        parts.extend([f'## {heading}', '', body or _MISSING, ''])
        if not body:
            parts.extend([f'_({purpose})_', ''])
    for heading, body in book_level.items():
        if heading not in rendered and body.strip():
            parts.extend([f'## {heading}', '', body.strip(), ''])

    parts.extend([
        '## Continuity anchors',
        '',
        'Each block below is the fixed description of one entity. Use it '
        '**verbatim** — the same words in every image that entity appears in. '
        'Identical strings are the entire mechanism by which a character looks '
        'like the same character in image two and image nineteen, so '
        'paraphrasing one, however well, breaks it. Do not improve an anchor '
        'here; if one is wrong, fix `reference/canon/` and regenerate this '
        'packet — and never revise an anchor an already-rendered illustration '
        'used, because the rendered image is what the string now describes.',
        '',
    ])
    if not anchors:
        parts.extend([_MISSING, ''])
    else:
        for canon_id, text in anchors.items():
            parts.extend([anchor_block(canon_id, text,
                                       labels.get(canon_id) or canon_id), ''])
    return '\n'.join(parts).rstrip() + '\n'


# ============================================================================
# visual-state.md
# ============================================================================

def render_visual_state(*, grid: StateGrid,
                        illustrated: dict[str, list[str]]) -> str:
    """The dense scene x entity view, derived from the sparse transition log.

    Derived here rather than kept under `reference/` so there is no second file
    to keep fresh: `reference/visual-state.csv` records transitions, and a
    transition keyed "from s04 onward" survives the scene reordering that would
    leave a stored grid silently blank.
    """
    parts = [
        '# What is visibly true when',
        '',
        'Derived from `reference/visual-state.csv`, which records only the '
        'moments a state *changes*; the state then persists forward until the '
        'next change. This table is that walk already done. Each entry in '
        '`illustrations.md` also carries the resolution for its own scene, so '
        'you only need this table when you want the shape of the whole book.',
        '',
    ]

    if not grid['entities']:
        parts.extend([
            _NONE_TRACKED,
            '',
            'Nothing records what changes on schedule in this book — wardrobe, '
            'a lamp lit or dark, an object broken. Run `storyforge illustrate '
            '--state`. Every entry below is therefore silent about state, not '
            'confirming it is unchanged.',
            '',
        ])
    else:
        header = ['Scene', 'Illustrations'] + [
            f'`{entity}`' for entity in grid['entities']]
        parts.append('| ' + ' | '.join(header) + ' |')
        parts.append('|' + '---|' * len(header))
        for scene_id in grid['scenes']:
            cells = grid['cells'].get(scene_id, {})
            row = [f'`{scene_id}`',
                   ', '.join(f'`{i}`' for i in illustrated.get(scene_id, []))
                   or '—']
            row.extend(cells.get(entity) or '—' for entity in grid['entities'])
            parts.append('| ' + ' | '.join(row) + ' |')
        parts.append('')
        parts.append('A dash means no transition has stated that entity yet at '
                     'that point in the book — unstated, not unchanged.')
        parts.append('')

    if grid['unpositioned']:
        parts.extend([
            f'**Not in this table:** '
            f'{", ".join(f"`{s}`" for s in grid["unpositioned"])}. These '
            f'scenes are active in `scenes.csv` but `reference/chapter-map.csv` '
            f'does not place them, so nothing above speaks for them.',
            '',
        ])
    return '\n'.join(parts).rstrip() + '\n'


# ============================================================================
# illustrations.md
# ============================================================================

def render_entry(entry: Entry) -> str:
    """One illustration's entry — only what is specific to this image.

    Sections with nothing in them are omitted rather than rendered empty,
    except `Beat` and `In frame`, which carry `packet.NOT_RECORDED` from
    `resolve` so a thin entry reads as thin instead of as terse.

    `Absent` is one of the two deliberate exceptions to positive framing. #263
    established that negated content keywords leak into the render, and that
    holds for description; the exception is narrow and enumerable — named
    entities that must not appear, and violations of the stated colour logic
    (the latter lives in `acceptance.md`). Orientation and no-text are the
    other two exceptions.
    """
    lines = [
        f'### {entry["id"]}',
        '',
        f'- Scene: `{entry["scene_id"] or "—"}` · Layout: '
        f'{entry["layout"]} · Aspect: {entry["aspect"]}',
        '',
        f'**Beat.** {entry["beat"]}',
        '',
        f'**In frame.** {entry["in_frame"]}',
    ]
    for label, value in (('State', entry['state']),
                         ('Absent', entry['absent']),
                         ('Contrast', entry['contrast']),
                         ('This image also', entry['notes'])):
        if value:
            lines.extend(['', f'**{label}.** {value}'])
    return '\n'.join(lines)


def render_illustrations(*, entries: list[Entry]) -> str:
    """Every entry, in reading order."""
    parts = [
        '# The illustrations',
        '',
        f'{len(entries)} illustration(s), in reading order. Each entry is '
        f'deliberately short: the house style, the anchors, and every check '
        f'that is identical across the set live in `canon.md` and '
        f'`acceptance.md`, and repeating them per image is how a set of prompts '
        f'starts disagreeing with itself.',
        '',
        '`State` is the visual-state matrix resolved for that scene — what is '
        'visibly true there — not a restatement of the anchors, which say what '
        'never changes.',
        '',
    ]
    if not entries:
        parts.extend([
            '_No illustrations are planned. Run `storyforge illustrate '
            '--plan`._', ''])
    for entry in entries:
        parts.extend([render_entry(entry), ''])
    return '\n'.join(parts).rstrip() + '\n'


# ============================================================================
# reference-images.md
# ============================================================================

def render_reference_images(*, references: list[tuple[str, str]]) -> str:
    """What to upload, in what order, and what each one is for.

    The files are **not copied** into the packet. Paths are project-relative
    from the project root, and the author uploads from disk — a copy inside the
    packet would be a second thing to invalidate every time a render is
    replaced.
    """
    return '\n'.join([
        '# Reference images',
        '',
        'These files are not copied into the packet. The paths below are '
        'relative to the project root; upload them from disk. A copy in here '
        'would be a second thing to invalidate every time a render is '
        'replaced.',
        '',
        pi.render_references_block(references),
        '',
        'Reference images carry style and likeness, which is why the entries '
        'in `illustrations.md` do not re-describe either. As illustrations are '
        'ingested they become references for the ones after them, so re-run '
        '`storyforge illustrate --package` after each batch of ingests to pick '
        'up the new ones.',
        '',
    ])


# ============================================================================
# acceptance.md
# ============================================================================

def render_acceptance(*, aspects: list[str]) -> str:
    """The checks that are identical for every image in the set.

    Everything here was deliberately moved *out* of the per-illustration
    entries: stating the orientation rule twenty times is twenty chances for
    one of them to be paraphrased away, and an entry that carries the whole
    house style is no longer thin.
    """
    orientation = '\n'.join(
        f'- {pi.orientation_clause(aspect)}'  # type: ignore[arg-type]
        for aspect in aspects) or f'- {pi.orientation_clause()}'

    return f"""# Acceptance criteria

Apply all of this to every image. It is stated once here rather than in each
entry, which is what keeps the entries short.

## Before you accept an image

1. **The beat.** The image shows what its entry's **Beat** says happens. Not
   the scene in general — that moment.
2. **In frame.** Everything the entry's **In frame** names is present and
   recognizable.
3. **Absent.** Nothing the entry's **Absent** line names appears anywhere in
   the image.
4. **State.** Every entity matches the entry's **State** line: the wardrobe,
   the lit or unlit thing, the damage. State is what changes on schedule, and
   getting it wrong is the single most common way an illustration contradicts
   the chapter it sits in.
5. **Likeness.** Every character, creature, place, and prop matches its anchor
   in `canon.md` — the same anchor the earlier images used.
6. **Colour logic.** The palette rules in `canon.md` hold. A colour that
   contradicts them is a reject even when the image is otherwise good: the
   palette is usually carrying meaning, and an off-palette object reads as a
   different kind of thing.
7. **Contrast.** The image does not repeat the staging of its neighbours — see
   the entry's **Contrast** line and the sequence rules below.
8. **No lettering.** {pi._NO_TEXT_CONSTRAINT.capitalize()}
9. **Orientation.** The image is in the orientation its entry names:

{orientation}

## Framing

Describe what *is* in the image, not what is missing — negated content keywords
leak into the render. ("A bare sill", not "no clutter on the sill.")

There are exactly three exceptions, and they are exceptions because positive
phrasing has been observed not to prevent them: the **Absent** line, a
violation of the stated **colour logic**, and the **orientation** directive.
Do not widen them into general prohibitions.

## Sequence rules

Twenty generation calls cannot see each other, so left alone they converge on
the same staging — and a set where three of the last four images are the same
shot reads the emotional peak as a lull, however good each image is on its own.

- No two adjacent images share camera distance *and* height.
- No two adjacent images share time of day and light direction unless the story
  requires it.
- Vary how much of the frame the subject occupies. A run of mid-distance
  two-figure compositions is the failure mode.
- Alternate interior and environmental framing across the sequence.
- Every fourth image: put it beside the previous three. If it could be
  mistaken for one of them, re-roll it rather than accept it.

## When an image fails a check

Re-roll it. A near-miss accepted early becomes the reference image every later
illustration inherits from, which is how one wrong lantern colour ends up in
the whole book.
"""
