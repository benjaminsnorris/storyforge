"""`storyforge voice import`: an author's own writing into their voice repo's
corpus (#652, plan B1).

Sources (`read_sources`), any mix of them:
- a folder: its Markdown (`.md`, `.markdown`) and HTML (`.html`, `.htm`)
  files, and any RSS or Atom file in it (`.xml`, `.rss`, `.atom`: a feed, or
  a blog's export, as WordPress exports RSS), recursively, hidden ones left
  out;
- one such file;
- a `.txt` file listing URLs, one a line (`#` comments);
- a URL: a page, or a feed (told by its content type or its first tag).

Each piece keeps its title, date (`YYYY-MM-DD`, `YYYY-MM` or `YYYY` as
given by its front matter, feed, page metadata or a dated file name, a real
date (`voice_repo.valid_date`), else blank: never guessed, and never an
Atom `<updated>`, which is when it was changed), kind (`voice_repo.KINDS`)
and source. The kind comes from what the piece says about itself: front
matter (YAML `---` or Hugo's TOML `+++`: `kind`, `type`, `layout`,
`categories`, `tags`; a `link`, `link_url` or `external_url` key makes it a
link post), a feed item's categories, or a feed item that links off the
feed's own site (a link post, recorded as `KIND_OFF_SITE` and named, since
a moved blog does this too). A tag or a feed category (feeds carry a
blog's tags as categories) never makes a piece fiction by saying `story`
or `stories`: a post tagged `story` tells one about the author's week
(`FORM_ONLY_WORDS`, #680). `--kind` sets one kind for the whole import.
With no sign, a piece is filed as an essay and the summary counts how many
were, so the author can correct `corpus/index.csv`.

Boilerplate goes: HTML is parsed with the standard library's `html.parser`,
the page's `<article>` (or `<main>`, or the body) kept and its scripts,
styles, navigation, headers, footers, asides, forms, figures, code blocks
and block quotes dropped; Markdown loses its front matter, code blocks,
block quotes, tables, images, HTML and link syntax. Block quotes go because
they are someone else's words, and the fingerprint measures the author's.
What's kept is stored as Markdown: `# title`, then one paragraph a block.

A feed item with only a cut summary (it ends in "…" or "read more") isn't
imported unless `--follow-links` fetches its page, and only a page on the
feed's own site is fetched: a cut link post's page is someone else's
writing. An item with only a summary and no cut marker is imported and
named (it may be an excerpt); `--follow-links` fetches its page too. A
folder's files that aren't Markdown, HTML or a feed are named.

Fetched content is untrusted data: only text is taken from it, never run;
a page or feed over `MAX_BYTES` is refused; only http and https URLs are
fetched; a feed declaring a DOCTYPE or an entity anywhere is refused before
it is parsed (no entity expansion); text is decoded in the header's
charset, else the one the document declares, else UTF-8, and is an ERROR
when none decodes it. Fetching goes through one injectable function
(`fetch(url) -> Fetched`), so the tests use none; the real one sends a
generic User-Agent and nothing about the user.

Nothing is replaced: a piece whose source is already in the index
(`source_key`), or that is already there under another source (the same
words, or the same title and date: a folder, then the blog's feed), is
skipped and named. Title and date match only when the title isn't used on
other dates (a default like "Microblog post") and the two copies aren't
files in one folder, which never holds one post twice (#680). A source that can't be read or fetched is an ERROR, and
the command exits 1 after importing the rest; a write that fails removes
what it wrote.
"""

from __future__ import annotations

import email.utils
import hashlib
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Iterable
from xml.parsers import expat

from storyforge import voice_repo as vr

#: a page or feed bigger than this isn't read
MAX_BYTES = 10 * 1024 * 1024
#: seconds to wait for a URL
TIMEOUT = 30
#: the User-Agent sent: generic, nothing about the user
USER_AGENT = 'Mozilla/5.0 (compatible; storyforge)'
MARKDOWN_EXT = ('.md', '.markdown')
HTML_EXT = ('.html', '.htm')
FEED_EXT = ('.xml', '.rss', '.atom')
URL_LIST_EXT = ('.txt',)

#: words a piece may say about its kind, and the kind each means
KIND_WORDS = {
    'essay': 'essay', 'essays': 'essay', 'article': 'essay', 'articles': 'essay',
    'longform': 'essay', 'long-form': 'essay',
    'fiction': 'fiction', 'story': 'fiction', 'stories': 'fiction',
    'short-story': 'fiction', 'short-stories': 'fiction',
    'note': 'notes', 'notes': 'notes', 'micro': 'notes', 'microblog': 'notes',
    'status': 'notes', 'aside': 'notes', 'asides': 'notes',
    'link': 'link', 'links': 'link', 'linked': 'link', 'link-post': 'link',
    'linkpost': 'link', 'bookmark': 'link', 'bookmarks': 'link',
}
#: words that name a kind only in a front-matter field about the piece's
#: form (kind, type, layout, post_type, category, categories), never as a
#: tag or a feed category (a feed carries the blog's tags as categories):
#: a post tagged `story` tells a story about the author's week (#680)
FORM_ONLY_WORDS = frozenset({'story', 'stories'})
#: front-matter keys that make a piece a link post
LINK_KEYS = ('link', 'link_url', 'external_url', 'linkurl')
#: how a truncated feed summary ends
_TRUNCATED_RE = re.compile(r'(?:…|\.\.\.|\[…\]|\[\.\.\.\]|read more|continue reading'
                           r'|read the rest)[\s\W]*$', re.IGNORECASE)


class VoiceImportError(Exception):
    """A source that can't be read, fetched or parsed; the message says why."""


@dataclass(frozen=True)
class Fetched:
    """What a URL returned: its final URL, content type and body."""
    url: str
    content_type: str
    body: bytes


Fetch = Callable[[str], Fetched]


#: how a piece's kind was found (`Piece.kind_from`)
KIND_SAID = 'said'          # the piece said so (front matter, categories), or --kind
KIND_GUESSED = 'guessed'    # nothing said: filed as an essay
KIND_OFF_SITE = 'off-site'  # a feed item linking off the feed's site: filed as a link


@dataclass
class Piece:
    """One piece of writing, read and cleaned: its Markdown body has no
    title heading (`markdown` adds it). `kind_from` says how its kind was
    found, so the import can name the guesses."""
    title: str
    date: str
    kind: str
    body: str
    source: str
    kind_from: str = KIND_SAID
    #: its tags or feed categories said `story` (`FORM_ONLY_WORDS`), which
    #: wasn't taken as fiction: the import names these (#680)
    story_tag: bool = False

    def markdown(self) -> str:
        head = f'# {self.title}\n\n' if self.title else ''
        return f'{head}{self.body.strip()}\n'


@dataclass
class Report:
    """What reading the sources found: the pieces, and the problems
    (ERROR lines: a source not imported) and notes (WARNING lines)."""
    pieces: list[Piece] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ============================================================================
# Fetching
# ============================================================================

def is_url(s: str) -> bool:
    return s.lower().startswith(('http://', 'https://'))


def fetch_url(url: str) -> Fetched:
    """GET `url` (http or https only) with a generic User-Agent; refuse a
    body over `MAX_BYTES` or a redirect off http(s). Raises VoiceImportError."""
    import urllib.request
    if not is_url(url):
        raise VoiceImportError(f'{url}: only http and https URLs are fetched')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT,
                                               'Accept': 'text/html, application/xml, '
                                                         'application/rss+xml, '
                                                         'application/atom+xml, */*'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            final = resp.geturl()
            if not is_url(final):
                raise VoiceImportError(f'{url} redirected to {final}, which isn\'t http(s)')
            body = resp.read(MAX_BYTES + 1)
            ctype = resp.headers.get('Content-Type', '')
    except VoiceImportError:
        raise
    except Exception as e:   # urllib's errors, timeouts, bad URLs
        raise VoiceImportError(f'{url} couldn\'t be fetched ({e.__class__.__name__}: {e})') from e
    if len(body) > MAX_BYTES:
        raise VoiceImportError(f'{url} is over {MAX_BYTES // (1024 * 1024)} MB; not read')
    return Fetched(final, ctype, body)


_DECLARED_RE = (re.compile(rb'<\?xml[^>]*?encoding=["\']([\w.:-]+)', re.IGNORECASE),
                re.compile(rb'<meta[^>]+?charset=["\']?([\w.:-]+)', re.IGNORECASE))


def _decode(body: bytes, content_type: str = '', where: str = '') -> str:
    """`body` as text in the charset the HTTP header names, else the one the
    document declares (its XML declaration or `<meta charset>`), else UTF-8.
    Raises VoiceImportError when none of them decodes it: replacing bytes
    would put wrong characters in the corpus without a word (a local file
    that isn't UTF-8 is an ERROR the same way)."""
    tried = []
    m = re.search(r'charset=["\']?([\w.:-]+)', content_type or '', re.IGNORECASE)
    if m:
        tried.append(m.group(1))
    head = body[:4096]
    for rx in _DECLARED_RE:
        d = rx.search(head)
        if d:
            tried.append(d.group(1).decode('ascii'))
            break
    tried.append('utf-8')
    for enc in tried:
        try:
            return body.decode(enc).lstrip('\ufeff')
        except (LookupError, UnicodeDecodeError):
            continue
    raise VoiceImportError(f'{where or "the page"} isn\'t in the encoding it declares or UTF-8 '
                           f'(tried {", ".join(dict.fromkeys(tried))}); not imported')


# ============================================================================
# Cleaning
# ============================================================================

def _norm_date(raw: str) -> str:
    """`YYYY-MM-DD` from an ISO date or an RFC 822 one (a feed's pubDate),
    or '' when it can't be read."""
    raw = (raw or '').strip().strip('"\'')
    if not raw:
        return ''
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', raw)
    if m:
        date = '-'.join(m.groups())
        return date if vr.valid_date(date) else ''
    m = re.match(r'^(\d{4})(?:-(\d{2}))?$', raw)
    if m:
        return raw if vr.valid_date(raw) else ''
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return ''
    return dt.strftime('%Y-%m-%d') if dt else ''


def kind_of(words: list[str]) -> str:
    """The kind the first of `words` that names one means, or ''."""
    for w in words:
        k = KIND_WORDS.get(w.strip().lower().replace(' ', '-').replace('_', '-'))
        if k:
            return k
    return ''


def _collapse(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


#: tags whose whole content is boilerplate, or not the author's prose
_SKIP_TAGS = frozenset({'script', 'style', 'noscript', 'template', 'svg', 'math', 'nav',
                        'footer', 'header', 'aside', 'form', 'button', 'select', 'iframe',
                        'object', 'video', 'audio', 'canvas', 'figure', 'pre', 'blockquote',
                        'dialog', 'head'})
#: roles that mark boilerplate
_SKIP_ROLES = frozenset({'navigation', 'banner', 'contentinfo', 'complementary', 'search',
                         'menu', 'menubar', 'dialog'})
#: elements that hold the page's content: their class and id never skip them
#: (WordPress puts layout and taxonomy classes on <body> and <article>)
_CONTAINER_TAGS = frozenset({'html', 'body', 'article', 'main'})
#: class words that describe the piece, not a part of the page
#: (`category-social-media`, `tag-ads`, `has-sidebar`, `single-post`)
_TAXONOMY_CLASS_RE = re.compile(r'^(?:category|tag|has|post-format|format|single|page|postid'
                                r'|type|status|author)-', re.IGNORECASE)
#: class or id words that mark boilerplate
_SKIP_CLASS_RE = re.compile(r'(?:^|[\s_-])(?:comments?|share|sharing|social|related|sidebar'
                            r'|newsletter|subscribe|breadcrumbs?|pagination|navigation|menu'
                            r'|cookie|advert|ads)(?:$|[\s_-])', re.IGNORECASE)
_VOID_TAGS = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
                        'meta', 'param', 'source', 'track', 'wbr'})
_BLOCK_TAGS = frozenset({'p', 'div', 'section', 'article', 'main', 'li', 'ul', 'ol', 'dl',
                         'dt', 'dd', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'tr',
                         'td', 'th', 'body', 'br', 'hr', 'figcaption', 'details',
                         'summary'})
_HEADINGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
_CONTENT_CLASS_RE = re.compile(r'(?:^|\s)(?:e-content|entry-content|post-content|post-body'
                               r'|article-body|article-content)(?:$|\s)', re.IGNORECASE)


class _Extractor(HTMLParser):
    """The text of an HTML page as paragraphs, boilerplate dropped, each
    marked as inside the page's first `<article>` (or content element) and
    inside `<main>` or not; and its title, headline, metadata and first
    `<time datetime>`."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip: list[str] = []
        self.buf: list[str] = []
        self.heading = ''
        self.blocks: list[tuple[str, bool, bool]] = []   # (text, in_article, in_main)
        self.content_tag = ''
        self.content_depth = 0
        self.content_done = False
        self.main = 0
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.time = ''
        self.h1 = ''
        self.h1_buf: list[str] | None = None

    def _flush(self):
        text = _collapse(''.join(self.buf))
        self.buf = []
        if text:
            if self.heading:
                text = f'{"#" * int(self.heading[1])} {text}'
            self.blocks.append((text, self.content_depth > 0, self.main > 0))

    @staticmethod
    def _skips(tag, a) -> bool:
        if tag in _SKIP_TAGS:
            return True
        if (a.get('role') or '').lower() in _SKIP_ROLES:
            return True
        if a.get('aria-hidden') == 'true' or 'hidden' in a:
            return True
        if tag in _CONTAINER_TAGS or _CONTENT_CLASS_RE.search(a.get('class') or ''):
            return False
        words = [w for w in f'{a.get("class") or ""} {a.get("id") or ""}'.split()
                 if not _TAXONOMY_CLASS_RE.match(w)]
        return bool(_SKIP_CLASS_RE.search(' '.join(words)))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            key = (a.get('property') or a.get('name') or a.get('itemprop') or '').lower()
            if key and a.get('content') and key not in self.meta:
                self.meta[key] = a['content']
            return
        if tag == 'title' and not self.title_parts and self.skip in ([], ['head']):
            self.in_title = True
            return
        # the date and the headline, even inside a skipped <header>
        if tag == 'time' and not self.time and a.get('datetime'):
            self.time = a['datetime']
        if tag == 'h1' and not self.h1 and self.h1_buf is None and \
                not set(self.skip) - {'header', 'head'}:
            self.h1_buf = []
        if self.skip:
            if tag not in _VOID_TAGS:
                self.skip.append(tag)
            return
        if tag not in _VOID_TAGS and self._skips(tag, a):
            self._flush()
            self.skip.append(tag)
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _HEADINGS:
            self.heading = tag
        if self.content_depth and tag == self.content_tag:
            self.content_depth += 1
        elif not self.content_depth and not self.content_done and (
                tag == 'article' or _CONTENT_CLASS_RE.search(a.get('class') or '')):
            self.content_tag, self.content_depth = tag, 1
        if tag == 'main' or (a.get('role') or '').lower() == 'main':
            self.main += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'title' and self.in_title:
            self.in_title = False
            return
        if tag == 'h1' and self.h1_buf is not None:
            self.h1 = _collapse(''.join(self.h1_buf))
            self.h1_buf = None
        if self.skip:
            if tag in self.skip:
                while self.skip and self.skip.pop() != tag:
                    pass
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _HEADINGS:
            self.heading = ''
        if self.content_depth and tag == self.content_tag:
            self.content_depth -= 1
            if not self.content_depth:
                self.content_done = True
        if tag == 'main' and self.main:
            self.main -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.h1_buf is not None:
            self.h1_buf.append(data)
        if not self.skip:
            self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


@dataclass(frozen=True)
class Page:
    title: str
    date: str
    body: str


def html_page(html: str) -> Page:
    """An HTML page's title, date and prose (paragraphs as Markdown, the
    page's headline left out of the body)."""
    p = _Extractor()
    p.feed(html)
    p.close()
    for scope in (lambda b: b[1], lambda b: b[2], lambda b: True):
        blocks = [b[0] for b in p.blocks if scope(b)]
        if any(not t.startswith('#') for t in blocks):
            break
    title = _collapse(p.meta.get('og:title') or p.h1 or ''.join(p.title_parts))
    if blocks and blocks[0].lstrip('#').strip() == title:
        blocks = blocks[1:]
    date = _norm_date(p.meta.get('article:published_time') or p.meta.get('datepublished')
                      or p.meta.get('date') or p.meta.get('dc.date') or p.time)
    return Page(title, date, '\n\n'.join(blocks))


_FRONT_RE = re.compile(r'\A---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)', re.DOTALL)
#: Hugo's TOML front matter, between `+++` lines
_TOML_FRONT_RE = re.compile(r'\A\+\+\+[ \t]*\r?\n(.*?)\r?\n\+\+\+[ \t]*(?:\r?\n|\Z)', re.DOTALL)


def _toml_front(block: str) -> dict[str, str | list[str]]:
    """The top-level `key = value` lines of TOML front matter (strings,
    dates, numbers and one-line arrays); a `[table]` ends them."""
    from storyforge.common import parse_yaml_scalar
    meta: dict[str, str | list[str]] = {}
    for line in block.splitlines():
        s = line.strip()
        if s.startswith('['):
            break
        m = re.match(r'^([A-Za-z_][\w-]*)\s*=\s*(.*)$', s)
        if not m:
            continue
        key, raw = m.group(1).lower(), m.group(2).strip()
        if raw.startswith('[') and raw.endswith(']'):
            meta[key] = [parse_yaml_scalar(x) for x in raw[1:-1].split(',') if x.strip()]
        else:
            meta[key] = parse_yaml_scalar(raw)
    return meta


def front_matter(text: str) -> tuple[dict[str, str | list[str]], str]:
    """A Markdown file's front matter, and the text after it: YAML between
    `---` lines (scalars, and lists given as a block or `[a, b]`), or
    Hugo's TOML between `+++` lines (`_toml_front`)."""
    from storyforge.common import parse_yaml_scalar
    toml = _TOML_FRONT_RE.match(text)
    if toml:
        return _toml_front(toml.group(1)), text[toml.end():]
    m = _FRONT_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str | list[str]] = {}
    key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        km = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', line)
        if km:
            key, raw = km.group(1).lower(), km.group(2).strip()
            if raw.startswith('[') and raw.endswith(']'):
                meta[key] = [parse_yaml_scalar(x) for x in raw[1:-1].split(',') if x.strip()]
            elif raw:
                meta[key] = parse_yaml_scalar(raw)
            else:
                meta[key] = []
        elif key and line.strip().startswith('-') and isinstance(meta.get(key), list):
            meta[key].append(parse_yaml_scalar(line.strip()[1:]))   # type: ignore[union-attr]
    return meta, text[m.end():]


def markdown_prose(text: str) -> str:
    """Markdown without what isn't the author's running prose: code blocks,
    block quotes, tables, images, reference-link and footnote definitions,
    HTML (its text kept, scripts and styles dropped), link syntax and
    footnote marks. Headings stay (the fingerprint leaves them out)."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    out, fence = [], None
    for line in text.split('\n'):
        s = line.strip()
        m = re.match(r'^(`{3,}|~{3,})', s)
        # a dropped line leaves a blank one, so the prose either side of it
        # stays two paragraphs
        if fence:
            if m and s.startswith(fence):
                fence = None
            out.append('')
            continue
        if m:
            fence = m.group(1)
            out.append('')
            continue
        if s.startswith('>') or (s.startswith('|') and s.endswith('|')):
            out.append('')
            continue
        if re.match(r'^\[[^\]]+\]:\s', s):          # [ref]: url, [^1]: note
            out.append('')
            continue
        out.append(line)
    text = '\n'.join(out)
    text = re.sub(r'<(script|style)\b.*?</\1\s*>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>\n]+>', '', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'!\[[^\]]*\]\[[^\]]*\]', '', text)
    text = re.sub(r'\[\^[^\]]+\]', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\[[^\]]*\]', r'\1', text)
    text = re.sub(r'^[ \t]*(?:[-*+]|\d+[.)])[ \t]+', '', text, flags=re.MULTILINE)
    import html as _html
    text = _html.unescape(text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    return [x.strip() for x in re.split(r'[,;]', str(v or '')) if x.strip()]


def markdown_piece(text: str, source: str, fallback_title: str = '') -> Piece:
    """A Markdown file as a piece: title, date and kind from its front
    matter, the body cleaned (`markdown_prose`); a leading `# title`
    heading becomes the title."""
    meta, body = front_matter(text)
    body = markdown_prose(body)
    title = str(meta.get('title') or '')
    m = re.match(r'^#\s+(.+)\n*', body)
    if m and (not title or _collapse(m.group(1)) == title):
        title = title or _collapse(m.group(1))
        body = body[m.end():]
    words = []
    for k in ('kind', 'type', 'layout', 'post_type', 'category', 'categories'):
        words += _as_list(meta.get(k))
    tags = _as_list(meta.get('tags'))
    words += [t for t in tags if t.strip().lower() not in FORM_ONLY_WORDS]
    kind = kind_of(words)
    if not kind and any(meta.get(k) for k in LINK_KEYS):
        kind = 'link'
    date = _norm_date(str(meta.get('date') or meta.get('published') or meta.get('pubdate') or ''))
    return Piece(title or fallback_title, date, kind or 'essay', body, source,
                 KIND_SAID if kind else KIND_GUESSED,
                 story_tag=not kind and any(t.strip().lower() in FORM_ONLY_WORDS for t in tags))


def html_piece(html: str, source: str, fallback_title: str = '') -> Piece:
    page = html_page(html)
    return Piece(page.title or fallback_title, page.date, 'essay', page.body, source,
                 KIND_GUESSED)


# ============================================================================
# Feeds
# ============================================================================

_ATOM = '{http://www.w3.org/2005/Atom}'
_CONTENT = '{http://purl.org/rss/1.0/modules/content/}encoded'
_DC_DATE = '{http://purl.org/dc/elements/1.1/}date'
_WP_TYPE = '{http://wordpress.org/export/1.2/}post_type'
_WP_STATUS = '{http://wordpress.org/export/1.2/}status'


def looks_like_feed(text: str) -> bool:
    head = re.sub(r'<\?xml[^>]*\?>|<!--.*?-->', '', text[:2000], flags=re.DOTALL).lstrip()
    return head.startswith(('<rss', '<feed', '<rdf:RDF'))


def _host(url: str) -> str:
    host = urllib.parse.urlparse(url or '').netloc.lower()
    return host[4:] if host.startswith('www.') else host


def _text(el) -> str:
    return (el.text or '').strip() if el is not None else ''


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str
    date: str
    categories: tuple[str, ...]
    html: str
    summary_only: bool
    related: str = ''


def _refuse_dtd(text: str, where: str) -> None:
    """Raise VoiceImportError if the XML declares a DOCTYPE or an entity
    anywhere: the parser itself is asked, so a declaration pushed down by
    comments is still found. A document that isn't well-formed is left for
    `ET` to report."""
    def refuse(*_):
        raise VoiceImportError(f'{where}: the feed declares a DOCTYPE or an entity; not parsed')
    p = expat.ParserCreate()
    p.StartDoctypeDeclHandler = refuse
    p.EntityDeclHandler = refuse
    try:
        p.Parse(text, True)
    except expat.ExpatError:
        pass


def feed_items(xml: str, where: str) -> tuple[str, list[FeedItem], list[str]]:
    """An RSS 2.0 or Atom feed's site link and items, and notes on items
    left out (a WordPress export's pages, drafts and attachments). Raises
    VoiceImportError for a feed with a DOCTYPE or an entity (refused unparsed),
    or one that isn't well-formed XML, RSS or Atom."""
    _refuse_dtd(xml, where)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise VoiceImportError(f'{where}: not well-formed XML ({e})') from e
    items, notes = [], []
    if root.tag == f'{_ATOM}feed':
        site = ''
        for ln in root.findall(f'{_ATOM}link'):
            if ln.get('rel', 'alternate') == 'alternate':
                site = ln.get('href', '')
        for e in root.findall(f'{_ATOM}entry'):
            link = related = ''
            for ln in e.findall(f'{_ATOM}link'):
                rel = ln.get('rel', 'alternate')
                if rel == 'alternate' and not link:
                    link = ln.get('href', '')
                elif rel == 'related' and not related:
                    related = ln.get('href', '')
            content = e.find(f'{_ATOM}content')
            summary = e.find(f'{_ATOM}summary')
            body = content if content is not None else summary
            html = (body.text or '') if body is not None else ''
            if body is not None and body.get('type') == 'xhtml':
                html = ''.join(ET.tostring(c, encoding='unicode') for c in body)
            # <updated> is when it was last changed, not published: never the date
            items.append(FeedItem(
                _text(e.find(f'{_ATOM}title')), link or _text(e.find(f'{_ATOM}id')),
                _norm_date(_text(e.find(f'{_ATOM}published'))),
                tuple(c.get('term', '') for c in e.findall(f'{_ATOM}category')),
                html, content is None, related))
        return site, items, notes
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None:
        raise VoiceImportError(f'{where}: neither an RSS nor an Atom feed (<{root.tag}>)')
    site = _text(channel.find('link'))
    skipped = 0
    for it in channel.findall('item'):
        wp_type = _text(it.find(_WP_TYPE))
        wp_status = _text(it.find(_WP_STATUS))
        if (wp_type and wp_type != 'post') or (wp_status and wp_status != 'publish'):
            skipped += 1
            continue
        content = it.find(_CONTENT)
        desc = it.find('description')
        html = _text(content) if content is not None and _text(content) else _text(desc)
        items.append(FeedItem(
            _text(it.find('title')), _text(it.find('link')) or _text(it.find('guid')),
            _norm_date(_text(it.find('pubDate')) or _text(it.find(_DC_DATE))),
            tuple(_text(c) for c in it.findall('category')),
            html, not (content is not None and _text(content))))
    if skipped:
        notes.append(f'{where}: {skipped} item(s) that aren\'t published posts (pages, '
                     f'drafts, attachments) left out')
    return site, items, notes


def _truncated(item: FeedItem) -> bool:
    if not item.summary_only:
        return False
    tail = html_page(item.html).body[-80:] if item.html else ''
    return not tail or bool(_TRUNCATED_RE.search(tail))


# ============================================================================
# Reading the sources
# ============================================================================

def _piece_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', stem)
    return stem.replace('-', ' ').replace('_', ' ').strip()


def _date_from_name(path: str) -> str:
    m = re.match(r'^(\d{4}-\d{2}-\d{2})', os.path.basename(path))
    return m.group(1) if m and vr.valid_date(m.group(1)) else ''


def _shown(names: list[str], most: int = 5) -> str:
    return '; '.join(names[:most]) + (f' (and {len(names) - most} more)'
                                      if len(names) > most else '')


def _item_key(where: str, item: FeedItem) -> str:
    """A feed item's source when it has no link, guid or id: the feed and a
    hash of the item's title, date and text, so it stays the same when the
    feed grows (a position would shift and skip a new item as known)."""
    digest = hashlib.sha1('\n'.join((item.title, item.date, item.html)).encode('utf-8'))
    return f'{where}#{digest.hexdigest()[:12]}'


class _Reader:
    def __init__(self, voice_dir: str, fetch: Fetch, follow_links: bool, report: Report):
        self.voice_dir = voice_dir
        self.fetch = fetch
        self.follow = follow_links
        self.report = report

    def rel(self, path: str) -> str:
        return os.path.relpath(os.path.abspath(path), self.voice_dir)

    def add(self, piece: Piece):
        if not piece.body.strip() or not vr.prose_words(piece.body):
            self.report.warnings.append(f'{piece.source}: no prose found; not imported')
            return
        self.report.pieces.append(piece)

    # -- local files
    def file(self, path: str):
        ext = os.path.splitext(path)[1].lower()
        src = self.rel(path)
        try:
            with open(path, 'rb') as f:
                raw = f.read(MAX_BYTES + 1)
        except OSError as e:
            self.report.errors.append(f'{src} can\'t be read ({e})')
            return
        if len(raw) > MAX_BYTES:
            self.report.errors.append(f'{src} is over {MAX_BYTES // (1024 * 1024)} MB; not read')
            return
        try:
            text = raw.decode('utf-8').lstrip('﻿')
        except UnicodeDecodeError as e:
            self.report.errors.append(f'{src} isn\'t UTF-8 ({e.reason} at byte {e.start})')
            return
        if ext in URL_LIST_EXT:
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    self.url(line.split()[0])
            return
        if ext in FEED_EXT or (ext not in MARKDOWN_EXT + HTML_EXT and looks_like_feed(text)):
            self.feed(text, src)
            return
        if ext in HTML_EXT:
            piece = html_piece(text, src, _piece_name(path))
        else:
            piece = markdown_piece(text, src, _piece_name(path))
        piece.date = piece.date or _date_from_name(path)
        self.add(piece)

    def folder(self, path: str):
        corpus = os.path.realpath(os.path.join(self.voice_dir, vr.CORPUS_DIR))
        real = os.path.realpath(path)
        if real == corpus or real.startswith(corpus + os.sep):
            self.report.errors.append(f'{self.rel(path)} is the corpus itself; import from '
                                      f'where the writing is now')
            return
        found, other = [], {}
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
            for n in sorted(files):
                if n.startswith('.'):
                    continue
                if n.lower().endswith(MARKDOWN_EXT + HTML_EXT + FEED_EXT):
                    found.append(os.path.join(root, n))
                else:
                    ext = os.path.splitext(n)[1].lower() or '(no extension)'
                    other.setdefault(ext, []).append(os.path.relpath(os.path.join(root, n),
                                                                     path))
        if not found:
            self.report.errors.append(f'{self.rel(path)} holds no Markdown, HTML or feed file')
        elif other:
            n = sum(len(v) for v in other.values())
            by_ext = ', '.join(f'{len(v)} {ext}' for ext, v in
                               sorted(other.items(), key=lambda kv: (-len(kv[1]), kv[0])))
            names = [f for v in other.values() for f in v]
            self.report.warnings.append(
                f'{self.rel(path)}: {n} file(s) that aren\'t Markdown, HTML or a feed, not '
                f'imported ({by_ext}): {_shown(sorted(names))}')
        for f in found:
            self.file(f)

    # -- the web
    def get(self, url: str) -> tuple[str, str, str] | None:
        """(final URL, text, content type), or None after reporting why not."""
        try:
            got = self.fetch(url)
        except VoiceImportError as e:
            self.report.errors.append(str(e))
            return None
        try:
            text = _decode(got.body, got.content_type, url)
        except VoiceImportError as e:
            self.report.errors.append(str(e))
            return None
        return got.url, text, got.content_type

    def url(self, url: str):
        if not is_url(url):
            self.report.errors.append(f'{url}: not an http or https URL')
            return
        got = self.get(url)
        if got is None:
            return
        final, text, ctype = got
        if 'xml' in ctype.lower() or looks_like_feed(text):
            self.feed(text, url)
            return
        self.add(html_piece(text, url, _piece_name(urllib.parse.urlparse(final).path)))

    def feed(self, xml: str, where: str):
        try:
            site, items, notes = feed_items(xml, where)
        except VoiceImportError as e:
            self.report.errors.append(str(e))
            return
        self.report.warnings.extend(notes)
        site_host = _host(site) or (_host(where) if is_url(where) else '')
        truncated, off_site_cut, summary_only = [], [], []
        for item in items:
            source = item.link or _item_key(where, item)
            kind = kind_of([c for c in item.categories
                            if c.strip().lower() not in FORM_ONLY_WORDS])
            story_tag = not kind and any(c.strip().lower() in FORM_ONLY_WORDS
                                         for c in item.categories)
            off_site = bool(site_host and is_url(item.link) and _host(item.link) != site_host)
            kind_from = KIND_SAID if kind or item.related else \
                KIND_OFF_SITE if off_site else KIND_GUESSED
            if not kind and (item.related or off_site):
                kind = 'link'
            cut = _truncated(item)
            # a summary with no full-content element and no cut marker may be
            # the whole post or an excerpt; a link post's summary is the post
            partial = item.summary_only and not cut and kind != 'link'
            if cut or (partial and self.follow and site_host and is_url(item.link)):
                if self.follow and is_url(item.link) and site_host and not off_site:
                    got = self.get(item.link)
                    if got is None:
                        continue
                    page = html_page(got[1])
                    body, title = page.body, item.title or page.title
                elif self.follow and is_url(item.link):
                    # its page is someone else's, or can't be told to be the author's
                    off_site_cut.append(item.title or source)
                    continue
                else:
                    truncated.append(item.title or source)
                    continue
            else:
                body, title = html_page(item.html).body, item.title
                if partial and body.strip():
                    summary_only.append(item.title or source)
            if body.lstrip('#').strip() == title:
                body = ''
            self.add(Piece(title, item.date, kind or 'essay', body, source, kind_from,
                           story_tag=story_tag and kind_from == KIND_GUESSED))
        if truncated:
            shown = _shown(truncated)
            self.report.warnings.append(
                f'{where}: {len(truncated)} item(s) carry only a cut summary, not imported '
                f'(pass --follow-links to fetch their pages): {shown}')
        if summary_only:
            self.report.warnings.append(
                f'{where}: {len(summary_only)} item(s) imported from the feed\'s summary alone '
                f'(no full-content element, no cut marker): if those are excerpts, remove '
                f'their rows from {vr.INDEX_FILE} and their files, then import again with '
                f'--follow-links: {_shown(summary_only)}')
        if off_site_cut:
            whose = (f'off {site_host}' if site_host
                     else 'to pages the feed names no site for')
            self.report.warnings.append(
                f'{where}: {len(off_site_cut)} item(s) carry only a cut summary and link '
                f'{whose}, so their pages may be someone else\'s writing; not fetched or '
                f'imported: {_shown(off_site_cut)}')


def read_sources(voice_dir: str, sources: list[str], fetch: Fetch | None = None,
                 follow_links: bool = False, kind: str = '') -> Report:
    """Read every source into pieces (nothing written). `fetch` gets each
    URL (default `fetch_url`, looked up at call time so a test can replace
    it). `kind`, when given, is every piece's kind."""
    report = Report()
    reader = _Reader(os.path.abspath(voice_dir), fetch or fetch_url, follow_links, report)
    for src in sources:
        if is_url(src):
            reader.url(src)
        elif os.path.isdir(src):
            reader.folder(src)
        elif os.path.isfile(src):
            reader.file(src)
        else:
            report.errors.append(f'{src}: not a folder, a file or an http(s) URL')
    if kind:
        for p in report.pieces:
            p.kind, p.kind_from, p.story_tag = kind, KIND_SAID, False
    return report


# ============================================================================
# Writing them
# ============================================================================

def slug(text: str, most: int = 60) -> str:
    """A file-name slug: lower-case ASCII letters, digits and hyphens."""
    import unicodedata
    s = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:most].rstrip('-') or 'piece'


@dataclass
class Plan:
    """What an import writes: new index rows with their files' text; the
    pieces skipped because their source is already in the index; and those
    skipped because the same piece is there under another source (the same
    text, or the same title and date as `plan_import` matches them), as
    (source, the file that has it)."""
    rows: list[vr.IndexRow] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)
    already: list[str] = field(default_factory=list)
    same_piece: list[tuple[str, str]] = field(default_factory=list)
    #: imported although a piece in the corpus or this import has the same
    #: title and date, as (source, that file, why): the title is used on
    #: other dates, or both are files of one folder. Named, so a double
    #: that slipped through can be found (#680)
    title_date_kept: list[tuple[str, str, str]] = field(default_factory=list)


def source_key(source: str) -> str:
    """A source as the index stores it (`csv_safe`), and for a URL without
    what doesn't change the page: the scheme, `www.`, a trailing `/`."""
    from storyforge.common import csv_safe
    s = csv_safe(source)
    if not is_url(s):
        return s
    u = urllib.parse.urlparse(s)
    return f'{_host(s)}{u.path.rstrip("/")}' + (f'?{u.query}' if u.query else '')


def _text_key(body: str) -> str:
    """A piece's words, lower-cased, without its markup or punctuation,
    hashed: the same post read from Markdown and from its HTML page match."""
    words = re.findall(r'\w+', body.lower())
    return hashlib.sha1(' '.join(words).encode('utf-8')).hexdigest() if words else ''


def _title_norm(title: str) -> str:
    return _collapse(title).lower()


def _full_date(date: str) -> bool:
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date or ''))


def _title_date_key(title: str, date: str,
                    generic: frozenset[str] = frozenset()) -> tuple[str, str] | None:
    """(title, date) for matching one piece reached two ways, or None: no
    title, no full date, or a `generic` title (one used on more than one
    full date, like a blog's default "Microblog post"), which names no one
    piece (#680)."""
    title = _title_norm(title)
    if not title or title in generic or not _full_date(date):
        return None
    return title, date


def _generic_titles(pairs: Iterable[tuple[str, str]]) -> frozenset[str]:
    """The titles, of (title, date) `pairs`, used on more than one full
    date: the dates `_title_date_key` would key on (an undated copy of a
    post doesn't make its title generic)."""
    dates: dict[str, set[str]] = {}
    for title, date in pairs:
        t = _title_norm(title)
        if t and _full_date(date):
            dates.setdefault(t, set()).add(date)
    return frozenset(t for t, ds in dates.items() if len(ds) > 1)


def _folder(source: str) -> str | None:
    """A file source's folder and extension (as `csv_safe` stores the
    source, so a stored row and a new piece compare), or None for a URL or
    a feed item. Two files of one type in one folder with one title and
    date are two pieces: a folder of posts never holds one post twice
    (#680). URLs get no such exemption: one host can serve a post
    under two URLs (a tracking query, a redirect, a short link), which only
    the title and date catch."""
    from storyforge.common import csv_safe
    if is_url(source) or '#' in source:
        return None     # a URL, or a feed item keyed by its feed (`_item_key`)
    s = csv_safe(source)
    # the extension too: a post's Markdown and its rendered page side by
    # side are one piece in two forms
    return f'{os.path.normpath(os.path.dirname(s))}|{os.path.splitext(s)[1].lower()}'


def _stored_body(text: str) -> str:
    """A corpus file's body: its `# title` line left out (`Piece.markdown`)."""
    return re.sub(r'\A#[ \t][^\n]*\n', '', text.replace('\r\n', '\n'))


def plan_import(voice_dir: str, pieces: list[Piece]) -> Plan:
    """Name each new piece's file (`corpus/<date>-<slug>.md`, `-2` and on
    for a name taken) and skip a piece the corpus or this import already
    has: by its source (`source_key`), or, reached another way (a folder,
    then its feed), by its text or its title and date (`_title_date_key`:
    not a title used on other dates, and not two files in one folder,
    `_folder`). Raises
    VoiceRepoError as `voice_repo.read_index`."""
    existing = vr.read_index(voice_dir)
    sources = {source_key(r.source) for r in existing if r.source}
    generic = _generic_titles([(r.title, r.date) for r in existing]
                              + [(p.title, p.date) for p in pieces])
    texts: dict[str, str] = {}
    dated: dict[tuple[str, str], str] = {}
    folder_of = {r.file: _folder(r.source) for r in existing if r.source}
    any_dated: dict[tuple[str, str], str] = {}   # the same, with no title generic
    for r in existing:
        raw = _title_date_key(r.title, r.date)
        if raw:
            any_dated.setdefault(raw, r.file)
        key = _title_date_key(r.title, r.date, generic)
        if key:
            dated.setdefault(key, r.file)
        try:
            with open(os.path.join(voice_dir, r.file), encoding='utf-8-sig') as f:
                tk = _text_key(_stored_body(f.read()))
        except (OSError, UnicodeDecodeError):
            continue    # `voice fingerprint` and the summary report a file that can't be read
        if tk:
            texts.setdefault(tk, r.file)
    taken = {os.path.normpath(r.file) for r in existing}
    corpus = os.path.join(voice_dir, vr.CORPUS_DIR)
    if os.path.isdir(corpus):
        taken |= {os.path.normpath(os.path.join(vr.CORPUS_DIR, n)) for n in os.listdir(corpus)}
    plan = Plan()
    ordered = sorted(pieces, key=lambda p: (p.date or '9999', p.source))
    for p in ordered:
        sk = source_key(p.source)
        if sk in sources:
            plan.already.append(p.source)
            continue
        tk, dk = _text_key(p.body), _title_date_key(p.title, p.date, generic)
        dated_twin = dk and dated.get(dk)
        folder = _folder(p.source)
        kept_why = ''
        if dated_twin and folder is not None and folder_of.get(dated_twin) == folder:
            dated_twin, kept_why = None, 'both are files of one folder'
        raw = _title_date_key(p.title, p.date)
        if raw and not dk and any_dated.get(raw):
            kept_why = 'its title is used on other dates'
        twin = (tk and texts.get(tk)) or dated_twin
        if not twin and kept_why:
            plan.title_date_kept.append(
                (p.source, dated.get(dk) or any_dated.get(raw) or '', kept_why))
        if twin:
            plan.same_piece.append((p.source, twin))
            continue
        sources.add(sk)
        base = '-'.join(x for x in (p.date, slug(p.title or _piece_name(p.source))) if x)
        name, n = f'{base}.md', 2
        while os.path.normpath(os.path.join(vr.CORPUS_DIR, name)) in taken:
            name, n = f'{base}-{n}.md', n + 1
        rel = f'{vr.CORPUS_DIR}/{name}'
        taken.add(os.path.normpath(rel))
        if tk:
            texts[tk] = rel
        if dk:
            dated[dk] = rel
        if raw:
            any_dated.setdefault(raw, rel)
        folder_of[rel] = _folder(p.source)
        plan.rows.append(vr.IndexRow(rel, _collapse(p.title), p.date, p.kind, p.source, ''))
        plan.texts[rel] = p.markdown()
    return plan


def write_import(voice_dir: str, plan: Plan) -> None:
    """Write the plan's files, then the index with its rows added at the
    end (the files first, so the index never names a file not written).
    Raises VoiceRepoError when a write fails, after removing the files this
    plan wrote (all new: `plan_import` never reuses a name), so a failed
    import leaves no file the index doesn't name."""
    from storyforge.voiceprint_proposals import _write_text
    written = []
    try:
        for rel, text in plan.texts.items():
            _write_text(os.path.join(voice_dir, rel), text)
            written.append(rel)
        if plan.rows:
            vr.write_index(voice_dir, vr.read_index(voice_dir) + plan.rows)
    except (OSError, vr.VoiceRepoError) as e:
        left = []
        for rel in written:
            try:
                os.remove(os.path.join(voice_dir, rel))
            except OSError:
                left.append(rel)
        tail = (f'; these couldn\'t be removed and aren\'t in the index: {", ".join(left)}'
                if left else '; the files it had written are removed')
        raise vr.VoiceRepoError(f'the import couldn\'t be written ({e}): nothing imported'
                                f'{tail}') from e
