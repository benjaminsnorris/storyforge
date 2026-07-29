"""The visual-state transition log.

A row records the moment a tracked entity's visible state *changes*; the state
persists forward until the next transition for that entity. The state at any
scene is a forward walk over the log.

This exists because the illustration flow already had `reference/canon/` for
what must **never** change — a character's face, a lamp's construction — and
nowhere to put what changes *on schedule*: wardrobe by chapter, a lamp lit or
dark, how many village lights are still burning. Four of ten real findings on a
real book traced to that gap.

Sparse rather than a dense scene x entity grid because scene-map operations
insert, merge, split, and reorder — a transition keyed "from act2-sc01 onward"
still means something after a scene lands before it, where a dense grid would
have no row and fall silently blank. And one authorial decision ("from Chapter 4
they arrive dressed") is recorded once instead of restated in every illustrated
scene from 4 to 15, each restatement a cell that can go stale alone.

The trade sparse makes: a row can name a scene that has since been cut, which is
why `state_unknown_scene` is an error and not a warning.

Granularity is one track per independently-changing aspect, not one per entity:
`nora-clothing` rather than `nora`, because clothing and injury change on
different schedules and a single track would force restating one to change the
other. The convention is `{canon_id}-{aspect}` where an entity has several
tracks and a bare `canon_id` where it has one.

See benjaminsnorris/storyforge#278 and the spec at
docs/superpowers/specs/2026-07-28-illustration-state-matrix-and-packet-design.md.
"""

import csv
import os
import re
from typing import TYPE_CHECKING, TypedDict

from storyforge.common import log

if TYPE_CHECKING:  # pragma: no cover - typing only
    from storyforge.canon import AnchorLabel
    from storyforge.illustrations import IllustrationFinding

STATE_COLUMNS: list[str] = ['entity', 'from_scene', 'state', 'evidence']
STATE_FILENAME = 'visual-state.csv'
#: Project-relative, and the `file` every state finding carries: the fix is an
#: edit to the log even when the finding is *about* a scene.
STATE_FILE = os.path.join('reference', STATE_FILENAME)


class Transition(TypedDict):
    """One row of the log: an entity's visible state, from a scene onward."""
    entity: str
    from_scene: str
    state: str
    evidence: str


def parse_state_override(value: str) -> dict[str, str]:
    """Parse a plan row's `state_override` cell — `entity:state;entity:state`.

    An override is visual state true in *this image only*, which the transition
    log cannot express: tear-streaked faces and arms raised against a light are
    not schedule changes, and a pure log would have to write a change and then a
    change back, which is nonsense.

    Splits on the FIRST colon so a state may itself contain one. An entry with
    no colon names no entity and is skipped rather than guessed at.
    """
    out: dict[str, str] = {}
    for part in (value or '').split(';'):
        part = part.strip()
        if not part:
            continue
        if ':' not in part:
            log(f'WARNING: state_override entry {part!r} has no "entity:state" '
                f'colon — skipped')
            continue
        entity, _, state = part.partition(':')
        entity, state = entity.strip(), state.strip()
        if entity and state:
            out[entity] = state
        else:
            log(f'WARNING: state_override entry {part!r} has an empty entity or '
                f'state — skipped')
    return out


def state_path(project_dir: str) -> str:
    """Absolute path to the transition log, whether or not it exists."""
    return os.path.join(project_dir, STATE_FILE)


def read_transitions(project_dir: str) -> list[Transition]:
    """Every transition, in file order. An absent file is empty, not an error.

    A row with no `entity` names nothing and is skipped — with a log line,
    because a silently dropped row is a state the author believes is recorded.
    """
    from storyforge.illustrations import _read_ref_csv
    rows = _read_ref_csv(project_dir, STATE_FILENAME)
    out: list[Transition] = []
    for index, row in enumerate(rows, start=2):  # +1 header, +1 for 1-based
        entity = (row.get('entity') or '').strip()
        if not entity:
            log(f'WARNING: {STATE_FILE} line {index} has no entity — skipped')
            continue
        out.append({
            'entity': entity,
            'from_scene': (row.get('from_scene') or '').strip(),
            'state': (row.get('state') or '').strip(),
            'evidence': (row.get('evidence') or '').strip(),
        })
    return out


def state_at(project_dir: str, scene_id: str) -> dict[str, str]:
    """Entity -> state in effect at *scene_id*.

    A transition takes effect **at** its own scene, so the comparison is `<=`.
    An entity whose first transition is later than *scene_id* is absent from the
    result rather than present-and-blank — "not yet established" and
    "established as empty" are different, and callers report them differently.

    `_scene_order` prefers the chapter map and falls back to `scenes.csv:seq`,
    so a scene the chapter map omits has no position and resolves to `{}`. That
    is the right degradation — nothing is guessed — but it reads identically to
    "nothing is tracked yet", so it gets a log line.
    """
    from storyforge.illustrations import _scene_order
    order = _scene_order(project_dir)
    if scene_id not in order:
        log(f'WARNING: scene {scene_id!r} has no reading position — the chapter '
            f'map does not list it, and scenes.csv is only consulted when the '
            f'map is empty. Visual state resolves as empty, not as unchanged')
        return {}
    return _resolve(order, read_transitions(project_dir), order[scene_id])


def _resolve(
    order: dict[str, int],
    transitions: list[Transition],
    target: int,
) -> dict[str, str]:
    """The forward walk itself, over already-loaded order and transitions.

    Separate from `state_at` so the pre-pass can resolve many scenes without
    re-reading the chapter map and the log once per scene.
    """
    best: dict[str, tuple[int, str]] = {}
    for transition in transitions:
        pos = order.get(transition['from_scene'])
        if pos is None or pos > target:
            continue
        prior = best.get(transition['entity'])
        # `>=` rather than `>`: two transitions for one entity at the same scene
        # means the later row in the file wins, which is deterministic and
        # matches how the plan CSV resolves duplicates.
        if prior is None or pos >= prior[0]:
            best[transition['entity']] = (pos, transition['state'])
    return {entity: state for entity, (_pos, state) in sorted(best.items())}


def entities(project_dir: str) -> list[str]:
    """Every distinct tracked entity, sorted."""
    return sorted({t['entity'] for t in read_transitions(project_dir)})


def write_transitions(project_dir: str, rows: list[Transition]) -> str:
    """Write the log and return its path.

    `lineterminator` is explicit because `csv.writer` emits its own terminator
    and defaults to CRLF — which `cleanup` flags, and which turns every
    one-field edit into a whole-file diff. `newline=''` on the open does not
    prevent it.
    """
    path = state_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=STATE_COLUMNS, delimiter='|',
                                lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in STATE_COLUMNS})
    return path


# ============================================================================
# The deterministic pre-pass
# ============================================================================

class PrepassResult(TypedDict):
    """What the deterministic pass found, and what the LLM should read.

    `findings` are problems in the log itself and gaps between the log and the
    plan — all cheap, all certain. `candidate_scenes` is the narrowed set of
    scenes whose prose could disagree with the log; it exists so the audit's one
    LLM call reads a handful of scenes instead of the book.

    Everything after `candidate_scenes` is what the *caller* needs to report the
    narrowing honestly — how many scenes were selected out of how many exist,
    across how many entities, which positioned scenes had no prose to read, which
    drafted scenes the chapter map cannot position (so the audit never sees them
    at all), and the search terms each entity was matched by. They are returned
    rather than logged here because `validate_plan` also calls `prepass`, and
    neither `validate` nor `cleanup` is auditing anything: the caller knows
    whether to speak.
    """
    findings: list['IllustrationFinding']
    candidate_scenes: list[str]
    scene_count: int
    tracked_entities: list[str]
    undrafted_scenes: list[str]
    #: Drafted, active scenes with no reading position. Invisible to the
    #: narrowing — `_candidate_scenes` walks `_scene_order`, so a scene the
    #: chapter map omits holds prose nothing reads. Surfaced so a clean audit
    #: cannot silently exclude five scenes the author just drafted.
    unmapped_scenes: list[str]
    search_terms: dict[str, list[str]]


def _csv_safe(text: str) -> str:
    """Collapse *text* onto one line with no `|` before it enters a `detail`.

    Finding details land in the unquoted pipe-delimited
    `working/cleanup-report.csv`, and evidence and state cells are author prose.
    Delegates to the illustration module's helper so there is one such function.
    """
    from storyforge.illustrations import _csv_safe as flatten
    return flatten(text)


def _entity_search_terms(
    entity: str,
    display_names: dict[str, 'AnchorLabel'],
) -> set[str]:
    """Phrases whose presence in a scene means that scene talks about *entity*.

    An entity id is `{canon_id}-{aspect}` where it has several tracks and a bare
    `canon_id` where it has one, so the id alone ("nora-clothing") is rarely the
    phrase the prose uses. Resolution:

    1. the longest prefix of the id that names a canon file — the author said
       where the id ends — plus that entity's display name;
    2. otherwise the humanized id, whole.

    Shortening a multi-segment id is only safe when a canon file confirms where
    the id ends. Guessing that the last segment is the aspect looked harmless
    until you notice which entities are *state-only*: a lantern count or a lamp's
    lit/dark state is not a character, location, or motif with an invariant
    design, so it is systematically the kind of entity that has no canon file.
    `village-lights` — the spec's own example — would degenerate to `village`,
    and on a village-set book that makes nearly every scene a candidate, which
    can push one call past its context window. A missed candidate is a
    contradiction that ships; an unbounded candidate set is a call that cannot
    run at all, and the second failure is worse because it is not partial.
    """
    terms = {entity.replace('-', ' ')}
    parts = entity.split('-')

    canon_id = ''
    for count in range(len(parts), 0, -1):
        candidate = '-'.join(parts[:count])
        if candidate in display_names:
            canon_id = candidate
            break

    if canon_id:
        terms.add(canon_id.replace('-', ' '))
        terms.add(display_names[canon_id]['label'])

    return {' '.join(t.lower().split()) for t in terms if t.strip()}


def known_scene_ids(project_dir: str) -> set[str]:
    """Every scene a transition may legitimately name.

    A scene with a reading position, plus one that is active in `scenes.csv` but
    absent from the chapter map — the latter is a `state_unmapped_scene` warning,
    not a broken row. Anything outside this set produces `state_unknown_scene`.
    """
    from storyforge.common import check_chapter_map_freshness
    from storyforge import illustrations as ill
    _fresh, missing_from_map, _extra = check_chapter_map_freshness(project_dir)
    return set(ill._scene_order(project_dir)) | set(missing_from_map)


def _mentions(haystack: str, term: str) -> bool:
    """Whole-word match of *term* in already-normalized lowercase *haystack*."""
    return re.search(rf'(?<!\w){re.escape(term)}(?!\w)', haystack) is not None


def _scene_haystack(text: str) -> str:
    """Scene prose, marker-free, whitespace-collapsed, lowercased.

    Markers come out first: a marker is not prose, and `illus:great-lamp` would
    otherwise make every illustrated scene mention every entity it names.
    """
    from storyforge.illustrations import strip_markers
    return ' '.join(strip_markers(text).split()).lower()


def prepass(project_dir: str) -> PrepassResult:
    """Check the log deterministically, and narrow the prose the LLM reads.

    Four checks, none of which needs a model:

    1. a `from_scene` that names no scene at all — `state_unknown_scene`, an
       error, because the transition never applies and every scene after it
       resolves to the previous state. A `from_scene` that *does* exist in
       `scenes.csv` but is not in the chapter map is a different situation and a
       different finding: `state_unmapped_scene`, a warning, because the
       transition row is well-formed and the chapter map is what is incomplete.
       Conflating the two would push an author to delete good rows;
    2. an `evidence` quote no longer in that scene's prose —
       `evidence_not_found`, matched whitespace-tolerantly so a reflow does not
       read as drift;
    3. an illustration whose `canon_refs` names an entity with no resolved state
       at its scene — `state_unspecified`. An aspect track satisfies a bare
       canon id (`nora-clothing` covers `nora`), and a `state_override` on the
       row satisfies it too: a one-off state that does not persist is still a
       stated state;
    4. `candidate_scenes` — the scenes that mention a tracked entity at or after
       that entity's first transition, which is where prose and log can
       disagree.
    """
    from storyforge.common import check_chapter_map_freshness
    from storyforge import illustrations as ill

    transitions = read_transitions(project_dir)
    order = ill._scene_order(project_dir)
    findings: list['IllustrationFinding'] = []

    # The authority on "exists in scenes.csv but the chapter map omits it" — the
    # same function `assemble` and `evaluate` gate on, rather than a second
    # hand-rolled scenes.csv read that could disagree with it. It excludes
    # cut/merged/archived scenes from `active_ids`, which is exactly right here:
    # a transition keyed to a cut scene must stay an error.
    _fresh, missing_from_map, _extra = check_chapter_map_freshness(project_dir)
    unmapped = set(missing_from_map)

    # --- Checks 1 and 2: the log against the prose -------------------------
    # Positions of the transitions that actually resolve, per entity. Built
    # here so checks 3 and 4 do not re-walk the log.
    resolved: dict[str, set[int]] = {}
    for transition in transitions:
        entity = transition['entity']
        from_scene = transition['from_scene']
        position = order.get(from_scene)
        if position is None:
            if from_scene in unmapped:
                findings.append({
                    'kind': 'state_unmapped_scene',
                    'id': entity,
                    'scene_id': from_scene,
                    'file': os.path.join('reference', 'chapter-map.csv'),
                    'detail': f'transition for {entity!r} is keyed to '
                              f'{from_scene}, which exists in scenes.csv but is '
                              f'not in the chapter map — the row is fine, but '
                              f'the transition cannot be positioned until the '
                              f'map lists the scene',
                })
            else:
                findings.append({
                    'kind': 'state_unknown_scene',
                    'id': entity,
                    'file': STATE_FILE,
                    'detail': f'transition for {entity!r} is keyed to '
                              f'{from_scene!r}, which is not an active scene in '
                              f'scenes.csv — cut, renamed, or mistyped. The '
                              f'transition never applies, so every scene after '
                              f'it resolves to the previous state',
                })
            continue
        resolved.setdefault(entity, set()).add(position)

        if not transition['evidence']:
            continue
        text = ill._read_scene(project_dir, from_scene)
        if text is None:
            # Undrafted is valid in-flight state, not a finding — the same
            # posture as an unrendered illustration. Say so rather than
            # reporting the evidence as missing from prose that does not exist.
            log(f'  visual-state: {from_scene} has no file in scenes/ — cannot '
                f'check the evidence for {entity!r} yet')
            continue
        if ill.find_anchor(ill.strip_markers(text), transition['evidence']) is None:
            findings.append({
                'kind': 'evidence_not_found',
                'id': entity,
                'scene_id': from_scene,
                'file': STATE_FILE,
                'detail': f'evidence for {entity!r} — '
                          f'"{_csv_safe(transition["evidence"])}" — no longer '
                          f'appears in {from_scene}. Either the prose was '
                          f'revised or the transition belongs in another scene',
            })

    # --- Check 3: illustrations naming state nobody stated -----------------
    for row in ill.read_plan(project_dir):
        if (row.get('status') or '').strip() == 'superseded':
            continue
        refs = ill._split_array(row.get('canon_refs', ''))
        if not refs:
            continue
        rid = (row.get('id') or '').strip()
        scene_id = (row.get('scene_id') or '').strip()
        if scene_id not in order:
            # validate_plan already reports a missing or unknown scene_id;
            # emitting a second finding for the same cell would double-count.
            log(f'  visual-state: illustration {rid!r} has no resolvable '
                f'scene_id ({scene_id!r}) — its entity states were not checked')
            continue

        covered = {key.lower()
                   for key in _resolve(order, transitions, order[scene_id])}
        covered |= {key.lower()
                    for key in parse_state_override(row.get('state_override', ''))}
        for ref in refs:
            needle = ref.lower()
            if any(key == needle or key.startswith(f'{needle}-')
                   for key in covered):
                continue
            findings.append({
                'kind': 'state_unspecified',
                'id': rid,
                'scene_id': scene_id,
                'file': STATE_FILE,
                'detail': f'illustration {rid!r} in {scene_id} shows '
                          f'{_csv_safe(ref)}, but no transition states its '
                          f'visible state at that point. Add a row to '
                          f'{STATE_FILE}, or set state_override on the plan row '
                          f'if the state is true in this image only',
            })

    candidates, undrafted, terms = _candidate_scenes(project_dir, order,
                                                     resolved)
    # Drafted and active, but with no reading position — so the narrowing, which
    # walks `order`, never looks at it. Its prose is neither read nor reported as
    # unread unless this is surfaced.
    unmapped = sorted(sid for sid in missing_from_map
                      if ill._read_scene(project_dir, sid) is not None)
    return {
        'findings': findings,
        'candidate_scenes': candidates,
        'scene_count': len(order),
        'tracked_entities': sorted(resolved),
        'undrafted_scenes': undrafted,
        'unmapped_scenes': unmapped,
        'search_terms': {entity: sorted(values)
                         for entity, values in terms.items()},
    }


def _candidate_scenes(
    project_dir: str,
    order: dict[str, int],
    resolved: dict[str, set[int]],
) -> tuple[list[str], list[str], dict[str, set[str]]]:
    """Scenes whose prose could contradict the log, and scenes with no prose.

    A scene qualifies when it mentions a tracked entity and sits at or after
    that entity's first resolved transition — the span over which the log
    asserts something about that entity. A scene that *is* one of the entity's
    transitions is skipped for it: the evidence quote already pins that scene,
    and check 2 verifies it.

    Returns `(candidates, undrafted, terms_by_entity)`; the first two in reading
    order. Silent by design — the caller reports the narrowing, because `prepass`
    is also called from `validate_plan` and neither `validate` nor `cleanup` is
    auditing anything. The term sets come back so the caller can log *why* a
    narrowing was wide or empty, which is otherwise undiagnosable.
    """
    from storyforge import illustrations as ill

    if not resolved:
        return [], [], {}

    display_names = _display_names(project_dir)
    terms = {entity: _entity_search_terms(entity, display_names)
             for entity in resolved}
    first = {entity: min(positions) for entity, positions in resolved.items()}

    candidates: list[str] = []
    undrafted: list[str] = []
    for scene_id, position in sorted(order.items(), key=lambda kv: (kv[1], kv[0])):
        text = ill._read_scene(project_dir, scene_id)
        if text is None:
            undrafted.append(scene_id)
            continue
        haystack = _scene_haystack(text)
        for entity, entity_terms in terms.items():
            if position < first[entity] or position in resolved[entity]:
                continue
            if any(_mentions(haystack, term) for term in entity_terms):
                candidates.append(scene_id)
                break

    return candidates, undrafted, terms


def _display_names(project_dir: str) -> dict[str, 'AnchorLabel']:
    """Canon display names, or {} when the project has no canon tier yet."""
    from storyforge import canon
    return canon.anchor_display_names(project_dir)


# ============================================================================
# Digest drift — the audit's provenance, and prose revised under a render
# ============================================================================

PROVENANCE_COLUMNS: list[str] = ['scene_id', 'digest', 'audited_at']
PROVENANCE_FILE = os.path.join('working', 'illustration-audit-provenance.csv')


class Provenance(TypedDict):
    """One scene the audit read, and the prose it read."""
    scene_id: str
    digest: str
    audited_at: str


def provenance_path(project_dir: str) -> str:
    return os.path.join(project_dir, PROVENANCE_FILE)


def read_provenance(project_dir: str) -> list[Provenance]:
    """Every provenance row, in file order. Absent file is empty, not an error."""
    path = provenance_path(project_dir)
    if not os.path.isfile(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    reader = csv.DictReader(raw.splitlines(), delimiter='|')
    out: list[Provenance] = []
    for index, row in enumerate(reader, start=2):
        scene_id = (row.get('scene_id') or '').strip()
        if not scene_id:
            log(f'WARNING: {PROVENANCE_FILE} line {index} has no scene_id — '
                f'skipped')
            continue
        out.append({
            'scene_id': scene_id,
            'digest': (row.get('digest') or '').strip(),
            'audited_at': (row.get('audited_at') or '').strip(),
        })
    return out


def write_provenance(project_dir: str, rows: list[Provenance]) -> str:
    """Write the provenance file. `lineterminator` explicit, as everywhere."""
    path = provenance_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=PROVENANCE_COLUMNS, delimiter='|',
                                lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in PROVENANCE_COLUMNS})
    return path


def digest_drift(project_dir: str) -> list['IllustrationFinding']:
    """Scenes whose prose moved since something recorded a digest of it.

    Two independent records, two findings:

    - `audit_stale` — the audit read this scene's prose and recorded its digest;
      the prose has since changed, so the contradiction pass no longer covers it.
    - `prose_changed` — an illustration was ingested against this scene's prose;
      the prose has since changed, so the art may no longer match what it
      accompanies. The row is not wrong, but nothing else in the pipeline would
      notice.

    Both compare `illustrations.prose_digest`, which is marker-free and
    whitespace-normalized, so embedding a marker or reflowing a paragraph does
    not read as a revision.
    """
    from storyforge import illustrations as ill

    findings: list['IllustrationFinding'] = []

    for record in read_provenance(project_dir):
        scene_id = record['scene_id']
        current = ill.scene_prose_digest(project_dir, scene_id)
        if not current:
            log(f'WARNING: {PROVENANCE_FILE} names {scene_id}, which has no '
                f'file in scenes/ — staleness for it cannot be determined')
            continue
        if record['digest'] and current != record['digest']:
            findings.append({
                'kind': 'audit_stale',
                'id': scene_id,
                'scene_id': scene_id,
                'file': PROVENANCE_FILE,
                'detail': f'{scene_id} was revised since the last '
                          f'contradiction audit '
                          f'({record["audited_at"] or "date not recorded"}) — '
                          f'the audit no longer covers its prose',
            })

    for row in ill.read_plan(project_dir):
        if (row.get('status') or '').strip() != 'ingested':
            continue
        recorded = (row.get('scene_digest') or '').strip()
        if not recorded:
            continue
        scene_id = (row.get('scene_id') or '').strip()
        current = ill.scene_prose_digest(project_dir, scene_id)
        if not current or current == recorded:
            continue
        findings.append({
            'kind': 'prose_changed',
            'id': (row.get('id') or '').strip(),
            'scene_id': scene_id,
            'file': os.path.join('reference', ill.PLAN_FILENAME),
            'detail': f'{scene_id} was revised after '
                      f'{(row.get("id") or "").strip()!r} was rendered from it '
                      f'— confirm the art still matches the prose it '
                      f'accompanies',
        })

    return findings
