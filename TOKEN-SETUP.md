# Meta token + IDs — setup

The uploader **creates ads**, so it needs a Meta access token with the
**`ads_management`** permission (read-only `ads_read` is not enough). Everything it
creates is **PAUSED** — the token's write power is only ever used to stage ads you
then review and launch yourself in Ads Manager.

You need three things from Meta, all from <https://business.facebook.com>:

| Value | Where to find it |
|---|---|
| **Ad account id** (`act_…`) | Ads Manager → account dropdown (top left). Looks like `act_1234567890`. |
| **Page id** | Your Facebook Page → About / Settings, or `business.facebook.com/settings/pages`. |
| **Instagram actor id** *(optional)* | Business Settings → Accounts → Instagram accounts. Leave blank to run Facebook-only. |

---

## Token option A — quick test (expires in ~1–2 hours)

Good enough to confirm the tool works end to end.

1. Go to the **Graph API Explorer**: <https://developers.facebook.com/tools/explorer/>
2. Pick your app (or create one — any "Business" type app works).
3. Add permission **`ads_management`** (and `pages_show_list` if your ad uses a Page).
4. **Generate Access Token**, approve, copy it.

This token dies in an hour or two — fine for a first `whoami` and a `--dry-run`.

## Token option B — permanent (recommended for real use)

A **System User** token does not expire — set it once, never think about it again.

1. **Business Settings → Users → System Users → Add.** Name it e.g. `ads-uploader`.
2. **Add Assets** → assign your **Ad Account** (toggle *Manage campaigns* ON — the
   uploader writes) and your **Page**. If you use Instagram, assign that too.
3. **Generate New Token** → pick your app → scope **`ads_management`** → expiry **Never**.
4. Copy it and **treat it like a password.**

> The token's user/system-user must have access to the Page and ad account you put
> in `config.json`, or Meta will reject the ad creation with a permissions error.

---

## Put the token + IDs in place

**Easiest — one command** (writes `.env` + `config.json` for you):

```bash
python3 -m meta_uploader setup \
  --token "<YOUR_TOKEN>" \
  --ad-account-id "act_1234567890" \
  --page-id "1234567890" \
  --instagram-actor-id "1789..."        # optional, omit to skip \
  --default-link-url "https://your-store.com/product"
```

**Or by hand:**

```bash
cp config.example.json config.json     # then edit the IDs
echo 'META_ACCESS_TOKEN=<YOUR_TOKEN>' > .env
```

## Turn a short-lived token into a long-lived one (optional)

If you started with a Token-A test token, exchange it for a ~60-day one without
re-doing setup (needs your app id + secret from the app's Basic Settings):

```bash
python3 -m meta_uploader setup \
  --token "<SHORT_LIVED_TOKEN>" --ad-account-id "act_…" --page-id "…" \
  --exchange --app-id "<APP_ID>" --app-secret "<APP_SECRET>"
```

(For a token that *never* expires, use the System User route above instead.)

## Verify

```bash
python3 -m meta_uploader whoami
```

Prints your user, ad account name + currency, and whether Drive is connected. If it
errors with code 190 / 102 / 463 / 467, the token or its scope is wrong.

---

**Security:** `.env` and `config.json` are git-ignored — your token and IDs never get
committed. If a token ever leaks, regenerate it in Business Settings (that instantly
invalidates the old one).
