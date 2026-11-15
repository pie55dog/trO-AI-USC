# Hosting Tro for $0 (no card)

The phone app stays on **GitHub Pages**. The backend and its database run on **Render's free plan**,
which needs no card. Email goes out through a free **Google Apps Script** in your Gmail.

| Piece | Where | Free limit | Catch |
|---|---|---|---|
| Backend | Render free web service (`render.yaml`) | 750 hours a month | Sleeps after 15 idle minutes and takes up to a minute to wake |
| Database | Render free Postgres | 1 GB | **Deleted 30 days after you create it.** Fine for the hackathon |
| Photos, bracelet uploads | A copy is kept in the database (`MEDIA_IN_DB`) | Shares the 1 GB | The free disk is wiped on every restart, so files come back from the database |
| Email | Apps Script in your Gmail (`deploy/email-relay.gs`) | About 100 recipients a day | Render's free plan blocks normal email ports |
| Keep-awake ping | GitHub Actions, every 10 minutes | Free on public repos | Uses about 720 of the 750 monthly hours. Turn it off after the demo |

## What you do (about 15 minutes)

### 1. Email relay (5 min)
1. Sign in to the **personal Gmail** that should send Tro's emails. A USC account may block step 4.
2. Open https://script.new and replace everything with the contents of `deploy/email-relay.gs`.
3. On the `RELAY_KEY` line, replace `CHANGE-ME-...` with a long random string. Mash the keyboard
   for 30 or more characters. Keep it handy for step 2, and don't paste it into chats.
4. Click **Deploy > New deployment**, choose the gear and then **Web app**, set *Execute as: Me* and
   *Who has access: Anyone*, and click **Deploy**. Allow access when Google asks. If it warns
   "Google hasn't verified this app", click *Advanced > Go to project*.
5. Copy the **Web app URL**. It ends in `/exec`.

### 2. Backend on Render (5 min, then about 5 min of building)
1. Sign up at https://render.com with **GitHub**. No card is needed.
2. Click **New > Blueprint**, pick the `trO-AI-USC` repo, and click **Connect**. If Render can't see
   the repo, click *Configure GitHub* and give it access to the repo.
3. Render reads `render.yaml` and asks for four values:
   - `EMAIL_RELAY_URL`: the `/exec` URL from step 1
   - `EMAIL_RELAY_KEY`: the random string from step 1
   - `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`: from your LinkedIn app's *Auth* tab.
     Leave them blank to skip LinkedIn for now.
4. Click **Deploy Blueprint**. When `tro-api` shows *Live*, copy its address from the top of its page.
   It looks like `https://tro-api-xxxx.onrender.com`.

> If Render asks for a card on the Blueprint page, skip the Blueprint and do it by hand.
> First click **New > Postgres**, choose the Free plan in Oregon, and create it.
> Then click **New > Web Service**, pick the repo, and set Root Directory `backend`, Build `pip install -r requirements.txt`,
> Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and the Free plan in Oregon. Copy every `envVars`
> entry from `render.yaml` into its Environment tab. For `DATABASE_URL`, use the database's
> *Internal Database URL*. For the three keys, use any long random strings.

### 3. Point the phone app at it (2 min)
1. In GitHub, go to the repo, then **Settings > Secrets and variables > Actions > Variables**, and add
   `VITE_API_URL` = the Render address. Leave off the trailing slash.
2. Under **Settings > Pages**, set Source to **GitHub Actions**.
3. Under **Actions > Deploy web app to GitHub Pages**, click **Run workflow**.

### 4. LinkedIn (1 min)
In the LinkedIn developer portal, open your app, then **Auth > Authorized redirect URLs**, and add
`https://<render address>/auth/linkedin/callback`.

### 5. AI key for conversation notes (2 min, free, no card)
Sign up at **console.groq.com** (Google sign-in works), open **API Keys > Create API Key**, and copy it.
On Render open `tro-api` > **Environment**, set `AI_API_KEY` to it, and save (it redeploys). Paste it
there yourself; don't send it in a chat. Without it, recordings are kept and wait; after adding it,
`POST /admin/process` (with `X-Admin-Key`) finishes them.

### Check it
Open `https://<render address>/health`. It should say `{"ok":true}`. The first visit can take a minute.

## Demo day
- **Wake it up early.** The keep-awake ping should handle this, but open the app once 2 minutes before you start anyway.
  The app also pings the backend the moment it opens.
- **Don't redeploy during the demo.** Render redeploys automatically on every push to `main`, and each
  redeploy restarts the server.
- **Organizer and bracelet keys** are on Render: open `tro-api`, then **Environment**, and look at
  `ADMIN_API_KEY` and `BRACELET_API_KEY`. Share them privately, never in the repo.

## For the firmware team (Seeed XIAO ESP32-S3)
The sketch is in [`firmware/`](../firmware/README.md). Put the Render address in `SERVER_URL` and the
`BRACELET_API_KEY` in `BRACELET_KEY` in `secrets.h` (never committed). It uses `WiFiClientSecure` with
`setInsecure()` for the demo, waits up to a minute at boot for a sleeping server, and keeps one HTTPS
connection open so each tap report is fast.

## After the demo
Turn off the keep-awake ping (**Actions > Keep backend awake > ... > Disable workflow**). The free
database deletes itself 30 days after creation. To keep the data, export it before then
(Render's database page has the connection details for `pg_dump`).
