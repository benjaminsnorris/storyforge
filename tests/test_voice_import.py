"""`storyforge voice import` (#652, plan B1): `storyforge.voice_import` on
local fixtures, with fetching faked (no network)."""

import os
import shutil

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
    assert (p.title, p.date, p.kind, p.kind_from) == ('On Walking', '2019-03-02', 'essay', 'said')
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
    assert p.kind_from == 'guessed' and p.kind == 'essay'


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
        ('On Rain', '2017-04-02', ('essay',)), ('A short story', '', ('story',))]
    # (the story gives only <updated>: when it was changed, not published, so no date)
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
              vi.Piece('On walking!', '2019-03-02', 'essay', 'Other words.', 'b'),
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


# ============================================================================
# Review fixes (#669)
# ============================================================================

@pytest.mark.parametrize('body_attrs, article_attrs', [
    ('class="single-post has-sidebar"', ''),
    ('', 'class="post category-social-media tag-ads"'),
    ('id="menu-open" class="sharing-on"', 'class="post type-post status-publish"'),
])
def test_a_wordpress_body_or_article_class_never_skips_the_page(body_attrs, article_attrs):
    """CR-1: taxonomy and layout classes on <body> or <article> don't drop
    the page; a real sidebar inside it still goes."""
    page = vi.html_page(f'<html><body {body_attrs}><article {article_attrs}>'
                        f'<p>The author\'s own words.</p>'
                        f'<div class="sidebar">Side stuff</div></article></body></html>')
    assert page.body == "The author's own words."


def test_a_doctype_pushed_down_by_comments_is_still_refused():
    """CR-2: the refusal asks the parser, not the first 20,000 characters."""
    xml = ('<?xml version="1.0"?><!--' + 'x' * 25000 + '-->'
           '<!DOCTYPE rss [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
           '<rss><channel><link>https://e.com</link><item><title>&b;</title>'
           '<description>t</description></item></channel></rss>')
    with pytest.raises(vi.VoiceImportError, match='DOCTYPE or an entity'):
        vi.feed_items(xml, 'padded.xml')


def test_follow_links_never_fetches_an_off_site_cut_summary(repo):
    """CR-3: a cut link post's page is someone else's article: it isn't
    fetched or imported (even with --kind essay), and the WARNING says why."""
    xml = ('<rss version="2.0"><channel><link>https://me.com/</link>'
           '<item><title>Theirs</title><link>https://other.net/their-article</link>'
           '<description>Read this, it opens with [&#8230;]</description></item>'
           '<item><title>Mine</title><link>https://www.me.com/mine</link>'
           '<description>My post starts here [&#8230;]</description></item>'
           '</channel></rss>')
    web = FakeWeb({'https://www.me.com/mine': ('text/html', '<article><p>All mine.</p></article>'),
                   'https://other.net/their-article':
                       ('text/html', '<article><p>Not the author.</p></article>')})
    feed = os.path.join(repo, '..', 'feed.xml')
    with open(feed, 'w', encoding='utf-8') as f:
        f.write(xml)
    r = vi.read_sources(repo, [feed], fetch=web, follow_links=True, kind='essay')
    assert web.asked == ['https://www.me.com/mine']
    assert [(p.title, p.body) for p in r.pieces] == [('Mine', 'All mine.')]
    assert any('off me.com' in w and 'Theirs' in w for w in r.warnings)


def test_a_feed_in_its_declared_encoding_and_one_that_cant_be_decoded(repo):
    """CR-4: the XML declaration's or <meta>'s charset is used when the
    header gives none; bytes no declared charset decodes are an ERROR, not
    replacement characters."""
    latin = ('<?xml version="1.0" encoding="ISO-8859-1"?><rss version="2.0"><channel>'
             '<link>https://e.com/</link><item><title>Caf\xe9</title><link>https://e.com/c</link>'
             '<content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">'
             '&lt;p&gt;Caf\xe9 society, at length.&lt;/p&gt;</content:encoded></item>'
             '</channel></rss>').encode('latin-1')
    meta = '<meta charset="windows-1252"><article><p>Na\xefve r\xe9sum\xe9.</p></article>'
    bad = b'<article><p>Caf\xe9</p></article>'

    def fetch(url):
        return {'https://e.com/feed': vi.Fetched(url, 'text/xml', latin),
                'https://e.com/meta': vi.Fetched(url, 'text/html', meta.encode('cp1252')),
                'https://e.com/bad': vi.Fetched(url, 'text/html', bad)}[url]
    r = vi.read_sources(repo, ['https://e.com/feed', 'https://e.com/meta', 'https://e.com/bad'],
                        fetch=fetch)
    assert [p.title for p in r.pieces][0] == 'Café'
    assert r.pieces[0].body == 'Café society, at length.'
    assert r.pieces[1].body == 'Naïve résumé.'
    assert len(r.errors) == 1 and 'https://e.com/bad' in r.errors[0]
    assert 'encoding' in r.errors[0]
    assert all('\ufffd' not in p.body for p in r.pieces)


def test_the_same_post_from_a_folder_then_its_feed_is_skipped(repo, capsys):
    """SF-1: a piece already in the corpus under another source (a folder,
    then the blog's feed) isn't imported twice; the summary names it."""
    from storyforge import cmd_voice
    posts = os.path.join(repo, '..', 'blog')
    os.makedirs(posts)
    with open(os.path.join(posts, '2023-12-30-the-year-in-books.md'), 'w', encoding='utf-8') as f:
        f.write('---\ntitle: The Year in Books\ndate: 2023-12-30\n---\n'
                'I read *fewer* books this year than last, and liked more of them.\n\n'
                'The best was a slim novel about a ferryman, which I finished in a single '
                'afternoon and then started again.\n')
    assert cmd_voice.main(['import', posts, '--dir', repo]) == 0
    capsys.readouterr()
    assert cmd_voice.main(['import', os.path.join(FIX, 'feed.xml'), '--dir', repo]) == 0
    out = capsys.readouterr().out
    assert 'Imported 1 piece(s)' in out                     # the link post only
    assert '1 already in the corpus under another source' in out
    assert 'corpus/2023-12-30-the-year-in-books.md <- https://www.example.com/2023/12/' in out
    assert [r.title for r in vr.read_index(repo)] == ['The Year in Books',
                                                      "Someone else's great essay"]


def test_the_same_title_and_date_in_one_import_is_one_piece(repo):
    """SF-1: a static-site build folder with both the page and the feed."""
    pieces = [vi.Piece('On Walking', '2019-03-02', 'essay', 'From the page.', 'site/on-walking.html'),
              vi.Piece('On Walking', '2019-03-02', 'essay', 'From the feed.', 'https://e.com/w')]
    plan = vi.plan_import(repo, pieces)
    assert len(plan.rows) == 1 and len(plan.same_piece) == 1


@pytest.mark.parametrize('stored, again', [
    ('https://www.example.com/post/', 'http://example.com/post'),
    ('notes  draft.md', 'notes draft.md'),
    ('a|b.md', 'a|b.md'),
])
def test_a_source_matches_its_index_row_as_stored(repo, stored, again):
    """SF-6/TD-6: sources compare as the index stores them (csv_safe), and
    URLs without scheme, www or a trailing slash."""
    vi.write_import(repo, vi.plan_import(repo, [vi.Piece('One', '', 'essay', 'Words here.', stored)]))
    plan = vi.plan_import(repo, [vi.Piece('Other', '', 'essay', 'New words.', again)])
    assert plan.rows == [] and plan.already == [again]


def test_a_linkless_feed_item_keeps_its_source_when_the_feed_grows(repo):
    """T6/TD-5: an item with no link, guid or id is keyed by its content,
    not its position, so a new item at the top isn't skipped as known."""
    def feed(*titles):
        items = ''.join(f'<item><title>{t}</title><content:encoded>&lt;p&gt;{t} body words.'
                        f'&lt;/p&gt;</content:encoded></item>' for t in titles)
        return ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
                f'<channel><link>https://e.com/</link>{items}</channel></rss>')
    path = os.path.join(repo, '..', 'export.xml')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(feed('Old'))
    vi.write_import(repo, vi.plan_import(repo, vi.read_sources(repo, [path]).pieces))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(feed('New', 'Old'))
    plan = vi.plan_import(repo, vi.read_sources(repo, [path]).pieces)
    assert [r.title for r in plan.rows] == ['New'] and len(plan.already) == 1


def test_an_atom_entry_without_a_link_takes_its_id():
    xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title>'
           '<id>tag:e.com,2020:1</id><content type="html">x</content></entry></feed>')
    _, items, _ = vi.feed_items(xml, 'a.xml')
    assert items[0].link == 'tag:e.com,2020:1'


def test_link_posts_guessed_from_the_host_are_named(repo, capsys):
    """SF-5: an item filed as a link only because it links off the feed's
    site is reported on its own line, not as if it said so."""
    from storyforge import cmd_voice
    r = vi.read_sources(repo, [os.path.join(FIX, 'feed.xml')], fetch=_no_network)
    other = next(p for p in r.pieces if p.title == "Someone else's great essay")
    assert other.kind == 'link' and other.kind_from == vi.KIND_OFF_SITE
    assert cmd_voice.main(['import', os.path.join(FIX, 'feed.xml'), '--dir', repo]) == 0
    out = capsys.readouterr().out
    assert "1 filed as link posts only because they link off the feed's own site" in out
    assert "Someone else's great essay" in out


def test_an_atom_related_link_said_it_is_a_link_post():
    xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><link href="https://me.com/"/>'
           '<entry><title>See this</title><link href="https://me.com/see"/>'
           '<link rel="related" href="https://them.net/x"/>'
           '<content type="html">&lt;p&gt;Worth a look.&lt;/p&gt;</content></entry></feed>')
    _, items, _ = vi.feed_items(xml, 'a.xml')
    assert items[0].related == 'https://them.net/x'


def _feed_file(repo, xml, name='feed.xml'):
    path = os.path.join(repo, '..', name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(xml)
    return path


EXCERPT_FEED = ('<rss version="2.0"><channel><link>https://me.com/</link>'
                '<item><title>Excerpt</title><link>https://me.com/excerpt</link>'
                '<description>The opening paragraph of a longer post.</description></item>'
                '</channel></rss>')


def test_a_summary_without_a_cut_marker_is_named(repo):
    """SF-2: a summary-only item with no marker is imported, but named, so
    an excerpt-only feed isn't taken for whole posts in silence."""
    r = vi.read_sources(repo, [_feed_file(repo, EXCERPT_FEED)], fetch=_no_network)
    assert [p.title for p in r.pieces] == ['Excerpt']
    assert len(r.warnings) == 1 and "from the feed's summary alone" in r.warnings[0]
    assert 'Excerpt' in r.warnings[0] and '--follow-links' in r.warnings[0]


def test_follow_links_fetches_every_summary_only_post_on_the_site(repo):
    """SF-2: with --follow-links a summary-only item's page is fetched even
    without a cut marker, so the whole post is what's imported."""
    web = FakeWeb({'https://me.com/excerpt':
                   ('text/html', '<article><p>The whole longer post.</p></article>')})
    r = vi.read_sources(repo, [_feed_file(repo, EXCERPT_FEED)], fetch=web, follow_links=True)
    assert [p.body for p in r.pieces] == ['The whole longer post.'] and r.warnings == []


def test_follow_links_a_page_that_cant_be_fetched_is_an_error(repo, capsys, monkeypatch):
    """T4: a cut summary whose page fails is an ERROR (exit 1), never dropped."""
    from storyforge import cmd_voice
    r = vi.read_sources(repo, [os.path.join(FIX, 'feed.xml')], fetch=FakeWeb({}),
                        follow_links=True)
    assert len(r.errors) == 1 and '404' in r.errors[0]
    assert 'A cut summary' not in [p.title for p in r.pieces]
    monkeypatch.setattr(vi, 'fetch_url', FakeWeb({}))
    assert cmd_voice.main(['import', os.path.join(FIX, 'feed.xml'), '--follow-links',
                           '--dir', repo]) == 1
    assert "1 source(s) above weren't imported" in capsys.readouterr().out


def test_files_a_folder_doesnt_import_are_named(repo, tmp_path):
    """SF-3: a folder's .txt, .docx and the like are counted and named."""
    d = tmp_path / 'posts'
    shutil.copytree(os.path.join(FIX, 'posts'), d)
    (d / 'old-post.txt').write_text('An old post.\n', encoding='utf-8')
    (d / 'essay.docx').write_bytes(b'PK')
    (d / '.DS_Store').write_bytes(b'x')
    r = vi.read_sources(repo, [str(d)], fetch=_no_network)
    assert len(r.pieces) == 4
    assert len(r.warnings) == 1
    w = r.warnings[0]
    assert "2 file(s) that aren't Markdown, HTML or a feed" in w
    assert '1 .docx, 1 .txt' in w and 'essay.docx; old-post.txt' in w and 'DS_Store' not in w


def test_a_failed_write_says_so_and_leaves_no_orphan(repo, capsys, monkeypatch):
    """SF-4: a write that fails part-way raises, removes the files this
    import wrote, and nothing claims "Imported"."""
    from storyforge import cmd_voice
    from storyforge import voiceprint_proposals as vpp
    real, calls = vpp._write_text, []

    def flaky(path, text):
        calls.append(path)
        if len(calls) == 3:
            raise OSError(28, 'No space left on device')
        real(path, text)
    monkeypatch.setattr(vpp, '_write_text', flaky)
    assert cmd_voice.main(['import', os.path.join(FIX, 'posts'), '--dir', repo]) == 1
    out = capsys.readouterr().out
    assert 'Imported' not in out
    assert "the import couldn't be written" in out and 'No space left' in out
    assert sorted(os.listdir(os.path.join(repo, 'corpus'))) == ['index.csv']
    assert vr.read_index(repo) == []


def test_a_corpus_file_the_index_doesnt_name_is_a_warning(repo, capsys):
    """SF-4: a stray corpus file (from an older interrupted import, or by
    hand) is named on import and on fingerprint."""
    from storyforge import cmd_voice
    with open(os.path.join(repo, 'corpus', 'orphan.md'), 'w', encoding='utf-8') as f:
        f.write('# Orphan\n\nWords.\n')
    assert vr.unindexed_files(repo) == ['corpus/orphan.md']
    cmd_voice.main(['import', os.path.join(FIX, 'posts'), '--dir', repo])
    assert "1 file(s) in corpus/ that corpus/index.csv doesn't name" in capsys.readouterr().out
    cmd_voice.main(['fingerprint', '--dir', repo])
    assert 'corpus/orphan.md' in capsys.readouterr().out


def test_dry_run_shows_what_the_corpus_would_hold(repo, capsys):
    """SF-7/T7/C7: a dry run judges the planned pieces as an import would."""
    from storyforge import cmd_voice
    with open(os.path.join(repo, 'voice.yaml'), 'w', encoding='utf-8') as f:
        f.write('author: T\nkinds:\n  - essay\nmin_words: 100\n')
    assert cmd_voice.main(['import', os.path.join(FIX, 'posts'), '--dir', repo,
                           '--dry-run']) == 0
    out = capsys.readouterr().out
    assert 'After the import, the corpus: 4 piece(s)' in out
    assert '1 count toward the fingerprint' in out and 'not counted: 1 a fiction piece' in out
    assert 'WARNING: the pieces that count hold' in out
    assert vr.read_index(repo) == []


def test_hugo_toml_front_matter():
    """CR-6: `+++` front matter gives the title, date and kind, and isn't
    counted as prose."""
    p = vi.markdown_piece('+++\ntitle = "On Rivers"\ndate = 2020-06-01T09:00:00Z\n'
                          'tags = ["essays", "water"]\n[params]\nkind = "note"\n+++\n'
                          'The river was high that June.\n', 'src')
    assert (p.title, p.date, p.kind, p.kind_from) == ('On Rivers', '2020-06-01', 'essay', 'said')
    assert p.body == 'The river was high that June.'
