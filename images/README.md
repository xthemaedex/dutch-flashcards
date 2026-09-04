# Per-word images (Phase 4)

Concrete nouns get a Creative-Commons photo on the card front. Everything else
(abstract nouns, time words, particles, most verbs/adjectives) has no image and
renders text-only.

## How they get here

`scripts/fetch_images.py` fetches them **once** from the [Openverse](https://openverse.org)
API (no account, no key), downscales to `images/<lemma>.jpg`, and records the
pick + its CC attribution in the content JSON and the DB (`words.image_*`). The
finished app only ever serves the saved file — no API calls at runtime.

```
python3 scripts/fetch_images.py                 # nouns in data/seed_words.json
python3 scripts/fetch_images.py --dry-run        # preview picks only
python3 scripts/fetch_images.py --redo huis,hond # re-fetch specific lemmas
python3 scripts/fetch_images.py --json data/corpus_words.json   # full set
```

`data/image_stoplist.txt` lists lemmas that should never get an image — add to it
as you spot bad matches.

## Manual override

Dropping your own `images/<lemma>.jpg` here works too, as long as
`words.image_path` for that lemma points at it (set it in the JSON's `image`
block, or directly in the DB).

## Serving

- local: `serve.py` → `/img/<lemma>`
- production: the jsDelivr media branch (`IMAGE_BASE_URL`), same as audio

This whole folder is gitignored (except this README); the files live on the
`audio` branch, pushed by `scripts/publish_audio.mjs`.
