"""Shared fixtures and builders for the interior-illustration tests (#278).

A plain module rather than a cross-test-module import: `from tests.…` resolved
only under `python3 -m pytest` and broke the bare `pytest tests/test_thing.py`
invocation CLAUDE.md documents — as a *collection* error, which made bare
`pytest tests/` collect nothing at all. pytest puts this file's directory on
sys.path for every collected test module, so `from illustration_helpers import …`
works under every invocation.

Kept out of conftest.py because these are builders callers invoke directly, not
fixtures pytest injects.
"""

import os
import struct
import subprocess
import zlib

from storyforge import illustrations as ill


def make_png(path: str, width: int, height: int) -> str:
    """Write a real minimal PNG of the given dimensions."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + b'\x00\x00\x00' * width for _ in range(height))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
                + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return path


def make_jpeg(path: str, width: int, height: int) -> str:
    """Write a minimal JPEG with an APP0 segment before the SOF0.

    The APP0 is deliberate: it exercises the segment walk skipping a
    payload-bearing marker before reaching the dimensions.
    """
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00' + b'\x00' * 9
    sof0 = (b'\xff\xc0' + struct.pack('>H', 17) + b'\x08'
            + struct.pack('>HH', height, width) + b'\x03' + b'\x00' * 9)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\xff\xd8' + app0 + sof0 + b'\xff\xd9')
    return path


def make_webp(path: str, width: int, height: int) -> str:
    """Write a minimal VP8X-form WebP."""
    payload = (b'VP8X' + struct.pack('<I', 10) + b'\x00' * 4
               + (width - 1).to_bytes(3, 'little')
               + (height - 1).to_bytes(3, 'little'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 4 + len(payload)) + b'WEBP'
                + payload)
    return path


def write_scene(project_dir: str, scene_id: str, text: str) -> str:
    """Write a scene file and return its path."""
    path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def pandoc_html(markdown: str) -> str:
    """Convert markdown to HTML the same way the manifest builder does."""
    result = subprocess.run(
        ['pandoc', '-f', 'markdown', '-t', 'html', '--no-highlight'],
        input=markdown, capture_output=True, text=True,
    )
    return result.stdout


SCENE = (
    'The lantern guttered once and held.\n'
    '\n'
    'She set it on the sill and waited for the street to answer.\n'
    '\n'
    'Nothing came. The cold worked up through the floorboards.\n'
    '\n'
    'By morning she had decided.\n'
)

#: Deliberately adversarial: passive voice, a dialogue-tag adverb, a filler
#: phrase, dialogue, and a weather word in the opening. SCENE has none of those,
#: so every per-1000-word density computed on it is 0/N and stays 0 whether N is
#: 30 or 31 — which let a full revert of marker-stripping pass 5 of 9 scorer
#: assertions. Anything asserting that a marker does not perturb a scorer must
#: use this fixture.
SCENE_ADVERSARIAL = (
    'The rain was falling steadily on the cold street.\n'
    '\n'
    'She set it on the sill and waited, due to the fact that nothing else '
    'was left.\n'
    '\n'
    '"You came," she said quietly. It was noticed by everyone in the room.\n'
    '\n'
    'By morning she had decided.\n'
)


def plan_row(**overrides) -> dict[str, str]:
    """A complete plan row with sane defaults."""
    row = ill.blank_row('lantern-vigil')
    row.update({
        'scene_id': 'vigil',
        'anchor': 'She set it on the sill',
        'placement': 'after_anchor',
        'beat': 'A woman waits at a lit window',
        'rationale': 'The image holds the waiting the prose spends three '
                     'paragraphs on',
    })
    row.update(overrides)
    return row


# ============================================================================
# Seeding the fixture for the packet (#278 phase 3)
# ============================================================================
#
# tests/fixtures/test-project carries a visual-state.csv (phase 2) but NO
# reference/canon/ tree and NO illustration plan — checked, not assumed. The
# packet needs both, so these builders write them into a *copy* of the fixture
# rather than into the shared fixture itself: seeding canon files there would
# change what every cleanup, validate, and canon test sees.
#
# Every id below is a real registry id in the fixture (characters.csv,
# locations.csv, motif-taxonomy.csv) and every scene id is a real fixture scene
# that the chapter map positions, so the seeded state actually resolves.

#: canon_id -> (canon_type, Embeddable block body). Each body contains a '.',
#: which the drift test perturbs.
BOOK_LEVEL_CANON: dict[str, tuple[str, str]] = {
    'visual-foundation': (
        'foundation',
        'Full-colour cinematic interior illustration for adult literary '
        'fantasy. Every image should read as a room someone works in.',
    ),
    'visual-vocabulary': (
        'vocabulary',
        'Warm lamplight and umber for the office; cold slate blue for the '
        'blank places on the map. Camera at standing eye height.',
    ),
    'content-limits': (
        'rules',
        'No gore, no modern dress, no crowd larger than a dozen figures.',
    ),
}

#: canon_id -> (subdir, canon_type, anchor text). Reused verbatim by every
#: prompt, which is why the packet copies must be byte-identical.
ENTITY_CANON: dict[str, tuple[str, str, str]] = {
    'dorren-hayle': (
        'characters', 'character',
        'Dorren Hayle: fifty-one, grey hair pinned flat, steel-rimmed '
        'spectacles, a black wool waistcoat, ink on her right cuff.',
    ),
    'cartography-office': (
        'locations', 'location',
        'The Pressure Cartography Office: a long hall of slanted oak drafting '
        'tables under high north windows.',
    ),
    'maps': (
        'motifs', 'motif',
        'The master survey: a four-foot vellum sheet inked in umber and iron '
        'gall, its border ruled in a single hairline.',
    ),
}


def write_canon_file(project_dir: str, *, canon_id: str, canon_type: str,
                     body: str, subdir: str = '') -> str:
    """Write one minimal-valid canon file and return its path."""
    parts = [project_dir, 'reference', 'canon']
    if subdir:
        parts.append(subdir)
    path = os.path.join(*parts, f'{canon_id}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            '---\n'
            f'canon_id: {canon_id}\n'
            f'canon_type: {canon_type}\n'
            'canon_updated: 2026-07-28\n'
            'appears_in:\n'
            'first_appearance:\n'
            '---\n\n'
            '## Embeddable block\n\n'
            f'{body}\n\n'
            '## Clauses\n\n## Related canon\n\n## Iteration history\n'
        )
    return path


def seed_canon(project_dir: str) -> dict[str, str]:
    """Write the three book-level canon files and three entity anchors.

    Returns canon_id -> anchor text for the entity files, which is what
    `canon.anchor_texts` should then report.
    """
    for canon_id, (canon_type, body) in BOOK_LEVEL_CANON.items():
        write_canon_file(project_dir, canon_id=canon_id,
                         canon_type=canon_type, body=body)
    for canon_id, (subdir, canon_type, body) in ENTITY_CANON.items():
        write_canon_file(project_dir, canon_id=canon_id,
                         canon_type=canon_type, body=body, subdir=subdir)
    return {cid: body for cid, (_sub, _type, body) in ENTITY_CANON.items()}


def seed_state_transitions(project_dir: str) -> None:
    """Append transitions for two seeded canon entities.

    Evidence quotes are verbatim from the fixture prose (checked: 'held her
    breath' is in act1-sc01, 'Blank parchment' in act1-sc02), so the pre-pass
    has nothing to report about them. `cartography-office` deliberately gets
    NO transition — the packet must report an entity a plan row names but
    nothing states.
    """
    from storyforge import visual_state as vs
    existing = list(vs.read_transitions(project_dir))
    existing.extend([
        {'entity': 'dorren-hayle', 'from_scene': 'act1-sc01',
         'state': 'black waistcoat, sleeves buttoned, calipers in hand',
         'evidence': 'held her breath'},
        {'entity': 'maps', 'from_scene': 'act1-sc02',
         'state': 'the new survey blank where the village was',
         'evidence': 'Blank parchment'},
    ])
    vs.write_transitions(project_dir, existing)


def seed_illustration_plan(project_dir: str) -> list[dict[str, str]]:
    """Write a two-row plan on real fixture scenes and return the rows."""
    first = ill.blank_row('the-finest-cartographer')
    first.update({
        'scene_id': 'act1-sc01',
        'anchor': 'held her breath',
        'placement': 'after_anchor',
        'layout': 'full_page',
        'beat': 'Dorren measures the ridgeline for the third time',
        'rationale': 'The image holds the precision the chapter spends its '
                     'first page establishing',
        'subject': 'Dorren bent over the master survey with brass calipers',
        'composition': 'Close on her hands and the vellum, lamp behind her',
        'canon_refs': 'dorren-hayle;cartography-office',
        'register': 'brightest',
    })
    second = ill.blank_row('the-blank-page')
    second.update({
        'scene_id': 'act1-sc02',
        'anchor': 'Blank parchment',
        'placement': 'before_anchor',
        'layout': 'half_page',
        'beat': 'The village is gone from the new survey',
        'rationale': 'The absence is the turn of the chapter and prose cannot '
                     'show an absence',
        'subject': 'The empty quarter of the map under a low reading lamp',
        'composition': 'Overhead, square, the sheet filling the frame',
        'canon_refs': 'maps',
        'register': 'darkest',
        'state_override': 'maps:one corner curled back under a paperweight',
    })
    rows = [first, second]
    ill.write_plan(project_dir, rows)
    return rows


def seed_packet_project(project_dir: str) -> dict[str, str]:
    """Canon + plan + state, the state the packet is assembled from."""
    anchors = seed_canon(project_dir)
    seed_state_transitions(project_dir)
    seed_illustration_plan(project_dir)
    return anchors


def write_direction_file(project_dir: str, body: str) -> str:
    """Write a raw direction document."""
    path = ill.direction_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)
    return path


def truncated_png(path: str, width: int, height: int) -> str:
    """Write a header-valid PNG with no IDAT and no IEND.

    This is what an aborted render download leaves behind: `image_dimensions`
    reads 32 bytes and reports plausible dimensions, so every naive guard
    passes it.
    """
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body)))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height,
                                             8, 2, 0, 0, 0)))
    return path


def make_webp_vp8(path: str, width: int, height: int) -> str:
    """Write a lossy VP8 WebP — what plain `cwebp` emits."""
    body = (b'\x00\x00\x00' + b'\x9d\x01\x2a'
            + struct.pack('<HH', width, height) + b'\x00' * 8)
    payload = b'VP8 ' + struct.pack('<I', len(body)) + body
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 4 + len(payload)) + b'WEBP'
                + payload)
    return path


def make_webp_vp8l(path: str, width: int, height: int) -> str:
    """Write a lossless VP8L WebP."""
    body = b'\x2f' + struct.pack('<I', (width - 1) | ((height - 1) << 14)) \
        + b'\x00' * 4
    payload = b'VP8L' + struct.pack('<I', len(body)) + body
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 4 + len(payload)) + b'WEBP'
                + payload)
    return path


def write_csv(project_dir: str, name: str, header: str, rows: list[str]) -> None:
    """Write a pipe-delimited CSV under reference/."""
    path = os.path.join(project_dir, 'reference', name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(header + '\n')
        for row in rows:
            f.write(row + '\n')


SAMPLE_DIRECTION = """# The Lantern Folk — Illustration Plan

## Format

Full-color, cinematic photorealistic storybook imagery for ages 6-8.

## Visual promise

The ordinary world should feel completely real.

## Recurring visual language

- Warm amber and gold for the Lantern Folk.
- Cool moonlit blue for the woods.

## Content limits

Never horror imagery. No blood or gore.

## Continuity anchors

### Leo

Ten years old; tall and lean for his age; warm light-brown skin.

### Murkwolves

Large wolf-shaped concentrations of cold shadow and blue-gray mist.

### The village and Great Lamp

The village sits among the enormous exposed roots of the Old Oak.
"""


SCENE_WITH_FRONTMATTER = (
    '---\n'
    'id: "vigil"\n'
    'status: "drafted"\n'
    'drafted_at: "2026-02-28T14:30:00Z"\n'
    '---\n'
    '\n'
    + SCENE
)


def write_prompt_file(project_dir: str, illus_id: str, *,
                      body: str = '', **kwargs) -> str:
    """Write a real `render_prompt_file` output for one row, at its plan path.

    The packet fixture deliberately has no prompt files, so every body in it
    comes from `packet._derived_body` — a renderer that emits exactly the four
    enumerated sections. That made the two invariant tests structurally
    incapable of failing: five of the eight forbidden strings live in *this*
    file's output, not in any packet renderer, and the only thing keeping them
    out of an upload is `parse_prompt_file`'s bounds (#306 review, T-2/T-3).

    So this writes the genuine article — paste sentinel, trailing `##
    Constraints`, `## Accept only if`, `## Log` and all — which is the shape the
    parse has to survive.
    """
    from storyforge import prompts_illustrate as pi
    row = ill.blank_row(illus_id)
    row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open'})
    row.update(kwargs)
    text = pi.render_prompt_file(
        row=row,
        body=body or ('## Scene\n\nA low room.\n\n## Subject\n\nOne figure.\n\n'
                      '## Important details\n\n- A lamp.\n\n## Use case\n\n'
                      'Interior illustration for a novel.'),
        references=[('manuscript/assets/cover-illustration.png', 'cover art')],
        state='the coat is buttoned')
    path = os.path.join(project_dir, ill.default_prompt_rel(illus_id))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path
