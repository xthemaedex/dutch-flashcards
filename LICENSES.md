# Data licensing

The flashcard content is derived from open datasets. `flashcards.db` and
`data/corpus_words.json` are therefore a **derivative work** and must carry
attribution. Add an "About / Credits" screen in the app with the following.

| Source | What it contributes | License | Attribution / share-alike |
|---|---|---|---|
| **Wiktionary** via [kaikki.org](https://kaikki.org/) (Tatu Ylonen, *wiktextract*) | part of speech, English glosses, de/het + gender, plural, verb forms | CC BY-SA 4.0 / GFDL | Attribute "Wiktionary"; the derived data is **share-alike** — release the bundled dictionary data under CC BY-SA 4.0. |
| **Tatoeba** ([tatoeba.org](https://tatoeba.org/)) | example sentences + English translations | CC BY 2.0 FR | Attribute "Tatoeba.org and contributors"; link the sentence source. |
| **hermitdave/FrequencyWords** (OpenSubtitles 2018) | word frequency ranking → set membership, CEFR band heuristic | CC BY-SA 4.0 | Attribute; ranking data is share-alike. |
| **Openverse** ([openverse.org](https://openverse.org/)) — aggregates Flickr, Wikimedia Commons, etc. | per-word photos on the card front | per-image (CC0 / PDM / CC BY / CC BY-SA / CC BY-NC…) | Each image's ready-made credit line is stored in `words.image_attribution` and shown under the photo. A Credits screen should list them; the license is per file (see `image_license`). |
| **Brysbaert, Warriner & Kuperman (2014)** concreteness ratings, via [ArtsEngine/concreteness](https://github.com/ArtsEngine/concreteness) | picks which nouns are concrete enough to try fetching an image for — not shipped in the app | free for research use | Cite the paper ("Concreteness ratings for 40 thousand generally known English word lemmas", *Behavior Research Methods*). Build-time only; no derived data in `flashcards.db`. |
| FreeDict `nld-eng` (**not used by default**) | optional fallback translations | GPL-2.0 | Only enable if you accept GPL obligations on the bundled data. |

Notes:
- App **code** you write is unaffected — only the bundled *data* inherits these terms.
- CC BY-SA "share-alike" applies to the dictionary/frequency-derived fields, not
  to your UI or spaced-repetition logic.
- The rule-based conjugator output (`scripts/conjugator.py`) is your own work;
  where it copies Wiktionary forms, those remain CC BY-SA.
- Generated audio (Piper / edge-tts): Piper voices are typically MIT/CC0 —
  check the specific voice card. edge-tts audio comes from a Microsoft service;
  fine for personal use, review terms before public redistribution. This is why
  **Piper is recommended for anything you ship.**
