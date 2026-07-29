"""Prompt builders for interior illustrations.

Three prompt families live here:

  - **Selection** — asks the model which narrative moments earn an
    illustration, given the deterministic pre-pass findings.
  - **Art direction (book level)** — the typed canon files every illustration
    inherits: `visual-foundation`, `visual-vocabulary`, `content-limits`, plus
    one continuity-anchor file per character/location/motif (see
    `.superpowers/sdd/2026-07-28-illustration-canon-adoption/`).
  - **Art direction (per illustration)** — turns one plan row into an
    image-generation prompt the author can paste into GPT Image 2.

Plus the author-facing renderers for the non-``full`` coaching levels (planning
brief, constraint checklist, direction template) and the whole-sequence
continuity review — documents, not prompts.

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
from typing import Final, Literal

from storyforge.illustrations import (
    ANCHORS_SECTION, DIRECTION_SECTIONS, PrepassFindings, RenderStep,
    VALID_PLACEMENTS,
)

#: Aspect is derived from author-written prose (layout, then composition) and
#: consumed by orientation_clause, which silently falls back to portrait for an
#: unrecognized value — so the domain is worth naming. Mirrors pages.PageAspect.
Aspect = Literal['portrait', 'square', 'landscape']
ASPECTS: Final[tuple[Aspect, ...]] = ('portrait', 'square', 'landscape')
DEFAULT_ASPECT: Final[Aspect] = 'portrait'

# Phrasing matches the cover skill's Step T2.1 constraint verbatim — image
# models render text unreliably, and the two prompt families should not drift
# apart on the one constraint they share.
_NO_TEXT_CONSTRAINT: Final[str] = (
    'no text, no letters, no words, no typography anywhere in the image.'
)


# ============================================================================
# Orientation
# ============================================================================

def aspect_for_row(row: dict[str, str]) -> Aspect:
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


def orientation_clause(aspect: Aspect = DEFAULT_ASPECT) -> str:
    """Return the explicit orientation directive for an aspect.

    GPT Image 2 returns landscape unless told otherwise (#263), so every
    prompt states its orientation in both the Use case and the Constraints.

    Orientation and the standing no-text rule are the two constraints stated as
    explicit negations. Everything describing image *content* uses positive
    framing only, because negated content keywords leak into the render;
    orientation drift and stray lettering are both failure modes positive
    phrasing has not been observed to prevent. (The GN version of this claim in
    #263 says "the one place" because GN prompts do not carry the no-text rule —
    prose prompts do.)
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
    """Anchors available to an illustration prompt, keyed by canon_id.

    Reads reference/canon/ entity files. The strings are verbatim and must
    stay that way: likeness continuity across separately generated images
    depends on every prompt sending byte-identical text.
    """
    from storyforge import canon
    return canon.anchor_texts(project_dir)


#: Canon subdirectory per proposed anchor type. A type outside this map (or
#: absent) falls back to 'character' with a WARNING rather than guessing
#: silently — a stub filed under the wrong registry tells the author to add a
#: character row for a location, which is a confusing way to learn about a
#: parse failure.
_ANCHOR_TYPE_SUBDIR: Final[dict[str, str]] = {
    'character': 'characters',
    'location': 'locations',
    'motif': 'motifs',
}
_ANCHOR_TYPE_FALLBACK: Final[str] = 'character'


def canon_rel_path(canon_type: str, canon_id: str) -> str:
    """Project-relative path where a canon_id of canon_type belongs.

    Root types (`canon.ROOT_TYPES` — foundation/vocabulary/rules) live at the
    canon directory's root; every entity type lives under its subdirectory
    per `_ANCHOR_TYPE_SUBDIR`, falling back to `character` for an
    unrecognized type. Used by `--direction` to place both the three
    book-level files and the per-entity anchor stubs it writes.
    """
    from storyforge import canon
    if canon_type in canon.ROOT_TYPES:
        return os.path.join(canon.CANON_DIR, f'{canon_id}.md')
    subdir = _ANCHOR_TYPE_SUBDIR.get(canon_type, _ANCHOR_TYPE_FALLBACK)
    return os.path.join(canon.CANON_DIR, subdir, f'{canon_id}.md')


def append_anchor_stubs(project_dir: str,
                        anchors: dict[str, tuple[str, str]]) -> list[str]:
    """Persist model-proposed anchors as canon file stubs.

    `anchors` maps display name -> (canon_type, anchor_text).

    Returns the canon_ids written. An anchor whose canon_id already exists
    anywhere in reference/canon/ is left alone: append_anchor_stubs never
    revises an existing anchor, because a rendered illustration may already
    depend on its exact text.

    Two independent existence checks guard the write, and neither subsumes
    the other:

    - canon.canon_id_index — the declared `canon_id` in each *parseable*
      file's frontmatter, lowercased — catches an existing anchor whose
      filename stem differs from its own canon_id (a warning, not a block,
      in validate_canon_file). Keying on the stem instead let
      `characters/nora.md` get written to "add" an anchor already at
      `characters/Nora.md` (truncating it in place on a case-insensitive
      filesystem) or already at `characters/nora-smith.md` (creating a
      second file that then shadowed the original in anchor_texts's
      last-sorted-path tie-break).
    - a plain `os.path.exists` on the exact candidate path catches a file
      sitting at that path whose frontmatter canon_id_index can't read at
      all — absent, truncated, or missing the `canon_id` key. Those files
      are invisible to canon_id_index (it only indexes what it can parse a
      canon_id out of), so relying on canon_id_index alone would silently
      truncate a malformed-but-real file the moment a proposal's slug
      happened to match its path.

    Either check firing skips the write and logs a WARNING; the anchor is
    left for the author to sort out rather than risking any of the above.

    The registry row is deliberately NOT created. canon_missing_registry_entry
    reports the gap, and an author confirming the name is cheaper than
    silently making a model's guess canonical.
    """
    from storyforge import canon
    from storyforge.common import log

    existing = canon.canon_id_index(project_dir)
    written: list[str] = []
    for name, (raw_type, text) in sorted(anchors.items()):
        name = name.strip()
        text = (text or '').strip()
        if not text:
            log(f'WARNING: proposed anchor {name!r} has no anchor text; skipped')
            continue
        canon_id = _slugify(name)
        if not canon_id:
            log(f'WARNING: proposed anchor {name!r} has no usable slug; skipped')
            continue
        if canon_id in existing:
            log(f'WARNING: proposed anchor {name!r} (canon_id {canon_id!r}) '
                f'already exists at {existing[canon_id]}; left alone rather '
                f'than risk overwriting or shadowing it')
            continue
        canon_type = (raw_type or '').strip().lower()
        if canon_type not in _ANCHOR_TYPE_SUBDIR:
            log(f'WARNING: proposed anchor {name!r} has type {raw_type!r}; '
                f'filing as {_ANCHOR_TYPE_FALLBACK} — move the file and its '
                f'registry row if that is wrong')
            canon_type = _ANCHOR_TYPE_FALLBACK
        subdir = _ANCHOR_TYPE_SUBDIR[canon_type]
        rel_path = os.path.join(canon.CANON_DIR, subdir, f'{canon_id}.md')
        path = os.path.join(project_dir, rel_path)
        if os.path.exists(path):
            # canon_id_index only sees files whose frontmatter it could
            # parse a canon_id out of — a file at this exact path with no
            # frontmatter, truncated frontmatter, or no canon_id key is
            # invisible to it, so it would otherwise be silently
            # overwritten here.
            log(f'WARNING: proposed anchor {name!r} would write {rel_path}, '
                f'which already exists; left alone rather than overwrite it')
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_canon_stub(canon_id=canon_id, canon_type=canon_type,
                                anchor=text))
        # Keep the index current within this call too — a second proposal in
        # the same batch that collides with one just written must skip it for
        # the same reason, not race it.
        existing[canon_id] = rel_path
        written.append(canon_id)
    return written


def _slugify(name: str) -> str:
    """Lowercase kebab-case slug, matching canon's id validation."""
    return re.sub(r'[^a-z0-9]+', '-', name.strip().lower()).strip('-')


def _canon_stub(*, canon_id: str, canon_type: str, anchor: str) -> str:
    """A minimal valid canon file carrying one anchor.

    `appears_in` and `first_appearance` are left empty rather than guessed:
    a wrong first_appearance would misorder the render sequence, and
    canon_missing_key reports the omission.
    """
    return (
        '---\n'
        f'canon_id: {canon_id}\n'
        f'canon_type: {canon_type}\n'
        'canon_updated:\n'
        'appears_in:\n'
        'first_appearance:\n'
        '---\n'
        '\n'
        '## Embeddable block\n'
        '\n'
        f'{anchor}\n'
        '\n'
        '## Clauses\n'
        '\n'
        '## Related canon\n'
        '\n'
        '## Iteration history\n'
    )


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

If you propose any new anchor — a character, location, or motif with no
anchor yet — append it at the very end as:

```
ANCHORS
- Name | type — the anchor string
```

`type` must be one of `character`, `location`, or `motif`.
"""


# Tolerates `ANCHORS`, `ANCHORS:`, and `**ANCHORS**` — a model that decorates
# the marker would otherwise lose every anchor AND leave the block in the prompt
# body, which the author then pastes into the image model as prompt text.
ANCHOR_BLOCK_RE = re.compile(
    r'^[ \t]*(?:\*\*)?ANCHORS(?:\*\*)?[ \t]*:?[ \t]*$(.*)\Z',
    re.MULTILINE | re.DOTALL,
)

# `Name | type — description`, with `| type` optional. The separator before
# the description is an em/en dash, or a colon, or a hyphen *surrounded by
# whitespace* — never a bare hyphen, which would sever every hyphenated name
# ("Jean-Luc" became {'Jean': 'Luc — …'}). The mangled name was then written
# into the direction document as canonical and, because append_anchor_stubs
# never revises an existing anchor, stayed corrupt — and stopped matching
# canon_refs, so the anchor silently left every prompt. That guard is
# unchanged by the added `| type` group: the optional pipe segment is tried
# and abandoned at every candidate split point before the separator
# alternation runs, so it cannot turn a hyphenated name's internal `-` into a
# false separator either.
_ANCHOR_LINE_RE = re.compile(
    r'^[ \t]*[-*][ \t]*(?P<name>.+?)[ \t]*'
    r'(?:\|[ \t]*(?P<type>[a-zA-Z]+)[ \t]*)?'
    r'(?:[—–]|:|(?<=\s)-(?=\s))[ \t]*'
    r'(?P<desc>.+?)[ \t]*$'
)

#: Trailing code fence left behind when the ANCHORS block was inside one.
_TRAILING_FENCE_RE = re.compile(r'\n[ \t]*`{3,}[ \t]*\Z')


def split_anchor_block(body: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """Split a model's prompt body from any trailing ANCHORS block.

    Returns (body_without_anchors, anchors), where anchors maps display name
    -> (canon_type, anchor_text). Anchors proposed inline are lifted out so
    they can be persisted once and reused verbatim. `canon_type` is the raw,
    unvalidated string the model wrote (possibly '' when no `| type` was
    given) — append_anchor_stubs is what falls back to 'character' with a
    warning.

    Lines in the block that do not parse as ``Name [| type] — description``
    are reported by :func:`unparsed_anchor_lines` rather than silently
    dropped.
    """
    m = ANCHOR_BLOCK_RE.search(body)
    if not m:
        return _strip_trailing_fence(body), {}

    anchors: dict[str, tuple[str, str]] = {}
    for line in m.group(1).splitlines():
        am = _ANCHOR_LINE_RE.match(line)
        if am:
            name = am.group('name').strip().strip('*').strip()
            desc = am.group('desc').strip()
            raw_type = (am.group('type') or '').strip()
            if name and desc:
                anchors[name] = (raw_type, desc)
    # The request demonstrates the block inside a code fence, so the model
    # usually emits one; cutting at the ANCHORS line leaves the opening fence
    # behind, which corrupts every following section of the prompt file.
    return _strip_trailing_fence(body[:m.start()]), anchors


def unparsed_anchor_lines(body: str) -> list[str]:
    """Lines in a model's ANCHORS block that did not parse as an anchor.

    Surfaced so a mangled proposal is a warning the author can act on rather
    than an anchor that quietly never existed.
    """
    m = ANCHOR_BLOCK_RE.search(body)
    if not m:
        return []
    unparsed = []
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('```'):
            continue
        am = _ANCHOR_LINE_RE.match(line)
        if not am or not am.group('name').strip().strip('*').strip() \
                or not am.group('desc').strip():
            unparsed.append(stripped)
    return unparsed


def _strip_trailing_fence(text: str) -> str:
    """Remove an unterminated trailing code fence."""
    return _TRAILING_FENCE_RE.sub('', text.rstrip()).strip()


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
                       references: list[str] | list[tuple[str, str]],
                       aspect: Aspect = DEFAULT_ASPECT,
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
        '| `id` | Letters, digits, `-`, `_`; must start with a letter or '
        'digit. Unique across the plan, case-insensitively. |',
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
# Canon files (book level)
# ============================================================================

#: The three book-level canon files an illustrated prose book needs, mapped
#: from the old direction document's non-anchor sections. Continuity anchors
#: are not here — they are one file per entity, discovered from the
#: character/location registries and the plan's canon_refs. `canon_type` is
#: one of `canon.ROOT_TYPES`, so all three live at the canon root rather than
#: in a subdirectory.
CANON_PLAN: tuple[tuple[str, str, str], ...] = (
    ('visual-foundation', 'foundation',
     'Medium, rendering style, audience, and what every image must deliver. '
     'One or two sentences beat three paragraphs of adjectives.'),
    ('visual-vocabulary', 'vocabulary',
     'The rules that repeat: palette split by faction or mood, camera '
     'height, depth of field, how materials render, the standing no-text '
     'rule.'),
    ('content-limits', 'rules',
     'What the art must never do. Intensity ceilings, imagery to stay away '
     'from, anything the audience age rules out. State these as limits.'),
)


def render_canon_template(*, canon_id: str, canon_type: str, purpose: str,
                          coaching: str) -> str:
    """Render an unfilled canon file for the author or the model to complete.

    The Embeddable block carries a TODO line deliberately: canon.anchor_texts
    and canon.is_canon_block_populated both treat placeholder text as
    unpopulated, so an unfinished file is reported rather than silently
    shipped into a prompt as though it were direction.
    """
    if coaching == 'coach':
        block = (f'TODO — {purpose}\n\nWhat would you say here, in one or '
                 f'two sentences?\n')
    else:
        block = f'TODO — {purpose}\n'
    return (
        '---\n'
        f'canon_id: {canon_id}\n'
        f'canon_type: {canon_type}\n'
        'canon_updated:\n'
        'appears_in:\n'
        'first_appearance:\n'
        '---\n'
        '\n'
        '## Embeddable block\n'
        '\n'
        f'{block}'
        '\n'
        '## Clauses\n'
        '\n'
        '## Related canon\n'
        '\n'
        '## Iteration history\n'
    )


def render_filled_canon(*, canon_id: str, canon_type: str, body: str) -> str:
    """Render a canon file whose Embeddable block is already-written text.

    Thin wrapper over `_canon_stub` — the full-coaching `--direction` path
    reaches for the same minimal-valid-file shape `append_anchor_stubs` uses
    for a model-proposed anchor; there is no reason for a second format.
    """
    return _canon_stub(canon_id=canon_id, canon_type=canon_type, anchor=body)


def build_canon_direction_request(*, title: str, genre: str, audience: str,
                                  canon_context: str,
                                  story_context: str) -> str:
    """Build the prompt that drafts the three book-level canon Embeddable
    blocks in a single call.

    Asks for exactly the three `CANON_PLAN` ids as `##`-headed sections, so
    `parse_canon_direction_response` can drop each body straight into its own
    canon file without a second request per file.
    """
    briefs = '\n\n'.join(
        f'### {canon_id}\n\n{purpose}'
        for canon_id, _canon_type, purpose in CANON_PLAN)

    return f"""Write the book-level illustration direction for a novel, as \
three short canonical blocks.

**Title:** {title}{f' · **Genre:** {genre}' if genre else ''}\
{f' · **Audience:** {audience}' if audience else ''}

Each block below becomes a canon file that every interior-illustration prompt
in this book inherits. A per-illustration prompt can be re-rolled cheaply; a
book whose images disagree with each other has to be re-rendered wholesale.
Be specific and be decisive.

## Story context

{story_context}

## Canon

{canon_context}

## Blocks to write

Use these exact `##` headings, in this order, and write only the block's
content underneath — no restating the heading, no extra commentary.

{briefs}

## How to write it

- **Concrete over evocative.** "Warm amber and gold for the lantern-folk; cool
  moonlit blue and charcoal for the woods" is usable. "A magical palette" is
  not.
- **Name real materials.** Bark, moss, wax, leaded glass, waxed thread. Image
  models render named materials well and abstractions badly.
- **State limits as limits**, not as prompt text.
- State the standing no-text rule under `visual-vocabulary`.

Return markdown, starting at the first `##` heading. No preamble, no
commentary.
"""


def parse_canon_direction_response(text: str) -> dict[str, str]:
    """Split a canon-direction response into `{canon_id: embeddable body}`.

    Matches `## <heading>` headings against `CANON_PLAN`'s ids specifically —
    a model that free-associates an extra heading must not silently become a
    fourth canon file. Unmatched headings are simply not in the result.
    """
    known_ids = {canon_id for canon_id, _canon_type, _purpose in CANON_PLAN}
    sections: dict[str, str] = {}
    matches = list(re.finditer(r'^##\s+(.+?)\s*$', text, re.MULTILINE))
    for i, match in enumerate(matches):
        name = match.group(1).strip().lower()
        if name not in known_ids:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        if body:
            sections[name] = body
    return sections


# ============================================================================
# Sequence review
# ============================================================================

def render_sequence_review(*, title: str, steps: list[RenderStep],
                           anchors: dict[str, str],
                           direction: dict[str, str]) -> str:
    """Render the whole-sequence continuity review checklist.

    The rendered output explains to the author why a set-level pass exists; this
    docstring does not repeat it.
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
