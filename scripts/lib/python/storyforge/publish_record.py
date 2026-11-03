"""What is live on Bookshelf: the publish record and `publish --verify`.

`working/publish-manifest.json` is regenerated on every publish and never
committed, so nothing said what a book's readers were reading. After a
successful publish, `storyforge publish` now writes
`production/publish-record.json` and commits it. The record holds no prose,
only hashes: each chapter's title, heading and part, and a SHA-256 of each
scene's `content_html` exactly as sent.

Bookshelf stores `content_html` verbatim and serves the same shape from
`GET /api/books/{slug}/digest`, so `publish --verify` compares the live book
with the record (and with what publish would send today) chapter by chapter
and scene by scene.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

RECORD_PATH = os.path.join('production', 'publish-record.json')
RECORD_VERSION = 1


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def chapters_digest(manifest_chapters: list[dict]) -> list[dict]:
    """The manifest's chapters in the digest shape Bookshelf returns."""
    out = []
    for ch in manifest_chapters:
        scenes = sorted(ch.get('scenes', []), key=lambda s: s.get('sort_order', 0))
        out.append({
            'number': ch['number'],
            'title': ch.get('title', ''),
            'heading': ch.get('heading'),
            'part': ch.get('part'),
            'scenes': [{
                'slug': s['slug'],
                'sort_order': s.get('sort_order'),
                'word_count': s.get('word_count'),
                'sha256': sha256_text(s.get('content_html', '')),
            } for s in scenes],
        })
    return out


def _git_out(project_dir: str, *args: str) -> str:
    try:
        r = subprocess.run(['git', '-C', project_dir, *args],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def build_record(project_dir: str, manifest: dict, result: dict,
                 storyforge_version: str, now: datetime | None = None) -> dict:
    """The record of a publish that just succeeded."""
    now = now or datetime.now(timezone.utc)
    chapters = chapters_digest(manifest.get('chapters', []))
    commit = _git_out(project_dir, 'rev-parse', 'HEAD')
    # The scenes as published may differ from the commit: say so, rather than
    # pointing a reader at a commit that isn't what went out.
    dirty = bool(_git_out(project_dir, 'status', '--porcelain', '--', 'scenes',
                          'reference', 'storyforge.yaml'))
    return {
        'record_version': RECORD_VERSION,
        'slug': manifest.get('slug', ''),
        'title': manifest.get('title', ''),
        'book_id': result.get('book_id', ''),
        'published_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'storyforge_version': storyforge_version,
        'project_commit': commit,
        'uncommitted_changes': dirty,
        'totals': {
            'chapters': len(chapters),
            'scenes': sum(len(c['scenes']) for c in chapters),
            'words': sum(s.get('word_count') or 0
                         for c in chapters for s in c['scenes']),
        },
        'chapters': chapters,
    }


def write_record(project_dir: str, record: dict) -> str:
    path = os.path.join(project_dir, RECORD_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return path


def read_record(project_dir: str) -> dict | None:
    path = os.path.join(project_dir, RECORD_PATH)
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def compare(expected: list[dict], live: list[dict]) -> list[str]:
    """Every difference between two digests' chapters, one line each.

    Empty when they match. Chapters are matched by number and scenes by slug,
    so a moved scene reads as moved, not as one removed and one added.
    """
    diffs: list[str] = []
    exp_ch = {c['number']: c for c in expected}
    live_ch = {c['number']: c for c in live}
    for n in sorted(set(exp_ch) - set(live_ch)):
        diffs.append(f'chapter {n} ("{exp_ch[n]["title"]}") is not live')
    for n in sorted(set(live_ch) - set(exp_ch)):
        diffs.append(f'chapter {n} ("{live_ch[n]["title"]}") is live but not expected')

    exp_scene_chapter = {s['slug']: c['number'] for c in expected for s in c['scenes']}
    live_scene_chapter = {s['slug']: c['number'] for c in live for s in c['scenes']}

    for n in sorted(set(exp_ch) & set(live_ch)):
        e, lv = exp_ch[n], live_ch[n]
        for field in ('title', 'heading', 'part'):
            if (e.get(field) or None) != (lv.get(field) or None):
                diffs.append(f'chapter {n}: {field} is {json.dumps(lv.get(field), ensure_ascii=False)} '
                             f'live, {json.dumps(e.get(field), ensure_ascii=False)} expected')
        live_scenes = {s['slug']: s for s in lv['scenes']}
        exp_scenes = {s['slug']: s for s in e['scenes']}
        for s in e['scenes']:
            slug = s['slug']
            got = live_scenes.get(slug)
            if got is None:
                where = live_scene_chapter.get(slug)
                diffs.append(f'chapter {n}: scene {slug} is not live'
                             + (f' (it is live in chapter {where})' if where else ''))
                continue
            if got.get('sha256') != s.get('sha256'):
                diffs.append(f'chapter {n}: scene {slug} text differs')
            if got.get('sort_order') != s.get('sort_order'):
                diffs.append(f'chapter {n}: scene {slug} is at position '
                             f'{got.get("sort_order")} live, {s.get("sort_order")} expected')
        for slug in live_scenes:
            if slug not in exp_scenes and slug not in exp_scene_chapter:
                diffs.append(f'chapter {n}: scene {slug} is live but not expected')
    return diffs
