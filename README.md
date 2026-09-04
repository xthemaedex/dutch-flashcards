# Dutch Flashcard App — Phases 1–5 (complete)

**Phase 1** (data): content generated **once, offline, from open datasets** — no
paid API, no AI API. **Phase 2** (review UI): SM-2 spaced repetition,
flip/swipe/rate. **Phase 3** (audio): one-tap + auto-play pronunciation from
cached files. **Phase 4** (stats & polish): streak, per-level completion,
difficulty heatmap, "mark as known", optional per-word images, dark mode.
**Phase 5** (PWA): installable, offline via a service worker, daily due-cards
reminder, native-feeling tab bar. All progress lives in the browser
(`localStorage` / IndexedDB), never the server.

**Runtime: fully static.** The data is frozen into JSON at build time and served
from a CDN — no database, no serverless functions, nothing to run out of quota.

```
dutch-flashcard-app/
├── data/
│   ├── seed_words.json        # hand-authored 20-word verification batch (Claude, no API)
│   ├── corpus_words.json      # auto-built corpus (frequency + Wiktionary + Tatoeba)
│   ├── image_candidates.txt   # curated concrete nouns worth an image (pick_image_words.py)
│   ├── audio_manifest.json    # which audio clips exist on the CDN branch
│   └── sources/               # downloaded open datasets (see scripts/fetch_sources.sh)
├── db/
│   ├── schema.sql             # SQLite schema  (BUILD-TIME ONLY)
│   └── flashcards.db          # build artifact — build_static.py reads it, then nothing does
├── scripts/
│   ├── fetch_sources.sh       # one-time: download the open datasets (~280 MB)
│   ├── conjugator.py          # rule-based Dutch verb conjugation engine
│   ├── build_corpus.py        # datasets -> corpus_words.json (+ report)
│   ├── seed_db.py             # *_words.json -> SQLite build DB
│   ├── build_static.py        # build DB -> public/data/*.json  (the deploy artifact)
│   ├── pick_image_words.py    # corpus -> data/image_candidates.txt (concreteness-filtered)
│   ├── fetch_images.py        # candidates -> images/<lemma>.jpg via Openverse
│   ├── generate_audio.py      # queued audio -> cached .mp3 (free/local TTS)
│   ├── publish_audio.mjs      # push audio/ + images/ to the jsDelivr `audio` branch
│   ├── refresh_media.sh       # publish media + rebuild static + (commit/push)
│   └── serve.py               # local static file server
├── public/                    # the app — this whole folder is what deploys
│   ├── index.html · app.css · app.js · srs.js · sw.js · manifest.webmanifest · icon-*.png
│   └── data/                  #   cards.json · details.json · sets.json · stats.json (built)
├── images/                    # per-word CC photos, fetched by fetch_images.py (gitignored)
└── audio/{word,sentence}/     # cached .mp3 (gitignored; live on the `audio` branch)
```

## Phase 2 — review app

```bash
python3 scripts/serve.py        # then open http://localhost:8000
```

- **Review** — SM-2 spaced repetition. Front: word + de/het tag + fill-in-the-blank
  sentence + audio. Flip (tap / "Show answer" / Space) for definition, translation,
  full sentence, and for verbs the **whole 42-form conjugation table as one card**
  (never 42 scattered cards). Rate **Again / Hard / Good / Easy** (buttons, keys
  1–4, or **swipe → knew it / ← didn't**). Session = 30 due-or-new cards, "due
  today" queue orders by *most-lapsed* then *most-overdue*, tops up with ≤20 new.
  Thin progress bar + `card N / 30`; session-complete summary.
- **Browse / Search** — flip through any set, or look up any word (see Phase 4
  for the Stats tab).

### Phase 3 — audio

- **One-tap** 🔊 on the word (front) and the example sentence (back).
- **Auto-play** toggles in the header 🔊 menu (persisted): word on card show
  (default **on**), sentence on flip (default **off**). First play in a session
  may be blocked by the browser until you touch the screen once.
- Missing clip → a flat muted 🔇 glyph, never a dead button. Playing → the button
  pulses. Replay with the button or the **R** key.
- Bonus: if you generate per-form audio (`generate_audio.py --audio-conjugations`),
  every cell of a verb's conjugation table becomes tap-to-hear; otherwise plain text.
- **No new API calls** — everything streams from `audio/…/*.mp3` written in Phase 1.

### Phase 4 — stats, streaks & polish

- **Streak** — consecutive days with ≥1 review. A subtle `🔥 N` chip in the header
  (turns orange once you've reviewed today); full detail + a 14-day activity
  sparkline on the **Stats** tab.
- **Stats** — words mastered / in progress / due / not started, and **completion %
  per CEFR level** with a bar (mastered · in-progress · learning · new).
- **Difficulty heatmap** — your weakest words as terracotta tiles (intensity =
  lapses + lost ease), tap one to open the card.
- **Mark as known** — "✓ I already know this" on the review card and browse card
  (with undo) — skip the grind, still counts toward the streak.
- **Dark mode** — the ◐ button, top right (persisted; also follows the OS by default).
- **Per-word images** — concrete nouns get a Creative-Commons photo on the card
  front, sized as a co-equal focal point with the word (image ~55–65 % of the
  card height on mobile, the lemma large and bold directly below, de/het + 🔊
  small and secondary). Abstract words, particles and most verbs/adjectives get
  no image and fall back to the text-only card; a broken image does the same.
  - **Which words** — `scripts/pick_image_words.py` builds `data/image_candidates.txt`:
    corpus nouns with a de/het article, no verb-homograph collision (every
    finite form of every corpus verb is excluded via `conjugator.py`), and an
    English gloss whose head word scores ≥ 4.25 concreteness in the Brysbaert
    ratings. Blind keyword search only works for concrete, picturable nouns —
    the full frequency list is far too noisy. Default output ≈ 600 words.
  - **Fetching** — `scripts/fetch_images.py` sources from the **Openverse** API
    (no account; ~200 req/day anonymous, so it's throttled). Picks a
    card-friendly CC image, downscales to `images/<lemma>.jpg`, writes the pick
    + attribution into the content JSON (`words.image_*`). Flags: `--only-list`
    (the curated set), `--strict-title` (only images whose title matches the
    query), `--requests N` (daily cap, resumable), `--top`, `--redo`, `--dry-run`.
    `data/image_stoplist.txt` blocks lemmas *and deletes* any already-fetched
    image for them; `data/image_misses.txt` (auto) skips dead ends on re-runs.
    A daily scheduled task grows coverage; QA is a contact-sheet pass adding
    duds to the stoplist.
  - The image URL + CC credit are baked into `details.json` by `build_static.py`
    (`--deploy` → jsDelivr URL; local → `/img/<lemma>` so you can preview freshly
    fetched images). Publish with `scripts/refresh_media.sh`.

### Phase 5 — PWA (install · offline · reminder)

- **Installable** — `manifest.webmanifest` + icons + apple-touch meta. In Chrome
  or Safari (not the in-app preview browser), "Add to Home Screen" / "Install"
  launches it full-screen with no browser chrome.
- **Offline** — `sw.js` precaches the app shell and caches data, audio and images
  as you use them (cache-first for `/audio`, `/img`, `/api/word/*`;
  stale-while-revalidate for `/api/cards` & co; `index.html` fallback for
  navigations). Review runs fully offline once cards have loaded once.
- **Daily reminder** — Settings (⚙️) → *Notify me when cards are due*. Requests
  notification permission, then (on Chrome/Android, installed) registers a
  `periodicSync` that fires ~daily; the page writes the due count into IndexedDB
  so the service worker can read it. *Send a test notification* fires one now.
  iOS needs 16.4+ **and** the app on the Home Screen. A truly guaranteed daily
  push (phone off, app closed for days) needs an always-on server — out of scope
  for a local personal build; this covers the normal case.
- **Tab bar** — Review / Sets / Stats / Search, blurred, safe-area-aware,
  44 px+ targets, press-scale feedback.

**Testing** (must be a real browser, `http://localhost:8000`):
DevTools → Application → Service Workers shows it active; tick *Offline* there
and reload — the app still runs. Install via the omnibox icon / Share sheet.
Reminder: Settings → test notification.

All scheduling is in `localStorage` (key `dfx-srs-v1`) — the review loop makes
**zero network calls** after the initial card load, which is what lets Phase 5
drop the server entirely. "Reset all progress" on the start screen clears it.

`serve.py` gained `/api/cards` (lean list for the queue) and now serves the
`viewer/` directory; `/api/word/{id}` still returns full per-card detail.

## Pipeline

```bash
cd dutch-flashcard-app

# 1. one-time dataset download (~280 MB into data/sources/)
bash scripts/fetch_sources.sh

# 2. build the corpus (default 2000 words; raise for B2 breadth)
python3 scripts/build_corpus.py --limit 2000

# 3. load it into the build DB
python3 scripts/seed_db.py --reset --json data/corpus_words.json

# 4. freeze the data into static JSON the app serves directly
python3 scripts/build_static.py

# 5. audio (pick one; both free, no key). Report first:
python3 scripts/generate_audio.py --report
python3 scripts/generate_audio.py --provider edge --voice nl-NL-MaartenNeural
```

Re-run `build_corpus.py --limit N` any time to grow the set; `seed_db.py` is
idempotent (`--reset` rebuilds from scratch). `db/flashcards.db` is now only a
*build* artifact — `build_static.py` reads it once and the finished app never
touches a database.

### 6. Run the app

```bash
npm run dev                       # build_static.py + serve.py; open http://localhost:8000
```

Opens the Phase 2 review app (see **Phase 2** above). Streaks, the difficulty
heatmap, per-set stats and PWA install are Phases 4–5 in
`dutch-flashcard-app-build-prompts.md`.

Audio is generated lazily — do it a set at a time:

```bash
python3 scripts/generate_audio.py --provider edge --voice nl-NL-MaartenNeural --set "A1 (frequency)"
```

The full 8000-word set is ~15,000 clips; via edge-tts that is a multi-hour
one-time run (Piper, running locally in parallel, is much faster). Cards with no
audio yet just show a muted button.

## Open datasets used (all offline, no keys)

| Dataset | Used for | License |
|---|---|---|
| [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords) `nl_50k` (OpenSubtitles) | word ranking → which lemmas, CEFR band heuristic | CC-BY-SA 4.0 |
| [kaikki.org](https://kaikki.org/dictionary/Dutch/) Dutch Wiktionary extract | part of speech, English gloss, de/het + gender + plural, verb forms | CC-BY-SA 4.0 / GFDL |
| [Tatoeba](https://tatoeba.org) `nld` sentences + `nld-eng` links | example sentences + English translations + fill-in-the-blank | CC-BY 2.0 FR |
| FreeDict `nld-eng` | *optional* fallback translations (not used by default) | GPL-2.0 |

The generated `flashcards.db` is a derivative of CC-BY-SA and CC-BY material —
attribute those sources in the app's About screen and license the bundled data
accordingly. See `data/corpus_words.json` → `meta.sources`.

## Verb conjugation engine (`scripts/conjugator.py`)

Rules-first, data-corrected:

1. **Weak (regular) verbs** — spelling rules: stem derivation (`maken`→`maak`,
   `studeren`→`studeer`, `openen`→`open`), `'t kofschip` for `-te/-de` and the
   past participle, separable-prefix handling (`opbellen`→`ik bel op` /
   `opgebeld`).
2. **Strong / irregular verbs** — a hand-coded table of ~135 verbs
   `(imperfectum sg, imperfectum pl, past participle, auxiliary)`, plus 12 that
   are also irregular in the present (`zijn`, `hebben`, `kunnen`, …).
3. **Wiktionary override** — when the corpus builder has Wiktionary forms for a
   verb, those replace the rule output; the participle is always taken from
   Wiktionary when present. The rule engine only fully owns verbs Wiktionary
   doesn't cover (`corpus_report.md` → "conjugated by spelling rules only").
4. The 4 compound tenses (perfectum, plusquamperfectum, futurum, futurum
   exactum, conditionalis) are assembled here — fully regular given
   participle + infinitive + auxiliary.

```bash
python3 scripts/conjugator.py --selftest
python3 scripts/conjugator.py werken hebben zijn opbellen gaan studeren
```

## Schema — [db/schema.sql](db/schema.sql)

Only a *build-time* SQLite database (`seed_db.py` → `build_static.py` reads it →
static JSON). Nothing queries it at runtime.

`word_sets` · `words` (noun cols + verb cols + `image_*`, NULL when N/A) ·
`word_set_members` (M:N) · `example_sentences` (incl. `sentence_blanked`) ·
`verb_conjugations` (`tense` + `person` CHECK-constrained, sort keys) ·
`audio_assets` (`status`, relative `file_path`, `char_count`) · `v_word_card` view.

`tense ∈ {presens, imperfectum, perfectum, plusquamperfectum, futurum, futurum_exactum, conditionalis}`
`person ∈ {ik, jij, hij, wij, jullie, zij_mv}`

`definition_nl` is NULL for the corpus (Wiktionary's English edition has no Dutch
definitions) — the English gloss covers both translation and definition. The
hand-authored `seed_words.json` batch does have Dutch definitions.

Phase 2 adds SRS tables (`review_state`, `review_log`); not built yet.

## Current corpus (`--limit 2000`)

2000 words — 979 nouns (de/het + gender + plural), 333 verbs (full 42-form
tables), 349 adjectives, 125 adverbs, rest function words. 1988 Tatoeba example
sentences with English translations + fill-in-the-blank. Sets: A1 563 / A2 516 /
B1 900 / B2 21.

CEFR bands are a **frequency heuristic** (rank ≤750 A1, ≤1500 A2, ≤3000 B1, else
B2), not official CEFR. `--limit 2000` only reaches rank ~3000, so B2 is nearly
empty — run `--limit 8000` (or higher) for real B2 breadth; the pipeline is
unchanged, it just takes ~30s and a bigger DB.

**Review before trusting at scale — `data/corpus_report.md` has every row:**
- 12 words with no example sentence (rare loanwords / interjections: `sheriff`, `bravo`, `euh`)
- 8 nouns with no de/het (plurale tantum: `kleren`, `hersenen`, `data`, …)
- 1 verb conjugated by spelling rules only (`wegwezen`, a fixed expression)
- 26 frequency tokens skipped as non-infinitive verb forms / plural homographs
- verb cloze occasionally blanks a homograph (`begin` the noun, `weg`) — the
  builder has no sentence-level POS tagging
- `POS_FORCE` / `SKIP_LEMMAS` in `build_corpus.py` are the hand-maintained
  override lists — extend them as review turns up more edge cases

---

## Audio: Google Cloud TTS free tier & scaling

**Google Cloud TTS free tier** (per calendar month, resets monthly):

| Voice type | Free chars / month | Price after free |
|---|---|---|
| Standard | 4,000,000 | $4 / 1M |
| WaveNet | 1,000,000 | $4 / 1M |
| Neural2 | 1,000,000 | $16 / 1M |
| Studio | 100,000 | $30 / 1M |

Sources: [Google pricing](https://cloud.google.com/text-to-speech/pricing),
[Speechify 2026](https://speechify.com/blog/google-text-to-speech-api/),
[costbench 2026](https://costbench.com/software/ai-voice-tools/google-cloud-text-to-speech/free-plan/).
Verify before a large run.

**20-word test batch:** 901 chars — free everywhere.
**2000-word corpus (words + sentences):** 62,340 chars — 1.6% of the Standard
free tier, 6.2% of WaveNet. Free.
**Full 10,000-word B2 set (words + sentences):** ~630,000 chars — still free on
Google Standard *and* WaveNet.

### Projection to a full B2 set (~5,000–10,000 words)

~63 chars/word (lemma + one sentence); optional per-form conjugation audio adds
~756 chars/verb.

| Scenario | Characters | Google Standard (4M/mo) | Google WaveNet (1M/mo) |
|---|---|---|---|
| 10,000 words, no conjugation audio | ~630,000 | free | free |
| 10,000 words + conj. audio for ~600 core verbs | ~1,084,000 | free | **over ~84k (~$0.34)** |
| 10,000 words + conj. audio for ~1,500 verbs | ~1,764,000 | free | **over ~764k (~$3 / Neural2 ~$12)** |

### The flag

- **Words + sentences only:** never exceeds the free tier at any realistic scale.
- **Full conjugation-table audio for many verbs** crosses ~1M chars: still free
  on Google **Standard**, but **breaks WaveNet/Neural2's monthly free tier**.
  Mitigate: use Standard voices, or split the one-time run across two calendar
  months, or skip per-form conjugation audio. Studio's 100k/mo tier is unusable.

### Recommended: skip the metered API

The word list will keep growing, so use a free **unmetered** engine —
`generate_audio.py` supports `--provider {report,espeak,piper,edge,google}`:

1. **Piper** (rhasspy/piper) — local, open-source, neural, offline, `$0`, no
   quota, reproducible. Dutch voices `nl_NL-nathalie-medium`, `nl_NL-mls_7432-low`.
   **Top pick for the full set.**
2. **edge-tts** (`pip install edge-tts`) — free, no key, neural
   `nl-NL-MaartenNeural` / `nl-NL-ColetteNeural`. **Used for the demo audio here.**
3. **Amazon Polly** free tier — 5M chars/month for the first 12 months.
4. eSpeak NG — tiny, robotic; fallback for any failed file.

---

## Deployment

**Live:** https://dutch-flashcard-app.vercel.app  ·  auto-deploys on push to `main`.

**Fully static — no database, no serverless functions.** The dataset never
changes at runtime, so `build_static.py` freezes it into JSON files and Vercel's
CDN serves them.

- **What deploys:** just `public/` — the shell + `public/data/{cards,details,sets,stats}.json`
  (committed) + icons. `vercel.json` has no build step and no functions.
- **Regenerating the data** (after `build_corpus.py`, `generate_audio.py` or
  `fetch_images.py`):

    ```bash
    python3 scripts/seed_db.py --json data/corpus_words.json --reset
    python3 scripts/build_static.py --deploy      # bakes jsDelivr URLs + bumps the SW
    git add public/data data/audio_manifest.json && git commit && git push
    ```

- **Audio + images** live on the orphan **`audio`** branch, served by **jsDelivr**
  (`cdn.jsdelivr.net/gh/<user>/dutch-flashcards@audio/{audio,images}/...`). Their
  absolute URLs are baked into `details.json` at build time. `data/audio_manifest.json`
  records which clips exist (so the build knows which to link).

```bash
# generate more audio (background; edge-tts is slow/flaky, re-run as needed)
python3 scripts/generate_audio.py --provider edge --voice nl-NL-MaartenNeural --redo-errors
#   ...or faster, no rate limits:  --provider piper --piper-model voices/<nl>.onnx

# fetch per-word images (throttled ~150/day; a scheduled task loops this)
python3 scripts/pick_image_words.py                       # -> data/image_candidates.txt
python3 scripts/fetch_images.py --json data/corpus_words.json \
        --only-list data/image_candidates.txt --strict-title --requests 150

# publish everything: push media to the branch, rebuild static, then commit + push
bash scripts/refresh_media.sh
```

**History:** earlier revisions used Turso (libSQL) behind Vercel functions; the
free-tier read quota couldn't take `/api/details` scanning the whole dataset on
every visit, so it moved to static. `.env.example` still lists the old vars.

New files appear on the live site within ~12 h (jsDelivr branch cache), sooner
after the automatic purge. The service worker caches each played clip / shown image.
`push_images_to_turso.mjs` only ALTERs the columns in and UPDATEs the rows — it
never `DELETE`s from `words`, so the deployed audio is untouched.
