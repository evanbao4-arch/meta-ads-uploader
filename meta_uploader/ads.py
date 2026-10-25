"""Create ad creatives, ads (PAUSED), and ad sets (PAUSED).

Everything created here is PAUSED — nothing ever spends (FR-010). Advantage+
audience expansion is disabled on new ad sets (FR-007a).
"""

from __future__ import annotations

from .client import GraphClient, MetaError
from .creative import advantage_plus_optout_spec, build_creative_payload


def create_creative(
    client: GraphClient,
    name: str,
    page_id: str,
    instagram_actor_id: str,
    asset: dict,
    copy: dict,
) -> str:
    payload = build_creative_payload(
        name,
        page_id,
        instagram_actor_id,
        asset,
        copy,
        degrees_of_freedom_spec=advantage_plus_optout_spec(),
    )
    resp = client.post(f"{client.account_id}/adcreatives", data=payload)
    return resp["id"]


def create_ad(
    client: GraphClient,
    name: str,
    adset_id: str,
    creative_id: str,
) -> str:
    """Create the ad PAUSED inside an existing ad set."""
    resp = client.post(
        f"{client.account_id}/ads",
        data={
            "name": name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
    )
    return resp["id"]


def read_effective_enhancements(client: GraphClient, creative_id: str) -> dict:
    """Read the creative back to report which Advantage+ enhancements actually stuck."""
    try:
        resp = client.get(
            creative_id, params={"fields": "degrees_of_freedom_spec"}
        )
        return resp.get("degrees_of_freedom_spec", {})
    except MetaError:
        return {}


def ads_manager_url(account_id: str, ad_id: str) -> str:
    acct = account_id.replace("act_", "")
    return (
        "https://adsmanager.facebook.com/adsmanager/manage/ads?act="
        f"{acct}&selected_ad_ids={ad_id}"
    )


def create_adset(
    client: GraphClient,
    campaign_id: str,
    name: str,
    optimization_goal: str = "OFFSITE_CONVERSIONS",
    billing_event: str = "IMPRESSIONS",
    daily_budget: int | None = None,
    targeting: dict | None = None,
    promoted_object: dict | None = None,
    advertiser_identity_id: str | None = None,
) -> str:
    """Create a PAUSED ad set under an existing campaign, with Advantage+ audience OFF.

    daily_budget is in the account's minor units (e.g. cents). Raises NEEDS_INPUT
    listing what's still required, rather than guessing targeting/budget.

    promoted_object carries the conversion target for a sales ad set, e.g.
    {"pixel_id": "...", "custom_event_type": "PURCHASE"}. Meta rejects
    OFFSITE_CONVERSIONS without it.

    advertiser_identity_id fills Meta's "Ad transparency" advertiser/payer, which
    some regions (e.g. Australia, from ~Sep 2026) require before a NEW ad set can
    deliver. Copy it off an existing ad set's
    regional_regulation_identities.universal_beneficiary.
    """
    targeting = dict(targeting or {})
    ta = dict(targeting.get("targeting_automation") or {})
    ta["advantage_audience"] = 0
    targeting["targeting_automation"] = ta

    missing = []
    if daily_budget is None:
        missing.append("daily_budget")
    if not targeting.get("geo_locations"):
        missing.append("targeting (at least geo_locations)")
    if optimization_goal == "OFFSITE_CONVERSIONS" and not promoted_object:
        missing.append("promoted_object (pixel_id + custom_event_type for conversions)")
    if missing:
        raise MetaError(
            "Missing settings to create a new ad set.",
            code="NEEDS_INPUT",
            fix="Provide: " + ", ".join(missing),
        )

    data = {
        "name": name,
        "campaign_id": campaign_id,
        "optimization_goal": optimization_goal,
        "billing_event": billing_event,
        "daily_budget": daily_budget,
        "targeting": targeting,
        "status": "PAUSED",
    }
    if promoted_object:
        data["promoted_object"] = promoted_object
    if advertiser_identity_id:
        data["regional_regulation_identities"] = {
            "universal_beneficiary": advertiser_identity_id,
            "universal_payer": advertiser_identity_id,
        }
    resp = client.post(f"{client.account_id}/adsets", data=data)
    return resp["id"]


def adset_optout_audience_note() -> dict:
    """Exposed for tests/transparency: what we force on every new ad set."""
    return {
        "targeting_automation": {"advantage_audience": 0},
        "status": "PAUSED",
        "creative_optout": advantage_plus_optout_spec(),
    }
