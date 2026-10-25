"""Authenticated Google Drive download (service account, read-only).

Lets a card's `Asset Link` point at a PRIVATE Google Drive file (share URL or
bare file ID) and have it streamed straight into the Meta upload — any size, no
public-sharing, no virus-scan interstitial that the unauthenticated download path
trips over on big files.

How it works: a service-account JSON key (path in env var
`GOOGLE_APPLICATION_CREDENTIALS`, surfaced through config.py) is used to call the
Drive API `files.get(alt=media)` with a chunked `MediaIoBaseDownload` to a temp
file. The Drive folder must be shared with the service account's email (Viewer).

This module is OPTIONAL: with no key configured, callers fall back to the public
share-link / local logic in media.py. Google libraries are imported lazily inside
functions so the package (and its test suite) imports without them and the tool
still runs when Drive is unused.

Read-only to Drive (scope `drive.readonly`). Touches nothing on Meta.
"""

from __future__ import annotations

import io
import os
import re
import tempfile

from .client import MetaError

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
OAUTH_SCOPES = [DRIVE_SCOPE]

# Drive ids are URL-safe base64-ish tokens; match the standard share-URL shapes
# first, then a bare id. Ordered most-specific to least.
_ID_PATTERNS = (
    re.compile(r"/file/d/([A-Za-z0-9_-]+)"),         # /file/d/<id>/view
    re.compile(r"/folders/([A-Za-z0-9_-]+)"),        # /drive/folders/<id>
    re.compile(r"[?&]id=([A-Za-z0-9_-]+)"),          # ?id=<id> / &id=<id>
    re.compile(r"/d/([A-Za-z0-9_-]+)"),              # /document/d/<id>, /d/<id>
)
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def is_drive_ref(value: str) -> bool:
    """True if `value` looks like a Drive share URL or a bare Drive file id."""
    if not value:
        return False
    v = value.strip()
    if "drive.google.com" in v or "docs.google.com" in v:
        return True
    # A bare id only — never treat a generic http(s) URL as a Drive ref.
    return bool(_BARE_ID_RE.match(v)) and not v.lower().startswith(
        ("http://", "https://")
    )


def extract_file_id(url_or_id: str) -> str:
    """Pull the Drive file/folder id from a share URL, or accept a bare id.

    Handles `/file/d/<id>/`, `?id=<id>`/`&id=<id>`, `/folders/<id>`,
    `/document/d/<id>`, and a bare `<id>`. Raises MetaError if nothing usable is
    found.
    """
    if not (url_or_id and url_or_id.strip()):
        raise MetaError(
            "No Google Drive link or file id was given.",
            code="ASSET_MISSING",
            fix="Provide a Drive share URL or a file id.",
        )
    v = url_or_id.strip()

    if v.lower().startswith(("http://", "https://")) or "drive.google.com" in v:
        for pat in _ID_PATTERNS:
            m = pat.search(v)
            if m:
                return m.group(1)
        raise MetaError(
            f"Couldn't find a Google Drive file id in '{v}'.",
            code="ASSET_UNREACHABLE",
            fix=(
                "Use a link like https://drive.google.com/file/d/<id>/view, or "
                "paste the file id directly."
            ),
        )

    if _BARE_ID_RE.match(v):
        return v

    raise MetaError(
        f"'{v}' isn't a recognisable Google Drive link or file id.",
        code="ASSET_UNREACHABLE",
        fix="Paste a Drive share URL or the file id.",
    )


def _load_credentials(credentials_path: str | None):
    """Build read-only Drive service-account credentials, or raise a clear error
    if the key isn't configured / readable. Google libs imported lazily."""
    if not credentials_path:
        raise MetaError(
            "Google Drive credentials aren't configured.",
            code="DRIVE_NO_CREDS",
            fix=(
                "Set GOOGLE_APPLICATION_CREDENTIALS in .env to the path of a "
                "service-account JSON key, then share the Drive folder with the "
                "service account's email (Viewer). See DRIVE-SETUP.md."
            ),
        )
    if not os.path.exists(credentials_path):
        raise MetaError(
            f"The Google Drive credentials file wasn't found at "
            f"'{credentials_path}'.",
            code="DRIVE_NO_CREDS",
            fix=(
                "Fix the GOOGLE_APPLICATION_CREDENTIALS path in .env (it must "
                "point at the service-account JSON key). See DRIVE-SETUP.md."
            ),
        )
    try:
        from google.oauth2 import service_account
    except ImportError:
        raise MetaError(
            "Google API libraries aren't installed in this environment.",
            code="DRIVE_NO_CREDS",
            fix=(
                "Run `pip install google-api-python-client google-auth` in the "
                "tool's venv. See DRIVE-SETUP.md."
            ),
        )
    try:
        return service_account.Credentials.from_service_account_file(
            credentials_path, scopes=[DRIVE_SCOPE]
        )
    except (ValueError, KeyError) as exc:
        raise MetaError(
            f"The Google Drive credentials file isn't a valid service-account "
            f"key ({exc}).",
            code="DRIVE_NO_CREDS",
            fix=(
                "Re-download the JSON key from Google Cloud Console (IAM & Admin "
                "> Service Accounts > Keys). See DRIVE-SETUP.md."
            ),
        )


def service_account_email(credentials_path: str | None) -> str | None:
    """The service account's email (for 'share the folder with this address'
    messaging), or None if creds aren't configured/valid."""
    try:
        creds = _load_credentials(credentials_path)
    except MetaError:
        return None
    return getattr(creds, "service_account_email", None)


# --- OAuth user login: the keyless path (works under orgs blocking SA keys) ---


def _load_oauth_user_credentials(client_path: str | None, token_path: str | None):
    """Load stored OAuth user creds, refreshing + re-saving if expired. Raises a
    clear MetaError pointing at `drive-auth` when no valid token exists yet."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        raise MetaError(
            "Google auth libraries aren't installed in this environment.",
            code="DRIVE_NO_CREDS",
            fix=(
                "Run `pip install google-api-python-client google-auth "
                "google-auth-oauthlib` in the tool's venv. See DRIVE-SETUP.md."
            ),
        )
    if not (token_path and os.path.exists(token_path)):
        raise MetaError(
            "You haven't signed in to Google Drive yet.",
            code="DRIVE_NO_CREDS",
            fix=(
                "Run `python3 -m meta_uploader drive-auth` once to sign in (it "
                "opens a browser). See DRIVE-SETUP.md."
            ),
        )
    creds = Credentials.from_authorized_user_file(token_path, OAUTH_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            try:
                with open(token_path, "w") as fh:
                    fh.write(creds.to_json())
            except OSError:
                pass
        else:
            raise MetaError(
                "Your Google Drive sign-in has expired and can't refresh.",
                code="DRIVE_NO_CREDS",
                fix="Run `python3 -m meta_uploader drive-auth` to sign in again.",
            )
    return creds


def oauth_account_email(creds) -> str | None:
    """The signed-in Google account's email (for reporting), or None."""
    try:
        from googleapiclient.discovery import build

        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        about = service.about().get(fields="user").execute()
        return (about.get("user") or {}).get("emailAddress")
    except Exception:  # noqa: BLE001 - reporting only
        return None


def run_oauth_flow(client_path: str | None, token_path: str | None) -> str | None:
    """One-time interactive consent: opens a browser, stores the refresh token at
    `token_path`, and returns the signed-in account email. Google libs lazy."""
    if not (client_path and os.path.exists(client_path)):
        raise MetaError(
            f"OAuth client file not found at '{client_path}'.",
            code="DRIVE_NO_CREDS",
            fix=(
                "Create a Desktop OAuth client in Google Cloud Console and save "
                "its JSON to .secrets/oauth_client.json. See DRIVE-SETUP.md."
            ),
        )
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise MetaError(
            "google-auth-oauthlib isn't installed in this environment.",
            code="DRIVE_NO_CREDS",
            fix="Run `pip install google-auth-oauthlib` in the tool's venv.",
        )
    flow = InstalledAppFlow.from_client_secrets_file(client_path, OAUTH_SCOPES)
    creds = flow.run_local_server(port=0)
    os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
    with open(token_path, "w") as fh:
        fh.write(creds.to_json())
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return oauth_account_email(creds)


def configured_method(cfg) -> str | None:
    """Which Drive auth is set up, by file presence only (no network):
    'oauth-user', 'service-account', or None."""
    token = getattr(cfg, "google_oauth_token", "") or ""
    client = getattr(cfg, "google_oauth_client", "") or ""
    sa = getattr(cfg, "google_application_credentials", "") or ""
    if (token and os.path.exists(token)) or (client and os.path.exists(client)):
        return "oauth-user"
    if sa and os.path.exists(sa):
        return "service-account"
    return None


def load_drive_credentials(cfg):
    """Resolve Drive credentials from config, OAuth-first (the keyless path that
    works under orgs blocking service-account keys), then a service-account key.
    Returns (creds, method). Raises DRIVE_NO_CREDS with both options if nothing
    is set up."""
    token = getattr(cfg, "google_oauth_token", "") or ""
    client = getattr(cfg, "google_oauth_client", "") or ""
    sa = getattr(cfg, "google_application_credentials", "") or ""
    if (token and os.path.exists(token)) or (client and os.path.exists(client)):
        return _load_oauth_user_credentials(client, token), "oauth-user"
    if sa:
        return _load_credentials(sa), "service-account"
    raise MetaError(
        "Google Drive isn't connected yet.",
        code="DRIVE_NO_CREDS",
        fix=(
            "Drop a Desktop OAuth client JSON at .secrets/oauth_client.json and "
            "run `python3 -m meta_uploader drive-auth` (recommended), or set "
            "GOOGLE_APPLICATION_CREDENTIALS to a service-account key. See "
            "DRIVE-SETUP.md."
        ),
    )


def account_email(creds, method: str) -> str | None:
    """Email for the active auth method (for reporting / share-with messaging)."""
    if method == "service-account":
        return getattr(creds, "service_account_email", None)
    return oauth_account_email(creds)


def _build_service(credentials_path: str | None = None, creds=None):
    """Authenticated Drive v3 service. Pass a ready `creds` object (e.g. OAuth
    user login) or a service-account key path. Google libs imported lazily."""
    creds = creds or _load_credentials(credentials_path)
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _suffix_for(name: str | None, mime_type: str | None) -> str:
    """Best-effort file extension from the Drive filename, then the MIME type."""
    if name:
        ext = os.path.splitext(name)[1].lower()
        if ext and ext != ".bin":
            return ext
    if mime_type:
        import mimetypes

        ext = (mimetypes.guess_extension(mime_type.split(";")[0].strip()) or "").lower()
        if ext and ext != ".bin":
            return ext
    return ""


def get_metadata(file_id: str, credentials_path: str | None = None, creds=None) -> dict:
    """name + mimeType + size for a Drive file, mapping API errors to MetaError."""
    service = _build_service(credentials_path, creds=creds)
    try:
        return (
            service.files()
            .get(fileId=file_id, fields="id,name,mimeType,size", supportsAllDrives=True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 - normalised below
        _raise_for_drive_error(exc, file_id, credentials_path)


def download_file(
    file_id: str,
    dest: str | None = None,
    credentials_path: str | None = None,
    chunk_size: int = 32 * 1024 * 1024,
    on_progress=None,
    creds=None,
) -> str:
    """Download a private Drive file to a temp path and return it.

    Chunked (`MediaIoBaseDownload`) so files of any size stream without loading
    into memory. `dest` overrides the temp path. `on_progress(fraction)` is called
    after each chunk if given. Errors are mapped to actionable MetaErrors.
    """
    from googleapiclient.http import MediaIoBaseDownload

    service = _build_service(credentials_path, creds=creds)

    meta = get_metadata(file_id, credentials_path, creds=creds)
    suffix = _suffix_for(meta.get("name"), meta.get("mimeType"))

    if dest:
        path = dest
    else:
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="meta_drive_")
        os.close(fd)

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    try:
        with open(path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if on_progress and status:
                    on_progress(status.progress())
    except Exception as exc:  # noqa: BLE001 - normalised below
        try:
            os.remove(path)
        except OSError:
            pass
        _raise_for_drive_error(exc, file_id, credentials_path)

    return path


def _raise_for_drive_error(exc: Exception, file_id: str, credentials_path: str | None):
    """Translate a googleapiclient error into an operator-friendly MetaError."""
    if isinstance(exc, MetaError):
        raise exc

    status = None
    try:
        from googleapiclient.errors import HttpError

        if isinstance(exc, HttpError):
            status = getattr(getattr(exc, "resp", None), "status", None)
    except ImportError:
        pass

    sa_email = service_account_email(credentials_path) or (
        "the Google account this tool is signed in as"
    )

    if status in (403, 404):
        raise MetaError(
            f"Google Drive denied access to file '{file_id}' (HTTP {status}).",
            code="ASSET_UNREACHABLE",
            fix=(
                f"Make sure {sa_email} can view the file or its folder (Viewer "
                "access) in Google Drive, then try again."
            ),
        )
    if status == 401:
        raise MetaError(
            "Google Drive rejected the service-account credentials (HTTP 401).",
            code="DRIVE_NO_CREDS",
            fix=(
                "The key may be revoked or the Drive API not enabled. Re-check "
                "GOOGLE_APPLICATION_CREDENTIALS and the Cloud project. See "
                "DRIVE-SETUP.md."
            ),
        )
    raise MetaError(
        f"Couldn't download from Google Drive ({exc}).",
        code="ASSET_UNREACHABLE",
        fix=(
            f"Confirm the file id is correct and that {sa_email} can view it, "
            "then try again."
        ),
    )
