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

See benjaminsnorris/storyforge#278 and
docs/superpowers/specs/2026-07-28-illustration-state-matrix-and-packet-design.md.
"""

import os
from collections.abc import Iterable
from typing import Literal, TypedDict, cast

from storyforge import canon
from storyforge import illustrations as ill
from storyforge import prompts_illustrate as pi
from storyforge import visual_state as vs
from storyforge.common import log, normalize_for_comparison

#: Project-relative home of the packet. Under `manuscript/` because it is a
#: production artifact like the assembled chapters, not reference material the
#: author edits — `--package` regenerates it wholesale.
PACKET_DIR = os.path.join('manuscript', 'illustration-packet')

#: The six files, in the order `--package` writes and reports them.
PACKET_FILES: tuple[str, ...] = (
    'README.md', 'canon.md', 'visual-state.md', 'illustrations.md',
    'reference-images.md', 'acceptance.md',
)

#: What an entry says in place of a field the plan never filled. An entry that
#: silently omitted the line would read as "nothing to say here" rather than
#: "nobody wrote this down", and the difference is the whole coverage contract.
NOT_RECORDED = '_(not recorded — see the gaps in README.md)_'


class Entry(TypedDict):
    """One illustration's entry: what is specific to this image and nothing else.

    **The 80–120 word budget governs the derived content** — the beat, the
    subject, the resolved state, the one-sentence contrast, the composition note.
    An author's own `absent` and `contrast` cells sit on top of that and are
    their choice to spend; the budget exists to stop the *renderer* from
    restating what the shared sections already say.

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
    aspect: str
    beat: str
    in_frame: str
    state: str
    absent: str
    contrast: str
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


class PacketContents(TypedDict):
    """Everything the six renderers need, plus the record of what is missing."""
    book_level: dict[str, str]
    anchors: dict[str, str]
    entries: list[Entry]
    references: list[tuple[str, str]]
    #: Why the reference list is shorter than the ingested art suggests —
    #: canon-excluded renders, `--no-prior-refs`, the four-image cap, and a
    #: cover-only or empty chain. Rendered beneath the list in
    #: `reference-images.md`, because a list that silently shrank to the cover
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
    predecessors: dict[str, str] = {}
    previous = ''
    for row in rows_in_reading_order(project_dir, plan=plan, order=order):
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


def is_built(project_dir: str) -> bool:
    """True when every packet file exists.

    All six or none: a half-written packet is a partial handoff, and reporting
    it as built is how an author hands over a bundle with no acceptance
    criteria in it.
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
            canon_cutoff: str | None = None) -> PacketContents:
    """Collect what the packet says, recording every gap rather than filtering.

    Reads the canon tier (phase 1), the visual-state matrix (phase 2), and the
    plan. Deterministic and side-effect free apart from log lines: `--package`
    must be safe to re-run, and the idempotence test compares two calls.

    `canon_cutoff` is threaded to `state_context`, the reference list, and the
    style reference, so one `--package` walks the canon tree once. It was walked
    five times, which logged an unparseable `canon_updated` five times and read
    as five broken files.
    """
    gaps: list[str] = []

    book_level = pi.book_level_direction(project_dir)
    gaps.extend(_book_level_gaps(project_dir))

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

    entries: list[Entry] = []
    for row in rows:
        entry, row_gaps = _entry_for(row, context=context)
        entries.append(entry)
        gaps.extend(row_gaps)

    gaps.extend(_audit_gaps(project_dir))
    gaps.extend(_stale_render_gaps(project_dir, rows,
                                   context['canon_cutoff']))

    # The style reference is resolved once here and handed to both consumers: the
    # reference list embeds it and the gaps report its problems, and resolving it
    # twice walked the canon tree a second time to answer the same question.
    from storyforge import cmd_illustrate
    style = cmd_illustrate.resolve_style_reference(
        project_dir, canon_cutoff=context['canon_cutoff'])
    references, reference_notes = _packet_references(
        project_dir, rows, canon_cutoff=context['canon_cutoff'], style=style)
    # Unconditionally, not behind the composite below. The style reference is the
    # packet's most influential image and the only one always present, and its
    # problems reached exactly one file: `run_package` logs `gaps`, so a stale or
    # mis-declared cover appeared in no log line and no README gap — which made
    # "the packet says what it cannot tell you" an overclaim. Same class as
    # `_book_level_gaps`' "no house style for it", which is already unconditional.
    gaps.extend(cmd_illustrate.style_reference_warnings(style))
    if reference_notes and _has_ingested_art(rows) and len(references) <= 1:
        # The dangerous shape: renders exist on disk and none of them reached
        # the list. The detail is in reference-images.md; this is the line that
        # gets it into README.md, which is where the author looks first.
        gaps.append(
            'the reference-image list is cover-only or empty even though this '
            'book has ingested illustrations — see reference-images.md for '
            'which were excluded and why. Uploading only what is listed means '
            'the next renders carry no likeness reference, which is the drift '
            'the reference chain exists to prevent.')

    return {
        'book_level': book_level,
        'anchors': anchors,
        'entries': entries,
        'references': references,
        'reference_notes': reference_notes,
        'gaps': gaps,
    }


def _stale_render_gaps(project_dir: str, rows: list[dict[str, str]],
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
            f'still ship, and they still need re-rendering. Their entries below '
            f'say so individually; re-render and re-ingest them rather than '
            f'demoting `status`.')
    return gaps


def _has_ingested_art(rows: list[dict[str, str]]) -> bool:
    """Whether any live plan row claims a rendered file."""
    return any((row.get('status') or '').strip() == 'ingested'
               and (row.get('asset_file') or '').strip() for row in rows)


def _book_level_gaps(project_dir: str) -> list[str]:
    """Gaps for the three book-level canon files.

    Absent and scaffolded are separated because the fixes differ: `--direction`
    writes an absent file and is a no-op on one that already exists, so
    conflating them tells an author who has just run it to run it again.
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
            f'packet stops there, so it is shorter than the canon file looks. '
            f'Demote it to `###`, then re-run `--package`.')
    for canon_id in ill.missing_reference_sections(project_dir):
        if canon.resolve_canon_path(project_dir, canon_id) is None:
            gaps.append(
                f'book-level canon `{canon_id}` has no file under '
                f'reference/canon/ — this packet states no house style for it, '
                f'and images generated without it will not look like one '
                f'book. Run `storyforge illustrate --direction`.')
        else:
            gaps.append(
                f'book-level canon `{canon_id}` is still an unfilled scaffold '
                f'— a TODO fed to an image model reads as a deliberate '
                f'instruction, so this packet leaves it out entirely. Edit '
                f'reference/canon/{canon_id}.md directly.')
    return gaps


def _entry_for(row: dict[str, str], *,
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
    subject = (row.get('subject') or '').strip()
    if not subject:
        gaps.append(
            f'illustration `{illus_id}` has no subject — its entry cannot say '
            f'what is in frame. Fill `subject` in '
            f'reference/{ill.PLAN_FILENAME}.')

    state, state_gaps = state_for_row(row, context=context)
    gaps.extend(state_gaps)

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
        'in_frame': subject or NOT_RECORDED,
        'state': state,
        # `absent` is an author-written column the plan schema does not define:
        # `write_plan` preserves columns beyond `PLAN_COLUMNS`, so an author can
        # add it by hand. Deliberately not added to `PLAN_COLUMNS`, because
        # nothing in the pipeline populates it and a write-only column is the
        # mistake `embeds_as` already made. Empty is the normal case — most
        # images have nothing that must be absent.
        'absent': (row.get('absent') or '').strip(),
        'contrast': contrast_for_row(row, context=context),
        'notes': (row.get('composition') or '').strip(),
        'treatment': treatment,
        'stale_reason': ill.stale_render_reason(row, context['canon_cutoff']),
    }
    return entry, gaps


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
    overrides = vs.parse_state_override(row.get('state_override', ''))
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


def contrast_for_row(row: dict[str, str], *, context: RowContext) -> str:
    """What must make this image different from its neighbours.

    Derived from facts on the plan — the reading-order predecessor and the
    `register` extremes — plus anything the author wrote in a `contrast`
    column (author-written, like `absent`, and preserved by `write_plan`
    without being part of the schema). Nothing is invented: twenty independent
    generation calls cannot
    see each other, which is how a set ends up with four images of the same
    two children kneeling around the same lamp.

    **One derived sentence, not three.** The entry exists to be thin, and three
    stacked sentences here spent a tenth of the 80–120 word budget restating two
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
    follows = (f'follows `{previous_id}` and must not repeat its staging'
               if previous_id else '')

    if extreme and follows:
        derived = f'{extreme}; it {follows}.'
    elif extreme:
        derived = f'{extreme}.'
    elif follows:
        derived = f'{follows[0].upper()}{follows[1:]}.'
    else:
        derived = ''

    author = (row.get('contrast') or '').strip()
    return ' '.join(part for part in (derived, author) if part)


def _audit_gaps(project_dir: str) -> list[str]:
    """The contradiction audit's coverage of the prose this packet describes."""
    gaps: list[str] = []
    if not vs.read_provenance(project_dir):
        return [
            'the contradiction audit has never been run — nothing has read '
            'the prose against the visual-state matrix, so this packet may '
            'describe an image of something the book does not do. Run '
            '`storyforge illustrate --audit`.']
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
        style: 'object | None' = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """The labeled reference-image list for the whole packet, and why it is short.

    Reuses `--prompts`' per-illustration builder rather than a second one, so
    the packet inherits its two exclusions: the cover art is the *artwork* and
    not the typeset cover, and a render older than the newest `canon_updated`
    is left out with a WARNING instead of teaching the new session drift the
    current canon exists to remove.

    Files are never copied into the packet — `reference-images.md` carries
    project-relative paths, because a copy is a second thing to invalidate.

    The second element is the exclusion record. `--prompts` only logs those, and
    for a prompt file that is enough because the author is watching the run; the
    packet is read hours later, so the reasons have to be *in* it.
    """
    from storyforge import cmd_illustrate
    notes: list[str] = []
    if canon_cutoff is None:
        canon_cutoff = canon.newest_canon_updated(project_dir)
    references = cmd_illustrate._references_for(
        project_dir, 'the packet', plan=rows,
        canon_cutoff=canon_cutoff, style=style, notes=notes)
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

#: Slot order, and the label each slot carries wherever the batch is reported.
BATCH_SLOTS: tuple[tuple[str, str], ...] = (
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


def anchor_batch(project_dir: str) -> AnchorBatch:
    """The four-slot anchor batch, with every guess disclosed."""
    rows = rows_in_reading_order(project_dir)
    fallback: list[str] = []
    if not rows:
        return {'establisher': '', 'darkest': '', 'brightest': '',
                'later_state': '',
                'fallback': ['the plan has no rows, so there is no anchor '
                             'batch to render. Run `storyforge illustrate '
                             '--plan`.']}

    ids = [row['id'].strip() for row in rows]

    establisher = next((step['id'] for step in ill.render_order(project_dir)
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
    for slot, guess, position in (('darkest', darkest, 'first'),
                                  ('brightest', brightest, 'last')):
        if slot not in by_register:
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

    later_state, later_state_note = _later_state_exemplar(project_dir, rows)
    if later_state_note:
        fallback.append(later_state_note)

    return {'establisher': establisher, 'darkest': darkest,
            'brightest': brightest, 'later_state': later_state,
            'fallback': fallback}


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
                          rows: list[dict[str, str]]) -> tuple[str, str]:
    """The illustration furthest from opening conditions, and any disclosure.

    "Furthest" is counted as the entities it *shows* — the ones its `canon_refs`
    name — whose governing transition is not that entity's first. An image can
    only lock a changed wardrobe if the wardrobe is in it, so counting entities
    the row does not name would pick an image that establishes nothing.

    Ties break to the earliest position, because the batch exists to lock
    designs for everything after it.
    """
    order = ill._scene_order(project_dir)
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
    """Compare every anchor copy in the written packet to its canon source.

    The copies are wrapped in `<!-- canon-embed: id -->` markers, which is the
    convention `canon.find_canon_embeds` already parses and `check_canon_drift`
    already guards for GN page files. Reading the *written file* back is a
    different check from `resolve`'s: this one is the only thing that would
    catch a renderer wrapping or re-indenting a long anchor, or an author
    hand-editing a file whose whole point is being a render.

    Compared after `normalize_for_comparison`, so cosmetic whitespace is not
    drift and a changed word is. Returns [] when no packet is built — an
    unbuilt packet is in-flight state, not a finding.
    """
    findings: list[ill.IllustrationFinding] = []
    directory = packet_dir(project_dir)
    if not os.path.isdir(directory):
        return findings

    sources = canon.anchor_texts(project_dir)
    normalized = {cid: normalize_for_comparison(text)
                  for cid, text in sources.items()}

    for name in PACKET_FILES:
        path = packet_file(project_dir, name)
        if not os.path.isfile(path):
            continue
        rel = os.path.join(PACKET_DIR, name)
        try:
            with open(path, encoding='utf-8') as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            # One unreadable file must not take the whole check down, and must
            # not pass for "no drift" either.
            findings.append({
                'kind': 'anchor_copy_drift',
                'file': rel,
                'detail': f'could not read {rel} to check its anchor copies: '
                          f'{exc}. Re-run `storyforge illustrate --package`.',
            })
            continue
        embeds, unclosed, invalid = canon.find_canon_embeds(text)
        for opener in unclosed:
            findings.append({
                'kind': 'anchor_copy_drift',
                'id': opener['canon_id'],
                'file': rel,
                'detail': f'anchor copy `{opener["canon_id"]}` in {rel} has no '
                          f'closing marker, so its text cannot be checked '
                          f'against reference/canon/. Re-run `storyforge '
                          f'illustrate --package`.',
            })
        for bad in invalid:
            findings.append({
                'kind': 'anchor_copy_drift',
                'file': rel,
                'detail': f'anchor copy marker `{bad["raw_id"]}` in {rel} is '
                          f'not a valid canon id, so its text cannot be '
                          f'checked against reference/canon/. Re-run '
                          f'`storyforge illustrate --package`.',
            })
        for embed in embeds:
            cid = embed['canon_id']
            if cid not in normalized:
                findings.append({
                    'kind': 'anchor_copy_drift',
                    'id': cid,
                    'file': rel,
                    'detail': f'{rel} carries an anchor for `{cid}`, which no '
                              f'longer resolves to a populated canon file — '
                              f'the packet is directing art from an anchor '
                              f'that no longer exists.',
                })
                continue
            if embed['normalized'] != normalized[cid]:
                findings.append({
                    'kind': 'anchor_copy_drift',
                    'id': cid,
                    'file': rel,
                    'detail': f'the anchor copy for `{cid}` in {rel} differs '
                              f'from reference/canon/. Likeness continuity is '
                              f'the string, so re-run `storyforge illustrate '
                              f'--package` rather than editing the packet.',
                })
    return findings


#: Sources whose edit invalidates the packet: the plan, the transition log, and
#: every canon file. Not the scene prose — a prose revision is `prose_changed`
#: and `audit_stale`, which say something more specific than "regenerate".
def _packet_sources(project_dir: str) -> list[str]:
    """Absolute paths of every file the packet is assembled from."""
    sources = [ill.plan_path(project_dir), vs.state_path(project_dir)]
    canon_dir = os.path.join(project_dir, canon.CANON_DIR)
    if os.path.isdir(canon_dir):
        sources.extend(canon._walk_canon_files(canon_dir))
    return [path for path in sources if os.path.isfile(path)]


def packet_stale(project_dir: str) -> list[ill.IllustrationFinding]:
    """Report a packet older than the plan, the state log, or any canon file.

    The packet is a render, so an out-of-date one is not a conflict to merge —
    it is a `--package` away. What makes it worth a finding is that a stale
    packet looks exactly like a fresh one to the author working through it, and
    a session generating twenty images from last week's plan is expensive.

    Compared by mtime, strictly: a source written in the same clock tick as the
    packet is the ordinary `--package` run itself, not staleness.
    """
    if not is_built(project_dir):
        return []
    packet_mtime = min(os.path.getmtime(packet_file(project_dir, name))
                       for name in PACKET_FILES)
    newer = sorted(os.path.relpath(path, project_dir)
                   for path in _packet_sources(project_dir)
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
