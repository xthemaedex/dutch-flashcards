#!/usr/bin/env python3
"""
build_static.py — freeze the read-API into static JSON files.

The flashcard data never changes at runtime, so instead of a database + a
serverless function per request, we precompute every response once and serve
the files straight from the CDN. Run this after seed_db.py.

    python3 scripts/seed_db.py --json data/corpus_words.json --reset
    python3 scripts/build_static.py                       # local: relative media paths
    python3 scripts/build_static.py --deploy              # prod: jsDelivr media URLs

Outputs (into public/data/):
    cards.json     lean list for the SRS queue + card fronts
    details.json   every word's full back-of-card detail (the big one, ~8 MB)
    sets.json      the CEFR bands + word counts
    stats.json     counts for the Stats screen
    meta.json      { generated, words, audio, images }

Search and browse-by-set are done client-side from cards.json — no endpoint.
"""
import argparse
import json
import os
import sqlite3
import time

import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "db", "flashcards.db")
OUT = os.path.join(ROOT, "public", "data")
SW = os.path.join(ROOT, "public", "sw.js")
AUDIO_MANIFEST = os.path.join(ROOT, "data", "audio_manifest.json")

CDN = "https://cdn.jsdelivr.net/gh/xthemaedex/dutch-flashcards@audio"

TENSE_ORDER = ["presens", "imperfectum", "perfectum", "plusquamperfectum",
               "futurum", "futurum_exactum", "conditionalis"]
PERSON_ORDER = ["ik", "jij", "hij", "wij", "jullie", "zij_mv"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deploy", action="store_true",
                    help="images -> jsDelivr URLs (default: /img/<lemma>, so you "
                         "can preview freshly-fetched images before they're on the CDN). "
                         "Also bumps the service-worker cache version.")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        raise SystemExit("no %s — run seed_db.py first" % args.db)
    os.makedirs(OUT, exist_ok=True)

    audio_base = CDN + "/audio"                             # always the CDN — stable, public
    image_base = CDN + "/images" if args.deploy else None   # else /img/<lemma> route

    have_audio = set()
    if os.path.isfile(AUDIO_MANIFEST):
        have_audio = set(json.load(open(AUDIO_MANIFEST)))

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    def audio_url(scope, aid):
        if aid not in have_audio:
            return None
        return "%s/%s/%05d.mp3" % (audio_base, scope, aid)

    def image_obj(w):
        if not w["image_path"]:
            return None
        lemma = w["lemma"].lower()
        url = (image_base + "/" + lemma + ".jpg") if image_base else "/img/" + lemma
        return {"url": url, "attribution": w["image_attribution"],
                "license": w["image_license"], "source_url": w["image_source_url"]}

    # ---- sets.json ----
    sets = [dict(r) for r in conn.execute("""
        SELECT ws.id, ws.name, ws.cefr_level, ws.description,
               COUNT(m.word_id) AS word_count
        FROM word_sets ws LEFT JOIN word_set_members m ON m.set_id = ws.id
        GROUP BY ws.id ORDER BY ws.sort_order, ws.name""")]
    dump("sets.json", sets)

    # ---- cards.json ----
    cards = [dict(r) for r in conn.execute("""
        SELECT w.id, w.lemma, w.part_of_speech AS pos, w.article, w.gender,
               w.cefr_level AS cefr, w.frequency_rank AS rank, w.translation_en,
               s.sentence_nl, s.sentence_blanked,
               (w.part_of_speech = 'verb') AS is_verb
        FROM words w
        LEFT JOIN example_sentences s ON s.word_id = w.id AND s.sort_order = 0
        ORDER BY w.frequency_rank""")]
    dump("cards.json", cards)

    # ---- details.json ----
    out = {}
    for w in conn.execute("SELECT * FROM words"):
        out[w["id"]] = {
            "translation_en": w["translation_en"],
            "definition_nl": w["definition_nl"], "definition_en": w["definition_en"],
            "article": w["article"], "gender": w["gender"], "plural": w["plural"],
            "auxiliary": w["auxiliary"], "past_participle": w["past_participle"],
            "is_separable": w["is_separable"], "is_irregular": w["is_irregular"],
            "part_of_speech": w["part_of_speech"],
            "image": image_obj(w),
            "sentences": [], "audio": {},
        }

    for r in conn.execute(
            "SELECT * FROM example_sentences ORDER BY word_id, sort_order"):
        d = out.get(r["word_id"])
        if d is not None:
            d["sentences"].append(dict(r))

    for r in conn.execute(
            "SELECT word_id, id, tense, person, form FROM verb_conjugations"):
        d = out.get(r["word_id"])
        if d is None:
            continue
        d.setdefault("conjugations", {t: {} for t in TENSE_ORDER})
        d.setdefault("conj_ids", {t: {} for t in TENSE_ORDER})
        d.setdefault("persons", PERSON_ORDER)
        d["conjugations"][r["tense"]][r["person"]] = r["form"]
        d["conj_ids"][r["tense"]][r["person"]] = r["id"]

    n_audio = 0
    for r in conn.execute(
            "SELECT id, scope, word_id, sentence_id, conjugation_id FROM audio_assets"):
        url = audio_url(r["scope"], r["id"])
        if not url:
            continue
        d = out.get(r["word_id"])
        if d is None:
            continue
        if r["scope"] == "sentence":
            key = "sentence:%s" % r["sentence_id"]
        elif r["scope"] == "conjugation":
            key = "conj:%s" % r["conjugation_id"]
        else:
            key = r["scope"]
        d["audio"][key] = url
        n_audio += 1
    dump("details.json", out)

    # ---- stats.json ----
    stats = {
        "words": conn.execute("SELECT COUNT(*) FROM words").fetchone()[0],
        "by_pos": {r[0]: r[1] for r in conn.execute(
            "SELECT part_of_speech, COUNT(*) FROM words GROUP BY part_of_speech")},
        "sentences": conn.execute("SELECT COUNT(*) FROM example_sentences").fetchone()[0],
        "conjugations": conn.execute("SELECT COUNT(*) FROM verb_conjugations").fetchone()[0],
        "audio_done": n_audio,
        "audio_total": conn.execute("SELECT COUNT(*) FROM audio_assets").fetchone()[0],
    }
    dump("stats.json", stats)

    n_img = conn.execute(
        "SELECT COUNT(*) FROM words WHERE image_path IS NOT NULL").fetchone()[0]
    dump("meta.json", {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deploy": args.deploy, "words": stats["words"],
        "audio": n_audio, "images": n_img,
    })
    conn.close()

    bump = bump_sw() if args.deploy else None
    print("\n%d words · %d audio clips · %d images · deploy=%s%s"
          % (stats["words"], n_audio, n_img, args.deploy,
             ("  · sw -> " + bump) if bump else ""))


def bump_sw():
    """Increment the service-worker cache version so clients pick up new data.
    (A redeploy only re-runs the SW install when sw.js itself changed.)"""
    if not os.path.isfile(SW):
        return None
    src = open(SW, encoding="utf-8").read()
    m = re.search(r'const CACHE = "dfx-v(\d+)"', src)
    if not m:
        return None
    nxt = int(m.group(1)) + 1
    open(SW, "w", encoding="utf-8").write(
        src[:m.start()] + 'const CACHE = "dfx-v%d"' % nxt + src[m.end():])
    return "v%d" % nxt


def dump(name, obj):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    print("  %-14s %6.1f KB" % (name, os.path.getsize(path) / 1024))


if __name__ == "__main__":
    main()
