"""Build the ad creative payload: object_story_spec + Advantage+ opt-out.

The Advantage+ opt-out (FR-007a) is the operator's hard requirement: every creative
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


def advantage_plus_optout_spec() -> dict:
    """degrees_of_freedom_spec that opts OUT of Advantage+ Standard Enhancements."""
    return {
        "creative_features_spec": {
            "standard_enhancements": {"enroll_status": "OPT_OUT"},
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
    payload = {
        "name": name,
        "object_story_spec": build_object_story_spec(
            page_id, instagram_actor_id, asset, copy
        ),
    }
    if degrees_of_freedom_spec:
        payload["degrees_of_freedom_spec"] = degrees_of_freedom_spec
    return payload
