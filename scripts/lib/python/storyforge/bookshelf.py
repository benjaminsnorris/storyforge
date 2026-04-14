"""Bookshelf API client — authentication, publishing, and annotations.

Replaces direct database access via the bookshelf repo's publish-book.ts script
with HTTP calls to the Bookshelf API endpoints.

Environment variables:
    BOOKSHELF_URL           — deployed bookshelf URL (e.g. https://bookshelf.example.com)
    BOOKSHELF_EMAIL         — admin user email for Supabase auth
    BOOKSHELF_PASSWORD      — admin user password for Supabase auth
    BOOKSHELF_SUPABASE_URL  — Supabase project URL
    BOOKSHELF_SUPABASE_ANON_KEY — Supabase anon/publishable key
"""

import json
import os
import urllib.request
import urllib.error
import urllib.parse

from storyforge.common import log


# ============================================================================
# Configuration
# ============================================================================

_ENV_VARS = (
    'BOOKSHELF_URL',
    'BOOKSHELF_EMAIL',
    'BOOKSHELF_PASSWORD',
    'BOOKSHELF_SUPABASE_URL',
    'BOOKSHELF_SUPABASE_ANON_KEY',
)

# Color labels — used when API does not return color_label field.
# Will be removed when benjaminsnorris/bookshelf#5 lands.
COLOR_LABELS = {
    'pink': 'Needs Revision',
    'orange': 'Cut / Reconsider',
    'blue': 'Research Needed',
    'green': 'Strong Passage',
    'yellow': 'Important',
}


def check_env() -> dict[str, str]:
    """Validate that all required environment variables are set.

    Returns:
        Dict mapping env var names to their values.

    Raises:
        SystemExit: If any required variable is missing.
    """
    missing = [v for v in _ENV_VARS if not os.environ.get(v)]
    if missing:
        log(f'Missing environment variables: {", ".join(missing)}')
        log('Set these in your shell or .env before publishing.')
        raise SystemExit(1)
    return {v: os.environ[v] for v in _ENV_VARS}


# ============================================================================
# Authentication
# ============================================================================

def authenticate(supabase_url: str, supabase_anon_key: str,
                 email: str, password: str) -> str:
    """Sign in to Supabase and return a JWT access token.

    Uses the Supabase GoTrue REST API directly (no SDK dependency).

    Args:
        supabase_url: Supabase project URL.
        supabase_anon_key: Supabase anon/publishable key.
        email: Admin user email.
        password: Admin user password.

    Returns:
        JWT access token string.

    Raises:
        RuntimeError: If authentication fails.
    """
    url = f'{supabase_url}/auth/v1/token?grant_type=password'
    body = json.dumps({'email': email, 'password': password}).encode()
    headers = {
        'Content-Type': 'application/json',
        'apikey': supabase_anon_key,
    }

    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace') if e.fp else ''
        raise RuntimeError(
            f'Supabase auth failed (HTTP {e.code}): {detail}'
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f'Cannot reach Supabase: {e.reason}') from e

    token = data.get('access_token')
    if not token:
        raise RuntimeError('Supabase auth response missing access_token')
    return token


# ============================================================================
# Publishing
# ============================================================================

def publish(bookshelf_url: str, token: str, manifest: dict) -> dict:
    """Publish a book via the Bookshelf API.

    Sends the manifest as a PUT request to /api/books/<slug>.

    Args:
        bookshelf_url: Deployed bookshelf URL.
        token: JWT access token from authenticate().
        manifest: Publish manifest dict (title, author, slug, chapters, etc.).

    Returns:
        Response dict with ok, book_id, slug, published, highlights, cover_uploaded.

    Raises:
        RuntimeError: If the API returns an error.
    """
    slug = manifest.get('slug', '')
    if not slug:
        raise RuntimeError('Manifest missing slug field')

    url = f'{bookshelf_url.rstrip("/")}/api/books/{urllib.parse.quote(slug)}'
    body = json.dumps(manifest, ensure_ascii=False).encode()
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }

    req = urllib.request.Request(url, data=body, headers=headers, method='PUT')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace') if e.fp else ''
        try:
            error_data = json.loads(detail)
            msg = error_data.get('error', detail)
            phase = error_data.get('phase', '')
            if phase:
                msg = f'{msg} (failed during: {phase})'
        except (json.JSONDecodeError, AttributeError):
            msg = detail
        raise RuntimeError(
            f'Bookshelf publish failed (HTTP {e.code}): {msg}'
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f'Cannot reach Bookshelf: {e.reason}') from e


# ============================================================================
# Annotations
# ============================================================================

def get_annotations(bookshelf_url: str, token: str, slug: str,
                    chapter: int | None = None,
                    color: str | None = None,
                    search: str | None = None,
                    status: str = 'active',
                    format: str = 'json',
                    user_id: str | None = None) -> dict:
    """Fetch annotations for a book from the Bookshelf API.

    Args:
        bookshelf_url: Deployed bookshelf URL.
        token: JWT access token.
        slug: Book slug.
        chapter: Filter by chapter number.
        color: Filter by highlight color.
        search: Text search in highlights and notes.
        status: Filter by status (active, orphaned, all).
        format: Response format (json or markdown).
        user_id: Filter to specific user.

    Returns:
        Response dict with annotations data.

    Raises:
        RuntimeError: If the API returns an error.
    """
    params = {}
    if chapter is not None:
        params['chapter'] = str(chapter)
    if color:
        params['color'] = color
    if search:
        params['search'] = search
    if status != 'active':
        params['status'] = status
    if format != 'json':
        params['format'] = format
    if user_id:
        params['user_id'] = user_id

    qs = urllib.parse.urlencode(params)
    url = f'{bookshelf_url.rstrip("/")}/api/books/{urllib.parse.quote(slug)}/annotations'
    if qs:
        url += f'?{qs}'

    headers = {'Authorization': f'Bearer {token}'}
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace') if e.fp else ''
        raise RuntimeError(
            f'Bookshelf annotations failed (HTTP {e.code}): {detail}'
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f'Cannot reach Bookshelf: {e.reason}') from e
