"""Load and validate the local config + secret access token.

Secrets live in two local files that are git-ignored:
  - .env          -> META_ACCESS_TOKEN (the only required secret),
                     GOOGLE_APPLICATION_CREDENTIALS (optional: path to a Google
                     service-account JSON key, for authenticated Drive downloads)
  - config.json   -> ad account / page / instagram / default link / api version

All validation errors are phrased for a non-technical operator and point back to
the README setup section.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is in the project venv
    load_dotenv = None

TOOL_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = TOOL_DIR / ".env"
CONFIG_PATH = TOOL_DIR / "config.json"

_API_VERSION_RE = re.compile(r"^v\d+\.\d+$")
_SETUP_HINT = "See README.md (Setup) or run `python3 -m meta_uploader setup`."


class ConfigError(Exception):
    """Raised when config/token is missing or invalid. Message is operator-friendly."""


@dataclass
class Config:
    access_token: str
    ad_account_id: str
    page_id: str
    instagram_actor_id: str
    default_link_url: str
    graph_api_version: str
    # Optional: Meta's "Ad transparency" advertiser id. Some regions (e.g.
    # Australia, from ~Sep 2026) won't deliver a NEW ad set without it. Read it
    # off an existing ad set's regional_regulation_identities.universal_beneficiary.
    advertiser_identity_id: str = ""
    # Optional: path to a Google service-account JSON key. When set, private
    # Google Drive assets are streamed straight into the upload via the
    # authenticated Drive API. Unset is fine — the tool falls back to the
    # public share-link / local-file path and works exactly as before.
    google_application_credentials: str = ""
    # Optional: OAuth user-login for Drive (the keyless path, for orgs that
    # block service-account keys). Paths to the Desktop OAuth client JSON and
    # the stored refresh token; both default into .secrets/. Created by
    # `drive-auth`. Preferred over the SA key when present.
    google_oauth_client: str = ""
    google_oauth_token: str = ""


def load_config(env_path: Path = ENV_PATH, config_path: Path = CONFIG_PATH) -> Config:
    """Load + validate. Raises ConfigError with a plain-language message on any problem."""
    if load_dotenv is not None and Path(env_path).exists():
        load_dotenv(env_path)

    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            f"No Meta access token found. Add META_ACCESS_TOKEN to {env_path}. "
            f"{_SETUP_HINT}"
        )

    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found at {config_path}. Copy config.example.json to "
            f"config.json and fill it in. {_SETUP_HINT}"
        )

    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"config.json isn't valid JSON ({exc}). Fix the file or recreate it "
            f"from config.example.json. {_SETUP_HINT}"
        )

    ad_account_id = str(raw.get("ad_account_id", "")).strip()
    page_id = str(raw.get("page_id", "")).strip()
    instagram_actor_id = str(raw.get("instagram_actor_id", "")).strip()
    default_link_url = str(raw.get("default_link_url", "")).strip()
    graph_api_version = str(raw.get("graph_api_version", "")).strip()

    if not (ad_account_id.startswith("act_") and ad_account_id[4:].isdigit()):
        raise ConfigError(
            "ad_account_id must look like 'act_1234567890' (got "
            f"'{ad_account_id or '<empty>'}'). Find it in Ads Manager's account "
            "picker. " + _SETUP_HINT
        )

    if not page_id:
        raise ConfigError("page_id is required in config.json. " + _SETUP_HINT)

    if default_link_url and not re.match(r"^https?://", default_link_url):
        raise ConfigError(
            f"default_link_url must start with http(s):// (got '{default_link_url}')."
        )

    if not _API_VERSION_RE.match(graph_api_version):
        raise ConfigError(
            f"graph_api_version must look like 'v21.0' (got "
            f"'{graph_api_version or '<empty>'}')."
        )

    # Optional, never required. Standard env var; expand ~ so a home-relative
    # path works. We do NOT check the file exists here — that's surfaced as an
    # actionable message only when a Drive download is actually attempted.
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if gac:
        gac = os.path.expanduser(gac)

    # OAuth user-login (keyless) — defaults into .secrets/ so no env var is
    # needed once `drive-auth` has run. Env vars override the defaults.
    secrets_dir = TOOL_DIR / ".secrets"
    oauth_client = os.environ.get("GOOGLE_OAUTH_CLIENT", "").strip()
    oauth_client = (
        os.path.expanduser(oauth_client)
        if oauth_client
        else str(secrets_dir / "oauth_client.json")
    )
    oauth_token = os.environ.get("GOOGLE_OAUTH_TOKEN", "").strip()
    oauth_token = (
        os.path.expanduser(oauth_token)
        if oauth_token
        else str(secrets_dir / "drive_token.json")
    )

    return Config(
        access_token=token,
        ad_account_id=ad_account_id,
        page_id=page_id,
        instagram_actor_id=instagram_actor_id,
        default_link_url=default_link_url,
        graph_api_version=graph_api_version,
        advertiser_identity_id=str(raw.get("advertiser_identity_id", "")).strip(),
        google_application_credentials=gac,
        google_oauth_client=oauth_client,
        google_oauth_token=oauth_token,
    )
