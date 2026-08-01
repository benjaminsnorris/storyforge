"""The renderers for `manuscript/illustration-packet/`.

Deterministic assembly — no API calls, no timestamps. `--package` regenerates
the packet wholesale, so it is a render and never hand-edited, and two runs over
unchanged sources must produce identical bytes (there is a test).

Why a packet at all. Lived experience on a twenty-illustration book is that one
long-running session working from shared reference material beats twenty
independent hyper-detailed leaf prompts — the same conclusion GN reached in #260
when per-panel generation failed. So the shared files carry the house style, the
anchors, the state matrix, and every acceptance check identical across the set,
uploaded once at the top of a session.

**The author uploads files; they do not paste regions out of them (#306).** That
one fact governs `render_image_prompt` and is why `illustrations.md` exists in
the shape it does:

- Everything in an image prompt is for the model, or it is not in the file.
  There is no "below the line" an upload respects. The retired `--export`'s
  per-unit file was 13.9 KB of which 9.5 KB was seventeen paragraphs about canon
  staleness, sitting above a paste boundary an upload ignores.
- Everything addressed to the author — staleness, treatment, why a body is thin,
  which uploaded reference is this row's own old render — goes to
  `illustrations.md`, which is the file the author works down to pick what to
  generate next.

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
from typing import Final, get_args

from storyforge import illustrations as ill
from storyforge import prompts_illustrate as pi
from storyforge.packet import (
    BATCH_SLOTS, IMAGE_PROMPTS_SUBDIR, AnchorBatch, Entry, ImagePrompt,
    PacketContents, RenderNeeds, RenderState, StateGrid, anchor_block,
    ids_in_state, render_state,
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

def _render_uploads(references: list[tuple[str, str]],
                    notes: list[str]) -> str:
    """Step 1 of the runbook: what to upload, and what is missing from it.

    The paths are project-relative and the files are **not copied** into the
    packet. Two reasons, and the second is the one that settled it: a copy is a
    second thing to invalidate every time a render is replaced, and the author
    frequently works from a machine other than the one holding the repo — so a
    gitignored copy would be the one part of the bundle that does not travel,
    while `manuscript/assets/**` is tracked and therefore already there.

    `notes` is load-bearing, not decoration. A list that silently shrank to the
    cover — every prior render excluded as pre-canon, say — reads exactly like a
    book where nothing has been rendered yet, and the author then uploads the
    cover alone and generates the whole set with no likeness reference. It lives
    here rather than in a file of its own because this is the step it is about.
    """
    parts = [pi.render_references_block(references), '']
    if notes:
        parts.extend([
            '**Read this before you upload.** A short list is not the same as '
            'having little to reference.',
            '',
            '\n'.join(f'- {note}' for note in notes),
            '',
        ])
    parts.append(
        'These are uploaded **once**, at the top of the session, and every image '
        'prompt below refers to them by number. As illustrations are ingested '
        'they become references for the ones after them, so re-run `storyforge '
        'illustrate --package` after each batch of ingests to pick up the new '
        'ones.')
    return '\n'.join(parts)


def render_readme(*, title: str, contents: PacketContents,
                  entry_count: int, batch: AnchorBatch,
                  needs_render: RenderNeeds) -> str:
    """The runbook, the two phases, and what the packet cannot tell you."""
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
`reference/illustration-plan.csv`, `reference/visual-state.csv`,
`reference/canon/`, or the prompt bodies in `reference/illustration-prompts/`
instead, then regenerate.

## The files

| File | What it is |
|---|---|
| `README.md` | This file: the runbook, the two phases, and what the packet cannot tell you |
| `canon.md` | The reference tier — house style and the continuity anchors |
| `visual-state.md` | Scene x entity: what is visibly true when |
| `illustrations.md` | The index you work down, and everything addressed to you |
| `acceptance.md` | The checks that are the same for every image |
| `{IMAGE_PROMPTS_SUBDIR}/<id>.md` | One upload file per illustration |

## The session

**1. Upload the reference images.** Paths are relative to the project root.

{_render_uploads(contents['references'], contents['reference_notes'])}

**2. Upload `canon.md`.** The house style and every continuity anchor, read once
and kept in context. An anchor works because it is the *identical string* in
every image its entity appears in, so it is uploaded rather than restated per
illustration.

**3. Generate, one illustration at a time.** Upload
`{IMAGE_PROMPTS_SUBDIR}/<id>.md` and ask for the image.

**Upload them one at a time, not all at once.** A single small file is read
whole; twenty at once is the case where a model retrieves and paraphrases
instead, and a paraphrased continuity anchor is not an anchor.

Every file in `{IMAGE_PROMPTS_SUBDIR}/` is written for the image model and
contains nothing addressed to you — no staleness notes, no provenance, no
checklists. Everything that *is* addressed to you is in `illustrations.md`, so
read that row before you upload its prompt.

## Two phases

**Phase 1 — the anchor batch.** Render and approve these four first, then
`storyforge illustrate --ingest <dir>` them. They become reference images for
everything after, which is the difference between a set that agrees with itself
and twenty images that each invented their own version of a character.

{_render_batch(batch, needs_render)}

**Phase 2 — the churn.** Work `illustrations.md` top to bottom, generating each
row's image prompt in turn, then check the result against `acceptance.md` before
you accept it.

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

## Where the image prompts came from

Each `{IMAGE_PROMPTS_SUBDIR}/<id>.md` is assembled from the model-authored prose
in `reference/illustration-prompts/<id>.md` (written by `storyforge illustrate
--prompts`, or stood in for from the plan row when that file is missing), plus a
Constraints block re-derived from `reference/illustration-plan.csv` and
`reference/visual-state.csv` on every run. The constraints are re-derived rather
than inherited because a prompt body written before a matrix edit still carries
the old state, and a file containing both would contradict itself.
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

#: How a row's art reads in the index. Enumerated positively for `done`, so an
#: out-of-vocabulary `status` falls toward *pending*: reading a row that needed
#: no reading costs a glance, while skipping one because a typo made it look
#: finished loses an illustration from the book. `superseded` never reaches the
#: index — `rows_in_reading_order` drops it.
_RENDERED_STATUSES: Final[frozenset[ill.PlanStatus]] = frozenset(
    {'rendered', 'ingested'})

#: The `Art` cell per state. `re-render` and `done` sit on rows whose `status` is
#: identical, which is exactly why `status` cannot be the signal (#300).
_ART_CELLS: Final[dict[RenderState, str]] = {
    'done': 'done',
    'pending': 'to render',
    'stale': '**re-render**',
}

# Totality by assertion: a dict literal is not checked against its `Literal` key
# type, so a missing member type-checks clean and raises `KeyError` partway
# through writing the index table.
assert set(_ART_CELLS) == set(get_args(RenderState))


def _entry_state(entry: Entry) -> RenderState:
    """Which instruction this row carries, as one exhaustive answer.

    Canon-stale art is deliberately **not** `'done'`: it is the art that most
    needs regenerating, and a row saying `done` over it is what lets a session
    hand the set over unrendered. `--prompts` already excludes a pre-canon render
    from the reference chain, so the cost is not inherited drift — it is a churn
    with no likeness reference beyond the cover (#300).
    """
    if entry['stale_reason']:
        return 'stale'
    return ('done' if entry['status'] in _RENDERED_STATUSES else 'pending')


def _row_notes(entry: ImagePrompt) -> list[str]:
    """Everything addressed to the author about one illustration.

    Every one of these was a section of the retired export's per-unit file, above
    a paste boundary that an upload does not respect. They are collected here
    instead, in the file the author reads to choose what to generate next — which
    is also the moment any of them can still be acted on for free.
    """
    notes: list[str] = []
    if entry['stale_reason']:
        notes.append(
            # `stale_render_reason` is a clause, not a sentence — it ends
            # without punctuation because its other callers embed it mid-line.
            # Concatenated raw this rendered "...last updated 2026-07-28
            # Generate it again", which reads as a defect in the packet.
            f'**Re-render.** This illustration already has art, and '
            f'{entry["stale_reason"]}. Generate it again; leave `status` alone — '
            f'demoting it drops the illustration from the Bookshelf publish '
            f'manifest while the epub, the PDF, and the web book keep shipping '
            f'it.')
    if entry['body_warning']:
        notes.append(f'**Art direction.** {entry["body_warning"]}')
    elif (entry['body_source'] == 'prompt_file'
          and entry['prompt_source'] != ill.default_prompt_rel(entry['id'])):
        # Only when the path is *not* the convention. README states the
        # convention once, and it is identical for every row — noting it per row
        # would put every illustration in a section whose whole value is that it
        # holds only the ones worth reading. A declared `prompt_file` is the
        # case that genuinely differs, and the one an author editing the prose
        # would otherwise go looking for at the default path.
        notes.append(
            f'**Art direction.** From `{entry["prompt_source"]}`, which the '
            f'plan\'s `prompt_file` cell declares — not the default path.')
    if entry['self_reference']:
        notes.append(f'**Uploaded references.** {entry["self_reference"]}')
    if not entry['state']:
        notes.append(
            '**No visual state resolved.** The costume, the lighting, and any '
            'damage in this prompt are the model\'s inference rather than a read '
            'of the book\'s schedule. Add a transition to '
            '`reference/visual-state.csv`, or a `state_override` on the plan row '
            'if the state is true in this image only.')
    return notes


def _cell(value: str) -> str:
    """One table cell: never empty, never able to split the row.

    A pipe closes a markdown cell, so an unescaped one shifts every later value
    along by one column and drops the last — the shape `common.csv_safe` guards
    against in the unquoted pipe-delimited CSVs, in a different renderer.

    **Defence-in-depth, not a live path**, and worth saying so: the plan is
    itself pipe-delimited, `write_plan` sanitizes a pipe on the way out, and an
    extra one shatters the row on the way in — so no plan cell reaches here
    carrying one. What *is* live is the newline collapse (a hand-edited cell can
    hold one) and the em-dash default, which keeps an empty cell from closing
    early.
    """
    text = ' '.join((value or '').split())
    return text.replace('|', '\\|') if text else '—'


def render_illustrations(*, entries: list[ImagePrompt]) -> str:
    """The index the author works down — and the only place addressed to them.

    This file stopped describing images in #306. It used to carry an 80-120 word
    entry per illustration, derived from the plan row, while `--prompts`
    separately paid for a 250-400 word body that the packet ignored and merely
    pointed at. Two renderings of one row is how they come to disagree about a
    costume (#297); the body is now rendered once, into the upload file, and this
    file carries what a *human* needs: what is finished, what is stale, what is
    thin, and what to check.

    The 80-120 word budget went with the entries. It existed to stop the renderer
    restating what the shared sections already said, and there is nothing left to
    restate — the thing being rendered is a model-authored body that has no
    business being squeezed to 120 words.
    """
    parts = [
        '# The illustrations',
        '',
        f'{len(entries)} illustration(s), in reading order. Upload '
        f'`{IMAGE_PROMPTS_SUBDIR}/<id>.md` for the one you are generating; that '
        f'file is written for the image model and says nothing to you.',
        '',
        '**This file is the half addressed to you.** Read a row here before you '
        'upload its prompt: what is already rendered, what needs re-rendering, '
        'where the art direction is thin, and which of the uploaded reference '
        'images is that row\'s own earlier render.',
        '',
        '`Staging` is the treatment `--sequence` assigned so twenty independent '
        'generation calls stop converging on one shot. It is already embodied in '
        'the prompt body, and is repeated here so you can check that it is.',
        '',
    ]
    if not entries:
        parts.extend([
            '_No illustrations are planned. Run `storyforge illustrate '
            '--plan`._', ''])
        return '\n'.join(parts).rstrip() + '\n'

    parts.extend([
        '| # | Illustration | Scene | Aspect | Art | Staging | Beat |',
        '|---|---|---|---|---|---|---|',
    ])
    for position, entry in enumerate(entries, start=1):
        parts.append(
            f'| {position} | `{entry["id"]}` | `{entry["scene_id"] or "—"}` | '
            f'{entry["aspect"]} | {_ART_CELLS[_entry_state(entry)]} | '
            f'{_cell(entry["treatment"])} | {_cell(entry["beat"])} |')
    parts.append('')

    flagged = [(entry, _row_notes(entry)) for entry in entries]
    flagged = [(entry, notes) for entry, notes in flagged if notes]
    if not flagged:
        parts.extend([
            '## Before you upload',
            '',
            '_Nothing on any row needs reading first. That is a statement about '
            'the plan, the canon files, and the state matrix — not a promise '
            'that the art will be right._',
            '',
        ])
        return '\n'.join(parts).rstrip() + '\n'

    parts.extend([
        '## Before you upload',
        '',
        f'{len(flagged)} of {len(entries)} illustration(s) have something you '
        f'should know before generating them. The rest need no reading.',
        '',
    ])
    for entry, notes in flagged:
        parts.extend([f'### `{entry["id"]}`', ''])
        parts.extend([f'- {note}' for note in notes])
        parts.append('')
    return '\n'.join(parts).rstrip() + '\n'


# ============================================================================
# image-prompts/<id>.md
# ============================================================================

#: Headings an image prompt may carry. The four body sections come from the
#: model-authored prose (or `packet._derived_body`, which mirrors them), and
#: `Constraints` is appended deterministically.
#:
#: Enumerated so the invariant has something to be tested against: a regression
#: that reinstates an author-facing section here uploads it to an image model,
#: and nothing about the resulting image would look wrong.
IMAGE_PROMPT_SECTIONS: Final[tuple[str, ...]] = (
    'Scene', 'Subject', 'Important details', 'Use case', 'Constraints',
)


def render_image_prompt(*, prompt: ImagePrompt, title: str) -> str:
    """One illustration's upload file: the whole of it is for the image model.

    **The rule, and the reason it is a rule** (#306): the author uploads this
    file rather than pasting a region out of it, so anything in it reaches the
    model. Its predecessor marked a paste boundary and put four author-facing
    sections above it — on a real book, 9.5 KB of a 13.9 KB file, seventeen
    near-identical paragraphs about canon staleness. An upload ignores the
    boundary. So nothing addressed to the author goes in here; `_row_notes`
    collects all of it into `illustrations.md`.

    Size is a correctness property rather than tidiness. A small text file is
    read into context whole; at 14 KB an upload is near the size where retrieval
    and summarization begin, and a summarized continuity anchor is a paraphrased
    one — which defeats the identical-string mechanism the canon tier rests on.

    There is no `## Accept only if` block. #297 put the resolved state in the
    file twice on purpose — once as a Constraints bullet for the model, once as
    an acceptance line for the author — and the paste boundary is what made those
    two audiences instead of one. Uploading collapses them, so the second copy
    stopped being a check and became the longest string in the file repeated
    verbatim. `acceptance.md` says the per-image checks are these Constraints
    bullets; the check survives, the duplication does not.
    """
    constraints = pi.prompt_constraints(
        aspect=prompt['aspect'], state=prompt['state'],
        absent=prompt['absent'], contrast=prompt['contrast'])
    return '\n'.join([
        f'# {prompt["id"]} — {title}',
        '',
        f'Generate one image from this brief. {prompt["aspect"].capitalize()}, '
        f'{prompt["size"].replace("x", " × ")}, {prompt["quality"]} quality, '
        f'{prompt["model"]}. Return it as `{prompt["id"]}.png`.',
        '',
        prompt['body'].strip(),
        '',
        '## Constraints',
        '',
        '\n'.join(constraints),
        '',
    ])


# ============================================================================
# acceptance.md
# ============================================================================

#: Where each per-image field lives. One dict rather than the two the export
#: needed: the checks were always identical across bundles and only their
#: *pointers* differed, and there is one bundle now. The pointers name the
#: Constraints bullets because that is where every per-image field ends up — the
#: image prompt carries no separate acceptance block since #306, for the reason
#: `render_image_prompt` records.
_FIELD_HOMES: Final[dict[str, str]] = {
    'where': "each illustration's `%s/<id>.md`" % IMAGE_PROMPTS_SUBDIR,
    'beat': "the prompt's **Scene** and **Subject** sections",
    'in_frame': "the prompt's **Subject** section",
    'absent': "the prompt's `Not in this image:` constraint",
    'state': "the prompt's visual-state constraint",
    'contrast': "the prompt's `Set this image apart` constraint",
    'orientation': 'its prompt',
}


def render_acceptance(*, aspects: Sequence[pi.Aspect]) -> str:
    """The checks that are identical for every image in the set.

    Everything here was deliberately kept *out* of the per-illustration files:
    stating the orientation rule twenty times is twenty chances for one of them
    to be paraphrased away, and it is uploaded once per session anyway.

    Since #306 this is also where the per-image acceptance check lives. An image
    prompt used to carry its own `## Accept only if` block below a paste
    boundary; the author uploads the whole file now, so that block became the
    longest string in it repeated verbatim. The check did not go away — check the
    render against the prompt's own Constraints bullets, which is what the
    pointers below say.
    """
    homes = _FIELD_HOMES
    orientation = '\n'.join(
        f'- {pi.orientation_clause(aspect)}'
        for aspect in aspects) or f'- {pi.orientation_clause()}'

    return f"""# Acceptance criteria

Apply all of this to every image. It is stated once here, and uploaded once,
rather than repeated in {homes['where']} — which is what keeps those small
enough to be read whole rather than summarized.

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
