"""What goes into the illustration handoff packet, and proof the copies are exact.

Resolution and validation only: `prompts_packet.py` renders, `cmd_illustrate
--package` writes, and nothing here calls a model. The split exists because the
two invariants of the packet are checkable properties of the *data*, and both
have to be assertable without going through a renderer:

1. **An anchor copied into the packet is byte-identical to its canon source.**
   Likeness continuity across separately generated images is nothing more than
   every prompt sending the same bytes, so `resolve` hands anchors through from
   `canon.anchor_texts` untouched — no strip, no rewrap, no re-labelling — and
   `anchor_copy_drift` reads the *written* packet back and compares it to the
   source. Two checks on two different paths: the first catches a transform
   during resolution, the second one during rendering, and only the second
   would catch a renderer that wraps or re-indents a long anchor.

2. **The packet never claims coverage it does not have.** It is a document an
   author works from for hours, assembled from data that may be incomplete, so
   every hole is collected into `gaps` as it is found and rendered *into* the
   packet rather than logged once and lost. A thin entry, an entity nobody
   stated a visual state for, a book-level canon file that is still a scaffold,
   and an audit that never ran are all coverage facts the author needs while
   they are working, not twenty minutes earlier.

`entry_for` is where `state_for_row`, `contrast_for_row` and
`ill.stale_render_reason` are applied, and it is the **only** rendering of a plan
row in the pipeline (#306). That was the point of sharing it with the retired
export, and collapsing to one bundle makes #297's guarantee structural rather
than conventional: two renderings of a row is how they come to disagree about a
costume, and there is now one.

See benjaminsnorris/storyforge#278 and
docs/superpowers/specs/2026-07-28-illustration-state-matrix-and-packet-design.md.
"""

import os
import re
from collections.abc import Iterable
from typing import (TYPE_CHECKING, Final, Literal, NamedTuple,
                    TypedDict, cast)

from storyforge import canon
from storyforge import illustrations as ill
from storyforge import prompts_illustrate as pi
from storyforge import visual_state as vs
from storyforge.common import log, normalize_for_comparison

if TYPE_CHECKING:  # pragma: no cover - typing only
    # `cmd_illustrate` imports this module, so the real type cannot be imported
    # at module scope; only the annotation needs it.
    from storyforge.cmd_illustrate import StyleReference

#: Project-relative home of the packet. Under `manuscript/` because it is a
#: production artifact like the assembled chapters, not reference material the
#: author edits — `--package` regenerates it wholesale.
PACKET_DIR = os.path.join('manuscript', 'illustration-packet')

#: The root files, in the order `--package` writes and reports them.
#:
#: `reference-images.md` was one of them until #306. Its upload list and its
#: exclusion disclosures both moved into README.md, beside the step of the
#: runbook where the author acts on them — sending a reader out of the runbook
#: and back is the fragmentation the merge exists to remove.
PACKET_FILES: tuple[str, ...] = (
    'README.md', 'canon.md', 'visual-state.md', 'illustrations.md',
    'acceptance.md',
)

#: Files earlier versions wrote at the packet root and this one does not.
#: `--package` deletes them, because a leftover is a second, stale answer to a
#: question the current packet already answers — and a packet is a render, so
#: nothing in it should outlive the run that wrote it.
RETIRED_PACKET_FILES: tuple[str, ...] = ('reference-images.md',)

# A name in both would have one `--package` run delete a file it just wrote, or
# write one it just deleted, depending on call order — and the removal logs
# "its contents are in README.md now" about a file that is present.
assert not set(PACKET_FILES) & set(RETIRED_PACKET_FILES), \
    'a packet file cannot be both written and deleted by one run'

#: Where the per-illustration upload files go. `image-prompts/`, not `prompts/`,
#: because the model-authored bodies live at
#: `reference/illustration-prompts/{id}.md` with identical basenames: two
#: directories called `prompts/` both holding `LF-05.md`, one a durable record
#: and one a render, is a coin flip at the moment the author is picking a file to
#: upload.
IMAGE_PROMPTS_SUBDIR: Final[str] = 'image-prompts'

#: Where an image prompt's body came from. Never a silent fallback: a block
#: assembled from three plan cells reads exactly like a complete prompt, so
#: `illustrations.md` says which rows are in this state and `README.md`
#: aggregates the cause.
BodySource = Literal['prompt_file', 'plan_row']

#: The pixel size each aspect is generated at, stated in the image prompt so a
#: render is reproducible two weeks later. GPT Image 2's portrait and landscape
#: shapes; `orientation_clause` states the same ratios in prose, because the
#: model reads the prose and not the numbers.
SIZES: dict[pi.Aspect, str] = {
    'portrait': '1024x1536',
    'landscape': '1536x1024',
    'square': '1024x1024',
}

#: Stated rather than chosen per row. Interior art is the one part of a book that
#: cannot be fixed in proof, and the cost difference is a few cents against a
#: re-render.
QUALITY: Final[str] = 'high'

#: What an entry says in place of a field the plan never filled. An entry that
#: silently omitted the line would read as "nothing to say here" rather than
#: "nobody wrote this down", and the difference is the whole coverage contract.
NOT_RECORDED = '_(not recorded — see the gaps in README.md)_'


class Entry(TypedDict):
    """One shared derivation of a plan row, consumed twice.

    `illustrations.md`'s index reads the author-facing half — `_entry_state`
    over `status` and `stale_reason`, the `Staging` and `Beat` columns — and
    `ImagePrompt` carries the model-facing half into the upload's Constraints
    block.

    **There is no longer a word budget.** `render_entry` enforced 80–120 words
    of derived content and both went with #306: there is one rendering of a row
    now, so there is nothing to restate, and the thing being rendered is a
    model-authored body that has no business being squeezed to 120 words.

    Everything identical across the set lives in `canon.md` and
    `acceptance.md` instead — the colour prohibitions, the orientation rule,
    no lettering. `state` stays here because it is a *resolution* of the
    visual-state matrix for one scene, not a duplication of the matrix.
    """
    id: str
    scene_id: str
    #: The plan row's status, typed to the vocabulary `validate_plan` gates.
    #: Carried so an entry for finished art cannot look identical to one for
    #: pending work: the documented flow renders the anchor batch, ingests it,
    #: and regenerates, so the normal mid-flight packet mixes the two while
    #: README tells the author to work the file top to bottom.
    status: ill.PlanStatus
    layout: str
    #: From `pi.aspect_for_row`, which returns the vocabulary rather than a raw
    #: cell — so no `cast` here, unlike `status`. Typed because a consumer indexes
    #: a per-aspect table with it (`SIZES`), where an out-of-vocabulary
    #: value would be a KeyError partway through writing a bundle.
    aspect: pi.Aspect
    #: One sentence: what happens in this image. Rendered in `illustrations.md`'s
    #: index so two illustrations in one scene are distinguishable at a glance,
    #: which a scene id alone cannot do. Carries `NOT_RECORDED` when the plan
    #: never filled it, so a thin row reads as thin rather than as terse.
    beat: str
    state: str
    absent: str
    #: **Model-facing, and free of illustration ids** — see `RowContrast`. Named
    #: plainly because it is what `prompt_constraints` renders into the upload,
    #: and the id-bearing form is the one that needs qualifying.
    contrast: str
    #: The same direction with ids intact, for the author-facing acceptance block
    #: and `illustrations.md`.
    contrast_for_author: str
    #: The author's own sentences held back from `contrast` because they name
    #: another illustration. Disclosed rather than dropped.
    contrast_withheld: str
    notes: str
    #: This image's place in the sequence's staging — camera distance and
    #: height, time of day, how much of the frame the subject occupies,
    #: interior versus environmental. Written by `--sequence` or by the author.
    treatment: str
    #: Why the art this row already claims no longer follows the canon. '' means
    #: only that this check found nothing to say — the art is current, no art
    #: exists yet, or the row is `rendered` and carries no date to judge. `status`
    #: alone cannot answer the question, and an
    #: entry marked `ingested — do not regenerate` over art the canon has since
    #: outgrown tells a session to skip the one image it must redo (#300).
    stale_reason: str


class ImagePrompt(Entry):
    """One illustration's upload file: everything, and only what, the image model
    should read.

    The rule this type exists to enforce (#306): **everything in an image prompt
    is for the model, or it is not in the file.** The author uploads it rather
    than pasting a marked region out of it, so there is no "below the line" — a
    section addressed to the author reaches the image model. The retired export's
    per-unit file was 13.9 KB of which 9.5 KB was seventeen paragraphs about
    canon staleness, all of it above a paste boundary that an upload ignores.

    So the author-facing halves of a row live on `Entry` and render into
    `illustrations.md`: `stale_reason`, `treatment`, `notes`, and `body_warning`
    below. What this subclass adds is the model-facing half.
    """
    model: str
    size: str
    quality: str
    #: The model-authored prose, or the plan-derived stand-in. Never '': a row
    #: with nothing written says so in `illustrations.md` and still renders a
    #: usable shape here.
    body: str
    body_source: BodySource
    #: The prompt file consulted for `body`, whether or not it yielded prose.
    #: Recorded even when nothing was read from it, so a file appearing at the
    #: default path is noticed rather than silently ignored.
    prompt_source: str
    #: Why this body is thinner than it looks, '' when there is nothing to say.
    #: Rendered into `illustrations.md` — **never** into the image prompt, which
    #: is the whole point of the type.
    body_warning: str
    #: The shared root cause behind `body_warning`, for README's `cause -> ids`
    #: aggregation. '' when `body_warning` is ''.
    body_cause: str
    #: Set when this illustration's own earlier render is in the book-level
    #: upload list. `_references_for` excludes a row from its own chain, and a
    #: per-row chain is what the export had; one list uploaded once cannot make
    #: that exclusion, so the row is told about it instead. Author-facing, so it
    #: renders in `illustrations.md`.
    self_reference: str


class PacketContents(TypedDict):
    """Everything the renderers need, plus the record of what is missing."""
    book_level: dict[str, str]
    anchors: dict[str, str]
    entries: list[ImagePrompt]
    references: list[tuple[str, str]]
    #: Why the reference list is shorter than the ingested art suggests, or is
    #: not what the author approved — canon-excluded renders, `--no-prior-refs`,
    #: the prior-illustration cap, an anchor-batch member whose art exists and
    #: cannot be used, and a cover-only or empty chain. Rendered beneath the list in
    #: README's upload step, because a list that silently shrank to the cover
    #: reads as "nothing is ingested yet" and the author then uploads the cover
    #: alone.
    reference_notes: list[str]
    gaps: list[str]


class RowContext(TypedDict):
    """Everything `state_for_row` and `contrast_for_row` need, read once.

    Exists so `--prompts` and `--package` resolve a row's visual state through
    the *same* code over the *same* inputs. They did not, and the divergence was
    not cosmetic: the packet's `**State.**` line said pajamas while the prompt
    file for the same row said jacket and boots, because `--prompts` never
    received the matrix at all and the model inferred a costume from anchor
    prose describing the whole book (#297).

    Named for the row rather than the state because `predecessors` serves
    `contrast_for_row`, and a type called `StateContext` carrying a
    contrast-only field is how the next reader concludes their addition needs
    its own bag.
    """
    anchors: dict[str, str]
    labels: dict[str, canon.AnchorLabel]
    #: Reading position per scene, from the chapter map.
    order: dict[str, int]
    #: Active scene ids, so a cut scene is distinguishable from an unmapped one.
    known: set[str]
    transitions: list[vs.Transition]
    #: Reading-order predecessor per illustration id, '' for the first. What
    #: `contrast_for_row` needs, and the reason both callers must read reading
    #: order rather than render order. A row **absent** from this map is not the
    #: first illustration — see `contrast_for_row`.
    predecessors: dict[str, str]
    #: Every id the plan declares, **including `superseded` rows** — so this is
    #: not `set(predecessors)`, which is reading order and excludes them.
    #: `contrast_for_row` matches author prose against it to decide which
    #: sentences name another illustration and must not reach the image model
    #: (#305). Matching known ids rather than a generic pattern is what keeps
    #: ordinary words out of it: a plan id may be as plain as `a10`.
    plan_ids: set[str]
    #: Newest `canon_updated` across reference/canon/, read once so the canon
    #: tree is not walked per row (and its unparseable-date WARNING not logged
    #: per row). '' when no canon file carries a parseable date, which means
    #: nothing can be judged stale.
    canon_cutoff: str


#: Kept so a name other modules may already import does not silently vanish.
#: Same type; `RowContext` is what new code should say.
StateContext = RowContext


def state_context(project_dir: str, *,
                  plan: list[dict[str, str]] | None = None,
                  canon_cutoff: str | None = None) -> RowContext:
    """Read the canon tier, the chapter map, the transition log, and the plan once.

    `plan` must be the **whole** plan, never an `--ids` subset: `predecessors` is
    a statement about reading order across the book, and a one-row plan would
    make that row its own book-start and strip its contrast clause. Passed in so
    the reading order comes from the same `read_plan` the caller iterates rather
    than from a second read that could differ.

    Reading order excludes `superseded` rows, so a row revived through
    `--prompts --ids` is **absent** from `predecessors` rather than mapped to '';
    `contrast_for_row` is what keeps those two apart.
    """
    order = ill._scene_order(project_dir)
    # Read once and hand the same list to `rows_in_reading_order`: `read_plan`
    # logs per malformed row, so a second read would report one broken row twice
    # — the defect the canon walk-count test exists for.
    rows = ill.read_plan(project_dir) if plan is None else plan
    plan_ids = {r.get('id', '').strip() for r in rows if r.get('id', '').strip()}
    predecessors: dict[str, str] = {}
    previous = ''
    for row in rows_in_reading_order(project_dir, plan=rows, order=order):
        illus_id = row['id'].strip()
        # setdefault, not assignment: two rows sharing an id would otherwise
        # leave only the later one's predecessor, where the old in-loop
        # accumulator gave each row its own. `run_package` deliberately skips
        # `validate_plan`, so nothing upstream gates a duplicate id.
        predecessors.setdefault(illus_id, previous)
        previous = illus_id
    return {
        'anchors': canon.anchor_texts(project_dir),
        'labels': canon.anchor_display_names(project_dir),
        'order': order,
        'known': vs.known_scene_ids(project_dir),
        'transitions': vs.read_transitions(project_dir),
        'predecessors': predecessors,
        'plan_ids': plan_ids,
        'canon_cutoff': (canon.newest_canon_updated(project_dir)
                         if canon_cutoff is None else canon_cutoff),
    }


class StateGrid(TypedDict):
    """The dense scene x entity view derived from the sparse transition log.

    Derived into the packet rather than stored under `reference/` so there is
    no second file to keep fresh — the same reasoning `reference/outline.md`
    follows for the expanding outline.
    """
    entities: list[str]
    scenes: list[str]
    cells: dict[str, dict[str, str]]
    #: Active scenes the chapter map cannot position, so no column of the grid
    #: can speak for them. Named because a grid that silently omitted five
    #: freshly drafted scenes would read as coverage.
    unpositioned: list[str]


def packet_dir(project_dir: str) -> str:
    """Absolute path to the packet directory, whether or not it exists."""
    return os.path.join(project_dir, PACKET_DIR)


def packet_file(project_dir: str, name: str) -> str:
    """Absolute path to one packet file."""
    return os.path.join(packet_dir(project_dir), name)


def image_prompts_dir(project_dir: str) -> str:
    """Absolute path to the image-prompt directory, whether or not it exists."""
    return os.path.join(packet_dir(project_dir), IMAGE_PROMPTS_SUBDIR)


def image_prompt_file(project_dir: str, illus_id: str) -> str:
    """Absolute path to one illustration's upload file.

    The id reaches a path, so it is checked here rather than trusted. The plan is
    a documented hand-edit surface, `run_package` deliberately does not call
    `validate_plan`, and `--package` clears this directory — so an id of
    `../../evil` would escape the packet tree and take a directory nobody named
    with it. Raising is the only behaviour that cannot be bypassed by a later
    caller forgetting to check first (#298's lesson, kept).
    """
    if not ill._ID_RE.match(illus_id):
        raise ValueError(
            f'illustration id {illus_id!r} is not a legal id, so it cannot name '
            f'a file in {PACKET_DIR}/{IMAGE_PROMPTS_SUBDIR}/. Fix the `id` cell '
            f'in reference/{ill.PLAN_FILENAME}.')
    return os.path.join(image_prompts_dir(project_dir), f'{illus_id}.md')


def is_built(project_dir: str) -> bool:
    """True when every packet root file exists.

    All of them or none: a half-written packet is a partial handoff, and
    reporting it as built is how an author hands over a bundle with no
    acceptance criteria in it.

    **Keyed on the root files only, and `--package` writes `image-prompts/`
    first.** Writing the root files first would flip this True at the moment the
    packet was emptiest, so an interrupted run left `--diagnose` printing "built
    and current" over a directory with nothing to upload in it. The window is
    closed by the write order rather than by widening the predicate, because a
    packet legitimately has no image prompts when the plan has no rows.
    """
    return all(os.path.isfile(packet_file(project_dir, name))
               for name in PACKET_FILES)


# ============================================================================
# Resolution
# ============================================================================

def rows_in_reading_order(project_dir: str, *,
                          plan: list[dict[str, str]] | None = None,
                          order: dict[str, int] | None = None,
                          ) -> list[dict[str, str]]:
    """Live plan rows in the order a reader meets them.

    Reading order, not render order: `render_order` deliberately hoists the
    visual key to the front, which is right for producing the art and wrong for
    deciding what an illustration's neighbours are. One function so the entries,
    the contrast lines, and the anchor batch cannot end up disagreeing about
    which illustration comes first.

    `plan` and `order` let a caller that has already read them pass them in, so
    one packet build parses `chapter-map.csv` once instead of three times.
    """
    if order is None:
        order = ill._scene_order(project_dir)
    rows = [row for row in (plan if plan is not None
                            else ill.read_plan(project_dir))
            if (row.get('status') or '').strip() != 'superseded']
    return sorted(rows, key=lambda r: (
        order.get((r.get('scene_id') or '').strip(), ill._SORTS_LAST),
        r['id'].strip()))


#: Illustration id -> why it still needs a render, in reading order. An empty
#: reason means no art exists for it yet; a non-empty one means art exists and
#: predates the canon that now governs it, and *is the sentence shown to the
#: author*. Absent from the mapping is the only shape that means done.
RenderNeeds = dict[str, str]

#: What `render_state` answers. `'done'` is the only one that means leave it be.
RenderState = Literal['done', 'pending', 'stale']


def render_state(needs: RenderNeeds, illus_id: str) -> RenderState:
    """Which of the three states this illustration is in.

    **The single place `in` versus `.get()` is decided.** `RenderNeeds` encodes
    three states over two levels, so every consumer that spelled the check by
    hand had to get that distinction right independently — and `needs.get(id)`
    read as "done" collapses *pending* into *done*, which is #300 exactly, at the
    call site (`_report_packet_rung`) that is the go/no-go on a paid render run.
    Five hand-written copies of a discrimination whose failure mode is the bug
    the discrimination exists to fix is one too many.
    """
    if illus_id not in needs:
        return 'done'
    return 'stale' if needs[illus_id] else 'pending'


def ids_in_state(needs: RenderNeeds, state: RenderState,
                 among: Iterable[str] | None = None) -> list[str]:
    """Ids in *state*, deduplicated, in `needs` order (or `among`'s order).

    `among` narrows to a subset — the anchor batch's four slots, where two slots
    can resolve to one illustration and a naive list would name it twice.
    """
    source = list(needs) if among is None else list(dict.fromkeys(among))
    return [i for i in source if render_state(needs, i) == state]


def needs_render(project_dir: str, *,
                 plan: list[dict[str, str]] | None = None,
                 canon_cutoff: str | None = None) -> RenderNeeds:
    """Which illustrations still need a render, and why, in reading order.

    **Not a status check.** `status == 'ingested'` says a file was filed, not
    that the file follows the canon in force now — and a run that read it that
    way contradicted itself out loud: `cmd_illustrate._references_for` excluded
    every one of a book's twenty ingested renders as pre-canon while the anchor
    batch reported four of them `Rendered: yes` and README declared phase 1
    complete (#300). One predicate, `ill.stale_render_reason`, so the two halves
    of a run cannot answer the question differently.

    `status` is deliberately *not* consulted as the fix for that: demoting a
    canon-stale row to make the packet honest drops it from the Bookshelf publish
    manifest (`ill.manifest_assets` skips a non-`ingested` row) while the epub,
    the PDF, and the web book keep shipping it (`ill.resolve_for_local` excludes
    only `superseded`) — so the editions disagree about art the author believes
    they retired. Needing a re-render and being publishable are different facts
    and now have different homes.

    `plan` must be the **whole** plan, for a sharper version of the reason
    `state_context` says so: every id *absent* from the result reads as finished,
    so a subset plan reports every row it omitted as done — #300's exact shape.
    `canon_cutoff` lets a caller that has already read the canon tree pass its
    answer, so one command does not walk it (and re-log its unparseable-date
    WARNING) several times.
    """
    if canon_cutoff is None:
        canon_cutoff = canon.newest_canon_updated(project_dir)
    needs: RenderNeeds = {}
    for row in rows_in_reading_order(project_dir, plan=plan):
        illus_id = row['id'].strip()
        if (row.get('status') or '').strip() != 'ingested':
            needs[illus_id] = ''
            continue
        reason = ill.stale_render_reason(row, canon_cutoff)
        if reason:
            needs[illus_id] = reason
    return needs


def resolve(project_dir: str, *,
            canon_cutoff: str | None = None,
            batch: AnchorBatch | None = None) -> PacketContents:
    """Collect what the packet says, recording every gap rather than filtering.

    Reads the canon tier (phase 1), the visual-state matrix (phase 2), and the
    plan. Deterministic and side-effect free apart from log lines: `--package`
    must be safe to re-run, and the idempotence test compares two calls.

    `canon_cutoff` is threaded to `state_context`, the reference list, and the
    style reference, so one `--package` walks the canon tree once. It was walked
    five times, which logged an unparseable `canon_updated` five times and read
    as five broken files.

    `batch` is threaded for the same reason: `run_package` derives it for
    README's batch table, and the reference list now ranks by it (#311).
    """
    gaps: list[str] = []

    book_level = pi.book_level_direction(project_dir)
    gaps.extend(book_level_gaps(project_dir))

    plan = ill.read_plan(project_dir)
    context = state_context(project_dir, plan=plan,
                            canon_cutoff=canon_cutoff)
    anchors = context['anchors']
    if not anchors:
        gaps.append(
            'no entity canon file has a populated Embeddable block — no '
            'illustration in this packet carries a continuity anchor, so '
            'nothing holds a character or a place to one design across the '
            'set. Run `storyforge illustrate --direction`.')

    rows = rows_in_reading_order(project_dir, plan=plan,
                                 order=context['order'])
    if not rows:
        gaps.append(
            'the illustration plan has no rows — this packet describes no '
            'illustrations. Run `storyforge illustrate --plan`.')

    # The style reference is resolved once here and handed to both consumers: the
    # reference list embeds it and the gaps report its problems, and resolving it
    # twice walked the canon tree a second time to answer the same question.
    from storyforge import cmd_illustrate
    style = cmd_illustrate.resolve_style_reference(
        project_dir, canon_cutoff=context['canon_cutoff'])
    # Resolved *before* the row loop, not after it as the packet's six-file
    # version did: the upload list is book-level now, and a row needs to know
    # whether its own earlier render is in it (`_self_reference_note`).
    if batch is None:
        batch = anchor_batch(project_dir)
    references, reference_notes = _packet_references(
        project_dir, rows, canon_cutoff=context['canon_cutoff'], style=style,
        batch=batch)
    reference_stems = {
        os.path.splitext(os.path.basename(rel))[0]: position
        for position, (rel, _purpose) in enumerate(references, start=1)}

    entries: list[ImagePrompt] = []
    for row in rows:
        entry, row_gaps = image_prompt_for(
            project_dir, row, context=context,
            reference_stems=reference_stems)
        entries.append(entry)
        gaps.extend(row_gaps)
    gaps.extend(_body_cause_gaps(entries))

    gaps.extend(audit_gaps(project_dir))
    gaps.extend(stale_render_gaps(project_dir, rows,
                                   context['canon_cutoff']))
    # Unconditionally, not behind the composite below. The style reference is the
    # packet's most influential image and the only one always present, and its
    # problems reached exactly one file: `run_package` logs `gaps`, so a stale or
    # mis-declared cover appeared in no log line and no README gap — which made
    # "the packet says what it cannot tell you" an overclaim. Same class as
    # `book_level_gaps`' "no house style for it", which is already unconditional.
    gaps.extend(cmd_illustrate.style_reference_warnings(style))
    if reference_notes and _has_ingested_art(rows) and len(references) <= 1:
        # The dangerous shape: renders exist on disk and none of them reached
        # the list. This gap and the exclusions it points at are now both in
        # README.md — the pointer named `reference-images.md` until #306
        # retired that file, so the packet's most consequential gap sent the
        # author to a filename the same run deletes.
        gaps.append(
            'the reference-image list is cover-only or empty even though this '
            'book has ingested illustrations — the exclusions are listed under '
            '**Read this before you upload** in step 1 above. Uploading only '
            'what is listed means the next renders carry no likeness '
            'reference, which is the drift the reference chain exists to '
            'prevent.')

    return {
        'book_level': book_level,
        'anchors': anchors,
        'entries': entries,
        'references': references,
        'reference_notes': reference_notes,
        'gaps': gaps,
    }


def _body_cause_gaps(entries: list[ImagePrompt]) -> list[str]:
    """One gap per shared cause, naming the rows — never one gap per row.

    A project-wide cause (no prompt files written yet, a prompt file that will
    not parse) is one sentence about the project followed by the ids it hit. Per
    row it is twenty near-identical bullets in the section whose value is
    proportional to its signal-to-noise, which is what teaches an author to skip
    the section the real warnings live in (#290).

    Ids capped at three plus a count by `_and_more`, for the same reason.
    """
    causes: dict[str, list[str]] = {}
    for entry in entries:
        if entry['body_cause']:
            causes.setdefault(entry['body_cause'], []).append(entry['id'])
    return [
        f'{len(ids)} of {len(entries)} illustration(s) {cause} '
        f'({_and_more(ids)}).'
        for cause, ids in causes.items()]


def stale_render_gaps(project_dir: str, rows: list[dict[str, str]],
                       canon_cutoff: str) -> list[str]:
    """Canon-stale art, as one aggregate gap — and the case where it is unknown.

    Two holes this closes, both of the kind README.md exists to state:

    - **Rows outside the anchor batch were invisible here.** A stale row was
      marked in its own entry heading and, if it happened to fill one of the four
      slots, in the batch table. On a twenty-row book that put seventeen of them
      nowhere in README.md, while the author was told to work `illustrations.md`
      top to bottom. `_references_for`'s per-row WARNINGs are the log channel
      #300 says was scrolled past.
    - **An unjudgeable cutoff read as "all current."** See
      `ill.staleness_unchecked_finding`; this is the same disclosure in the
      artifact the author still has an hour later.

    Aggregated `count → ids`, following `_warn_unanchored_rows`: one project-wide
    fact behind every row's reason means twenty near-identical sentences, and a
    gap channel that cries wolf teaches the author to skip the section where the
    real warnings live.
    """
    gaps = [f['detail'] for f in ill.staleness_unchecked_finding(
        project_dir, rows, canon_cutoff)]
    stale = [row['id'].strip() for row in rows
             if ill.stale_render_reason(row, canon_cutoff)]
    if stale:
        gaps.append(
            f'{len(stale)} of {len(rows)} illustration(s) already have art that '
            f'predates the canon now governing them ({", ".join(stale)}) — they '
            f'still ship, and they still need re-rendering. Each one says so '
            f'where it appears; re-render and re-ingest them rather than '
            f'demoting `status`.')
    return gaps


def _has_ingested_art(rows: list[dict[str, str]]) -> bool:
    """Whether any live plan row claims a rendered file."""
    return any((row.get('status') or '').strip() == 'ingested'
               and (row.get('asset_file') or '').strip() for row in rows)


def book_level_gaps(project_dir: str, *,
                    bundle: str = 'packet') -> list[str]:
    """Gaps for the three book-level canon files.

    Absent and scaffolded are separated because the fixes differ: `--direction`
    writes an absent file and is a no-op on one that already exists, so
    conflating them tells an author who has just run it to run it again.

    `bundle` is the noun the sentences use for the artifact these gaps are being
    written into. It had a second value while `--export` existed, whose README
    must not have said "this packet"; there is one bundle now and no caller
    passes it. Kept as a seam rather than inlined, because a gap that is wrong
    about where it is written is the failure it exists to prevent — but a reader
    should not go looking for a second caller, so: there is none.
    """
    gaps: list[str] = []
    # A truncated block is neither absent nor a scaffold, so
    # missing_reference_sections reports it clean — but the packet copied only
    # the text above the stray `##`, which is exactly the coverage overclaim
    # README.md must not make (#293).
    for canon_id, truncations in sorted(
            canon.truncated_anchor_ids(project_dir).items()):
        headings = ', '.join(f'`{t.heading}`' for t in truncations)
        gaps.append(
            f'canon `{canon_id}` has a `##` heading inside its Embeddable '
            f'block ({headings}), which ends the block — the copy in this '
            f'{bundle} stops there, so it is shorter than the canon file looks. '
            f'Demote it to `###`, then regenerate.')
    for canon_id in ill.missing_reference_sections(project_dir):
        if canon.resolve_canon_path(project_dir, canon_id) is None:
            gaps.append(
                f'book-level canon `{canon_id}` has no file under '
                f'reference/canon/ — this {bundle} states no house style for it, '
                f'and images generated without it will not look like one '
                f'book. Run `storyforge illustrate --direction`.')
        else:
            gaps.append(
                f'book-level canon `{canon_id}` is still an unfilled scaffold '
                f'— a TODO fed to an image model reads as a deliberate '
                f'instruction, so this {bundle} leaves it out entirely. Edit '
                f'reference/canon/{canon_id}.md directly.')
    return gaps


def entry_for(row: dict[str, str], *,
              context: RowContext) -> tuple[Entry, list[str]]:
    """Build one entry and the gaps found while building it."""
    illus_id = row['id'].strip()
    scene_id = (row.get('scene_id') or '').strip()
    gaps: list[str] = []

    beat = (row.get('beat') or '').strip()
    if not beat:
        gaps.append(
            f'illustration `{illus_id}` has no beat — its entry cannot say '
            f'what happens in the image. Fill `beat` in '
            f'reference/{ill.PLAN_FILENAME}.')
    # The gap survives the removal of the `in_frame` field it used to populate.
    # `subject` still reaches the image model — through `_derived_body` when no
    # prompt file exists, and through the art-direction request `--prompts` built
    # from it when one does — so an empty cell is still a hole, it just no longer
    # has an index column of its own to be blank in.
    if not (row.get('subject') or '').strip():
        gaps.append(
            f'illustration `{illus_id}` has no subject — nothing says what is in '
            f'frame. Fill `subject` in reference/{ill.PLAN_FILENAME}.')

    state, state_gaps = state_for_row(row, context=context)
    gaps.extend(state_gaps)
    contrast = contrast_for_row(row, context=context)

    status = cast(ill.PlanStatus,
                  (row.get('status') or '').strip() or 'planned')
    treatment = (row.get('treatment') or '').strip()
    late = _staging_postdates_render(row) if treatment else ''
    if late:
        gaps.append(
            f'illustration `{illus_id}` was staged {late[0]}, after its render '
            f'was ingested {late[1]} — the finished art does not follow its '
            f'treatment. Re-render it from the current entry, or clear the '
            f'`treatment` cell if the art is right as it stands.')

    entry: Entry = {
        'id': illus_id,
        'scene_id': scene_id,
        'status': status,
        'layout': (row.get('layout') or ill.DEFAULT_LAYOUT).strip()
                  or ill.DEFAULT_LAYOUT,
        'aspect': pi.aspect_for_row(row),
        'beat': beat or NOT_RECORDED,
        'state': state,
        # `absent` is an author-written column the plan schema does not define:
        # `write_plan` preserves columns beyond `PLAN_COLUMNS`, so an author can
        # add it by hand. Deliberately not added to `PLAN_COLUMNS`, because
        # nothing in the pipeline populates it and a write-only column is the
        # mistake `embeds_as` already made. Empty is the normal case — most
        # images have nothing that must be absent.
        'absent': (row.get('absent') or '').strip(),
        'contrast': contrast.for_model,
        'contrast_for_author': contrast.for_author,
        'contrast_withheld': contrast.withheld,
        'notes': (row.get('composition') or '').strip(),
        'treatment': treatment,
        'stale_reason': ill.stale_render_reason(row, context['canon_cutoff']),
    }
    return entry, gaps


def image_prompt_for(project_dir: str, row: dict[str, str], *,
                     context: RowContext,
                     reference_stems: dict[str, int],
                     ) -> tuple[ImagePrompt, list[str]]:
    """Build one illustration's upload file and the gaps found while building it.

    Everything author-facing that this collects — `body_warning`, `body_cause`,
    `self_reference` — lands on the returned object for `illustrations.md` and
    `README.md` to render. None of it reaches the file the model reads; see
    `ImagePrompt`.

    `reference_stems` maps an uploaded reference's filename stem to its position
    in the book-level list, which is how a row learns that its own earlier render
    is one of the images the author uploaded at the top of the session.
    """
    entry, gaps = entry_for(row, context=context)
    body = _body_for(project_dir, row)

    prompt: ImagePrompt = {
        **entry,
        'model': pi.DEFAULT_IMAGE_MODEL,
        'size': SIZES[entry['aspect']],
        'quality': QUALITY,
        'body': body['text'],
        'body_source': body['source'],
        'prompt_source': body['path'],
        'body_warning': body['warning'],
        'body_cause': body['cause'],
        'self_reference': _self_reference_note(entry['id'], reference_stems),
    }
    return prompt, gaps


def _self_reference_note(illus_id: str, reference_stems: dict[str, int]) -> str:
    """What to tell the author when their own earlier render is in the uploads.

    `cmd_illustrate._references_for` excludes a row from its own chain, because
    re-rendering an illustration with its own previous version in front of the
    model is how a re-render reproduces what it was meant to replace. The retired
    export could honour that per unit, since it copied a chain per directory. One
    list uploaded once at the top of a session cannot — so the exclusion becomes
    a sentence addressed to the author instead.

    Deliberately author-facing and therefore **not** in the image prompt: phrased
    for the model it would be a negation ("ignore reference 2"), and #263's
    finding that negated keywords leak into the render is why the exceptions to
    positive framing are enumerable rather than open. The four remain `absent`,
    colour logic, orientation, and no-text.
    """
    position = reference_stems.get(illus_id)
    if position is None:
        return ''
    others = [str(n) for n in sorted(reference_stems.values())
              if n != position]
    anchoring = (f'References {", ".join(others[:-1])} and {others[-1]} anchor '
                 f'this image' if len(others) > 1 else
                 f'Reference {others[0]} anchors this image' if others else
                 'No other uploaded image anchors this one')
    return (f'{anchoring}; reference {position} is this illustration\'s own '
            f'earlier render. This is a re-render, not a match — do not treat '
            f'it as the target.')


class _Body(TypedDict):
    """An image prompt's prose, where it came from, and what to say about it.

    One bag rather than a four-tuple because `path` and `source` are one fact
    about one file, and the pair `('prompt_file', '')` is not a state that can
    exist — a tuple invited exactly that.
    """
    text: str
    source: BodySource
    #: The prompt file that was *consulted*, whether or not it existed or parsed.
    #: Recorded unconditionally so a file appearing at the default path is
    #: noticed: `_body_for` picks it up with no plan edit, and
    #: `parse_prompt_file`'s docstring invites hand-authoring.
    path: str
    #: The sentence for `illustrations.md`, '' when there is nothing to say.
    warning: str
    #: The project-wide phrasing README aggregates `cause -> ids`. Names the
    #: shared root cause, not this row.
    cause: str


def _body_for(project_dir: str, row: dict[str, str]) -> _Body:
    """The model-authored prose for a row, or a stand-in — plus why.

    A missing, unreadable, or unparseable prompt file is **not** a refusal: the
    packet costs nothing to produce, so the useful behaviour is to build it and
    say what is thin about it — `run_package`'s posture throughout. It is also
    not silent: a block assembled from three plan cells reads exactly like a
    complete prompt, and an author who cannot tell the difference generates from
    it.

    A **declared** `prompt_file` that does not exist gets its own sentence. An
    author who typed a path meant that path, so the prose usually exists
    somewhere (moved, renamed, uncommitted) and the action is to find it — a
    different action from "generate it again".

    A body whose own prose carries a `Constraints` heading is used and *reported*
    (`body_truncated`): the parse cuts at the first such heading to keep stale
    constraints out of the upload, which means anything the model wrote after it
    — often `### Use case` — is dropped. Reporting rather than silently
    substituting the plan row follows #293: a truncation every consumer accepts
    is worse than an absence, because nothing looks wrong.
    """
    illus_id = row['id'].strip()
    declared = (row.get('prompt_file') or '').strip()
    rel = declared or ill.default_prompt_rel(illus_id)
    path = os.path.join(project_dir, rel)
    plan_row = _derived_body(row)
    tail = (f'so its image prompt is assembled from the plan row alone — the '
            f'beat, the subject, and the composition note, with none of the '
            f'scene-specific prose `--prompts` writes')

    if not os.path.isfile(path):
        if declared:
            return {
                'text': plan_row, 'source': 'plan_row', 'path': rel,
                'warning': f'the plan declares art direction at `{rel}`, which '
                           f'is not there, {tail}. Restore that file, or clear '
                           f'the `prompt_file` cell and run `storyforge '
                           f'illustrate --prompts --ids {illus_id}`.',
                'cause': 'declare a `prompt_file` that does not exist, so their '
                         'image prompts come from the plan row',
            }
        return {
            'text': plan_row, 'source': 'plan_row', 'path': rel,
            'warning': f'this illustration has no written art direction, {tail}. '
                       f'Run `storyforge illustrate --prompts --ids {illus_id}` '
                       f'first for a stronger prompt.',
            'cause': 'have no written art direction, so their image prompts come '
                     'from the plan row alone',
        }
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return {
            'text': plan_row, 'source': 'plan_row', 'path': rel,
            'warning': f'its prompt file `{rel}` could not be read '
                       f'({getattr(exc, "strerror", None) or exc}), {tail}. Fix '
                       f'its permissions or delete the file, then re-run '
                       f'`--package`.',
            'cause': 'have a prompt file that could not be read, so their image '
                     'prompts come from the plan row',
        }

    parsed = pi.parse_prompt_file(text)
    if parsed['status'] == 'ok':
        return {'text': parsed['body'], 'source': 'prompt_file', 'path': rel,
                'warning': '', 'cause': ''}
    if parsed['status'] == 'body_truncated':
        return {
            'text': parsed['body'], 'source': 'prompt_file', 'path': rel,
            'warning': f'its prompt file `{rel}` carries its own `Constraints` '
                       f'heading inside the prompt body, which ends the body — '
                       f'so everything the model wrote after it (often `### Use '
                       f'case`) is **not** in the uploaded prompt. Demote that '
                       f'heading in `{rel}` and re-run `--package`.',
            'cause': 'have a `Constraints` heading inside their prompt body, so '
                     'part of their art direction was dropped',
        }
    reason = ('has no `## Prompt` section'
              if parsed['status'] == 'no_prompt_section'
              else 'has an empty prompt body')
    return {
        'text': plan_row, 'source': 'plan_row', 'path': rel,
        'warning': f'its prompt file `{rel}` {reason}, {tail}. Re-run '
                   f'`storyforge illustrate --prompts --ids {illus_id}`.',
        'cause': 'have a prompt file with no usable prompt body, so their image '
                 'prompts come from the plan row',
    }


def _derived_body(row: dict[str, str]) -> str:
    """A prompt body built from the plan row, in the prompt file's own shape.

    Four sections rather than free prose, because the whole artifact is written
    for a model tuned on the 5-section template (#260) — and because a stand-in
    shaped like the real thing is how a reader sees at a glance which parts are
    thin. `NOT_RECORDED` is deliberately not reused: it points at README's gap
    list, and this text is uploaded to an image model that cannot follow it.
    """
    def cell(key: str) -> str:
        return (row.get(key) or '').strip()

    unwritten = '_(not recorded in the plan)_'
    details = [f'- {label}: {cell(key) or unwritten}' for label, key in (
        ('Palette', 'palette'), ('Composition', 'composition'),
        ('Mood', 'mood'), ('Motifs to carry', 'motifs'))]
    return '\n'.join([
        '## Scene', '',
        cell('beat') or unwritten, '',
        '## Subject', '',
        cell('subject') or unwritten, '',
        '## Important details', '',
        '\n'.join(details), '',
        '## Use case', '',
        'Interior illustration for a novel.',
    ])


def _staging_postdates_render(row: dict[str, str]) -> tuple[str, str] | None:
    """`(treatment_at, ingested_at)` when the staging is later, else None.

    Only an ingested row can have art that fails to follow its treatment, and
    only *dates* can establish that it does. **A missing stamp says nothing.**
    An unstamped legacy row, or a treatment an author wrote by hand (which
    `--sequence` never stamps because it never overwrites one), is not evidence
    of a problem — and treating it as one made this gap fire on every ingested
    row of a book staged in the documented order, which is 86% noise in the one
    section whose credibility the rest of the packet's honesty depends on.

    Compared as ISO dates via `canon.iso_date_or_empty`, which sort
    lexicographically. Strictly later: same-day is the ordinary incremental loop
    (stage, prompt, render, ingest) and date granularity cannot separate the two.
    """
    if (row.get('status') or '').strip() != 'ingested':
        return None
    staged = canon.iso_date_or_empty(row.get('treatment_at') or '')
    ingested = canon.iso_date_or_empty(row.get('ingested_at') or '')
    if not staged or not ingested or staged <= ingested:
        return None
    return staged, ingested


def state_for_row(row: dict[str, str], *, context: RowContext,
                  include_anchor_gaps: bool = True) -> tuple[str, list[str]]:
    """Resolve the matrix for this scene, then overlay the row's override.

    **The single resolution both `--package` and `--prompts` read.** An anchor
    necessarily describes the whole book — "navy pajamas on the first night, and
    from a04 onward a rust-red jacket" — so no anchor can tell a generation call
    which night *this* image is. That is the question the matrix answers, and
    while it reached only the packet, prompt files contradicted the packet built
    from the same row in both directions (#297). Two renderings of one row is how
    they disagree; one function is how they cannot — **within one run**. Across
    runs they still can: a prompt file is a render like the packet, but unlike the
    packet there is no `prompt_stale`, so editing the transition log after
    `--prompts` diverges the two silently. Re-run `--prompts --ids …` after
    editing the matrix.

    Only the entities the row's `canon_refs` names, because sending the whole
    cast wastes tokens and invites the model to draw people who are not in the
    frame. An aspect track satisfies a bare canon id — `nora-clothing` covers
    `nora` — matching how `visual_state.prepass` decides the same question.

    A `state_override` entity the row does not name is still included: it was
    written for this image specifically, and dropping it would be the silent
    filtering this module exists to avoid. The override also *wins* over the
    forward walk for the entities it names, which is what makes it a usable
    escape hatch for state true in one image only.

    **An unresolvable `canon_refs` entry produces one gap, not two** (#290). It
    used to produce both the anchor gap and the "no transition states its visual
    state there" gap for one root cause. `_unanchored_gap` is the survivor, and
    it is emitted *after* resolution so it can name what actually happened —
    both consequences and both remedies when the state is also unstated, the
    anchor alone when the state resolved. Under `include_anchor_gaps=False`
    (`--prompts`) both are suppressed **for those refs only**: an anchored entity
    with no transition still reports, and `_warn_unanchored_rows` covers the
    unanchored ones at every coaching level, naming the missing anchor rather
    than a missing transition.

    Args:
        include_anchor_gaps: Whether to report a `canon_refs` entry that
            resolves to no populated canon file. `--prompts` passes False
            because `cmd_illustrate._warn_unanchored_rows` already warns about
            exactly that, before the fan-out, naming the rows and the missing
            ids — a second copy of the same finding trains an author to skim the
            log where the other gaps live.
    """
    illus_id = row['id'].strip()
    scene_id = (row.get('scene_id') or '').strip()
    anchors = context['anchors']
    order = context['order']
    known = context['known']
    refs = ill._split_array(row.get('canon_refs', ''))
    # `.applied` only — the skipped and prose-key halves are reported by
    # `visual_state.prepass` as findings, on the gate authors read (#309).
    overrides = vs.parse_state_override(
        row.get('state_override', '')).applied
    gaps: list[str] = []

    anchor_keys = {key.lower() for key in anchors}
    unanchored = {ref for ref in refs if ref.lower() not in anchor_keys}
    # Filled by the resolution loop below, then read by the anchor gaps, which
    # are therefore emitted *after* it: whether an unanchored ref also failed to
    # resolve a state decides which remedies the one gap should offer, and
    # asserting the answer before knowing it made the first version of this gap
    # state a falsehood about half the rows it fired on.
    unstated: set[str] = set()

    resolved: dict[str, str] = {}
    if not scene_id:
        if refs:
            gaps.append(
                f'illustration `{illus_id}` has no scene_id, so no visual '
                f'state resolves for it. Set `scene_id` in '
                f'reference/{ill.PLAN_FILENAME}.')
    elif scene_id not in known:
        gaps.append(
            f'illustration `{illus_id}` names scene `{scene_id}`, which is '
            f'not an active scene in scenes.csv — cut, renamed, or mistyped. '
            f'No visual state resolves for this entry.')
    elif scene_id not in order:
        gaps.append(
            f'illustration `{illus_id}`: scene `{scene_id}` has no reading '
            f'position — reference/chapter-map.csv does not list it — so '
            f'nothing in the visual-state matrix resolves for this entry.')
    else:
        resolved = vs._resolve(order, context['transitions'], order[scene_id])

    parts: list[tuple[str, str]] = []
    claimed: set[str] = set()
    for ref in refs:
        needle = ref.lower()
        matched = [key for key in resolved
                   if key.lower() == needle
                   or key.lower().startswith(f'{needle}-')]
        if not matched and needle in {key.lower() for key in overrides}:
            matched = [key for key in overrides if key.lower() == needle]
        if not matched:
            if scene_id and scene_id in order:
                if ref in unanchored:
                    # One root cause, one gap — reported below, where it can
                    # offer both remedies instead of guessing which applies.
                    unstated.add(ref)
                else:
                    gaps.append(
                        f'illustration `{illus_id}` shows `{ref}` in '
                        f'`{scene_id}`, but no transition states its visual '
                        f'state there. Add a row to {vs.STATE_FILE}, or a '
                        f'`state_override` on the plan row if the state is '
                        f'true in this image only.')
            continue
        for key in sorted(matched):
            claimed.add(key.lower())
            parts.append((key, overrides.get(key, resolved.get(key, ''))))

    for key, value in overrides.items():
        if key.lower() not in claimed:
            claimed.add(key.lower())
            parts.append((key, value))

    # A transition with an empty `state` cell is admitted by `read_transitions`
    # (it only requires `entity`), and it *matches* — which means it suppresses
    # the "no transition states its visual state there" gap above and then
    # renders as nothing. Half-filling the matrix would therefore be strictly
    # worse than not filling it, because it deletes the warning that says to
    # finish. Recorded rather than filtered.
    for key, value in parts:
        if not value:
            gaps.append(
                f'illustration `{illus_id}` shows `{key}`, whose governing '
                f'transition at or before `{scene_id}` has an empty `state` '
                f'cell — so the entry says nothing about it, and the row is '
                f'suppressing the gap that would have told you to state it. '
                f'Fill the state in {vs.STATE_FILE}, or delete the row.')

    if include_anchor_gaps:
        for ref in refs:
            if ref in unanchored:
                gaps.append(_unanchored_gap(illus_id, ref, scene_id,
                                            stated=ref not in unstated))

    return '; '.join(f'{_entity_label(key, context["labels"])}: {value}'
                     for key, value in parts if value), gaps


def _unanchored_gap(illus_id: str, ref: str, scene_id: str, *,
                    stated: bool) -> str:
    """The one gap for a `canon_refs` entry that resolves to no canon file.

    Two shapes, because the remedy differs and the first version asserted the
    wrong one for both:

    - **State resolved.** The gap is about the anchor only. Saying "no visual
      state is reported for it either" here is simply false — the entry shows the
      state — and the sentence that followed it condemned the transition row that
      produced it.
    - **State also unstated.** Then it is genuinely one root cause with two
      consequences, and the gap says so. But it must offer *both* remedies:
      `visual_state.prepass` still emits `state_unspecified` for this row (it
      does not consult anchors), whose action text says to add a transition row.
      Telling the author here that a transition row "states a change to a design
      nothing has stated" put two instructions twenty lines apart in one
      `--diagnose` in direct contradiction — strictly worse than the duplication
      the suppression was meant to remove.

    The state-only entity class is why neither remedy can be presented as the
    only one: a lantern count or a lamp's lit/dark state has no invariant design,
    so it has no canon file **by design**, and for those the transition row is
    right and `--direction` is wrong.
    """
    head = (f'illustration `{illus_id}` names canon_refs `{ref}`, which '
            f'resolves to no populated canon file — that entity is '
            f'art-directed with no continuity anchor, so nothing holds it to '
            f'one design')
    if stated:
        return (f'{head}. Its visual state does resolve, so this is about the '
                f'anchor alone: author it with `storyforge illustrate '
                f'--direction`, or drop `{ref}` from `canon_refs` if it is a '
                f'state-only entity — a light count, a lamp lit or dark — with '
                f'no invariant design to anchor.')
    return (f'{head}, and no transition states its visual state'
            f'{f" in `{scene_id}`" if scene_id else ""} either, so the entry '
            f'says nothing about it. If `{ref}` has an invariant design, author '
            f'the anchor with `storyforge illustrate --direction`. If it is a '
            f'state-only entity — a light count, a lamp lit or dark — it has no '
            f'canon file by design: add a row to {vs.STATE_FILE} or a '
            f'`state_override` instead, and drop it from `canon_refs`.')


def _entity_label(entity: str, labels: dict[str, canon.AnchorLabel]) -> str:
    """Human-facing name for a state entity.

    A state entity is either a canon id or `{canon_id}-{aspect}` (the
    granularity convention: one track per independently-changing aspect). The
    aspect form is rendered `Nora (clothing)` so the entry reads as prose
    rather than echoing a slug at an image model.
    """
    if entity in labels:
        return labels[entity]['label']
    base, _, aspect = entity.rpartition('-')
    if base and base in labels:
        return f'{labels[base]["label"]} ({aspect})'
    return canon.humanize_canon_id(entity)


def contrast_for_row(row: dict[str, str], *,
                     context: RowContext) -> 'RowContrast':
    """What must make this image different from its neighbours.

    Derived from facts on the plan — the reading-order predecessor and the
    `register` extremes — plus anything the author wrote in a `contrast`
    column (author-written, like `absent`, and preserved by `write_plan`
    without being part of the schema). Nothing is invented: twenty independent
    generation calls cannot
    see each other, which is how a set ends up with four images of the same
    two children kneeling around the same lamp.

    **One derived sentence, not three.** The entry exists to be thin, and three
    stacked sentences here restated two
    facts. The author's own note, if any, follows it untouched.

    Read by `--prompts` as well as `--package`, for the same reason as
    `state_for_row`: one string, so the two artifacts cannot describe the same
    row differently **within one run**. Across runs they still can: a prompt file
    is a render like the packet, but unlike the packet there is no
    `prompt_stale`, so editing the plan or the transition log after `--prompts`
    diverges the two silently. Re-run `--prompts --ids …` after editing either.

    **A row absent from `predecessors` is not the first illustration.** Reading
    order excludes `superseded` rows while `--prompts --ids` deliberately revives
    one, so a `.get(id, '')` default merged "not in the order I indexed" into
    "starts the book" — the revived row's prompt lost its contrast clause, and
    the packet built after ingest had it. That is #297's own failure shape inside
    the function written to prevent it, so the two cases are kept apart: an
    absent row gets a clause naming the situation rather than a silent omission.
    """
    illus_id = row['id'].strip()
    predecessors = context['predecessors']
    if illus_id in predecessors:
        previous_id = predecessors[illus_id]
    else:
        previous_id = ''
        log(f'WARNING: illustration `{illus_id}` is not in the book\'s reading '
            f'order — a `superseded` row revived by --ids, or a plan written '
            f'since this context was read. Nothing states which illustration it '
            f'follows, so its contrast line cannot say what staging to avoid; '
            f'the packet will say once the row is live again.')
    register = (row.get('register') or '').strip().lower()
    extreme = (f'The {register} image in the book'
               if register in ill.VALID_REGISTERS else '')

    # Two phrasings of one fact, built from parts rather than by rewriting one
    # into the other. A substitution on the assembled string produces "it Do not
    # repeat…" for the register variant, where the clause is mid-sentence.
    follows_author = (f'follows `{previous_id}` and must not repeat its staging'
                      if previous_id else '')
    follows_model = ('must not repeat the staging of the illustration '
                     'immediately before it' if previous_id else '')

    def _assemble(follows: str) -> str:
        if extreme and follows:
            return f'{extreme}; it {follows}.'
        if extreme:
            return f'{extreme}.'
        if follows:
            return f'{follows[0].upper()}{follows[1:]}.'
        return ''

    author = (row.get('contrast') or '').strip()
    kept, withheld = _split_author_contrast(author, context['plan_ids'])

    return RowContrast(
        for_model=' '.join(p for p in (_assemble(follows_model), kept) if p),
        for_author=' '.join(p for p in (_assemble(follows_author), author) if p),
        withheld=withheld,
    )


class RowContrast(NamedTuple):
    """One row's contrast direction, in the two forms its two audiences need.

    **`for_model` carries no illustration ids, and that is the whole point**
    (#305). `prompt_constraints` renders contrast into the upload file, and since
    #306 that file has no paste boundary — the author uploads it whole, so every
    word reaches the image model. Nineteen of twenty prompts on a real book
    therefore instructed the model to compare this image against `LF-04`, an image
    it cannot see, in the one artifact designed for a model that has only what you
    hand it. `render_image_prompt`'s own docstring states the rule the ids broke.

    `for_author` keeps them, because an id is exactly right for a human checking a
    render — it names the file to open. It goes to the source prompt file's
    `## Accept only if` and to `illustrations.md`'s notes.

    `withheld` is the author's own sentences that named an id, so
    `illustrations.md` can show them rather than silently dropping them. There is
    no rewrite that preserves their meaning: "colder and markedly darker than
    `LF-05`" cannot survive without `LF-05`, so the comparison becomes a *review*
    criterion rather than something a generation call can act on. Dropping it
    without saying so would be the silent-omission failure this pipeline keeps
    being bitten by.
    """
    for_model: str
    for_author: str
    withheld: str


def _split_author_contrast(author: str,
                           plan_ids: set[str]) -> tuple[str, str]:
    """Split author contrast into (safe for the model, withheld because of ids).

    Sentence-level, on the same punctuation heuristic as
    `illustrations.first_sentence` and with the same caveat: it is not
    segmentation, so `Mr. Ives` splits. That is tolerable here because the two
    halves are recombined for the author verbatim — a mis-split can only move a
    fragment into the withheld column, which is disclosed, never into the copy the
    model reads.

    Matching is against ids the plan actually declares, plus any backticked
    token that looks like one. A generic pattern alone would be far too eager: a
    plan id may be as plain as `a10`, and `absent`/`contrast` are author prose.
    """
    if not author:
        return '', ''
    ids = sorted((i for i in plan_ids if i), key=len, reverse=True)
    # Word-boundary search per id, **not** tokenize-and-strip-punctuation. The
    # first cut stripped a fixed set of characters off each word and compared
    # sets, which missed the possessive: a real book's cell read "deliberately
    # unlike LF-07's hard outdoor light boundary", and `LF-07's` does not strip to
    # `LF-07` because `s` is not punctuation. `\b` holds after the `7` regardless
    # of what follows, which is what makes this robust against every attachment —
    # possessives, hyphens, parentheses — instead of an enumerated list of them.
    pattern = (re.compile(r'\b(?:%s)\b' % '|'.join(re.escape(i) for i in ids),
                          re.IGNORECASE) if ids else None)
    kept: list[str] = []
    dropped: list[str] = []
    for sentence in _sentences(author):
        names_id = bool(pattern and pattern.search(sentence)) or bool(
            _BACKTICKED_ID_RE.search(sentence))
        (dropped if names_id else kept).append(sentence)
    return ' '.join(kept).strip(), ' '.join(dropped).strip()


#: A backticked token shaped like a plan id — the belt to `plan_ids`' braces, for
#: an author who wrote a contrast against art that is not in the plan (a cut row,
#: or a typo). Requires the backticks, so ordinary prose cannot trip it.
_BACKTICKED_ID_RE = re.compile(r'`[A-Za-z0-9][A-Za-z0-9_-]*`')


def _sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation, keeping the punctuation."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p.strip()]


def audit_gaps(project_dir: str, *, bundle: str = 'packet') -> list[str]:
    """The contradiction audit's coverage of the prose this bundle describes.

    `bundle` names the artifact for the reason `book_level_gaps` records, and
    like it has one caller and one value since #306.
    """
    gaps: list[str] = []
    if not vs.read_provenance(project_dir):
        return [
            f'the contradiction audit has never been run — nothing has read '
            f'the prose against the visual-state matrix, so this {bundle} may '
            f'describe an image of something the book does not do. Run '
            f'`storyforge illustrate --audit`.']
    stale = sorted({f['scene_id'] for f in vs.digest_drift(project_dir)
                    if f['kind'] == 'audit_stale' and f.get('scene_id')})
    if stale:
        gaps.append(
            f'the contradiction audit is stale — {len(stale)} scene(s) were '
            f'revised since it ran: {", ".join(stale)}. Re-run '
            f'`storyforge illustrate --audit`.')
    return gaps


def _packet_references(
        project_dir: str, rows: list[dict[str, str]], *,
        canon_cutoff: str | None = None,
        style: "StyleReference | None" = None,
        batch: AnchorBatch | None = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """The labeled reference-image list for the whole packet, and why it is short.

    Reuses `--prompts`' per-illustration builder rather than a second one, so
    the packet inherits its two exclusions: the cover art is the *artwork* and
    not the typeset cover, and a render older than the newest `canon_updated`
    is left out with a WARNING instead of teaching the new session drift the
    current canon exists to remove.

    Files are never copied into the packet — README's upload step carries
    project-relative paths, because a copy is a second thing to invalidate.

    The second element is the exclusion record. `--prompts` only logs those, and
    for a prompt file that is enough because the author is watching the run; the
    packet is read hours later, so the reasons have to be *in* it.

    `batch` is threaded through for the same reason `canon_cutoff` and `style`
    are — `run_package` has already derived it for README's batch table, and
    `anchor_batch` re-reads the plan, the chapter map, and the transition log.
    The upload list is where #311 was found: the four images phase 1 exists to
    approve were the ones the cap dropped.
    """
    from storyforge import cmd_illustrate
    notes: list[str] = []
    if canon_cutoff is None:
        canon_cutoff = canon.newest_canon_updated(project_dir)
    references = cmd_illustrate._references_for(
        project_dir, 'the packet', plan=rows,
        canon_cutoff=canon_cutoff, style=style, batch=batch, notes=notes)
    return references, notes


def state_grid(project_dir: str) -> StateGrid:
    """The dense scene x entity view the packet renders.

    One column per tracked entity, one row per positioned scene, each cell the
    state in effect there — the sparse log's forward walk done once so the
    generating session does not have to do it per image.
    """
    transitions = vs.read_transitions(project_dir)
    order = ill._scene_order(project_dir)
    scenes = sorted(order, key=lambda sid: order[sid])
    entities = sorted({t['entity'] for t in transitions})
    cells = {sid: vs._resolve(order, transitions, order[sid]) for sid in scenes}
    unpositioned = sorted(vs.known_scene_ids(project_dir) - set(order))
    return {
        'entities': entities,
        'scenes': scenes,
        'cells': cells,
        'unpositioned': unpositioned,
    }
# ============================================================================
# The anchor batch
# ============================================================================

#: The four slots, as a type. `BATCH_SLOTS` and `AnchorBatch` are one vocabulary
#: in two declarations, and every consumer indexes the second with a key from the
#: first — which is why six `# type: ignore[literal-required]` comments
#: accumulated, each asserting something nothing in this repo could verify.
#: Naming the slots narrows the subscript instead, and a `get_args` totality test
#: catches an addition to one declaration and not the other.
BatchSlot = Literal['establisher', 'darkest', 'brightest', 'later_state']

#: Slot order, and the label each slot carries wherever the batch is reported.
BATCH_SLOTS: tuple[tuple[BatchSlot, str], ...] = (
    ('establisher', 'establisher — the most shared vocabulary, earliest'),
    ('darkest', 'darkest register'),
    ('brightest', 'brightest register'),
    ('later_state', 'later-state exemplar'),
)


class AnchorBatch(TypedDict):
    """The four illustrations to render and approve before the churn.

    Derived on every read, never stored, so it cannot disagree with the plan —
    the same reasoning `render_order` follows. Phase 1 of the handoff exists
    because a long generation run referencing *descriptions* drifts, while one
    referencing four approved images does not.

    An empty slot is a real answer, not an error: a plan where nothing names a
    continuity anchor has no establisher. Every empty or guessed slot is
    disclosed in `fallback`.
    """
    establisher: str
    darkest: str
    brightest: str
    later_state: str
    #: Disclosures about slots that were guessed or could not be filled. The
    #: point of the whole structure: a silent guess about which image is the
    #: darkest in the book is how an author discovers at image twenty that
    #: nothing is.
    fallback: list[str]
    #: Which slots hold a guess rather than a choice — a subset of `darkest` and
    #: `brightest`, the only two slots with a fallback. `fallback` says the same
    #: thing in prose, and prose is unaskable: #311's reference labels have to
    #: know, because a prompt file carries neither the batch table nor these
    #: notes, so `anchor batch: brightest` there is a claim with nothing in the
    #: document to check it against. An *empty* slot is not a guessed one.
    guessed: list[BatchSlot]


def slots_by_id(batch: AnchorBatch) -> dict[str, BatchSlot]:
    """Each filled illustration id -> the first slot it fills, in promotion order.

    Keyed by id, not by slot, because darkest and brightest can resolve to one
    illustration — which `anchor_batch` discloses as "the batch brackets nothing"
    and which is the *common* configuration, since nothing populates `register`
    on most projects. That row must occupy one reference and be named once.

    Extracted because this is the fourth walk over `BATCH_SLOTS` and three of
    them wanted exactly this intermediate. `render_state`'s reasoning applies:
    a discrimination hand-written at N sites is N chances to write the one
    spelling whose failure mode is the bug the discrimination exists to prevent.
    """
    filled: dict[str, BatchSlot] = {}
    for slot, _label in BATCH_SLOTS:
        # `batch[slot]`, never `.get`: `AnchorBatch` is total and `anchor_batch`
        # fills every key, so a missing one is a structural mismatch between the
        # two declarations of the slot vocabulary. Three of the four consumers
        # raise on it; the fourth used `.get` and quietly promoted nothing, which
        # reverts #311 with no sound at all.
        illus_id = batch[slot].strip()
        if illus_id and illus_id not in filled:
            filled[illus_id] = slot
    return filled


def anchor_batch(project_dir: str, *,
                 plan: list[dict[str, str]] | None = None,
                 order: dict[str, int] | None = None,
                 transitions: list[vs.Transition] | None = None,
                 ) -> AnchorBatch:
    """The four-slot anchor batch, with every guess disclosed.

    `plan`, `order` and `transitions` let a caller that has already read them
    pass them in, as `rows_in_reading_order` does. Not an optimization: this
    reads the transition log, and `read_transitions` logs a WARNING per
    malformed row *per read*, so deriving the batch beside a `state_context`
    that had already read it made one broken row report itself twice — the
    "N walks read as N broken files" defect CLAUDE.md holds a canon-tree test
    on. Threading `plan` also removes a precondition two callers could disagree
    about: a caller ranking an in-memory plan would otherwise get slots derived
    from disk.
    """
    rows = rows_in_reading_order(project_dir, plan=plan, order=order)
    fallback: list[str] = []
    guessed: list[BatchSlot] = []
    if not rows:
        return {'establisher': '', 'darkest': '', 'brightest': '',
                'later_state': '', 'guessed': [],
                'fallback': ['the plan has no rows, so there is no anchor '
                             'batch to render. Run `storyforge illustrate '
                             '--plan`.']}

    ids = [row['id'].strip() for row in rows]

    establisher = next((step['id'] for step in
                        ill.render_order(project_dir, plan=plan, order=order)
                        if step['is_visual_key']), '')
    if not establisher:
        fallback.append(_no_establisher_note(rows))

    by_register: dict[str, str] = {}
    for row in rows:
        register = (row.get('register') or '').strip().lower()
        if register in ill.VALID_REGISTERS and register not in by_register:
            by_register[register] = row['id'].strip()

    darkest = by_register.get('darkest') or ids[0]
    brightest = by_register.get('brightest') or ids[-1]
    register_slots: tuple[tuple[BatchSlot, str, str], ...] = (
        ('darkest', darkest, 'first'), ('brightest', brightest, 'last'))
    for slot, guess, position in register_slots:
        if slot not in by_register:
            # Recorded in both channels on purpose: `fallback` is what README
            # prints, `guessed` is what a consumer can branch on. They are set
            # together so a slot cannot be disclosed in one and not the other.
            guessed.append(slot)
            fallback.append(
                f'no plan row is marked `register={slot}`, so the {slot} slot '
                f'is a guess: `{guess}`, the {position} illustration in '
                f'reading order. Mark the real extremes with '
                f'`register=darkest` and `register=brightest` in '
                f'reference/{ill.PLAN_FILENAME}; bracketing the book\'s '
                f'lighting range is what stops the whole set landing in one '
                f'exposure.')
    if darkest == brightest and len(ids) > 1:
        fallback.append(
            f'the darkest and brightest slots resolved to the same '
            f'illustration (`{darkest}`), so the batch brackets nothing.')

    later_state, later_state_note = _later_state_exemplar(
        project_dir, rows, order=order, transitions=transitions)
    if later_state_note:
        fallback.append(later_state_note)

    return {'establisher': establisher, 'darkest': darkest,
            'brightest': brightest, 'later_state': later_state,
            'fallback': fallback, 'guessed': guessed}


def _no_establisher_note(rows: list[dict[str, str]]) -> str:
    """Why the establisher slot is empty — the plan, or the horizon.

    Two different facts, and the batch reported the first for both: a plan whose
    early rows name no `canon_refs` and whose later rows do had an empty slot
    while "no illustration names a continuity anchor" was flatly false about it
    (#290). Only the wording changed — the horizon is a deliberate constraint,
    for the reason `ill.render_order` states.

    The emitted string carries the explanation rather than this docstring,
    because the author is the one who has to act on it.
    """
    horizon = ill.visual_key_horizon(len(rows))
    later = [row['id'].strip() for row in rows[horizon:]
             if ill._split_array(row.get('canon_refs', ''))]
    if not later:
        return ('no illustration names a continuity anchor in `canon_refs`, so '
                'there is no visual key to establish the look — the batch has '
                'no establisher, and whichever image is rendered first will set '
                'the style by accident. Fill `canon_refs` in '
                f'reference/{ill.PLAN_FILENAME}.')
    return (f'none of the first {horizon} illustration(s) in reading order '
            f'names a continuity anchor in `canon_refs`, so the batch has no '
            f'establisher. {len(later)} later illustration(s) do name anchors '
            f'({_and_more(later)}), but the visual key is chosen from the early '
            f'ones on purpose: it exists so everything after it has something '
            f'real to reference, and the climax cannot do that. Fill '
            f'`canon_refs` on one of the first {horizon} rows in '
            f'reference/{ill.PLAN_FILENAME}.')


#: How many ids a disclosure names before it summarises the rest. Enough to
#: recognise which rows are meant, few enough that the sentence stays readable.
_MAX_NAMED_IDS = 3


def _and_more(ids: list[str]) -> str:
    """Name the first few ids and count the rest.

    The shape this exists for is not rare: on a twenty-row book the horizon is
    six, so filling `canon_refs` from the middle of the book outward leaves
    fourteen ids to name. Fourteen backticked ids mid-sentence is what makes a
    `fallback` note skippable — and these notes are the whole disclosure channel
    for a guessed or unfillable slot, so their readability *is* the feature (the
    reasoning `treatment_at` records: a channel that cries wolf teaches the
    author to skip the section where the real warnings live).
    """
    named = ', '.join(f'`{i}`' for i in ids[:_MAX_NAMED_IDS])
    rest = len(ids) - _MAX_NAMED_IDS
    return named if rest <= 0 else f'{named}, and {rest} more'


def _later_state_exemplar(project_dir: str,
                          rows: list[dict[str, str]], *,
                          order: dict[str, int] | None = None,
                          transitions: list[vs.Transition] | None = None,
                          ) -> tuple[str, str]:
    """The illustration furthest from opening conditions, and any disclosure.

    "Furthest" is counted as the entities it *shows* — the ones its `canon_refs`
    name — whose governing transition is not that entity's first. An image can
    only lock a changed wardrobe if the wardrobe is in it, so counting entities
    the row does not name would pick an image that establishes nothing.

    Ties break to the earliest position, because the batch exists to lock
    designs for everything after it.

    `order` and `transitions` are threaded from the caller when it has them:
    `read_transitions` logs per malformed row per read, so a second read reports
    one broken row twice.
    """
    if order is None:
        order = ill._scene_order(project_dir)
    if transitions is None:
        transitions = vs.read_transitions(project_dir)

    first_position: dict[str, int] = {}
    for transition in transitions:
        position = order.get(transition['from_scene'])
        if position is None:
            continue
        entity = transition['entity']
        if entity not in first_position or position < first_position[entity]:
            first_position[entity] = position

    best_id, best_count = '', 0
    for row in rows:
        scene_id = (row.get('scene_id') or '').strip()
        if scene_id not in order:
            continue
        resolved = vs._resolve(order, transitions, order[scene_id])
        named = {ref.lower() for ref in ill._split_array(row.get('canon_refs', ''))}
        count = 0
        for entity, _state in resolved.items():
            key = entity.lower()
            shows = any(key == ref or key.startswith(f'{ref}-')
                        for ref in named)
            if not shows:
                continue
            governing = _governing_position(order, transitions, entity,
                                           order[scene_id])
            if governing is not None and governing != first_position.get(entity):
                count += 1
        if count > best_count:
            best_id, best_count = row['id'].strip(), count

    if best_id:
        return best_id, ''
    return '', (
        'no illustration shows a tracked entity in a state later than that '
        'entity\'s first, so the batch has no later-state exemplar — nothing '
        'locks a changed wardrobe or a broken object before the churn, and the '
        'first image that needs one will invent it. Either that is true of the '
        f'book, or {vs.STATE_FILE} is thinner than the story.')


def _governing_position(order: dict[str, int],
                        transitions: list[vs.Transition],
                        entity: str, target: int) -> int | None:
    """Position of the transition in effect for *entity* at *target*.

    Mirrors `visual_state._resolve`'s rule — take effect **at** the transition's
    own scene, latest row wins a tie — but returns the position rather than the
    state, which is what tells us whether the governing transition is the
    entity's first.
    """
    best: int | None = None
    for transition in transitions:
        if transition['entity'] != entity:
            continue
        position = order.get(transition['from_scene'])
        if position is None or position > target:
            continue
        if best is None or position >= best:
            best = position
    return best


# ============================================================================
# The written packet, checked against its sources
# ============================================================================

#: Anchor copies are wrapped in the canon-embed markers `canon.py` already
#: parses. Adopting the existing convention rather than a private one gives the
#: drift check a parser it does not have to write, and gives that convention its
#: first legitimate writer: nothing in the pipeline emits these markers today,
#: so `check_canon_drift` has been guarding a shape only hand-editing produced.
_EMBED_OPEN = '<!-- canon-embed: {canon_id} -->'
_EMBED_CLOSE = '<!-- /canon-embed -->'


def anchor_block(canon_id: str, text: str, label: str) -> str:
    """Render one anchor copy, wrapped so its fidelity can be checked.

    The writer lives beside `anchor_copy_drift`, its reader, so the two cannot
    disagree about the marker format. `text` goes in byte-for-byte on its own
    lines — no indentation, no wrapping, no trailing punctuation added — which
    is what lets the drift check compare against the canon source and what lets
    a generating session paste the string verbatim.
    """
    return '\n'.join([
        f'### {label}',
        '',
        _EMBED_OPEN.format(canon_id=canon_id),
        text,
        _EMBED_CLOSE,
    ])


def anchor_copy_drift(project_dir: str) -> list[ill.IllustrationFinding]:
    """Compare every written anchor copy to its canon source.

    The copies are wrapped in `<!-- canon-embed: id -->` markers, which is the
    convention `canon.find_canon_embeds` already parses and `check_canon_drift`
    already guards for GN page files. Reading the *written file* back is a
    different check from `resolve`'s: this one is the only thing that would
    catch a renderer wrapping or re-indenting a long anchor, or an author
    hand-editing a file whose whole point is being a render.

    Covered both bundles until #306 folded the export into the packet; one tree
    now, and the loop shape is kept because the per-file walk is what the
    findings are built from either way.

    Compared after `normalize_for_comparison`, so cosmetic whitespace is not
    drift and a changed word is. Returns [] when the packet is not built — an
    unbuilt bundle is in-flight state, not a finding.
    """
    findings: list[ill.IllustrationFinding] = []
    sources = canon.anchor_texts(project_dir)
    normalized = {cid: normalize_for_comparison(text)
                  for cid, text in sources.items()}

    if not os.path.isdir(os.path.join(project_dir, PACKET_DIR)):
        return findings
    for name in PACKET_FILES:
        findings.extend(_file_anchor_drift(
            project_dir, os.path.join(PACKET_DIR, name), normalized,
            '--package'))
    return findings


def _file_anchor_drift(project_dir: str, rel: str,
                       normalized: dict[str, str],
                       command: str) -> list[ill.IllustrationFinding]:
    """Every anchor-copy problem in one written file."""
    path = os.path.join(project_dir, rel)
    if not os.path.isfile(path):
        return []
    rerun = f'`storyforge illustrate {command}`'
    findings: list[ill.IllustrationFinding] = []
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        # One unreadable file must not take the whole check down, and must
        # not pass for "no drift" either.
        return [{
            'kind': 'anchor_copy_drift',
            'file': rel,
            'detail': f'could not read {rel} to check its anchor copies: '
                      f'{exc}. Re-run {rerun}.',
        }]
    embeds, unclosed, invalid = canon.find_canon_embeds(text)
    for opener in unclosed:
        findings.append({
            'kind': 'anchor_copy_drift',
            'id': opener['canon_id'],
            'file': rel,
            'detail': f'anchor copy `{opener["canon_id"]}` in {rel} has no '
                      f'closing marker, so its text cannot be checked '
                      f'against reference/canon/. Re-run {rerun}.',
        })
    for bad in invalid:
        findings.append({
            'kind': 'anchor_copy_drift',
            'file': rel,
            'detail': f'anchor copy marker `{bad["raw_id"]}` in {rel} is '
                      f'not a valid canon id, so its text cannot be '
                      f'checked against reference/canon/. Re-run {rerun}.',
        })
    for embed in embeds:
        cid = embed['canon_id']
        if cid not in normalized:
            findings.append({
                'kind': 'anchor_copy_drift',
                'id': cid,
                'file': rel,
                'detail': f'{rel} carries an anchor for `{cid}`, which no '
                          f'longer resolves to a populated canon file — it '
                          f'is directing art from an anchor that no longer '
                          f'exists.',
            })
            continue
        if embed['normalized'] != normalized[cid]:
            findings.append({
                'kind': 'anchor_copy_drift',
                'id': cid,
                'file': rel,
                'detail': f'the anchor copy for `{cid}` in {rel} differs '
                          f'from reference/canon/. Likeness continuity is '
                          f'the string, so re-run {rerun} rather than '
                          f'editing the file.',
            })
    return findings


#: Sources whose edit invalidates the packet: the plan, the transition log, and
#: every canon file. Not the scene prose — a prose revision is `prose_changed`
#: and `audit_stale`, which say something more specific than "regenerate".
def _body_paths(project_dir: str, plan: list[dict[str, str]]) -> list[str]:
    """Every prompt body the packet inlines, resolved the way `_body_for` does.

    Through each row's `prompt_file` cell, falling back to
    `ill.default_prompt_rel` — **not** by listing
    `reference/illustration-prompts/`. A directory listing missed two supported
    shapes outright: a project that has not run `migrate` keeps its bodies under
    the legacy path via that column, and a declared path elsewhere is
    legitimate (`test_step9_leaves_an_unrelated_prompt_file_cell_alone`). For
    both, editing a body left `--diagnose` reporting "built and current" over a
    packet inlining the old prose.
    """
    paths: list[str] = []
    for row in plan:
        illus_id = (row.get('id') or '').strip()
        if not illus_id:
            continue
        rel = ((row.get('prompt_file') or '').strip()
               or ill.default_prompt_rel(illus_id))
        paths.append(os.path.join(project_dir, rel))
    return paths


def _packet_sources(project_dir: str) -> tuple[list[str], list[str]]:
    """`(paths, problems)` — every file the packet is assembled from.

    The prompt bodies are among them since #306. Before, the packet named their
    path and the author opened them separately, so their mtime said nothing about
    the packet; now `--package` inlines each body into an image prompt, and a
    body rewritten after the last run is exactly the staleness this reports.

    A non-empty `problems` means freshness cannot be judged, which the caller
    must report as *unknown* rather than render as current.
    """
    problems: list[str] = []
    sources = [ill.plan_path(project_dir), vs.state_path(project_dir)]
    canon_dir = os.path.join(project_dir, canon.CANON_DIR)
    if os.path.isdir(canon_dir):
        try:
            sources.extend(canon._walk_canon_files(canon_dir))
        except OSError as exc:
            problems.append(f'{canon.CANON_DIR} could not be walked '
                            f'({exc.strerror or exc})')
    sources.extend(_body_paths(project_dir, ill.read_plan(project_dir)))
    return [path for path in sources if os.path.isfile(path)], problems


def _packet_written_files(project_dir: str) -> tuple[list[str], list[str]]:
    """`(paths, problems)` — every file `--package` writes.

    `packet_stale` takes the *oldest* of these. Root files only would miss a
    source rewritten between the image-prompt writes and the root-file writes of
    the same run — a narrow window, but the whole finding is about a packet that
    looks current and is not.

    The listing is guarded. An unguarded `os.listdir` here raised
    `PermissionError` straight out of `validate_plan`, which is the single
    finding collector — one unreadable directory took down the whole
    illustration health report, including the blocking findings `cmd_validate`
    gates on. That is the regression a prior round fixed for `ill.sha256_of`
    (#298), reintroduced by #306.
    """
    written = [packet_file(project_dir, name) for name in PACKET_FILES]
    problems: list[str] = []
    prompts = image_prompts_dir(project_dir)
    if os.path.isdir(prompts):
        try:
            written.extend(
                os.path.join(prompts, name)
                for name in sorted(os.listdir(prompts))
                if name.endswith('.md'))
        except OSError as exc:
            problems.append(f'{os.path.join(PACKET_DIR, IMAGE_PROMPTS_SUBDIR)} '
                            f'could not be read ({exc.strerror or exc})')
    return ([path for path in written if os.path.isfile(path)], problems)


def _missing_image_prompts(project_dir: str) -> list[str]:
    """Live plan rows with no upload file, in reading order.

    mtime cannot see this. `is_built` keys on the root files, and on a *rebuild*
    those already exist from the previous run — so a failure inside
    `_write_image_prompts`, which clears before it writes, left `--diagnose`
    printing "built and current" over the directory the author had been told to
    upload from. The write-order argument only ever covered a first build.

    An id that cannot name a file is skipped rather than reported: it is
    `ill.illegal_plan_ids`' finding, `run_package` refuses on it before writing,
    and `image_prompt_file` would raise out of a read-only health check.
    """
    directory = image_prompts_dir(project_dir)
    if not os.path.isdir(directory):
        return []
    missing: list[str] = []
    for row in rows_in_reading_order(project_dir):
        illus_id = row['id'].strip()
        if not ill._ID_RE.match(illus_id):
            continue
        if not os.path.isfile(os.path.join(directory, f'{illus_id}.md')):
            missing.append(illus_id)
    return missing


def packet_stale(project_dir: str) -> list[ill.IllustrationFinding]:
    """Report a packet older than the plan, the state log, or any canon file.

    The packet is a render, so an out-of-date one is not a conflict to merge —
    it is a `--package` away. What makes it worth a finding is that a stale
    packet looks exactly like a fresh one to the author working through it, and
    a session generating twenty images from last week's plan is expensive.

    Compared by mtime, strictly: a source written in the same clock tick as the
    packet is the ordinary `--package` run itself, not staleness.

    **Also reports an image prompt missing for a live plan row** — see
    `_missing_image_prompts` — and **says so when freshness could not be judged
    at all**, because `--diagnose` renders an empty list as "built and current".

    **What it does not check** is the *content* of an image prompt against what
    `render_image_prompt` would produce now, so a hand-edit of a file the packet
    documents as a render goes undetected. Stated here rather than left for this
    finding's silence to imply otherwise.
    """
    if not is_built(project_dir):
        return []
    written, write_problems = _packet_written_files(project_dir)
    sources, source_problems = _packet_sources(project_dir)
    problems = write_problems + source_problems
    if problems:
        detail = '; '.join(problems)
        log(f'WARNING: the packet\'s freshness could not be checked: {detail}')
        return [{
            'kind': 'packet_stale',
            'file': os.path.join(PACKET_DIR, 'README.md'),
            'detail': f'the packet\'s freshness could not be checked '
                      f'({detail}), so it is unknown rather than current. Fix '
                      f'that and re-run `storyforge illustrate --diagnose`.',
        }]

    missing = _missing_image_prompts(project_dir)
    if missing:
        log(f'WARNING: {len(missing)} plan row(s) have no image prompt in the '
            f'packet: {", ".join(missing)}')
        return [{
            'kind': 'packet_stale',
            'file': os.path.join(PACKET_DIR, IMAGE_PROMPTS_SUBDIR),
            'detail': f'{len(missing)} live plan row(s) have no upload file in '
                      f'{PACKET_DIR}/{IMAGE_PROMPTS_SUBDIR}/ '
                      f'({_and_more(missing)}) — the packet is half-written, '
                      f'not merely out of date. Re-run `storyforge illustrate '
                      f'--package`.',
        }]

    packet_mtime = min(os.path.getmtime(path) for path in written)
    newer = sorted(os.path.relpath(path, project_dir)
                   for path in sources
                   if os.path.getmtime(path) > packet_mtime)
    if not newer:
        return []
    log(f'WARNING: the illustration packet is older than {len(newer)} of its '
        f'source file(s): {", ".join(newer)}')
    return [{
        'kind': 'packet_stale',
        'file': os.path.join(PACKET_DIR, 'README.md'),
        'detail': f'the packet is older than {len(newer)} file(s) it was '
                  f'assembled from ({", ".join(newer)}) — regenerate it with '
                  f'`storyforge illustrate --package` before generating from '
                  f'it.',
    }]
