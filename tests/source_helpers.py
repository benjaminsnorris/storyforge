"""A tiny source project and an adaptation of it (#477), for the source tests."""

import os

from storyforge import source

# ----------------------------------------------------------------------------
# A tiny source project and an adaptation of it
# ----------------------------------------------------------------------------

SOURCE_FILES = {
    'reference/scenes.csv': (
        'id|seq|title|summary|pov|location|timeline_day\n'
        'gods-debate|1|The Gods Debate|Jove and Minerva debate the return of Ulysses|narrator|olympus|1\n'
        'minerva-visits|2|Minerva Visits|Minerva comes to Ithaca as Mentes|telemachus|ithaca-hall|1\n'
        'assembly-called|3|The Assembly|Telemachus calls the assembly; the son of Saturn sends eagles|telemachus|ithaca-hall|2\n'
        'ship-sails|4|The Ship Sails|Telemachus sails at night for Pylos|telemachus|harbor|3\n'
    ),
    'reference/scene-intent.csv': (
        'id|function|value_at_stake|value_shift|characters|on_stage|mice_threads\n'
        'gods-debate|Jove grants the return|homecoming|-/+|jove;minerva;ulysses|jove;minerva|+ulysses-return\n'
        'minerva-visits|Pallas Minerva rouses the son|courage|-/+|minerva;telemachus|minerva;telemachus|ulysses-return\n'
        'assembly-called|Telemachus defies the suitors|authority|-/+|telemachus|telemachus|\n'
        'ship-sails|The journey begins|courage|+/++|telemachus;minerva|telemachus;minerva|\n'
    ),
    'reference/scene-briefs.csv': (
        'id|goal|outcome|key_actions|key_dialogue|knowledge_out\n'
        'gods-debate|Minerva wants Jove to free Ulysses|yes|Jove agrees;Mercury is sent|"Ulysses suffers"|ulysses-to-return\n'
        'minerva-visits|Minerva wants to rouse Telemachus|yes|Minerva as Mentes|"Go to Pylos"|\n'
        'assembly-called|Telemachus wants the suitors gone|no-but|eagles fight|"Leave my house"|\n'
        'ship-sails|Telemachus wants news of Ulysses|yes|the ship sails|"Cast off"|\n'
    ),
    'reference/characters.csv': (
        'id|name|role|aliases\n'
        'jove|Jove|supporting|son of Saturn\n'
        'minerva|Minerva|supporting|Pallas Minerva;Pallas\n'
        'ulysses|Ulysses|protagonist|\n'
        'telemachus|Telemachus|protagonist|\n'
        'narrator|Narrator|minor|\n'
    ),
    'reference/locations.csv': (
        'id|name|aliases\n'
        'olympus|Olympus|\n'
        'ithaca-hall|Hall of Ulysses|\n'
        'harbor|Harbor|\n'
    ),
    'reference/mice-threads.csv': 'id|name|type|aliases\nulysses-return|Ulysses\' return|event|\n',
    'reference/commitments.csv': (
        'id|scene_id|type|subject|statement|quote|known_by\n'
        'ulysses-to-return|gods-debate|knowledge|ulysses|Jove decrees Ulysses goes home|'
        '"Ulysses shall go home"|minerva\n'
    ),
    'reference/world-bible.md': '# World\n\nJove rules Olympus.\n',
    'scenes/gods-debate.md': 'Now Jove spoke to Minerva of Ulysses.\r\n',
    'scenes/minerva-visits.md': 'Then Pallas Minerva went down.\n',
    'scenes/assembly-called.md': 'The son of Saturn sent two eagles.\n',
    'scenes/ship-sails.md': 'They sailed all night.\n',
}

NAME_MAP = (
    'source_id|target_id|source_name|target_name\n'
    'jove|zeus|Jove|Zeus\n'
    'minerva|athena|Minerva|Athena\n'
    'ulysses|odysseus|Ulysses|Odysseus\n'
    'telemachus|telemachus|Telemachus|Telemachus\n'
    'narrator|narrator|Narrator|Narrator\n'
    'olympus|olympus|Olympus|Olympus\n'
    'ithaca-hall|ithaca-hall|Hall of Ulysses|Hall of Odysseus\n'
    'harbor|harbor|Harbor|Harbor\n'
    '||Saturn|Cronus\n'
    '||Pallas Minerva|Pallas Athena\n'
    '||Mercury|Hermes\n'
)

YAML = """project:
  title: "Telemachus"
  medium: novel
phase: spine

source:
  projects:
    - slug: odyssey
      path: ../odyssey   # the extraction
  name_map: reference/names.csv
{extra}
"""


def _write(base, files):
    for rel, text in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)


def make_adaptation(tmp_path):
    src = tmp_path / 'odyssey'
    proj = tmp_path / 'telemachus'
    _write(src, SOURCE_FILES)
    _write(proj, {
        'storyforge.yaml': YAML.format(extra='  mode: faithful'),
        'reference/names.csv': NAME_MAP,
        'reference/scenes.csv': 'id|seq|title\n',
        'reference/key-decisions.md': '# Key Decisions\n\n## Version rules\n\nThe YA version '
                                      'softens the killing.\n\n## Other\n\nNot a rule.\n',
    })
    return str(proj)


def import_source(project_dir, **kw):
    cfg = source.read_config(project_dir)
    return source.import_source(project_dir, cfg, 'odyssey', **kw)


# ----------------------------------------------------------------------------
# The no-range snapshot: what an adaptation without a `range:` produces,
# fixed in tests/fixtures/golden-prompts/source-no-range.json from the code
# as it was before source ranges were added (#517). A deliberate change
# regenerates it: json.dump({**snapshot_outputs(tmp, plugin),
# **snapshot_outputs_multi(tmp2, plugin)}, f, indent=1, sort_keys=True,
# ensure_ascii=False) plus a trailing newline.
# ----------------------------------------------------------------------------

SNAPSHOT_FILES = {
    'reference/scenes.csv': ('id|seq|title|status|pov\n'
                             'olympus-council-meets|1|Council|mapped|narrator\n'
                             'athena-at-the-door|2|At the Door|mapped|telemachus\n'
                             'telemachus-sails-at-night|3|Night|mapped|telemachus\n'),
    'reference/scene-intent.csv': ('id|function|on_stage\n'
                                   'olympus-council-meets|x|zeus;athena\n'
                                   'athena-at-the-door|y|athena;telemachus\n'
                                   'telemachus-sails-at-night|z|telemachus\n'),
    'reference/scene-briefs.csv': (
        'id|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|knowledge_out\n'
        'athena-at-the-door|Athena wants to rouse him|suitors|yes|c|d|she knocks|"Go"|\n'),
    'reference/source-map.csv': (
        'scene_id|source_scenes|treatment|note\n'
        'olympus-council-meets|gods-debate|dramatize|\n'
        'athena-at-the-door|minerva-visits;assembly-called|compress|two days in one\n'
        'telemachus-sails-at-night||invent|\n'),
    'scenes/athena-at-the-door.md': 'Athena came to the door. ' * 10,
}


def snapshot_outputs(tmp_path, plugin):
    """Every source output of the snapshot adaptation, as text: the import's
    files, the source bible, the four prompt sections, coverage (with one
    source scene left unaccounted for) and one source-fidelity prompt."""
    import json
    from storyforge import prompts_source, source_fidelity
    proj = make_adaptation(tmp_path)
    _write(proj, {'storyforge.yaml': YAML.format(
        extra='  mode: faithful\n  rules: reference/key-decisions.md#version-rules')})
    result = import_source(proj)
    _write(proj, SNAPSHOT_FILES)
    cfg = source.read_config(proj)
    rows = source.map_rows_by_scene(source.read_source_map(proj))
    plan = source_fidelity.plan_scene(proj, 'athena-at-the-door', 'brief', plugin, cfg, rows,
                                      source.read_rules(proj, cfg))
    bible = os.path.join(proj, 'reference', 'source', 'odyssey', source.SOURCE_BIBLE)
    with open(bible, encoding='utf-8') as f:
        bible_text = f.read()
    return {
        'import_files': sorted(result.files),
        'bible': bible_text,
        'spine': prompts_source.spine_section(proj),
        'architecture': prompts_source.architecture_section(proj),
        'map': prompts_source.map_section(proj),
        'briefs': prompts_source.briefs_section(proj, None),
        'coverage': json.dumps(source.check_coverage(proj, cfg), sort_keys=True, indent=1),
        'fidelity': plan.prompt,
    }


MULTI_YAML = """project:
  title: "Telemachus"
source:
  projects:
    - slug: odyssey
      path: ../odyssey
    - slug: iliad
      path: ../iliad
  name_map: reference/names.csv
  mode: free
"""


def snapshot_outputs_multi(tmp_path, plugin):
    """The same outputs for two sources (the second a copy of the first, so
    every id is shared and refs are `slug:id`) in free mode, keyed `multi_*`."""
    import json
    from storyforge import prompts_source, source_fidelity
    proj = make_adaptation(tmp_path)
    _write(str(tmp_path / 'iliad'), SOURCE_FILES)
    _write(proj, {'storyforge.yaml': MULTI_YAML})
    cfg = source.read_config(proj)
    for slug in cfg.slugs():
        source.import_source(proj, cfg, slug)
    _write(proj, {**SNAPSHOT_FILES, 'reference/source-map.csv': (
        'scene_id|source_scenes|treatment|note\n'
        'olympus-council-meets|odyssey:gods-debate;iliad:gods-debate|compress|\n'
        'athena-at-the-door|odyssey:minerva-visits;iliad:assembly-called|compress|both\n'
        'telemachus-sails-at-night||invent|\n'
        '|iliad:ship-sails|cut|later\n')})
    rows = source.map_rows_by_scene(source.read_source_map(proj))
    plan = source_fidelity.plan_scene(proj, 'athena-at-the-door', 'brief', plugin, cfg, rows,
                                      source.read_rules(proj, cfg))
    return {
        'multi_spine': prompts_source.spine_section(proj),
        'multi_architecture': prompts_source.architecture_section(proj),
        'multi_map': prompts_source.map_section(proj),
        'multi_briefs': prompts_source.briefs_section(proj, None),
        'multi_coverage': json.dumps(source.check_coverage(proj, cfg), sort_keys=True,
                                     indent=1),
        'multi_fidelity': plan.prompt,
    }
