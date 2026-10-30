"""Found validating The Great Gatsby after #322 (evals F-033, F-034)."""

import os

from ledger_helpers import read_facts


def _rewrite(path, edit):
    import csv
    with open(path) as f:
        rows = list(csv.DictReader(f, delimiter='|'))
        header = list(rows[0].keys())
    edit(rows)
    with open(path, 'w') as f:
        w = csv.DictWriter(f, fieldnames=header, delimiter='|', lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


class TestMiceMentionsValidate:
    """F-020 made a bare name a mention, but the schema still required +/-:
    120 errors on Gatsby."""

    def test_bare_mention_is_valid(self):
        from storyforge.schema import _check_mice
        alias = {'tom-myrtle-affair': 'tom-myrtle-affair'}
        types = {'tom-myrtle-affair': 'character'}
        assert _check_mice('tom-myrtle-affair;+tom-myrtle-affair;-tom-myrtle-affair',
                           alias, types) == []
        assert _check_mice('character:tom-myrtle-affair', alias, types) == []

    def test_unknown_mention_still_reported(self):
        from storyforge.schema import _check_mice
        problems = _check_mice('no-such-thread', {'a': 'a'}, {})
        assert problems and 'not in mice-threads.csv' in problems[0]['reason']

    def test_prose_is_not_a_mention_without_a_registry(self):
        from storyforge.schema import _check_mice
        assert _check_mice('gatsby dream opens', {}, {})
        assert _check_mice('+ +x', {}, {})
        assert _check_mice('gatsby-dream;+inquiry:who', {}, {}) == []

    def test_bare_operator_is_invalid(self):
        from storyforge.schema import _check_mice
        assert _check_mice('+', {}, {})


class TestBooleanAnswers:
    """Gatsby's physical states stored action_gating as prose ("Yes — Wilson
    cannot move or act independently"): 39 schema failures."""

    def test_reduce_boolean(self):
        from storyforge.enrich import reduce_boolean
        assert reduce_boolean('Yes — Wilson cannot move') == 'true'
        assert reduce_boolean('no') == 'false'
        assert reduce_boolean('No — cosmetic only') == 'false'
        assert reduce_boolean('action_gating: yes') == 'true'
        assert reduce_boolean('TRUE') == 'true'
        assert reduce_boolean('Limits ability to care for himself') == \
            'Limits ability to care for himself'
        assert reduce_boolean('nothing') == 'nothing'
        # Review of #323: hedges and other labels are left alone
        for raw in ('Yes/no', 'no — but yes in act 3', 'yes, partially; no when seated',
                    'Maybe: yes', 'partially: no'):
            assert reduce_boolean(raw) == raw, raw

    def test_physical_state_parser_reduces(self):
        # action_gating is now a JSON boolean in a structured reply, so the
        # model can no longer attach prose; the parser writes the CSV strings.
        import json
        from storyforge.extract import parse_physical_state_response
        result = parse_physical_state_response(json.dumps({
            'physical_state_in': [], 'physical_state_out': [], 'resolved_states': [],
            'new_states': [
                {'id': 'daisy-sobbing', 'character': 'daisy-buchanan',
                 'description': 'sobbing', 'category': 'appearance', 'action_gating': True},
                {'id': 'gatsby-pink-suit', 'character': 'jay-gatsby',
                 'description': 'pink suit', 'category': 'appearance', 'action_gating': False},
            ]}), 'sc1')
        gating = {s['id']: s['action_gating'] for s in result['_new_states']}
        assert gating == {'daisy-sobbing': 'true', 'gatsby-pink-suit': 'false'}

    def test_hone_write_registry_reduces(self, project_dir):
        from storyforge.hone import write_registry
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')
        write_registry(ref_dir, 'physical-states', [
            {'id': 'x', 'character': 'Pell', 'description': 'd', 'category': 'injury',
             'acquired': 'act1-sc01', 'resolves': 'never', 'action_gating': 'Yes — limps'}])
        assert read_facts(ref_dir, 'physical-states.csv')['x']['action_gating'] == 'true'


class TestCleanupAnswerFormats:
    def test_repairs_stored_values(self, project_dir):
        from storyforge.extract import run_cleanup
        from storyforge.elaborate import _read_csv_as_map
        ref_dir = os.path.join(project_dir, 'reference')

        def phys(rows):
            states = [r for r in rows if r['type'] == 'physical']
            states[0]['action_gating'] = 'Yes — cannot run'
            states[1]['action_gating'] = 'Produces as evidence; drives dialogue'

        def briefs(rows):
            rows[0]['continuity_deps'] = '(none)'
            rows[1]['continuity_deps'] = 'act1-sc01;none'
        _rewrite(os.path.join(ref_dir, 'commitments.csv'), phys)
        _rewrite(os.path.join(ref_dir, 'scene-briefs.csv'), briefs)

        summary = run_cleanup(ref_dir)

        assert summary['answer_formats']['count'] == 3
        p = list(read_facts(ref_dir, 'physical-states.csv').values())
        assert p[0]['action_gating'] == 'true'
        assert p[1]['action_gating'] == 'Produces as evidence; drives dialogue'
        b = list(_read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv')).values())
        assert b[0]['continuity_deps'] == '' and b[1]['continuity_deps'] == 'act1-sc01'
        # Idempotent
        assert run_cleanup(ref_dir)['answer_formats']['count'] == 0

    def test_changes_only_the_gating_cell_of_the_ledger(self, project_dir):
        """Only physical rows' action_gating changes: every other fact and
        every other column (a quote, who knows it) is kept."""
        from storyforge import ledger
        from storyforge.extract import cleanup_answer_formats
        ref_dir = os.path.join(project_dir, 'reference')
        rows = ledger.load_from(ref_dir)
        rows[0]['quote'] = 'keep me'
        states = [r for r in rows if r['type'] == 'physical']
        states[0]['action_gating'] = 'Yes — limps'
        states[0]['known_by'] = 'tessa-merrin'
        ledger.save_to(ref_dir, rows, command='test')
        cleanup_answer_formats(ref_dir)
        after = ledger.load_from(ref_dir)
        states[0]['action_gating'] = 'true'
        assert after == rows


def test_physical_state_prompt_asks_for_a_boolean():
    # The structured reply's schema now enforces the boolean; the prompt names the field.
    from storyforge.extract import PHYSICAL_STATE_SCHEMA, build_physical_state_prompt
    state = PHYSICAL_STATE_SCHEMA['properties']['new_states']['items']
    assert state['properties']['action_gating'] == {'type': 'boolean'}
    prompt = build_physical_state_prompt('s1', 'Text.', {'on_stage': 'Nick'}, {}, [])
    assert 'action_gating (true when' in prompt
