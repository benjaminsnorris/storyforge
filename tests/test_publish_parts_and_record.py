"""Book parts in the publish manifest (F-155) and the publish record (F-156)."""
import hashlib
import json
import os
import subprocess
from unittest.mock import patch

import pytest


def _project(tmp_path, chapter_parts, yaml_parts=None):
    """A project with one scene per chapter; chapter_parts gives each chapter's part column."""
    ref = tmp_path / 'reference'
    ref.mkdir(exist_ok=True)
    scenes_dir = tmp_path / 'scenes'
    scenes_dir.mkdir(exist_ok=True)
    yaml = 'project:\n  title: Middlemarch\n  author: George Eliot\n'
    if yaml_parts:
        yaml += 'parts:\n' + ''.join(
            f"  - number: {n}\n    title: '{t}'\n" for n, t in enumerate(yaml_parts, 1))
    (tmp_path / 'storyforge.yaml').write_text(yaml)
    scenes = [f's{i}' for i in range(1, len(chapter_parts) + 1)]
    lines = ['id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words']
    for i, sid in enumerate(scenes, 1):
        lines.append(f'{sid}|{i}|T{i}||pov|loc|1|morning|short|action|drafted|3|200')
    (ref / 'scenes.csv').write_text('\n'.join(lines) + '\n')
    ch = ['chapter|title|heading|part|scenes']
    for i, (sid, part) in enumerate(zip(scenes, chapter_parts), 1):
        ch.append(f'{i}|Chapter {i}|numbered|{part}|{sid}')
    (ref / 'chapter-map.csv').write_text('\n'.join(ch) + '\n')
    for sid in scenes:
        (scenes_dir / f'{sid}.md').write_text(f'Scene {sid} -- here.\n')
    return str(tmp_path)


def _manifest(project):
    from storyforge.assembly import generate_publish_manifest
    with open(generate_publish_manifest(project, include_dashboard=False,
                                        include_cover=False)) as f:
        return json.load(f)


# ============================================================================
# F-155: parts
# ============================================================================

class TestManifestParts:
    def test_each_chapter_carries_its_titled_part(self, tmp_path):
        proj = _project(tmp_path, ['', '1', '1', '2'],
                        ['Book I: Miss Brooke', 'Book II: Old and Young'])
        chapters = _manifest(proj)['chapters']
        assert [c.get('part') for c in chapters] == [
            None,
            {'number': 1, 'title': 'Book I: Miss Brooke'},
            {'number': 1, 'title': 'Book I: Miss Brooke'},
            {'number': 2, 'title': 'Book II: Old and Young'},
        ]

    def test_a_part_number_without_a_title_sends_no_part(self, tmp_path):
        """Homer: each book's part number, but no parts: in storyforge.yaml."""
        chapters = _manifest(_project(tmp_path, ['1', '2']))['chapters']
        assert all('part' not in c for c in chapters)


class TestWriteParts:
    def test_replaces_the_templates_commented_example(self, tmp_path):
        from storyforge.assembly import read_part_field, count_parts, write_parts
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: X\n\n# parts:\n#   - number: 1\n#     title: "Part One"\n'
            '#   - number: 2\n#     title: "Part Two"\n\n# Production\nproduction:\n  author: A\n')
        assert write_parts(str(tmp_path), ["Book I: Miss Brooke", "Volume II: Lydgate's"])
        text = (tmp_path / 'storyforge.yaml').read_text()
        assert '# parts:' not in text and 'Part One' not in text
        assert 'production:\n  author: A' in text
        assert count_parts(str(tmp_path)) == 2
        assert read_part_field(1, str(tmp_path), 'title') == 'Book I: Miss Brooke'
        assert read_part_field(2, str(tmp_path), 'title') == "Volume II: Lydgate's"

    def test_appends_when_there_is_no_example(self, tmp_path):
        from storyforge.assembly import read_part_field, write_parts
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: X\n')
        assert write_parts(str(tmp_path), ['Volume I'])
        assert read_part_field(1, str(tmp_path), 'title') == 'Volume I'

    def test_leaves_the_authors_parts_alone(self, tmp_path):
        from storyforge.assembly import write_parts
        original = "parts:\n  - number: 1\n    title: 'Mine'\n"
        (tmp_path / 'storyforge.yaml').write_text(original)
        assert not write_parts(str(tmp_path), ['Theirs'])
        assert (tmp_path / 'storyforge.yaml').read_text() == original


class TestPartTitles:
    def test_parts_that_hold_chapters_are_kept(self):
        from storyforge.cmd_scenes_setup import _part_titles
        units = [(1, 'chapter', 'Prelude'), (9, 'part', '# Book I: Miss Brooke'),
                 (11, 'chapter', 'Chapter I'), (90, 'chapter', 'Chapter II'),
                 (200, 'part', 'BOOK II. OLD AND YOUNG.'), (202, 'chapter', 'Chapter XIII')]
        assert _part_titles(units) == ['Book I: Miss Brooke', 'BOOK II. OLD AND YOUNG.']

    def test_a_part_that_is_its_own_chapter_means_no_parts(self):
        """The Iliad: "BOOK I" heads the text itself; no chapter heading follows."""
        from storyforge.cmd_scenes_setup import _part_titles
        units = [(1, 'part', 'BOOK I'), (300, 'part', 'BOOK II')]
        assert _part_titles(units) == []
        assert _part_titles([(1, 'part', 'Book I'), (3, 'chapter', 'Chapter 1'),
                             (90, 'part', 'Book II')]) == []

    def test_no_parts(self):
        from storyforge.cmd_scenes_setup import _part_titles
        assert _part_titles([(1, 'chapter', 'Chapter 1')]) == []


# ============================================================================
# F-156: the publish record and --verify
# ============================================================================

def _git_project(tmp_path):
    proj = _project(tmp_path, ['1', '1'], ['Volume I'])
    for cmd in (['init', '-q', '-b', 'main'], ['config', 'user.email', 't@t'],
                ['config', 'user.name', 't'], ['add', '-A'], ['commit', '-qm', 'init']):
        subprocess.run(['git', '-C', proj, *cmd], check=True)
    return proj


def _live_from(manifest):
    """What Bookshelf's digest route returns for a stored manifest."""
    from storyforge.publish_record import chapters_digest
    return {'slug': manifest['slug'], 'title': manifest['title'],
            'updated_at': 'now', 'chapters': chapters_digest(manifest['chapters'])}


ENV = {v: 'x' for v in ('BOOKSHELF_URL', 'BOOKSHELF_EMAIL', 'BOOKSHELF_PASSWORD',
                        'BOOKSHELF_SUPABASE_URL', 'BOOKSHELF_SUPABASE_ANON_KEY')}


def _publish(proj, capsys):
    from storyforge import cmd_publish
    sent = {}

    def fake_publish(url, token, manifest):
        sent['manifest'] = manifest
        return {'book_id': 'b1', 'slug': manifest['slug'],
                'published': {'chapters': 2, 'scenes': 2, 'words': 8}}

    with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
         patch.dict(os.environ, ENV), \
         patch('storyforge.bookshelf.authenticate', return_value='tok'), \
         patch('storyforge.bookshelf.publish', side_effect=fake_publish), \
         patch('storyforge.git._push', return_value=True):
        cmd_publish.main(['--no-dashboard', '--no-cover'])
    capsys.readouterr()
    return sent['manifest']


def _verify(proj, live, capsys):
    from storyforge import cmd_publish
    with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
         patch.dict(os.environ, ENV), \
         patch('storyforge.bookshelf.authenticate', return_value='tok'), \
         patch('storyforge.bookshelf.get_digest', return_value=live), \
         pytest.raises(SystemExit) as exit_:
        cmd_publish.main(['--verify', '--no-cover'])
    return exit_.value.code, capsys.readouterr().out


class TestPublishRecord:
    def test_a_publish_writes_and_commits_the_record(self, tmp_path, capsys):
        proj = _git_project(tmp_path)
        sent = _publish(proj, capsys)
        with open(os.path.join(proj, 'production', 'publish-record.json')) as f:
            record = json.load(f)
        assert record['slug'] == 'middlemarch' and record['book_id'] == 'b1'
        assert record['totals'] == {'chapters': 2, 'scenes': 2, 'words': 8}
        assert record['project_commit']
        assert record['uncommitted_changes'] is False
        scene = record['chapters'][0]['scenes'][0]
        html = sent['chapters'][0]['scenes'][0]['content_html']
        assert scene['sha256'] == hashlib.sha256(html.encode()).hexdigest()
        assert record['chapters'][0]['part'] == {'number': 1, 'title': 'Volume I'}
        # No prose in the record: hashes only.
        assert 'content_html' not in json.dumps(record)
        log = subprocess.run(['git', '-C', proj, 'log', '--name-only', '-1', '--format=%s'],
                             capture_output=True, text=True).stdout
        assert 'Publish: record what is live' in log
        assert 'production/publish-record.json' in log

    def test_the_record_commit_leaves_other_staged_files_alone(self, tmp_path, capsys):
        proj = _git_project(tmp_path)
        with open(os.path.join(proj, 'notes.md'), 'w') as f:
            f.write('staged, not published\n')
        subprocess.run(['git', '-C', proj, 'add', 'notes.md'], check=True)
        _publish(proj, capsys)
        files = subprocess.run(['git', '-C', proj, 'show', '--name-only', '--format=', 'HEAD'],
                               capture_output=True, text=True).stdout.split()
        assert files == ['production/publish-record.json']
        staged = subprocess.run(['git', '-C', proj, 'diff', '--cached', '--name-only'],
                                capture_output=True, text=True).stdout.split()
        assert staged == ['notes.md']

    def test_a_failed_publish_writes_no_record(self, tmp_path, capsys):
        from storyforge import cmd_publish
        proj = _git_project(tmp_path)
        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
             patch.dict(os.environ, ENV), \
             patch('storyforge.bookshelf.authenticate', return_value='tok'), \
             patch('storyforge.bookshelf.publish', side_effect=RuntimeError('boom')), \
             pytest.raises(SystemExit):
            cmd_publish.main(['--no-dashboard', '--no-cover'])
        assert not os.path.exists(os.path.join(proj, 'production', 'publish-record.json'))


class TestVerify:
    def test_live_matches_the_record(self, tmp_path, capsys):
        proj = _git_project(tmp_path)
        live = _live_from(_publish(proj, capsys))
        code, out = _verify(proj, live, capsys)
        assert code == 0
        assert 'Live matches the record' in out
        assert 'nothing to publish' in out

    def test_a_changed_live_scene_fails(self, tmp_path, capsys):
        proj = _git_project(tmp_path)
        live = _live_from(_publish(proj, capsys))
        live['chapters'][1]['scenes'][0]['sha256'] = '0' * 64
        live['chapters'][0]['part'] = None
        code, out = _verify(proj, live, capsys)
        assert code == 1
        assert 'chapter 2: scene s2 text differs' in out
        assert 'chapter 1: part is null live' in out

    def test_a_local_edit_is_reported_as_not_yet_published(self, tmp_path, capsys):
        proj = _git_project(tmp_path)
        live = _live_from(_publish(proj, capsys))
        with open(os.path.join(proj, 'scenes', 's1.md'), 'a') as f:
            f.write('\nA new paragraph.\n')
        code, out = _verify(proj, live, capsys)
        assert code == 0
        assert 'Not yet published' in out
        assert 'chapter 1: scene s1 text differs' in out

    def test_without_a_record_it_still_compares_the_project(self, tmp_path, capsys):
        proj = _project(tmp_path, ['1', '1'], ['Volume I'])
        live = _live_from(_manifest(proj))
        code, out = _verify(proj, live, capsys)
        assert code == 2
        assert 'No production/publish-record.json' in out
        assert 'nothing to publish' in out

    def test_an_unknown_book_fails(self, tmp_path, capsys):
        proj = _project(tmp_path, ['1'], ['Volume I'])
        code, out = _verify(proj, None, capsys)
        assert code == 1
        assert 'Bookshelf has no book "middlemarch"' in out


class TestCompare:
    def test_a_moved_scene_reads_as_moved(self):
        from storyforge.publish_record import compare
        exp = [{'number': 1, 'title': 'A', 'scenes': []},
               {'number': 2, 'title': 'B', 'scenes': [{'slug': 'x', 'sort_order': 1, 'sha256': 'h'}]}]
        live = [{'number': 1, 'title': 'A', 'scenes': [{'slug': 'x', 'sort_order': 1, 'sha256': 'h'}]},
                {'number': 2, 'title': 'B', 'scenes': []}]
        assert compare(exp, live) == ['chapter 2: scene x is not live (it is live in chapter 1)']

    def test_missing_and_extra_chapters(self):
        from storyforge.publish_record import compare
        exp = [{'number': 1, 'title': 'A', 'scenes': []}]
        live = [{'number': 2, 'title': 'B', 'scenes': []}]
        assert compare(exp, live) == ['chapter 1 ("A") is not live',
                                      'chapter 2 ("B") is live but not expected']
