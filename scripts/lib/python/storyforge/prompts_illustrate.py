"""Prompt builders for interior illustrations.

Two prompt families live here:

  - **Selection** — asks the model which narrative moments earn an
    illustration, given the deterministic pre-pass findings.
  - **Art direction** — turns one plan row into an image-generation prompt the
    author can paste into GPT Image 2.

The art-direction prompts reuse the five principles validated on
benjaminsnorris/ashes PR #9 and encoded for graphic-novel pages in #260/#263:
the 5-section OpenAI template, reference images carrying style and likeness,
an identical character-anchor string everywhere a character appears, positive
framing instead of negation, and an explicit orientation directive. Those were
learned the expensive way on a different medium; prose illustrations inherit
them rather than rediscovering them.

See benjaminsnorris/storyforge#278.
"""

import json
import os
import re
from typing import Final

from storyforge.illustrations import (
    ILLUSTRATIONS_SUBDIR, PrepassFindings, VALID_PLACEMENTS,
)

# Anchors live beside the art so every later illustration can reuse the exact
# strings — principle 4 only works if the string is literally identical.
ANCHORS_FILENAME: Final[str] = 'character-anchors.md'

DEFAULT_ASPECT: Final[str] = 'portrait'
VALID_ASPECTS: Final[tuple[str, ...]] = ('portrait', 'square', 'landscape')

_NO_TEXT_CONSTRAINT: Final[str] = (
    'Render no text, no letters, no words, and no typography anywhere in the '
    'image.'
)


# ============================================================================
# Orientation
# ============================================================================

def aspect_for_row(row: dict[str, str]) -> str:
    """Determine an illustration's aspect from its composition field.

    There is no dedicated aspect column — an interior illustration's shape is
    a compositional decision, so it is read out of `composition` when the
    author states one there. Portrait is the default because it matches the
    page it sits on.
    """
    text = (row.get('composition') or '').lower()
    for aspect in ('landscape', 'square'):
        if re.search(rf'\b{aspect}\b', text):
            return aspect
    return DEFAULT_ASPECT


def orientation_clause(aspect: str = DEFAULT_ASPECT) -> str:
    """Return the explicit orientation directive for an aspect.

    GPT Image 2 returns landscape unless told otherwise (#263), so every
    prompt states its orientation in both the Use case and the Constraints.
    This is the one place the prompt negates — the content rules below use
    positive framing only, because negated content keywords leak into the
    image, but orientation drift needs the explicit "not".
    """
    a = (aspect or DEFAULT_ASPECT).strip().lower()
    if a == 'landscape':
        return ('Render in LANDSCAPE orientation — wider than tall, ~3:2 '
                'aspect ratio. Do not render as portrait or square.')
    if a == 'square':
        return ('Render in SQUARE orientation — 1:1 aspect ratio. Do not '
                'render as portrait or landscape.')
    return ('Render in PORTRAIT orientation — taller than wide, ~2:3 aspect '
            'ratio. Do not render as landscape or square.')


# ============================================================================
# Character anchors
# ============================================================================

def anchors_path(project_dir: str) -> str:
    """Path to the shared character-anchor file."""
    return os.path.join(project_dir, ILLUSTRATIONS_SUBDIR, ANCHORS_FILENAME)


def read_character_anchors(project_dir: str) -> dict[str, str]:
    """Read the persisted character-anchor strings.

    Format is one ``- **Name** — anchor string`` bullet per character. Kept as
    markdown rather than CSV so the author can read and edit it directly; the
    anchor is a sentence of prose, not structured data.
    """
    path = anchors_path(project_dir)
    if not os.path.isfile(path):
        return {}
    anchors: dict[str, str] = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^\s*[-*]\s*\*\*(.+?)\*\*\s*[—:-]\s*(.+?)\s*$', line)
            if m:
                anchors[m.group(1).strip()] = m.group(2).strip()
    return anchors


def write_character_anchors(project_dir: str, anchors: dict[str, str]) -> str:
    """Write the character-anchor file, merging with what is already there.

    Existing anchors are never overwritten: an anchor's whole value is that it
    stays byte-identical across every illustration, so revising one silently
    would break likeness continuity in the art already rendered.
    """
    merged = read_character_anchors(project_dir)
    for name, anchor in anchors.items():
        merged.setdefault(name.strip(), anchor.strip())

    path = anchors_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        '# Character anchors',
        '',
        'One fixed description per character, reused **verbatim** in every',
        'illustration prompt that features them. Identical strings are what',
        'keep a character recognizable across separately generated images —',
        'paraphrasing an anchor defeats its purpose.',
        '',
    ]
    for name in sorted(merged):
        lines.append(f'- **{name}** — {merged[name]}')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path


# ============================================================================
# Selection prompt
# ============================================================================

def build_selection_prompt(*, prepass: PrepassFindings, target_count: int,
                           story_context: str, coaching: str = 'full') -> str:
    """Build the prompt that proposes which moments earn an illustration.

    The pre-pass findings go in as evidence the model must engage with, not as
    background. Left to itself a model picks whichever scenes read most
    vividly, which is not the same question as which moments an image can do
    something prose cannot.
    """
    findings = json.dumps({
        'recommended_count': prepass['recommended_count'],
        'already_planned': prepass['planned_count'],
        'scenes_already_illustrated': prepass['covered_scenes'],
        'uncovered_spine_events': prepass['uncovered_spine_events'],
        'turning_point_scenes': prepass['turning_point_scenes'],
        'motif_payoffs': prepass['motif_payoffs'],
        'motif_singletons': prepass['motif_singletons'],
        'chapters_with_no_illustration': prepass['uncovered_chapters'],
        'chapters_with_three_or_more': prepass['clustered_chapters'],
    }, indent=2)

    ask = (
        'Propose the illustrations.' if coaching == 'full'
        else 'Propose candidate illustrations for the author to choose among.'
    )

    return f"""You are art-directing interior illustrations for a novel.

{ask} Choose {target_count} moments. Each one must earn its place.

## Story context

{story_context}

## Deterministic findings

These were computed from the project's structural data. Engage with them —
argue for or against each candidate. Do not ignore them and do not simply
accept them.

```json
{findings}
```

## What makes a moment worth illustrating

- The image does something the prose cannot: it holds a composition, a scale,
  or a spatial relationship that sentences deliver only sequentially.
- It sits at a beat the reader will already be leaning into — a turning point,
  a value shift, the payoff of a motif the book has been building.
- It does not spoil what the facing page is about to reveal. An illustration
  arrives at the same time as the prose it accompanies, or slightly after.
  Never before.
- It is distributed. Illustrations bunched into three chapters read as an
  accident of the author's enthusiasm rather than a design.
- It is renderable: a specific subject in a specific space, not an abstraction
  or a montage.

## Output

Return JSON only, in this exact shape:

```json
{{
  "proposals": [
    {{
      "id": "kebab-case-slug",
      "scene_id": "the-scene-id-from-the-data",
      "anchor": "a short verbatim quote from that scene marking where the image lands",
      "placement": "after_anchor",
      "beat": "one sentence: what narrative moment this image renders",
      "rationale": "why this moment earns an illustration, and what the image does that the prose cannot",
      "subject": "the concrete subject: who or what is depicted, doing what",
      "composition": "framing, scale, vantage, and aspect if it matters",
      "palette": "color direction",
      "mood": "emotional register and light",
      "motifs": "semicolon-separated motif names this image carries",
      "canon_refs": "semicolon-separated character or world bible references the art must honor",
      "avoid": "what this image must not show, especially anything the prose has not revealed yet"
    }}
  ]
}}
```

`placement` must be one of: {', '.join(sorted(VALID_PLACEMENTS))}.

The `anchor` must be a phrase that appears **verbatim** in the named scene and
is unique within it. It is what lets the plan survive revision, so a generic
phrase that recurs is worse than useless.
"""


def parse_selection_response(text: str) -> tuple[list[dict], str]:
    """Extract the ``proposals`` list from a selection response.

    Returns (proposals, status) where status is 'ok', 'no_proposals_key', or
    'no_json'. Three extraction attempts — bare JSON, fenced block, first
    brace-to-brace span — matching cmd_propose_summaries._extract_proposals.
    """
    def _take(obj) -> list[dict] | None:
        if isinstance(obj, dict):
            inner = obj.get('proposals')
            if isinstance(inner, list):
                return [p for p in inner
                        if isinstance(p, dict) and str(p.get('id', '')).strip()]
        return None

    parsed_any = False
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        parsed_any = True
        out = _take(parsed)
        if out:
            return out, 'ok'
    return [], 'no_proposals_key' if parsed_any else 'no_json'


def _json_candidates(text: str):
    """Yield progressively looser JSON candidates from a model response."""
    yield text
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        yield m.group(1).strip()
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        yield m.group(0)


# ============================================================================
# Art direction
# ============================================================================

def build_art_direction_request(*, row: dict[str, str], scene_excerpt: str,
                                character_anchors: dict[str, str],
                                canon_context: str,
                                style_note: str = '') -> str:
    """Build the prompt that writes one illustration's image prompt.

    Asks for the prompt *body* in the 5-section template. The surrounding file
    — references, orientation, the no-text constraint — is assembled
    deterministically by render_prompt_file, so those invariants can't be
    paraphrased away by a model having an off day.
    """
    anchors_block = '\n'.join(
        f'- **{name}** — {anchor}' for name, anchor in sorted(character_anchors.items())
    ) or '(none recorded yet — propose one for each character who appears)'

    fields = '\n'.join(
        f'- **{key}**: {row.get(key, "").strip()}'
        for key in ('beat', 'subject', 'composition', 'palette', 'mood',
                    'motifs', 'canon_refs')
        if (row.get(key) or '').strip()
    )

    style = f'\n## House style\n\n{style_note}\n' if style_note.strip() else ''

    return f"""Write an image-generation prompt for one interior illustration.

## The illustration

{fields}

## The scene it accompanies

{scene_excerpt}

## Canon the art must honor

{canon_context}

## Character anchors

Reuse these strings **verbatim** for any character who appears. If a character
has no anchor yet, write one and it becomes canonical for every later
illustration.

{anchors_block}
{style}
## How to write it

Use OpenAI's five-section template, in this order, as markdown headings:

**Scene** — the setting in one or two sentences: place, time, light.
**Subject** — who or what the image is of, and what they are doing. Character
anchors go here, verbatim.
**Important details** — the specifics that carry meaning: objects, textures,
spatial relationships, the direction of light. Three to six of them.
**Use case** — that this is an interior illustration for a novel, and the
orientation.
**Constraints** — what must hold.

Rules:

- Keep the whole body between 250 and 400 words. Reference images carry style
  and likeness; prose spent re-describing them is prose wasted.
- Frame everything positively. Say what is in the image, not what is absent —
  negated keywords leak into the render. ("A bare sill" not "no clutter on the
  sill.")
- Be concrete. A specific object in a specific light beats an adjective.
- Do not describe anything the scene has not revealed by this point in the book.

Return the five sections as markdown. No preamble, no commentary.

If you propose any new character anchor, append it at the very end as:

```
ANCHORS
- Name — the anchor string
```
"""


ANCHOR_BLOCK_RE = re.compile(
    r'^ANCHORS\s*$(.*)\Z', re.MULTILINE | re.DOTALL,
)


def split_anchor_block(body: str) -> tuple[str, dict[str, str]]:
    """Split a model's prompt body from any trailing ANCHORS block.

    Returns (body_without_anchors, anchors). Anchors proposed inline are
    lifted out so they can be persisted once and reused verbatim.
    """
    m = ANCHOR_BLOCK_RE.search(body)
    if not m:
        return body.strip(), {}
    anchors: dict[str, str] = {}
    for line in m.group(1).splitlines():
        am = re.match(r'^\s*[-*]\s*(.+?)\s*[—:-]\s*(.+?)\s*$', line)
        if am:
            anchors[am.group(1).strip().strip('*')] = am.group(2).strip()
    return body[:m.start()].strip(), anchors


def render_references_block(references: list[str]) -> str:
    """Render the labeled reference-image list.

    Reference images do the heavy lifting on style and likeness, so the list
    is explicit about what each one is for — an unlabeled pile of images gets
    uploaded in the wrong order and the style anchor stops working.
    """
    if not references:
        return ('_No reference images yet. The first illustration establishes '
                'the house style; every later one should reference it._')
    lines = ['Upload these, in this order:', '']
    lines.extend(f'{i}. `{ref}`' for i, ref in enumerate(references, 1))
    return '\n'.join(lines)


def render_prompt_file(*, row: dict[str, str], body: str,
                       references: list[str], aspect: str = DEFAULT_ASPECT,
                       model: str = 'gpt-image-2') -> str:
    """Assemble an illustration's prompt file.

    The invariants — orientation in two places, the no-text constraint, the
    reference manifest — are written here rather than requested from the model,
    because a prompt that quietly loses its orientation directive produces a
    landscape image and a wasted generation.
    """
    illus_id = (row.get('id') or '').strip()
    orientation = orientation_clause(aspect)
    scene_id = (row.get('scene_id') or '').strip()

    parts = [
        f'# Illustration prompt — {illus_id}',
        '',
        f'- **Scene:** `{scene_id}`',
        f'- **Beat:** {(row.get("beat") or "").strip()}',
        f'- **Target model:** {model}',
        f'- **Aspect:** {aspect}',
        '',
        '## References to upload',
        '',
        render_references_block(references),
        '',
        '## Prompt',
        '',
        'Paste everything below into the image model.',
        '',
        '---',
        '',
        body.strip(),
        '',
        '### Constraints',
        '',
        f'- {orientation}',
        f'- {_NO_TEXT_CONSTRAINT}',
        '- Match the style, palette, and line quality of the reference images.',
        '- Keep every character consistent with their anchor description above.',
        '',
        '---',
        '',
        '## Log',
        '',
        '| Attempt | Model | Aspect | Output | Status | Note |',
        '|---------|-------|--------|--------|--------|------|',
        f'| 1 | {model} | {aspect} | | | |',
        '',
        'Record every generation here — the prompt plus these settings is the',
        'reproducible seed for the art, and the only way to get back to a',
        'result you liked two weeks later.',
        '',
    ]
    return '\n'.join(parts)


# ============================================================================
# Coaching variants
# ============================================================================

def render_coach_brief(*, prepass: PrepassFindings,
                       target_count: int) -> str:
    """Render the coach-mode planning brief.

    Surfaces the deterministic findings as questions. The author picks the
    moments; the brief makes sure they are choosing against the book's actual
    structure rather than their memory of it.
    """
    lines = [
        '# Illustration planning brief',
        '',
        f'Your book supports roughly **{target_count}** interior '
        f'illustrations. You currently have '
        f'**{prepass["planned_count"]}** planned.',
        '',
        '## What the structural data says',
        '',
    ]

    if prepass['uncovered_spine_events']:
        lines.append('### Spine events with no illustration')
        lines.append('')
        lines.append('These are the irreducible events of your story. An '
                     'unillustrated one is not a problem — but if the art '
                     'skips the spine entirely, ask what it is covering '
                     'instead.')
        lines.append('')
        for event in prepass['uncovered_spine_events']:
            lines.append(f'- **{event["title"] or event["id"]}** — '
                         f'{event["summary"]}')
        lines.append('')

    if prepass['turning_point_scenes']:
        lines.append('### Scenes carrying a turning point or value shift')
        lines.append('')
        for scene in prepass['turning_point_scenes'][:15]:
            bits = [b for b in (scene.get('turning_point'),
                                scene.get('value_shift')) if b]
            lines.append(f'- **{scene["title"] or scene["architecture_scene"]}**'
                         f' — {", ".join(bits)}. {scene.get("summary", "")}')
        lines.append('')
        lines.append('*Which of these is the reader most leaning into? That is '
                     'usually where an image lands hardest.*')
        lines.append('')

    if prepass['motif_payoffs']:
        lines.append('### Motifs that pay off')
        lines.append('')
        lines.append('A motif on its third appearance carries everything the '
                     'first two deposited. Illustrating it there means the '
                     'image inherits that weight for free.')
        lines.append('')
        for payoff in prepass['motif_payoffs']:
            lines.append(f'- **{payoff["motif"]}** — {payoff["appearances"]} '
                         f'appearances; payoff at `{payoff["payoff_scene"]}`')
        lines.append('')

    if prepass['motif_singletons']:
        lines.append('### Motifs appearing once')
        lines.append('')
        lines.append('*Is each of these meant to be a single note, or did it '
                     'lose its recurrence in revision?*')
        lines.append('')
        lines.append('- ' + '\n- '.join(prepass['motif_singletons'][:20]))
        lines.append('')

    if prepass['uncovered_chapters']:
        lines.append('### Chapters with no illustration')
        lines.append('')
        lines.append('- ' + ', '.join(prepass['uncovered_chapters']))
        lines.append('')

    if prepass['clustered_chapters']:
        lines.append('### Chapters with three or more')
        lines.append('')
        lines.append('- ' + ', '.join(prepass['clustered_chapters']))
        lines.append('')
        lines.append('*Clustering usually means the art is following your '
                     'interest rather than the book\'s shape.*')
        lines.append('')

    lines.extend([
        '## Questions to settle',
        '',
        '1. What is the one image someone would remember from this book?',
        '2. Are the illustrations carrying the plot, the world, or the '
        'interior life? A book usually wants one of those, consistently.',
        '3. Does any candidate show something the reader has not yet been '
        'told? That is the failure mode that cannot be fixed later.',
        '4. What do the illustrations have in common visually — palette, '
        'framing, level of abstraction? That agreement is the house style.',
        '',
        '## When you have decided',
        '',
        'Add a row per illustration to `reference/illustration-plan.csv`, or '
        'tell me the moments and I will record them.',
        '',
    ])
    return '\n'.join(lines)


def render_strict_checklist(*, prepass: PrepassFindings,
                           target_count: int) -> str:
    """Render the strict-mode constraint checklist.

    Data and requirements only — no proposals, no interpretation of which
    moments matter. The author supplies all creative direction.
    """
    lines = [
        '# Illustration plan — constraint checklist',
        '',
        'Generated for `coaching=strict`. This file reports structural data '
        'and lists what each plan row requires. It proposes nothing.',
        '',
        '## Counts',
        '',
        f'- Scenes: {prepass["scene_count"]}',
        f'- Chapters: {prepass["chapter_count"]}',
        f'- Illustrations currently planned: {prepass["planned_count"]}',
        f'- Count consistent with book length: {target_count}',
        '',
        '## Coverage data',
        '',
        f'- Spine events with no illustrated scene: '
        f'{len(prepass["uncovered_spine_events"])}',
        f'- Architecture scenes carrying a turning point or value shift: '
        f'{len(prepass["turning_point_scenes"])}',
        f'- Motifs with 3+ appearances: {len(prepass["motif_payoffs"])}',
        f'- Motifs appearing once: {len(prepass["motif_singletons"])}',
        f'- Chapters with no illustration: '
        f'{", ".join(prepass["uncovered_chapters"]) or "none"}',
        f'- Chapters with 3+ illustrations: '
        f'{", ".join(prepass["clustered_chapters"]) or "none"}',
        '',
        '## Required per plan row',
        '',
        '| Column | Requirement |',
        '|--------|-------------|',
        '| `id` | Lowercase kebab-case slug, unique across the plan. |',
        '| `scene_id` | Must match an id in `reference/scenes.csv`. |',
        '| `anchor` | A phrase appearing verbatim and exactly once in that '
        'scene file. |',
        f'| `placement` | One of: {", ".join(sorted(VALID_PLACEMENTS))}. '
        '`scene_open` and `scene_close` need no anchor. |',
        '| `beat` | One sentence. Becomes the image alt text. |',
        '| `subject` | Concrete subject of the image. |',
        '| `composition` | Framing and vantage. State `landscape` or `square` '
        'here if the illustration is not portrait. |',
        '| `palette`, `mood` | Art direction. |',
        '| `motifs` | Semicolon-separated; must match '
        '`reference/motif-taxonomy.csv`. |',
        '| `canon_refs` | Semicolon-separated bible references. |',
        '| `status` | `planned` until a prompt exists. |',
        '',
        '## Next commands',
        '',
        '```bash',
        'storyforge illustrate --prompts     # art direction for planned rows',
        'storyforge illustrate --ingest DIR  # bring rendered files in',
        'storyforge illustrate --diagnose    # plan health report',
        '```',
        '',
    ]
    return '\n'.join(lines)
