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
    ANCHORS_SECTION, DEFAULT_LAYOUT, DIRECTION_FILENAME, DIRECTION_SECTIONS,
    PrepassFindings, RenderStep, VALID_LAYOUTS, VALID_PLACEMENTS,
    read_continuity_anchors, read_direction,
)

DEFAULT_ASPECT: Final[str] = 'portrait'
VALID_ASPECTS: Final[tuple[str, ...]] = ('portrait', 'square', 'landscape')

# Phrasing matches the cover skill's Step T2.1 constraint verbatim — image
# models render text unreliably, and the two prompt families should not drift
# apart on the one constraint they share.
_NO_TEXT_CONSTRAINT: Final[str] = (
    'no text, no letters, no words, no typography anywhere in the image.'
)


# ============================================================================
# Orientation
# ============================================================================

def aspect_for_row(row: dict[str, str]) -> str:
    """Determine an illustration's aspect from its layout, then its composition.

    Layout decides first because it is a physical fact about the page: a
    double-page spread is wider than tall no matter what the composition note
    says. Failing that, an interior illustration's shape is a compositional
    decision, so it is read out of `composition` when the author states one
    there. Portrait is the default because it matches the page it sits on.
    """
    layout = (row.get('layout') or '').strip().lower()
    if layout == 'double_page':
        return 'landscape'

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
# Continuity anchors
# ============================================================================

def anchors_for_prompt(project_dir: str) -> dict[str, str]:
    """Return the continuity anchors from the direction document.

    Anchors are authored up front in `reference/illustration-direction.md`, not
    accumulated as a side effect of prompting. That ordering is the point: an
    anchor is an input to the art, and the reason it works is that every prompt
    reuses the identical string. A description invented on the fly by whichever
    illustration happened to be rendered first is not an anchor, it is a
    coincidence.
    """
    return read_continuity_anchors(project_dir)


def append_anchor_stubs(project_dir: str, anchors: dict[str, str]) -> list[str]:
    """Append newly-proposed anchors to the direction document.

    Returns the names actually added. Existing anchors are never touched: their
    whole value is staying byte-identical across every illustration, so revising
    one silently would break likeness continuity in art already rendered.

    New anchors are appended rather than merged in place so the author sees them
    as additions to review, in the one document that holds the book's whole
    visual contract.
    """
    from storyforge.illustrations import direction_path

    existing = {name.lower() for name in read_continuity_anchors(project_dir)}
    fresh = {name.strip(): desc.strip() for name, desc in anchors.items()
             if name.strip() and desc.strip()
             and name.strip().lower() not in existing}
    if not fresh:
        return []

    path = direction_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            current = f.read()
    else:
        current = f'# Illustration art direction\n\n## {ANCHORS_SECTION}\n'
    if ANCHORS_SECTION not in current:
        current = current.rstrip('\n') + f'\n\n## {ANCHORS_SECTION}\n'

    addition = '\n'.join(
        f'### {name}\n\n{fresh[name]}\n' for name in sorted(fresh))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(current.rstrip('\n') + '\n\n' + addition)
    return sorted(fresh)


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

def render_direction_block(direction: dict[str, str]) -> str:
    """Render the book-level art direction for inclusion in a prompt.

    Every section of the author's document is passed through, in the canonical
    order first and then anything they added of their own. The anchors section
    is excluded — it is rendered separately, because anchors must be reused
    verbatim rather than summarized alongside the rest of the direction.
    """
    if not direction:
        return ''
    ordered = [name for name in DIRECTION_SECTIONS if name != ANCHORS_SECTION]
    ordered += [name for name in direction
                if name not in DIRECTION_SECTIONS]
    parts = []
    for name in ordered:
        body = direction.get(name, '').strip()
        if body:
            parts.append(f'### {name}\n\n{body}')
    return '\n\n'.join(parts)


def build_art_direction_request(*, row: dict[str, str], scene_excerpt: str,
                                character_anchors: dict[str, str],
                                canon_context: str,
                                direction: dict[str, str] | None = None,
                                style_note: str = '') -> str:
    """Build the prompt that writes one illustration's image prompt.

    Asks for the prompt *body* in the 5-section template. The surrounding file
    — references, orientation, the no-text constraint — is assembled
    deterministically by render_prompt_file, so those invariants can't be
    paraphrased away by a model having an off day.
    """
    anchors_block = '\n'.join(
        f'- **{name}** — {anchor}' for name, anchor in sorted(character_anchors.items())
    ) or '(none recorded yet — propose one for each character or creature who appears)'

    fields = '\n'.join(
        f'- **{key}**: {row.get(key, "").strip()}'
        for key in ('beat', 'subject', 'layout', 'composition', 'palette',
                    'mood', 'motifs', 'canon_refs')
        if (row.get(key) or '').strip()
    )

    direction_text = render_direction_block(direction or {})
    house = (f'\n## Book-level art direction\n\nEvery illustration in this '
             f'book obeys this. It is not background — a prompt that departs '
             f'from it produces an image that does not belong to the '
             f'book.\n\n{direction_text}\n' if direction_text else '')

    style = f'\n## House style\n\n{style_note}\n' if style_note.strip() else ''

    return f"""Write an image-generation prompt for one interior illustration.
{house}
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


def render_references_block(
        references: list[str] | list[tuple[str, str]]) -> str:
    """Render the labeled reference-image list.

    Reference images do the heavy lifting on style and likeness, so the list is
    explicit about what each one is for — an unlabeled pile of images gets
    uploaded in the wrong order and the style anchor stops working.

    Accepts `(path, label)` pairs, or bare paths for a list with no labels.
    """
    if not references:
        return ('_No reference images yet. The first illustration establishes '
                'the house style; every later one should reference it._')
    lines = ['Upload these, in this order:', '']
    for i, ref in enumerate(references, 1):
        path, label = ref if isinstance(ref, tuple) else (ref, '')
        lines.append(f'{i}. `{path}`' + (f' — {label}' if label else ''))
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
        f'- Render {_NO_TEXT_CONSTRAINT}',
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


# ============================================================================
# Art-direction document
# ============================================================================

#: What each expected section of the direction document has to answer. Used by
#: every coaching level: as instructions to the model, as questions to the
#: author, and as a checklist.
DIRECTION_BRIEF: Final[dict[str, str]] = {
    'Format': 'The medium, rendering style, and intended audience in one or '
              'two sentences. "Full-color cinematic photorealism for a '
              'read-aloud fantasy novel, ages 6-8" tells an image model more '
              'than three paragraphs of adjectives.',
    'Visual promise': 'What every image in this book must deliver — the thing '
                      'a reader would notice missing. Usually a relationship '
                      'between two registers: how the ordinary world reads, '
                      'and how the extraordinary appears inside it.',
    'Recurring visual language': 'The rules that repeat: palette split by '
                                 'faction or mood, camera height, depth of '
                                 'field, materials rendered naturalistically, '
                                 'and the standing no-text rule.',
    'Content limits': 'What the art must never do, stated as limits rather '
                      'than as prompt text — intensity ceilings, imagery to '
                      'stay away from, anything the audience age rules out.',
    ANCHORS_SECTION: 'One `### Name` subsection per thing the art must keep '
                     'consistent: characters, creatures, key locations, '
                     'signature props. Each body is a fixed description, '
                     'reused verbatim in every prompt that features it. '
                     'Include measurable facts — height, age, exact colors — '
                     'because those are what drift.',
}


def build_direction_request(*, title: str, genre: str, audience: str,
                            canon_context: str, story_context: str,
                            entities: list[str]) -> str:
    """Build the prompt that drafts the book-level art-direction document.

    This document is authored once and constrains every illustration, which
    makes it the highest-leverage artifact in the flow — a per-illustration
    prompt can be re-rolled cheaply, but a book whose images disagree with each
    other has to be re-rendered wholesale.
    """
    briefs = '\n\n'.join(
        f'### {name}\n\n{brief}' for name, brief in DIRECTION_BRIEF.items())
    entity_list = '\n'.join(f'- {name}' for name in entities) or \
        '(derive them from the bibles below)'

    return f"""Write the book-level illustration art direction for a novel.

**Title:** {title}{f' · **Genre:** {genre}' if genre else ''}\
{f' · **Audience:** {audience}' if audience else ''}

This single document governs every interior illustration in the book. A
per-illustration prompt can be re-rolled cheaply; a book whose images disagree
with each other has to be re-rendered wholesale. Be specific and be decisive.

## Story context

{story_context}

## Canon

{canon_context}

## Things the art must keep consistent

Write a continuity anchor for each of these, plus any others the canon makes
necessary:

{entity_list}

## Sections to write

Use these exact `##` headings, in this order.

{briefs}

## How to write it

- **Concrete over evocative.** "Warm amber and gold for the lantern-folk; cool
  moonlit blue and charcoal for the woods" is usable. "A magical palette" is
  not.
- **Name real materials.** Bark, moss, wax, leaded glass, waxed thread. Image
  models render named materials well and abstractions badly.
- **Put measurable facts in the anchors.** Height in centimeters, age in years,
  exact hair and eye color, specific garments. These are the details that drift
  between separately generated images, and the only defence is stating them.
- **Anchors are descriptions, not scenes.** What the thing *is*, always — not
  what it does in any one illustration.
- State the standing no-text rule in the recurring visual language.

Return the document as markdown, starting at the first `##` heading. No
preamble, no commentary.
"""


def render_direction_template(*, title: str, coaching: str,
                              entities: list[str]) -> str:
    """Render the direction-document template for coach or strict coaching.

    `coach` frames each section as a question the author answers; `strict`
    reduces it to the requirement plus a blank. Neither writes any creative
    content, which is the whole distinction from the `full` path.
    """
    lines = [f'# Illustration art direction — {title}', '']
    if coaching == 'coach':
        lines += [
            'This document governs every interior illustration in the book.',
            'Answer each section in your own words — what you write here is',
            'what every prompt will carry.',
            '',
        ]
    else:
        lines += [
            'This document governs every interior illustration in the book.',
            'Each section below lists what it must contain. Fill them in.',
            '',
        ]

    for name, brief in DIRECTION_BRIEF.items():
        lines.append(f'## {name}')
        lines.append('')
        if coaching == 'coach':
            lines.append(f'_{_as_question(name, brief)}_')
        else:
            lines.append(f'_Required: {brief}_')
        lines.append('')
        if name == ANCHORS_SECTION:
            for entity in entities:
                lines.append(f'### {entity}')
                lines.append('')
                lines.append('_(fill this in — include height, age, exact '
                             'colors, and specific garments)_')
                lines.append('')
            if not entities:
                lines.append('### Name')
                lines.append('')
                lines.append('_(fill this in)_')
                lines.append('')
        else:
            lines.append('_(fill this in)_')
            lines.append('')
    return '\n'.join(lines)


#: Coach-mode phrasings, so the template asks rather than instructs.
_DIRECTION_QUESTIONS: Final[dict[str, str]] = {
    'Format': 'What is someone holding when they hold this book — what medium, '
              'what rendering style, for what reader?',
    'Visual promise': 'What would a reader notice missing if one illustration '
                      'failed to deliver it?',
    'Recurring visual language': 'What repeats across every image — palette, '
                                 'camera height, level of detail? What makes '
                                 'two of these images obviously from the same '
                                 'book?',
    'Content limits': 'What must the art never do? What would be too much for '
                      'your reader?',
    ANCHORS_SECTION: 'What must look the same every time it appears — which '
                     'characters, creatures, places, objects? Describe each one '
                     'the way you would to someone who has to draw it without '
                     'reading the book.',
}


def _as_question(name: str, brief: str) -> str:
    """Return the coach-mode question for a section, falling back to its brief."""
    return _DIRECTION_QUESTIONS.get(name, brief)


# ============================================================================
# Sequence review
# ============================================================================

def render_sequence_review(*, title: str, steps: list[RenderStep],
                           anchors: dict[str, str],
                           direction: dict[str, str]) -> str:
    """Render the whole-sequence continuity review checklist.

    Per-illustration validation cannot catch continuity drift: each image is
    individually fine and the set is still inconsistent. This is the pass that
    looks at all of them together, which is the only place a character who
    gained an inch of height across ten renders becomes visible.
    """
    rendered = [s for s in steps if s['status'] == 'ingested']
    pending = [s for s in steps if s['status'] != 'ingested']

    lines = [
        f'# Illustration sequence review — {title}',
        '',
        f'{len(rendered)} of {len(steps)} illustrations rendered.',
        '',
        'Review the sequence **as a set**, in render order. Per-illustration '
        'checks pass on images that are individually fine and collectively '
        'inconsistent; this pass is the only one that catches drift.',
        '',
        '## Cross-sequence checks',
        '',
    ]

    checks = [
        ('Identity', 'Is every character recognizably the same person in every '
                     'image they appear in?'),
        ('Scale', 'Are size relationships consistent — between characters, and '
                  'between characters and their world?'),
        ('Costume', 'Does clothing match the anchor, and change only where the '
                    'story changes it?'),
        ('Geography', 'Do recurring locations have a stable layout across '
                      'images?'),
        ('Light progression', 'Does the light track the story — brightening and '
                             'darkening where it should, and nowhere else?'),
        ('Palette', 'Does the palette split hold, image to image?'),
        ('Intensity', 'Is every image within the limits set in Content limits?'),
        ('Text', 'Is every image free of lettering, captions, borders, and '
                 'watermarks?'),
    ]
    for name, question in checks:
        lines.append(f'- [ ] **{name}** — {question}')
    lines.append('')

    if anchors:
        lines += ['## Anchors to check against', '']
        for name in sorted(anchors):
            lines.append(f'- [ ] **{name}** — {anchors[name]}')
        lines.append('')

    limits = direction.get('Content limits', '').strip()
    if limits:
        lines += ['## Content limits', '', limits, '']

    lines += ['## Render order', '']
    for i, step in enumerate(steps, 1):
        mark = 'x' if step['status'] == 'ingested' else ' '
        key = ' — **visual key**' if step['is_visual_key'] else ''
        locks = (f' · locks: {", ".join(step["locks"])}'
                 if step['locks'] else '')
        lines.append(f'{i}. [{mark}] `{step["id"]}`{key}{locks}')
    lines.append('')

    if pending:
        lines += [
            '## Still to render',
            '',
            'Continuity drift is cheapest to fix before the rest are rendered, '
            'because every later image references the earlier ones.',
            '',
        ]
        for step in pending:
            lines.append(f'- `{step["id"]}` ({step["status"]})')
        lines.append('')

    lines += [
        '## Before final layout',
        '',
        '- [ ] Correct any drift found above, re-rendering from the anchor '
        'rather than patching the image.',
        '- [ ] Re-run `storyforge illustrate --diagnose` after re-ingesting.',
        '',
    ]
    return '\n'.join(lines)
