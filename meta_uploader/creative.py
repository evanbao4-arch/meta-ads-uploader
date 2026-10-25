"""Build the ad creative payload: object_story_spec + Advantage+ opt-out.

The Advantage+ opt-out is the hard requirement: every creative
runs exactly as built. We send a Standard-Enhancements OPT_OUT and the caller reads
the creative back to report anything Meta refused to disable.
"""

from __future__ import annotations

from .client import MetaError

ALLOWED_CTAS = frozenset(
    {
        "BUY_NOW",
        "SIGN_UP",
        "BOOK_TRAVEL",
        "SUBSCRIBE",
        "GET_QUOTE",
        "SHOP_NOW",
        "SEE_MORE",
        "GET_OFFER",
        "ORDER_NOW",
        "CONTACT_US",
        "LEARN_MORE",
        "DOWNLOAD",
        "NO_BUTTON",
    }
)


# Every Advantage+ creative enhancement Meta exposes, opted out one by one.
#
# Meta deprecated the single blanket `standard_enhancements` flag this helper
# used to send ("Including standard enhancements field in creative has been
# deprecated. Please choose to set individual features instead."), so any
# creative built with the old spec was REJECTED — and the create path quietly
# stopped sending an opt-out at all. Result: 177 ads in the account carry live
# enhancements we never chose. Found 2026-08-13 while rebuilding two ads.
#
# This list is read off a creative Meta accepted (Aug 2026). Meta adds features
# over time: if Ads Manager shows an enhancement switched on that isn't listed
# here, add its name to this tuple.
ADVANTAGE_PLUS_FEATURES = (
    "adapt_to_placement", "add_text_overlay", "ads_with_benefits",
    "advantage_plus_creative", "app_highlights", "audio", "biz_ai",
    "carousel_to_video", "catalog_feed_tag", "creative_stickers",
    "cv_transformation", "description_automation", "dha_optimization",
    "dynamic_partner_content", "enable_ncs_testimonials", "enhance_cta",
    "feed_caption_optimization", "generate_cta", "hide_price", "ig_glados_feed",
    "ig_video_native_subtitle", "image_animation", "image_auto_crop",
    "image_background_gen", "image_brightness_and_contrast", "image_enhancement",
    "image_templates", "image_text_translation", "image_touchups", "image_uncrop",
    "inline_comment", "local_store_extension", "media_liquidity_animated_image",
    "media_order", "media_type_automation", "multi_photo_to_video",
    "pac_recomposition", "pac_relaxation", "product_browsing",
    "product_extensions", "product_metadata_automation", "profile_card",
    "replace_media_text", "reveal_details_over_time", "show_destination_blurbs",
    "show_summary", "site_extensions", "standard_enhancements_catalog",
    "text_optimizations", "text_translation", "translate_voiceover",
    "video_auto_crop", "video_filtering", "video_highlight", "video_highlights",
    "video_to_image", "video_uncrop", "wa_mm_image_filtering",
)


def advantage_plus_optout_spec() -> dict:
    """degrees_of_freedom_spec that opts OUT of every Advantage+ enhancement.

    Per-feature, because Meta rejects the deprecated blanket field. An ad we
    built should look the way we built it — no auto-crop, no added text, no
    music, no restyling — so the read on the creative is a read on OUR creative.
    """
    return {
        "creative_features_spec": {
            feature: {"enroll_status": "OPT_OUT"}
            for feature in ADVANTAGE_PLUS_FEATURES
        }
    }


def _call_to_action(cta_type: str, link: str) -> dict:
    cta_type = (cta_type or "SHOP_NOW").upper()
    if cta_type not in ALLOWED_CTAS:
        raise MetaError(
            f"Unknown call-to-action '{cta_type}'.",
            code="BAD_CTA",
            fix="Use one of: " + ", ".join(sorted(ALLOWED_CTAS)),
        )
    return {"type": cta_type, "value": {"link": link}}


def build_object_story_spec(
    page_id: str,
    instagram_actor_id: str,
    asset: dict,
    copy: dict,
) -> dict:
    """Assemble object_story_spec for an image (link_data) or video (video_data) ad.

    Only a destination `link` is required (many statics ship as an image with the
    message baked in). `message` (primary text) and `headline` are OPTIONAL and
    are included only when present.
    """
    link = copy.get("link")
    if not link:
        raise MetaError(
            "No destination link for the ad.",
            code="NEEDS_INPUT",
            fix=(
                "Add a `link` to the ad copy, or set "
                "default_link_url in config.json."
            ),
        )

    cta = _call_to_action(copy.get("cta", "SHOP_NOW"), link)
    message = copy.get("message")
    headline = copy.get("headline")
    description = copy.get("description")

    spec = {"page_id": page_id}
    if instagram_actor_id:
        spec["instagram_user_id"] = instagram_actor_id

    if asset.get("type") == "image":
        if not asset.get("image_hash"):
            raise MetaError(
                "Image asset has no image_hash (upload it first).",
                code="ASSET_MISSING",
            )
        link_data = {
            "image_hash": asset["image_hash"],
            "link": link,
            "call_to_action": cta,
        }
        if message:
            link_data["message"] = message
        if headline:
            link_data["name"] = headline
        if description:
            link_data["description"] = description
        spec["link_data"] = link_data
        return spec

    if asset.get("type") == "carousel":
        cards = asset.get("cards") or []
        if len(cards) < 2:
            raise MetaError(
                "A carousel needs at least 2 cards.",
                code="NEEDS_INPUT",
                fix="Provide an asset.cards list of 2-10 images.",
            )
        child_attachments = []
        for i, card in enumerate(cards):
            if not card.get("image_hash"):
                raise MetaError(
                    f"Carousel card {i + 1} has no image_hash (upload it first).",
                    code="ASSET_MISSING",
                )
            card_link = card.get("link") or link
            att = {
                "image_hash": card["image_hash"],
                "link": card_link,
                "call_to_action": _call_to_action(
                    card.get("cta") or copy.get("cta", "SHOP_NOW"), card_link
                ),
            }
            if card.get("name"):
                att["name"] = card["name"]
            if card.get("description"):
                att["description"] = card["description"]
            child_attachments.append(att)

        link_data = {
            "link": link,
            "child_attachments": child_attachments,
            "multi_share_optimized": False,
            "multi_share_end_card": False,
        }
        if message:
            link_data["message"] = message
        spec["link_data"] = link_data
        return spec

    if not asset.get("video_id"):
        raise MetaError(
            "Video asset has no video_id (upload it first).",
            code="ASSET_MISSING",
        )
    video_data = {"video_id": asset["video_id"], "call_to_action": cta}
    if message:
        video_data["message"] = message
    if headline:
        video_data["title"] = headline
    if description:
        video_data["link_description"] = description
    thumb = asset.get("thumbnail") or {}
    if thumb.get("image_hash"):
        video_data["image_hash"] = thumb["image_hash"]
    elif thumb.get("image_url"):
        video_data["image_url"] = thumb["image_url"]
    spec["video_data"] = video_data
    return spec


def build_creative_payload(
    name: str,
    page_id: str,
    instagram_actor_id: str,
    asset: dict,
    copy: dict,
    degrees_of_freedom_spec: dict | None = None,
) -> dict:
    """Full /adcreatives payload.

    The Advantage+ opt-out is passed in (optional) rather than hard-coded: Meta
    deprecated the blanket `standard_enhancements` opt-out (error: "Including
    standard enhancements field ... has been deprecated. Please choose to set
    individual features instead.") in favour of PER-FEATURE flags. The correct
    feature keys are discovered by reading a created creative's
    `degrees_of_freedom_spec` back (see read_effective_enhancements), then the
    per-feature opt-out is supplied here.
    """
    if asset.get("type") == "existing_post":
        payload = {"name": name, **build_existing_post_ref(asset)}
    else:
        payload = {
            "name": name,
            "object_story_spec": build_object_story_spec(
                page_id, instagram_actor_id, asset, copy
            ),
        }
    if degrees_of_freedom_spec:
        payload["degrees_of_freedom_spec"] = degrees_of_freedom_spec
    return payload


def build_existing_post_ref(asset: dict) -> dict:
    """Point a creative at an EXISTING page post instead of building a new one.

    This is Ads Manager's "Use Existing Post". The reason to reach for it is
    SOCIAL PROOF: every ad pointing at the same post shares one pool of likes,
    comments and shares, instead of each ad minting a fresh post with zero
    engagement.

    The trade, and it is not negotiable: **the post owns its own copy.** Primary
    text, headline, link, CTA, card order and end-card settings all live on the
    post, so none of them can be overridden here -- passing `copy` to a creative
    built this way silently does nothing. Reuse a post to relaunch a GOOD ad; a
    broken or out-of-date one has to be rebuilt from the asset instead.
    """
    post_id = asset.get("post_id")
    if not post_id:
        raise MetaError(
            "No post id to reuse.",
            code="NEEDS_INPUT",
            fix=(
                "Set asset.post_id to the page post, e.g. '<page_id>_<post_id>'. "
                "Read it off an existing ad's creative field `effective_object_story_id`."
            ),
        )
    return {"object_story_id": post_id}
