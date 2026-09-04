#!/bin/bash
# Publish newly-generated media (audio clips + per-word images) to the live site.
#
# Run after scripts/generate_audio.py or scripts/fetch_images.py have produced
# more files:
#   1. push audio/ and images/ to the jsDelivr `audio` branch
#   2. regenerate data/audio_manifest.json from what's now on the branch
#   3. rebuild the static data files (bumps the service-worker version)
#
# Then commit the changed data/ + public/ files and push to main — Vercel
# redeploys and the new media is live (jsDelivr may take up to ~12 h to refresh
# its branch cache; publish_audio.mjs already fires a purge).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> pushing audio/ + images/ to the jsDelivr branch"
node scripts/publish_audio.mjs

echo
echo "==> regenerating data/audio_manifest.json from origin/audio"
git ls-tree -r --name-only origin/audio | grep '\.mp3$' \
  | sed -E 's|.*/0*([0-9]+)\.mp3|\1|' | sort -n \
  | python3 -c 'import sys,json; json.dump(sorted(int(x) for x in sys.stdin), open("data/audio_manifest.json","w"))'

echo
echo "==> rebuilding static data"
python3 scripts/seed_db.py --json data/corpus_words.json --reset >/dev/null
python3 scripts/build_static.py --deploy

echo
echo "Done. Now:  git add data/audio_manifest.json data/corpus_words.json public/ && git commit && git push"
