# Google Drive — setup (optional)

By default the uploader can pull a creative from a **public** "anyone with the link"
URL or a **local file**. Connect Google Drive and it will instead stream **private**
Drive files of **any size** straight into the Meta upload — no public sharing, and no
tripping over Drive's virus-scan interstitial that corrupts naive downloads of big
videos.

This is **optional** and **read-only** to Drive. With nothing configured, the tool
behaves exactly as before (public URL / local file).

There are two ways to connect. **OAuth (Option A) is recommended** — it needs no
service-account key and works even under Google Workspace orgs that block SA keys.

---

## Option A — OAuth sign-in (recommended, keyless)

1. **Create / pick a Google Cloud project** —
   <https://console.cloud.google.com/projectcreate>
2. **Enable the Drive API** — APIs & Services → Library → "Google Drive API" → **Enable**.
3. **Create an OAuth client** — APIs & Services → Credentials → **Create credentials →
   OAuth client ID → Application type: Desktop app**. Download its JSON.
   (If asked, configure the OAuth consent screen as **External**, add yourself as a
   test user — no app verification needed for personal use.)
4. **Save the client JSON** to `.secrets/oauth_client.json`:
   ```bash
   mkdir -p .secrets
   mv ~/Downloads/client_secret_*.json .secrets/oauth_client.json
   ```
5. **Sign in once** (opens a browser):
   ```bash
   python3 -m meta_uploader drive-auth
   ```
   This saves a refresh token to `.secrets/drive_token.json`. You won't need to sign
   in again.
6. **Confirm access:**
   ```bash
   python3 -m meta_uploader drive-check --file "https://drive.google.com/file/d/<FILE_ID>/view"
   ```

## Option B — service-account key

1–2. Same Cloud project + enable the Drive API as above.
3. **Create a service account** — IAM & Admin → Service Accounts → Create. No project
   roles needed. Open it → **Keys → Add key → Create new key → JSON**.
4. **Save the key** outside git, e.g. `.secrets/drive-sa.json`.
5. **Share your Drive folder with the service account's email** (it looks like
   `name@project.iam.gserviceaccount.com`; `drive-check` prints it). Right-click the
   folder in Drive → Share → paste the email → role **Viewer**.
6. **Point the tool at the key** — add to `.env`:
   ```
   GOOGLE_APPLICATION_CREDENTIALS=.secrets/drive-sa.json
   ```
7. Confirm with `python3 -m meta_uploader drive-check`.

---

## How it's used

Once connected, any asset reference that is a Drive share URL **or** a bare Drive file
id is downloaded through the authenticated Drive API automatically — in
`create-from-json` (image, video, carousel cards, thumbnail) and anywhere an asset is
resolved. No per-run flags. `whoami` reports whether Drive is configured.

## Troubleshooting

- **`drive_auth: not_connected`** — you haven't run `drive-auth` (Option A) or set
  `GOOGLE_APPLICATION_CREDENTIALS` (Option B). The tool still runs via public links.
- **`DRIVE_NO_CREDS`, "sign-in expired"** — run `python3 -m meta_uploader drive-auth` again.
- **`ASSET_UNREACHABLE`, HTTP 403/404** — the file/folder isn't shared with the
  account you signed in as (Option A) or the service-account email (Option B).
- **`invalid_grant` / Drive API errors** — the Drive API isn't enabled on the project,
  or the key/consent was revoked. Re-check steps 2–4.

`.secrets/` and `.env` are git-ignored — keys and tokens can never be committed.
