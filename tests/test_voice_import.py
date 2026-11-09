"""`storyforge voice import` (#652, plan B1): `storyforge.voice_import` on
local fixtures, with fetching faked (no network)."""

import os

import pytest

from storyforge import voice_import as vi
from storyforge import voice_repo as vr

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(PLUGIN, 'tests', 'fixtures', 'voice-import')


def _read(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as f:
        return f.read()


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / 'my-voice'
    vr.init_repo(str(d), 'Test Author')
    return str(d)


def _no_network(url):
    raise AssertionError(f'fetched {url}')


class FakeWeb:
    """Pages by URL; records what was asked for."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        if url not in self.pages:
            raise vi.VoiceImportError(f'{url} couldn\'t be fetched (HTTPError: 404)')
        ctype, body = self.pages[url]
        return vi.Fetched(url, ctype, body.encode('utf-8'))


# ============================================================================
# Markdown
# ============================================================================

def test_markdown_front_matter_gives_title_date_and_kind():
    p = vi.markdown_piece(_read('posts/2019-03-02-on-walking.md'), 'src')
    assert (p.title, p.date, p.kind, p.kind_found) == ('On Walking', '2019-03-02', 'essay', True)
    assert p.body.startswith('I walk most mornings') and '---' not in p.body


def test_markdown_link_post_and_fiction_and_the_title_heading():
    link = vi.markdown_piece(_read('posts/a-link-worth-reading.md'), 'src')
    assert link.kind == 'link' and 'emulation' not in link.body   # the quote isn't theirs
    story = vi.markdown_piece(_read('posts/the-lighthouse-keeper.md'), 'src')
    assert story.kind == 'fiction' and story.title == 'The Lighthouse Keeper'
    assert not story.body.startswith('#')                           # the heading is the title


def test_markdown_loses_what_isnt_prose():
    p = vi.markdown_piece(_read('posts/notes-on-tools.md'), 'src')
    body = p.body
    for gone in ('print(', 'quotation from somebody', '| pen', 'shot.png', 'example.com',
                 'footnote', 'alert', '<div', '[^1]', '[docs]'):
        assert gone not in body, gone
    assert 'with a link to the docs and an image:' in body
    assert 'The second is patience.' in body and 'Some inline HTML text stays.' in body
    assert not p.kind_found and p.kind == 'essay'


def test_front_matter_lists_and_no_front_matter():
    meta, rest = vi.front_matter('---\ntags:\n  - Notes\n  - x\ntitle: T\n---\nBody.\n')
    assert meta == {'tags': ['Notes', 'x'], 'title': 'T'} and rest == 'Body.\n'
    assert vi.front_matter('No front matter.\n') == ({}, 'No front matter.\n')
    p = vi.markdown_piece('---\ntype: note\n---\nA quick one.\n', 'src')
    assert p.kind == 'notes'


@pytest.mark.parametrize('raw, want', [
    ('2019-03-02 08:15:00 -0700', '2019-03-02'),
    ('2019-03-02T08:15:00Z', '2019-03-02'),
    ('Sat, 30 Dec 2023 10:00:00 +0000', '2023-12-30'),
    ('2019', '2019'),
    ('2019-04', '2019-04'),
    ('last Tuesday', ''),
    ('', ''),
])
def test_dates(raw, want):
    assert vi._norm_date(raw) == want


# ============================================================================
# HTML
# ============================================================================

def test_html_keeps_the_article_and_drops_boilerplate():
    page = vi.html_page(_read('page.html'))
    assert page.title == 'Why I Still Write Letters' and page.date == '2018-11-20'
    body = page.body
    assert body.startswith('My grandmother wrote me a letter')
    assert 'can’t edit it once it’s sealed' in body      # entities decoded
    assert '## What changed' in body
    for gone in ('Home', 'Subscribe', 'tracking', 'color: red', 'famous line', 'shoebox, in',
                 'not = ', 'Share on', 'Great post', 'Related posts', 'All rights reserved',
                 'November 20, 2018'):
        assert gone not in body, gone


def test_html_without_an_article_takes_main_then_body():
    main = vi.html_page('<html><body><nav>Menu</nav><main><p>In main.</p></main>'
                        '<p>Outside.</p></body></html>')
    assert main.body == 'In main.'
    body = vi.html_page('<html><head><title>T</title></head><body><p>One.</p>'
                        '<div>Two<br>three.</div><footer>F</footer></body></html>')
    assert body.title == 'T' and body.body == 'One.\n\nTwo\n\nthree.'


def test_html_content_class_marks_the_article_and_unclosed_tags_survive():
    page = vi.html_page('<body><div class="sidebar"><p>Side</div>'
                        '<div class="entry-content"><p>First<p>Second</div><p>After</body>')
    assert page.body == 'First\n\nSecond'


# ============================================================================
# Feeds
# ============================================================================

def test_rss_items_kinds_dates_and_cut_summaries():
    site, items, notes = vi.feed_items(_read('feed.xml'), 'feed.xml')
    assert site == 'https://www.example.com/' and notes == []
    assert [i.title for i in items] == ['The Year in Books', "Someone else's great essay",
                                        'A cut summary']
    assert items[0].date == '2023-12-30' and not items[0].summary_only
    assert [vi._truncated(i) for i in items] == [False, False, True]


def test_atom_items():
    site, items, _ = vi.feed_items(_read('atom.xml'), 'atom.xml')
    assert site == 'https://example.com/'
    assert [(i.title, i.date, i.categories) for i in items] == [
        ('On Rain', '2017-04-02', ('essay',)), ('A short story', '2017-05-09', ('story',))]
    assert 'empty' in vi.html_page(items[1].html).body


def test_a_feed_with_entities_is_refused_unparsed():
    with pytest.raises(vi.VoiceImportError, match='DOCTYPE or an entity'):
        vi.feed_items(_read('entities.xml'), 'entities.xml')


def test_a_wordpress_export_keeps_published_posts_only():
    xml = ('<rss version="2.0" xmlns:wp="http://wordpress.org/export/1.2/" '
           'xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
           '<link>https://ex.com</link>'
           '<item><title>Post</title><link>https://ex.com/p</link><wp:post_type>post'
           '</wp:post_type><wp:status>publish</wp:status>'
           '<content:encoded>&lt;p&gt;Words.&lt;/p&gt;</content:encoded></item>'
           '<item><title>About</title><wp:post_type>page</wp:post_type></item>'
           '<item><title>Draft</title><wp:post_type>post</wp:post_type>'
           '<wp:status>draft</wp:status></item></channel></rss>')
    _, items, notes = vi.feed_items(xml, 'export.xml')
    assert [i.title for i in items] == ['Post'] and '2 item(s)' in notes[0]


def test_not_a_feed():
    with pytest.raises(vi.VoiceImportError, match='neither an RSS nor an Atom'):
        vi.feed_items('<html><body/></html>', 'x.xml')
    with pytest.raises(vi.VoiceImportError, match='not well-formed'):
        vi.feed_items('<rss><channel>', 'x.xml')


# ============================================================================
# Reading sources
# ============================================================================

def test_read_a_folder_of_local_files(repo):
    r = vi.read_sources(repo, [os.path.join(FIX, 'posts')], fetch=_no_network)
    assert r.errors == [] and r.warnings == []
    assert sorted((p.title, p.kind) for p in r.pieces) == [
        ('A link worth reading', 'link'), ('Notes on tools', 'essay'),
        ('On Walking', 'essay'), ('The Lighthouse Keeper', 'fiction')]
    walk = next(p for p in r.pieces if p.title == 'On Walking')
    assert walk.source == os.path.relpath(os.path.join(FIX, 'posts',
                                                       '2019-03-02-on-walking.md'), repo)


def test_read_a_local_feed_a_link_post_off_site_and_a_cut_summary(repo):
    r = vi.read_sources(repo, [os.path.join(FIX, 'feed.xml')], fetch=_no_network)
    assert [(p.title, p.kind) for p in r.pieces] == [('The Year in Books', 'essay'),
                                                     ("Someone else's great essay", 'link')]
    assert 'bad()' not in r.pieces[0].body
    assert len(r.warnings) == 1 and '--follow-links' in r.warnings[0]


def test_follow_links_fetches_a_cut_summarys_page(repo):
    web = FakeWeb({'https://www.example.com/2023/11/a-cut-summary':
                   ('text/html', '<article><p>The whole post, at last.</p></article>')})
    r = vi.read_sources(repo, [os.path.join(FIX, 'feed.xml')], fetch=web, follow_links=True)
    assert web.asked == ['https://www.example.com/2023/11/a-cut-summary']
    cut = next(p for p in r.pieces if p.title == 'A cut summary')
    assert cut.body == 'The whole post, at last.' and r.warnings == []


def test_urls_from_a_list_a_page_and_a_feed(repo):
    web = FakeWeb({
        'https://www.example.com/why-i-still-write-letters':
            ('text/html; charset=utf-8', _read('page.html')),
        'https://www.example.com/feed.xml': ('application/rss+xml', _read('feed.xml')),
    })
    r = vi.read_sources(repo, [os.path.join(FIX, 'urls.txt')], fetch=web)
    assert web.asked == ['https://www.example.com/why-i-still-write-letters',
                         'https://www.example.com/feed.xml']
    assert [p.title for p in r.pieces] == ['Why I Still Write Letters', 'The Year in Books',
                                           "Someone else's great essay"]
    assert r.pieces[0].source == 'https://www.example.com/why-i-still-write-letters'


def test_sources_that_cant_be_read_are_errors(repo, tmp_path):
    bad = tmp_path / 'latin1.md'
    bad.write_bytes(b'Caf\xe9 society.\n')
    web = FakeWeb({})
    r = vi.read_sources(repo, [str(bad), 'https://example.com/gone', 'ftp://x/y',
                               str(tmp_path / 'missing'), os.path.join(FIX, 'entities.xml')],
                        fetch=web)
    assert len(r.errors) == 5 and r.pieces == []
    assert "isn't UTF-8" in r.errors[0] and '404' in r.errors[1]
    assert 'not a folder, a file or an http(s) URL' in r.errors[2]


def test_a_page_with_no_prose_is_a_warning(repo):
    web = FakeWeb({'https://e.com/empty': ('text/html', '<nav>Only a menu</nav>')})
    r = vi.read_sources(repo, ['https://e.com/empty'], fetch=web)
    assert r.pieces == [] and 'no prose found' in r.warnings[0]


def test_importing_the_corpus_itself_is_refused(repo):
    r = vi.read_sources(repo, [os.path.join(repo, 'corpus')], fetch=_no_network)
    assert 'the corpus itself' in r.errors[0]


def test_kind_flag_sets_every_kind(repo):
    r = vi.read_sources(repo, [os.path.join(FIX, 'posts')], fetch=_no_network, kind='notes')
    assert {p.kind for p in r.pieces} == {'notes'}


def test_fetch_url_refuses_other_schemes():
    with pytest.raises(vi.VoiceImportError, match='only http and https'):
        vi.fetch_url('file:///etc/passwd')


def test_fetch_url_sends_a_generic_user_agent(monkeypatch):
    import urllib.request
    seen = {}

    class Resp:
        headers = {'Content-Type': 'text/html'}

        def geturl(self):
            return 'https://example.com/x'

        def read(self, n):
            return b'<p>Hi.</p>'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen['headers'] = dict(req.header_items())
        seen['timeout'] = timeout
        return Resp()
    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    got = vi.fetch_url('https://example.com/x')
    assert got.body == b'<p>Hi.</p>'
    assert seen['headers']['User-agent'] == vi.USER_AGENT
    assert '@' not in ' '.join(seen['headers'].values())          # no email, nothing personal
    assert seen['timeout'] == vi.TIMEOUT


def test_fetch_url_refuses_a_body_too_big(monkeypatch):
    import urllib.request

    class Resp:
        headers = {}

        def geturl(self):
            return 'https://example.com/x'

        def read(self, n):
            return b'x' * n

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout: Resp())
    with pytest.raises(vi.VoiceImportError, match='MB; not read'):
        vi.fetch_url('https://example.com/x')


# ============================================================================
# Writing
# ============================================================================

def test_plan_names_files_by_date_and_slug_and_skips_known_sources(repo):
    pieces = [vi.Piece('On Walking', '2019-03-02', 'essay', 'Words.', 'a'),
              vi.Piece('On Walking', '2019-03-02', 'essay', 'Other words.', 'b'),
              vi.Piece('Ça va? / Notes', '', 'notes', 'More.', 'c'),
              vi.Piece('Dup', '', 'essay', 'Same source.', 'a')]
    plan = vi.plan_import(repo, pieces)
    assert [r.file for r in plan.rows] == ['corpus/2019-03-02-on-walking.md',
                                           'corpus/2019-03-02-on-walking-2.md',
                                           'corpus/ca-va-notes.md']
    assert plan.already == ['a']
    vi.write_import(repo, plan)
    assert vi.plan_import(repo, pieces).rows == []
    with open(os.path.join(repo, 'corpus', '2019-03-02-on-walking.md'), encoding='utf-8') as f:
        assert f.read() == '# On Walking\n\nWords.\n'


def test_slug_never_leaves_the_corpus():
    assert vi.slug('../../etc/passwd') == 'etc-passwd'
    assert vi.slug('') == 'piece' and vi.slug('???') == 'piece'
    assert len(vi.slug('word ' * 50)) <= 60


# ============================================================================
# storyforge voice import
# ============================================================================

def test_cmd_import_a_folder_then_again(repo, capsys):
    from storyforge import cmd_voice
    assert cmd_voice.main(['import', os.path.join(FIX, 'posts'), '--dir', repo]) == 0
    out = capsys.readouterr().out
    assert 'Imported 4 piece(s)' in out and '1 fiction' in out and '1 link' in out
    assert 'filed as essays' in out
    assert 'Corpus: 4 piece(s)' in out
    assert 'WARNING: the pieces that count hold 0 words' in out   # all short; the link is out
    rows = vr.read_index(repo)
    assert [r.title for r in rows] == ['On Walking', 'A link worth reading',
                                       'The Lighthouse Keeper', 'Notes on tools']
    for r in rows:
        assert os.path.isfile(os.path.join(repo, r.file))
    assert cmd_voice.main(['import', os.path.join(FIX, 'posts'), '--dir', repo]) == 0
    assert 'Imported 0 piece(s); 4 already in the corpus, skipped' in capsys.readouterr().out
    assert len(vr.read_index(repo)) == 4


def test_cmd_import_counts_by_voice_yaml(repo, capsys):
    from storyforge import cmd_voice
    with open(os.path.join(repo, 'voice.yaml'), 'w', encoding='utf-8') as f:
        f.write('author: T\nkinds:\n  - essay\nmin_words: 100\n')
    assert cmd_voice.main(['import', os.path.join(FIX, 'posts'), '--dir', repo]) == 0
    out = capsys.readouterr().out
    assert '1 count toward the fingerprint' in out                 # On Walking
    assert 'not counted: 1 a fiction piece' in out and '1 a link piece' in out


def test_cmd_import_dry_run_writes_nothing(repo, capsys):
    from storyforge import cmd_voice
    before = sorted(os.listdir(os.path.join(repo, 'corpus')))
    assert cmd_voice.main(['import', os.path.join(FIX, 'posts'), '--dir', repo,
                           '--dry-run']) == 0
    out = capsys.readouterr().out
    assert 'Would import 4 piece(s)' in out and 'Dry run: nothing written.' in out
    assert sorted(os.listdir(os.path.join(repo, 'corpus'))) == before
    assert vr.read_index(repo) == []


def test_cmd_import_errors_exit_1_after_importing_the_rest(repo, capsys, monkeypatch):
    from storyforge import cmd_voice
    monkeypatch.setattr(vi, 'fetch_url', FakeWeb({}))
    assert cmd_voice.main(['import', os.path.join(FIX, 'posts', 'the-lighthouse-keeper.md'),
                           'https://example.com/gone', '--dir', repo]) == 1
    out = capsys.readouterr().out
    assert 'Imported 1 piece(s)' in out and '404' in out
    assert "1 source(s) above weren't imported" in out
    assert len(vr.read_index(repo)) == 1


def test_cmd_import_needs_a_voice_repo(tmp_path, capsys):
    from storyforge import cmd_voice
    assert cmd_voice.main(['import', FIX, '--dir', str(tmp_path)]) == 1
    assert 'voice init' in capsys.readouterr().out
