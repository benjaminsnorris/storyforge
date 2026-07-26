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
