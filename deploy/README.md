# Hosting Tro for $0

The phone app stays on **GitHub Pages**. The backend runs on **Google Cloud Run**
inside your Firebase project. Everything below stays inside Google's free
monthly allowances at demo size.

| Piece | Where | Free allowance (per month) | Demo use |
|---|---|---|---|
| Backend server | Cloud Run, us-central1, max 1 server | 240,000 CPU-seconds (about 66 hours awake) | a few hours |
| Database | SQLite file, backed up every second to Cloud Storage by [Litestream](https://litestream.io) | 5 GB storage in us-central1 | a few MB |
| Photos, bracelet uploads | Same Cloud Storage bucket, mounted at `/media` | 5 GB | a few MB |
| Passwords and keys | Secret Manager | 6 secret versions | 5 |
| Building the server | Cloud Build | 2,500 build-minutes | about 4 per deploy |
| Server images | Artifact Registry, old images auto-deleted | 0.5 GB | about 0.3 GB |

A **budget alert** emails you if the project costs even $0.01. An alert only warns you. It
does not stop charges. The one cost that could show up is a fraction of a cent for the
source upload Cloud Build stores in a US multi-region bucket.

## What you do (about 10 minutes)

1. **Create the Firebase project.** Go to https://console.firebase.google.com, click
   *Create a project*, and name it (for example `tro-demo`). Google Analytics is optional.
   Note the **project ID** shown under the name. It looks like `tro-demo-1a2b3`.
2. **Switch to Blaze.** In the project, click *Upgrade* (bottom left) and pick
   *Blaze, pay as you go*. This needs a card, but nothing here goes past the free allowances.
3. **Run the setup script in Cloud Shell.** Open https://shell.cloud.google.com and run:

   ```bash
   git clone https://github.com/pie55dog/trO-AI-USC.git
   cd trO-AI-USC
   bash deploy/setup.sh YOUR_PROJECT_ID
   ```

   It asks for your Gmail address and app password, and your LinkedIn client ID and
   secret. Passwords are hidden as you type and go straight into Secret Manager.
   Press Enter to skip either one and add it later by running the script again.
   At the end it prints your backend address, like `https://tro-api-xxxx-uc.a.run.app`.
4. **Point the phone app at it.** In GitHub, go to the repo, then *Settings > Secrets and variables >
   Actions > Variables*, and add `VITE_API_URL` with the address from step 3.
   Make sure *Settings > Pages > Source* is **GitHub Actions**, then go to *Actions >
   Deploy web app to GitHub Pages > Run workflow*.
5. **Tell LinkedIn the new address.** In the LinkedIn developer portal, open your app, then
   *Auth > Authorized redirect URLs*, and add `https://<backend address>/auth/linkedin/callback`.

## Updating the backend

Merge the change to `main`, then in Cloud Shell:

```bash
cd trO-AI-USC && git pull && bash deploy/setup.sh YOUR_PROJECT_ID
```

It reuses all secrets and keeps the database. **Don't redeploy during the demo.** For
a few seconds the old and new servers overlap, and a sign-up made during that time could be lost.

## Demo day tips

- **Wake the server first.** After about 15 minutes with no visitors it goes to sleep, and the
  first request takes a few seconds. Open the app once just before you start.
- **Hotspot:** phones and bracelets only need internet access. The backend is public https,
  so any network works.
- **Bracelets:** see the firmware section below.
- **Sending the post-event emails:** organizers use the `X-Admin-Key` header
  (`--secret=tro-admin-key`). See `backend/README.md`.

## For the firmware team (Seeed XIAO ESP32-S3)

- **Endpoint:** `POST https://<backend address>/bracelets/uploads`, as a multipart form with
  `bracelet_id` (required), `event_id` (optional), `payload` (optional JSON text), and
  `files` (optional, repeatable, for audio). Full details are at the top of
  `backend/app/routers/bracelets.py`, and live docs are at `https://<backend address>/docs`.
- **Auth:** header `X-Bracelet-Key: <key>`. Grace gets the key with
  `gcloud secrets versions access latest --secret=tro-bracelet-key` and shares it privately.
  Keep it out of the firmware repo, for example in an untracked `secrets.h`.
- **HTTPS only.** In Arduino, use `WiFiClientSecure` with `HTTPClient`. For the demo,
  `client.setInsecure()` is fine. To verify the server properly, load Google's root CA
  (GTS Root R1 from https://pki.goog/repository/) with `client.setCACert(...)`.
- **Size limit:** Cloud Run rejects any single request over **32 MB**, so send long audio
  in several uploads.
- **Wake-up delay:** the first request after a quiet stretch can take a few seconds, so use
  an HTTP timeout of at least 30 seconds.

## After the demo

To be sure nothing is ever billed, delete the project: Firebase console > Project
settings > *Delete project*. Or remove billing from it in the Google Cloud console.

## How the database survives

Cloud Run's disk is wiped whenever the server sleeps or restarts. The container
(`backend/Dockerfile`, `backend/start.sh`) runs Litestream around the API:

1. On start, Litestream restores `tro.db` from `gs://<project>-tro-data/db/`.
2. While running, it copies every change to the bucket about once a second.
3. `--max-instances=1` guarantees there is only ever one copy being written.

Locally nothing changes. Without `LITESTREAM_REPLICA_URL`, the backend uses a plain SQLite file.
