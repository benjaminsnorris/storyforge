"""Source fidelity: an adaptation's briefs or prose against its source (#477).

The same shape as brief fidelity (`scoring.build_fidelity_prompt`), with the
source scenes on the left-hand side: one call per mapped scene (score uses
the evaluation tier, Sonnet) compares the scene's brief, or its prose, with the source scenes it adapts
(`reference/source-map.csv`) on `ELEMENTS`, lists every departure and tags it
(`TAGS`): `deliberate` (the map row's treatment or note, or a version rule
under `source.rules`, authorizes it), `moved` (a beat moved to or from a
neighbouring book scene: the prompt also shows the nearest mapped scene
before and after this one, with their map rows and source scenes, and the
authority names the neighbour), `staging` (connective invention that
changes no event, fact or outcome; in `free` mode, or in `faithful` mode
when a version rule or the scene's note, which must exist, allows it; never
on `outcome` or `knowledge_out`) or `drift` (nothing does). The prompt asks
for elements scored 1-5 on drift only; the code doesn't check that the
scores follow the drift. Drift is what revise reads (#617: the Telemachy
pilot's 80 drift were 24 moved, 46 staging, 8 false alarms and 2 real
departures). A `moved ... to: <neighbour>` claim is confirmed against the
neighbour's result in the same run, and a WARNING lists those that aren't.
With a `range:`, a scene whose map row names a source scene outside it is
not checked (it is broken data, which validate blocks on).

A reply whose rows name the one source scene the map row names in place of
the book scene's id is read as the book scene's (#618), logged, and kept in
the scores file's `remapped` column. A reply that can't be parsed is asked
again once, with what was wrong; both calls are logged and costed. A refused
or cut-off reply is not asked again: it is the failure.

Output, in the score cycle's directory: `source-fidelity.csv`
(`SCORE_COLUMNS`) and `source-fidelity-rationale.csv` (`RATIONALE_COLUMNS`),
merged by (scene, target) so a briefs run and a prose run share a cycle.
`target_hash` records what was scored; `latest_drift` only returns drift
whose brief or prose hasn't changed since, which is what revise's upstream
fix reads (so a fixed brief isn't fixed again on stale scores). `mode` is
the revise hook's business: in `free` mode drift is reported, not fixed.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field

from storyforge import source
from storyforge.common import csv_safe, log

ELEMENTS = ('goal', 'outcome', 'key_actions', 'key_dialogue', 'on_stage', 'knowledge_out')
TAGS = ('deliberate', 'moved', 'staging', 'drift')
TARGETS = ('brief', 'prose')

SCORES_FILE = 'source-fidelity.csv'
RATIONALE_FILE = 'source-fidelity-rationale.csv'
SCORE_COLUMNS = ['id', 'target', 'target_hash', *ELEMENTS, 'overall', 'drift', 'deliberate',
                 'moved', 'staging', 'remapped']
# The header before `moved`, `staging` and `remapped` (#617, #618): a cycle
# scored then is still read, its rows' new cells empty (not counted, not zero)
_OLDER_SCORE_COLUMNS = (
    ['id', 'target', 'target_hash', 'goal', 'outcome', 'key_actions', 'key_dialogue',
     'on_stage', 'knowledge_out', 'overall', 'drift', 'deliberate'],
)
# Elements staging can't be on: a changed outcome or new fact is not staging
_NO_STAGING = ('outcome', 'knowledge_out')
# Elements whose staging departures report() lists, not only counts
_STAGING_LISTED = ('goal', 'key_actions', 'key_dialogue')
RATIONALE_COLUMNS = ['id', 'target', 'element', 'tag', 'evidence', 'authority']

# The brief fields a brief target shows (knowledge_out with its statements)
_BRIEF_FIELDS = ('goal', 'conflict', 'outcome', 'crisis', 'decision', 'key_actions',
                 'key_dialogue', 'knowledge_out')
# The source fields compared (plus summary, pov and on_stage for orientation)
_SOURCE_FIELDS = ('goal', 'outcome', 'key_actions', 'key_dialogue', 'knowledge_out')
# Brief fields the target shows that aren't scored elements: a departure on
# one is kept in the rationale under its own name, never a failed scene. The
# model comments on what it is shown (Beowulf B-023: 3 of 48 scenes lost)
NOTED_FIELDS = ('title', 'pov', 'conflict', 'crisis', 'decision')
# How knowledge_out is shown on both sides: what the scene adds. The briefs
# prompt makes knowledge_out knowledge_in plus the scene's new facts, so the
# whole list compared with a source scene's own facts read every carried
# fact as drift (Gawain G-024: 36 of 95 drift items)
KNOWLEDGE_LABEL = 'knowledge_out (new in this scene)'


def new_facts(brief: dict) -> list[str]:
    """The fact ids a brief's knowledge_out adds to its knowledge_in."""
    carried = set(source.split_ids(brief.get('knowledge_in', '')))
    return [f for f in source.split_ids(brief.get('knowledge_out', '')) if f not in carried]


class SourceFidelityError(Exception):
    """A reply that can't be used: refused, cut off, or not in the format."""


@dataclass(frozen=True)
class Result:
    scene_id: str
    target: str
    target_hash: str
    scores: dict[str, int]
    departures: list[dict[str, str]] = field(default_factory=list)
    remapped: str = ''    # the source scene id the reply's rows named in place of scene_id

    def __post_init__(self):
        if self.target not in TARGETS:
            raise ValueError(f'target {self.target!r}')
        if set(self.scores) != set(ELEMENTS) or not all(
                isinstance(v, int) and 1 <= v <= 5 for v in self.scores.values()):
            raise ValueError(f'{self.scene_id}: scores must be 1-5 for exactly {ELEMENTS}')
        for d in self.departures:
            if (set(d) != {'element', 'tag', 'evidence', 'authority'}
                    or d['element'] not in ELEMENTS + NOTED_FIELDS or d['tag'] not in TAGS
                    or not d['evidence'] or (d['authority'] == 'none') != (d['tag'] == 'drift')):
                raise ValueError(f'{self.scene_id}: departure {d!r}')

    @property
    def overall(self) -> float:
        from storyforge.scoring import _power_mean
        return round(_power_mean([float(v) for v in self.scores.values()]), 1)

    def count(self, tag: str) -> int:
        if tag not in TAGS:
            raise ValueError(f'tag {tag!r} (one of {", ".join(TAGS)})')
        return sum(1 for d in self.departures if d['tag'] == tag)


# ============================================================================
# The two sides
# ============================================================================

def _project_tables(project_dir: str) -> dict[str, dict[str, dict]]:
    from storyforge.elaborate import _read_csv
    ref = os.path.join(project_dir, 'reference')
    return {name: {r.get('id', ''): r for r in _read_csv(os.path.join(ref, name))}
            for name in ('scenes.csv', 'scene-intent.csv', 'scene-briefs.csv',
                         'commitments.csv')}


def target_text(project_dir: str, scene_id: str, target: str,
                tables: dict | None = None) -> str | None:
    """What is scored for a scene: its brief (with on_stage and the facts its
    knowledge_out names), or its prose without illustration markers. None
    when there is none (no brief goal, or no prose file)."""
    if target == 'prose':
        from storyforge.illustrations import read_scene_prose
        path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        try:
            prose = read_scene_prose(path).strip()
        except FileNotFoundError:
            return None
        return prose or None
    t = tables or _project_tables(project_dir)
    brief = t['scene-briefs.csv'].get(scene_id, {})
    if not brief.get('goal', '').strip():
        return None
    scene = t['scenes.csv'].get(scene_id, {})
    intent = t['scene-intent.csv'].get(scene_id, {})
    facts = t['commitments.csv']
    lines = []
    for key, val in (('title', scene.get('title', '')), ('pov', scene.get('pov', '')),
                     ('on_stage', intent.get('on_stage', ''))):
        if val.strip():
            lines.append(f'**{key}:** {val.strip()}')
    for key in _BRIEF_FIELDS:
        val = brief.get(key, '').strip()
        if not val:
            continue
        if key == 'knowledge_out':
            val = '; '.join(f'{f} ({facts[f]["statement"]})' if facts.get(f, {}).get('statement')
                            else f for f in new_facts(brief))
            if not val:
                continue
            key = KNOWLEDGE_LABEL
        lines.append(f'**{key}:** {val}')
    return '\n'.join(lines)


def target_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def _source_side(project_dir: str, refs: list[tuple[str, str]], tables=None,
                 heading: str = '###') -> str:
    from storyforge.prompts_source import _Tables
    t = tables or _Tables(project_dir)
    blocks = []
    for slug, sid in refs:
        scene = t.row(slug, 'scenes.csv', sid)
        brief = t.row(slug, 'scene-briefs.csv', sid)
        intent = t.row(slug, 'scene-intent.csv', sid)
        facts = {k: r.get('statement', '') for k, r in t.table(slug, 'commitments.csv').items()}
        lines = [f'{heading} {slug}:{sid}' + (f': {scene["title"]}' if scene.get('title') else '')]
        summary = scene.get('summary', '') or intent.get('function', '')
        for key, val in (('summary', summary), ('pov', scene.get('pov', '')),
                         ('on_stage', intent.get('on_stage', ''))):
            if val.strip():
                lines.append(f'**{key}:** {val.strip()}')
        for key in _SOURCE_FIELDS:
            val = brief.get(key, '').strip()
            if not val:
                continue
            if key == 'knowledge_out':
                val = '; '.join(f'{f} ({facts[f]})' if facts.get(f) else f
                                for f in new_facts(brief))
                if not val:
                    continue
                key = KNOWLEDGE_LABEL
            lines.append(f'**{key}:** {val}')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def source_fixed_outcomes(project_dir: str) -> list[str]:
    """The scenes whose outcome a `faithful` adaptation takes from its source,
    in map order: for each source scene, the last scene (by seq) whose map row
    ends on it. A single-source scene keeps the source's outcome; of a source
    scene split in several, the last part keeps it and the earlier parts carry
    their own; invented scenes are free. [] for no `source:` block, `free`
    mode or no map yet. Raises SourceError for a block or map that can't be
    read (#550, Gawain G-025: the outcome review relabelled nine scenes the
    source fixes, and source fidelity then flagged each as drift)."""
    cfg = source.read_config(project_dir)
    if cfg is None or cfg.mode != 'faithful':
        return []
    rows = source.read_source_map(project_dir) or []
    from storyforge.elaborate import _read_csv_as_map
    scenes = _read_csv_as_map(os.path.join(project_dir, 'reference', 'scenes.csv'))

    def seq(sid: str) -> int:
        val = (scenes.get(sid) or {}).get('seq', '')
        return int(val) if val.isdigit() else 0

    last: dict[str, str] = {}
    for row in rows:
        sid = row.get('scene_id', '')
        refs = source.split_ids(row.get('source_scenes', ''))
        if not sid or not refs or row.get('treatment') == 'invent':
            continue
        if refs[-1] not in last or seq(sid) >= seq(last[refs[-1]]):
            last[refs[-1]] = sid
    return sorted(set(last.values()), key=seq)


# ============================================================================
# Prompt
# ============================================================================

@dataclass(frozen=True)
class ReplyRules:
    """What reading one scene's reply needs (#617, #618): the adaptation's
    `mode`; `aliases`, the ids read as the scene's own (the one source scene
    its map row names); `neighbours`, (name, book scene id) pairs a `moved`
    authority may name (each neighbour's book id and its source scenes'
    ids); and whether the scene's map row has a note and the project has
    version rules, which a faithful `staging` authority must point at."""
    mode: str
    aliases: frozenset = frozenset()
    neighbours: tuple = ()
    has_note: bool = False
    has_rules: bool = False

    def __post_init__(self):
        if self.mode not in source.MODES:
            raise ValueError(f'mode {self.mode!r} (one of {", ".join(source.MODES)})')

    @property
    def names(self) -> frozenset:
        return frozenset(n for n, _ in self.neighbours)

    def neighbour_named(self, authority: str) -> str | None:
        """The neighbour's book id an authority names, or None."""
        for name, book_id in sorted(self.neighbours, key=lambda p: -len(p[0])):
            if re.search(rf'(?<![\w:-]){re.escape(name)}(?![\w-])', authority):
                return book_id
        return None


@dataclass(frozen=True)
class Plan:
    """What one scene's check needs, or why it can't be checked: exactly one
    of `prompt` (with its `target_hash` and the `rules` for reading the
    reply) and `skip`. `notes` are WARNINGs about the prompt (neighbours not
    known or not shown)."""
    scene_id: str
    prompt: str = ''
    target_hash: str = ''
    skip: str = ''        # why there is no prompt ('' when there is one)
    broken: bool = False  # the skip means the data is wrong, not that there's nothing to do
    rules: ReplyRules | None = None
    notes: tuple = ()

    def __post_init__(self):
        if (bool(self.prompt) == bool(self.skip) or bool(self.prompt) != bool(self.target_hash)
                or bool(self.prompt) != (self.rules is not None)):
            raise ValueError(f'{self.scene_id}: a Plan has a prompt, its hash and its rules, '
                             f'or a skip')


def _is_mapped(row: dict | None) -> bool:
    return bool(row and row.get('treatment') != 'invent'
                and source.split_ids(row.get('source_scenes', '')))


def reading_order(project_dir: str) -> list[str]:
    """The active scenes' ids in reading order (`source.active_scenes`)."""
    return [r['id'] for r in source.active_scenes(project_dir)]


def neighbours(scene_id: str, order: list[str],
               map_rows: dict[str, dict]) -> tuple[str | None, str | None] | None:
    """The nearest book scene before and after `scene_id` in `order` whose
    map row names source scenes (invented and unmapped scenes are passed
    over), None on a side with none. None, not known, when the scene isn't
    in `order` (cut, merged, archived, or not in scenes.csv)."""
    if scene_id not in order:
        return None
    i = order.index(scene_id)
    before = next((s for s in reversed(order[:i]) if _is_mapped(map_rows.get(s))), None)
    after = next((s for s in order[i + 1:] if _is_mapped(map_rows.get(s))), None)
    return before, after


def _id_forms(ref: tuple[str, str], cat: dict) -> set[str]:
    """The ways a reply can name a source scene: `slug:id`, and the bare id
    when the catalogue resolves it to that scene."""
    slug, sid = ref
    return {f'{slug}:{sid}'} | ({sid} if source.resolve_source_id(sid, cat) == ref else set())


def _neighbour_side(project_dir: str, scene_id: str, own: list[tuple[str, str]],
                    order: list[str], map_rows: dict[str, dict], cat: dict,
                    spans: dict, source_tables) -> tuple[str, tuple, tuple]:
    """The neighbours' block of the prompt, the (name, book id) pairs a
    `moved` authority may use (each neighbour's book id and its source
    scenes' ids), and WARNINGs: neighbours not known, or a neighbour whose
    source scenes can't be shown."""
    near = neighbours(scene_id, order, map_rows)
    if near is None:
        return ('### Neighbouring scenes: unknown (this scene is not in the reading order: '
                'it has no seq, or is cut or merged). Do not use `moved`.', (),
                (f'{scene_id} is not in the reading order, so its neighbours are unknown '
                 f'and `moved` can\'t be used',))
    blocks, names, notes = [], set(), []
    for where, nid in zip(('before', 'after'), near):
        if nid is None:
            blocks.append(f'### The book scene {where} it: none (no scene {where} this one '
                          f'adapts a source scene)')
            continue
        row = map_rows[nid]
        names.add((nid, nid))
        lines = [f'### The book scene {where} it: `{nid}`',
                 f'**Its map row:** `{row.get("treatment", "")}`'
                 + (f'. {row["note"].strip()}' if row.get('note', '').strip() else '')]
        refs = [source.resolve_source_id(r, cat) for r in source.split_ids(row['source_scenes'])]
        if any(r is None for r in refs) or any(source.outside_range(r, spans) for r in refs):
            lines.append('(Its source scenes are not in the imported source, or are outside '
                         'the adapted range, so they are not shown.)')
            notes.append(f'{scene_id}: the neighbouring scene {nid}\'s source scenes are not '
                         f'in the imported source or outside the range, so they are not shown '
                         f'(run validate)')
        else:
            for r in refs:
                names |= {(n, nid) for n in _id_forms(r, cat)}
            shared = [f'{slug}:{sid}' for slug, sid in refs if (slug, sid) in own]
            if shared:
                lines.append(f'It also adapts {", ".join(shared)}, shown above as this '
                             f'scene\'s own source.')
            new = [r for r in refs if r not in own]
            if new:
                lines.append(_source_side(project_dir, new, source_tables, heading='####'))
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks), tuple(sorted(names)), tuple(notes)


#: What the prompt says about `staging`, by mode
_STAGING = {
    'free': ('This adaptation\'s mode is `free`, which allows connective invention: name '
             '`mode: free`, or the version rule that allows it, in `authority`.'),
    'faithful': ('This adaptation\'s mode is `faithful`, so `staging` is allowed only when a '
                 'version rule above or this scene\'s note allows connective invention: start '
                 '`authority` with `rule:` or `note`. Otherwise connective invention is '
                 '`drift`.'),
}


def plan_scene(project_dir: str, scene_id: str, target: str, plugin_dir: str,
               cfg: source.SourceConfig, map_rows: dict[str, dict],
               rules: str, tables: dict | None = None,
               cat: dict | None = None, source_tables=None,
               spans: dict | None = None, order: list[str] | None = None) -> Plan:
    """One scene's check, or why there is none. `cat`, `spans` (each
    source's adapted scene ids, from `source.spans`) and `order` (the reading
    order, `reading_order`) are read when not given; a caller planning many
    scenes passes them. A map row naming a source scene outside its source's
    `range:` is broken: only the range is being adapted, and validate blocks
    on it."""
    if target not in TARGETS:
        raise ValueError(f'target must be one of {TARGETS}')
    row = map_rows.get(scene_id)
    if row is None:
        return Plan(scene_id, skip='not in the source map (run validate)', broken=True)
    if row.get('treatment') == 'invent':
        return Plan(scene_id, skip='invented (no source scene)')
    cat = cat if cat is not None else source.catalogue(project_dir, cfg)
    refs = [source.resolve_source_id(r, cat) for r in source.split_ids(row.get('source_scenes', ''))]
    if not refs or any(r is None for r in refs):
        return Plan(scene_id, skip='its source scenes are not in the imported source '
                                   '(run validate)', broken=True)
    spans = spans if spans is not None else source.spans(project_dir, cfg)
    outside = [f'{slug}:{sid}' for slug, sid in refs if source.outside_range((slug, sid), spans)]
    if outside:
        return Plan(scene_id, skip=f'its source scenes {", ".join(outside)} are outside the '
                                   f'adapted range (run validate)', broken=True)
    tables = tables or _project_tables(project_dir)
    text = target_text(project_dir, scene_id, target, tables)
    if text is None:
        return Plan(scene_id, skip='no brief' if target == 'brief' else 'no prose')

    order = order if order is not None else reading_order(project_dir)
    if source_tables is None:
        from storyforge.prompts_source import _Tables
        source_tables = _Tables(project_dir)
    near, near_names, notes = _neighbour_side(project_dir, scene_id, refs, order, map_rows,
                                              cat, spans, source_tables)
    # A reply naming the one source scene in place of the book scene (#618);
    # never another book scene's id, cut ones included
    aliases = _id_forms(refs[0], cat) if len(refs) == 1 else set()
    aliases -= set(tables['scenes.csv']) - {scene_id}

    template_path = os.path.join(plugin_dir, 'scripts', 'prompts', 'scoring',
                                 'source-fidelity.md')
    with open(template_path, encoding='utf-8') as f:
        template = f.read()
    kind = 'brief' if target == 'brief' else 'prose'
    prompt = (template
              .replace('{SOURCE_DATA}', _source_side(project_dir, refs, source_tables))
              .replace('{NEIGHBOURS}', near)
              .replace('{STAGING}', _STAGING.get(cfg.mode, _STAGING['faithful']))
              .replace('{TREATMENT}', row.get('treatment', ''))
              .replace('{NOTE}', row.get('note', '') or '(none)')
              .replace('{MODE}', cfg.mode)
              .replace('{RULES}', rules or '(none)')
              .replace('{TARGET_DATA}', text)
              .replace('{TARGET_KIND}', kind)
              .replace('{SCENE_ID}', scene_id))
    rules_ = ReplyRules(cfg.mode, frozenset(aliases), near_names,
                        has_note=bool(row.get('note', '').strip()),
                        has_rules=bool((rules or '').strip()))
    return Plan(scene_id, prompt=prompt, target_hash=target_hash(text), rules=rules_,
                notes=notes)


# ============================================================================
# Parsing
# ============================================================================

def _authority_problem(tag: str, element: str, authority: str, rules: ReplyRules) -> str:
    """Why a departure's authority doesn't fit its tag, or ''."""
    none = authority.lower() in ('', 'none')
    if tag == 'drift':
        return '' if none else (f'a drift departure on {element} that names an authority '
                                f'({authority}): drift has none')
    if none:
        return f'a {tag} departure on {element} with no authority'
    if tag == 'moved' and rules.neighbour_named(authority) is None:
        books = sorted({b for _, b in rules.neighbours})
        return (f'a moved departure on {element} whose authority ({authority}) names no '
                f'neighbouring scene' + (f' ({", ".join(books)})' if books
                                         else ': this scene has none shown'))
    if tag == 'staging' and element in _NO_STAGING:
        return (f'a staging departure on {element}: a changed outcome or a new fact is not '
                f'staging')
    if tag == 'staging' and rules.mode == 'faithful':
        lead = authority.strip().lower()
        if re.match(r'(version )?rules?\b', lead):
            if not rules.has_rules:
                return (f'a staging departure on {element} authorized by {authority}: this '
                        f'project has no version rules')
        elif re.match(r'note\b', lead):
            if not rules.has_note:
                return (f'a staging departure on {element} authorized by {authority}: this '
                        f'scene\'s map row has no note')
        else:
            return (f'a staging departure on {element} authorized by {authority}: in faithful '
                    f'mode only a version rule or the note allows connective invention '
                    f'(start the authority with `rule:` or `note`)')
    return ''


def _clean_authority(cell: str) -> str:
    """An authority cell without the backticks and quotes models put round it."""
    return re.sub(r'[`"]', '', cell).strip().strip("'").strip()


def parse_response(response: str, scene_id: str, target: str, hash_: str,
                   rules: ReplyRules) -> Result:
    """The reply's SCORES and DEPARTURES, read by the scene's `rules`.
    Raises SourceFidelityError when an element has no 1-5 score, or a
    departure names an unknown element or tag, says nothing, or its
    authority doesn't fit its tag (`_authority_problem`: `drift` has none;
    `moved` names a neighbour; `staging` is never on outcome or
    knowledge_out, and in `faithful` mode names a rule the project has or
    the note the scene has): a result with a misread tag would send the
    wrong scenes to revise. Rows naming one of `rules.aliases` (the one
    source scene the map row names) are read as `scene_id`'s, and the Result
    says so (`remapped`)."""
    aliases = rules.aliases
    scores: dict[str, int] = {}
    departures: list[dict[str, str]] = []
    problems: list[str] = []
    score_rows = 0
    remapped = ''
    section = None
    for line in response.splitlines():
        s = line.strip().strip('`')
        if not s:
            continue
        if re.match(r'^\**SCORES\**:?$', s, re.I):
            section = 'scores'
            continue
        if re.match(r'^\**DEPARTURES\**:?$', s, re.I):
            section = 'departures'
            continue
        parts = [p.strip() for p in s.split('|')]
        if parts[0] == 'id' or section is None:
            continue
        if parts[0] != scene_id and parts[0] in aliases:
            remapped, parts[0] = parts[0], scene_id
        if parts[0] != scene_id:
            problems.append(f'a row for {parts[0]!r}, not {scene_id}')
            continue
        if section == 'scores':
            score_rows += 1
            if score_rows > 1:
                problems.append('more than one SCORES row')
                continue
            if len(parts) != len(ELEMENTS) + 1:
                problems.append(f'a SCORES row with {len(parts)} cells')
                continue
            for el, val in zip(ELEMENTS, parts[1:]):
                if val.isdigit() and 1 <= int(val) <= 5:
                    scores[el] = int(val)
                else:
                    problems.append(f'{el} score {val!r} is not 1-5')
        else:
            if len(parts) != 5:
                # a | inside the text would cut the evidence short
                problems.append(f'a DEPARTURES row with {len(parts)} cells, not 5')
                continue
            element, tag, evidence = parts[1], parts[2].strip('`*').lower(), parts[3]
            authority = _clean_authority(parts[4])
            if element not in ELEMENTS and element not in NOTED_FIELDS:
                problems.append(f'departure element {element!r}')
            elif tag not in TAGS:
                problems.append(f'departure tag {tag!r} ({", ".join(TAGS)})')
            elif not evidence:
                problems.append(f'a {tag} departure on {element} that says nothing')
            elif why := _authority_problem(tag, element, authority, rules):
                problems.append(why)
            else:
                departures.append({'element': element, 'tag': tag, 'evidence': evidence,
                                   'authority': 'none' if tag == 'drift' else authority})
    missing = [el for el in ELEMENTS if el not in scores]
    if missing and not problems:
        problems.append(f'no score for {", ".join(missing)}')
    if problems:
        raise SourceFidelityError(f'{scene_id}: ' + '; '.join(problems))
    return Result(scene_id, target, hash_, scores, departures, remapped)


# ============================================================================
# Files
# ============================================================================

def _read(path: str, columns: list[str], older: tuple = ()) -> list[dict[str, str]]:
    """A results file's rows ([] when there is none), keyed by `columns`. A
    file with one of the `older` headers is read too, the columns it lacks
    empty. Raises SourceError for one that can't be read, has another header,
    or a row with the wrong number of cells: drift read from it would be
    wrong."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise source.SourceError(f'{path} could not be read ({e})') from e
    if not lines:
        return []
    header = lines[0].split('|')
    if header != columns and header not in [list(h) for h in older]:
        raise source.SourceError(f'{path}: the header must be {"|".join(columns)}; '
                                 f're-run score --source-fidelity')
    rows = [l.split('|') for l in lines[1:]]
    bad = [n for n, r in enumerate(rows, 2) if len(r) != len(header)]
    if bad:
        raise source.SourceError(f'{path} line {bad[0]}: wrong number of cells')
    return [{c: dict(zip(header, r)).get(c, '') for c in columns} for r in rows]


def _write(path: str, columns: list[str], rows: list[dict[str, str]]) -> None:
    out = ['|'.join(columns)] + ['|'.join(csv_safe(str(r.get(c, ''))) for c in columns)
                                 for r in rows]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(out) + '\n')


def write_results(results: list[Result], out_dir: str) -> None:
    """Merge results into the cycle's two files: a row for the same scene and
    target is replaced; every other row stays."""
    os.makedirs(out_dir, exist_ok=True)
    done = {(r.scene_id, r.target) for r in results}
    scores_path = os.path.join(out_dir, SCORES_FILE)
    rat_path = os.path.join(out_dir, RATIONALE_FILE)
    scores = [r for r in _read(scores_path, SCORE_COLUMNS, _OLDER_SCORE_COLUMNS)
              if (r.get('id'), r.get('target')) not in done]
    rats = [r for r in _read(rat_path, RATIONALE_COLUMNS)
            if (r.get('id'), r.get('target')) not in done]
    for res in results:
        row = {'id': res.scene_id, 'target': res.target, 'target_hash': res.target_hash,
               'overall': res.overall, 'remapped': res.remapped,
               **{tag: res.count(tag) for tag in TAGS}}
        row.update({el: res.scores[el] for el in ELEMENTS})
        scores.append(row)
        rats += [{'id': res.scene_id, 'target': res.target, **d} for d in res.departures]
    _write(scores_path, SCORE_COLUMNS, scores)
    _write(rat_path, RATIONALE_COLUMNS, rats)


def read_scores(cycle_dir: str) -> list[dict[str, str]]:
    """A cycle's `source-fidelity.csv` rows ([] when there is none), an
    older cycle's included (its `moved`/`staging`/`remapped` empty). Raises
    SourceError as `_read` does."""
    return _read(os.path.join(cycle_dir, SCORES_FILE), SCORE_COLUMNS, _OLDER_SCORE_COLUMNS)


def _cycles(project_dir: str) -> list[str]:
    scores_dir = os.path.join(project_dir, 'working', 'scores')
    if not os.path.isdir(scores_dir):
        return []
    found = []
    for name in os.listdir(scores_dir):
        m = re.match(r'^cycle-(\d+)$', name)
        if m and os.path.isfile(os.path.join(scores_dir, name, SCORES_FILE)):
            found.append((int(m.group(1)), os.path.join(scores_dir, name)))
    return [p for _, p in sorted(found, reverse=True)]


@dataclass
class DriftState:
    """What the newest source-fidelity results say, per scene and target."""
    drift: dict[str, list[str]] = field(default_factory=dict)  # scene -> drift lines
    stale: list[str] = field(default_factory=list)    # scored on a brief/prose since changed
    checked: int = 0                                   # (scene, target) results read
    pretag: int = 0     # current results scored before moved/staging (their drift may be either)

    def pretag_line(self) -> str:
        """What to say about `pretag` ('' for none)."""
        return (f'{self.pretag} source-fidelity result(s) predate the moved/staging tags, so '
                f'their drift may include moved or connective material; re-score to reclassify'
                if self.pretag else '')


def drift_state(project_dir: str) -> DriftState:
    """Drift from each scene's newest source-fidelity result per target, only
    where the brief or prose scored is unchanged since (its hash matches);
    results scored on something since changed are listed `stale`, and
    current results from before the moved/staging tags are counted
    (`pretag`). An empty state for a project without a source block. Raises
    SourceError for a results file that can't be read (see `_read`)."""
    state = DriftState()
    if source.read_config(project_dir) is None:
        return state
    tables = _project_tables(project_dir)
    seen: set[tuple[str, str]] = set()
    for cycle in _cycles(project_dir):
        rats = _read(os.path.join(cycle, RATIONALE_FILE), RATIONALE_COLUMNS)
        for row in _read(os.path.join(cycle, SCORES_FILE), SCORE_COLUMNS,
                         _OLDER_SCORE_COLUMNS):
            key = (row['id'], row['target'])
            if key in seen or key[1] not in TARGETS:
                continue
            seen.add(key)
            state.checked += 1
            current = target_text(project_dir, key[0], key[1], tables)
            if current is None or target_hash(current) != row['target_hash']:
                state.stale.append(f'{key[0]} ({key[1]})')
                continue
            if row['moved'] == '' and row['staging'] == '':
                state.pretag += 1
            lines = [f'{key[1]} {r["element"]}: {r["evidence"]}' for r in rats
                     if (r['id'], r['target']) == key and r['tag'] == 'drift']
            if str(len(lines)) != row['drift']:
                raise source.SourceError(
                    f'{os.path.join(cycle, SCORES_FILE)}: {key[0]} ({key[1]}) counts '
                    f'{row["drift"]} drift but {RATIONALE_FILE} lists {len(lines)}')
            if lines:
                state.drift.setdefault(key[0], []).extend(lines)
    return state


def latest_drift(project_dir: str) -> dict[str, list[str]]:
    """{scene id: its current drift departures as one-line descriptions}
    (`drift_state(...).drift`)."""
    return drift_state(project_dir).drift


# ============================================================================
# Running
# ============================================================================

#: Appended to the prompt when a reply can't be read: one re-ask (#618)
RETRY_NOTE = '''

## Your earlier reply could not be used

Your earlier reply to this prompt is below. It could not be read: {problem}.

Write the whole output again, in the Output Format above, with that fixed. Every row starts with `{scene_id}`.

<earlier_reply>
{reply}
</earlier_reply>
'''

def run(project_dir: str, scene_ids: list[str], target: str, *, plugin_dir: str,
        out_dir: str, log_dir: str, model: str, system: list | None = None,
        parallel: int = 6) -> tuple[list[Result], dict[str, str], dict[str, str]]:
    """Check each mapped scene; write the results into `out_dir`.

    Returns (results, skipped, failed): `skipped` is scene -> why it had
    nothing to check (invented, no brief or prose), `failed` is scene -> why
    there is no result: a check that ran and failed, or a scene whose map
    data is broken (not mapped, source scenes not found or outside the
    source's `range:`). Raises SourceError for a source block, map, range or
    rules file that can't be used, or a source not imported.
    """
    from storyforge.api import (
        calculate_cost_from_usage, extract_text, extract_usage, invoke_to_file, stop_problem,
    )
    from storyforge.costs import log_operation
    from storyforge.runner import run_parallel

    cfg = source.read_config(project_dir)
    if cfg is None:
        raise source.SourceError('storyforge.yaml has no `source:` block')
    rows = source.read_source_map(project_dir)
    if rows is None:
        raise source.SourceError(f'there is no reference/{source.SOURCE_MAP} yet '
                                 f'(elaborate --stage map writes it)')
    map_rows = source.map_rows_by_scene(rows)
    rules = source.read_rules(project_dir, cfg)
    tables = _project_tables(project_dir)

    from storyforge.prompts_source import _Tables
    source.require_imported(project_dir, cfg)
    cat = source.catalogue(project_dir, cfg)
    spans = source.spans(project_dir, cfg)
    src_tables = _Tables(project_dir)
    order = reading_order(project_dir)
    plans = {sid: plan_scene(project_dir, sid, target, plugin_dir, cfg, map_rows, rules,
                             tables, cat, src_tables, spans, order)
             for sid in scene_ids}
    skipped = {sid: p.skip for sid, p in plans.items() if p.skip and not p.broken}
    broken = {sid: p.skip for sid, p in plans.items() if p.broken}
    todo = [sid for sid, p in plans.items() if not p.skip]
    for sid in todo:
        for note in plans[sid].notes:
            log(f'  WARNING: {note}')
    os.makedirs(log_dir, exist_ok=True)

    def ask(sid: str, prompt: str, log_file: str) -> str:
        if os.path.exists(log_file):
            os.remove(log_file)   # never read an earlier run's reply as this one's
        response = invoke_to_file(prompt, model, log_file, 2048, system=system)
        usage = extract_usage(response)
        log_operation(project_dir, f'score-source-fidelity-{target}', model,
                      usage['input_tokens'], usage['output_tokens'],
                      calculate_cost_from_usage(usage, model), target=sid,
                      cache_read=usage.get('cache_read', 0),
                      cache_create=usage.get('cache_create', 0))
        problem = stop_problem(response)
        if problem:
            raise SourceFidelityError(f'{sid}: {problem}')
        return extract_text(response)

    def check(sid: str) -> Result:
        plan = plans[sid]
        log_file = os.path.join(log_dir, f'source-fidelity-{target}-{sid}.json')
        retry_file = os.path.join(log_dir, f'source-fidelity-{target}-{sid}-retry.json')
        if os.path.exists(retry_file):
            os.remove(retry_file)
        read = dict(scene_id=sid, target=target, hash_=plan.target_hash, rules=plan.rules)
        reply = ask(sid, plan.prompt, log_file)
        try:
            return parse_response(reply, **read)
        except SourceFidelityError as e:
            first = str(e).removeprefix(f'{sid}: ')
        # One re-ask, saying what was wrong; a second failure is the failure
        log(f'  {sid}: the reply could not be read ({first}); asking again once')
        reply = ask(sid, plan.prompt + RETRY_NOTE.format(problem=first, scene_id=sid,
                                                          reply=reply.strip()),
                    retry_file)
        try:
            return parse_response(reply, **read)
        except SourceFidelityError as e:
            raise SourceFidelityError(f'{e} (asked twice; the first reply: {first})') from e

    outcomes = run_parallel(todo, check, max_workers=parallel,
                            label=f'source fidelity ({target})')
    results: list[Result] = []
    failed: dict[str, str] = dict(broken)
    for sid in todo:
        out = outcomes.get(sid)
        if isinstance(out, Result):
            results.append(out)
        else:
            failed[sid] = str(out) if out is not None else 'not run (interrupted)'
    if results:
        write_results(results, out_dir)
        unconfirmed = unconfirmed_moves(results, {sid: plans[sid].rules for sid in todo})
        if unconfirmed:
            log(f'  WARNING: {len(unconfirmed)} moved departure(s) not confirmed by the '
                f'neighbour\'s result in this run (left as moved):')
            for line in unconfirmed:
                log(f'    {line}')
    return results, skipped, failed


def unconfirmed_moves(results: list[Result], rules: dict[str, ReplyRules]) -> list[str]:
    """Each `moved` departure whose authority says `to` a neighbour that
    has no result in `results`, or whose result has no `moved` departure
    naming this scene back (#617 review, SF-6). One line each; a check, not
    a reclassification."""
    by_id = {r.scene_id: r for r in results}
    out = []
    for r in results:
        for d in r.departures:
            if d['tag'] != 'moved' or not re.match(r'\s*to\b', d['authority'], re.I):
                continue
            nid = rules[r.scene_id].neighbour_named(d['authority'])
            other = by_id.get(nid)
            if other is None:
                why = 'it has no result in this run'
            elif any(o['tag'] == 'moved'
                     and rules[nid].neighbour_named(o['authority']) == r.scene_id
                     for o in other.departures):
                continue
            else:
                why = 'its result has no moved departure naming this scene'
            out.append(f'{r.scene_id} {d["element"]} to {nid}: {why}')
    return out


def report(results: list[Result], skipped: dict[str, str], failed: dict[str, str],
           target: str) -> None:
    """Log what the run found and what it couldn't check: the departures
    counted by tag, every drift, every staging departure on goal,
    key_actions or key_dialogue (where staging could hide a changed event),
    and every reply read under its source scene's id."""
    if results:
        avg = sum(r.overall for r in results) / len(results)
        drift = [r for r in results if r.count('drift')]
        counts = {tag: sum(r.count(tag) for r in results) for tag in TAGS}
        log(f'  Source fidelity ({target}): {len(results)} scenes, avg {avg:.1f}/5; '
            f'{counts["drift"]} drift in {len(drift)} scenes; not drift: '
            f'{counts["deliberate"]} deliberate, {counts["moved"]} moved, '
            f'{counts["staging"]} staging')
        for r in results:
            for d in r.departures:
                if d['tag'] == 'staging' and d['element'] in _STAGING_LISTED:
                    log(f'    staging {r.scene_id} {d["element"]}: {d["evidence"]}')
        for r in results:
            if r.remapped:
                log(f'    note: {r.scene_id}: the reply named its source scene '
                    f'{r.remapped} in place of {r.scene_id}; read as {r.scene_id}\'s')
        for r in drift:
            for d in r.departures:
                if d['tag'] == 'drift':
                    log(f'    drift {r.scene_id} {d["element"]}: {d["evidence"]}')
    if skipped:
        log(f'  Not checked ({len(skipped)}): '
            + '; '.join(f'{s} ({why})' for s, why in skipped.items()))
    for sid, why in failed.items():
        log(f'  WARNING: no source-fidelity result for {sid}: {why}')
