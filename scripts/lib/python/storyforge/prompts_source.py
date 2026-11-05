"""The source-aware additions to the elaboration prompts (#477).

Each `*_section` function returns '' (and `bibles_text` []) for a project
with no `source:` block, and the prompt builders add nothing in that case, so
their prompts stay byte for byte what they were. With a block, a source not
imported yet raises SourceError before any prompt is built. With a block, they give the spine the source's events to
select from, the architecture its cast and POV distribution, the map every
source scene to account for in `reference/source-map.csv`, and the briefs
each scene's source briefs and the source prose itself.

With a `range:`, the spine, architecture and map sections use only the span's
scenes (`source.adapted_scenes`), and the briefs section refuses a scene whose
map row names a source scene outside the span; the rest of the source reaches
the model only through the Source Bible, as context. A source not imported, a
bible built for another range, or a range that can't be resolved raises
SourceError before any prompt is built.
"""

from __future__ import annotations

import os

from storyforge import source
from storyforge.common import log

# Source prose a briefs prompt may carry, in words. Past it, a scene's source
# prose is left out and the prompt says which; its source brief stays.
SOURCE_PROSE_MAX_WORDS = 60000

_BRIEF_FIELDS = ('goal', 'conflict', 'outcome', 'crisis', 'decision',
                 'key_actions', 'key_dialogue', 'knowledge_out', 'emotions', 'subtext')


def _cfg(project_dir: str) -> source.SourceConfig | None:
    """The source block, or None; raises SourceError when a source isn't
    imported (a prompt would promise a source and show none of it)."""
    cfg = source.read_config(project_dir)
    if cfg is not None:
        source.require_imported(project_dir, cfg)
    return cfg


def _header(cfg: source.SourceConfig) -> str:
    names = ', '.join(f'`{s}`' for s in cfg.slugs())
    how = ('**faithful**: every source event appears in the novel unless the version '
           'rules or a stated reason cut it' if cfg.mode == 'faithful'
           else '**free**: the source is a starting point; follow it where the plan '
                'does, and give a reason for each source scene left out')
    head = (f'This novel adapts a source ({names}); its events, cast and places are in '
            f'the Source Bible. Mode: {how}.')
    spans = [f'`{p.slug}`: {p.range.describe()}' for p in cfg.projects if p.range]
    if spans:
        head += (f' Only part of the source is adapted ({"; ".join(spans)}): "every '
                 f'source event" means every event in the adapted span.')
    return head


def rules_block(project_dir: str, cfg: source.SourceConfig) -> str:
    rules = source.read_rules(project_dir, cfg)
    return f'\n### Version rules\n\n{rules}\n' if rules else ''


def bibles_text(project_dir: str) -> list[tuple[str, str]]:
    """[(label, text)] of the source bibles, or [] with no source block.
    Raises SourceError for a source not imported or a bible unreadable."""
    cfg = source.read_config(project_dir)
    return source.source_bibles(project_dir, cfg) if cfg else []


# ----------------------------------------------------------------------------
# Spine
# ----------------------------------------------------------------------------

def spine_section(project_dir: str) -> str:
    cfg = _cfg(project_dir)
    if not cfg:
        return ''
    parts = [f'## Source\n\n{_header(cfg)}',
             'The spine is a selection and reframing of the source\'s events, not an '
             'invention: choose the source events this version turns on, and keep their '
             'order unless a version rule says otherwise. Each spine event\'s function names '
             'the source event it comes from.']
    for slug in cfg.slugs():
        if cfg.project(slug).range is not None:
            parts.append(_span_events(project_dir, cfg, slug))
            continue
        spine = source.read_table(project_dir, slug, 'spine.csv')
        if spine:
            rows = '\n'.join(f'{r.get("seq", "")}|{r.get("id", "")}|{r.get("title", "")}|'
                             f'{r.get("summary", "") or r.get("function", "")}'
                             for r in sorted(spine, key=source._seq))
            parts.append(f'### The source\'s irreducible events ({slug}/spine.csv)\n\n'
                         f'```\nseq|id|title|summary\n{rows}\n```')
        else:
            parts.append(f'The source `{slug}` has no spine; its events are in the Source '
                         f'Bible, in reading order.')
    return '\n\n'.join(parts) + rules_block(project_dir, cfg)


def _span_events(project_dir: str, cfg: source.SourceConfig, slug: str) -> str:
    """A ranged source's events for the spine: the span's scenes. The
    source's own spine.csv isn't shown: its rows name no scenes, so it can't
    be cut to the span, and the whole book's turning points would pull the
    spine past it."""
    everything = source.source_scenes(project_dir, slug)
    scenes = source.adapted_scenes(project_dir, cfg, slug, everything)
    rng = cfg.project(slug).range
    rows = '\n'.join(f'{s.get("seq", "")}|{s.get("id", "")}|{s.get("title", "")}|'
                     f'{s.get("summary", "")}' for s in scenes)
    return (f'### The adapted span ({slug}: {rng.describe()}, {len(scenes)} of '
            f'{len(everything)} scenes)\n\n'
            f'This version adapts only these scenes of `{slug}`; choose its spine from their '
            f'events. The source\'s own spine covers the whole source, so it isn\'t shown; '
            f'the events before and after the span are context in the Source Bible.\n\n'
            f'```\nseq|id|title|summary\n{rows}\n```')


# ----------------------------------------------------------------------------
# Architecture
# ----------------------------------------------------------------------------

def architecture_section(project_dir: str) -> str:
    cfg = _cfg(project_dir)
    if not cfg:
        return ''
    ranged = any(p.range is not None for p in cfg.projects)
    parts = [f'## Source\n\n{_header(cfg)}',
             'Build the architecture from the source\'s cast. The POV distribution below is '
             + ('the source\'s (within the adapted span, for a source with a range)'
                if ranged else 'the source\'s')
             + '; keep it, or change it where the version rules or a POV shift '
             'call for it.']
    for slug in cfg.slugs():
        rng = cfg.project(slug).range
        scenes = source.adapted_scenes(project_dir, cfg, slug)
        in_span = {s.get('id', '') for s in scenes}
        chars = {c.get('id', ''): c for c in source.read_table(project_dir, slug, 'characters.csv')}
        pov: dict[str, int] = {}
        for s in scenes:
            p = s.get('pov', '').strip()
            if p:
                pov[p] = pov.get(p, 0) + 1
        on_stage: dict[str, int] = {}
        for r in source.read_table(project_dir, slug, 'scene-intent.csv'):
            if rng is not None and r.get('id', '') not in in_span:
                continue
            for cid in source.split_ids(r.get('on_stage', '')):
                on_stage[cid] = on_stage.get(cid, 0) + 1
        span = f', {rng.describe()}' if rng else ''
        lines = [f'### {slug}: POV distribution ({len(scenes)} scenes{span})', '']
        for cid, n in sorted(pov.items(), key=lambda kv: -kv[1]):
            name = chars.get(cid, {}).get('name', '') or cid
            lines.append(f'- {name} (`{cid}`): {n} scenes ({n / max(1, len(scenes)):.0%})')
        cast = sorted(chars.values(), key=lambda c: -on_stage.get(c.get('id', ''), 0))
        if rng is not None:
            # Who the span puts on stage or in POV; the rest are in the Source Bible
            cast = [c for c in cast if on_stage.get(c.get('id', '')) or pov.get(c.get('id', ''))]
        lines += ['', f'### {slug}: principal cast (by scenes on stage{span})', '']
        for c in cast[:30]:
            cid = c.get('id', '')
            role = c.get('role', '').strip()
            lines.append(f'- {c.get("name", "") or cid} (`{cid}`)'
                         + (f', {role}' if role else '')
                         + f': on stage in {on_stage.get(cid, 0)}')
        if len(cast) > 30:
            lines.append(f'- ... {len(cast) - 30} more in the Source Bible')
        if rng is not None and len(cast) < len(chars):
            lines.append(f'- ({len(chars) - len(cast)} of the source\'s characters are not '
                         f'on stage in the adapted span; they are in the Source Bible)')
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts) + rules_block(project_dir, cfg)


# ----------------------------------------------------------------------------
# Map
# ----------------------------------------------------------------------------

def map_section(project_dir: str) -> str:
    cfg = _cfg(project_dir)
    if not cfg:
        return ''
    multi = len(cfg.slugs()) > 1
    parts = [f'## Source\n\n{_header(cfg)}']
    ranged = []
    for slug in cfg.slugs():
        everything = source.source_scenes(project_dir, slug)
        scenes = source.adapted_scenes(project_dir, cfg, slug, everything)
        rng = cfg.project(slug).range
        intent = {r.get('id', ''): r for r in source.read_table(project_dir, slug, 'scene-intent.csv')}
        rows = '\n'.join(
            f'{s.get("seq", "")}|{s.get("id", "")}|{s.get("title", "")}|'
            f'{s.get("timeline_day", "")}|{s.get("pov", "")}|'
            f'{intent.get(s.get("id", ""), {}).get("function", "") or s.get("summary", "")}'
            for s in scenes)
        count = (f'{len(scenes)}' if rng is None else
                 f'{len(scenes)} of {len(everything)}: {rng.describe()}')
        if rng is not None:
            ranged.append(f'`{slug}` ({rng.describe()})')
        parts.append(f'### Source scenes: {slug} ({count})\n\n'
                     f'```\nseq|id|title|timeline_day|pov|function\n{rows}\n```')
    if ranged:
        parts.append(f'This novel adapts only part of {", ".join(ranged)}: the scenes listed '
                     f'above. The source\'s other scenes are context in the Source Bible '
                     f'(what came before, and what comes after); give them no row, adapted '
                     f'or cut.')
    cut_rule = ('a cut needs a reason in its note (a version rule, or why the event '
                'isn\'t needed)')
    ids = ('write each source scene as slug:id, since this novel has more than one source'
           if multi else 'use the source scene ids exactly as listed')
    parts.append(f"""### Source map

Account for **every** source scene above. Each new scene says which source scenes it adapts and how; each source scene left out gets a `cut` row. Output the whole map:

```source-map-csv
scene_id|source_scenes|treatment|note
(one row per scene in your scenes-csv, then one cut row per source scene left out)
```

- `source_scenes`: semicolon-separated source scene ids; {ids}
- `treatment`: `dramatize` (the source scene played as a scene), `compress` (several source scenes, or a long one, in less), `expand` (more than the source gives), `pov-shift` (told from another character), `reorder` (moved out of the source's order), `invent` (no source scene: leave source_scenes empty), `cut` (scene_id empty, the source scene in source_scenes)
- `note`: what changes and why, briefly; {cut_rule}. A scene moved before or after the source's timeline needs a note
- Flashbacks, uneven scene lengths and nested threads are fine""")
    return '\n\n'.join(parts) + rules_block(project_dir, cfg)


# ----------------------------------------------------------------------------
# Briefs
# ----------------------------------------------------------------------------

def _scenes_to_brief(project_dir: str, scene_ids: list[str] | None) -> list[str]:
    from storyforge.elaborate import _read_csv
    ref = os.path.join(project_dir, 'reference')
    scenes = source.active_scenes(project_dir)
    if scene_ids:
        known = {s.get('id') for s in scenes}
        unknown = [s for s in scene_ids if s not in known]
        if unknown:
            log(f'WARNING: not scenes in scenes.csv, so not briefed: {", ".join(unknown)}')
        wanted = set(scene_ids)
        return [s['id'] for s in scenes if s.get('id') in wanted]
    briefed = {r.get('id', '') for r in _read_csv(os.path.join(ref, 'scene-briefs.csv'))
               if r.get('goal', '').strip()}
    return [s['id'] for s in scenes if s.get('id') and s['id'] not in briefed]


def changed_names(project_dir: str, cfg: source.SourceConfig) -> list[tuple[str, str]]:
    """The name map's changed names across the sources, longest first."""
    seen: dict[str, str] = {}
    for p in cfg.projects:
        rel = cfg.map_path(p)
        if rel:
            for s, t in source.load_name_map(source.resolve(project_dir, rel)).changed():
                seen.setdefault(s, t)
    return sorted(seen.items(), key=lambda p: (-len(p[0]), p[0]))


def names_note(project_dir: str, cfg: source.SourceConfig) -> str:
    changed = changed_names(project_dir, cfg)
    if not changed:
        return ''
    pairs = '; '.join(f'{s} → {t}' for s, t in changed)
    return ('The source prose uses the translator\'s names; this novel uses the name map\'s. '
            'Never carry a source name into a brief: write the new name. Changed names: '
            f'{pairs}.')


class _Tables:
    """The imported source's CSVs, read once per prompt."""

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self._cache: dict[tuple[str, str], dict[str, dict]] = {}

    def row(self, slug: str, name: str, key: str) -> dict:
        return self.table(slug, name).get(key, {})

    def table(self, slug: str, name: str) -> dict[str, dict]:
        if (slug, name) not in self._cache:
            self._cache[(slug, name)] = {
                r.get('id', ''): r for r in source.read_table(self.project_dir, slug, name)}
        return self._cache[(slug, name)]


def source_scene_block(project_dir: str, slug: str, sid: str, *, prose: bool,
                       tables: _Tables | None = None) -> str:
    """One source scene for a prompt: its brief (with the facts its
    knowledge_out names), and with `prose`, its text."""
    t = tables or _Tables(project_dir)
    scene = t.row(slug, 'scenes.csv', sid)
    brief = t.row(slug, 'scene-briefs.csv', sid)
    intent = t.row(slug, 'scene-intent.csv', sid)
    facts = t.table(slug, 'commitments.csv')
    lines = [f'#### Source scene {slug}:{sid}' + (f': {scene["title"]}' if scene.get('title') else '')]
    for key, val in (('summary', scene.get('summary', '') or intent.get('function', '')),
                     ('pov', scene.get('pov', '')), ('on_stage', intent.get('on_stage', '')),
                     ('timeline_day', scene.get('timeline_day', '')),
                     ('told_by', scene.get('told_by', ''))):
        if val.strip():
            lines.append(f'**{key}:** {val.strip()}')
    for key in _BRIEF_FIELDS:
        val = brief.get(key, '').strip()
        if not val:
            continue
        if key == 'knowledge_out':
            val = '; '.join(f'{f} ({facts[f]["statement"]})' if facts.get(f, {}).get('statement')
                            else f for f in source.split_ids(val))
        lines.append(f'**{key}:** {val}')
    if prose:
        text = source.source_prose(project_dir, slug, sid)
        lines.append(f'\n<source-prose scene="{sid}">\n{text}\n</source-prose>'
                     if text else '\n(no source prose for this scene)')
    return '\n'.join(lines)


def briefs_section(project_dir: str, scene_ids: list[str] | None) -> str:
    cfg = _cfg(project_dir)
    if not cfg:
        return ''
    rows = source.read_source_map(project_dir) or []
    by_scene = source.map_rows_by_scene(rows)
    cat = source.catalogue(project_dir, cfg)
    spans = source.spans(project_dir, cfg)
    targets = _scenes_to_brief(project_dir, scene_ids)

    parts = [f'## Source\n\n{_header(cfg)}',
             'Write each brief while looking at the source text below: keep the source\'s '
             'events, outcomes and turns for what the treatment keeps, and make every '
             'departure one the treatment, its note or the version rules call for. Key '
             'dialogue keeps the substance of the source\'s lines in this novel\'s voice; '
             'never copy the translation\'s wording.']
    note = names_note(project_dir, cfg)
    if note:
        parts.append(note)

    tables = _Tables(project_dir)
    budget = SOURCE_PROSE_MAX_WORDS
    no_prose: list[str] = []
    unmapped: list[str] = []
    unresolved: list[str] = []
    outside: list[str] = []
    blocks = []
    for sid in targets:
        row = by_scene.get(sid)
        if not row:
            unmapped.append(sid)
            continue
        refs = [source.resolve_source_id(r, cat) for r in source.split_ids(row.get('source_scenes', ''))]
        head = f'### {sid}: {row.get("treatment", "")}'
        if row.get('note'):
            head += f' ({row["note"]})'
        if not refs:
            blocks.append(f'{head}\n\n' + ('An invented scene: no source scene.'
                                             if row.get('treatment') == 'invent'
                                             else 'No source scene given.'))
            continue
        body = [head]
        for ref, hit in zip(source.split_ids(row.get('source_scenes', '')), refs):
            if hit is None:
                unresolved.append(f'{sid} ({ref})')
                body.append(f'#### Source scene {ref}: not found in the imported source')
                continue
            if source.outside_range(hit, spans):
                outside.append(f'{sid} ({ref}: {hit[0]} adapts '
                               f'{source.range_note(cfg, hit[0])})')
                continue
            words = len((source.source_prose(project_dir, *hit) or '').split())
            show = words <= budget
            if show:
                budget -= words
            else:
                no_prose.append(f'{hit[0]}:{hit[1]}')
            body.append(source_scene_block(project_dir, hit[0], hit[1], prose=show,
                                            tables=tables))
        blocks.append('\n\n'.join(body))
    # Said to the author as well as to the model
    if not rows:
        log('WARNING: no reference/source-map.csv yet: the briefs prompt has no source '
            'scenes, only the Source Bible')
    if unmapped:
        log(f'WARNING: not in the source map, briefed without source scenes: '
            f'{", ".join(unmapped)}')
    if unresolved:
        log(f'WARNING: source scenes not found in the imported source (run validate): '
            f'{", ".join(unresolved)}')
    if outside:
        # A brief written without its source would be wrong, and validate
        # blocks the row anyway: stop before anything is spent
        raise source.SourceError(
            f'the source map adapts scenes outside the adapted range: '
            f'{", ".join(outside)}; widen `range` in storyforge.yaml (and re-run '
            f'`storyforge source import`) or fix the map, then run validate')
    if no_prose:
        log(f'WARNING: source prose left out of the briefs prompt (over '
            f'{SOURCE_PROSE_MAX_WORDS:,} words): {", ".join(no_prose)}; brief fewer '
            f'scenes at a time with --scene')
    if not rows:
        parts.append('There is no source map yet (reference/source-map.csv), so no scene '
                     'is matched to its source scenes; brief from the Source Bible.')
    elif unmapped:
        parts.append(f'Not in the source map, so shown without source scenes: '
                     f'{", ".join(unmapped)}.')
    if no_prose:
        parts.append(f'Source prose left out to keep this prompt under '
                     f'{SOURCE_PROSE_MAX_WORDS:,} words of source text (their source briefs '
                     f'are given): {", ".join(no_prose)}. Brief fewer scenes at a time '
                     f'(--scene a,b,c) to see it.')
    parts += blocks
    return '\n\n'.join(parts) + rules_block(project_dir, cfg)
