# Meta Ads Uploader

**Get your finished ads into Facebook and Instagram without the drag, drop and untick routine.**

You point it at a creative (a file on your computer, a Google Drive link, or a web link),
say which ad set it should go into, and it builds the ad for you in Ads Manager: the
image or video, your caption, headline, link and button, named the way you want.

Every ad it makes is **paused**. It never spends a cent. You open Ads Manager, check it,
and switch it on yourself.

---

## Why bother

If you upload ads by hand, you know the routine: upload the file, paste the caption, set
the link, then hunt down and untick Meta's "enhancements" (auto-crops, added music, AI
text, filters) so your ad runs the way you made it. Every ad. Every time.

This does all of that in one go, and it never forgets a box:

- **Your ad runs exactly as you made it.** All of Meta's creative "enhancements" are
  switched off on every ad (58 of them as of Oct 2026, one by one, the way Meta now
  insists on).
- **Nothing goes live by accident.** Paused by default, always.
- **Big videos work.** Large files upload in chunks, so you don't have to shrink them.
- **Private Google Drive files work.** No need to make your folder public.
- **Consistent names.** Tell Claude your naming convention once and every ad follows it.

## How you actually use it (no code)

You don't type commands. You talk to Claude (Claude Code or Claude Desktop) with this
folder open, like you'd brief a junior media buyer:

> "Here's a new static: `~/Desktop/sleepy-mum.png`. Put it in my top-of-funnel ad set.
> Caption: *The nights are long enough...* Headline: *Finally sleep through the night*.
> Link to mystore.com/weighted-blanket. Name it with our usual convention."

Claude reads this README, works out the rest, runs the tool, and hands you back a link to
the paused ad in Ads Manager.

## What you need

- A Mac or PC with **Claude Code** (or Claude Desktop) installed.
- Admin access to your **Meta ad account** and **Facebook Page**.
- About **20 minutes, once**, to connect Meta. This is the only fiddly part.

## Setting it up (let Claude drive)

The easiest way: download this folder, open it in Claude Code, and say:

> "Set this up for me. Walk me through it one step at a time and tell me exactly what to
> click. I'm not technical."

Claude will install what's needed and walk you through the one manual bit: creating a
Meta "access token" in Meta's developer tools. That token is a private key that lets
Claude talk to your ad account. The full click-by-click guide is in **TOKEN-SETUP.md**.

**Two rules:**
1. **Never paste your token into a chat.** Put it straight into the `.env` file (Claude
   will tell you how). It's a key to your ad account; treat it like a password.
2. Your token, account IDs and settings stay on your computer. They are never uploaded
   back to GitHub (the project is set up to ignore them).

**Australian advertisers:** Meta now wants an "advertiser identity" on every new ad set
(the ad transparency rule). If you get a "provide a verified advertiser" error, ask
Claude to copy the id off one of your existing ad sets into `advertiser_identity_id` in
`config.json`. Uploading into an ad set that already exists isn't affected.

## What it doesn't do

- It doesn't decide your targeting, budget or strategy. That's you.
- It doesn't write your ads for you. (Claude can draft a caption, but your best copy
  still comes from you and your data.)
- It never switches anything on and never edits ads that are already running.

---

# The technical bit (for Claude, or if you're curious)

Everything below is the reference Claude follows. You don't need to read it.

## Setup by hand

```bash
# 1. Get the code + a virtual environment
git clone https://github.com/evanbao4-arch/meta-ads-uploader && cd meta-ads-uploader
python3 -m venv .venv && source .venv/bin/activate    # Python 3.10+
pip install -r requirements.txt

# 2. Connect Meta (token + your account/page IDs). Walkthrough: TOKEN-SETUP.md
python3 -m meta_uploader setup \
  --token "<YOUR_TOKEN>" --ad-account-id "act_1234567890" --page-id "1234567890" \
  --default-link-url "https://your-store.com/product"

# 3. Confirm it works (read-only, creates nothing)
python3 -m meta_uploader whoami

# 4. (Optional) Connect Google Drive for private assets: see DRIVE-SETUP.md
python3 -m meta_uploader drive-auth
```

Secrets live in `.env`, `.secrets/` and your filled-in `config.json`, all git-ignored.

## Driving it from Claude: describe the ad, Claude builds it

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
| `new_adset` | ✅** | Or create one: `{campaign_id, name?, optimization_goal?, billing_event?, daily_budget?, targeting?, promoted_object?, advertiser_identity_id?}` (created PAUSED, Advantage+ audience OFF). `promoted_object` (e.g. `{"pixel_id": "…", "custom_event_type": "PURCHASE"}`) is required for the default sales goal. |
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

## Licence

MIT. Free to use, change and share. See `LICENSE`. It comes with no warranty: you check every ad before it goes live.
