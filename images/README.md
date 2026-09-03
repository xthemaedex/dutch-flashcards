# Per-word images (optional)

Drop an image named after the Dutch lemma and it shows on that card — front of
the review card and the browse card. No database change, no config.

```
images/hond.jpg      -> appears on the "hond" card
images/fiets.png
images/huis.webp
```

Supported: `.jpg` `.jpeg` `.png` `.webp` `.gif`. Served by `scripts/serve.py` at
`/img/<lemma>`; a missing file just means no image (the `<img>` removes itself).

Nothing here is auto-populated — Phase 4 only wires up display. A later phase
could bulk-fetch open-licensed images (e.g. Openverse / Wikimedia Commons).
