"""Media Library uploads + asset resolution.

- resolve_asset: turn an asset URL (Google Drive / direct link) into a local temp file (+ type)
- upload_image: -> image_hash
- upload_video: -> video_id, with a bounded processing wait + thumbnail (FR-004/005/006)
"""

from __future__ import annotations

import mimetypes
import os
import re
import tempfile
import time

import requests

from . import drive
from .client import GraphClient, MetaError

# A last-resort hint for the rare asset whose extension and content-type are both
# unknown; classification keys off the file extension first (see _classify).
VIDEO_FORMATS = frozenset({"video"})
_VIDEO_EXTS = frozenset({".mov", ".mp4", ".mkv", ".avi", ".webm", ".m4v"})
_IMAGE_EXTS = frozenset({".png", ".jpg", ".webp", ".gif", ".jpeg"})


def is_video_format(fmt: str | None) -> bool:
    return bool(fmt) and fmt.strip() in VIDEO_FORMATS


def normalize_drive_url(url: str) -> str:
    """Rewrite a Google Drive share link to a direct-download URL."""
    m = re.search(r"drive\.google\.com/file/d/([^/]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    m = re.search(r"drive\.google\.com/(?:open|uc)\?(?:[^&]*&)*id=([^&]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def _classify(path: str, content_type: str | None, fmt: str | None) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _IMAGE_EXTS:
        return "image"
    if content_type:
        if content_type.startswith("video/"):
            return "video"
        if content_type.startswith("image/"):
            return "image"
    if is_video_format(fmt):
        return "video"
    return "image"


def resolve_asset(
    asset_link: str,
    fmt: str | None = None,
    session: requests.Session | None = None,
    credentials_path: str | None = None,
    creds=None,
) -> dict:
    """Download asset_link to a temp file. Returns {file, type}.

    A Google Drive reference (share URL or bare file id) is downloaded via the
    authenticated Drive API when Drive credentials are available — a ready
    `creds` object (OAuth user login) or a service-account key path. This works
    for PRIVATE files of any size with no virus-scan interstitial. With no creds
    (the default), the existing public share-link / direct-URL path is used, so
    behaviour is unchanged when Drive auth isn't configured.
    """
    if not (asset_link and asset_link.strip()):
        raise MetaError(
            "No asset URL or file path to upload.",
            code="ASSET_MISSING",
            fix="Provide the creative's Google Drive link, a direct URL, or a local file path.",
        )

    link = asset_link.strip()

    # Authenticated Drive path: when this looks like a Drive ref AND we have
    # Drive credentials (an OAuth creds object or a SA key path). Otherwise fall
    # through to the existing public-URL / direct-download logic untouched.
    if (creds is not None or credentials_path) and drive.is_drive_ref(link):
        file_id = drive.extract_file_id(link)
        path = drive.download_file(
            file_id, credentials_path=credentials_path, creds=creds
        )
        return {"file": path, "type": _classify(path, None, fmt)}

    url = normalize_drive_url(link)
    sess = session or requests.Session()
    try:
        resp = sess.get(url, stream=True, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise MetaError(
            f"Couldn't download the asset from its link ({exc}).",
            code="ASSET_UNREACHABLE",
            fix=(
                "Check the asset URL is shared/public (a Google Drive 'anyone "
                "with the link' or a direct file URL)."
            ),
        )

    content_type = (
        resp.headers.get("content-type", "").split(";")[0].strip() or None
    )

    cd = resp.headers.get("content-disposition", "")
    cd_name = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    suffix = (
        (
            os.path.splitext(cd_name.group(1).strip())[1]
            if cd_name
            else ""
        )
        or os.path.splitext(url.split("?")[0])[1]
        or mimetypes.guess_extension(content_type or "")
        or ""
    ).lower()
    if suffix == ".bin":
        suffix = ""

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="tcc_asset_")
    with os.fdopen(fd, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            fh.write(chunk)

    return {"file": path, "type": _classify(path, content_type, fmt)}


def upload_image(client: GraphClient, file_path: str) -> dict:
    with open(file_path, "rb") as fh:
        resp = client.post(f"{client.account_id}/adimages", files={"file": fh})
    images = resp.get("images") or {}
    if not images:
        raise MetaError(
            "Meta accepted the image upload but returned no hash.",
            code="ASSET_REJECTED",
        )
    first = next(iter(images.values()))
    return {"image_hash": first["hash"]}


def upload_video(
    client: GraphClient,
    file_path: str,
    timeout: int = 300,
    poll_interval: int = 5,
    on_progress=None,
) -> dict:
    with open(file_path, "rb") as fh:
        resp = client.post(f"{client.account_id}/advideos", files={"file": fh})
    video_id = resp.get("id")
    if not video_id:
        raise MetaError(
            "Video upload failed (no video id returned).",
            code="ASSET_REJECTED",
        )

    waited = 0
    while waited < timeout:
        status = client.get(video_id, params={"fields": "status"}).get("status") or {}
        video_status = status.get("video_status")
        if video_status == "ready":
            return {
                "video_id": video_id,
                "thumbnail": _best_thumbnail(client, video_id),
            }
        if video_status == "error":
            raise MetaError(
                "Meta could not process this video.",
                code="VIDEO_PROCESSING",
                fix="Check the video meets Meta's format/length limits, then try again.",
            )
        if on_progress:
            on_progress(f"video processing… ({waited}s)")
        time.sleep(poll_interval)
        waited += poll_interval

    raise MetaError(
        f"Video was still processing after {timeout}s.",
        code="VIDEO_PROCESSING",
        fix="Try again, or raise the timeout with --timeout.",
    )


def _best_thumbnail(client: GraphClient, video_id: str) -> dict:
    data = client.get(f"{video_id}/thumbnails").get("data", [])
    if not data:
        return {}
    preferred = next((t for t in data if t.get("is_preferred")), data[0])
    uri = preferred.get("uri")
    if uri:
        return {"image_url": uri}
    return {}
