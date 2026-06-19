"""Command-line surface for the Meta uploader.

Run as:  python3 -m meta_uploader <subcommand> [args]

Every subcommand prints JSON to stdout and exits 0 on success / non-zero on error.
Create commands accept --dry-run, which prints the exact Graph API payloads and
the resulting ad name WITHOUT calling Meta (nothing is created).

This file is the only place that wires config -> client -> the Meta operations.
The orchestration layer (e.g. a Claude session) builds the inputs and calls these
subcommands.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .client import GraphClient, MetaError
from .config import Config, ConfigError, CONFIG_PATH, ENV_PATH, load_config
from . import ads as ads_mod
from . import creative as creative_mod
from . import drive as drive_mod
from . import media as media_mod

EXIT = {
    "ok": 0,
    "unexpected": 1,
    "config": 2,
    "asset": 3,
    "api": 4,
    "needs_input": 5,
}

_CODE_TO_EXIT = {
    "AUTH": EXIT["config"],
    "DRIVE_NO_CREDS": EXIT["config"],
    "ASSET_MISSING": EXIT["asset"],
    "ASSET_UNREACHABLE": EXIT["asset"],
    "ASSET_REJECTED": EXIT["asset"],
    "VIDEO_PROCESSING": EXIT["asset"],
    "NEEDS_INPUT": EXIT["needs_input"],
    "BAD_CTA": EXIT["needs_input"],
    "API": EXIT["api"],
}


def _print(obj: dict) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _client(cfg: Config) -> GraphClient:
    return GraphClient(
        cfg.access_token, cfg.graph_api_version, account_id=cfg.ad_account_id
    )


def _resolve_link(copy: dict, cfg: Config) -> None:
    if not copy.get("link"):
        if cfg.default_link_url:
            copy["link"] = cfg.default_link_url


def _as_local_file(
    file_ref: str, fmt_hint: str | None = None, cfg: Config | None = None
) -> str:
    """Accept a local path OR a remote/Drive reference and return a local file path.

    Remote refs are downloaded to a temp file via media.resolve_asset. A Google
    Drive reference (share URL or bare file id) goes through the authenticated
    Drive API when Drive is connected — OAuth user login (preferred) or a
    service-account key — so PRIVATE files of any size stream straight in;
    otherwise the public share-link / direct-URL path is used. This lets a
    card's Asset Link be used directly instead of a pre-downloaded file."""
    if not isinstance(file_ref, str):
        return file_ref
    ref = file_ref.strip()
    is_http = ref.lower().startswith(("http://", "https://"))
    is_drive = drive_mod.is_drive_ref(ref)
    drive_url = is_drive and ("google.com" in ref)
    bare_drive_id = is_drive and not is_http and not drive_url

    creds = None
    if cfg is not None and is_drive:
        try:
            creds, _ = drive_mod.load_drive_credentials(cfg)
        except MetaError:
            creds = None  # not connected — fall back to public/local handling

    # Remote (download to temp) when: an http(s) URL, a Drive share URL, or a
    # bare Drive id we can actually authenticate. A bare id without creds can't
    # be fetched, so leave it as a path and let normal file handling report it.
    if is_http or drive_url or (bare_drive_id and creds is not None):
        return media_mod.resolve_asset(ref, fmt=fmt_hint, creds=creds)["file"]
    return file_ref


def cmd_whoami(args, cfg: Config) -> dict:
    client = _client(cfg)
    me = client.get("me", params={"fields": "id,name"})
    acct = client.get(cfg.ad_account_id, params={"fields": "name,currency,account_status"})
    # Drive is optional; report how it's wired up by file presence only (no
    # network call, and never failing whoami).
    method = drive_mod.configured_method(cfg)
    if method:
        drive_info = {
            "configured": True,
            "method": method,
            "note": "Run `drive-check` to test access.",
        }
    else:
        drive_info = {"configured": False}
    return {
        "user": me,
        "ad_account": {"id": cfg.ad_account_id, **acct},
        "page_id": cfg.page_id,
        "instagram_actor_id": cfg.instagram_actor_id or None,
        "default_link_url": cfg.default_link_url or None,
        "api_version": cfg.graph_api_version,
        "drive": drive_info,
    }


def cmd_drive_check(args, cfg: Config) -> dict:
    """Verify Google Drive auth (OAuth user login or service-account) and,
    optionally, test reading a file. How the operator confirms access AFTER
    signing in / sharing a folder. Never writes; reads metadata only.

    Returns a clean message (not an exception) if Drive isn't connected — the
    feature is optional.
    """
    try:
        creds, method = drive_mod.load_drive_credentials(cfg)
    except MetaError as exc:
        return {"drive_auth": "not_connected", **exc.to_dict()}

    email = drive_mod.account_email(creds, method)
    out = {
        "drive_auth": "ok",
        "method": method,
        "account": email,
        "next": (
            "Drive is connected. Re-run with --file <url|id> to confirm access "
            "to a specific file."
        ),
    }

    if args.file:
        file_id = drive_mod.extract_file_id(args.file)
        meta = drive_mod.get_metadata(file_id, creds=creds)
        out["file_check"] = {
            "input": args.file,
            "file_id": file_id,
            "name": meta.get("name"),
            "mime_type": meta.get("mimeType"),
            "size_bytes": int(meta["size"]) if meta.get("size") else None,
            "readable": True,
        }
        out["next"] = "Drive access confirmed — this file can be streamed into an upload."
    return out


def cmd_drive_auth(args, cfg: Config) -> dict:
    """One-time browser sign-in for Google Drive (OAuth user login). Saves a
    refresh token to .secrets/drive_token.json — no service-account key needed,
    so it works under orgs that block SA keys."""
    email = drive_mod.run_oauth_flow(cfg.google_oauth_client, cfg.google_oauth_token)
    return {
        "drive_auth": "connected",
        "signed_in_as": email,
        "token_saved": cfg.google_oauth_token,
        "next": (
            "Run `python3 -m meta_uploader drive-check --file <drive-url>` to "
            "confirm access to a file."
        ),
    }


def cmd_list_campaigns(args, cfg: Config) -> dict:
    client = _client(cfg)
    params = {"fields": "id,name,objective,status", "limit": 100}
    if args.status and args.status != "all":
        params["effective_status"] = json.dumps([args.status.upper()])
    return {"campaigns": client.get_all(f"{cfg.ad_account_id}/campaigns", params)}


def cmd_list_adsets(args, cfg: Config) -> dict:
    client = _client(cfg)
    params = {"fields": "id,name,campaign_id,status", "limit": 100}
    path = f"{args.campaign}/adsets" if args.campaign else f"{cfg.ad_account_id}/adsets"
    return {"adsets": client.get_all(path, params)}


def cmd_upload_image(args, cfg: Config) -> dict:
    return media_mod.upload_image(_client(cfg), args.file)


def cmd_upload_video(args, cfg: Config) -> dict:
    return media_mod.upload_video(
        _client(cfg),
        args.file,
        timeout=args.timeout,
        on_progress=lambda m: print(m, file=sys.stderr),
    )


def cmd_create_adset(args, cfg: Config) -> dict:
    targeting = json.loads(open(args.targeting_json).read()) if args.targeting_json else None
    if args.dry_run:
        return {
            "dry_run": True,
            "would_create_adset": {
                "name": args.name,
                "campaign_id": args.campaign,
                "status": "PAUSED",
                "optimization_goal": args.optimization_goal,
                "billing_event": args.billing_event,
                "daily_budget": args.daily_budget,
                "targeting_automation": {"advantage_audience": 0},
            },
        }
    adset_id = ads_mod.create_adset(
        _client(cfg),
        campaign_id=args.campaign,
        name=args.name,
        optimization_goal=args.optimization_goal,
        billing_event=args.billing_event,
        daily_budget=args.daily_budget,
        targeting=targeting,
    )
    return {
        "adset_id": adset_id,
        "name": args.name,
        "campaign_id": args.campaign,
        "status": "PAUSED",
    }


def cmd_create_ad(args, cfg: Config) -> dict:
    copy = {
        "message": args.message,
        "headline": args.headline,
        "link": args.link,
        "cta": args.cta,
    }
    _resolve_link(copy, cfg)
    if args.image_hash:
        asset = {"type": "image", "image_hash": args.image_hash}
    else:
        asset = {
            "type": "video",
            "video_id": args.video_id,
            "thumbnail": {"image_hash": args.thumbnail_hash} if args.thumbnail_hash else {},
        }
    return _build_and_create(
        cfg,
        args.name,
        args.adset,
        asset,
        copy,
        dry_run=args.dry_run,
    )


def cmd_create_from_json(args, cfg: Config) -> dict:
    if args.file != "-":
        spec = json.loads(open(args.file).read())
    else:
        spec = json.load(sys.stdin)

    copy = dict(spec.get("copy") or {})
    _resolve_link(copy, cfg)
    name = spec["name"]
    asset_in = spec.get("asset") or {}

    if args.dry_run:
        if asset_in.get("type") == "image":
            placeholder = {"type": "image", "image_hash": "<uploaded-at-runtime>"}
        elif asset_in.get("type") == "carousel":
            placeholder = {
                "type": "carousel",
                "cards": [
                    {
                        "image_hash": f"<card-{i + 1}-at-runtime>",
                        "link": c.get("link"),
                        "name": c.get("name"),
                        "description": c.get("description"),
                        "cta": c.get("cta"),
                    }
                    for i, c in enumerate(asset_in.get("cards") or [])
                ],
            }
        else:
            placeholder = {
                "type": "video",
                "video_id": "<uploaded-at-runtime>",
                "thumbnail": {"image_url": "<thumbnail-at-runtime>"},
            }
        adset_id = spec.get("adset_id") or "<new-adset-at-runtime>"
        return _build_and_create(
            cfg,
            name,
            adset_id,
            placeholder,
            copy,
            dry_run=True,
            new_adset=spec.get("new_adset"),
        )

    client = _client(cfg)

    if asset_in.get("type") == "image":
        asset = {
            "type": "image",
            **media_mod.upload_image(
                client, _as_local_file(asset_in["file"], "Static", cfg)
            ),
        }
    elif asset_in.get("type") == "carousel":
        cards_out = []
        for i, card in enumerate(asset_in.get("cards") or []):
            up = media_mod.upload_image(
                client, _as_local_file(card["file"], "Static", cfg)
            )
            cards_out.append(
                {
                    "image_hash": up["image_hash"],
                    "link": card.get("link"),
                    "name": card.get("name"),
                    "description": card.get("description"),
                    "cta": card.get("cta"),
                }
            )
            print(
                f"uploaded carousel card {i + 1}/{len(asset_in['cards'])}",
                file=sys.stderr,
            )
        asset = {"type": "carousel", "cards": cards_out}
    else:
        asset = {
            "type": "video",
            **media_mod.upload_video(
                client,
                _as_local_file(asset_in["file"], "video", cfg),
                timeout=int(spec.get("video_timeout", 300)),
                on_progress=lambda m: print(m, file=sys.stderr),
            ),
        }
        if spec.get("thumbnail_file"):
            asset["thumbnail"] = media_mod.upload_image(
                client, _as_local_file(spec["thumbnail_file"], "Static", cfg)
            )

    adset_id = spec.get("adset_id")
    created_adset = None
    if not adset_id and spec.get("new_adset"):
        na = spec["new_adset"]
        adset_id = ads_mod.create_adset(
            client,
            na["campaign_id"],
            na.get("name", name),
            na.get("optimization_goal", "OFFSITE_CONVERSIONS"),
            na.get("billing_event", "IMPRESSIONS"),
            daily_budget=na.get("daily_budget"),
            targeting=na.get("targeting"),
        )
        created_adset = {
            "adset_id": adset_id,
            "campaign_id": na["campaign_id"],
            "status": "PAUSED",
        }

    if not adset_id:
        raise MetaError(
            "No destination ad set. Provide adset_id or new_adset.",
            code="NEEDS_INPUT",
        )

    out = _build_and_create(
        cfg,
        name,
        adset_id,
        asset,
        copy,
        dry_run=False,
        client=client,
    )
    if created_adset:
        out["created_adset"] = created_adset
    return out


def cmd_setup(args, cfg: Config) -> dict:
    """Write .env + config.json. Optionally exchange a short-lived token for a long-lived one."""
    token = args.token
    exchanged = False
    if args.exchange:
        if not (args.app_id and args.app_secret and token):
            raise MetaError(
                "Exchange needs --token, --app-id and --app-secret.",
                code="NEEDS_INPUT",
            )
        import requests

        r = requests.get(
            f"https://graph.facebook.com/{args.api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": args.app_id,
                "client_secret": args.app_secret,
                "fb_exchange_token": token,
            },
            timeout=60,
        )
        data = r.json()
        if "access_token" not in data:
            raise MetaError(
                "Token exchange failed: " + json.dumps(data.get("error", data)),
                code="API",
            )
        token = data["access_token"]
        exchanged = True

    ENV_PATH.write_text(f"META_ACCESS_TOKEN={token}\n")
    config = {
        "ad_account_id": args.ad_account_id,
        "page_id": args.page_id,
        "instagram_actor_id": args.instagram_actor_id or "",
        "default_link_url": args.default_link_url or "",
        "graph_api_version": args.api_version,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    return {
        "wrote": [str(ENV_PATH), str(CONFIG_PATH)],
        "token_exchanged_to_long_lived": exchanged,
        "next": "Run `python3 -m meta_uploader whoami` to confirm the connection.",
    }


def _build_and_create(
    cfg: Config,
    name: str,
    adset_id: str,
    asset: dict,
    copy: dict,
    dry_run: bool = False,
    client=None,
    new_adset=None,
) -> dict:
    creative_payload = creative_mod.build_creative_payload(
        name, cfg.page_id, cfg.instagram_actor_id, asset, copy
    )
    ad_payload = {
        "name": name,
        "adset_id": adset_id,
        "creative": {"creative_id": "<created-at-runtime>"},
        "status": "PAUSED",
    }

    if dry_run:
        out = {
            "dry_run": True,
            "ad_name": name,
            "adset_id": adset_id,
            "adcreatives_payload": creative_payload,
            "ads_payload": ad_payload,
            "advantage_plus": (
                "per-feature opt-out pending (Meta deprecated the blanket field); "
                "effective state read back after create"
            ),
        }
        if new_adset:
            out["would_create_adset"] = {
                **new_adset,
                "status": "PAUSED",
                "targeting_automation": {"advantage_audience": 0},
            }
        return out

    client = client or _client(cfg)
    creative_id = ads_mod.create_creative(
        client, name, cfg.page_id, cfg.instagram_actor_id, asset, copy
    )
    ad_id = ads_mod.create_ad(client, name, adset_id, creative_id)
    effective = ads_mod.read_effective_enhancements(client, creative_id)
    ads_url = ads_mod.ads_manager_url(cfg.ad_account_id, ad_id)

    out = {
        "ad_id": ad_id,
        "creative_id": creative_id,
        "name": name,
        "adset_id": adset_id,
        "status": "PAUSED",
        "ads_manager_url": ads_url,
        "advantage_plus": {
            "note": "blanket opt-out deprecated by Meta; per-feature opt-out pending",
            "effective": effective,
        },
    }

    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="meta_uploader",
        description="Meta Ads uploader — Drive/URL/local asset -> PAUSED Meta ad.",
    )
    p.add_argument("--version", action="version", version=f"meta_uploader {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("whoami", help="Verify the connection (no writes).")

    sp = sub.add_parser(
        "drive-check",
        help=(
            "Verify Google Drive auth (OAuth or service account); optionally "
            "test reading a file. No writes."
        ),
    )
    sp.add_argument(
        "--file",
        help="A Drive share URL or file id to test read access to (optional).",
    )

    sub.add_parser(
        "drive-auth",
        help=(
            "One-time Google Drive sign-in (OAuth, opens a browser). Saves a "
            "token so private Drive files can stream straight into uploads."
        ),
    )

    sp = sub.add_parser("list-campaigns", help="List campaigns.")
    sp.add_argument("--status", choices=["active", "paused", "all"], default="all")

    sp = sub.add_parser("list-adsets", help="List ad sets.")
    sp.add_argument("--campaign", help="Limit to one campaign id.")

    sp = sub.add_parser("upload-image", help="Upload an image; returns image_hash.")
    sp.add_argument("--file", required=True)

    sp = sub.add_parser("upload-video", help="Upload a video; waits for processing.")
    sp.add_argument("--file", required=True)
    sp.add_argument("--timeout", type=int, default=300)

    sp = sub.add_parser(
        "create-adset", help="Create a PAUSED ad set under an existing campaign."
    )
    sp.add_argument("--campaign", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--optimization-goal", default="OFFSITE_CONVERSIONS")
    sp.add_argument("--billing-event", default="IMPRESSIONS")
    sp.add_argument("--daily-budget", type=int, help="Minor units (e.g. cents).")
    sp.add_argument("--targeting-json", help="Path to a targeting JSON file.")
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("create-ad", help="Create a PAUSED ad in an existing ad set.")
    sp.add_argument("--name", required=True)
    sp.add_argument("--adset", required=True)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--image-hash")
    g.add_argument("--video-id")
    sp.add_argument("--thumbnail-hash")
    sp.add_argument("--message", required=True)
    sp.add_argument("--headline", required=True)
    sp.add_argument("--link")
    sp.add_argument("--cta", default="SHOP_NOW")
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser(
        "create-from-json", help="Upload asset + create PAUSED ad from one JSON spec."
    )
    sp.add_argument("--file", required=True, help="Path to the spec JSON, or '-' for stdin.")
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser(
        "setup", help="Write .env + config.json (optionally exchange to a long-lived token)."
    )
    sp.add_argument("--token", required=True)
    sp.add_argument("--ad-account-id", required=True)
    sp.add_argument("--page-id", required=True)
    sp.add_argument("--instagram-actor-id", default="")
    sp.add_argument("--default-link-url", default="")
    sp.add_argument("--api-version", default="v21.0")
    sp.add_argument("--exchange", action="store_true", help="Exchange the token for a long-lived one.")
    sp.add_argument("--app-id")
    sp.add_argument("--app-secret")

    return p


_NEEDS_CONFIG = frozenset(
    {
        "whoami",
        "drive-check",
        "drive-auth",
        "list-campaigns",
        "list-adsets",
        "upload-image",
        "upload-video",
        "create-adset",
        "create-ad",
        "create-from-json",
    }
)

_HANDLERS = {
    "whoami": cmd_whoami,
    "drive-check": cmd_drive_check,
    "drive-auth": cmd_drive_auth,
    "list-campaigns": cmd_list_campaigns,
    "list-adsets": cmd_list_adsets,
    "upload-image": cmd_upload_image,
    "upload-video": cmd_upload_video,
    "create-adset": cmd_create_adset,
    "create-ad": cmd_create_ad,
    "create-from-json": cmd_create_from_json,
    "setup": cmd_setup,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = _HANDLERS[args.command]
    try:
        cfg = load_config() if args.command in _NEEDS_CONFIG else None
        result = handler(args, cfg)
        _print(result)
        return EXIT["ok"]
    except ConfigError as exc:
        _print({"error": str(exc), "code": "CONFIG"})
        return EXIT["config"]
    except MetaError as exc:
        _print(exc.to_dict())
        return _CODE_TO_EXIT.get(exc.code, EXIT["api"])
    except (KeyError, FileNotFoundError, ValueError) as exc:
        _print({"error": f"{type(exc).__name__}: {exc}", "code": "INPUT"})
        return EXIT["needs_input"]


if __name__ == "__main__":
    raise SystemExit(main())
