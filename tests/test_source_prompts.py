"""Adaptation (#477): the source-aware elaboration prompts and shared context.

Without a `source:` block nothing changes (also checked against the recorded
eval prompts by `evals/run.py`)."""

import os

import pytest

from storyforge import common, prompts_elaborate as pe, prompts_source, source

from source_helpers import YAML, _write, import_source, make_adaptation

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _fresh_context():
    common.clear_shared_context_cache()
    yield
    common.clear_shared_context_cache()


@pytest.fixture
def adapted(tmp_path):
    proj = make_adaptation(tmp_path)
    import_source(proj)
    _write(proj, {
        'storyforge.yaml': YAML.format(
            extra='  mode: faithful\n  rules: reference/key-decisions.md#version-rules'),
        'reference/scenes.csv': ('id|seq|title|status\n'
                                 'olympus-council-meets|1|Council|mapped\n'
                                 'athena-at-the-door|2|At the Door|mapped\n'
                                 'telemachus-sails-at-night|3|Night|mapped\n'),
        'reference/source-map.csv': (
            'scene_id|source_scenes|treatment|note\n'
            'olympus-council-meets|gods-debate|dramatize|\n'
            'athena-at-the-door|minerva-visits;assembly-called|compress|two days in one\n'
            'telemachus-sails-at-night||invent|\n'
            '|ship-sails|cut|told in a line\n'),
    })
    return proj


class TestWithoutSource:
    def test_sections_are_empty(self, project_dir):
        assert prompts_source.spine_section(project_dir) == ''
        assert prompts_source.architecture_section(project_dir) == ''
        assert prompts_source.map_section(project_dir) == ''
        assert prompts_source.briefs_section(project_dir, None) == ''
        assert prompts_source.bibles_text(project_dir) == []

    def test_prompts_carry_no_source_text(self, project_dir):
        for prompt in (pe.build_spine_prompt(project_dir, PLUGIN, 'seed'),
                       pe.build_architecture_prompt(project_dir, PLUGIN),
                       pe.build_map_prompt(project_dir, PLUGIN),
                       pe.build_briefs_prompt(project_dir, PLUGIN),
                       pe._existing_refs(project_dir)):
            assert 'Source' not in prompt
            assert 'source-map' not in prompt

    @pytest.mark.parametrize('name, build', [
        ('spine', lambda p: pe.build_spine_prompt(p, PLUGIN, 'seed', system_context=True)),
        ('architecture', lambda p: pe.build_architecture_prompt(p, PLUGIN, 'REGISTRIES',
                                                                 system_context=True)),
        ('map', lambda p: pe.build_map_prompt(p, PLUGIN, 'REGISTRIES', system_context=True)),
        ('briefs', lambda p: pe.build_briefs_prompt(p, PLUGIN, None, 'REGISTRIES',
                                                    system_context=True)),
        ('existing-refs', lambda p: pe._existing_refs(p)),
    ])
    def test_byte_identical_to_main(self, project_dir, name, build):
        """T-7: generated from main's builders on the fixture project before
        #477. A deliberate prompt change regenerates these files."""
        golden = os.path.join(PLUGIN, 'tests', 'fixtures', 'golden-prompts', f'{name}.txt')
        with open(golden, encoding='utf-8', newline='') as f:
            assert build(project_dir) == f.read()

    def test_shared_context_has_no_source_bible(self, project_dir):
        labels = [b['text'].split('\n', 1)[0] for b in
                  common.build_shared_context(project_dir, 'claude-opus-5-5')]
        assert not any('Source Bible' in l for l in labels)


class TestWithSource:
    def test_shared_context_and_refs_carry_the_source_bible(self, adapted):
        blocks = common.build_shared_context(adapted, 'claude-opus-5-5')
        bible = [b for b in blocks if b['text'].startswith('=== Source Bible (odyssey) ===')]
        assert len(bible) == 1 and 'The Gods Debate' in bible[0]['text']
        assert blocks[-1].get('cache_control') or len(''.join(b['text'] for b in blocks)) < 16384
        assert '### Source Bible (odyssey)' in pe._existing_refs(adapted)

    def test_spine(self, adapted):
        p = pe.build_spine_prompt(adapted, PLUGIN, 'seed', system_context=True)
        assert 'selection and reframing of the source' in p
        assert 'Mode: **faithful**' in p
        assert 'softens the killing' in p         # the version rules
        # Key Decisions is in the reference docs whole (G-012), so the rules
        # it holds are pointed to, not repeated, and never under an
        # inverted heading (B-015)
        assert p.count('softens the killing') == 1
        assert p.count('Not a rule') == 1
        assert 'The version rules are in Key Decisions' in p
        assert '### Version rules' not in p

    def test_rules_kept_elsewhere_are_given_with_their_own_heading(self, adapted):
        _write(adapted, {
            'reference/version-rules.md': '# Rules\n\n## Version rules\n\nNo gods cut.\n',
            'storyforge.yaml': YAML.format(
                extra='  mode: faithful\n  rules: reference/version-rules.md#version-rules')})
        p = pe.build_spine_prompt(adapted, PLUGIN, 'seed', system_context=True)
        assert '\n### Version rules\n\nNo gods cut.' in p     # demoted under ## Source
        assert '\n## Version rules\n\nNo gods cut.' not in p

    def test_spine_lists_the_source_spine_when_there_is_one(self, adapted, tmp_path):
        _write(adapted, {'reference/source/odyssey/spine.csv':
                         'id|seq|title|summary\ngods-free-him|1|Freed|Zeus frees Odysseus\n'})
        p = pe.build_spine_prompt(adapted, PLUGIN, 'seed', system_context=True)
        assert '1|gods-free-him|Freed|Zeus frees Odysseus' in p

    def test_architecture_has_cast_and_pov(self, adapted):
        p = pe.build_architecture_prompt(adapted, PLUGIN, system_context=True)
        assert 'Telemachus (`telemachus`): 3 scenes (75%)' in p
        assert 'Narrator (`narrator`): 1 scenes (25%)' in p
        assert 'Athena (`athena`), supporting: on stage in 3' in p

    def test_map_lists_every_source_scene_and_asks_for_the_map(self, adapted):
        p = pe.build_map_prompt(adapted, PLUGIN, system_context=True)
        for sid in ('gods-debate', 'minerva-visits', 'assembly-called', 'ship-sails'):
            assert f'|{sid}|' in p
        assert '```source-map-csv\nscene_id|source_scenes|treatment|note' in p
        assert 'Account for **every** source scene' in p
        assert 'slug:id' not in p    # one source: bare ids

    def test_briefs_carry_source_briefs_prose_and_names(self, adapted):
        p = pe.build_briefs_prompt(adapted, PLUGIN, system_context=True)
        assert '### athena-at-the-door: compress (two days in one)' in p
        assert '#### Source scene odyssey:minerva-visits: Athena Visits' in p
        assert '**goal:** Athena wants to rouse Telemachus' in p       # mapped brief
        assert '<source-prose scene="minerva-visits">\nThen Pallas Minerva went down.' in p
        assert ('**knowledge_out:** ulysses-to-return (Zeus decrees Odysseus goes home)'
                in p)
        assert 'Minerva → Athena' in p and 'Saturn → Cronus' in p
        assert '### telemachus-sails-at-night: invent' in p
        assert '#### Source scene odyssey:ship-sails' not in p     # cut: not briefed

    def test_briefs_scope(self, adapted):
        p = pe.build_briefs_prompt(adapted, PLUGIN, scene_ids=['olympus-council-meets'],
                                   system_context=True)
        assert 'gods-debate' in p and '### athena-at-the-door' not in p

    def test_briefs_skip_scenes_already_briefed(self, adapted):
        _write(adapted, {'reference/scene-briefs.csv':
                         'id|goal\nathena-at-the-door|She knocks\n'})
        p = pe.build_briefs_prompt(adapted, PLUGIN, system_context=True)
        assert '### olympus-council-meets' in p and '### athena-at-the-door' not in p

    def test_source_prose_over_budget_is_named(self, adapted, monkeypatch):
        monkeypatch.setattr(prompts_source, 'SOURCE_PROSE_MAX_WORDS', 8)
        p = pe.build_briefs_prompt(adapted, PLUGIN, system_context=True)
        assert '<source-prose scene="gods-debate">' in p          # 8 words: fits
        assert '<source-prose scene="minerva-visits">' not in p
        assert 'Source prose left out' in p and 'odyssey:minerva-visits' in p

    def test_no_map_yet_is_said(self, adapted):
        os.remove(source.source_map_path(adapted))
        p = pe.build_briefs_prompt(adapted, PLUGIN, system_context=True)
        assert 'There is no source map yet' in p

    def test_not_imported_stops_every_prompt(self, adapted):
        """SF-2/CR-4: a prompt would promise a source and show none of it."""
        import shutil
        shutil.rmtree(os.path.join(adapted, 'reference', 'source', 'odyssey'))
        for build in (lambda: pe.build_spine_prompt(adapted, PLUGIN, 's', system_context=True),
                      lambda: pe.build_map_prompt(adapted, PLUGIN, system_context=True),
                      lambda: common.build_shared_context(adapted, 'claude-opus-5-5')):
            with pytest.raises(source.SourceError, match='not imported'):
                build()

    def test_briefs_warn_the_author(self, adapted, monkeypatch, capsys):
        """SF-6: what the prompt leaves out is logged, and a source scene that
        can't be found is named in the prompt rather than skipped."""
        monkeypatch.setattr(prompts_source, 'SOURCE_PROSE_MAX_WORDS', 8)
        _write(adapted, {'reference/source-map.csv': (
            'scene_id|source_scenes|treatment|note\n'
            'olympus-council-meets|gods-debate;no-such-scene|dramatize|\n'
            'athena-at-the-door|minerva-visits;assembly-called|compress|two days in one\n')})
        p = pe.build_briefs_prompt(adapted, PLUGIN, system_context=True)
        out = capsys.readouterr().out
        assert '#### Source scene no-such-scene: not found in the imported source' in p
        assert 'source scenes not found in the imported source' in out
        assert 'not in the source map, briefed without source scenes: telemachus-sails' in out
        assert 'source prose left out' in out

    def test_missing_rules_section_stops(self, adapted):
        _write(adapted, {'storyforge.yaml': YAML.format(
            extra='  rules: reference/key-decisions.md#gone')})
        with pytest.raises(source.SourceError):
            pe.build_map_prompt(adapted, PLUGIN, system_context=True)


class TestDraftingPrompt:
    """#561 (B-025): an adaptation's drafting prompt had the Source Bible
    but not the mode, the version rules, or the scene's source passage."""

    def _prompt(self, project, scene_id):
        from storyforge.prompts import build_scene_prompt_from_briefs
        return build_scene_prompt_from_briefs(scene_id, project, PLUGIN, 'full',
                                              system_context=True)

    def test_carries_mode_treatment_passage_and_rules(self, adapted):
        p = self._prompt(adapted, 'athena-at-the-door')
        section = p.split('## Source\n', 1)[1]
        assert 'Mode: **faithful**' in section
        assert "treatment of its source: **compress** (two days in one)" in section
        assert '<source-prose scene="minerva-visits">\nThen Pallas Minerva went down.' in section
        assert '<source-prose scene="assembly-called">' in section
        assert 'softens the killing' in section           # the version rules
        assert 'Not a rule' not in p                      # only the rules section
        assert 'Minerva → Athena' in section
        assert p.index('## Source\n') < p.index('## Task')

    def test_an_invented_scene_has_rules_and_no_passage(self, adapted):
        p = self._prompt(adapted, 'telemachus-sails-at-night')
        assert 'An invented scene: it has no source passage' in p
        assert '<source-prose' not in p and 'softens the killing' in p

    def test_a_scene_not_in_the_map_is_said(self, adapted, capsys):
        _write(adapted, {'reference/source-map.csv':
                         'scene_id|source_scenes|treatment|note\n'
                         'olympus-council-meets|gods-debate|dramatize|\n'})
        p = self._prompt(adapted, 'athena-at-the-door')
        assert 'not in the source map, so no source passage' in p
        assert 'athena-at-the-door is not in reference/source-map.csv' in capsys.readouterr().out

    def test_source_prose_over_budget_is_named(self, adapted, monkeypatch, capsys):
        monkeypatch.setattr(prompts_source, 'DRAFT_SOURCE_MAX_WORDS', 8)
        p = self._prompt(adapted, 'athena-at-the-door')
        assert '<source-prose scene="minerva-visits">' in p          # fits
        assert '<source-prose scene="assembly-called">' not in p
        assert 'Source prose left out' in p and 'odyssey:assembly-called' in p
        assert 'source prose left out of the drafting prompt' in capsys.readouterr().out

    def test_without_a_source_block_there_is_no_section(self, project_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        p = build_scene_prompt_from_briefs('act1-sc01', project_dir, PLUGIN, 'full')
        assert '## Source' not in p and '<source-prose' not in p


class TestDraftingPromptBranches:
    """#571's review: the drafting section's other branches."""

    def _prompt(self, project, scene_id):
        from storyforge.prompts import build_scene_prompt_from_briefs
        return build_scene_prompt_from_briefs(scene_id, project, PLUGIN, 'full',
                                              system_context=True)

    def _map(self, adapted, row):
        _write(adapted, {'reference/source-map.csv':
                         'scene_id|source_scenes|treatment|note\n' + row + '\n'})

    def test_a_source_scene_not_found_is_named(self, adapted, capsys):
        self._map(adapted, 'athena-at-the-door|minerva-visits;no-such-scene|compress|')
        p = self._prompt(adapted, 'athena-at-the-door')
        assert 'Not found in the imported source: no-such-scene.' in p
        assert '<source-prose scene="minerva-visits">' in p
        assert 'source scenes not found in the imported source' in capsys.readouterr().out

    def test_a_source_scene_with_no_prose_says_so(self, adapted, monkeypatch):
        monkeypatch.setattr(source, 'source_prose', lambda *a: '')
        self._map(adapted, 'athena-at-the-door|minerva-visits|compress|')
        p = self._prompt(adapted, 'athena-at-the-door')
        assert '#### Source scene odyssey:minerva-visits\n\n(no source prose for this scene)' in p
        assert '<source-prose' not in p

    def test_a_mapped_scene_with_no_source_scenes_says_so(self, adapted):
        self._map(adapted, 'athena-at-the-door||dramatize|')
        p = self._prompt(adapted, 'athena-at-the-door')
        assert 'The map gives no source scene for it.' in p
        assert '<source-prose' not in p and 'softens the killing' in p

    def test_rules_from_a_file_section_sit_under_source(self, adapted):
        _write(adapted, {
            'homer/version-rules.md': '# Rules\n\n## Teen\n\nNo gore.\n\n### Detail\n\nx\n',
            'storyforge.yaml': YAML.format(
                extra='  mode: faithful\n  rules: homer/version-rules.md#teen')})
        section = self._prompt(adapted, 'athena-at-the-door').split('## Source\n', 1)[1]
        assert '\n### Teen\n\nNo gore.' in section and '\n#### Detail' in section
        assert '\n## Teen' not in section


def test_a_drafting_prompt_without_a_source_block_is_unchanged(project_dir):
    """#561: generated from main's builder before the drafting section; a
    deliberate prompt change regenerates the file."""
    from storyforge.prompts import build_scene_prompt_from_briefs
    golden = os.path.join(PLUGIN, 'tests', 'fixtures', 'golden-prompts', 'drafting.txt')
    with open(golden, encoding='utf-8', newline='') as f:
        assert build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full',
                                              system_context=True) == f.read()
