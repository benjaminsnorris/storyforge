"""Per-page file (graphic-novel mode) parsing and validation.

GN projects can break scenes into per-page files at pages/<prefix>-pN.md.
Each file has YAML frontmatter and a markdown body. See issue #251 and
docs/superpowers/plans/2026-05-27-gn-per-page-files.md for the schema.

The scene file (scenes/<scene_id>.md) remains the creative source of
truth; page files are the atomic per-page working units consumed by
extract, script-package, and cleanup.
"""

import os
import re


def page_id_prefix_for_scene(scene_id: str) -> str:
    """Return the prefix that page files for a scene should use.

    Convention: if scene_id starts with `s` + digits + `-`, the prefix is
    the leading `s\\d+` token (so `s01-studio-finalization` -> `s01`).
    Otherwise the full scene_id is the prefix (`the-blank-page` ->
    `the-blank-page`). Keeps both naming conventions tractable.
    """
    m = re.match(r'^(s\d+)-', scene_id)
    return m.group(1) if m else scene_id


def page_filename_for(scene_id: str, page_num: int) -> str:
    """Return the page file basename (without directory)."""
    return f'{page_id_prefix_for_scene(scene_id)}-p{page_num}.md'
