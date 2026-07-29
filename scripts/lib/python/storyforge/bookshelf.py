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

import concurrent.futures
import json
import os
import urllib.request
import urllib.error
import urllib.parse
from typing import Iterable, Mapping, Sequence, TypedDict

from storyforge.common import log
from storyforge.illustrations import normalize_asset_extension, sha256_of


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
# Asset transport — digest negotiation and signed-URL upload
# ============================================================================
#
# Publishing a book with images is a three-step contract
# (benjaminsnorris/bookshelf#11):
#
#   1. POST /api/books/{slug}/assets — declare every asset's metadata, receive
#      the digests whose bytes are not in the bucket plus a signed upload URL
#      for each.
#   2. PUT the bytes to those signed URLs. Keeps image size out of the publish
#      route's request budget, and unchanged art costs zero bytes on
#      re-publish because its digest is already present.
#   3. PUT /api/books/{slug} — the metadata-only manifest.
#
# Everything in this section is steps 1 and 2, and it is deliberately
# **role-generic**: it takes an asset list and a digest -> local-path mapping
# from its caller and never reads project data itself. The cover, illustrations,
# and any future asset role all travel the same path, so nothing here branches
# on `role`.

#: Server-side `MAX_ASSETS_PER_REQUEST`. Requests above this are rejected
#: outright, so the declaration is chunked.
MAX_ASSETS_PER_REQUEST = 200

#: Matches the endpoint's `SIGN_CONCURRENCY`. Its `maxDuration` is 30s, so a
#: serial upload loop over a large book is a plausible timeout, and unbounded
#: parallelism would open a connection per image.
UPLOAD_CONCURRENCY = 8

#: The bucket enforces `allowed_mime_types`, so a real Content-Type is
#: required. Keyed on normalized extensions; `jpg` collapses onto `jpeg`.
MIME_BY_EXTENSION = {
    'png': 'image/png',
    'jpeg': 'image/jpeg',
    'webp': 'image/webp',
}

#: What `uploadToSignedUrl` sends by default. Objects are content-addressed, so
#: the same digest is always the same bytes and re-writing one is pointless.
_UPLOAD_CACHE_CONTROL = 'max-age=3600'


class AssetSyncResult(TypedDict):
    """Outcome of one asset sync — counted in distinct storage objects."""
    declared: int       #: assets the caller handed in
    objects: int        #: distinct (digest, extension) pairs among them
    uploaded: int       #: objects whose bytes this run wrote
    unchanged: int      #: objects the bucket already held
    bytes_uploaded: int


def negotiate_assets(bookshelf_url: str, token: str, slug: str,
                     assets: Sequence[Mapping]) -> dict:
    """Step 1 — declare assets, learn which digests need bytes.

    Args:
        bookshelf_url: Deployed bookshelf URL.
        token: JWT access token from authenticate().
        slug: Book slug.
        assets: Asset descriptors (key, role, sha256, extension, ...). At most
            MAX_ASSETS_PER_REQUEST entries; chunking is sync_assets' job.

    Returns:
        Response dict: bucket, total, unchanged, missing (list of digests), and
        upload (digest -> {url, token, path}).

    Raises:
        RuntimeError: If the endpoint rejects the request or is unreachable.
    """
    url = (f'{bookshelf_url.rstrip("/")}/api/books/'
           f'{urllib.parse.quote(slug)}/assets')
    body = json.dumps({'assets': list(assets)}).encode()
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }

    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace') if e.fp else ''
        try:
            detail = json.loads(detail).get('error', detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(
            f'Bookshelf asset negotiation failed (HTTP {e.code}): {detail}'
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f'Cannot reach Bookshelf: {e.reason}') from e


def signed_upload_target(entry: Mapping, supabase_url: str | None = None) -> str:
    """Absolute PUT target for one entry of the endpoint's ``upload`` map.

    This is the one part of the contract that had to be read out of Supabase
    rather than out of bookshelf, so it lives in a single function.

    Verified against ``@supabase/storage-js``
    ``StorageFileApi.createSignedUploadUrl`` (bookshelf's own dependency): it
    returns ``{signedUrl, token, path}`` where ``signedUrl`` is **absolute** —
    ``{supabase_url}/storage/v1/object/upload/sign/{bucket}/{path}?token=<JWT>``
    — with the token already present as a query parameter. The bookshelf
    endpoint passes that value through as ``upload[digest].url``.

    ``uploadToSignedUrl`` then PUTs to exactly that URL. The token in the query
    string is the whole credential: no ``Authorization`` header is required,
    and the token is bound to the path the server signed, so it cannot be
    redirected at another book's prefix (asserted by bookshelf's
    ``tests/integration/assets-endpoint.test.ts``).

    The relative branch is defensive only. Should a future storage-js return a
    path-only ``url``, it would be rooted at the storage API — hence the
    ``/storage/v1`` prefix — and the separately returned ``token`` has to be
    reattached because a relative form would not carry it.
    """
    url = str(entry.get('url') or '')
    if not url:
        raise RuntimeError('Signed upload entry has no url')
    if url.startswith('http://') or url.startswith('https://'):
        return url

    if not supabase_url:
        raise RuntimeError(
            f'Signed upload url {url!r} is relative and BOOKSHELF_SUPABASE_URL '
            f'was not supplied, so it cannot be resolved'
        )
    absolute = f'{supabase_url.rstrip("/")}/storage/v1/{url.lstrip("/")}'
    if 'token=' in absolute:
        return absolute
    upload_token = str(entry.get('token') or '')
    if not upload_token:
        raise RuntimeError(
            f'Signed upload url {url!r} carries no token and none was returned '
            f'alongside it'
        )
    joiner = '&' if '?' in absolute else '?'
    return f'{absolute}{joiner}token={urllib.parse.quote(upload_token)}'


def upload_asset_bytes(target_url: str, local_path: str, extension: str,
                       timeout: int = 300) -> int:
    """PUT one asset's bytes to a signed upload URL. Returns bytes written.

    Raises:
        RuntimeError: If the file cannot be read or storage rejects the write.
    """
    mime = MIME_BY_EXTENSION.get(normalize_asset_extension(extension))
    if not mime:
        raise RuntimeError(
            f'{local_path}: extension {extension!r} is not one of '
            f'{", ".join(sorted(MIME_BY_EXTENSION))} — the storage bucket '
            f'would reject it'
        )
    try:
        with open(local_path, 'rb') as f:
            data = f.read()
    except OSError as e:
        raise RuntimeError(f'Cannot read {local_path}: {e}') from e

    headers = {
        'Content-Type': mime,
        'cache-control': _UPLOAD_CACHE_CONTROL,
        # Mirrors uploadToSignedUrl's default. An object that already exists is
        # the same bytes by construction, so overwriting has nothing to gain.
        'x-upsert': 'false',
    }
    req = urllib.request.Request(target_url, data=data, headers=headers,
                                method='PUT')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace') if e.fp else ''
        if e.code == 409:
            # Content-addressed: a name collision means these exact bytes are
            # already there. Report it rather than swallowing it — a 409 also
            # means the digest diff and the bucket disagreed.
            log(f'WARNING: {os.path.basename(local_path)} was already present '
                f'at its content-addressed path (HTTP 409); bytes not '
                f're-sent. Nothing is lost — the object is identical by '
                f'construction — but the digest diff and the bucket '
                f'disagreed about it.')
            return 0
        raise RuntimeError(
            f'Signed upload of {local_path} failed (HTTP {e.code}): {detail}'
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f'Signed upload of {local_path} could not reach storage: {e.reason}'
        ) from e
    return len(data)


def _distinct_objects(assets: Iterable[Mapping]) -> list[dict]:
    """One declaration per distinct storage object.

    Two assets can legitimately share a digest — the same image used twice —
    and the server dedupes to ``{digest}.{extension}`` before minting upload
    URLs. Deduping on the same unit here keeps the declaration under
    MAX_ASSETS_PER_REQUEST for its real cost, and means a digest spanning two
    chunks cannot be uploaded twice. The authoritative asset list is the
    manifest's, sent in step 3; this request is only a digest diff.
    """
    seen: set[tuple[str, str]] = set()
    objects: list[dict] = []
    for asset in assets:
        digest = str(asset.get('sha256') or '')
        extension = normalize_asset_extension(str(asset.get('extension') or ''))
        identity = (digest, extension)
        if identity in seen:
            continue
        seen.add(identity)
        # Only the fields the digest-diff endpoint validates. `role` is passed
        # through untouched and never inspected.
        objects.append({
            'key': asset.get('key'),
            'role': asset.get('role'),
            'sha256': digest,
            'extension': extension,
        })
    return objects


def _resolve_local_file(digest: str, extension: str,
                        sources: Mapping[str, str]) -> str:
    """Local file holding `digest`, verified to actually hash to it."""
    local = sources.get(digest)
    if not local:
        raise RuntimeError(
            f'Bookshelf needs the bytes for digest {digest[:12]}… '
            f'({extension}) but no local file was supplied for it. '
            f'Re-run `storyforge illustrate --ingest` (or regenerate the '
            f'publish manifest) so the digest maps to a file on disk.'
        )
    if not os.path.isfile(local):
        raise RuntimeError(
            f'Declared asset file is missing: {local} '
            f'(digest {digest[:12]}…). Re-ingest it, or set its plan row to '
            f'status=superseded so it is not published.'
        )
    try:
        actual = sha256_of(local)
    except OSError as e:
        raise RuntimeError(f'Cannot read declared asset file {local}: {e}') from e
    if actual != digest:
        raise RuntimeError(
            f'{local} no longer matches its recorded digest: manifest claims '
            f'{digest[:12]}…, the file on disk hashes to {actual[:12]}…. '
            f'The file changed after ingest — re-run '
            f'`storyforge illustrate --ingest` to record the new digest.'
        )
    return local


def sync_assets(bookshelf_url: str, token: str, slug: str,
                assets: Sequence[Mapping],
                sources: Mapping[str, str],
                supabase_url: str | None = None,
                concurrency: int = UPLOAD_CONCURRENCY) -> AssetSyncResult:
    """Steps 1 and 2 — negotiate digests, then upload only the missing bytes.

    Role-generic by design. `assets` and `sources` both come from the caller,
    which owns resolving a digest to a file; nothing here reads project data or
    branches on an asset's role, so a new role needs no change in this module.

    Args:
        bookshelf_url: Deployed bookshelf URL.
        token: JWT access token from authenticate().
        slug: Book slug.
        assets: The manifest's `assets` array (metadata only).
        sources: Maps each asset's sha256 to an absolute local file path.
        supabase_url: Only used if the endpoint ever returns a relative signed
            URL; see signed_upload_target.
        concurrency: Parallel uploads.

    Returns:
        AssetSyncResult with per-object counts.

    Raises:
        RuntimeError: On negotiation failure, a missing or drifted local file,
            or a rejected upload. Never returns partial success silently.
    """
    objects = _distinct_objects(assets)
    result: AssetSyncResult = {
        'declared': len(assets),
        'objects': len(objects),
        'uploaded': 0,
        'unchanged': 0,
        'bytes_uploaded': 0,
    }
    if not objects:
        return result

    extension_by_digest = {o['sha256']: o['extension'] for o in objects}

    # Chunked because the endpoint caps a request at MAX_ASSETS_PER_REQUEST.
    # Each chunk's bytes are uploaded before the next chunk is declared, so a
    # later chunk sees earlier uploads as already present.
    for start in range(0, len(objects), MAX_ASSETS_PER_REQUEST):
        chunk = objects[start:start + MAX_ASSETS_PER_REQUEST]
        response = negotiate_assets(bookshelf_url, token, slug, chunk)

        upload = response.get('upload') or {}
        missing = list(response.get('missing') or [])
        result['unchanged'] += int(response.get('unchanged') or 0)

        if not missing:
            continue

        # Resolve every file before writing any bytes, so an unreadable or
        # drifted asset fails the publish before it half-uploads a book.
        planned: list[tuple[str, str, str]] = []
        for digest in missing:
            extension = extension_by_digest.get(digest, '')
            local = _resolve_local_file(digest, extension, sources)
            entry = upload.get(digest)
            if not entry:
                raise RuntimeError(
                    f'Bookshelf reported digest {digest[:12]}… as missing but '
                    f'returned no signed upload URL for it'
                )
            planned.append((digest, local,
                            signed_upload_target(entry, supabase_url)))

        log(f'Uploading {len(planned)} asset object(s) '
            f'({len(chunk) - len(missing)} already present)...')

        # Collected rather than raised on the first failure, so the author sees
        # every broken file in one run instead of fixing them one publish at a
        # time.
        failures: list[str] = []
        workers = max(1, min(concurrency, len(planned)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(upload_asset_bytes, target, local,
                            extension_by_digest.get(digest, '')): (digest, local)
                for digest, local, target in planned
            }
            for future in concurrent.futures.as_completed(futures):
                digest, local = futures[future]
                try:
                    written = future.result()
                except RuntimeError as e:
                    failures.append(str(e))
                    continue
                result['uploaded'] += 1
                result['bytes_uploaded'] += written
                # written == 0 means the object was already there (a 409, which
                # logged its own warning) — saying "uploaded 0 bytes" would read
                # as a successful transfer of nothing.
                if written:
                    log(f'  uploaded {os.path.basename(local)} '
                        f'({written:,} bytes)')

        if failures:
            for message in failures:
                log(f'ERROR: {message}')
            raise RuntimeError(
                f'{len(failures)} asset upload(s) failed; the manifest was '
                f'not sent. Fix the files above and re-run publish — assets '
                f'that did upload are content-addressed and will not be '
                f're-sent.'
            )

    return result


# ============================================================================
# Publishing
# ============================================================================

def publish(bookshelf_url: str, token: str, manifest: dict) -> dict:
    """Publish a book via the Bookshelf API.

    Sends the manifest as a gzip-compressed PUT request to /api/books/<slug>.
    Falls back to uncompressed if the server returns 415 Unsupported Media Type.

    Args:
        bookshelf_url: Deployed bookshelf URL.
        token: JWT access token from authenticate().
        manifest: Publish manifest dict (title, author, slug, chapters, etc.).

    Returns:
        Response dict with ok, book_id, slug, published, highlights, cover_uploaded.

    Raises:
        RuntimeError: If the API returns an error.
    """
    import gzip

    slug = manifest.get('slug', '')
    if not slug:
        raise RuntimeError('Manifest missing slug field')

    url = f'{bookshelf_url.rstrip("/")}/api/books/{urllib.parse.quote(slug)}'
    raw_body = json.dumps(manifest, ensure_ascii=False).encode()

    # Log manifest size breakdown
    _log_manifest_size(manifest, raw_body)

    # Gzip compress the body
    compressed_body = gzip.compress(raw_body)
    log(f'Manifest compressed: {len(raw_body):,} → {len(compressed_body):,} bytes '
        f'({100 - len(compressed_body) * 100 // len(raw_body)}% reduction)')

    headers = {
        'Content-Type': 'application/json',
        'Content-Encoding': 'gzip',
        'Authorization': f'Bearer {token}',
    }

    req = urllib.request.Request(url, data=compressed_body, headers=headers, method='PUT')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 415:
            # Server doesn't support gzip — fall back to uncompressed
            log('Server does not support gzip, retrying uncompressed...')
            headers.pop('Content-Encoding')
            req = urllib.request.Request(url, data=raw_body, headers=headers, method='PUT')
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e2:
                e = e2  # fall through to error handling below

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


def _log_manifest_size(manifest: dict, raw_body: bytes) -> None:
    """Log a breakdown of manifest component sizes."""
    parts = []
    # Images are not in the manifest at all — they travel as bytes via
    # sync_assets, and only their metadata rides along in `assets`.
    for key in ('dashboard_html', 'dashboard_data'):
        val = manifest.get(key)
        if val:
            size = len(json.dumps(val, ensure_ascii=False).encode())
            if size > 10_000:
                parts.append(f'{key}: {size:,} bytes')
    chapters_size = len(json.dumps(manifest.get('chapters', []), ensure_ascii=False).encode())
    parts.append(f'chapters: {chapters_size:,} bytes')
    parts.append(f'total: {len(raw_body):,} bytes')
    log(f'Manifest size: {"; ".join(parts)}')


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
