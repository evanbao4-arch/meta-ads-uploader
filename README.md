# Meta Ads Uploader

A small command-line tool that takes a creative — from **Google Drive**, a URL, or a
local file — and creates a **PAUSED, ready-to-launch ad** in your Meta (Facebook /
Instagram) ad account. It talks to the Meta Marketing API directly over HTTPS.

**It never spends money.** Every ad and ad set is created with `status=PAUSED`. You
review each one in Ads Manager and launch it yourself.

## What it is — and isn't

- **It is** the *hands*: the mechanical, error-prone "get this asset into Meta as a
  correctly-formed ad" step, done right.
- **It isn't** a strategist. It makes no decisions about targeting, budget, or what to
  say — that's you (or you + Claude; see below). It just executes.

### Why it's worth using (the traps it has already eaten)

Anyone can POST to the Graph API. The time sink is the gotchas — these are solved here:

- **Creatives run exactly as you built them.** Meta silently auto-"enhances" creatives
  (Advantage+ Standard Enhancements). This opts out per-feature, so your ad isn't altered.
- **PAUSED by default.** You can never spend money on a typo.
- **Private Drive files of any size.** Streams straight from Drive — no public sharing,
  and it sidesteps the virus-scan interstitial that corrupts naive downloads of big videos.
- **Video processing wait.** Video uploads aren't ready instantly; the tool waits before
  attaching, so creation doesn't fail.

---

## Setup (≈10 minutes)

```bash
# 1. Get the code + a virtual environment
git clone <this-repo-url> meta-ads-uploader && cd meta-ads-uploader
python3 -m venv .venv && source .venv/bin/activate    # Python 3.10+
pip install -r requirements.txt

# 2. Connect Meta (token + your account/page IDs)
#    Full walkthrough: TOKEN-SETUP.md
python3 -m meta_uploader setup \
  --token "<YOUR_TOKEN>" --ad-account-id "act_1234567890" --page-id "1234567890" \
  --default-link-url "https://your-store.com/product"

# 3. Confirm it works (read-only, creates nothing)
python3 -m meta_uploader whoami

# 4. (Optional) Connect Google Drive for private assets — see DRIVE-SETUP.md
python3 -m meta_uploader drive-auth
```

- **`TOKEN-SETUP.md`** — get a Meta token (incl. a permanent one) and find your IDs.
- **`DRIVE-SETUP.md`** — connect Drive (optional; needed only for private Drive files).

Secrets live in `.env` and `.secrets/`, and your filled-in `config.json` — **all
git-ignored.** Nothing sensitive is ever committed.

---

## The main way to use it: describe the ad, let Claude build it

You don't hand-write JSON. Open this folder in Claude Code (or Claude Desktop) and just
say what you want. Claude reads this README, writes the ad copy, assembles the input the
tool expects, and runs it. **This README is the contract** that lets any Claude session
drive the tool correctly.

### Worked example

**You collated some creative and dropped it in a Drive folder. You type to Claude:**

> "I've got a new static here:
> `https://drive.google.com/file/d/1AbCdEfGhIjK/view`
> It's for tired new mums, angle is 'finally sleep through the night', 20% off this week,
> link to https://mystore.com/weighted-blanket. Write the primary text + headline and push
> it as a paused ad into ad set 23861234567890123."

**Claude writes the copy and produces this manifest** (`ad.json`):

```json
{
  "name": "2026-06-20 sleepy-mum static — sleep through the night",
  "asset": { "type": "image", "file": "https://drive.google.com/file/d/1AbCdEfGhIjK/view" },
  "copy": {
    "message": "The nights are long enough. Our weighted blanket helps you fall asleep faster and stay asleep — so you wake up to the baby, not the 3am ceiling stare. 20% off this week.",
    "headline": "Finally sleep through the night",
    "link": "https://mystore.com/weighted-blanket",
    "cta": "SHOP_NOW"
  },
  "adset_id": "23861234567890123"
}
```

**Then runs:**

```bash
python3 -m meta_uploader create-from-json --file ad.json
```

**And hands you back** the new ad id, creative id, and a direct **Ads Manager URL** to
the PAUSED ad — where you set your own targeting/budget and launch it.

> Tip: add `--dry-run` to print the exact payloads and the ad name **without** touching
> Meta. Great for sanity-checking before the real run.

**Two notes that make this work well:**
- For copy that sounds like *you*, paste 2–3 of your winning past ads into the chat —
  examples teach voice far better than describing it.
- If your Claude has a Google Drive connector, it can list a whole folder and build one
  manifest per file. Otherwise just paste the share links.

---

## The manifest (`create-from-json`)

One JSON object per ad. Minimum is a `name`, an `asset`, a `copy.link`, and a destination.

| Field | Required | Notes |
|---|---|---|
| `name` | ✅ | The ad's name in Ads Manager. |
| `asset.type` | ✅ | `"image"`, `"video"`, or `"carousel"`. |
| `asset.file` | ✅ (image/video) | Drive link, bare Drive id, public URL, or local path. |
| `asset.cards[]` | ✅ (carousel) | 2–10 items, each `{file, link?, name?, description?, cta?}`. |
| `thumbnail_file` | — | Video only: image for the video thumbnail. |
| `copy.link` | ✅* | Destination URL. *Falls back to `default_link_url` in config. |
| `copy.message` | — | Primary text. Omit if the hook is baked into the image. |
| `copy.headline` | — | Headline / title. |
| `copy.description` | — | Link description. |
| `copy.cta` | — | Defaults to `SHOP_NOW`. See allowed values below. |
| `adset_id` | ✅** | Existing ad set to put the ad in. |
| `new_adset` | ✅** | Or create one: `{campaign_id, name?, optimization_goal?, billing_event?, daily_budget?, targeting?}` (created PAUSED, Advantage+ audience OFF). |
| `video_timeout` | — | Seconds to wait for video processing (default 300). |

\* one of `copy.link` / `default_link_url` required. \*\* provide `adset_id` **or** `new_adset`.

**Allowed `cta` values:** `SHOP_NOW`, `BUY_NOW`, `LEARN_MORE`, `SIGN_UP`, `SUBSCRIBE`,
`GET_OFFER`, `ORDER_NOW`, `SEE_MORE`, `GET_QUOTE`, `CONTACT_US`, `DOWNLOAD`,
`BOOK_TRAVEL`, `NO_BUTTON`.

---

## Command reference

Every command prints JSON and exits non-zero on error. `--dry-run` (on create commands)
prints payloads without calling Meta.

| Command | What it does |
|---|---|
| `whoami` | Verify the connection; show account + Drive status. No writes. |
| `list-campaigns [--status active\|paused\|all]` | List campaigns. |
| `list-adsets [--campaign <id>]` | List ad sets (to find an `adset_id`). |
| `upload-image --file <path\|url>` | Upload an image; returns `image_hash`. |
| `upload-video --file <path\|url> [--timeout 300]` | Upload a video; waits for processing. |
| `create-adset --campaign <id> --name <n> [...]` | Create a PAUSED ad set. |
| `create-ad --name <n> --adset <id> (--image-hash <h> \| --video-id <id>) --message <m> --headline <h> [--link <url>] [--cta SHOP_NOW]` | Create one PAUSED ad from already-uploaded media. |
| **`create-from-json --file <path\|->`** | **Upload asset + create a PAUSED ad from one manifest. The main path.** |
| `drive-auth` / `drive-check [--file <url>]` | Connect / verify Google Drive (see DRIVE-SETUP.md). |
| `setup --token … --ad-account-id … --page-id …` | Write `.env` + `config.json` (see TOKEN-SETUP.md). |

---

## Going further

- **Folder-at-once:** a `from-drive-folder <link>` command (list a Drive folder → one
  paused ad per file) would match a "dump everything in a folder" workflow even more
  directly. Not built yet — today, point Claude at the folder (with a Drive connector) or
  paste the file links.
- The tool is **read-only to your decisions**: it never launches, never sets budgets you
  didn't ask for, never edits live ads. Bring your own rules in Ads Manager.

## Layout

```
meta_uploader/
  cli.py        # command surface (this is what you run)
  config.py     # loads .env + config.json
  client.py     # tiny Meta Graph API HTTP wrapper
  media.py      # upload image/video, resolve an asset to a local file
  drive.py      # authenticated Google Drive download (OAuth or service account)
  creative.py   # build the ad creative (image / video / carousel) + Advantage+ opt-out
  ads.py        # create creative / ad / ad set — always PAUSED
requirements.txt · config.example.json · TOKEN-SETUP.md · DRIVE-SETUP.md
```
