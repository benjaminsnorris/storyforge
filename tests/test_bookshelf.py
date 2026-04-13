"""Tests for bookshelf API client module."""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from unittest.mock import patch

import pytest


# ============================================================================
# Fixtures
# ============================================================================

class _MockHandler(BaseHTTPRequestHandler):
    """Configurable HTTP handler for testing API calls."""

    # Class-level config — set before each test
    response_code = 200
    response_body = b'{}'
    last_request = None

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        _MockHandler.last_request = {
            'method': 'POST',
            'path': self.path,
            'headers': dict(self.headers),
            'body': json.loads(body) if body else None,
        }
        self.send_response(_MockHandler.response_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(_MockHandler.response_body)

    def do_PUT(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        _MockHandler.last_request = {
            'method': 'PUT',
            'path': self.path,
            'headers': dict(self.headers),
            'body': json.loads(body) if body else None,
        }
        self.send_response(_MockHandler.response_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(_MockHandler.response_body)

    def do_GET(self):
        _MockHandler.last_request = {
            'method': 'GET',
            'path': self.path,
            'headers': dict(self.headers),
            'body': None,
        }
        self.send_response(_MockHandler.response_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(_MockHandler.response_body)

    def log_message(self, format, *args):
        pass  # suppress request logging


@pytest.fixture
def mock_server():
    """Start a local HTTP server for testing API calls."""
    server = HTTPServer(('127.0.0.1', 0), _MockHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{port}'
    server.shutdown()


@pytest.fixture(autouse=True)
def reset_handler():
    """Reset handler state between tests."""
    _MockHandler.response_code = 200
    _MockHandler.response_body = b'{}'
    _MockHandler.last_request = None


# ============================================================================
# check_env
# ============================================================================

class TestCheckEnv:
    def test_all_vars_set(self):
        from storyforge.bookshelf import check_env
        env = {
            'BOOKSHELF_URL': 'https://example.com',
            'BOOKSHELF_EMAIL': 'a@b.com',
            'BOOKSHELF_PASSWORD': 'pass',
            'BOOKSHELF_SUPABASE_URL': 'https://sb.example.com',
            'BOOKSHELF_SUPABASE_ANON_KEY': 'key123',
        }
        with patch.dict(os.environ, env, clear=False):
            result = check_env()
        assert result['BOOKSHELF_URL'] == 'https://example.com'
        assert result['BOOKSHELF_EMAIL'] == 'a@b.com'

    def test_missing_vars_exits(self):
        from storyforge.bookshelf import check_env
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit):
                check_env()


# ============================================================================
# authenticate
# ============================================================================

class TestAuthenticate:
    def test_returns_token(self, mock_server):
        from storyforge.bookshelf import authenticate
        _MockHandler.response_body = json.dumps({
            'access_token': 'jwt-token-123',
            'token_type': 'bearer',
        }).encode()

        token = authenticate(mock_server, 'anon-key', 'user@test.com', 'pass')
        assert token == 'jwt-token-123'

        # Verify request
        req = _MockHandler.last_request
        assert req['method'] == 'POST'
        assert '/auth/v1/token' in req['path']
        assert req['body']['email'] == 'user@test.com'
        assert req['body']['password'] == 'pass'
        # HTTP headers are case-insensitive; check with lowered keys
        lower_headers = {k.lower(): v for k, v in req['headers'].items()}
        assert lower_headers['apikey'] == 'anon-key'

    def test_auth_failure_raises(self, mock_server):
        from storyforge.bookshelf import authenticate
        _MockHandler.response_code = 401
        _MockHandler.response_body = b'{"error":"Invalid credentials"}'

        with pytest.raises(RuntimeError, match='auth failed'):
            authenticate(mock_server, 'key', 'bad@test.com', 'wrong')

    def test_missing_token_raises(self, mock_server):
        from storyforge.bookshelf import authenticate
        _MockHandler.response_body = b'{"user": {}}'

        with pytest.raises(RuntimeError, match='missing access_token'):
            authenticate(mock_server, 'key', 'user@test.com', 'pass')


# ============================================================================
# publish
# ============================================================================

class TestPublish:
    def test_publish_success(self, mock_server):
        from storyforge.bookshelf import publish
        _MockHandler.response_body = json.dumps({
            'ok': True,
            'book_id': 'uuid-123',
            'slug': 'test-book',
            'published': {'chapters': 2, 'scenes': 5, 'words': 10000},
            'highlights': {'unchanged': 3, 'reanchored': 1, 'orphaned': 0},
            'cover_uploaded': False,
        }).encode()

        manifest = {
            'title': 'Test Book',
            'author': 'Author',
            'slug': 'test-book',
            'chapters': [],
        }
        result = publish(mock_server, 'jwt-token', manifest)
        assert result['ok'] is True
        assert result['published']['chapters'] == 2

        req = _MockHandler.last_request
        assert req['method'] == 'PUT'
        assert req['path'] == '/api/books/test-book'
        assert 'Bearer jwt-token' in req['headers']['Authorization']

    def test_publish_missing_slug_raises(self):
        from storyforge.bookshelf import publish
        with pytest.raises(RuntimeError, match='missing slug'):
            publish('http://example.com', 'token', {'title': 'No Slug'})

    def test_publish_400_error(self, mock_server):
        from storyforge.bookshelf import publish
        _MockHandler.response_code = 400
        _MockHandler.response_body = json.dumps({
            'error': 'Slug mismatch',
        }).encode()

        with pytest.raises(RuntimeError, match='Slug mismatch'):
            publish(mock_server, 'token', {'slug': 'test'})

    def test_publish_500_error_with_phase(self, mock_server):
        from storyforge.bookshelf import publish
        _MockHandler.response_code = 500
        _MockHandler.response_body = json.dumps({
            'error': 'Database write failed',
            'phase': 'upsert_scenes',
        }).encode()

        with pytest.raises(RuntimeError, match='upsert_scenes'):
            publish(mock_server, 'token', {'slug': 'test'})


# ============================================================================
# get_annotations
# ============================================================================

class TestGetAnnotations:
    def test_fetch_annotations(self, mock_server):
        from storyforge.bookshelf import get_annotations
        _MockHandler.response_body = json.dumps({
            'annotations': [
                {'chapter': 1, 'color': 'yellow', 'highlighted_text': 'Nice passage'},
            ],
        }).encode()

        result = get_annotations(mock_server, 'token', 'test-book')
        assert len(result['annotations']) == 1

        req = _MockHandler.last_request
        assert req['method'] == 'GET'
        assert '/api/books/test-book/annotations' in req['path']

    def test_filter_params(self, mock_server):
        from storyforge.bookshelf import get_annotations
        _MockHandler.response_body = b'{"annotations": []}'

        get_annotations(mock_server, 'token', 'test-book',
                        chapter=3, color='pink', status='all')

        req = _MockHandler.last_request
        assert 'chapter=3' in req['path']
        assert 'color=pink' in req['path']
        assert 'status=all' in req['path']

    def test_404_error(self, mock_server):
        from storyforge.bookshelf import get_annotations
        _MockHandler.response_code = 404
        _MockHandler.response_body = b'{"error": "Book not found"}'

        with pytest.raises(RuntimeError, match='404'):
            get_annotations(mock_server, 'token', 'nonexistent')
