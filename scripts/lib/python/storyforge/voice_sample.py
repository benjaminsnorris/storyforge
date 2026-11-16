"""Finding a book's voice by blind sample rounds (#654; plan B5, and finding
7 of the ready-to-draft plan's "What the voice rounds showed", from *Wrath
Like Smoke*'s rounds).

One scene (or, before the scene map, a moment in the author's words) is
written several ways; the author marks sentences in a pull
request; the next round writes toward what was kept; the winner, ideally
finished by the author's hand, becomes an anchor (`reference/voice/anchors/`).
How the rounds worked on Wrath, and so how this runs:

- **One sentence per line** (`one_per_line`), so a comment attaches to a
  sentence. Paragraphs are kept with blank lines.
- **Unlabelled.** Samples are `Sample A`, `Sample B`... in a shuffled
  order; the key (what each tried) is kept outside the repo (`key_path`,
  under `~/.storyforge/voice-sample-keys/`, by the book folder's path), and
  given to the next round's writer. It isn't shown to the author by any
  command: they mark blind.
- **The rounds are PRs**, one per round. A later round (`--from-pr N`)
  reads the round file as it is at the PR's head, and every page of the
  PR author's comments (`pr_marks`): line comments checked against the
  line's text and mapped to the sample and sentence they mark (a comment on
  a sample's heading is a reaction to the whole sample), `suggestion`
  blocks as the author's own wording (an empty one cuts the line), and
  general reactions made since the round was committed.
- **Write toward the keeps**, not away from the cuts: round 3 obeyed every
  flagged problem and came out flat. The prompt says so.
- **Takes.** `--take <label>` revises one sample of the marked round toward
  its marks, in versions that differ in one named thing (`--versions
  "present tense;past tense"`); the versions are headed by those names.
- **Checked before it's shown.** Each sample gets the blocking read (one
  reading: physical slips) and, when the book has `checks.md`, the voice
  review; a separate reviser fixes only the flagged lines (`voice_review`).
  What was found, fixed and left out is in the PR's description.
- **A moment, before the map** (#656). The voice stage comes right after
  the synopsis and act shape, when there are no scenes yet: `--moment
  "..."` writes the author's words for a moment, with the synopsis, in
  place of a scene's plan (`_moment_context`); the key carries it to the
  next round. The prompts are the same.
- **The winner** (`--promote <round file> --sample X --name N`) is saved as
  an anchor, with optional `kind:`, `tense:` and `pov:` headers, from the
  round file as it is now (pull first: the author's edits made on GitHub).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
from dataclasses import asdict, dataclass, field

from storyforge.common import log

SAMPLES_DIR = os.path.join('working', 'voice-samples')
KEYS_ROOT = os.path.join('~', '.storyforge', 'voice-sample-keys')
#: what a round varies when the author doesn't say
DEFAULT_VARY = ('narrator stance', 'distance', 'tense')
LABELS = 'ABCDEFGH'
#: the answer budget for a round: every variant in one reply
ROUND_TOKENS = 16000

VARIANTS_SCHEMA = {
    'type': 'object',
    'properties': {'variants': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'tried': {'type': 'string'}, 'text': {'type': 'string'}},
        'required': ['tried', 'text'],
        'additionalProperties': False,
    }}},
    'required': ['variants'],
    'additionalProperties': False,
}


class SampleError(RuntimeError):
    """A round can't be made: the message says why."""


# ============================================================================
# The round file
# ============================================================================

def one_per_line(text: str) -> str:
    """`text` with each sentence on its own line, paragraphs apart."""
    from storyforge.scene_layout import sentence_spans
    paras = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    out = []
    for p in paras:
        flat = ' '.join(p.split())
        out.append('\n'.join(flat[a:b].strip() for a, b in sentence_spans(flat)))
    return '\n\n'.join(out)


def join_lines(text: str) -> str:
    """A sample's one-sentence-per-line text back into paragraphs."""
    paras = [p for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    return '\n\n'.join(' '.join(line.strip() for line in p.split('\n') if line.strip())
                       for p in paras)


@dataclass(frozen=True)
class Sample:
    """A sample of a round file: its label, its text (one sentence per line,
    as in the file), each sentence's 1-based line in that file's text, and
    the lines of its heading and word count (a comment there is about the
    whole sample)."""
    label: str
    text: str
    lines: dict[int, str]
    head_lines: frozenset[int] = frozenset()


def parse_round(text: str) -> dict[str, Sample]:
    """The samples of a round file, by label. A section is `## Sample X` or
    `## <name>` (a take's version).

    Raises:
        SampleError: a label given twice.
    """
    out: dict[str, Sample] = {}
    label, body, lines, heads = None, [], {}, set()

    def close():
        if label is not None:
            out[label] = Sample(label, '\n'.join(body).strip(), dict(lines), frozenset(heads))

    for n, line in enumerate(text.split('\n'), start=1):
        m = re.match(r'^##\s+(?:Sample\s+(?=[A-Z]\s*$))?(.+?)\s*$', line)
        if m:
            close()
            label = m.group(1).strip()
            if label in out:
                raise SampleError(f'the round file has two samples headed {label!r}')
            body, lines, heads = [], {}, {n}
            continue
        if label is None:
            continue
        if re.match(r'^\*\d[\d,]* words\*$', line.strip()):
            heads.add(n)
            continue
        body.append(line)
        if line.strip():
            lines[n] = line.strip()
    close()
    return out


def render_round(title: str, intro: str, samples: list[tuple[str, str]]) -> str:
    """A round file: the title, the intro, then each (label, text) sample,
    one sentence per line, with its word count."""
    parts = [f'# {title}', '', intro.strip(), '']
    for label, text in samples:
        flowing = one_per_line(text)
        words = len(flowing.split())
        heading = f'Sample {label}' if len(label) == 1 else label
        parts += [f'## {heading}', f'*{words:,} words*', '', flowing, '']
    return '\n'.join(parts).rstrip() + '\n'


INTRO = """{what}

Each sentence is on its own line, so you can comment on any sentence in the pull request: **keep**, **cut**, or **more like this** (and why, if it comes to you), or suggest your own wording. A comment on a sample's heading is about the whole sample. Submit your review when you're done: comments in an unsubmitted review can't be read. {blind}"""

BLIND = 'They are shuffled and unlabelled; what each one tried is kept outside the repo.'


def next_round_number(project_dir: str) -> int:
    folder = os.path.join(project_dir, SAMPLES_DIR)
    taken = [int(m.group(1)) for n in (os.listdir(folder) if os.path.isdir(folder) else [])
             if (m := re.match(r'round-(\d+)\.md$', n))]
    return max(taken, default=0) + 1


def round_rel(n: int) -> str:
    return os.path.join(SAMPLES_DIR, f'round-{n}.md')


def samples_digest(samples: dict[str, Sample]) -> str:
    """A hash of a round's sample texts, so a key is matched to its round."""
    joined = '\n'.join(f'{k}\n{join_lines(s.text)}' for k, s in sorted(samples.items()))
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()


# ============================================================================
# The key
# ============================================================================

@dataclass(frozen=True)
class RoundKey:
    """What a round tried, kept outside the repo: the round, its scene (or,
    before the scene map, the moment it wrote: `scene` '' and `moment` the
    author's words, #656), what it varied and blended (carried by the rounds
    after it, takes included), what each sample tried, the round or sample
    it came from, and the hash of its samples' text as written
    (`samples_digest`)."""
    round: int
    scene: str
    vary: tuple[str, ...] = DEFAULT_VARY
    influences: str = ''
    tried: dict[str, str] = field(default_factory=dict)
    take: str = ''
    from_round: int | None = None
    digest: str = ''
    moment: str = ''

    def __post_init__(self):
        # TD-2: a round wrote a scene or a moment, never both or neither
        if bool(self.scene) == bool(self.moment.strip()):
            raise ValueError('a round key names a scene or a moment, '
                             + ('not both' if self.scene else 'and has neither'))

    @property
    def subject(self) -> str:
        """What the round wrote, for a message: the scene, or the moment."""
        return self.scene or moment_title(self.moment)

    def to_json(self) -> dict:
        d = asdict(self)
        d['vary'] = list(self.vary)
        return d

    @classmethod
    def from_json(cls, d, where: str) -> 'RoundKey':
        try:
            if not isinstance(d, dict) or not isinstance(d.get('tried', {}), dict):
                raise TypeError('not a key object')
            return cls(int(d['round']), str(d['scene'] or ''), tuple(d.get('vary') or DEFAULT_VARY),
                       str(d.get('influences') or ''),
                       {str(k): str(v) for k, v in d.get('tried', {}).items()},
                       str(d.get('take') or ''), d.get('from_round'), str(d.get('digest') or ''),
                       moment=str(d.get('moment') or ''))
        except (KeyError, TypeError, ValueError) as e:
            raise SampleError(f'{where} isn\'t a round key ({e})') from e


def key_path(project_dir: str, n: int) -> str:
    """Where round `n`'s key lives: outside the repo, so the author marks
    the samples blind; by the book folder's path (another clone or
    worktree of the book has its own)."""
    real = os.path.realpath(project_dir)
    slug = f'{os.path.basename(real)}-{hashlib.sha1(real.encode()).hexdigest()[:8]}'
    return os.path.join(os.path.expanduser(KEYS_ROOT), slug, f'round-{n}.json')


def save_key(project_dir: str, key: RoundKey) -> str:
    path = key_path(project_dir, key.round)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(key.to_json(), f, indent=1, ensure_ascii=False)
    return path


def load_key(project_dir: str, n: int) -> RoundKey | None:
    """Round `n`'s key, or None when it isn't on this machine.

    Raises:
        SampleError: the file is there but isn't a key.
    """
    path = key_path(project_dir, n)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise SampleError(f'round {n}\'s key can\'t be read ({path}: {e})') from e
    return RoundKey.from_json(data, path)


# ============================================================================
# The marks on a round
# ============================================================================

@dataclass(frozen=True)
class Mark:
    """One comment on a sample: the sentence(s) it marks, its note, and the
    author's wording (None: no suggestion; '': cut the line)."""
    sentence: str
    note: str = ''
    wording: str | None = None


@dataclass
class SampleMarks:
    """The author's marks on one sample, and reactions to the whole sample."""
    marks: list[Mark] = field(default_factory=list)
    whole: list[str] = field(default_factory=list)


def marks_for_round(prs, samples: dict[str, Sample], round_path: str
                    ) -> tuple[dict[str, SampleMarks], list[str]]:
    """The PR's line comments on the round file (`round_path` from the
    repo's root), by sample. A comment is placed only when its line still
    says what GitHub showed (`Comment.line_text`); every comment that can't
    be placed is counted in the notes."""
    by_line = {n: (s.label, text) for s in samples.values() for n, text in s.lines.items()}
    heads = {n: s.label for s in samples.values() for n in s.head_lines}
    out: dict[str, SampleMarks] = {label: SampleMarks() for label in samples}
    notes = []
    other = moved = nowhere = 0
    path = round_path.replace(os.sep, '/')
    for c in prs.lines:
        if c.path != path:
            other += 1
            continue
        if c.line in heads:
            out[heads[c.line]].whole.append(c.body or 'see the suggestion')
            continue
        where = by_line.get(c.line)
        if where is None:
            nowhere += 1
            continue
        label, sentence = where
        if c.line_text and c.line_text != sentence:
            moved += 1
            continue
        if c.start_line and c.start_line < c.line:
            span = [by_line[n][1] for n in range(c.start_line, c.line + 1)
                    if n in by_line and by_line[n][0] == label]
            sentence = ' '.join(span) or sentence
        wordings = c.suggestions or (None,)
        for i, wording in enumerate(wordings):
            out[label].marks.append(Mark(sentence, c.body if i == 0 else '', wording))
    if other:
        notes.append(f'{other} line comment(s) on other files, left out')
    if nowhere:
        notes.append(f'{nowhere} comment(s) on {path} on lines that are no sample\'s '
                     f'sentence or heading, left out')
    if moved:
        notes.append(f'{moved} comment(s) on lines that have changed since they were made, '
                     f'left out: their sentence can\'t be told for sure')
    return out, notes


def describe_marks(samples: dict[str, Sample], marks: dict[str, SampleMarks],
                   key: RoundKey | None, general: list[str]) -> str:
    """The marked round, for the next round's writer: each sample, what it
    tried (the key), and the author's marks on it."""
    tried = key.tried if key else {}
    parts = ['## The last round, as the author marked it']
    for label, s in samples.items():
        name = f'Sample {label}' if len(label) == 1 else label
        parts.append(f'### {name}' + (f' (it tried: {tried[label]})' if label in tried else ''))
        parts.append(join_lines(s.text))
        sm = marks.get(label) or SampleMarks()
        if sm.whole:
            parts.append('The author on the whole sample:\n'
                         + '\n'.join(f'- {w}' for w in sm.whole))
        if sm.marks:
            lines = []
            for m in sm.marks:
                bits = [m.note] if m.note else []
                if m.wording == '':
                    bits.append('cut it')
                elif m.wording is not None:
                    bits.append(f'the author\'s wording: "{m.wording}"')
                lines.append(f'- "{m.sentence}": ' + '; '.join(bits))
            parts.append('Marks:\n' + '\n'.join(lines))
        if not (sm.marks or sm.whole):
            parts.append('(not marked)')
    if general:
        parts.append('### The author\'s general reactions\n\n' + '\n\n'.join(general))
    return '\n\n'.join(parts)


def count_marks(marks: dict[str, SampleMarks], labels) -> int:
    return sum(len(marks[k].marks) + len(marks[k].whole) for k in labels if k in marks)


# ============================================================================
# Writing a round
# ============================================================================

ROUND_PROMPT = """You are helping an author find the voice of their novel, {title}, by writing one scene several ways for them to react to, sentence by sentence.

{voice}

## The scene

{plan}

## This round

Write exactly {n} versions of this scene, each {words} words. The events are the same in each; only the voice changes. Vary {vary} across them{influences}. Make each version a real attempt at a voice an author would want to keep, not a parody of a style.
{direction}
For each version, say in one line what it tried (`tried`): the narrator's stance, the distance, the tense, the blend. The author won't see these.

Write the scenes as a novel's prose: no title, no notes. Plain, concrete, no stock phrasing."""

DIRECTION = """
{marked}

Write toward what the author kept and asked for more of: those lines are the voice. A cut tells you what's wrong with one line, not what's right; a round that only avoids the cuts comes out flat. Use the author's own wordings where given. Where a general reaction names a direction, take it.
"""

TAKE_PROMPT = """You are helping an author find the voice of their novel, {title}. Below is a sample they marked, line by line. Revise it toward their marks: keep what they kept, take their own wordings, change what they asked to change, and write toward the lines they liked. The events stay the same.

{voice}

## The scene

{plan}

{marked}

Write exactly {n} versions of the revised sample, which differ only in this: {versions}. Each version's `tried` is exactly one of: {names}."""


@dataclass
class Round:
    """A round made: its number, the round file's text, its key, and notes
    on what the checks found, fixed and left out."""
    number: int
    text: str
    key: RoundKey
    notes: list[str] = field(default_factory=list)

    @property
    def rel(self) -> str:
        return round_rel(self.number)


def _voice_text(project_dir: str) -> str:
    from storyforge import voice_book
    voice = voice_book.resolve(project_dir)
    voice.raise_if_unreadable(project_dir)
    if voice.kind == 'ok':
        return voice.text
    return ('## The voice so far\n\nNone yet: this round is how it is found. Write each '
            'version in a distinct, deliberate voice.')


def _scene_context(project_dir: str, scene_id: str) -> str:
    from storyforge import session
    try:
        return session.scene_plan(project_dir, scene_id, notes=True)
    except session.SessionError as e:
        raise SampleError(str(e)) from e


#: what the checks and the logs call a round of a moment (no scene id yet)
MOMENT_LABEL = 'voice-moment'
#: the longest a moment's words go into a round's title
_MOMENT_TITLE = 60


def moment_title(moment: str) -> str:
    """A moment's words, for a title or a message: one line, cut short."""
    text = ' '.join(moment.split())
    if len(text) > _MOMENT_TITLE:
        text = text[:_MOMENT_TITLE].rsplit(' ', 1)[0] + '…'
    return f'a moment ({text})'


#: what a moment round's notes say about the physical check (SF-L): a
#: moment has no scenes.csv row, so no POV to read the blocking against
MOMENT_CHECK_NOTE = ('A moment has no scene, so the physical check read each sample without '
                     'a point of view.')


def _synopsis(project_dir: str) -> tuple[str, str]:
    """(story-summary.md's synopsis, or '' with why not). '' with a reason
    when the file or the section is missing, empty, or still init's
    template text (SF-4: the template's instructions aren't the book).

    Raises:
        SampleError: story-summary.md is there but can't be read.
    """
    from storyforge.common import STORY_SUMMARY_PATH, get_plugin_dir, parse_story_summary
    try:
        parsed = parse_story_summary(project_dir)
    except (OSError, ValueError) as e:   # UnicodeDecodeError is a ValueError
        raise SampleError(f'{STORY_SUMMARY_PATH} can\'t be read ({e})') from e
    if parsed is None:
        return '', f'{STORY_SUMMARY_PATH} is missing'
    synopsis = (parsed.get('synopsis') or '').strip()
    if not synopsis:
        return '', f'{STORY_SUMMARY_PATH} has no synopsis'
    try:
        template = ((parse_story_summary(os.path.join(get_plugin_dir(), 'templates')) or {})
                    .get('synopsis') or '').strip()
    except (OSError, ValueError):
        template = ''
    if template and ' '.join(synopsis.split()) == ' '.join(template.split()):
        return '', f'{STORY_SUMMARY_PATH}\'s synopsis is still init\'s template'
    return synopsis, ''


def _moment_context(project_dir: str, moment: str) -> tuple[str, list[str]]:
    """The plan for a round of a moment (#656): the voice stage comes before
    the scene map, so there's no scene to plan from. The author's words for
    the moment, and the book's synopsis (who and what it's about) when
    story-summary.md has one; and the round's notes: no synopsis (why), and
    the physical check without a POV.

    Raises:
        SampleError: the moment is empty, or story-summary.md can't be read.
    """
    if not moment.strip():
        raise SampleError('--moment is empty: say the moment to write, in a sentence or two')
    lines = ['# A moment from the book (no scene map yet)', '', moment.strip()]
    notes = [MOMENT_CHECK_NOTE]
    synopsis, why = _synopsis(project_dir)
    if synopsis:
        lines += ['', '## What the book is about (the synopsis)', '', synopsis]
    else:
        notes.insert(0, f'{why}: the round had only the moment\'s words to go on.')
    return '\n'.join(lines), notes


def _plan(project_dir: str, scene_id: str, moment: str) -> tuple[str, str, list[str]]:
    """(the plan, the label for the checks and logs, notes for the round): a
    scene's plan, or a moment's when `moment` is given (then `scene_id` is
    '')."""
    if moment:
        if scene_id:
            raise SampleError('give a scene or a moment, not both')
        plan, notes = _moment_context(project_dir, moment)
        return plan, MOMENT_LABEL, notes
    return _scene_context(project_dir, scene_id), scene_id, []


def _ask_variants(prompt: str, model: str, log_file: str, project_dir: str,
                  scene_id: str) -> list[dict]:
    from storyforge.api import RefusalError, extract_text, invoke, is_truncated, log_reply
    try:
        response = invoke(prompt, model, ROUND_TOKENS, label=f'voice sample {scene_id}',
                          output_schema=VARIANTS_SCHEMA)
    except (RefusalError, RuntimeError) as e:
        raise SampleError(f'the round could not be written ({e})') from e
    log_reply(project_dir, response, 'voice-sample', scene_id, model)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(response, f)
    if is_truncated(response):
        raise SampleError(f'the round\'s reply hit its token limit ({log_file})')
    try:
        return json.loads(extract_text(response))['variants']
    except (ValueError, KeyError, TypeError) as e:
        raise SampleError(f'the round\'s reply could not be read ({e}; {log_file})') from e


def _usable(variants: list[dict], want: int, log_file: str) -> list[dict]:
    """Exactly `want` variants, each with text and what it tried.

    Raises:
        SampleError: fewer or more, or one blank.
    """
    blank = [i for i, v in enumerate(variants)
             if not (v.get('text') or '').strip() or not (v.get('tried') or '').strip()]
    if blank or len(variants) != want:
        raise SampleError(f'the round\'s reply has {len(variants)} version(s), {len(blank)} of '
                          f'them blank; {want} were asked for ({log_file}). Run it again')
    return variants


def check_samples(project_dir: str, scene_id: str, texts: dict[str, str], *, model: str,
                  log_dir: str) -> tuple[dict[str, str], list[str]]:
    """Each sample's physical slips (the blocking read, one reading) and,
    with checks.md, the voice review; a reviser fixes only what they flag.
    Returns the texts after it and notes for the PR: what was found and
    fixed, and every flag or check left out. The blocking read's spend is
    logged (`voice-sample-check`)."""
    from storyforge import api, blocking, voice_book, voice_review
    from storyforge.common import ReferenceDocError
    has_checks = bool(voice_book.checks_text(project_dir))
    out, notes = {}, []
    if not has_checks:
        notes.append('reference/voice/checks.md has no checks yet (missing, empty or init\'s '
                     'template): only physical slips were checked.')
    for label, text in texts.items():
        flags: list = []
        found = []
        try:
            with api.metered() as meter:
                read = blocking.check_blocking(
                    project_dir, scene_id, prose=text, model=model, readings=1,
                    log_file=os.path.join(log_dir, f'{label}-blocking.json'))
            meter.log(project_dir, 'voice-sample-check', scene_id)
            quoted = [f for f in read.findings if f.scene_quote]
            flags += [voice_review.Flag(f.scene_quote, 'blocking', f.explanation)
                      for f in quoted]
            found.append(f'{len(quoted)} physical slip(s)')
            left = (len(read.findings) - len(quoted)) + len(read.unverified)
            if left:
                notes.append(f'Sample {label}: {left} physical finding(s) left out '
                             f'(unverified, or quoting nothing).')
        except blocking.BlockingError as e:
            notes.append(f'Sample {label}: the physical check didn\'t finish ({e}).')
        if has_checks:
            try:
                rev = voice_review.review(project_dir, scene_id, text, model=model,
                                          log_file=os.path.join(log_dir, f'{label}-review.json'))
                flags += rev.flags
                found.append(f'{len(rev.flags)} line(s) against checks.md')
                left = len(rev.unverified) + rev.over_cap + rev.repeated
                if left:
                    notes.append(f'Sample {label}: {left} checks.md flag(s) left out '
                                 f'(not in the sample, past the cap, or repeated).')
            except (voice_review.VoiceReviewError, ReferenceDocError) as e:
                notes.append(f'Sample {label}: the voice review didn\'t finish ({e}).')
        placed = [f for f in flags if voice_review.flag_spans(text, f.quote)]
        if len(placed) < len(flags):
            notes.append(f'Sample {label}: {len(flags) - len(placed)} flag(s) whose words '
                         f'aren\'t in the sample, left out.')
        if not placed:
            out[label] = text
            continue
        try:
            revision = voice_review.revise(project_dir, scene_id, text, placed, model=model,
                                           log_file=os.path.join(log_dir, f'{label}-revise.json'),
                                           layout=False)
            out[label] = revision.prose
            notes.append(f'Sample {label}: flagged before you saw it ({", ".join(found)}); '
                         f'{revision.summary()}'
                         + (f'; {"; ".join(revision.dropped)}' if revision.dropped else '')
                         + '.')
        except (voice_review.VoiceReviewError, ReferenceDocError) as e:
            out[label] = text
            notes.append(f'Sample {label}: {len(placed)} line(s) flagged, not fixed: the '
                         f'reviser didn\'t finish ({e}).')
    return out, notes


def write_round(project_dir: str, scene_id: str, *, variants: int, vary: list[str],
                influences: str, model: str, log_dir: str, marked: str = '',
                previous: RoundKey | None = None, words: str = '300 to 500',
                rng: random.Random | None = None, moment: str = '') -> Round:
    """Round `next_round_number`: exactly `variants` versions of `scene_id`
    (or, with `scene_id` '', of `moment`: before the scene map, #656),
    checked, shuffled and labelled A, B, C... `marked`: the last round as
    the author marked it (`describe_marks`), for a round after the first.

    Raises:
        SampleError: `variants` out of range, the scene isn't in the book, or
            the round can't be written (a reply with the wrong count).
        common.ReferenceDocError, voice_repo.VoiceError: the voice can't be read.
    """
    from storyforge.common import read_yaml_field
    if not 2 <= variants <= len(LABELS):
        raise SampleError(f'--variants takes 2 to {len(LABELS)}, not {variants}')
    plan, label, plan_notes = _plan(project_dir, scene_id, moment)
    subject = scene_id or moment_title(moment)
    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    n = next_round_number(project_dir)
    infl = f', blending these influences: {influences}' if influences else ''
    prompt = ROUND_PROMPT.format(title=title, voice=_voice_text(project_dir), plan=plan,
                                 n=variants, words=words, vary=', '.join(vary),
                                 influences=infl,
                                 direction=DIRECTION.format(marked=marked) if marked else '')
    log_file = os.path.join(log_dir, f'round-{n}.json')
    got = _usable(_ask_variants(prompt, model, log_file, project_dir, label), variants,
                  log_file)
    rng = rng or random.Random()
    rng.shuffle(got)
    labelled = {LABELS[i]: v for i, v in enumerate(got)}
    texts, notes = check_samples(project_dir, label,
                                 {k: v['text'] for k, v in labelled.items()}, model=model,
                                 log_dir=os.path.join(log_dir, f'round-{n}-checks'))
    what = (f'{len(texts)} versions of *{subject}*. The events are the same in each; only '
            f'the voice changes: {", ".join(vary)}'
            + (f', and how they blend {influences}' if influences else '') + '.')
    text = render_round(f'Voice samples, round {n}: {subject}',
                        INTRO.format(what=what, blind=BLIND), list(texts.items()))
    key = RoundKey(n, scene_id, tuple(vary), influences,
                   {k: v['tried'] for k, v in labelled.items()}, '',
                   previous.round if previous else None,
                   samples_digest(parse_round(text)), moment=moment)
    return Round(n, text, key, plan_notes + notes)


def write_take(project_dir: str, scene_id: str, *, sample: str, marked: str,
               versions: list[str], model: str, log_dir: str,
               previous: RoundKey | None = None, moment: str = '') -> Round:
    """A take: one marked sample revised toward its marks, in versions that
    differ only in `versions` (each heads its version; matched by what the
    reply says it tried). The influences and vary list are carried from
    `previous`. With `scene_id` '' it takes on a round of `moment` (#656).

    Raises:
        SampleError: fewer than two or repeated versions, a reply that
            doesn't give each version once, or as `write_round`.
    """
    from storyforge.common import read_yaml_field
    if len(versions) < 2:
        raise SampleError('--versions names at least two, separated by ";"')
    if len(set(v.lower() for v in versions)) != len(versions):
        raise SampleError('--versions names one of them twice')
    plan, label, plan_notes = _plan(project_dir, scene_id, moment)
    subject = scene_id or moment_title(moment)
    title = read_yaml_field('project.title', project_dir) or 'Untitled'
    n = next_round_number(project_dir)
    prompt = TAKE_PROMPT.format(title=title, voice=_voice_text(project_dir), plan=plan,
                                marked=marked, n=len(versions),
                                versions=' / '.join(versions),
                                names='; '.join(versions))
    log_file = os.path.join(log_dir, f'round-{n}.json')
    got = _usable(_ask_variants(prompt, model, log_file, project_dir, label),
                  len(versions), log_file)
    by_name = {v.lower(): v for v in versions}
    named: dict[str, str] = {}
    for v in got:
        name = by_name.get(v['tried'].strip().lower())
        if name is None or name in named:
            raise SampleError(f'the take\'s reply names a version {v["tried"]!r}, not one of '
                              f'{"; ".join(versions)} once each ({log_file}). Run it again')
        named[name] = v['text']
    named = {v: named[v] for v in versions}
    texts, notes = check_samples(project_dir, label, named, model=model,
                                 log_dir=os.path.join(log_dir, f'round-{n}-checks'))
    what = (f'Sample {sample} of the last round, revised toward your marks, in '
            f'{len(texts)} versions: ' + '; '.join(texts) + '.')
    text = render_round(f'Voice samples, round {n}: {subject}, take on sample {sample}',
                        INTRO.format(what=what, blind=''), list(texts.items()))
    key = RoundKey(n, scene_id, previous.vary if previous else DEFAULT_VARY,
                   previous.influences if previous else '', {k: k for k in texts}, sample,
                   previous.round if previous else None, samples_digest(parse_round(text)),
                   moment=moment)
    return Round(n, text, key, plan_notes + notes)


# ============================================================================
# The winner
# ============================================================================

def promote(project_dir: str, round_file: str, label: str, name: str, *, kind: str = '',
            tense: str = '', pov: str = '', force: bool = False, dry_run: bool = False) -> str:
    """Save sample `label` of `round_file` (as it is now, hand edits
    included) as `reference/voice/anchors/<name>.md`; checked as an anchor
    before anything is written. Returns its path.

    Raises:
        SampleError: no such sample or round file, an anchor of that name
            (without `force`), a bad name or tense, or a sample that isn't
            an anchor (empty).
    """
    from storyforge import voice_book
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
        raise SampleError(f'--name {name!r}: use lowercase letters, digits and hyphens')
    if tense and tense not in voice_book.TENSES:
        raise SampleError(f'--tense takes {" or ".join(voice_book.TENSES)}, not {tense!r}')
    path = round_file if os.path.isabs(round_file) else os.path.join(project_dir, round_file)
    try:
        with open(path, encoding='utf-8') as f:
            samples = parse_round(f.read())
    except OSError as e:
        raise SampleError(f'{round_file} can\'t be read ({e})') from e
    sample = samples.get(label)
    if sample is None:
        raise SampleError(f'{round_file} has no sample {label!r} (it has '
                          f'{", ".join(samples) or "none"})')
    rel = os.path.join(voice_book.ANCHORS_DIR, f'{name}.md')
    dest = os.path.join(project_dir, rel)
    if os.path.exists(dest) and not force:
        raise SampleError(f'{rel} is there already; pass --force to replace it')
    header = [f'{k}: {v}' for k, v in (('kind', kind), ('tense', tense), ('pov', pov)) if v]
    content = ('\n'.join(header) + '\n\n' if header else '') + join_lines(sample.text) + '\n'
    try:
        voice_book.parse_anchor(rel, content)
    except ValueError as e:
        raise SampleError(f'sample {label} isn\'t an anchor: {e}') from e
    if not dry_run:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'w', encoding='utf-8') as f:
            f.write(content)
    return rel
