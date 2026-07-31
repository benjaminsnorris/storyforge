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

Everything derived from a plan row comes through `packet`: `entry_for`,
`state_for_row`, `contrast_for_row`, `needs_render`, and the gap collectors. Not
for brevity — so an export and a packet built in the same run cannot describe one
row's costume differently, which is the failure #297 was filed about and the
reason those functions are single-sourced at all.

Resolution, structure, and staleness only: `prompts_export.py` renders and
`cmd_illustrate.run_export` writes.
"""

import json
import os
import shutil
from typing import Literal, TypedDict

from storyforge import canon
from storyforge import illustrations as ill
from storyforge import packet
from storyforge import prompts_illustrate as pi
from storyforge import visual_state as vs
from storyforge.common import log

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


class ExportReference(TypedDict):
    """One reference image copied into a unit, in upload order.

    `sha256` is the copy's digest, which is what makes the invalidation concern
    the packet raises answerable rather than merely real: `export_stale` hashes
    the source again and reports a copy that no longer matches it.
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


class ExportUnit(TypedDict):
    """One illustration's directory: everything needed to generate that image.

    The fields duplicated from `packet.Entry` are *taken* from it rather than
    re-derived — see this module's docstring.
    """
    id: str
    scene_id: str
    status: ill.PlanStatus
    layout: str
    aspect: pi.Aspect
    model: str
    size: str
    quality: str
    beat: str
    subject: str
    state: str
    absent: str
    contrast: str
    treatment: str
    notes: str
    #: The model-authored prose, or the plan-derived stand-in. Never '': a unit
    #: with nothing to say says so in the block itself.
    body: str
    body_source: BodySource
    #: Project-relative prompt file the body came from, '' when there is none.
    prompt_source: str
    references: list[ExportReference]
    #: Why this row's existing art no longer follows the canon, '' when there is
    #: nothing to say. From `ill.stale_render_reason`, via `packet.Entry`.
    stale_reason: str
    #: What the person working this directory needs told, in the file they are
    #: reading. Also aggregated into `README.md` — two readers, not two gaps.
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
    #: True when this run covered every live plan row. A subset export leaves
    #: directories it did not write, and `README.md` must not read as a full one.
    complete: bool
    #: Unit directories already on disk that this run did not write.
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
    """Absolute path to one illustration's export directory."""
    return os.path.join(export_dir(project_dir), illus_id)


def is_built(project_dir: str) -> bool:
    """True when every shared export file exists.

    Keyed on the shared files rather than on any unit, because those are what
    make the bundle usable: a tree of unit directories with no `acceptance.md` is
    a handoff with no acceptance criteria, which is the same all-or-none reasoning
    `packet.is_built` follows.
    """
    return all(os.path.isfile(shared_file(project_dir, name))
               for name in SHARED_FILES)


def existing_units(project_dir: str) -> list[str]:
    """Ids of the unit directories currently on disk, sorted.

    A directory counts as a unit only when it holds a `manifest.json` this
    command wrote. `prune_units` deletes from this list, so a directory an author
    put in the export by hand is never a deletion candidate.
    """
    root = export_dir(project_dir)
    if not os.path.isdir(root):
        return []
    return sorted(
        name for name in os.listdir(root)
        if os.path.isfile(os.path.join(root, name, MANIFEST_FILENAME)))


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

    `ids` narrows to a subset. The plan handed to `packet.state_context` and
    `packet.needs_render` is still the **whole** plan, never the subset: reading
    order is a statement about the book, and a one-row plan makes that row its own
    book-start and strips its contrast clause (#297's shape, inside the fix).
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
    for row in rows:
        unit, unit_gaps = _unit_for(project_dir, row, context=context,
                                    plan=plan, canon_cutoff=canon_cutoff,
                                    style=style)
        units.append(unit)
        gaps.extend(unit_gaps)

    gaps.extend(packet.audit_gaps(project_dir, bundle='export'))
    # Over the rows in this export, not the whole plan: a gap naming rows the
    # bundle does not contain sends the reader looking for a directory that is
    # not there. `--diagnose` is where the whole plan's staleness is reported.
    gaps.extend(packet.stale_render_gaps(project_dir, rows, canon_cutoff))

    used = {unit['aspect'] for unit in units}
    exported = {unit['id'] for unit in units}
    return {
        'units': units,
        'book_level': pi.book_level_direction(project_dir),
        'anchors': context['anchors'],
        'labels': {cid: label['label']
                   for cid, label in context['labels'].items()},
        'aspects': [a for a in pi.ASPECTS if a in used] or [pi.DEFAULT_ASPECT],
        'gaps': gaps,
        # Set-covering rather than `ids is None`, so naming every live row
        # explicitly is not reported as partial — and so an empty plan is
        # "complete" rather than a partial export of nothing, which is a
        # different sentence for a different problem (the empty plan has its own
        # gap above).
        'complete': exported >= {r['id'].strip() for r in all_rows},
        'untouched': [i for i in existing_units(project_dir)
                      if i not in exported],
    }


def _unit_for(project_dir: str, row: dict[str, str], *,
              context: packet.RowContext, plan: list[dict[str, str]],
              canon_cutoff: str,
              style: 'object') -> tuple[ExportUnit, list[str]]:
    """Build one unit and the export-level gaps found while building it."""
    from storyforge import cmd_illustrate

    entry, gaps = packet.entry_for(row, context=context)
    illus_id = entry['id']
    warnings: list[str] = []

    body, body_source, prompt_source, body_gap = _body_for(project_dir, row)
    if body_gap:
        gaps.append(body_gap)
        warnings.append(body_gap)
    if entry['stale_reason']:
        warnings.append(
            f'this illustration already has art, and {entry["stale_reason"]}. '
            f'Generate it again from this block; do not demote its `status`.')
    if not entry['state']:
        warnings.append(
            'no visual state resolved for this illustration, so the costume, '
            'the lighting, and any damage below are the model\'s inference '
            'rather than a read of the book\'s schedule.')

    notes: list[str] = []
    references = _references_for_unit(
        project_dir, illus_id, plan=plan, canon_cutoff=canon_cutoff,
        style=style, notes=notes)
    warnings.extend(notes)
    if not references:
        gaps.append(
            f'illustration `{illus_id}` has no reference images at all, so its '
            f'directory carries no style or likeness anchor — whatever is '
            f'generated from it sets the look for everything that references it.')

    unit: ExportUnit = {
        'id': illus_id,
        'scene_id': entry['scene_id'],
        'status': entry['status'],
        'layout': entry['layout'],
        'aspect': entry['aspect'],
        'model': pi.DEFAULT_IMAGE_MODEL,
        'size': SIZES[entry['aspect']],
        'quality': QUALITY,
        'beat': entry['beat'],
        'subject': entry['in_frame'],
        'state': entry['state'],
        'absent': entry['absent'],
        'contrast': entry['contrast'],
        'treatment': entry['treatment'],
        'notes': entry['notes'],
        'body': body,
        'body_source': body_source,
        'prompt_source': prompt_source,
        'references': references,
        'stale_reason': entry['stale_reason'],
        'warnings': warnings,
    }
    return unit, gaps


def _body_for(project_dir: str,
              row: dict[str, str]) -> tuple[str, BodySource, str, str]:
    """The model-authored prose for a row, or a stand-in — plus why.

    Returns `(body, source, prompt_source, gap)`. A missing or unreadable prompt
    file is **not** a refusal: an export costs nothing to produce, so the useful
    behaviour is to build the bundle and say what is thin about it — the posture
    `run_package` takes. It is also not silent, in either artifact: a paste block
    assembled from three plan cells reads exactly like a complete prompt, and an
    author who cannot tell the difference generates from it.
    """
    illus_id = row['id'].strip()
    rel = (row.get('prompt_file') or '').strip() or ill.default_prompt_rel(
        illus_id)
    path = os.path.join(project_dir, rel)
    derived_gap = (
        f'illustration `{illus_id}` has no written art direction, so its paste '
        f'block is assembled from the plan row alone — the beat, the subject, '
        f'and the composition note, with none of the scene-specific prose '
        f'`--prompts` writes. Run `storyforge illustrate --prompts --ids '
        f'{illus_id}` first for a stronger prompt.')

    if not os.path.isfile(path):
        return _derived_body(row), 'plan_row', '', derived_gap
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return _derived_body(row), 'plan_row', '', (
            f'illustration `{illus_id}`: its prompt file `{rel}` could not be '
            f'read ({exc}), so its paste block is assembled from the plan row '
            f'alone. Fix or delete the file and re-run.')

    parsed = pi.parse_prompt_file(text)
    if parsed['status'] == 'ok':
        return parsed['body'], 'prompt_file', rel, ''
    reason = ('has no `## Prompt` section'
              if parsed['status'] == 'no_prompt_section'
              else 'has an empty prompt body')
    return _derived_body(row), 'plan_row', '', (
        f'illustration `{illus_id}`: its prompt file `{rel}` {reason}, so its '
        f'paste block is assembled from the plan row alone. Re-run `storyforge '
        f'illustrate --prompts --ids {illus_id}`.')


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
                         style: 'object',
                         notes: list[str]) -> list[ExportReference]:
    """Resolve this illustration's reference list into copy instructions.

    Reuses `--prompts`' own builder, so the export inherits its exclusions —
    the cover artwork rather than the typeset cover, and no render older than the
    newest `canon_updated` — instead of growing a second chain that could
    disagree with the prompt files it aggregates.

    Digests are read here rather than at copy time so `resolve` is the single
    place that reads the filesystem for a unit, and so a dry run reports exactly
    what a real run would write.
    """
    from storyforge import cmd_illustrate

    references: list[ExportReference] = []
    seen: set[str] = set()
    for rel, purpose in cmd_illustrate._references_for(
            project_dir, illus_id, plan=plan, canon_cutoff=canon_cutoff,
            style=style, notes=notes):  # type: ignore[arg-type]
        source = os.path.join(project_dir, rel)
        real = os.path.realpath(source)
        if real in seen:
            continue
        if not os.path.isfile(real):
            notes.append(
                f'`{rel}` is not in this directory — '
                + (f'it is a symlink to `{os.path.relpath(real, project_dir)}`, '
                   f'which does not exist. '
                   if os.path.islink(source) else 'the file is not there. ')
                + 'A copy could not be made, so nothing in this export carries '
                  'what it was for.')
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
            'sha256': ill.sha256_of(real),
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
    opened on. `copyfile` rather than `copy2`: the copy is a new file made now,
    and inheriting the source's mtime would make it look older than the export
    that wrote it.
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


def prune_units(project_dir: str, keep: set[str]) -> list[str]:
    """Delete unit directories for ids no longer in the plan. Returns the ids.

    Only called for a whole-plan export — a subset run has no business deleting
    the units it was not asked about, and `README.md` names those instead.

    Only directories holding a `manifest.json` this command wrote are candidates
    (see `existing_units`), so a directory an author added by hand survives.
    """
    removed: list[str] = []
    for illus_id in existing_units(project_dir):
        if illus_id in keep:
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
    """Report an export whose sources have moved since it was written.

    One finding with every reason in it, following `packet_stale`: the fix for
    all of them is `storyforge illustrate --export`, and splitting one root cause
    across several findings is the noise pattern the packet's own gap channel was
    narrowed to avoid.

    Two kinds of reason, because the export carries two kinds of thing:

    - **mtime**, for what it renders — the plan, the transition log, the canon
      files, and every prompt file it aggregated a body from. Strictly newer, so
      a source written in the same tick as the export is the `--export` run.
    - **digest**, for what it copies. This is what the recorded `sha256` is
      *for*: a re-render replaces a reference image, and comparing content
      catches that whether or not the mtime moved. A source that has since gone
      is the same root cause with a different sentence.

    Returns [] when no export is built — an unbuilt export is in-flight state.
    """
    if not is_built(project_dir):
        return []

    rendered = [shared_file(project_dir, name) for name in SHARED_FILES]
    sources = [ill.plan_path(project_dir), vs.state_path(project_dir)]
    canon_dir = os.path.join(project_dir, canon.CANON_DIR)
    if os.path.isdir(canon_dir):
        sources.extend(canon._walk_canon_files(canon_dir))

    reasons: list[str] = []
    for illus_id in existing_units(project_dir):
        directory = unit_dir(project_dir, illus_id)
        rendered.append(os.path.join(directory, MANIFEST_FILENAME))
        prompt = os.path.join(directory, PROMPT_FILENAME)
        if os.path.isfile(prompt):
            rendered.append(prompt)
        manifest = _read_manifest(os.path.join(directory, MANIFEST_FILENAME))
        if manifest is None:
            reasons.append(f'`{illus_id}/{MANIFEST_FILENAME}` could not be '
                           f'read, so that unit cannot be checked at all')
            continue
        source = str(manifest.get('prompt_source') or '')
        if source and os.path.isfile(os.path.join(project_dir, source)):
            sources.append(os.path.join(project_dir, source))
        reasons.extend(_reference_drift(project_dir, illus_id, manifest))

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

    log(f'WARNING: the illustration export is out of date: '
        f'{"; ".join(reasons)}')
    return [{
        'kind': 'export_stale',
        'file': os.path.join(EXPORT_DIR, 'README.md'),
        'detail': f'the export no longer matches its sources — '
                  f'{"; ".join(reasons)}. Regenerate it with `storyforge '
                  f'illustrate --export` before generating from it.',
    }]


def _reference_drift(project_dir: str, illus_id: str,
                     manifest: dict) -> list[str]:
    """Reasons a unit's copied reference images no longer match their sources."""
    reasons: list[str] = []
    entries = manifest.get('references')
    if not isinstance(entries, list):
        return reasons
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get('source') or '')
        digest = str(entry.get('sha256') or '')
        if not source or not digest:
            continue
        real = os.path.realpath(os.path.join(project_dir, source))
        if not os.path.isfile(real):
            reasons.append(f'`{illus_id}` references `{source}`, which no '
                           f'longer exists')
            continue
        if ill.sha256_of(real) != digest:
            reasons.append(f'`{source}` has changed since it was copied into '
                           f'`{illus_id}/{REFERENCES_SUBDIR}/`')
    return reasons
