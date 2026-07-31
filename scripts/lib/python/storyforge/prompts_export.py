"""The renderers for `manuscript/illustration-export/`.

Deterministic assembly — no API calls, no timestamps, so two runs over unchanged
sources produce identical bytes (there is a test). An export is a render like the
packet: an edit here is lost on the next run and never reaches the plan.

The one thing these renderers exist to guarantee is that **each unit's paste
region is contiguous and complete**. The packet's economies are right for a
session that reads `canon.md` once and keeps it in context; they are wrong for
handing one image to a browser session, where a prompt split across a prompt file
(the prose), a packet entry (the state), and the author's own memory (the image
paths) means sixty copy operations for twenty images and a real chance of pasting
the wrong pair (#298).

So the paste region carries the model-authored body, the resolved visual state,
the `absent` exclusions, and the contrast directive, in one block, above a line
that says where it ends. Everything the reader must *not* paste sits below that
line and says so in its heading — the marker convention the GN page renderer and
`prompts_illustrate.render_prompt_file` already use.
"""

import os
import shlex
from typing import Final

from storyforge import export as ex
from storyforge import prompts_illustrate as pi
from storyforge import prompts_packet as pp

#: The heading that opens the paste region, and the rule that closes it. A reader
#: skimming for "what do I paste" finds one answer.
_PASTE_OPEN: Final[str] = '## Paste everything below this line'
_PASTE_CLOSE: Final[str] = '## End of prompt — do NOT paste anything below'


def render_prompt(*, unit: ex.ExportUnit, title: str) -> str:
    """One illustration's `prompt.md`: the whole paste-ready block and its checks.

    The Constraints bullets come from `prompts_illustrate.prompt_constraints`,
    the same function the prompt file uses, so the two artifacts cannot drift
    apart in *how* they phrase a constraint. They can still differ in content, in
    two documented ways: the export opts into `contrast` (see that function for
    why the prompt file does not), and a prompt file predating a matrix edit still
    carries the old state in its own block while a fresh export carries the state
    in force now — there is no `prompt_stale`.

    A unit's `warnings` are rendered **above** the paste region rather than in a
    footnote, and `test_the_warnings_come_before_the_paste_region` pins that
    position. They are the things that change whether generating from this block
    is a good idea at all — no written art direction, no resolved visual state,
    art that predates the current canon, a reference image that could not be
    copied — and a reader who has already pasted has already spent the render.
    The reference chain's own disclosures are *not* here: they go under
    `## About these reference images`, below, because an unavoidable note about a
    book with no ingested art yet is not a reason to stop.
    """
    constraints = pi.prompt_constraints(
        aspect=unit['aspect'], state=unit['state'], absent=unit['absent'],
        contrast=unit['contrast'])
    accept = pi.prompt_acceptance_lines(
        state=unit['state'], absent=unit['absent'], contrast=unit['contrast'])

    if unit['references']:
        uploads = [
            f'{reference["order"]}. `{reference["file"]}` — '
            f'{reference["purpose"]}'
            for reference in unit['references']]
        upload_block = '\n'.join([
            f'Upload the {len(unit["references"])} image(s) in '
            f'`{ex.REFERENCES_SUBDIR}/` first, in this order:', '', *uploads])
    else:
        upload_block = (
            '_No reference images could be assembled for this illustration, so '
            'nothing anchors its style or likeness. Whatever is generated from '
            'this block sets the look for everything that references it._')

    parts = [
        f'# {unit["id"]} — {title}',
        '',
        f'- **Scene:** `{unit["scene_id"] or "—"}` · **Layout:** '
        f'{unit["layout"]} · **Aspect:** {unit["aspect"]}',
        f'- **Model:** {unit["model"]} · **Size:** {unit["size"]} · '
        f'**Quality:** {unit["quality"]}',
        f'- **Return the image as** `{unit["id"]}.png`, then '
        f'`storyforge illustrate --ingest <dir>`.',
        '',
    ]

    if unit['warnings']:
        parts.extend([
            '## Read this first',
            '',
            '\n'.join(f'- {warning}' for warning in unit['warnings']),
            '',
        ])

    parts.extend([
        '## References',
        '',
        upload_block,
        '',
    ])
    if unit['chain_notes']:
        parts.extend([
            '### About these reference images',
            '',
            'A short list is not the same as having little to reference.',
            '',
            '\n'.join(f'- {note}' for note in unit['chain_notes']),
            '',
        ])

    parts.extend([
        _PASTE_OPEN,
        '',
        unit['body'].strip(),
        '',
        pi.CONSTRAINTS_HEADING,
        '',
        '\n'.join(constraints),
        '',
        _PASTE_CLOSE,
        '',
        '### Accept only if',
        '',
        'Checked against this illustration\'s plan row, not against the render '
        'you happen to like. The checks that are identical for every image in '
        'the book live in `../acceptance.md`.',
        '',
        '\n'.join(accept),
        '',
    ])

    if unit['treatment']:
        # Below the paste line because the body already embodies it — the
        # art-direction request takes the treatment as a requirement — so
        # repeating it to the model would be a second, competing staging note.
        # It is here so the reader can check that the body actually did.
        parts.extend([
            '### Staging assigned to this image',
            '',
            unit['treatment'],
            '',
        ])

    parts.extend([
        '### Where this came from',
        '',
        _provenance(unit),
        '',
    ])
    return '\n'.join(parts)


def _provenance(unit: ex.ExportUnit) -> str:
    """Which files this block was assembled from, and that it is a render.

    Stated because the block is paste-ready and therefore looks authoritative: a
    reader who edits it is editing a render, and the sentence that tells them so
    has to be in the file they are reading rather than only in `README.md`.
    """
    lines = [
        f'- The prompt prose above: '
        + (f'`{unit["prompt_source"]}`' if unit['body_source'] == 'prompt_file'
           else '**assembled from the plan row**, because '
                f'`{unit["prompt_source"]}` did not yield one'),
        '- The state, `absent`, and `contrast` lines: '
        '`reference/illustration-plan.csv` and `reference/visual-state.csv`',
        '- The orientation, no-lettering, style-match, and anchor-consistency '
        'rules: fixed house rules in `prompts_illustrate.prompt_constraints`, '
        'the same ones every illustration in the book carries',
        f'- The reference images: copied from their project paths with symlinks '
        f'resolved; `{ex.MANIFEST_FILENAME}` records where each came from and '
        f'its sha256',
    ]
    return '\n'.join(lines) + (
        '\n\nThis file is a render. Edit the plan, the transition log, or the '
        'canon files and re-run `storyforge illustrate --export`; an edit here '
        'is lost on the next run.')


def render_readme(*, title: str, contents: ex.ExportContents) -> str:
    """The export's front page: what is here, how to work it, what is thin.

    `gaps` is rendered in full rather than summarized. The export is the artifact
    most likely to be read by someone who was not at the terminal when it was
    built — that is what it is for — so a gap that only reached a log line has
    reached nobody who matters.
    """
    units = contents['units']
    gaps = contents['gaps']

    rows = ['| Illustration | Scene | Aspect | References | Art direction |',
            '|---|---|---|---|---|']
    for unit in units:
        direction = ('written' if unit['body_source'] == 'prompt_file'
                     else '**plan row only**')
        mark = _unit_mark(unit)
        rows.append(
            f'| `{unit["id"]}`{mark} | `{unit["scene_id"] or "—"}` '
            f'| {unit["aspect"]} | {len(unit["references"])} | {direction} |')
    table = '\n'.join(rows) if units else (
        '_No illustrations in this export._')

    if gaps:
        gap_block = '\n'.join(f'- {gap}' for gap in gaps)
        gap_intro = (
            f'{len(gaps)} thing(s) below were missing from the data this export '
            f'was assembled from. Each one is a place a directory here is '
            f'thinner than it looks — read them before you generate, not after:')
    else:
        gap_block = ''
        gap_intro = ('Nothing was missing from the data this export was '
                     'assembled from. That is a statement about the plan, the '
                     'canon files, and the state matrix — not a promise that '
                     'the art will be right.')

    scope = _scope_note(contents)
    return f"""# Illustration export — {title}

{len(units)} illustration(s), one directory each. **Every directory is complete
on its own**: the paste-ready prompt, and the reference images as actual files.
Zip one and hand it over, or work them here.

{scope}

## The files

| Path | What it is |
|---|---|
| `README.md` | This file |
| `canon.md` | The reference tier — house style and every continuity anchor |
| `acceptance.md` | The checks that are the same for every image |
| `<id>/prompt.md` | One contiguous paste-ready block, and the per-image checks |
| `<id>/{ex.REFERENCES_SUBDIR}/` | The reference images, numbered in upload order |
| `<id>/{ex.MANIFEST_FILENAME}` | Model, size, quality, aspect, and each reference's sha256 |

## How to work one illustration

1. Open `<id>/prompt.md`.
2. Read anything under **Read this first** — it is why generating from that
   block might be a bad idea right now.
3. Upload the images in `<id>/{ex.REFERENCES_SUBDIR}/`, in filename order.
4. Paste everything between **{_PASTE_OPEN.lstrip('# ')}** and the end-of-prompt
   line. Nothing above or below it goes to the image model.
5. Check the result against `<id>/prompt.md`'s **Accept only if** section and
   `acceptance.md`. Re-roll rather than accepting a near miss — an accepted
   near miss becomes the reference image every later illustration inherits.
6. Save the image as `<id>.png` and bring it back:

```bash
storyforge illustrate --ingest <directory of returned images>
```

## What this export is not

**It is a render.** Regenerated wholesale by `storyforge illustrate --export`, so
an edit here is lost on the next run and never reaches the plan. Change
`reference/illustration-plan.csv`, `reference/visual-state.csv`, or
`reference/canon/` instead, then regenerate.

**Read `canon.md` before the first image and keep it in front of you.** The
per-illustration blocks deliberately do not repeat the house style or the
continuity anchors: an anchor is reused *verbatim* in every image its entity
appears in, and identical strings are the entire mechanism by which a character
looks like the same character in image two and image nineteen.

## The illustrations

{table}

## What this export cannot tell you

{gap_intro}

{gap_block}

Plan health — a marker with no row, a file no row claims, an anchor that no
longer matches the prose — is not in this list. Run `storyforge illustrate
--diagnose` for that.
"""


def _unit_mark(unit: ex.ExportUnit) -> str:
    """The one-word note beside an id whose art already exists.

    Routed through `prompts_packet._entry_state` rather than re-deciding the three
    states here. That function returns a `RenderState`, so the marks are exclusive
    structurally rather than by the order of two `if`s — and, more to the point,
    it owns `_RENDERED_STATUSES`, whose comment explains why the set is enumerated
    positively. A forked copy of `('rendered', 'ingested')` would leave this table
    disagreeing with the packet's entry headings the first time a status is added.

    `ExportUnit` inherits `packet.Entry`, so the same function reads both.
    """
    return {'stale': ' — **re-render**', 'done': ' — already rendered',
            'pending': ''}[pp._entry_state(unit)]


def _scope_note(contents: ex.ExportContents) -> str:
    """Say whether this export covers the whole book or a subset.

    A subset export leaves earlier directories in place, and those may have been
    built from a plan that has since moved. Saying "N illustrations" over a
    directory holding twenty is the coverage overclaim this whole bundle's gap
    section exists to avoid.

    Reads `scope`, not a bool. An empty plan is `whole-plan` here — calling it a
    partial export would be the wrong sentence — and that is only safe because
    `prune_units` takes `live_ids` and refuses an empty set, rather than deriving
    its delete authority from this same flag.
    """
    if contents['scope'] == 'whole-plan':
        return ('This export covers every illustration in the plan.'
                if contents['units'] else
                'The plan has no illustrations to export.')
    lines = ['**This is a partial export** — it was built for the '
             'illustrations listed below, not for the whole plan.']
    if contents['untouched']:
        named = ', '.join(f'`{i}`' for i in contents['untouched'])
        lines.append(
            f'{len(contents["untouched"])} other directory(ies) are still here '
            f'from an earlier run ({named}). This run did not touch them, so '
            f'they may have been built from a plan, a transition log, or canon '
            f'files that have since changed. Re-run `storyforge illustrate '
            f'--export` with no `--ids` to rebuild the whole bundle.')
    return '\n\n'.join(lines)


def render_zip_hint(project_dir: str, illus_id: str) -> str:
    """The one command that packages a single unit for handing over.

    Kept as a renderer rather than run: zipping is the author's call — they may
    be uploading the directory directly — and a command they can read beats a
    file this command decided to create.

    Shell-quoted, because this is a command a reader copies: a project path with a
    space in it otherwise produces one that fails, or worse, one that `cd`s
    somewhere else.
    """
    return (f'cd {shlex.quote(os.path.join(project_dir, ex.EXPORT_DIR))} && '
            f'zip -r {shlex.quote(f"{illus_id}.zip")} {shlex.quote(illus_id)} '
            f'canon.md acceptance.md')
