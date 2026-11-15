"""Long writing sessions: one writer drafts a stretch of the book in one
conversation (#655; plan `2026-11-08-deterministic-gate-and-voiceprint.md`
Part C, and `2026-11-14-ready-to-draft.md`).

Drafting scene by scene, each from its own brief in a separate call,
averages the voice and makes every scene a closed unit. A session keeps one
writer for a whole stretch:

- **The writer's context** (`system_blocks`, cached): how to work, the
  voice (`voice_book.resolve`: the author repo, book.md and the anchors;
  never checks.md), the key decisions, the series canon and name map, and
  the cast and places as rows. Then, as the first message, the story so far
  word for word (`story_so_far`), as much as the window allows.
- **Each scene** is one turn: a lean plan (`scene_plan`: POV, tense, when
  and where, the closest anchor, the events, the outcome, the knowledge and
  physical state out, the source passage for an adaptation, the stage as
  the last scene left it). No motifs, no scripted dialogue, no subtext; the
  author's notes only when `drafting.brief_notes` isn't `exclude` (briefs
  written before #644 hold model-written notes, which Wrath leaves out).
- **The writer replies** with the scene, then the stage at its end
  (`STAGE_OPEN`): a list of stage-sheet entries (`stage_sheet.Entry`),
  kept apart from the prose and saved as the scene's writer sheet.
- **After each scene**, in order:
  1. the free tense check (`voice_book.check_tense`): a mismatch goes back
     to the writer once, for the whole scene again;
  2. the voice review (`voice_review`): a reviewer flags lines against
     checks.md, a separate reviser rewrites only those;
  3. the gate (`cmd_write._gate_drafted_scene`), with this session's writer
     as its fixer (`Session.fixer`): hard findings go back to the writer as
     short notes and come back as edits, under every rule of
     `gate.gate_and_fix`;
  4. the writer's sheet against the extracted one, when the gate kept one
     (`compare_sheets`); a mismatch is reported;
  5. the commit, as `write` makes it.
  The conversation then keeps the scene as it was committed (`settle`):
  the next turn reads the final text, not the draft.
- A cut-off session resumes by running it again: drafted scenes are skipped
  and become the story so far.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from storyforge import voice_book
from storyforge.common import log

#: where a session's logs go, under working/logs/
LOG_SUBDIR = 'session'
#: what a session commits besides the scene: its logs (git path form)
LOG_DIR_FOR_COMMIT = f'working/logs/{LOG_SUBDIR}/'
#: the writer's answer budget per scene, in tokens (a scene of 5,000 words
#: is about 7,000)
SCENE_TOKENS = 16000
#: the share of the model's context window the story so far may take
STORY_SHARE = 0.55
#: rough tokens per word of English prose
TOKENS_PER_WORD = 1.35
#: what separates the scene from the writer's stage note in a reply
STAGE_OPEN = '<stage>'
STAGE_CLOSE = '</stage>'
SCENE_OPEN = '<scene>'
SCENE_CLOSE = '</scene>'
#: the brief fields a session's plan shows, as facts
FACT_FIELDS = ('key_actions', 'outcome', 'knowledge_out', 'physical_state_out')


class SessionError(RuntimeError):
    """The session can't go on: a reply that isn't a scene, a refusal, an
    API failure. The message says which scene and why."""


# ============================================================================
# What the writer is told
# ============================================================================

INSTRUCTIONS = """You are writing a novel, {title}, one scene after another, in one long sitting. You hold the whole of it: the voice, the story so far, and each scene's plan as it comes.

How to work:
- The voice is the passages below and the notes on what they do. Write toward the passages. When a scene is like one of them (its kind, its point of view, its tense), the plan names the closest; read it again before you start.
- Each plan says what happens, not how. Its wording is notes for you: never copy it into the prose, and never tell the reader what the plan says a moment means. Events, who is there, what is true at the end: those must hold. How they happen is yours.
- The story so far is the book as it stands. Carry everything forward from it: where people are, what they hold and wear, what they know, what has been said.
- Stay in the scene's point of view, at the distance and in the tense the plan and the voice give.

Reply to each plan with the scene, then the stage at its end, in exactly this form:

{scene_open}
(the scene's prose, and nothing else: no title, no notes)
{scene_close}
{stage_open}
(a JSON list of the stage at the scene's very end, one object per fact: {{"who": "<name>", "field": "<field>", "item": "<thing, for worn, light or door>", "value": "<value>", "quote": "<the scene's words that set it, or empty>"}}. Fields: posture (standing, sitting, kneeling, lying, crouching, mounted, down), hand_left and hand_right (what the hand holds, or empty), worn (on or off, with the item), present (here or gone), position, facing. Only what the scene shows.)
{stage_close}

Some turns are notes on a scene you wrote: a check found something wrong. Answer them exactly as the note asks."""


def _rows(path: str, columns: tuple[str, ...]) -> list[dict[str, str]]:
    from storyforge.elaborate import _read_csv
    if not os.path.isfile(path):
        return []
    return [{c: (r.get(c) or '').strip() for c in columns} for r in _read_csv(path)]


def cast_block(project_dir: str) -> str:
    """The characters and places as rows (names, aliases, pronouns, role),
    for the writer's context: facts, never the bibles' essays (#657)."""
    ref = os.path.join(project_dir, 'reference')
    people = _rows(os.path.join(ref, 'characters.csv'), ('name', 'aliases', 'role', 'pronouns'))
    places = _rows(os.path.join(ref, 'locations.csv'), ('name', 'aliases'))
    lines = []
    if people:
        lines.append('## The cast')
        for p in people:
            extra = '; '.join(filter(None, [
                f'also {p["aliases"].replace(";", ", ")}' if p['aliases'] else '',
                p['pronouns'], p['role']]))
            lines.append(f'- {p["name"]}' + (f' ({extra})' if extra else ''))
    if places:
        lines.append('\n## Places')
        for p in places:
            lines.append(f'- {p["name"]}'
                         + (f' (also {p["aliases"].replace(";", ", ")})' if p['aliases'] else ''))
    return '\n'.join(lines)


def system_blocks(project_dir: str) -> list[dict]:
    """The writer's standing context, one cached prefix: the instructions,
    the voice, the key decisions, the canon, and the cast and places.

    Raises:
        SessionError: the book has no voice to write toward.
        common.ReferenceDocError: a voice or reference file can't be read.
        series.SeriesError: the canon can't be read.
    """
    from storyforge.common import read_yaml_field
    from storyforge.prompts import key_decisions_block
    from storyforge.prompts_elaborate import reference_doc
    from storyforge.series import canon_text
    voice = voice_book.resolve(project_dir)
    voice.raise_if_unreadable(project_dir)
    if voice.kind != 'ok':
        raise SessionError(f'{voice.detail}: a session writes toward the voice\'s passages and '
                           f'there are none. First {voice_book.REMEDY}')
    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    parts = [INSTRUCTIONS.format(title=title, scene_open=SCENE_OPEN, scene_close=SCENE_CLOSE,
                                 stage_open=STAGE_OPEN, stage_close=STAGE_CLOSE),
             voice.text]
    decisions = key_decisions_block(reference_doc(project_dir, 'key-decisions.md'))
    if decisions:
        parts.append(decisions)
    parts += [f'## {label}\n\n{text}' for label, text in canon_text(project_dir)]
    cast = cast_block(project_dir)
    if cast:
        parts.append(cast)
    blocks = [{'type': 'text', 'text': p} for p in parts]
    blocks[-1]['cache_control'] = {'type': 'ephemeral'}
    return blocks


def story_cap_words(model: str) -> int:
    """How many words of the story so far a session sends."""
    from storyforge.api import max_input_tokens
    return int(max_input_tokens(model) * STORY_SHARE / TOKENS_PER_WORD)


def story_so_far(project_dir: str, first_scene: str, cap_words: int) -> tuple[str, list[str]]:
    """The book before `first_scene`, word for word, as the session's first
    message: every earlier scene with prose, in reading order. Past
    `cap_words`, the latest scenes that fit are sent whole and the earlier
    ones by their summaries. Returns (the text, notes for the log)."""
    from storyforge import ledger
    from storyforge.elaborate import get_scenes
    from storyforge.prompts import _has_prose, _scene_prose
    order = ledger.scene_order(project_dir)
    rows = {r['id']: r for r in get_scenes(os.path.join(project_dir, 'reference'))}
    if first_scene not in order:
        return '', []
    earlier = [s for s in sorted(order, key=order.get)
               if order[s] < order[first_scene] and _has_prose(project_dir, s)]
    if not earlier:
        return '', ['the story so far is empty: this is the first scene with prose']
    texts = {s: _scene_prose(project_dir, s) for s in earlier}
    whole, words = [], 0
    for s in reversed(earlier):
        n = len(texts[s].split())
        if words + n > cap_words and whole:
            break
        whole.insert(0, s)
        words += n
    summarized = [s for s in earlier if s not in whole]
    parts = ['# The story so far']
    notes = [f'the story so far: {len(whole)} scene(s), {words:,} words, word for word']
    if summarized:
        parts.append('## Before that, in summary')
        parts += [f'- {(rows.get(s) or {}).get("title") or s}: '
                  f'{(rows.get(s) or {}).get("summary") or "(no summary)"}' for s in summarized]
        notes.append(f'{len(summarized)} earlier scene(s) sent as summaries only (over '
                     f'{cap_words:,} words): {", ".join(summarized[:5])}'
                     + (' ...' if len(summarized) > 5 else ''))
    for s in whole:
        title = (rows.get(s) or {}).get('title') or s
        parts.append(f'## {title}\n\n{texts[s].strip()}')
    return '\n\n'.join(parts), notes


# ============================================================================
# The plan for one scene
# ============================================================================

def _statements(project_dir: str, ids: str, type_: str) -> list[str]:
    """Ledger statements for a `;` list of fact ids (the id itself when the
    ledger has none)."""
    from storyforge import ledger
    if not ids.strip():
        return []
    view = ledger.view_map(os.path.join(project_dir, 'reference'), type_)
    key = 'name' if type_ == 'knowledge' else 'description'
    out = []
    for i in (x.strip() for x in ids.split(';') if x.strip()):
        row = view.get(i) or {}
        text = row.get(key) or i
        who = row.get('character', '') if type_ == 'physical' else ''
        out.append(f'{who}: {text}' if who else text)
    return out


def closest_anchor(anchors, scene: dict[str, str]) -> str:
    """The anchor most like the scene, by POV then tense ('' when none
    shares either)."""
    pov = (scene.get('pov') or '').strip().lower()
    tense = (scene.get('tense') or '').strip().lower()
    best, score = '', 0
    for a in anchors:
        s = 2 * bool(pov and a.pov.lower() == pov) + bool(tense and a.tense == tense)
        if s > score:
            best, score = a.name, s
    return best


def brief_notes_wanted(project_dir: str) -> bool:
    """Whether the plan shows the author's note columns (goal, conflict,
    key_dialogue, ...): `drafting.brief_notes` in storyforge.yaml, `include`
    (the default) or `exclude` (briefs written before #644, whose notes a
    model wrote)."""
    from storyforge.common import read_yaml_field
    value = (read_yaml_field('drafting.brief_notes', project_dir) or 'include').strip().lower()
    if value not in ('include', 'exclude'):
        raise SessionError(f'storyforge.yaml: drafting.brief_notes is {value!r}; it takes '
                           f'include or exclude')
    return value == 'include'


def scene_plan(project_dir: str, scene_id: str, *, notes: bool, anchors=(),
               carried: str = '') -> str:
    """The plan the writer gets for one scene."""
    from storyforge.elaborate import AUTHOR_NOTE_COLUMNS, get_scene
    from storyforge.prompts import scene_when
    from storyforge.prompts_source import drafting_section
    ref = os.path.join(project_dir, 'reference')
    scene = get_scene(scene_id, ref)
    if not scene:
        raise SessionError(f'{scene_id} is not in scenes.csv')
    title = scene.get('title') or scene_id
    lines = [f'# Next: {title} ({scene_id})', '']

    def add(label, value):
        if value and value.strip():
            lines.append(f'- **{label}:** {value.strip()}')
    add('Point of view', scene.get('pov'))
    tense = (scene.get('tense') or '').strip().lower()
    add('Tense', tense if tense in voice_book.TENSES else '')
    add('When', scene_when(scene))
    add('Where', scene.get('location'))
    add('On stage', (scene.get('on_stage') or '').replace(';', ', '))
    add('Length', f'about {scene["target_words"]} words' if (scene.get('target_words') or '')
        .strip().isdigit() else '')
    anchor = closest_anchor(anchors, scene)
    add('Closest anchor', anchor)
    events = [e.strip() for e in (scene.get('key_actions') or '').split(';') if e.strip()]
    if events:
        lines += ['', '## What happens'] + [f'{n}. {e}' for n, e in enumerate(events, 1)]
    if (scene.get('outcome') or '').strip():
        lines += ['', f'## How it ends\n\n{scene["outcome"].strip()}']
    know = _statements(project_dir, scene.get('knowledge_out') or '', 'knowledge')
    if know:
        lines += ['', '## Known by the end'] + [f'- {k}' for k in know]
    state = _statements(project_dir, scene.get('physical_state_out') or '', 'physical')
    if state:
        lines += ['', '## True by the end'] + [f'- {k}' for k in state]
    if notes:
        kept = [(c, scene.get(c, '').strip()) for c in AUTHOR_NOTE_COLUMNS
                if (scene.get(c) or '').strip()]
        if kept:
            lines += ['', '## The author\'s notes (notes, not requirements)']
            lines += [f'- {c}: {v}' for c, v in kept]
    from storyforge.speaker_labels import LABEL_READING, has_label
    shown = ['key_actions', 'outcome'] + (list(AUTHOR_NOTE_COLUMNS) if notes else [])
    if any(has_label(scene.get(c, '')) for c in shown):
        lines += ['', LABEL_READING]   # what a speaker label means (#513)
    source = drafting_section(project_dir, scene_id)
    if source:
        lines += ['', source]
    if carried:
        lines += ['', '## The stage as the last scene left it', carried]
    return '\n'.join(lines)


# ============================================================================
# The reply
# ============================================================================

@dataclass
class Draft:
    """A scene the writer wrote: its prose, the stage at its end as the
    writer gave it (entry dicts), and why the stage note couldn't be used
    ('' when it could)."""
    prose: str
    stage: list[dict] = field(default_factory=list)
    stage_problem: str = ''


def parse_reply(text: str, scene_id: str) -> Draft:
    """The scene and the stage note from a reply.

    Raises:
        SessionError: no scene in the reply.
    """
    m = re.search(re.escape(SCENE_OPEN) + r'\s*(.*?)\s*' + re.escape(SCENE_CLOSE), text, re.S)
    if not m or not m.group(1).strip():
        raise SessionError(f'{scene_id}: the writer\'s reply has no {SCENE_OPEN} ... '
                           f'{SCENE_CLOSE} block')
    draft = Draft(m.group(1).strip() + '\n')
    s = re.search(re.escape(STAGE_OPEN) + r'\s*(.*?)\s*' + re.escape(STAGE_CLOSE), text, re.S)
    if not s:
        draft.stage_problem = 'the reply has no stage note'
        return draft
    raw = s.group(1).strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
    try:
        items = json.loads(raw or '[]')
        if not isinstance(items, list):
            raise ValueError('not a list')
    except ValueError as e:
        draft.stage_problem = f'the stage note is not a JSON list ({e})'
        return draft
    from storyforge.stage_sheet import Entry
    for item in items:
        try:
            draft.stage.append(Entry.from_json(item, 'the writer\'s stage note').to_json())
        except ValueError as e:
            draft.stage_problem = (draft.stage_problem + '; ' if draft.stage_problem
                                   else '') + str(e)
    return draft


# ============================================================================
# The writer's stage sheet
# ============================================================================

def save_writer_sheet(project_dir: str, scene_id: str, prose: str, stage: list[dict],
                      model: str) -> str:
    """Save the writer's stage note as the scene's writer sheet
    (`stage_sheet.sheet_path(..., 'writer')`); its `end` is the note."""
    from storyforge import stage_sheet
    sheet = {'format': stage_sheet.FORMAT, 'scene_id': scene_id, 'source': 'writer',
             'model': model, 'prose_sha256': stage_sheet.prose_hash(prose), 'cast': [],
             'opening': [], 'beats': [], 'end': stage}
    return stage_sheet.write_sheet(project_dir, sheet)


def carried_text(stage: list[dict]) -> str:
    """The writer's last stage note, as lines for the next plan."""
    from storyforge.stage_sheet import Entry, render
    try:
        return render([Entry.from_json(e) for e in stage])
    except ValueError:
        return ''


def compare_sheets(project_dir: str, scene_id: str, prose: str) -> tuple[list[str], str]:
    """Where the writer's sheet and the extracted one disagree about the
    scene's end: (mismatches, a note when they can't be compared). A
    mismatch means the prose or the writer's note is wrong."""
    from storyforge import stage_sheet
    paths = {src: stage_sheet.sheet_path(project_dir, scene_id, src)
             for src in ('writer', 'extracted')}
    if not os.path.isfile(paths['extracted']):
        return [], ('the writer\'s stage note was not compared: no extracted stage sheet '
                    '(the gate read the blocking whole; `--stage-sheet` keeps one)')
    if not os.path.isfile(paths['writer']):
        return [], 'the writer\'s stage note was not compared: the writer gave none'
    try:
        sheets = {src: stage_sheet.load_sheet(p) for src, p in paths.items()}
    except (OSError, ValueError) as e:
        return [], f'the writer\'s stage note was not compared: {e}'
    digest = stage_sheet.prose_hash(prose)
    stale = [src for src, sh in sheets.items() if sh.get('prose_sha256') != digest]
    if stale:
        return [], (f'the writer\'s stage note was not compared: the {" and ".join(stale)} '
                    f'sheet is of other prose')
    try:
        ends = {src: {e.key(): e for e in stage_sheet._entries(sh.get('end', []), f'{src} end')}
                for src, sh in sheets.items()}
    except ValueError as e:
        return [], f'the writer\'s stage note was not compared: {e}'
    out = []
    for key, w in sorted(ends['writer'].items()):
        x = ends['extracted'].get(key)
        if x is not None and x.value.lower() != w.value.lower():
            who = f'{w.who} ' if w.who else ''
            item = f' {w.item}' if w.item else ''
            out.append(f'{who}{w.field}{item}: the writer says "{w.value}", the prose says '
                       f'"{x.value}"' + (f' ("{x.quote}")' if x.quote else ''))
    return out, ''


# ============================================================================
# The conversation
# ============================================================================

class Session:
    """One writer's conversation. `messages` holds the story so far, then
    each settled scene as [plan, the scene as committed]."""

    def __init__(self, project_dir: str, model: str, system: list[dict], story: str,
                 log_dir: str):
        self.project_dir = project_dir
        self.model = model
        self.system = system
        self.log_dir = log_dir
        self.messages: list[dict] = []
        if story:
            self.messages += [
                {'role': 'user', 'content': story},
                {'role': 'assistant', 'content': 'I have the story so far. Send the first plan.'}]
        self._settled = len(self.messages)
        self._turn = 0
        self.scene_id = ''

    def _ask(self, content: str, label: str, tokens: int,
             output_schema: dict | None = None) -> dict:
        from storyforge.api import RefusalError, chat, is_truncated
        self._turn += 1
        log_file = os.path.join(self.log_dir, f'{self._turn:03d}-{label}.json')
        self.messages.append({'role': 'user', 'content': content})
        try:
            response = chat(self.messages, self.model, tokens, label=label, system=self.system,
                            output_schema=output_schema, log_file=log_file)
        except RefusalError as e:
            self.messages.pop()
            raise SessionError(f'{label}: the writer refused ({e})') from e
        except RuntimeError as e:
            self.messages.pop()
            raise SessionError(f'{label}: the request failed ({e})') from e
        if is_truncated(response):
            self.messages.pop()
            raise SessionError(f'{label}: the reply hit its token limit ({log_file})')
        from storyforge.api import extract_text
        self.messages.append({'role': 'assistant', 'content': extract_text(response)})
        return response

    def write(self, scene_id: str, plan: str) -> Draft:
        """Write the next scene from its plan."""
        from storyforge.api import extract_text
        self.scene_id = scene_id
        response = self._ask(plan, f'write-{scene_id}', SCENE_TOKENS)
        return parse_reply(extract_text(response), scene_id)

    def rewrite(self, scene_id: str, note: str) -> Draft:
        """The whole scene again, after a note (the tense check)."""
        from storyforge.api import extract_text
        content = (f'A note on {scene_id}: {note}\n\nWrite the whole scene again with that '
                   f'fixed and nothing else changed, in the same form '
                   f'({SCENE_OPEN} ... {STAGE_CLOSE}).')
        response = self._ask(content, f'rewrite-{scene_id}', SCENE_TOKENS)
        return parse_reply(extract_text(response), scene_id)

    def tell(self, note: str) -> None:
        """A note the writer should know but needn't answer (the reviser's
        edits): kept as a pair, so turns still alternate."""
        self.messages += [{'role': 'user', 'content': note},
                          {'role': 'assistant', 'content': 'Noted.'}]

    def fixer(self, scene_id, prose, result, *, log_dir='', model=None, protected=(),
              earlier=(), edits_out=None):
        """`gate.gate_and_fix`'s fixer: the gate's problems go to this
        writer, which answers with edits (`gate.FIX_SCHEMA`), applied by
        `gate.apply_edits`. Same contract as `gate.fix_scene`."""
        from storyforge import gate
        from storyforge.api import extract_text
        problems = gate.problems_to_fix(result)
        if not problems:
            return prose
        prompt = gate.build_fix_prompt(scene_id, prose, problems, protected, earlier)
        prompt = ('A continuity check read the scene you just wrote. ' + prompt.split('\n', 1)[1]
                  if '\n' in prompt else prompt)
        try:
            response = self._ask(prompt, f'fix-{scene_id}', 8000, output_schema=gate.FIX_SCHEMA)
            edits = json.loads(extract_text(response))['edits']
        except SessionError as e:
            raise gate.GateError(f'{scene_id}: the writer\'s fix failed: {e}') from e
        except (ValueError, KeyError, TypeError) as e:
            raise gate.GateError(f'{scene_id}: the writer\'s fix could not be read: {e}') from e
        fixed = gate.apply_edits(prose, edits)
        if edits_out is not None:
            edits_out.extend(edits)
        return fixed

    def settle(self, plan: str, prose: str, stage: list[dict]) -> None:
        """Keep the scene in the conversation as it was committed: [the
        plan, the final prose and stage], in place of the turns it took."""
        stage_json = json.dumps(stage, ensure_ascii=False)
        self.messages = self.messages[:self._settled] + [
            {'role': 'user', 'content': plan},
            {'role': 'assistant', 'content': f'{SCENE_OPEN}\n{prose.strip()}\n{SCENE_CLOSE}\n'
                                             f'{STAGE_OPEN}\n{stage_json}\n{STAGE_CLOSE}'}]
        self._settled = len(self.messages)


# ============================================================================
# The forecast
# ============================================================================

def forecast(project_dir: str, scene_ids: list[str], model: str, avg_words: int,
             story_words: int, system_tokens: int, review: bool) -> tuple[float, float, str]:
    """What a session over `scene_ids` should cost: the writer's turns (the
    standing context and the story so far read from cache, each scene
    written once, about one fix turn in three), the voice review and the
    gate. Returns (the writer and review in dollars, the gate in dollars,
    the basis, for the log)."""
    from storyforge import gate
    from storyforge.costs import calculate_cost
    scene_tokens = int(avg_words * TOKENS_PER_WORD)
    total, story = 0.0, int(story_words * TOKENS_PER_WORD)
    for _ in scene_ids:
        plan = 600
        total += calculate_cost(model, plan, scene_tokens + 400 + 2000,
                                cache_read=system_tokens + story)
        total += calculate_cost(model, 1500, 800, cache_read=system_tokens + story) / 3
        story += scene_tokens + plan
    review_cost = 0.0
    if review:
        per = (calculate_cost(model, system_tokens + scene_tokens + 1500, 1200)
               + calculate_cost(model, system_tokens + scene_tokens + 800, 1500))
        review_cost = per * len(scene_ids)
    gate_cost = gate.WRITE_GATE_COST_PER_SCENE * len(scene_ids)
    basis = (f'writer ~${total:.2f}, voice review ~${review_cost:.2f}, gate '
             f'~${gate_cost:.2f}; {len(scene_ids)} scene(s) of ~{avg_words:,} words after '
             f'~{story_words:,} words of story so far')
    return total + review_cost, gate_cost, basis
