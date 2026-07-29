"""Tests for the publish asset pipeline — digest diff, signed upload, cover rule.

Publishing a book with images is a three-step contract
(benjaminsnorris/bookshelf#11): declare digests, PUT the missing bytes to signed
URLs, then send the metadata-only manifest. Storyforge shipped only the third
step, so an illustrated book could not publish at all (#284).

The signed-URL call shape is pinned here rather than mocked away, because it is
the part most likely to be wrong: it was read out of `@supabase/storage-js`'s
`createSignedUploadUrl` (bookshelf's own dependency) rather than out of
bookshelf, and the endpoint passes that value straight through.
"""
import hashlib
import json
import os
import socketserver
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from storyforge import bookshelf


PNG = b'\x89PNG\r\n\x1a\n' + b'fake image bytes'


# ============================================================================
# Mock Bookshelf + Storage
# ============================================================================

class _AssetHandler(BaseHTTPRequestHandler):
    """Serves the digest-diff endpoint and the signed upload URLs it hands out.

    Both live on one server so a test can assert that the bytes landed at
    exactly the path the endpoint signed.
    """

    lock = threading.Lock()

    #: Queued (status, body) pairs for POST /api/books/<slug>/assets. The last
    #: one repeats, so a test that does not care about chunking sets one.
    negotiate_queue: list = []
    negotiate_requests: list = []

    #: Recorded PUTs: {'path', 'query', 'headers', 'body'}.
    uploads: list = []
    #: Status for signed uploads; a per-digest entry overrides the default.
    upload_status = 200
    upload_status_by_digest: dict = {}

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        payload = json.loads(self.rfile.read(length)) if length else None
        with _AssetHandler.lock:
            _AssetHandler.negotiate_requests.append({
                'path': self.path,
                'headers': dict(self.headers),
                'body': payload,
            })
            queue = _AssetHandler.negotiate_queue
            status, body = queue[0] if len(queue) == 1 else queue.pop(0)
        self._respond(status, json.dumps(body).encode())

    def do_PUT(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b''
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        digest = os.path.splitext(os.path.basename(parsed.path))[0]
        with _AssetHandler.lock:
            _AssetHandler.uploads.append({
                'path': parsed.path,
                'query': query,
                'headers': dict(self.headers),
                'body': raw,
            })
            status = _AssetHandler.upload_status_by_digest.get(
                digest, _AssetHandler.upload_status)
        if status >= 400:
            self._respond(status, b'{"error":"storage refused the write"}')
        else:
            self._respond(status, json.dumps({'Key': parsed.path}).encode())

    def _respond(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Server(ThreadingHTTPServer):
    """Threading, and without the reverse-DNS lookup HTTPServer does on bind.

    Threading because sync_assets uploads concurrently. The getfqdn skip is not
    cosmetic: on a machine whose resolver cannot answer for a loopback address
    it blocks for tens of seconds, and `server_name` is never read here.
    """

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@pytest.fixture(scope='module')
def server():
    """One server for the module — per-test state lives in reset_handler."""
    httpd = _Server(('127.0.0.1', 0), _AssetHandler)
    thread = threading.Thread(target=httpd.serve_forever,
                              kwargs={'poll_interval': 0.02}, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()


@pytest.fixture(autouse=True)
def reset_handler():
    _AssetHandler.negotiate_queue = [(200, {})]
    _AssetHandler.negotiate_requests = []
    _AssetHandler.uploads = []
    _AssetHandler.upload_status = 200
    _AssetHandler.upload_status_by_digest = {}


# ============================================================================
# Helpers
# ============================================================================

def write_image(tmp_path, name, body=PNG):
    """Write an image file and return (absolute path, its digest)."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path), hashlib.sha256(body).hexdigest()


def asset(key, digest, role='illustration', extension='png'):
    return {'key': key, 'role': role, 'sha256': digest, 'extension': extension}


def signed(base, slug, digest, extension='png'):
    """One entry of the endpoint's `upload` map, in the real shape.

    `createSignedUploadUrl` returns an absolute `signedUrl` with the token
    already present as a query parameter; the endpoint forwards it verbatim.
    """
    path = f'{slug}/{digest}.{extension}'
    token = f'token-for-{digest[:8]}'
    return {
        'url': (f'{base}/storage/v1/object/upload/sign/book-assets/{path}'
                f'?token={token}'),
        'token': token,
        'path': path,
    }


def diff_response(base, slug, missing, unchanged=0, extension='png'):
    return {
        'bucket': 'book-assets',
        'total': len(missing) + unchanged,
        'unchanged': unchanged,
        'missing': list(missing),
        'upload': {d: signed(base, slug, d, extension) for d in missing},
    }


# ============================================================================
# signed_upload_target — the one detail that had to be read from Supabase
# ============================================================================

class TestSignedUploadTarget:
    def test_absolute_url_is_used_verbatim(self):
        entry = signed('https://sb.example.com', 'book', 'a' * 64)
        assert bookshelf.signed_upload_target(entry) == entry['url']

    def test_the_token_rides_in_the_url_it_returns(self):
        """The token in the query string is the whole credential."""
        entry = signed('https://sb.example.com', 'book', 'b' * 64)
        assert 'token=' in bookshelf.signed_upload_target(entry)

    def test_a_non_absolute_url_is_refused_not_reconstructed(self):
        """storage-js builds signedUrl as `new URL(this.url + data.url)`, so it
        cannot come back relative, and route.ts forwards it verbatim.

        A relative url therefore means the contract changed. Rebuilding one from
        a guessed /storage/v1 prefix would be *less* safe than refusing — a
        signed upload URL is a bare write capability, and a wrong guess PUTs the
        bytes somewhere unintended.
        """
        entry = {'url': '/object/upload/sign/book-assets/b/c.png',
                 'token': 'tok', 'path': 'b/c.png'}
        with pytest.raises(RuntimeError, match='not absolute'):
            bookshelf.signed_upload_target(entry)

    def test_empty_url_is_an_error(self):
        with pytest.raises(RuntimeError, match='no url'):
            bookshelf.signed_upload_target({'token': 'tok'})


# ============================================================================
# Digest diff
# ============================================================================

class TestDigestDiff:
    def test_all_missing_uploads_every_object(self, server, tmp_path):
        one, d1 = write_image(tmp_path, 'one.png')
        two, d2 = write_image(tmp_path, 'two.png', PNG + b'2')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [d1, d2]))]

        result = bookshelf.sync_assets(
            server, 'jwt', 'bk',
            [asset('one', d1), asset('two', d2)],
            {d1: one, d2: two})

        assert result['uploaded'] == 2
        assert result['unchanged'] == 0
        assert result['bytes_uploaded'] == os.path.getsize(one) + os.path.getsize(two)
        assert len(_AssetHandler.uploads) == 2

    def test_all_unchanged_uploads_nothing(self, server, tmp_path):
        one, d1 = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [], unchanged=1))]

        result = bookshelf.sync_assets(server, 'jwt', 'bk',
                                      [asset('one', d1)], {d1: one})

        assert result == {'declared': 1, 'objects': 1, 'uploaded': 0,
                          'unchanged': 1, 'bytes_uploaded': 0}
        assert _AssetHandler.uploads == []

    def test_mixed_uploads_only_the_missing_one(self, server, tmp_path):
        one, d1 = write_image(tmp_path, 'one.png')
        two, d2 = write_image(tmp_path, 'two.png', PNG + b'2')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [d2], unchanged=1))]

        result = bookshelf.sync_assets(
            server, 'jwt', 'bk',
            [asset('one', d1), asset('two', d2)],
            {d1: one, d2: two})

        assert result['uploaded'] == 1
        assert result['unchanged'] == 1
        assert _AssetHandler.uploads[0]['body'] == PNG + b'2'

    def test_declaration_is_chunked_above_the_server_cap(self, server, tmp_path):
        """MAX_ASSETS_PER_REQUEST is 200; a bigger request is rejected outright."""
        assets = {}
        sources = {}
        for i in range(250):
            path, digest = write_image(tmp_path, f'i{i}.png', PNG + str(i).encode())
            assets[digest] = asset(f'i{i}', digest)
            sources[digest] = path
        # Nothing missing, so this exercises chunking without 250 uploads.
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [], unchanged=200)),
            (200, diff_response(server, 'bk', [], unchanged=50)),
        ]

        result = bookshelf.sync_assets(server, 'jwt', 'bk',
                                      list(assets.values()), sources)

        sizes = [len(r['body']['assets'])
                 for r in _AssetHandler.negotiate_requests]
        assert sizes == [200, 50]
        assert result['objects'] == 250
        assert result['unchanged'] == 250

    def test_exactly_the_cap_is_one_request(self, server, tmp_path):
        """200 is the boundary: the server rejects only *above* it.

        250 proves chunking happens; this proves it does not happen a request
        too early and split a legal declaration in two.
        """
        assets, sources = [], {}
        for i in range(bookshelf.MAX_ASSETS_PER_REQUEST):
            path, digest = write_image(tmp_path, f'b{i}.png', PNG + b'b%d' % i)
            assets.append(asset(f'b{i}', digest))
            sources[digest] = path
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [], unchanged=200))]

        bookshelf.sync_assets(server, 'jwt', 'bk', assets, sources)

        sizes = [len(r['body']['assets'])
                 for r in _AssetHandler.negotiate_requests]
        assert sizes == [200]

    def test_one_object_per_distinct_digest(self, server, tmp_path):
        """Two keys can share a digest — the same image used twice.

        The server dedupes to {digest}.{extension} before minting upload URLs,
        so declaring the same object twice would also risk uploading it twice
        when a digest straddles two chunks.
        """
        path, digest = write_image(tmp_path, 'shared.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        result = bookshelf.sync_assets(
            server, 'jwt', 'bk',
            [asset('first', digest), asset('second', digest)],
            {digest: path})

        assert result['declared'] == 2
        assert result['objects'] == 1
        assert len(_AssetHandler.uploads) == 1

    def test_no_assets_makes_no_requests(self, server):
        result = bookshelf.sync_assets(server, 'jwt', 'bk', [], {})
        assert result['objects'] == 0
        assert _AssetHandler.negotiate_requests == []

    def test_extensions_are_normalized_before_declaring(self, server, tmp_path):
        """jpg and jpeg are one format; the server collapses them and so must we."""
        path, digest = write_image(tmp_path, 'c.jpg', b'\xff\xd8\xff jpeg')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [], unchanged=1))]

        bookshelf.sync_assets(
            server, 'jwt', 'bk',
            [asset('c', digest, role='cover', extension='jpg')],
            {digest: path})

        declared = _AssetHandler.negotiate_requests[0]['body']['assets'][0]
        assert declared['extension'] == 'jpeg'


# ============================================================================
# The upload call shape
# ============================================================================

class TestUploadShape:
    def test_bytes_land_at_the_path_the_server_signed(self, server, tmp_path):
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        bookshelf.sync_assets(server, 'jwt', 'bk',
                              [asset('one', digest)], {digest: path})

        upload = _AssetHandler.uploads[0]
        assert upload['path'] == (
            f'/storage/v1/object/upload/sign/book-assets/bk/{digest}.png')
        assert upload['body'] == PNG

    def test_token_travels_in_the_query_string(self, server, tmp_path):
        """`uploadToSignedUrl` authenticates with the token, not a JWT header."""
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        bookshelf.sync_assets(server, 'jwt', 'bk',
                              [asset('one', digest)], {digest: path})

        upload = _AssetHandler.uploads[0]
        assert upload['query']['token'] == [f'token-for-{digest[:8]}']
        assert 'Authorization' not in upload['headers']

    def test_sends_a_real_content_type(self, server, tmp_path):
        """The bucket enforces allowed_mime_types."""
        path, digest = write_image(tmp_path, 'c.jpg', b'\xff\xd8\xff jpeg')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest], extension='jpeg'))]

        bookshelf.sync_assets(
            server, 'jwt', 'bk',
            [asset('c', digest, role='cover', extension='jpg')],
            {digest: path})

        assert _AssetHandler.uploads[0]['headers']['Content-Type'] == 'image/jpeg'

    def test_negotiation_carries_the_bearer_token(self, server, tmp_path):
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [], unchanged=1))]

        bookshelf.sync_assets(server, 'jwt-abc', 'bk',
                              [asset('one', digest)], {digest: path})

        req = _AssetHandler.negotiate_requests[0]
        assert req['path'] == '/api/books/bk/assets'
        assert req['headers']['Authorization'] == 'Bearer jwt-abc'

    def test_unsupported_extension_is_refused_before_the_put(self, tmp_path):
        path, _ = write_image(tmp_path, 'c.gif', b'GIF89a')
        with pytest.raises(RuntimeError, match='not one of'):
            bookshelf.upload_asset_bytes('http://x/y', path, 'gif')

    def test_an_unreadable_file_fails_before_the_put(self, tmp_path):
        with pytest.raises(RuntimeError, match='Cannot read'):
            bookshelf.upload_asset_bytes(
                'http://127.0.0.1:1/x', str(tmp_path / 'absent.png'), 'png')

    def test_unreachable_storage_is_surfaced(self, tmp_path):
        path, _ = write_image(tmp_path, 'one.png')
        with pytest.raises(RuntimeError, match='could not reach storage'):
            bookshelf.upload_asset_bytes('http://127.0.0.1:1/x', path, 'png')


# ============================================================================
# The transport is role-generic
# ============================================================================

class TestRoleGeneric:
    def test_cover_and_illustration_travel_the_same_path(self, server, tmp_path):
        cover, cd = write_image(tmp_path, 'cover.png')
        art, ad = write_image(tmp_path, 'art.png', PNG + b'art')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [cd, ad]))]

        result = bookshelf.sync_assets(
            server, 'jwt', 'bk',
            [asset('cover', cd, role='cover'), asset('art', ad)],
            {cd: cover, ad: art})

        assert result['uploaded'] == 2

    def test_an_unknown_role_passes_through_untouched(self, server, tmp_path):
        """Nothing here inspects `role`, so a new one needs no change here."""
        path, digest = write_image(tmp_path, 'ref.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        result = bookshelf.sync_assets(
            server, 'jwt', 'bk',
            [asset('ref', digest, role='packet-reference')],
            {digest: path})

        declared = _AssetHandler.negotiate_requests[0]['body']['assets'][0]
        assert declared['role'] == 'packet-reference'
        assert result['uploaded'] == 1


# ============================================================================
# Error paths — never a silent partial success
# ============================================================================

class TestErrorPaths:
    def test_auth_failure_is_surfaced(self, server, tmp_path):
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [(401, {'error': 'Admin required'})]

        with pytest.raises(RuntimeError, match='Admin required'):
            bookshelf.sync_assets(server, 'bad-jwt', 'bk',
                                  [asset('one', digest)], {digest: path})
        assert _AssetHandler.uploads == []

    def test_a_non_json_error_body_is_still_reported(self, server, tmp_path):
        """A gateway or proxy failure returns HTML, not the API's error shape."""
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [(502, '<html>Bad Gateway</html>')]

        with pytest.raises(RuntimeError, match='502'):
            bookshelf.sync_assets(server, 'jwt', 'bk',
                                  [asset('one', digest)], {digest: path})

    def test_unreachable_endpoint_is_surfaced(self, tmp_path):
        path, digest = write_image(tmp_path, 'one.png')
        with pytest.raises(RuntimeError, match='Cannot reach Bookshelf'):
            bookshelf.sync_assets('http://127.0.0.1:1', 'jwt', 'bk',
                                  [asset('one', digest)], {digest: path})

    def test_signed_url_rejection_names_the_file(self, server, tmp_path):
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]
        _AssetHandler.upload_status = 403

        with pytest.raises(RuntimeError, match='upload'):
            bookshelf.sync_assets(server, 'jwt', 'bk',
                                  [asset('one', digest)], {digest: path})

    def test_upload_failure_reports_every_file_then_raises(self, server,
                                                          tmp_path, capsys):
        one, d1 = write_image(tmp_path, 'one.png')
        two, d2 = write_image(tmp_path, 'two.png', PNG + b'2')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [d1, d2]))]
        _AssetHandler.upload_status = 403

        with pytest.raises(RuntimeError, match='2 asset upload\\(s\\) failed'):
            bookshelf.sync_assets(server, 'jwt', 'bk',
                                  [asset('one', d1), asset('two', d2)],
                                  {d1: one, d2: two})
        out = capsys.readouterr().out
        assert 'one.png' in out and 'two.png' in out

    def test_a_conflict_is_treated_as_already_present_and_logged(self, server,
                                                                tmp_path,
                                                                capsys):
        """Content-addressed: a name collision is the same bytes by construction."""
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]
        _AssetHandler.upload_status = 409

        result = bookshelf.sync_assets(server, 'jwt', 'bk',
                                      [asset('one', digest)], {digest: path})

        assert result['uploaded'] == 1
        assert result['bytes_uploaded'] == 0
        assert 'already present' in capsys.readouterr().out

    def test_a_socket_error_mid_transfer_is_wrapped(self, tmp_path):
        """`urlopen` only wraps request-phase failures.

        `getresponse()` and `resp.read()` raise ConnectionResetError,
        TimeoutError, or RemoteDisconnected unwrapped — none of them a URLError.
        This is the likeliest real failure: 8 concurrent PUTs of multi-megabyte
        images, and a reset while reading one response.
        """
        from unittest.mock import patch

        path, _ = write_image(tmp_path, 'one.png')
        with patch('storyforge.bookshelf.urllib.request.urlopen',
                   side_effect=ConnectionResetError('Connection reset by peer')):
            with pytest.raises(RuntimeError, match='broke mid-transfer'):
                bookshelf.upload_asset_bytes('http://x/y', path, 'png')

    def test_a_socket_error_during_negotiation_is_wrapped(self, server, tmp_path):
        from unittest.mock import patch

        _, digest = write_image(tmp_path, 'one.png')
        with patch('storyforge.bookshelf.urllib.request.urlopen',
                   side_effect=TimeoutError('timed out')):
            with pytest.raises(RuntimeError,
                               match='negotiation connection failed'):
                bookshelf.negotiate_assets(server, 'jwt', 'bk',
                                           [asset('one', digest)])

    def test_a_socket_error_is_aggregated_not_escaped(self, server, tmp_path,
                                                     capsys):
        """Escaping would discard the OTHER uploads' collected failures and
        reach the author as a traceback instead of a retry list."""
        from unittest.mock import patch

        one, d1 = write_image(tmp_path, 'one.png')
        two, d2 = write_image(tmp_path, 'two.png', PNG + b'2')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [d1, d2]))]

        with patch('storyforge.bookshelf.upload_asset_bytes',
                   side_effect=ConnectionResetError('Connection reset by peer')):
            with pytest.raises(RuntimeError,
                               match=r'2 asset upload\(s\) failed'):
                bookshelf.sync_assets(server, 'jwt', 'bk',
                                      [asset('one', d1), asset('two', d2)],
                                      {d1: one, d2: two})

        out = capsys.readouterr().out
        assert 'one.png' in out and 'two.png' in out
        assert 'Connection reset by peer' in out

    def test_an_unforeseen_failure_still_names_its_file(self, server, tmp_path,
                                                       capsys):
        """A bare exception may say nothing about which asset it was."""
        from unittest.mock import patch

        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        with patch('storyforge.bookshelf.upload_asset_bytes',
                   side_effect=MemoryError('out of memory')):
            with pytest.raises(RuntimeError, match='1 asset upload'):
                bookshelf.sync_assets(server, 'jwt', 'bk',
                                      [asset('one', digest)], {digest: path})

        assert 'one.png: out of memory' in capsys.readouterr().out

    def test_unmapped_digest_is_refused_with_a_next_step(self, server, tmp_path):
        _, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        with pytest.raises(RuntimeError, match='no local file was supplied'):
            bookshelf.sync_assets(server, 'jwt', 'bk',
                                  [asset('one', digest)], {})
        assert _AssetHandler.uploads == []

    def test_missing_local_file_is_refused(self, server, tmp_path):
        _, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        with pytest.raises(RuntimeError, match='missing'):
            bookshelf.sync_assets(server, 'jwt', 'bk', [asset('one', digest)],
                                  {digest: str(tmp_path / 'gone.png')})

    def test_unreadable_local_file_is_refused(self, server, tmp_path):
        """A directory where a file should be: os.path.isfile is not enough."""
        path, digest = write_image(tmp_path, 'one.png')
        os.chmod(path, 0o000)
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]
        try:
            if os.access(path, os.R_OK):
                pytest.skip('cannot make a file unreadable as this user')
            with pytest.raises(RuntimeError, match='Cannot read'):
                bookshelf.sync_assets(server, 'jwt', 'bk',
                                      [asset('one', digest)], {digest: path})
        finally:
            os.chmod(path, 0o644)

    def test_a_drifted_digest_is_caught_before_any_upload(self, server,
                                                         tmp_path):
        """The server re-hashes uploads and would raise assets_digest_mismatch.

        Catching it locally names the file and the fix instead.
        """
        path, digest = write_image(tmp_path, 'one.png')
        with open(path, 'ab') as f:
            f.write(b'edited after ingest')
        _AssetHandler.negotiate_queue = [
            (200, diff_response(server, 'bk', [digest]))]

        with pytest.raises(RuntimeError, match='no longer matches its recorded'):
            bookshelf.sync_assets(server, 'jwt', 'bk',
                                  [asset('one', digest)], {digest: path})
        assert _AssetHandler.uploads == []

    def test_missing_signed_url_for_a_missing_digest_is_an_error(self, server,
                                                                tmp_path):
        path, digest = write_image(tmp_path, 'one.png')
        _AssetHandler.negotiate_queue = [
            (200, {'missing': [digest], 'upload': {}, 'unchanged': 0})]

        with pytest.raises(RuntimeError, match='no signed upload URL'):
            bookshelf.sync_assets(server, 'jwt', 'bk',
                                  [asset('one', digest)], {digest: path})


# ============================================================================
# The cover rule
# ============================================================================

class TestRequireCoverAsset:
    def test_assets_with_a_cover_are_allowed(self):
        from storyforge.assembly import require_cover_asset
        require_cover_asset({'assets': [
            {'key': 'cover', 'role': 'cover'},
            {'key': 'lf-01', 'role': 'illustration'},
        ]})

    def test_assets_without_a_cover_are_refused(self):
        """A manifest declaring assets and no cover nulls cover_image_url.

        Publishing illustrations would delete the live book's cover — silent
        data loss on the reader side, so this refuses rather than warns.
        """
        from storyforge.assembly import require_cover_asset
        with pytest.raises(ValueError, match='none with role "cover"'):
            require_cover_asset({'assets': [
                {'key': 'lf-01', 'role': 'illustration'}]})

    def test_the_refusal_names_where_to_put_a_cover(self):
        from storyforge.assembly import require_cover_asset
        with pytest.raises(ValueError) as excinfo:
            require_cover_asset({'assets': [{'key': 'x', 'role': 'illustration'}]})
        assert 'production.cover_image' in str(excinfo.value)

    def test_cover_only_is_allowed(self):
        from storyforge.assembly import require_cover_asset
        require_cover_asset({'assets': [{'key': 'cover', 'role': 'cover'}]})

    def test_no_assets_at_all_is_allowed(self):
        """A manifest that never mentions assets says nothing about the cover."""
        from storyforge.assembly import require_cover_asset
        require_cover_asset({'title': 'T'})
        require_cover_asset({'assets': []})


class TestManifestCoverIntegration:
    def _project(self, tmp_path, with_cover=True):
        from illustration_helpers import make_jpeg
        ref = tmp_path / 'reference'
        ref.mkdir()
        (tmp_path / 'scenes').mkdir()
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: T\n  author: A\n')
        (ref / 'scenes.csv').write_text(
            'id|seq|title|status|word_count\ns1|1|One|drafted|10\n')
        (ref / 'chapter-map.csv').write_text(
            'chapter|title|heading|part|scenes\n1|Ch|numbered|1|s1\n')
        (tmp_path / 'scenes' / 's1.md').write_text('Prose.\n')
        if with_cover:
            make_jpeg(str(tmp_path / 'production' / 'cover.jpg'), 600, 900)
        return str(tmp_path)

    def _plan_one_illustration(self, project_dir):
        from illustration_helpers import make_png
        from storyforge import illustrations as ill
        art = os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR, 'lf-01.png')
        make_png(art, 40, 60)
        os.makedirs(os.path.join(project_dir, 'reference'), exist_ok=True)
        with open(ill.plan_path(project_dir), 'w') as f:
            f.write('|'.join(ill.PLAN_COLUMNS) + '\n')
            row = dict.fromkeys(ill.PLAN_COLUMNS, '')
            row.update(id='LF-01', scene_id='s1', placement='scene_open',
                       layout='full_page', status='ingested',
                       sha256=ill.sha256_of(art),
                       asset_file=ill.default_asset_rel('lf-01'),
                       width='40', height='60')
            f.write('|'.join(row[c] for c in ill.PLAN_COLUMNS) + '\n')
        scene = os.path.join(project_dir, 'scenes', 's1.md')
        with open(scene, 'w') as f:
            f.write('![[illus:LF-01]]\n\nProse.\n')

    def test_cover_and_illustrations_share_one_array(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        project = self._project(tmp_path)
        self._plan_one_illustration(project)

        with open(generate_publish_manifest(project,
                                           include_dashboard=False)) as f:
            manifest = json.load(f)

        assert [a['role'] for a in manifest['assets']] == ['cover', 'illustration']

    def test_every_declared_asset_maps_to_a_file(self, tmp_path):
        from storyforge.assembly import (generate_publish_manifest,
                                         read_asset_sources)
        project = self._project(tmp_path)
        self._plan_one_illustration(project)

        with open(generate_publish_manifest(project,
                                           include_dashboard=False)) as f:
            manifest = json.load(f)
        sources = read_asset_sources(project)

        for entry in manifest['assets']:
            local = sources[entry['sha256']]
            assert os.path.isfile(local)
            from storyforge.illustrations import sha256_of
            assert sha256_of(local) == entry['sha256']

    def test_illustrations_without_a_cover_are_refused(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        project = self._project(tmp_path, with_cover=False)
        self._plan_one_illustration(project)

        with pytest.raises(ValueError, match='none with role "cover"'):
            generate_publish_manifest(project, include_dashboard=False)

    def test_an_illustration_cannot_claim_the_cover_key(self, tmp_path):
        """Asset keys are unique per book; 'cover' belongs to the cover."""
        from storyforge import illustrations as ill
        from storyforge.assembly import generate_publish_manifest
        project = self._project(tmp_path)
        self._plan_one_illustration(project)
        rows = ill.read_plan(project)
        rows[0]['id'] = 'Cover'
        ill.write_plan(project, rows)
        scene = os.path.join(project, 'scenes', 's1.md')
        with open(scene, 'w') as f:
            f.write('![[illus:Cover]]\n\nProse.\n')

        with pytest.raises(ValueError, match='reserved for the book cover'):
            generate_publish_manifest(project, include_dashboard=False)


class TestOnDiskManifestGuards:
    """cmd_publish re-checks the manifest it reads back before sending it.

    Not a defence against editing working/publish-manifest.json: that file is
    regenerated on every run, so an edit is discarded rather than caught. What
    these cover is a manifest that reached the send path without passing the
    generator's own check — a bypassed or changed generator — which is what
    patching generate_publish_manifest simulates. Worth having on the one
    operation in this command that can destroy live data.
    """

    def _hand_written(self, tmp_path, manifest):
        project = TestManifestCoverIntegration()._project(tmp_path)
        os.makedirs(os.path.join(project, 'working'), exist_ok=True)
        path = os.path.join(project, 'working', 'publish-manifest.json')
        with open(path, 'w') as f:
            json.dump(manifest, f)
        return project, path

    def test_a_bypassed_generator_cannot_destroy_the_cover(self, tmp_path, capsys):
        from unittest.mock import patch
        from storyforge import cmd_publish

        project, path = self._hand_written(tmp_path, {
            'title': 'T', 'author': 'A', 'slug': 'bk', 'chapters': [],
            'assets': [{'key': 'lf-01', 'role': 'illustration',
                        'sha256': 'a' * 64, 'extension': 'png'}],
        })
        with patch('storyforge.cmd_publish.detect_project_root',
                   return_value=project), \
             patch('storyforge.assembly.generate_publish_manifest',
                   return_value=path), \
             patch('storyforge.bookshelf.publish') as pub:
            with pytest.raises(SystemExit):
                cmd_publish.main(['--no-dashboard'])

        pub.assert_not_called()
        assert 'none with role "cover"' in capsys.readouterr().out

    def test_a_manifest_with_no_source_map_is_named(self, tmp_path, capsys):
        """An empty map would otherwise surface as an opaque per-digest failure."""
        from unittest.mock import patch
        from storyforge import cmd_publish

        project, path = self._hand_written(tmp_path, {
            'title': 'T', 'author': 'A', 'slug': 'bk', 'chapters': [],
            'assets': [{'key': 'cover', 'role': 'cover',
                        'sha256': 'a' * 64, 'extension': 'png'}],
        })
        with patch('storyforge.cmd_publish.detect_project_root',
                   return_value=project), \
             patch('storyforge.assembly.generate_publish_manifest',
                   return_value=path):
            cmd_publish.main(['--dry-run', '--no-dashboard'])

        out = capsys.readouterr().out
        assert 'maps no digests to files' in out
        assert 'no local file recorded' in out


class TestAssetSourcesSidecar:
    def test_sidecar_paths_survive_a_moved_checkout(self, tmp_path):
        """Stored project-relative, resolved on read."""
        from storyforge.assembly import (asset_sources_path,
                                         generate_publish_manifest,
                                         read_asset_sources)
        project = TestManifestCoverIntegration()._project(tmp_path)
        TestManifestCoverIntegration()._plan_one_illustration(project)
        generate_publish_manifest(project, include_dashboard=False)

        with open(asset_sources_path(project)) as f:
            raw = json.load(f)
        assert all(not os.path.isabs(p) for p in raw.values())
        assert all(os.path.isfile(p)
                   for p in read_asset_sources(project).values())

    def test_the_sidecar_covers_every_declared_digest(self, tmp_path):
        from storyforge.assembly import (generate_publish_manifest,
                                         read_asset_sources)
        project = TestManifestCoverIntegration()._project(tmp_path)
        TestManifestCoverIntegration()._plan_one_illustration(project)

        with open(generate_publish_manifest(project,
                                           include_dashboard=False)) as f:
            manifest = json.load(f)
        sources = read_asset_sources(project)
        assert {a['sha256'] for a in manifest['assets']} <= set(sources)


class TestAssetCountCap:
    """Bookshelf validates the MANIFEST's array against MAX_ASSETS_PER_REQUEST
    too, not only the upload endpoint's request (`validateManifestAssets` runs
    the same `validateAssetRequests`).

    So the transport chunking correctly above 200 is not enough: without a
    pre-check, a 250-asset book uploads every byte and only then fails on
    `assets_validate`, wasting the whole transfer.
    """

    def test_at_the_cap_is_allowed(self):
        from storyforge.assembly import (MAX_MANIFEST_ASSETS,
                                         require_asset_count_within_cap)
        assets = [{'key': f'a{i}', 'role': 'illustration'}
                  for i in range(MAX_MANIFEST_ASSETS)]
        require_asset_count_within_cap(assets)

    def test_above_the_cap_is_refused_before_uploading(self):
        from storyforge.assembly import (MAX_MANIFEST_ASSETS,
                                         require_asset_count_within_cap)
        assets = [{'key': f'a{i}', 'role': 'illustration'}
                  for i in range(MAX_MANIFEST_ASSETS + 1)]
        with pytest.raises(ValueError, match='at most 200'):
            require_asset_count_within_cap(assets)

    def test_the_refusal_names_the_way_out(self):
        from storyforge.assembly import require_asset_count_within_cap
        with pytest.raises(ValueError) as excinfo:
            require_asset_count_within_cap([{'key': 'a'}] * 201)
        message = str(excinfo.value)
        assert 'status=superseded' in message
        assert 'Nothing was uploaded' in message

    def test_the_cap_matches_the_transport_constant(self):
        """Two copies of the server's limit would drift."""
        from storyforge.assembly import MAX_MANIFEST_ASSETS
        assert MAX_MANIFEST_ASSETS == bookshelf.MAX_ASSETS_PER_REQUEST


class TestUnpublishableIds:
    """`_ID_RE` allows `_` because the marker regex does; Bookshelf's key
    validator is `/^[a-z0-9][a-z0-9-]*$/` and does not.

    So `LF_01` is a legal plan id, a legal marker, and a 400 from the assets
    endpoint. Unreachable before #284 made assets actually ship.
    """

    def _plan_with_id(self, project_dir, illus_id):
        from illustration_helpers import make_png
        from storyforge import illustrations as ill
        art = os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                           f'{illus_id}.png')
        make_png(art, 8, 8)
        row = dict.fromkeys(ill.PLAN_COLUMNS, '')
        row.update(id=illus_id, scene_id='s1', placement='scene_open',
                   layout='full_page', status='ingested',
                   sha256=ill.sha256_of(art),
                   asset_file=ill.default_asset_rel(illus_id))
        ill.write_plan(project_dir, [row])
        scene = os.path.join(project_dir, 'scenes', 's1.md')
        with open(scene, 'w') as f:
            f.write(f'![[illus:{illus_id}]]\n\nProse.\n')

    def test_an_underscore_id_is_reported_locally(self, tmp_path):
        from storyforge import illustrations as ill
        project = TestManifestCoverIntegration()._project(tmp_path)
        self._plan_with_id(project, 'LF_01')

        kinds = [f['kind'] for f in ill.validate_plan(project)]
        assert 'unpublishable_id' in kinds

    def test_the_finding_is_blocking(self, tmp_path):
        """A row that cannot publish is incoherent, like invalid_id."""
        from storyforge import illustrations as ill
        assert 'unpublishable_id' in ill.BLOCKING_FINDINGS

    def test_the_finding_names_the_key_and_the_fix(self, tmp_path):
        from storyforge import illustrations as ill
        project = TestManifestCoverIntegration()._project(tmp_path)
        self._plan_with_id(project, 'LF_01')

        finding = next(f for f in ill.validate_plan(project)
                       if f['kind'] == 'unpublishable_id')
        assert "'lf_01'" in finding['detail']
        assert 'hyphens instead of underscores' in finding['detail']

    def test_a_hyphenated_id_is_fine(self, tmp_path):
        from storyforge import illustrations as ill
        project = TestManifestCoverIntegration()._project(tmp_path)
        self._plan_with_id(project, 'LF-01')

        kinds = [f['kind'] for f in ill.validate_plan(project)]
        assert 'unpublishable_id' not in kinds

    def test_an_overlong_id_is_reported(self, tmp_path):
        """The server caps a key at 128 characters."""
        from storyforge import illustrations as ill
        project = TestManifestCoverIntegration()._project(tmp_path)
        self._plan_with_id(project, 'a' * 129)

        kinds = [f['kind'] for f in ill.validate_plan(project)]
        assert 'unpublishable_id' in kinds

    def test_it_does_not_double_report_an_already_invalid_id(self, tmp_path):
        """An id `_ID_RE` rejects is invalid_id, not both."""
        from storyforge import illustrations as ill
        project = TestManifestCoverIntegration()._project(tmp_path)
        self._plan_with_id(project, 'LF-01')
        rows = ill.read_plan(project)
        rows[0]['id'] = '-leading-hyphen'
        ill.write_plan(project, rows)

        kinds = [f['kind'] for f in ill.validate_plan(project)]
        assert 'invalid_id' in kinds
        assert 'unpublishable_id' not in kinds

    def test_cleanup_prefixes_the_kind(self):
        """Kinds are declared bare; cmd_cleanup adds the illus_ prefix."""
        from storyforge import illustrations as ill
        assert not any(k.startswith('illus_')
                       for k in ill.IllustrationFindingKind.__args__)
