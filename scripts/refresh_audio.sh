#!/bin/bash
# Push newly-generated audio to the live site.
#
# Run this whenever scripts/generate_audio.py has produced more .mp3 clips:
#   1. uploads the new clips to the Vercel Blob store
#   2. refreshes the audio_assets table in Turso (so the API returns the URLs)
#
# The deployed app picks them up on its next data fetch (a reload or two for an
# already-installed PWA). No redeploy needed.
#
# Needs .env  (TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
#   and .env.local  (BLOB_READ_WRITE_TOKEN — created by `vercel blob create-store`)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> uploading new clips to Vercel Blob"
node --env-file=.env.local scripts/publish_audio.mjs

echo
echo "==> syncing audio_assets -> Turso"
node --env-file=.env scripts/migrate_to_turso.mjs --only audio_assets

echo
echo "Done. New audio is live."
