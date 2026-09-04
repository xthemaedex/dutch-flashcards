#!/usr/bin/env bash
# fetch_sources.sh — download the open datasets build_corpus.py needs.
# One-time. ~280 MB total. All CC-BY-SA / GPL open data, no API keys.
set -euo pipefail

cd "$(dirname "$0")/../data/sources"

echo "1/5  OpenSubtitles Dutch frequency list (hermitdave/FrequencyWords, CC-BY-SA 4.0)"
curl -fL -O "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/nl/nl_50k.txt"

echo "2/5  Wiktionary Dutch extract (kaikki.org, CC-BY-SA 4.0 / GFDL) — 247 MB"
curl -fL -O "https://kaikki.org/dictionary/Dutch/kaikki.org-dictionary-Dutch.jsonl"

echo "3/5  Tatoeba Dutch sentences + NL-EN links + English sentences (CC-BY 2.0 FR)"
curl -fL -O "https://downloads.tatoeba.org/exports/per_language/nld/nld_sentences.tsv.bz2"
curl -fL -O "https://downloads.tatoeba.org/exports/per_language/nld/nld-eng_links.tsv.bz2"
curl -fL -O "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences.tsv.bz2"
bunzip2 -kf nld_sentences.tsv.bz2 nld-eng_links.tsv.bz2 eng_sentences.tsv.bz2

echo "4/5  FreeDict Dutch-English (GPL-2.0) — optional fallback translations, not used by default"
curl -fL -O "https://download.freedict.org/dictionaries/nld-eng/0.2/freedict-nld-eng-0.2.src.tar.xz"

echo "5/5  Brysbaert concreteness ratings (40k English lemmas, free academic data)"
echo "     — used by scripts/pick_image_words.py to choose picturable nouns"
curl -fL -o concreteness.txt "https://raw.githubusercontent.com/ArtsEngine/concreteness/master/Concreteness_ratings_Brysbaert_et_al_BRM.txt"

echo
echo "Done. Files in data/sources/:"
ls -lh
echo
echo "Next: python3 scripts/build_corpus.py --limit 2000"
