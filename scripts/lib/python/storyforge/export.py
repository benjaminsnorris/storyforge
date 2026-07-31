"""What goes into the self-contained illustration export, and how it stales.

`--package` and `--export` produce two different artifacts for two different
consumers, and the difference is the whole reason this module exists beside
`packet.py`:

- **The packet** is for a long-running session that reads `canon.md` once and
  keeps it in context. Its entries are deliberately 80–120 words, because lived
  experience on a twenty-illustration book is that hyper-detailed leaf prompts
  underperform while shared reference material does better. Its reference images
  are *paths*, because the author is at the repo and a copy is a second thing to
  invalidate.
- **The export** is for handing one image over — to a browser session, to
  someone who does not have the repo, to a tool that takes an upload. There,
  every one of the packet's economies is a hole: the model-authored prose lives
  in a second file, the state lives in a third, and a zip of the bundle contains
  no art at all. So the export is **complete by construction**: one directory
  per illustration, holding one contiguous paste-ready block and the actual
  reference image files (#298).

The packet is therefore not amended to aggregate the prompt bodies. Inlining a
250–400 word model-authored body per entry would blow the budget that is the
packet's reason for existing and rebuild the twenty-independent-prompts shape it
replaced. What the packet does instead is name the convention once — see
`prompts_packet.render_illustrations` — and point at this command.

Everything derived from a plan row comes through `packet`: `entry_for` — which is
where `state_for_row`, `contrast_for_row`, and `ill.stale_render_reason` are
applied — and the gap collectors `book_level_gaps`, `audit_gaps`, and
`stale_render_gaps`. Not for brevity: so an export and a packet built in the same
run cannot describe one row's costume differently, which is the failure #297 was
filed about and the reason those functions are single-sourced at all.

Resolution, structure, and staleness only: `prompts_export.py` renders and
`cmd_illustrate.run_export` writes.
"""

import json
import os
import shutil
from typing import TYPE_CHECKING, Literal, TypedDict

from storyforge import canon
from storyforge import illustrations as ill
from storyforge import packet
from storyforge import prompts_illustrate as pi
from storyforge import visual_state as vs
from storyforge.common import log

if TYPE_CHECKING:  # pragma: no cover - typing only
    # `cmd_illustrate` imports this module, so the real type cannot be imported
    # at module scope. Only the annotation needs it, and annotating it `object`
    # cost the one argument check that mattered on the `_references_for` call.
    from storyforge.cmd_illustrate import StyleReference

#: Project-relative home of the export. Beside the packet under `manuscript/`,
#: for the same reason: it is a production artifact regenerated wholesale, not
#: reference material the author edits.
EXPORT_DIR = os.path.join('manuscript', 'illustration-export')

#: The files at the export root, read once and shared by every unit. Same order
#: `--export` writes and reports them.
SHARED_FILES: tuple[str, ...] = ('README.md', 'canon.md', 'acceptance.md')

PROMPT_FILENAME = 'prompt.md'
MANIFEST_FILENAME = 'manifest.json'
REFERENCES_SUBDIR = 'references'

#: The pixel size each aspect is generated at, recorded in `manifest.json` so a
#: render is reproducible two weeks later. GPT Image 2's portrait and landscape
#: shapes; `orientation_clause` states the same ratios in prose to the model,
#: which cannot be given a pixel count directly.
SIZES: dict[pi.Aspect, str] = {
    'portrait': '1024x1536',
    'landscape': '1536x1024',
    'square': '1024x1024',
}

#: Recorded rather than chosen per row. Interior art is the one part of a book
#: that cannot be fixed in proof, and the cost difference is a few cents against
#: a re-render.
QUALITY = 'high'

#: Where a unit's body came from. `'plan_row'` is not a silent fallback: it is
#: named in the unit's own `prompt.md`, in `README.md`, and in `manifest.json`,
#: because a block assembled from three plan cells reads like a complete prompt
#: and is not one.
BodySource = Literal['prompt_file', 'plan_row']

#: Whether this run covered the whole plan or a named subset. **Not a bool**: the
#: two questions a bool was answering diverge on an empty plan. `README.md` must
#: not call an empty plan a partial export, while nothing may delete a bundle on
#: the strength of a plan that read as zero rows — which `ill.read_plan` returns
#: for a file that is missing, renamed, or mid-merge. One flag answering both
#: deleted every unit directory and logged that the illustrations were "no longer
#: in the plan", which was false about the cause.
ExportScope = Literal['whole-plan', 'subset']


class ExportReference(TypedDict):
    """One reference image copied into a unit, in upload order.

    `sha256` is the digest of the bytes copied, which is what makes the
    invalidation concern the packet raises answerable rather than merely real:
    `export_stale` re-hashes **both** ends — the source (a re-render replaced it)
    and the copy in the unit directory (the bundle is missing it or holding
    something else). Checking only the source would leave the file the reader
    actually uploads unverified.
    """
    order: int
    #: Export-relative, e.g. `references/1-cover-illustration.png`. What the
    #: manifest's reader uploads.
    file: str
    #: Project-relative path the copy was made from, as the reference list gave
    #: it — a symlink included, so the author recognizes the name.
    source: str
    #: What the source resolved to when it was a symlink, '' otherwise. A zip
    #: preserving a dangling link is worse than a copy, so links are resolved on
    #: copy and the target recorded.
    resolved_from: str
    sha256: str
    purpose: str


class ExportUnit(packet.Entry):
    """One illustration's directory: everything needed to generate that image.

    **Inherits `packet.Entry` rather than re-declaring its fields.** The first
    version copied eleven of them, which had two costs: a field added to `Entry`
    reached the export silently never (a duplication has no failure mode a unit
    test can see until a renderer wants the missing field), and `aspect` was
    re-declared as `pi.Aspect` over `Entry`'s `str`, laundering a type nothing
    checks into a `SIZES[...]` lookup that would `KeyError` partway through
    writing a bundle. Inheritance is also why the entry's `in_frame` keeps its
    name here: a second name for one concept across two modules is the drift
    surface this PR's shared derivation exists to remove.

    Carrying the whole entry means a few of its fields reach no renderer — `beat`
    and `in_frame` arrive inside the model's own `### Scene` / `### Subject`
    sections, and `_derived_body` reads the plan row directly. That is a
    deliberate "the unit carries the entry", not a set of write-only fields.
    """
    model: str
    size: str
    quality: str
    #: The model-authored prose, or the plan-derived stand-in. Never '': a unit
    #: with nothing to say says so in the block itself.
    body: str
    body_source: BodySource
    #: The prompt file consulted for `body`, whether or not it yielded prose. See
    #: `_Body.path` for why it is recorded even when nothing was read from it.
    prompt_source: str
    references: list[ExportReference]
    #: The reference chain's own disclosures for this unit — a cover-only list, a
    #: render excluded as pre-canon, the four-image cap. Kept apart from
    #: `warnings` because they are informational: merged, an unavoidable note
    #: about a book with no ingested art yet sat above every unit's genuine
    #: blockers. `resolve` aggregates these into `README.md` by note.
    chain_notes: list[str]
    #: What the person working this directory needs told, in the file they are
    #: reading. **Not** aggregated into `README.md` — a warning that reaches only
    #: this list reaches only this unit's `prompt.md`, which is why the
    #: project-wide causes behind them are accumulated separately by `resolve`.
    warnings: list[str]


class ExportContents(TypedDict):
    """Everything the renderers need, plus the record of what is missing."""
    units: list[ExportUnit]
    book_level: dict[str, str]
    anchors: dict[str, str]
    labels: dict[str, str]
    #: Every aspect the exported units use, in canonical order, so
    #: `acceptance.md` states the orientation rule for those and no others.
    aspects: list[pi.Aspect]
    gaps: list[str]
    #: Whether this run covered every live plan row. A subset export leaves
    #: directories it did not write, and `README.md` must not read as a full one.
    scope: ExportScope
    #: Every live plan row's id — what `prune_units` is entitled to keep. Carried
    #: rather than recomputed so the caller cannot substitute the *exported* set,
    #: which for a subset run would delete everything it was not asked about.
    live_ids: frozenset[str]
    #: Unit directories already on disk that this run did not write. Empty on a
    #: `whole-plan` run, where those directories are pruned instead.
    untouched: list[str]


# ============================================================================
# Paths
# ============================================================================

def export_dir(project_dir: str) -> str:
    """Absolute path to the export directory, whether or not it exists."""
    return os.path.join(project_dir, EXPORT_DIR)


def shared_file(project_dir: str, name: str) -> str:
    """Absolute path to one shared export file."""
    return os.path.join(export_dir(project_dir), name)


def unit_dir(project_dir: str, illus_id: str) -> str:
    """Absolute path to one illustration's export directory.

    **Validates the id, because this path is written to and deleted from.**
    `copy_references` `rmtree`s `<unit>/references/`, so a plan `id` of
    `../../evil` — reachable by a hand-edit typo, since the plan is a documented
    hand-edit surface — escapes the export tree and destroys a directory nobody
    named. `run_export` refuses such a plan up front with a message; this raise is
    the guard that keeps a future caller from bypassing that check, and it uses
    the same `ill._ID_RE` that `validate_plan`'s `invalid_id` finding enforces.
    """
    if not ill._ID_RE.match(illus_id.strip()):
        raise ValueError(
            f'refusing to build an export path from illustration id '
            f'{illus_id!r}: ids must start with a letter or digit and hold only '
            f'letters, digits, hyphens, and underscores. Run `storyforge '
            f'validate` — this is the plan\'s `invalid_id` finding.')
    return os.path.join(export_dir(project_dir), illus_id.strip())


def is_built(project_dir: str) -> bool:
    """True when every shared export file exists.

    **Deliberately weaker than `packet.is_built`, which requires all six packet
    files including the payload.** A bundle with no units is a legitimate shape
    here (an empty plan, or a `--ids` run mid-flight), so requiring one would
    report a valid export as unbuilt. What is *not* legitimate is a bundle whose
    reader has no `canon.md` and no acceptance criteria, which is what these three
    files are.

    That leaves a window `packet.is_built` does not have, and it is closed
    elsewhere rather than here: `run_export` writes the units *before* the shared
    files, so this flips True only after the whole tree exists, and `export_stale`
    reports a unit missing its `prompt.md` or a copied reference. Before both, an
    interrupted run left `is_built` True and `--diagnose` printing `built and
    current` over zero directories.
    """
    return all(os.path.isfile(shared_file(project_dir, name))
               for name in SHARED_FILES)


def existing_units(project_dir: str) -> list[str]:
    """Ids of the unit directories currently on disk, sorted.

    A directory counts as a unit only when its name is a legal illustration id
    **and** it holds a `manifest.json` this command wrote. `prune_units` deletes
    from this list, so a directory an author put in the export by hand is never a
    deletion candidate — and the id check is what keeps `unit_dir`'s validation
    from turning a stray directory name into a crash on the way to that decision.
    """
    root = export_dir(project_dir)
    if not os.path.isdir(root):
        return []
    return sorted(
        name for name in os.listdir(root)
        if ill._ID_RE.match(name)
        and os.path.isfile(os.path.join(root, name, MANIFEST_FILENAME)))


# ============================================================================
# Resolution
# ============================================================================

def resolve(project_dir: str, *, ids: set[str] | None = None,
            canon_cutoff: str | None = None) -> ExportContents:
    """Collect what the export says, recording every gap rather than filtering.

    Deterministic and side-effect free apart from log lines and the digests it
    reads, so two runs over unchanged sources produce identical bytes — the
    packet's idempotence contract, and for the same reason: an export is a render,
    so a hand edit is lost on the next run and must never be the only copy of
    something.

    `ids` narrows to a subset, and it narrows **after** the ordering pass: the
    plan handed to `packet.state_context` and `packet.rows_in_reading_order` is
    always the whole plan. Reading order is a statement about the book, so a
    one-row plan would make that row its own book-start and strip the contrast
    clause it has in the full book — #297's shape, inside the fix.
    """
    from storyforge import cmd_illustrate

    if canon_cutoff is None:
        canon_cutoff = canon.newest_canon_updated(project_dir)

    plan = ill.read_plan(project_dir)
    context = packet.state_context(project_dir, plan=plan,
                                   canon_cutoff=canon_cutoff)
    all_rows = packet.rows_in_reading_order(project_dir, plan=plan,
                                            order=context['order'])
    rows = ([r for r in all_rows if r['id'].strip() in ids]
            if ids is not None else all_rows)

    gaps: list[str] = list(packet.book_level_gaps(project_dir,
                                                  bundle='export'))
    if not context['anchors']:
        gaps.append(
            'no entity canon file has a populated Embeddable block — nothing '
            'in this export holds a character or a place to one design across '
            'the set. Run `storyforge illustrate --direction`.')
    if not all_rows:
        gaps.append(
            'the illustration plan has no rows — this export describes no '
            'illustrations. Run `storyforge illustrate --plan`.')
    elif not rows:
        gaps.append(
            'none of the requested ids match a live plan row, so this export '
            'contains no illustrations.')

    style = cmd_illustrate.resolve_style_reference(
        project_dir, canon_cutoff=canon_cutoff)
    gaps.extend(cmd_illustrate.style_reference_warnings(style))

    # A gap rather than a log line, unlike `cmd_illustrate._anchor_labels`. The
    # export exists to be read away from the terminal that built it, so its
    # coverage facts belong in `README.md` — and routing this one through the log
    # instead would have printed the same WARNING twice whenever `--package` and
    # `--export` ran together, which is the duplicated-walk defect #300 records.
    guessed = sorted(cid for cid, label in context['labels'].items()
                     if label['source'] == 'slug')
    if guessed:
        gaps.append(
            f'{len(guessed)} continuity anchor(s) have no recorded display '
            f'name and are labeled from their id in canon.md '
            f'({", ".join(guessed)}) — that label is a guess. Add '
            f'`display_name:` to the canon file, or a `name` to the registry '
            f'row, if the title-cased slug reads wrong.')

    units: list[ExportUnit] = []
    # Aggregated `cause -> ids`, not appended per row. One project-wide cause
    # behind twenty rows is twenty near-identical README bullets and twenty
    # near-identical WARNINGs, in the section whose value is proportional to its
    # signal-to-noise — the pattern `_warn_unanchored_rows` and
    # `stale_render_gaps` already collapse (#290). The per-*unit* sentence stays
    # in that unit's `prompt.md`: two readers, not two gaps.
    causes: dict[str, list[str]] = {}
    notes: dict[str, list[str]] = {}
    for row in rows:
        unit, unit_gaps = _unit_for(project_dir, row, context=context,
                                    plan=plan, canon_cutoff=canon_cutoff,
                                    style=style, causes=causes, notes=notes)
        units.append(unit)
        gaps.extend(unit_gaps)
    for cause, affected in causes.items():
        gaps.append(f'{len(affected)} of {len(rows)} illustration(s) '
                    f'{cause} ({", ".join(affected)})')
    # The reference chain's own disclosures — a cover-only list, a render excluded
    # as pre-canon, the four-image cap. `--prompts` only logs these and that is
    # enough there, because the author is watching the run; the export is read
    # hours later and away from that terminal, so a note reaching only one unit's
    # `prompt.md` reached nobody looking at README's enumerated count.
    for note, affected in notes.items():
        gaps.append(f'{len(affected)} of {len(rows)} illustration(s): {note} '
                    f'({", ".join(affected)})')

    gaps.extend(packet.audit_gaps(project_dir, bundle='export'))
    # Over the rows in this export, not the whole plan: a gap naming rows the
    # bundle does not contain sends the reader looking for a directory that is
    # not there. `--diagnose` is where the whole plan's staleness is reported.
    gaps.extend(packet.stale_render_gaps(project_dir, rows, canon_cutoff))

    used = {unit['aspect'] for unit in units}
    exported = {unit['id'] for unit in units}
    live_ids = frozenset(r['id'].strip() for r in all_rows)
    # Set-covering rather than `ids is None`, so naming every live row explicitly
    # is not reported as partial. An empty plan is `whole-plan` too — README must
    # not call it a partial export — which is safe only because `prune_units`
    # takes `live_ids` and refuses an empty one; when this was a single `complete`
    # bool it was also the delete authority, and an unreadable plan wiped the
    # bundle.
    scope: ExportScope = ('whole-plan' if exported >= live_ids else 'subset')
    return {
        'units': units,
        'book_level': pi.book_level_direction(project_dir),
        'anchors': context['anchors'],
        'labels': {cid: label['label']
                   for cid, label in context['labels'].items()},
        'aspects': [a for a in pi.ASPECTS if a in used] or [pi.DEFAULT_ASPECT],
        'gaps': gaps,
        'scope': scope,
        'live_ids': live_ids,
        # Empty on a whole-plan run: those directories are about to be pruned, so
        # naming them as "still here from an earlier run" would describe a state
        # that ends microseconds later.
        'untouched': ([] if scope == 'whole-plan' else
                      [i for i in existing_units(project_dir)
                       if i not in exported]),
    }


def _unit_for(project_dir: str, row: dict[str, str], *,
              context: packet.RowContext, plan: list[dict[str, str]],
              canon_cutoff: str, style: 'StyleReference',
              causes: dict[str, list[str]],
              notes: dict[str, list[str]]) -> tuple[ExportUnit, list[str]]:
    """Build one unit and the export-level gaps found while building it.

    `causes` and `notes` are accumulators the caller aggregates `cause -> ids`
    after the loop. Per-row appends to `gaps` are for facts about *that* row; a
    project-wide cause (no prompt files yet, a cover-only reference chain) goes
    here instead, because twenty near-identical README bullets is what teaches an
    author to skip the section the real warnings live in (#290).
    """
    entry, gaps = packet.entry_for(row, context=context)
    illus_id = entry['id']
    warnings: list[str] = []

    body = _body_for(project_dir, row)
    if body['warning']:
        warnings.append(body['warning'])
        causes.setdefault(body['cause'], []).append(illus_id)
    if entry['stale_reason']:
        warnings.append(
            f'this illustration already has art, and {entry["stale_reason"]}. '
            f'Generate it again from this block; do not demote its `status`.')
    if not entry['state']:
        warnings.append(
            'no visual state resolved for this illustration, so the costume, '
            'the lighting, and any damage below are the model\'s inference '
            'rather than a read of the book\'s schedule.')

    # Two out-lists, because they are different kinds of fact and land in
    # different places. `chain` holds `_references_for`'s disclosures — a
    # cover-only list, a pre-canon exclusion, the four-image cap — which are
    # informational and are aggregated into README; `problems` holds this module's
    # own failures, which are blockers for this image and belong in the unit's
    # "Read this first" beside the other three. Merging them put an unavoidable
    # note about a book with no ingested art at the top of every unit, above the
    # genuine blockers.
    chain: list[str] = []
    problems: list[str] = []
    references = _references_for_unit(
        project_dir, illus_id, plan=plan, canon_cutoff=canon_cutoff,
        style=style, notes=chain, problems=problems)
    warnings.extend(problems)
    for note in chain:
        notes.setdefault(note, []).append(illus_id)
    if not references:
        gaps.append(
            f'illustration `{illus_id}` has no reference images at all, so its '
            f'directory carries no style or likeness anchor — whatever is '
            f'generated from it sets the look for everything that references it.')

    unit: ExportUnit = {
        **entry,
        'model': pi.DEFAULT_IMAGE_MODEL,
        'size': SIZES[entry['aspect']],
        'quality': QUALITY,
        'body': body['text'],
        'body_source': body['source'],
        'prompt_source': body['path'],
        'references': references,
        'chain_notes': chain,
        'warnings': warnings,
    }
    return unit, gaps


class _Body(TypedDict):
    """A unit's paste-block prose, where it came from, and what to say about it.

    One bag rather than a four-tuple because `path` and `source` are one fact
    about one file, and the pair `('prompt_file', '')` is not a state that can
    exist — a tuple invited exactly that, and losing the path is how `export_stale`
    went blind to art direction appearing at the default path.
    """
    text: str
    source: BodySource
    #: The prompt file that was *consulted*, whether or not it existed or parsed.
    #: Recorded unconditionally so `export_stale` can notice a file appearing
    #: there: `_body_for` picks up `ill.default_prompt_rel` with no plan edit, and
    #: `parse_prompt_file`'s docstring invites hand-authoring, so an author who
    #: writes one by hand would otherwise get a bundle reporting itself current
    #: over a three-cell stand-in.
    path: str
    #: The sentence for this unit's "Read this first", '' when there is nothing to
    #: say.
    warning: str
    #: The project-wide phrasing `resolve` aggregates `cause -> ids`. Names the
    #: shared root cause, not this row.
    cause: str


def _body_for(project_dir: str, row: dict[str, str]) -> _Body:
    """The model-authored prose for a row, or a stand-in — plus why.

    A missing, unreadable, or unparseable prompt file is **not** a refusal: an
    export costs nothing to produce, so the useful behaviour is to build the
    bundle and say what is thin about it — the posture `run_package` takes. It is
    also not silent, in either artifact: a paste block assembled from three plan
    cells reads exactly like a complete prompt, and an author who cannot tell the
    difference generates from it.

    A **declared** `prompt_file` that does not exist gets its own sentence. That
    is the #299 class — an author who typed a path meant that path, so the prose
    usually exists somewhere (moved, renamed, uncommitted) and the action is to
    find it, which is a different action from "generate it again".

    A body whose own prose carries a `Constraints` heading is used and *reported*
    (`body_truncated`): the parse cuts at the first such heading to keep stale
    constraints out of the paste block, which means anything the model wrote after
    it — often `### Use case` — is dropped. Reporting rather than silently
    substituting the plan row follows #293: a truncation every consumer accepts is
    worse than an absence, so it is said out loud.
    """
    illus_id = row['id'].strip()
    declared = (row.get('prompt_file') or '').strip()
    rel = declared or ill.default_prompt_rel(illus_id)
    path = os.path.join(project_dir, rel)
    plan_row = _derived_body(row)
    tail = (f'so its paste block is assembled from the plan row alone — the '
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
                         'paste blocks come from the plan row',
            }
        return {
            'text': plan_row, 'source': 'plan_row', 'path': rel,
            'warning': f'this illustration has no written art direction, {tail}. '
                       f'Run `storyforge illustrate --prompts --ids {illus_id}` '
                       f'first for a stronger prompt.',
            'cause': 'have no written art direction, so their paste blocks come '
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
                       f'its permissions or delete the file, then re-export.',
            'cause': 'have a prompt file that could not be read, so their paste '
                     'blocks come from the plan row',
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
                       f'case`) is **not** in the block below. Demote that '
                       f'heading in `{rel}` and re-export.',
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
        'cause': 'have a prompt file with no usable prompt body, so their paste '
                 'blocks come from the plan row',
    }


def _derived_body(row: dict[str, str]) -> str:
    """A paste block built from the plan row, in the prompt file's own shape.

    Four sections rather than free prose, because the whole export is written for
    a model that was tuned on the 5-section template (#260/#263) — and because a
    stand-in shaped like the real thing is how a reader sees at a glance which
    parts are thin. `packet.NOT_RECORDED` is deliberately not reused: it points
    at README gaps, and this file may be read on its own.
    """
    def cell(key: str) -> str:
        return (row.get(key) or '').strip()

    unwritten = '_(not recorded in the plan)_'
    details = [f'- {label}: {cell(key) or unwritten}' for label, key in (
        ('Palette', 'palette'), ('Composition', 'composition'),
        ('Mood', 'mood'), ('Motifs to carry', 'motifs'))]
    return '\n'.join([
        '### Scene', '',
        cell('beat') or unwritten, '',
        '### Subject', '',
        cell('subject') or unwritten, '',
        '### Important details', '',
        '\n'.join(details), '',
        '### Use case', '',
        'Interior illustration for a novel.',
    ])


def _references_for_unit(project_dir: str, illus_id: str, *,
                         plan: list[dict[str, str]], canon_cutoff: str,
                         style: 'StyleReference',
                         notes: list[str],
                         problems: list[str]) -> list[ExportReference]:
    """Resolve this illustration's reference list into copy instructions.

    Reuses `--prompts`' own builder, so the export inherits its exclusions —
    the cover artwork rather than the typeset cover, and no render older than the
    newest `canon_updated` — instead of growing a second chain that could
    disagree with the prompt files it aggregates. `rerun='--export'` because those
    disclosures are rendered into *this* bundle, and the packet's wording told the
    reader to regenerate the other one.

    Digests are read here rather than at copy time so resolution is the only place
    that reads a unit's reference bytes, and so a dry run reports exactly what a
    real run would write.

    `notes` takes the chain's informational disclosures; `problems` takes this
    function's own failures. Two lists because they land in different sections —
    see `_unit_for`.
    """
    from storyforge import cmd_illustrate

    references: list[ExportReference] = []
    seen: set[str] = set()
    for rel, purpose in cmd_illustrate._references_for(
            project_dir, illus_id, plan=plan, canon_cutoff=canon_cutoff,
            style=style, notes=notes, rerun='--export'):
        source = os.path.join(project_dir, rel)
        real = os.path.realpath(source)
        if real in seen:
            continue
        try:
            digest = ill.sha256_of(real)
        except OSError as exc:
            # `_references_for` resolved this path with `isfile`, which follows
            # symlinks — so a dangling link never gets here and an absent file
            # never does either. What does get here is a file that exists and
            # cannot be *read*. Skipped with a note rather than allowed to raise,
            # because the alternative is a traceback partway through writing the
            # bundle, and rather than silently dropped because a unit whose
            # manifest promises an upload the directory does not hold is the one
            # failure the whole export exists to make impossible.
            problems.append(
                f'`{rel}` could not be read ({exc.strerror or exc}), so no copy '
                f'of it is in this export and nothing here carries what it was '
                f'for. Fix its permissions and re-run `--export`.')
            log(f'WARNING: {illus_id}: {rel} could not be read '
                f'({exc.strerror or exc}) — it is not in that unit\'s '
                f'{REFERENCES_SUBDIR}/.')
            continue
        seen.add(real)
        order = len(references) + 1
        stem, extension = os.path.splitext(os.path.basename(rel))
        # Keyed on `islink`, not on `realpath != abspath`: on macOS the temp
        # directory a project may live under is itself a symlink, so comparing
        # the two paths reports every reference in the book as symlinked.
        resolved = (_relative_to(real, project_dir)
                    if os.path.islink(source) else '')
        references.append({
            'order': order,
            'file': os.path.join(REFERENCES_SUBDIR,
                                 f'{order}-{stem}{extension.lower()}'),
            'source': rel,
            'resolved_from': resolved,
            'sha256': digest,
            'purpose': purpose,
        })
    return references


def _relative_to(path: str, project_dir: str) -> str:
    """Project-relative when the path is inside the project, absolute otherwise.

    The export's paths reach a bundle that may be handed to someone without the
    repo, so a machine-specific absolute path is disclosed by being visibly
    absolute rather than quietly relativized into `../../..`.

    Compared against the *resolved* project directory, because callers pass a
    resolved path in: on macOS the temp directory a test project lives under is a
    symlink, and relativizing against the unresolved root turns every file inside
    the project into an escape.
    """
    relative = os.path.relpath(path, os.path.realpath(project_dir))
    return path if relative.startswith(os.pardir) else relative


def manifest_for(unit: ExportUnit) -> str:
    """Render one unit's `manifest.json`.

    The reproducible record of what this directory was generated from and with:
    the ids, every reference's digest, and the model, size, quality, and aspect
    the prompt was written for. No timestamp — the export is a render, and two
    runs over unchanged sources must produce identical bytes.
    """
    payload = {
        'id': unit['id'],
        'scene_id': unit['scene_id'],
        'status': unit['status'],
        'layout': unit['layout'],
        'aspect': unit['aspect'],
        'model': unit['model'],
        'size': unit['size'],
        'quality': unit['quality'],
        'treatment': unit['treatment'],
        'prompt': PROMPT_FILENAME,
        'body_source': unit['body_source'],
        'prompt_source': unit['prompt_source'],
        'expected_output': f'{unit["id"]}.png',
        'references': [dict(reference) for reference in unit['references']],
    }
    return json.dumps(payload, indent=2) + '\n'


# ============================================================================
# Writing the structure
# ============================================================================

def copy_references(project_dir: str, unit: ExportUnit) -> int:
    """Copy a unit's reference images in, replacing whatever was there.

    The directory is emptied first: numbering is positional, so a reference
    dropped from the chain would otherwise leave `3-old.png` beside a new
    `3-other.png` and the manifest's upload order would name one of two files
    that both look current.

    Symlinks are resolved on copy — `copyfile` follows them — because a bundle
    that preserved a link is a bundle whose art is missing on the machine it is
    opened on. `copyfile` rather than `copy2` because the copy is identified by
    the `sha256` recorded for it and by nothing else: carrying the source's mode
    bits and mtime into a bundle meant to be zipped and handed on would import
    metadata no consumer reads and `export_stale` deliberately ignores.
    """
    target = os.path.join(unit_dir(project_dir, unit['id']), REFERENCES_SUBDIR)
    if os.path.isdir(target):
        shutil.rmtree(target)
    if not unit['references']:
        return 0
    os.makedirs(target, exist_ok=True)
    copied = 0
    for reference in unit['references']:
        source = os.path.realpath(
            os.path.join(project_dir, reference['source']))
        shutil.copyfile(source, os.path.join(
            unit_dir(project_dir, unit['id']), reference['file']))
        copied += 1
    return copied


def prune_units(project_dir: str, *,
                live_ids: frozenset[str]) -> list[str]:
    """Delete unit directories for ids that have left the plan. Returns the ids.

    Only called when `ExportContents['scope']` is `whole-plan` — a subset run has
    no business deleting the units it was not asked about, and `README.md` names
    those as untouched instead.

    `live_ids` is the **plan's** id set, never the exported subset, and an empty
    one prunes nothing. That refusal is the point: `ill.read_plan` returns `[]`
    for a plan file that is missing, renamed, or mid-merge, so an empty set is
    overwhelmingly a lost plan rather than an author who deleted every
    illustration — and a wipe authorized by a missing file is not a wipe
    authorized by a changed plan. The old signature took a `keep` set built from
    the exported ids, which for an empty plan was empty, `scope` was vacuously
    whole-plan, and the whole bundle went with a log line blaming rows that had
    not moved.

    Note a `superseded` row *is* still in the plan: `rows_in_reading_order` drops
    it, so its directory is pruned, which is right — retired art must not sit in a
    bundle someone is about to work through — and is why this is worded as "left
    the plan" rather than "was removed from it".

    Only directories holding a `manifest.json` this command wrote are candidates
    (see `existing_units`), so a directory an author added by hand survives.
    """
    if not live_ids:
        log('WARNING: the plan resolved to no rows, so nothing was pruned from '
            f'the export. If the plan really is empty, delete {EXPORT_DIR}/ by '
            f'hand — a plan that reads as zero rows is more often a moved or '
            f'unreadable {ill.PLAN_FILENAME} than an emptied one.')
        return []
    removed: list[str] = []
    for illus_id in existing_units(project_dir):
        if illus_id in live_ids:
            continue
        shutil.rmtree(unit_dir(project_dir, illus_id))
        removed.append(illus_id)
    return removed


# ============================================================================
# Staleness
# ============================================================================

def _read_manifest(path: str) -> dict | None:
    """Parse one manifest, or None when it cannot be read."""
    try:
        with open(path, encoding='utf-8') as f:
            parsed = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def export_stale(project_dir: str) -> list[ill.IllustrationFinding]:
    """Report an export that no longer matches its sources, or cannot be checked.

    One finding with every reason in it, following `packet_stale`: the fix for
    almost all of them is `storyforge illustrate --export`, and splitting one root
    cause across several findings is the noise pattern the packet's own gap
    channel was narrowed to avoid.

    Three kinds of reason, because the export carries three kinds of thing:

    - **mtime**, for what it renders — the plan, the transition log, the canon
      files, and every prompt file it aggregated a body from. Strictly newer, so
      a source written in the same tick as the export is the `--export` run.
    - **digest**, for what it copies. This is what the recorded `sha256` is *for*,
      and it is compared **twice**: against the source (a re-render replaced it)
      and against the copy in the unit directory (the bundle is missing or holding
      a corrupt file). Only the second reading defends the claim that a manifest
      never promises an upload the directory does not hold — `run_export` writes
      `manifest.json` before `copy_references` runs, so an interrupted or failed
      copy leaves exactly that state.
    - **unchecked**, for anything this function could not evaluate — an
      unreadable manifest, a `references` value that is not a list, an entry with
      no recorded digest, an image that exists and cannot be read. Reported
      rather than skipped, because `--diagnose` renders silence here as `built
      and current`, and *"silence must mean checked, never could-not-check"* is
      the rule `ill.staleness_unchecked_finding` and `--audit`'s "Not assessed"
      already follow. These are the reasons `--export` alone may not fix.

    Source digests are memoized for the call: the cover artwork is a reference in
    every unit, so a twenty-illustration export would otherwise hash the same
    file twenty times per `validate_plan` — and `validate_plan` runs from
    `validate`, `cleanup`, and `--diagnose`.

    Returns [] when no export is built — an unbuilt export is in-flight state.
    """
    if not is_built(project_dir):
        return []

    rendered = [shared_file(project_dir, name) for name in SHARED_FILES]
    sources = [ill.plan_path(project_dir), vs.state_path(project_dir)]
    canon_dir = os.path.join(project_dir, canon.CANON_DIR)
    if os.path.isdir(canon_dir):
        sources.extend(canon._walk_canon_files(canon_dir))

    digests: dict[str, str | None] = {}
    reasons: list[str] = []
    for illus_id in existing_units(project_dir):
        directory = unit_dir(project_dir, illus_id)
        rendered.append(os.path.join(directory, MANIFEST_FILENAME))
        prompt = os.path.join(directory, PROMPT_FILENAME)
        if os.path.isfile(prompt):
            rendered.append(prompt)
        else:
            # Reported, not merely left out of the mtime set. A unit with no
            # `prompt.md` has nothing to paste, and omitting the missing file
            # from the freshness comparison is the shape where the absence of
            # the thing being checked removes it from the check.
            reasons.append(f'`{illus_id}` has no {PROMPT_FILENAME}, so that '
                           f'unit holds nothing to generate from')
        manifest = _read_manifest(os.path.join(directory, MANIFEST_FILENAME))
        if manifest is None:
            reasons.append(f'`{illus_id}/{MANIFEST_FILENAME}` could not be '
                           f'read, so that unit cannot be checked at all')
            continue
        source = str(manifest.get('prompt_source') or '')
        if source:
            full = os.path.join(project_dir, source)
            if os.path.isfile(full):
                sources.append(full)
                if str(manifest.get('body_source') or '') == 'plan_row':
                    # The path is recorded even when nothing was read from it, so
                    # that art direction *appearing* at it is detectable. An
                    # author told "run --prompts for a stronger prompt" who
                    # instead writes the file by hand otherwise gets a bundle
                    # reporting itself current over a three-cell stand-in.
                    reasons.append(
                        f'`{illus_id}` now has art direction at `{source}`, '
                        f'which its paste block predates — it was built from the '
                        f'plan row')
            elif str(manifest.get('body_source') or '') == 'prompt_file':
                reasons.append(
                    f'`{illus_id}`\'s art direction `{source}` is gone, so '
                    f're-exporting would fall back to the plan row')
        reasons.extend(_reference_drift(project_dir, illus_id, manifest,
                                        digests))

    export_mtime = min((os.path.getmtime(path) for path in rendered
                        if os.path.isfile(path)), default=0.0)
    newer = sorted(os.path.relpath(path, project_dir) for path in sources
                   if os.path.isfile(path)
                   and os.path.getmtime(path) > export_mtime)
    if newer:
        reasons.append(f'it is older than {len(newer)} file(s) it was '
                       f'assembled from ({", ".join(newer)})')
    if not reasons:
        return []

    log(f'WARNING: the illustration export is out of date or unverifiable: '
        f'{"; ".join(reasons)}')
    return [{
        'kind': 'export_stale',
        'file': os.path.join(EXPORT_DIR, 'README.md'),
        # "no longer matches **or cannot be checked against**": the detail
        # carries unchecked reasons too, and asserting a mismatch over an
        # unreadable manifest would state more than the check established.
        'detail': f'the export no longer matches its sources, or cannot be '
                  f'checked against them — {"; ".join(reasons)}. Regenerate it '
                  f'with `storyforge illustrate --export` before generating '
                  f'from it.',
    }]


def _digest(path: str, digests: dict[str, str | None]) -> str | None:
    """Memoized sha256 of *path*, or None when the file cannot be read.

    `None` is a distinct answer from a mismatching digest and callers must report
    it: an image that exists and cannot be read leaves the copy *unverifiable*,
    not verified. Unguarded, this call took `validate`, `cleanup`, and
    `--diagnose` down with a `PermissionError` — `validate_plan` is the single
    finding collector, so one unreadable image destroyed the whole illustration
    health report including the blocking findings `cmd_validate` gates on.
    """
    if path not in digests:
        try:
            digests[path] = ill.sha256_of(path)
        except OSError:
            digests[path] = None
    return digests[path]


def _reference_drift(project_dir: str, illus_id: str, manifest: dict,
                     digests: dict[str, str | None]) -> list[str]:
    """Reasons a unit's reference images are wrong, missing, or unverifiable.

    Checks the copy *and* the source against the recorded digest. Every path that
    cannot reach a verdict produces a sentence rather than falling through: a
    manifest whose `references` is the wrong shape, or an entry with no digest,
    leaves references unchecked, and `--diagnose` prints `built and current` over
    the result.
    """
    reasons: list[str] = []
    entries = manifest.get('references')
    if not isinstance(entries, list):
        reasons.append(
            f'`{illus_id}/{MANIFEST_FILENAME}` records `references` as '
            f'{type(entries).__name__} rather than a list, so none of that '
            f'unit\'s reference images can be checked')
        return reasons
    for position, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            reasons.append(f'`{illus_id}/{MANIFEST_FILENAME}` reference '
                           f'{position} is not an object, so it cannot be '
                           f'checked')
            continue
        source = str(entry.get('source') or '')
        digest = str(entry.get('sha256') or '')
        copied = str(entry.get('file') or '')
        if not source or not digest:
            reasons.append(
                f'`{illus_id}/{MANIFEST_FILENAME}` reference {position} records '
                f'no {"source path" if not source else "sha256"}, so that image '
                f'cannot be checked')
            continue

        if not copied:
            reasons.append(f'`{illus_id}` records no copied file for '
                           f'`{source}`, so nothing in that unit can be '
                           f'uploaded for it')
        else:
            path = os.path.join(unit_dir(project_dir, illus_id), copied)
            if not os.path.isfile(path):
                reasons.append(f'`{illus_id}/{copied}` is missing, so the '
                               f'manifest promises an upload the directory does '
                               f'not hold')
            else:
                actual = _digest(path, digests)
                if actual is None:
                    reasons.append(f'`{illus_id}/{copied}` could not be read, so '
                                   f'the copy cannot be checked at all')
                elif actual != digest:
                    reasons.append(f'`{illus_id}/{copied}` does not match the '
                                   f'digest recorded for it — the copy in this '
                                   f'export is not the image it claims to be')

        real = os.path.realpath(os.path.join(project_dir, source))
        if not os.path.isfile(real):
            reasons.append(f'`{illus_id}` references `{source}`, which no '
                           f'longer exists')
            continue
        current = _digest(real, digests)
        if current is None:
            reasons.append(f'`{source}` could not be read, so the copy in '
                           f'`{illus_id}/{REFERENCES_SUBDIR}/` cannot be '
                           f'checked against it at all')
        elif current != digest:
            reasons.append(f'`{source}` has changed since it was copied into '
                           f'`{illus_id}/{REFERENCES_SUBDIR}/`')
    return reasons
