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
import shutil
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
# The fixture's illustrated project (#288)
# ============================================================================
#
# tests/fixtures/test-project is a small, coherent illustrated project: the
# three book-level canon files, three entity canon files, a two-row plan, and a
# visual-state log (the log predates #288: phase 2 added `village` and
# `master-survey`). Every entity canon id is a real registry id (characters.csv,
# locations.csv, motif-taxonomy.csv), every scene id a fixture scene the chapter
# map positions, and every transition's evidence is verbatim in that scene's
# prose. `test_illustrated_fixture.py` holds all of that true, including that
# every tracked entity's search terms appear in positioned prose, and that the
# audit's candidate set is non-empty — an empty one means every test that
# thinks it exercises the model path takes the no-call branch and still passes.
#
# `master-survey` is deliberately a state-only entity with no canon file: the
# search-term path for an id no canon prefix confirms, and a tracked entity no
# plan row names. It tracks what the survey shows (the village gone); `maps`,
# the motif, tracks the sheet itself.
#
# The constants below are what the fixture's canon files carry; that test
# regenerates each file from them with `write_canon_file` and compares bytes.
# A test that needs a project *without* part of this removes it explicitly with
# the helpers at the end of this section, so the case it covers stays named.

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

#: The fixture plan's ids, in reading order.
FIXTURE_PLAN_IDS: tuple[str, ...] = ('the-finest-cartographer', 'the-blank-page')


def fixture_anchors() -> dict[str, str]:
    """canon_id -> anchor text for the fixture's entity canon files: what
    `canon.anchor_texts` reports on an unmodified copy of the fixture."""
    return {cid: body for cid, (_sub, _type, body) in ENTITY_CANON.items()}


#: canon_id -> (appears_in, first_appearance) for the fixture's canon files.
#: Both keys are required, and a blank one is a `canon_missing_key` warning.
FIXTURE_APPEARANCES: dict[str, tuple[str, str]] = {
    'visual-foundation': ('every illustration', 'act1-sc01'),
    'visual-vocabulary': ('every illustration', 'act1-sc01'),
    'content-limits': ('every illustration', 'act1-sc01'),
    'dorren-hayle': ('act1-sc01; act1-sc02', 'act1-sc01'),
    'cartography-office': ('act1-sc01', 'act1-sc01'),
    'maps': ('act1-sc01; act1-sc02', 'act1-sc01'),
}


#: canon_id -> `display_name` frontmatter. The `maps` motif's anchor is the
#: master survey, and no positioned scene says "maps" (only new-x1, which the
#: chapter map omits): without this its only search term would be `maps`, and
#: no prose the audit reads would name it.
FIXTURE_DISPLAY_NAMES: dict[str, str] = {'maps': 'Master survey'}


def write_canon_file(project_dir: str, *, canon_id: str, canon_type: str,
                     body: str, subdir: str = '',
                     appears_in: str = 'act1-sc01',
                     first_appearance: str = 'act1-sc01',
                     canon_updated: str = '2026-07-28',
                     display_name: str = '') -> str:
    """Write one minimal-valid canon file and return its path.

    The fixture's canon files have exactly this shape (written by this
    function), so a test adding a variant (another entity, a long anchor)
    writes one that matches them. `canon_updated` is the cutoff the reference
    chain compares ingest dates against; `display_name`, when given, is the
    first authority for an anchor's rendered label.
    """
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
            f'canon_updated: {canon_updated}\n'
            + (f'display_name: {display_name}\n' if display_name else '')
            + f'appears_in: {appears_in}\n'
            f'first_appearance: {first_appearance}\n'
            '---\n\n'
            '## Embeddable block\n\n'
            f'{body}\n\n'
            '## Clauses\n\n## Related canon\n\n## Iteration history\n'
        )
    return path


def remove_canon(project_dir: str) -> None:
    """Delete the copy's whole `reference/canon/` tree: a project with no
    canon tier yet."""
    shutil.rmtree(os.path.join(project_dir, 'reference', 'canon'))


def remove_plan(project_dir: str) -> None:
    """Delete the copy's illustration plan: a project that has planned none."""
    os.remove(ill.plan_path(project_dir))


def remove_illustration_seed(project_dir: str) -> None:
    """A project with no canon tier and no plan, as before `--direction` and
    `--plan` ever ran. The visual-state log is left alone (it predates both in
    the fixture's history and the audit suites own its variants)."""
    remove_canon(project_dir)
    remove_plan(project_dir)


def unstate_entity(project_dir: str, entity: str) -> None:
    """Drop every transition for *entity*, so a plan row that names it has no
    stated state — the gap the packet and `--prompts` must report.

    Raises ValueError when the log has no transition for *entity*: a typo
    would otherwise leave the state in place and the test asserting its
    absence would be testing nothing.
    """
    from storyforge import visual_state as vs
    before = vs.read_transitions(project_dir)
    rows = [t for t in before if t['entity'] != entity]
    if len(rows) == len(before):
        raise ValueError(f'no transition for {entity!r} in the fixture log')
    vs.write_transitions(project_dir, rows)


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
        split=scene_split(), row=row,
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


def scene_split(**overrides) -> ill.SceneSplit:
    """A `SceneSplit` for renderer tests that do not need a real scene.

    Defaults to the `normal` state — prose on both sides of the illustration —
    since that is the shape almost every prompt-file assertion is about. Pass
    `state=` plus the fields that state carries to exercise the others.
    """
    split: ill.SceneSplit = {
        'state': 'normal',
        'offset': 40,
        'cause': '',
        'read': 'She set it on the sill and waited.',
        'unread': 'Nothing came. The cold worked up.',
        'next_sentence': 'Nothing came.',
        'error': '',
    }
    split.update(overrides)          # type: ignore[typeddict-item]
    return split
