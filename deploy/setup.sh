#!/usr/bin/env bash
# One-time (and repeatable) setup of the Tro backend on Google Cloud Run.
#
# Run it in Google Cloud Shell, from the repo folder:
#
#     bash deploy/setup.sh YOUR_FIREBASE_PROJECT_ID
#
# Running it again redeploys the latest code and keeps every secret and the
# database. See deploy/README.md for the full walkthrough.
#
# Everything is sized to stay inside Google's free monthly allowances:
#   - Cloud Run in us-central1, never more than 1 server.
#   - A Cloud Storage bucket in us-central1 for photos and the database backup.
#   - Secret Manager: 5 secrets (6 are free).
#   - Old container images are cleaned up so storage stays under 0.5 GB.
#   - A $1 budget alert emails you if anything ever starts costing money.

set -euo pipefail

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="us-central1"
SERVICE="tro-api"
PAGES_ORIGIN="https://pie55dog.github.io"
FRONTEND_URL="${FRONTEND_URL:-$PAGES_ORIGIN/trO-AI-USC}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: bash deploy/setup.sh YOUR_FIREBASE_PROJECT_ID" >&2
  exit 1
fi
if [[ ! -f backend/Dockerfile ]]; then
  echo "Run this from the top folder of the repo (the one with backend/ in it)." >&2
  exit 1
fi

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
BUCKET="${PROJECT_ID}-tro-data"

say "Checking billing"
BILLING_ACCOUNT="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)' | sed 's|billingAccounts/||')"
if [[ -z "$BILLING_ACCOUNT" ]]; then
  echo "This project has no billing account. In the Firebase console, open"
  echo "the project, click Upgrade, and pick the Blaze (pay as you go) plan."
  exit 1
fi

say "Turning on the Google Cloud services Tro needs (takes a minute)"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com billingbudgets.googleapis.com \
  cloudresourcemanager.googleapis.com iam.googleapis.com

say "Storage bucket for photos and the database backup: gs://$BUCKET"
if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  # us-central1 + Standard class is inside the free tier (5 GB).
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
    --default-storage-class=STANDARD --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/storage.objectAdmin >/dev/null

say "Secrets (stored in Secret Manager, never in the code)"
secret_exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }
put_secret() {  # put_secret NAME VALUE  (creates it, or adds a new version)
  if secret_exists "$1"; then
    printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
    # Keep only the newest version so we stay under the free 6 versions.
    for old in $(gcloud secrets versions list "$1" --filter='state=ENABLED' --sort-by='~createTime' --format='value(name.basename())' | tail -n +2); do
      gcloud secrets versions destroy "$old" --secret="$1" --quiet >/dev/null
    done
  else
    printf '%s' "$2" | gcloud secrets create "$1" --replication-policy=automatic --data-file=- >/dev/null
  fi
}
random_key() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }

# Generated keys: made once, then reused on every rerun.
for name in tro-secret-key tro-admin-key tro-bracelet-key; do
  secret_exists "$name" || put_secret "$name" "$(random_key)"
done

# Settings that aren't secret are remembered in the bucket so reruns don't ask again.
CONFIG_OBJ="gs://$BUCKET/config/settings.env"
SMTP_USERNAME="" ; LINKEDIN_CLIENT_ID=""
if gcloud storage cat "$CONFIG_OBJ" >/tmp/tro-settings.env 2>/dev/null; then
  # shellcheck disable=SC1091
  source /tmp/tro-settings.env
fi

if ! secret_exists tro-smtp-password; then
  echo
  echo "Email: the Gmail account that sends the next-morning emails."
  echo "It needs an app password (Google Account > Security > 2-Step Verification > App passwords)."
  echo "Press Enter on both to skip email for now."
  read -r -p "  Gmail address: " SMTP_USERNAME
  if [[ -n "$SMTP_USERNAME" ]]; then
    read -r -s -p "  App password (hidden): " smtp_pw; echo
    smtp_pw="${smtp_pw// /}"  # Google shows it in groups of 4; spaces aren't part of it
    if [[ -n "$smtp_pw" ]]; then put_secret tro-smtp-password "$smtp_pw"; fi
  fi
fi

if ! secret_exists tro-linkedin-secret; then
  echo
  echo "LinkedIn sign-in: from developer.linkedin.com > your app > Auth tab."
  echo "Press Enter on both to skip LinkedIn for now."
  read -r -p "  Client ID: " LINKEDIN_CLIENT_ID
  if [[ -n "$LINKEDIN_CLIENT_ID" ]]; then
    read -r -s -p "  Client secret (hidden): " li_secret; echo
    if [[ -n "$li_secret" ]]; then put_secret tro-linkedin-secret "$li_secret"; fi
  fi
fi

printf 'SMTP_USERNAME=%q\nLINKEDIN_CLIENT_ID=%q\n' "$SMTP_USERNAME" "$LINKEDIN_CLIENT_ID" >/tmp/tro-settings.env
gcloud storage cp /tmp/tro-settings.env "$CONFIG_OBJ" >/dev/null
rm -f /tmp/tro-settings.env

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor \
  --condition=None >/dev/null
# Source deploys build with this same account; it needs the builder role.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/run.builder \
  --condition=None >/dev/null || true

say "Container image storage, with old images cleaned up automatically"
if ! gcloud artifacts repositories describe cloud-run-source-deploy --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create cloud-run-source-deploy --location="$REGION" \
    --repository-format=docker --description="Tro backend images"
fi
cat >/tmp/tro-cleanup.json <<'JSON'
[
  {"name": "keep-newest-2", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 2}},
  {"name": "delete-older", "action": {"type": "Delete"}, "condition": {"olderThan": "1d"}}
]
JSON
gcloud artifacts repositories set-cleanup-policies cloud-run-source-deploy \
  --location="$REGION" --policy=/tmp/tro-cleanup.json --no-dry-run >/dev/null
rm -f /tmp/tro-cleanup.json

# --- Deploy --------------------------------------------------------------
SERVICE_URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)' 2>/dev/null || true)"

ENV_FILE="$(mktemp)"
{
  echo "LITESTREAM_REPLICA_URL: 'gcs://$BUCKET/db/tro.db'"
  echo "FRONTEND_URL: '$FRONTEND_URL'"
  echo "CORS_ORIGINS: '$PAGES_ORIGIN,http://localhost:5173'"
  if [[ -n "$SERVICE_URL" ]]; then echo "LINKEDIN_REDIRECT_URI: '$SERVICE_URL/auth/linkedin/callback'"; fi
  if secret_exists tro-smtp-password && [[ -n "$SMTP_USERNAME" ]]; then
    echo "EMAIL_BACKEND: 'smtp'"
    echo "EMAIL_FROM: 'Tro <$SMTP_USERNAME>'"
    echo "SMTP_HOST: 'smtp.gmail.com'"
    echo "SMTP_PORT: '587'"
    echo "SMTP_USERNAME: '$SMTP_USERNAME'"
  fi
  if [[ -n "$LINKEDIN_CLIENT_ID" ]]; then echo "LINKEDIN_CLIENT_ID: '$LINKEDIN_CLIENT_ID'"; fi
} >"$ENV_FILE"

SECRETS="SECRET_KEY=tro-secret-key:latest,ADMIN_API_KEY=tro-admin-key:latest,BRACELET_API_KEY=tro-bracelet-key:latest"
if secret_exists tro-smtp-password; then SECRETS+=",SMTP_PASSWORD=tro-smtp-password:latest"; fi
if secret_exists tro-linkedin-secret; then SECRETS+=",LINKEDIN_CLIENT_SECRET=tro-linkedin-secret:latest"; fi

say "Building and deploying the backend (takes 3 to 5 minutes)"
# Why these settings:
#   max-instances 1   one server, so only one copy of the database is ever written.
#   min-instances 0   it sleeps when nobody uses it, which keeps it free.
#   no-cpu-throttling the backup keeps running between requests (still free:
#                     240,000 CPU-seconds a month is about 66 hours awake).
#   gen2              needed to mount the Storage bucket as a folder.
gcloud run deploy "$SERVICE" \
  --source=backend \
  --region="$REGION" \
  --allow-unauthenticated \
  --max-instances=1 --min-instances=0 \
  --cpu=1 --memory=512Mi --no-cpu-throttling \
  --execution-environment=gen2 \
  --service-account="$RUNTIME_SA" \
  --add-volume="name=media,type=cloud-storage,bucket=$BUCKET" \
  --add-volume-mount="volume=media,mount-path=/media" \
  --env-vars-file="$ENV_FILE" \
  --set-secrets="$SECRETS" \
  --quiet
rm -f "$ENV_FILE"

NEW_URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
if [[ "$NEW_URL" != "$SERVICE_URL" ]]; then
  # First deploy: now that we know the address, tell the app its LinkedIn callback.
  gcloud run services update "$SERVICE" --region="$REGION" --quiet \
    --update-env-vars="LINKEDIN_REDIRECT_URI=$NEW_URL/auth/linkedin/callback" >/dev/null
fi

say "Budget alert: emails you if this project ever costs more than \$0.01"
if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format='value(displayName)' | grep -qx "Tro demo"; then
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
    --display-name="Tro demo" --budget-amount=1USD \
    --filter-projects="projects/$PROJECT_ID" \
    --threshold-rule=percent=0.01 --threshold-rule=percent=0.5 --threshold-rule=percent=1.0 >/dev/null
fi

say "Checking the server answers"
if curl -fsS "$NEW_URL/health" >/dev/null; then echo "  OK: $NEW_URL/health"; else echo "  The server didn't answer yet. Try $NEW_URL/health in a minute."; fi

cat <<EOF

────────────────────────────────────────────────────────────────────
Done. Your backend is live at:

    $NEW_URL

Next steps (see deploy/README.md):

1. GitHub repo > Settings > Secrets and variables > Actions > Variables:
   add VITE_API_URL = $NEW_URL
   Then Actions > "Deploy web app to GitHub Pages" > Run workflow.

2. LinkedIn developer portal > your app > Auth > Authorized redirect URLs:
   add $NEW_URL/auth/linkedin/callback

3. Keys for organizers and bracelets (keep them out of chats and the repo):
     gcloud secrets versions access latest --secret=tro-admin-key
     gcloud secrets versions access latest --secret=tro-bracelet-key
────────────────────────────────────────────────────────────────────
EOF
