"""The briefs stage writes facts, never staging (#644, plan D3 and D4).

A brief keeps events, the turn, the outcome, and the knowledge and physical
state in and out. `key_dialogue`, `subtext`, `emotions` and `motifs` are the
author's optional notes: the stage never generates them, a reply that gives
them anyway is not written, and what the author wrote is kept. The author's
`must:` beats (#642) survive a regeneration word for word, and drafting and
the gate work from a brief whose optional columns are empty."""

import os

import pytest

from storyforge.cmd_elaborate import main
from storyforge.elaborate import AUTHOR_NOTE_COLUMNS, _read_csv_as_map
from storyforge.enrich import update_csv_field
from storyforge.prompts_elaborate import BRIEFS_OUTPUT_HEADER, NOTES_RULE

SCENE = 'new-x1'
FACTS = ('new-x1|yes-but|Kael opens the sealed drawer;Kael finds the census roll torn out;'
         'Kael pockets the stub||archivist-knows-village||torn-sleeve-kael|||||||false')
OLD_HEADER = ('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|'
              'key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|'
              'physical_state_in|physical_state_out')


def _reply(header, *rows):
    return '```briefs-csv\n' + header + '\n' + ''.join(r + '\n' for r in rows) + '```\n'


def _hone_reply(prompt):
    """The ledger reconciliation's reply: every numbered reference a NEW
    fact or state (as test_cmd_elaborate_briefs_ledger)."""
    import re
    refs = re.findall(r'^(\d+)\. (\S+)', prompt, re.M)
    if 'NEW | id | character | description' in prompt:
        return ''.join(f'{n} | NEW | {t} | Kael Maren | {t} | injury | false\n'
                       for n, t in refs)
    return ''.join(f'{n} | NEW | {t} | {t.replace("-", " ")} | secret\n' for n, t in refs)


@pytest.fixture
def novel(project_dir, monkeypatch, mock_git, mock_costs):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.cmd_elaborate.select_model', lambda tier: 'test-model')
    return project_dir


def _run(mock_api, reply, *extra):
    mock_api.set_response_fn(lambda prompt: _hone_reply(prompt)
                             if 'match no registry id' in prompt else reply)
    try:
        main(['--stage', 'briefs', *extra])
    except SystemExit:
        pass


def _brief(proj, sid=SCENE):
    return _read_csv_as_map(os.path.join(proj, 'reference', 'scene-briefs.csv'))[sid]


def _briefs_prompt(mock_api):
    return next(c['prompt'] for c in mock_api.calls
                if 'briefs-csv' in (c.get('prompt') or ''))


class TestThePromptAsksForFacts:
    def test_the_reply_header_has_no_author_notes(self, novel, mock_api):
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        prompt = _briefs_prompt(mock_api)
        header = prompt.split('```briefs-csv\n', 1)[1].split('\n', 1)[0]
        assert header == BRIEFS_OUTPUT_HEADER
        assert not set(header.split('|')) & set(AUTHOR_NOTE_COLUMNS)
        for col in AUTHOR_NOTE_COLUMNS:
            assert f'- **{col}**' not in prompt
        assert NOTES_RULE in prompt

    def test_no_motif_registry_is_offered(self, novel, mock_api):
        """motif-taxonomy.csv stays (the fixture has one); it no longer
        places motifs in briefs."""
        assert os.path.getsize(os.path.join(novel, 'reference', 'motif-taxonomy.csv'))
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        prompt = _briefs_prompt(mock_api)
        assert '### Motifs' not in prompt
        assert '### Characters' in prompt     # the other registries still go in

    def test_no_framework_mandates(self, novel, mock_api):
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        prompt = _briefs_prompt(mock_api)
        assert 'Every scene must have goal/conflict/outcome filled' not in prompt
        assert 'genuine dilemma' not in prompt
        assert 'Key dialogue should sound like the character' not in prompt
        assert '## Craft Principles' not in prompt
        assert 'Every scene must have its outcome and key_actions filled' in prompt


class TestAFactOnlyRun:
    def test_a_fact_only_reply_writes_a_fact_only_brief(self, novel, mock_api):
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        row = _brief(novel)
        assert row['outcome'] == 'yes-but'
        assert row['key_actions'].startswith('Kael opens the sealed drawer')
        assert row['knowledge_out'] == 'archivist-knows-village'
        assert row['physical_state_out'] == 'torn-sleeve-kael'
        for col in AUTHOR_NOTE_COLUMNS + ('goal', 'conflict', 'crisis', 'decision'):
            assert row[col] == '', col

    def test_staging_in_a_reply_is_not_written(self, novel, mock_api, capsys):
        """A reply on the old header (a model that ignores the prompt) has
        its author-note columns left out, and the run says so."""
        old = ('new-x1|Learn the truth|The archivist lies|yes-but|Trust or not|Trusts|'
               '|archivist-knows-village|Asks;Listens|Kael: "Ask me again"|fear;hope|'
               'ledger-ink|He means the opposite||false||')
        _run(mock_api, _reply(OLD_HEADER, old))
        row = _brief(novel)
        for col in AUTHOR_NOTE_COLUMNS:
            assert row[col] == '', col
        assert row['key_actions'] == 'Asks;Listens'
        out = capsys.readouterr().out
        assert ("left out the reply's key_dialogue, subtext, emotions, motifs: the "
                "author's notes, never generated (#644)") in out

    def test_the_authors_notes_are_kept(self, novel, mock_api):
        """An existing brief's hand-written notes survive a regeneration, even
        when the reply gives its own."""
        path = os.path.join(novel, 'reference', 'scene-briefs.csv')
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        update_csv_field(path, SCENE, 'subtext', 'Kael lies about the drawer')
        update_csv_field(path, SCENE, 'emotions', 'calm;fear')
        update_csv_field(path, SCENE, 'motifs', 'maps/cartography')
        cells = dict(zip(BRIEFS_OUTPUT_HEADER.split('|'), FACTS.split('|')))
        cells.update(key_dialogue='Kael: "Never"', subtext='A model subtext',
                     emotions='dread', motifs='ledger-ink')
        row_text = '|'.join(cells.get(c, '') for c in OLD_HEADER.split('|'))
        _run(mock_api, _reply(OLD_HEADER, row_text))
        row = _brief(novel)
        assert (row['subtext'], row['emotions'], row['motifs'], row['key_dialogue']) == (
            'Kael lies about the drawer', 'calm;fear', 'maps/cartography', '')


class TestMustBeatsEndToEnd:
    """#642 and #644: trimming a brief to facts and regenerating it keep the
    author's `must:` items word for word, in key_actions and key_dialogue;
    drafting is told to carry them; the gate reads them."""

    MUST_ACTION = 'must: Kael burns the census stub in the lamp'
    MUST_LINE = 'must: Kael: "The village was never on any map I drew"'

    def _author_marks(self, proj):
        path = os.path.join(proj, 'reference', 'scene-briefs.csv')
        update_csv_field(path, SCENE, 'key_actions',
                         f'Kael opens the sealed drawer;{self.MUST_ACTION};Kael leaves')
        update_csv_field(path, SCENE, 'key_dialogue', self.MUST_LINE)

    def test_regenerating_keeps_every_must_item(self, novel, mock_api, capsys):
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        self._author_marks(novel)
        # the regenerated brief drops the must action and gives a line of its own
        reworded = FACTS.replace('Kael pockets the stub', 'Kael burns the stub')
        cells = dict(zip(BRIEFS_OUTPUT_HEADER.split('|'), reworded.split('|')))
        cells['key_dialogue'] = 'Kael: "I never drew it"'
        _run(mock_api, _reply(OLD_HEADER, '|'.join(cells.get(c, '')
                                                    for c in OLD_HEADER.split('|'))))
        row = _brief(novel)
        assert self.MUST_ACTION in row['key_actions'].split('; ')
        assert row['key_actions'].startswith('Kael opens the sealed drawer')
        assert row['key_dialogue'] == self.MUST_LINE
        out = capsys.readouterr().out
        assert "put back the author's must item(s)" in out

    def test_a_scoped_rerun_on_a_fact_only_reply_keeps_them(self, novel, mock_api):
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        self._author_marks(novel)
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS), '--scene', SCENE)
        row = _brief(novel)
        assert self.MUST_ACTION in row['key_actions'].split('; ')
        assert row['key_dialogue'] == self.MUST_LINE

    def test_drafting_and_the_gate_read_the_kept_beats(self, novel, mock_api):
        from storyforge import gate
        from storyforge.prompts import build_scene_prompt_from_briefs
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        self._author_marks(novel)
        _run(mock_api, _reply(BRIEFS_OUTPUT_HEADER, FACTS))
        plugin = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        p = build_scene_prompt_from_briefs(SCENE, novel, plugin, 'full')
        assert ('- These beats, which the brief marks must: '
                'Kael burns the census stub in the lamp') in p
        checklist = p.split('**Key dialogue checklist', 1)[1]
        assert 'word for word' in checklist.split('\n', 1)[0]
        assert '  - [ ] Kael: "The village was never on any map I drew"' in checklist
        assert '**Key dialogue notes' not in p
        [line] = gate._brief_lines(novel, SCENE)
        assert line.text == 'The village was never on any map I drew'
        assert gate._must_beats(_brief(novel))['key_dialogue'][0].raw == self.MUST_LINE
