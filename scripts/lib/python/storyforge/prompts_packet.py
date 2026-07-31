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

import json
import re
from collections.abc import Sequence
from typing import Final, Literal

from storyforge import prompts_illustrate as pi
from storyforge.packet import (
    BATCH_SLOTS, AnchorBatch, Entry, PacketContents, RenderNeeds, RenderState,
    StateGrid, anchor_block, ids_in_state, render_state,
)

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

def _render_batch(batch: AnchorBatch, needs_render: RenderNeeds) -> str:
    """The four slots, marked for whether they are rendered, guesses disclosed.

    The disclosure is the load-bearing half. When `register` is unpopulated the
    darkest and brightest slots are guesses, and a guess presented as a choice
    is how an author finds out at image twenty that nothing in the book is the
    darkest image in the book.

    **`Rendered: yes` is a claim about the current canon, not about `status`.**
    A book whose twenty ingested renders all predated the canon governing them
    got a table of four `yes` rows, and a session working it top to bottom would
    have skipped phase 1 entirely (#300). A canon-stale slot reads `re-render`,
    and its reason is stated below the table because the row still says
    `ingested` everywhere else and an unexplained `re-render` reads as a bug in
    the packet.
    """
    cells: Final[dict[RenderState, str]] = {
        'done': 'yes', 'pending': 'not yet', 'stale': 're-render'}
    lines = ['| Slot | Illustration | Rendered |', '|---|---|---|']
    filled: list[str] = []
    for slot, label in BATCH_SLOTS:
        illus_id = batch[slot]  # type: ignore[literal-required]
        if not illus_id:
            lines.append(f'| {label} | _unfilled — see below_ | — |')
            continue
        filled.append(illus_id)
        lines.append(f'| {label} | `{illus_id}` | '
                     f'{cells[render_state(needs_render, illus_id)]} |')
    body = '\n'.join(lines)
    # Deduplicated: darkest and brightest can resolve to one illustration, and
    # one root cause stated twice is the noise #290 is about.
    stale = ids_in_state(needs_render, 'stale', filled)
    if stale:
        reasons = '\n'.join(f'- `{illus_id}`: {needs_render[illus_id]}'
                            for illus_id in stale)
        # Written out per number rather than assembled from inline ternaries.
        # This is the headline sentence of the phase-1 section, in the artifact
        # whose only product is credibility — "4 of these already has art" reads
        # as a defect in the packet, and the count is interpolated so the
        # `row(s)` convention the rest of the pipeline uses cannot apply here.
        if len(stale) == 1:
            claim = ('**1 of these already has art, and it does not follow the '
                     'canon in force now.** It is still `ingested`, so it still '
                     'ships in the book — but it is not a usable reference for '
                     'anything rendered from the current canon, so phase 1 is '
                     'not done until it is re-rendered and re-ingested:')
        else:
            claim = (f'**{len(stale)} of these already have art, and it does not '
                     f'follow the canon in force now.** They are still '
                     f'`ingested`, so they still ship in the book — but they are '
                     f'not usable references for anything rendered from the '
                     f'current canon, so phase 1 is not done until they are '
                     f're-rendered and re-ingested:')
        body += f'\n\n{claim}\n\n{reasons}'
    if batch['fallback']:
        disclosure = '\n'.join(f'- {note}' for note in batch['fallback'])
        # Counted as notes, not as slots: `fallback` also carries the
        # "brackets nothing" observation, which is about the batch as a whole
        # and would overstate a slot count by one.
        body += (f'\n\n**Read this before rendering the batch.** '
                 f'{len(batch["fallback"])} note(s) on how it was chosen — a '
                 f'guessed or unfilled slot is a decision waiting on you, not '
                 f'one already made:\n\n{disclosure}')
    return body

def render_readme(*, title: str, contents: PacketContents,
                  entry_count: int, batch: AnchorBatch,
                  needs_render: RenderNeeds) -> str:
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

**Phase 1 — the anchor batch.** Render and approve these four first, then
`storyforge illustrate --ingest <dir>` them. They become reference images for
everything after, which is the difference between a set that agrees with itself
and twenty images that each invented their own version of a character.

{_render_batch(batch, needs_render)}

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

#: Appended to the heading of an entry whose art already exists. The batch table
#: in README.md has always said which rows are rendered; the entries did not, and
#: an author told to work the file "top to bottom" would re-render finished art.
DONE_MARK: Final[str] = ' — already rendered'

#: Appended instead when art exists but predates the canon now governing it. The
#: opposite instruction from `DONE_MARK`, on a row whose `status` is identical —
#: which is exactly why `status` cannot be the signal (#300).
STALE_MARK: Final[str] = ' — re-render: the art predates the current canon'

#: Statuses that mean a file was made from this entry. Enumerated positively,
#: rather than as everything-but-the-pending-ones, so an out-of-vocabulary value
#: falls toward *pending*: reading an entry that did not need reading costs a
#: glance, while skipping one because a typo made it look finished loses an
#: illustration from the book. `superseded` never reaches an entry at all —
#: `rows_in_reading_order` drops it.
_RENDERED_STATUSES: Final[frozenset[str]] = frozenset({'rendered', 'ingested'})


def _entry_state(entry: Entry) -> RenderState:
    """Which instruction this entry carries, as one exhaustive answer.

    Replaces a `_is_rendered` predicate whose composite meaning ("rendered *and*
    current") its only caller had already discriminated — the `stale_reason`
    conjunct was dead by the elif ordering, so no test could reach it and a
    reader could take the predicate for the mechanism and reorder the caller.
    Mutual exclusion of the three marks is now structural.

    Canon-stale art is deliberately **not** `'done'`: it is the art that most
    needs regenerating, and an entry saying `do not regenerate` over it is what
    lets a session hand the set over unrendered. `--prompts` already excludes a
    pre-canon render from the reference chain, so the cost is not inherited drift
    — it is a churn with no likeness reference beyond the cover (#300).
    """
    if entry['stale_reason']:
        return 'stale'
    return ('done' if entry['status'] in _RENDERED_STATUSES else 'pending')


def render_entry(entry: Entry) -> str:
    """One illustration's entry — only what is specific to this image.

    An entry whose art exists is marked in two places (the heading and the
    metadata line) rather than one, because the heading is what a session
    skimming for the next thing to do actually reads.

    Sections with nothing in them are omitted rather than rendered empty,
    except `Beat` and `In frame`, which carry `packet.NOT_RECORDED` from
    `resolve` so a thin entry reads as thin instead of as terse.

    `Treatment` is this image's assigned place in the sequence's staging, from
    `--sequence`. It is per-image and cannot live in `acceptance.md`: the whole
    point is that it differs from the treatment of every other entry.

    `Absent` is one of the two deliberate exceptions to positive framing. #263
    established that negated content keywords leak into the render, and that
    holds for description; the exception is narrow and enumerable — named
    entities that must not appear, and violations of the stated colour logic
    (the latter lives in `acceptance.md`). Orientation and no-text are the
    other two exceptions.

    `Re-render` is bookkeeping, not derived content, and it is the one thing that
    pushes an entry past the budget — see
    `test_the_re_render_note_costs_only_its_own_lines`, which bounds it the way
    `DONE_MARK`'s test bounds the rendered marker. The entry is otherwise claiming
    to be finished, and the reason is what stops an unexplained instruction
    reading as a defect in the packet.
    """
    state = _entry_state(entry)
    mark, note = {
        'stale': (STALE_MARK, f' · **{entry["status"]}, but the art predates '
                              f'the current canon — re-render**'),
        'done': (DONE_MARK, f' · **{entry["status"]} — do not regenerate**'),
        'pending': ('', ''),
    }[state]
    lines = [
        f'### {entry["id"]}{mark}',
        '',
        f'- Scene: `{entry["scene_id"] or "—"}` · Layout: '
        f'{entry["layout"]} · Aspect: {entry["aspect"]}{note}',
    ]
    if state == 'stale':
        lines.extend(['', f'**Re-render.** {entry["stale_reason"]}'])
    lines.extend([
        '',
        f'**Beat.** {entry["beat"]}',
        '',
        f'**In frame.** {entry["in_frame"]}',
    ])
    for label, value in (('State', entry['state']),
                         ('Absent', entry['absent']),
                         ('Treatment', entry['treatment']),
                         ('Contrast', entry['contrast']),
                         ('This image also', entry['notes'])):
        if value:
            lines.extend(['', f'**{label}.** {value}'])
    return '\n'.join(lines)


def render_illustrations(*, entries: list[Entry]) -> str:
    """Every entry, in reading order.

    The header names the prompt-file convention and `--export` **once**, not per
    entry. The packet's own economy is that anything identical across the set is
    stated once, and both the path (`prompts/{id}.md`) and the command are
    identical for every row — so per-entry copies would spend the 80–120 word
    budget twenty times over on a sentence that never varies (#298).
    """
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
        'Where `storyforge illustrate --prompts` has been run, fuller '
        'scene-specific art direction for an illustration is in '
        '`manuscript/assets/illustrations/prompts/<id>.md`. These entries do '
        'not inline it: an entry that carried 300 words of prose would stop '
        'being thin, which is the one property this packet is built around. If '
        'you want the two halves in one paste-ready block, with the reference '
        'images copied in as files, run `storyforge illustrate --export` — that '
        'bundle is built for handing a single illustration over, and this one '
        'for working the set with `canon.md` in context.',
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

def render_reference_images(*, references: list[tuple[str, str]],
                            notes: list[str]) -> str:
    """What to upload, in what order, what each one is for, and what is missing.

    The files are **not copied** into the packet. Paths are project-relative
    from the project root, and the author uploads from disk — a copy inside the
    packet would be a second thing to invalidate every time a render is
    replaced.

    `notes` is load-bearing, not decoration. A list that silently shrank to the
    cover — every prior render excluded as pre-canon, say — reads exactly like a
    book where nothing has been rendered yet, and the author then uploads the
    cover alone and generates the rest of the set with no likeness reference.
    That is the drift this file exists to prevent.
    """
    parts = [
        '# Reference images',
        '',
        'These files are not copied into the packet. The paths below are '
        'relative to the project root; upload them from disk. A copy in here '
        'would be a second thing to invalidate every time a render is '
        'replaced.',
        '',
        pi.render_references_block(references),
        '',
    ]
    if notes:
        parts.extend([
            '## What is not in that list',
            '',
            'Read this before you upload. A short list is not the same as '
            'having little to reference.',
            '',
            '\n'.join(f'- {note}' for note in notes),
            '',
        ])
    parts.extend([
        'Reference images carry style and likeness, which is why the entries '
        'in `illustrations.md` do not re-describe either. As illustrations are '
        'ingested they become references for the ones after them, so re-run '
        '`storyforge illustrate --package` after each batch of ingests to pick '
        'up the new ones.',
        '',
    ])
    return '\n'.join(parts)


# ============================================================================
# acceptance.md
# ============================================================================

#: Where each per-image field lives, per bundle. The eight checks are identical
#: across both artifacts and are therefore written once — but they *point* at the
#: place the reader will find each field, and the packet's entries do not exist in
#: the export. Reusing the packet's wording verbatim there told a reader with no
#: repo to check the image against "the entry's Absent line", in a bundle whose
#: whole purpose is being readable without one.
_FIELD_HOMES: Final[dict[str, dict[str, str]]] = {
    'packet-entry': {
        'where': "its entry in `illustrations.md`",
        'beat': "its entry's **Beat**",
        'in_frame': "the entry's **In frame**",
        'absent': "the entry's **Absent** line",
        'state': "the entry's **State** line",
        'contrast': "the entry's **Contrast** line",
        'orientation': 'its entry',
    },
    'export-prompt': {
        'where': "that illustration's `prompt.md`",
        'beat': "the prompt's **Scene** and **Subject** sections",
        'in_frame': "the prompt's **Subject** section",
        'absent': "the prompt's `Not in this image:` constraint",
        'state': "the prompt's visual-state constraint",
        'contrast': "the prompt's `Set this image apart` constraint",
        'orientation': 'its prompt',
    },
}

#: Which bundle `render_acceptance` is writing for.
AcceptanceSource = Literal['packet-entry', 'export-prompt']


def render_acceptance(*, aspects: Sequence[pi.Aspect],
                      source: AcceptanceSource = 'packet-entry') -> str:
    """The checks that are identical for every image in the set.

    Everything here was deliberately moved *out* of the per-illustration
    entries: stating the orientation rule twenty times is twenty chances for
    one of them to be paraphrased away, and an entry that carries the whole
    house style is no longer thin.

    `source` selects the vocabulary for the per-image fields — see
    `_FIELD_HOMES`. One renderer, one list of checks, two sets of pointers,
    because the checks genuinely are the same and only their homes differ.
    """
    homes = _FIELD_HOMES[source]
    orientation = '\n'.join(
        f'- {pi.orientation_clause(aspect)}'
        for aspect in aspects) or f'- {pi.orientation_clause()}'

    return f"""# Acceptance criteria

Apply all of this to every image. It is stated once here rather than in
{homes['where']}, which is what keeps those short.

## Before you accept an image

1. **The beat.** The image shows what {homes['beat']} says happens. Not
   the scene in general — that moment.
2. **In frame.** Everything {homes['in_frame']} names is present and
   recognizable.
3. **Absent.** Nothing {homes['absent']} names appears anywhere in
   the image.
4. **State.** Every entity matches {homes['state']}: the wardrobe,
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
   {homes['contrast']} and the sequence rules below.
8. **No lettering.** {pi._NO_TEXT_CONSTRAINT.capitalize()}
9. **Orientation.** The image is in the orientation {homes['orientation']} names:

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


# ============================================================================
# The sequence pre-pass
# ============================================================================
#
# Measured evidence, not a hunch: of twenty renders for the real book, LF-05,
# LF-18, LF-19 and LF-20 are all "two children kneeling around a lit lamp", and
# the original review of that set independently reported "three of the last four
# images are the same shot". Twenty independent generation calls cannot see each
# other, so each prompt is individually good and the set is monotonous.
#
# The fix is NOT one call that writes all twenty prompts. That was considered and
# rejected for three concrete reasons: retry granularity (one failure becomes
# twenty), output quality (a long response gets terser and more formulaic toward
# the end, so the last illustrations get the worst prompts), and parsing (one
# malformed heading eats several prompts). Instead: one cheap call that sees
# every row's beat and layout — never the scene prose — and assigns each a
# distinct treatment.

#: The axes a treatment must vary. Named in the request and in the packet so the
#: vocabulary stays comparable across rows; a free-text "make it different"
#: produces adjectives that cannot be checked against each other.
TREATMENT_AXES: Final[tuple[str, ...]] = (
    'camera distance', 'camera height', 'time of day',
    'how much of the frame the subject occupies',
    'interior versus environmental',
)


def build_sequence_request(*, rows: list[dict[str, str]],
                           story_context: str) -> str:
    """Build the one call that assigns a distinct treatment to every row.

    Beats and layouts only. The scene prose is deliberately withheld: this pass
    is about how the *set* is staged, and a model given the prose starts
    art-directing individual images instead — which is what the per-illustration
    pass already does, better, with the reference tier in front of it.
    """
    listing = json.dumps([
        {
            'id': row['id'].strip(),
            'scene_id': (row.get('scene_id') or '').strip(),
            'layout': (row.get('layout') or '').strip(),
            'beat': (row.get('beat') or '').strip(),
            'register': (row.get('register') or '').strip(),
            'existing_treatment': (row.get('treatment') or '').strip(),
        }
        for row in rows
    ], indent=2)

    axes = '\n'.join(f'- **{axis}**' for axis in TREATMENT_AXES)

    return f"""You are staging a book's interior illustrations as a *sequence*.

Each of these illustrations will be generated by a separate call that cannot see
any of the others. Left alone, those calls converge: on the last real book, four
of twenty images were the same shot of the same two figures at the same
distance, each prompt individually fine and the set monotonous. Your job is to
prevent that before a single image is generated.

## Story context

{story_context}

## The illustrations, in reading order

Beats and layouts only — you are staging the sequence, not art-directing the
images. Something else does that, with the reference tier in front of it.

```json
{listing}
```

## What a treatment is

One short phrase, at most about twelve words, fixing this image's place along
these axes:

{axes}

Two adjacent images must not share camera distance *and* height. A run of
mid-distance two-figure compositions is the failure mode to design away from.
Let the register and the layout pull: a `double_page` spread wants scale, a
row marked `darkest` or `brightest` is a lighting extreme and should look like
one.

A row with a non-empty `existing_treatment` was set by the author. Return it
unchanged, and stage the others around it.

## Output

Return JSON only, in this exact shape, with one object per illustration:

```json
{{
  "treatments": [
    {{
      "id": "the-id-from-the-data",
      "treatment": "close, low angle, interior, night, subject fills the frame"
    }}
  ]
}}
```

No two treatments may be identical. If two images genuinely want the same
staging, say so in the second one's treatment ("deliberate echo of <id>, but
from the opposite side") so the repetition is a decision rather than an
accident.
"""


def parse_sequence_response(text: str) -> tuple[list[dict[str, str]], str]:
    """Extract the `treatments` list. Returns (treatments, status).

    Status is 'ok', 'no_treatments_key', or 'no_json' — the same three-value
    discipline as `parse_selection_response`, so the caller can tell "the model
    answered something we could not read" from "the model answered nothing".
    Rows missing an id or a treatment are dropped here and *counted* by the
    caller, which reports them.
    """
    def _take(obj) -> list[dict[str, str]] | None:
        if not isinstance(obj, dict):
            return None
        inner = obj.get('treatments')
        if not isinstance(inner, list):
            return None
        return [
            {'id': str(item.get('id', '')).strip(),
             'treatment': str(item.get('treatment', '')).strip()}
            for item in inner
            if isinstance(item, dict) and str(item.get('id', '')).strip()
            and str(item.get('treatment', '')).strip()
        ]

    parsed_any = False
    for candidate in _sequence_json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        parsed_any = True
        out = _take(parsed)
        if out:
            return out, 'ok'
    return [], 'no_treatments_key' if parsed_any else 'no_json'


def _sequence_json_candidates(text: str):
    """Yield progressively looser JSON candidates from a model response.

    Same three attempts as `prompts_illustrate._json_candidates`; kept local
    rather than importing a private helper across modules.
    """
    yield text
    fenced = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if fenced:
        yield fenced.group(1).strip()
    braced = re.search(r'\{.*\}', text, re.DOTALL)
    if braced:
        yield braced.group(0)


def render_sequence_checklist(*, rows: list[dict[str, str]]) -> str:
    """Strict coaching: the rows, the axes, and no proposals.

    A treatment is a compositional proposal, which strict coaching does not
    make. What it can do is lay the sequence out so the author can see the
    convergence risk and fill the column themselves.
    """
    axes = '\n'.join(f'- {axis}' for axis in TREATMENT_AXES)
    lines = [
        '# Sequence staging checklist',
        '',
        f'{len(rows)} illustration(s), in reading order. Fill the `treatment` '
        f'column in `reference/illustration-plan.csv` for each one. Twenty '
        f'independent generation calls cannot see each other, so without this '
        f'they converge on the same staging.',
        '',
        'Fix each image along these axes, in about a dozen words:',
        '',
        axes,
        '',
        'No two adjacent images should share camera distance *and* height, and '
        'no two treatments in the book should be identical.',
        '',
        '| # | Illustration | Layout | Register | Beat | Treatment |',
        '|---|---|---|---|---|---|',
    ]
    for index, row in enumerate(rows, 1):
        lines.append(
            f'| {index} | `{row["id"].strip()}` '
            f'| {(row.get("layout") or "").strip() or "—"} '
            f'| {(row.get("register") or "").strip() or "—"} '
            f'| {(row.get("beat") or "").strip() or "—"} '
            f'| {(row.get("treatment") or "").strip() or "_(fill in)_"} |')
    lines.append('')
    return '\n'.join(lines)


def render_sequence_brief(*, rows: list[dict[str, str]],
                          proposed: dict[str, str]) -> str:
    """Coach coaching: the proposals, for the author to accept or rewrite.

    Nothing is written to the plan — the author decides, which is what coach
    level means, and the column is a one-line copy either way.
    """
    lines = [
        '# Sequence staging — proposed',
        '',
        f'{len(proposed)} treatment(s) proposed for {len(rows)} illustration(s).'
        f' Nothing has been written to the plan. Copy the ones you agree with '
        f'into the `treatment` column of `reference/illustration-plan.csv`, and '
        f'rewrite the ones you do not.',
        '',
        '| Illustration | Proposed treatment | Already set |',
        '|---|---|---|',
    ]
    for row in rows:
        illus_id = row['id'].strip()
        existing = (row.get('treatment') or '').strip()
        lines.append(f'| `{illus_id}` | {proposed.get(illus_id) or "—"} '
                     f'| {existing or "—"} |')
    lines.append('')
    return '\n'.join(lines)


def duplicate_treatments(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    """Treatments shared by more than one row, mapped to the ids sharing them.

    Variety is the entire purpose of the pass, so identical treatments defeat it
    — silently, because each individual prompt still looks fine. Compared
    case-insensitively on collapsed whitespace: two treatments differing only in
    capitalisation are the same instruction.
    """
    seen: dict[str, list[str]] = {}
    for row in rows:
        treatment = ' '.join((row.get('treatment') or '').lower().split())
        if not treatment:
            continue
        seen.setdefault(treatment, []).append(row['id'].strip())
    return {treatment: ids for treatment, ids in seen.items() if len(ids) > 1}
