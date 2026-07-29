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
from typing import TypedDict

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
    """One illustration's entry: 80–120 words of what is specific to it.

    Everything identical across the set lives in `canon.md` and
    `acceptance.md` instead — the colour prohibitions, the orientation rule,
    no lettering. `state` stays here because it is a *resolution* of the
    visual-state matrix for one scene, not a duplication of the matrix.
    """
    id: str
    scene_id: str
    #: The plan row's status. Carried so an entry for finished art cannot look
    #: identical to one for pending work: the documented flow renders the anchor
    #: batch, ingests it, and regenerates, so the normal mid-flight packet mixes
    #: the two, and README tells the author to work the file top to bottom.
    status: str
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

def rows_in_reading_order(project_dir: str) -> list[dict[str, str]]:
    """Live plan rows in the order a reader meets them.

    Reading order, not render order: `render_order` deliberately hoists the
    visual key to the front, which is right for producing the art and wrong for
    deciding what an illustration's neighbours are. One function so the entries,
    the contrast lines, and the anchor batch cannot end up disagreeing about
    which illustration comes first.
    """
    order = ill._scene_order(project_dir)
    rows = [row for row in ill.read_plan(project_dir)
            if (row.get('status') or '').strip() != 'superseded']
    return sorted(rows, key=lambda r: (
        order.get((r.get('scene_id') or '').strip(), ill._SORTS_LAST),
        r['id'].strip()))


def resolve(project_dir: str) -> PacketContents:
    """Collect what the packet says, recording every gap rather than filtering.

    Reads the canon tier (phase 1), the visual-state matrix (phase 2), and the
    plan. Deterministic and side-effect free apart from log lines: `--package`
    must be safe to re-run, and the idempotence test compares two calls.
    """
    gaps: list[str] = []

    book_level = pi.book_level_direction(project_dir)
    gaps.extend(_book_level_gaps(project_dir))

    anchors = canon.anchor_texts(project_dir)
    if not anchors:
        gaps.append(
            'no entity canon file has a populated Embeddable block — no '
            'illustration in this packet carries a continuity anchor, so '
            'nothing holds a character or a place to one design across the '
            'set. Run `storyforge illustrate --direction`.')

    rows = rows_in_reading_order(project_dir)
    if not rows:
        gaps.append(
            'the illustration plan has no rows — this packet describes no '
            'illustrations. Run `storyforge illustrate --plan`.')

    order = ill._scene_order(project_dir)
    known = vs.known_scene_ids(project_dir)
    transitions = vs.read_transitions(project_dir)
    labels = canon.anchor_display_names(project_dir)

    entries: list[Entry] = []
    previous_id = ''
    for row in rows:
        entry, row_gaps = _entry_for(
            row, project_dir=project_dir, anchors=anchors, labels=labels,
            order=order, known=known, transitions=transitions,
            previous_id=previous_id,
        )
        entries.append(entry)
        gaps.extend(row_gaps)
        previous_id = entry['id']

    gaps.extend(_audit_gaps(project_dir))

    references, reference_notes = _packet_references(project_dir, rows)
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


def _entry_for(row: dict[str, str], *, project_dir: str,
               anchors: dict[str, str], labels: dict[str, canon.AnchorLabel],
               order: dict[str, int], known: set[str],
               transitions: list[vs.Transition],
               previous_id: str) -> tuple[Entry, list[str]]:
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

    state, state_gaps = _state_for(
        row, project_dir=project_dir, anchors=anchors, labels=labels,
        order=order, known=known, transitions=transitions)
    gaps.extend(state_gaps)

    status = (row.get('status') or '').strip() or 'planned'
    treatment = (row.get('treatment') or '').strip()
    if status == 'ingested' and treatment:
        # `--sequence` stages every live row, including finished art, and does
        # not record when it did so. If the staging was assigned after the
        # render, the render does not follow it — and nothing else would say so.
        gaps.append(
            f'illustration `{illus_id}` is already ingested and carries a '
            f'treatment. If the staging was assigned after the render — which '
            f'nothing records — the finished art does not follow it. The packet '
            f'cannot tell which came first, so confirm before you re-render.')

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
        'contrast': _contrast_for(row, previous_id),
        'notes': (row.get('composition') or '').strip(),
        'treatment': treatment,
    }
    return entry, gaps


def _state_for(row: dict[str, str], *, project_dir: str,
               anchors: dict[str, str],
               labels: dict[str, canon.AnchorLabel],
               order: dict[str, int], known: set[str],
               transitions: list[vs.Transition]) -> tuple[str, list[str]]:
    """Resolve the matrix for this scene, then overlay the row's override.

    Only the entities the row's `canon_refs` names, because sending the whole
    cast wastes tokens and invites the model to draw people who are not in the
    frame. An aspect track satisfies a bare canon id — `nora-clothing` covers
    `nora` — matching how `visual_state.prepass` decides the same question.

    A `state_override` entity the row does not name is still included: it was
    written for this image specifically, and dropping it would be the silent
    filtering this module exists to avoid.
    """
    illus_id = row['id'].strip()
    scene_id = (row.get('scene_id') or '').strip()
    refs = ill._split_array(row.get('canon_refs', ''))
    overrides = vs.parse_state_override(row.get('state_override', ''))
    gaps: list[str] = []

    for ref in refs:
        if ref.lower() not in {key.lower() for key in anchors}:
            gaps.append(
                f'illustration `{illus_id}` names canon_refs `{ref}`, which '
                f'resolves to no populated canon file — that entity is '
                f'art-directed with no continuity anchor, so nothing holds it '
                f'to one design.')

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
        resolved = vs._resolve(order, transitions, order[scene_id])

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
                gaps.append(
                    f'illustration `{illus_id}` shows `{ref}` in '
                    f'`{scene_id}`, but no transition states its visual state '
                    f'there. Add a row to {vs.STATE_FILE}, or a '
                    f'`state_override` on the plan row if the state is true '
                    f'in this image only.')
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

    return '; '.join(f'{_entity_label(key, labels)}: {value}'
                     for key, value in parts if value), gaps


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


def _contrast_for(row: dict[str, str], previous_id: str) -> str:
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
    """
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
        project_dir: str, rows: list[dict[str, str]],
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
    references = cmd_illustrate._references_for(
        project_dir, 'the packet', plan=rows,
        canon_cutoff=canon.newest_canon_updated(project_dir), notes=notes)
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
        fallback.append(
            'no illustration names a continuity anchor in `canon_refs`, so '
            'there is no visual key to establish the look — the batch has no '
            'establisher, and whichever image is rendered first will set the '
            'style by accident. Fill `canon_refs` in '
            f'reference/{ill.PLAN_FILENAME}.')

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
