#!/usr/bin/env python3
"""
pick_image_words.py — choose which corpus words are worth an auto-fetched image.

Blind keyword image search only works for *concrete, picturable* nouns. This
script builds that shortlist from data/corpus_words.json using:

  * part of speech == noun, with a de/het article, lemma length >= 3
  * NOT a verb homograph — every present/past singular form of every corpus
    verb is excluded (kills 'was', 'weet', 'geef', 'zit', 'kom', 'praat' …)
  * an English-gloss head word with a Brysbaert concreteness rating >= --min
    (data/sources/concreteness.txt — see scripts/fetch_sources.sh)
  * a short gloss (<= 3 content words) and no abstract markers

Output: data/image_candidates.txt (one lemma per line, most frequent first),
consumed by  scripts/fetch_images.py --only-list data/image_candidates.txt

    python3 scripts/pick_image_words.py                 # default --min 4.0
    python3 scripts/pick_image_words.py --min 4.25 --max 400
"""
import argparse
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import conjugator  # noqa: E402

CORPUS = os.path.join(ROOT, "data", "corpus_words.json")
CONC = os.path.join(ROOT, "data", "sources", "concreteness.txt")
OUT = os.path.join(ROOT, "data", "image_candidates.txt")
STOPLIST = os.path.join(ROOT, "data", "image_stoplist.txt")

_STOP = {"a", "an", "the", "to", "of", "for", "or", "and", "with", "in", "on",
         "at", "that", "which", "used", "esp", "usually", "something", "someone",
         "act", "state", "person", "piece", "kind", "type", "sort", "form"}
_ABSTRACT_RE = re.compile(
    r"\b(act|state|quality|fact|process|condition|manner|way|degree|"
    r"feeling|idea|concept|ability|amount|period|point|sense|matter)\b", re.I)


def load_concreteness():
    conc = {}
    with open(CONC, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            try:
                conc[row["Word"].strip().lower()] = float(row["Conc.M"])
            except (ValueError, KeyError):
                pass
    return conc


def load_stoplist():
    out = set()
    if os.path.isfile(STOPLIST):
        for line in open(STOPLIST, encoding="utf-8"):
            line = line.split("#")[0].strip().lower()
            if line:
                out.add(line)
    return out


def verb_forms(words):
    """Every single-word finite form of every corpus verb (+ the infinitive)."""
    forms = set()
    for w in words:
        if w.get("part_of_speech") != "verb":
            continue
        inf = w["lemma"]
        forms.add(inf.lower())
        try:
            c = conjugator.conjugate(inf, w.get("auxiliary") or "hebben")
        except Exception:  # noqa: BLE001
            continue
        for tense in ("presens", "imperfectum"):
            for form in c["conjugations"].get(tense, {}).values():
                parts = form.split()
                if len(parts) == 2:            # 'ik geef' -> 'geef'
                    forms.add(parts[1].lower())
    return forms


def gloss_words(t):
    t = re.split(r"[;,/(]", t or "")[0].strip().lower()
    return [w for w in re.findall(r"[a-z][a-z'-]*", t) if w not in _STOP]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min", type=float, default=4.0,
                    help="minimum Brysbaert concreteness (1-5, default 4.0)")
    ap.add_argument("--max", type=int, default=0, help="cap the list at N words")
    ap.add_argument("--json", default=CORPUS)
    args = ap.parse_args()

    for p in (args.json, CONC):
        if not os.path.isfile(p):
            sys.exit("missing: %s" % p)

    data = json.load(open(args.json, encoding="utf-8"))
    words = data["words"]
    conc = load_concreteness()
    stop = load_stoplist()
    vforms = verb_forms(words)
    print("corpus verbs -> %d excluded word forms" % len(vforms))

    picked, rej = [], {"homograph": 0, "abstract": 0, "long_gloss": 0,
                       "low_conc": 0, "no_conc": 0, "stoplist": 0, "shape": 0}
    for w in words:
        if w.get("part_of_speech") != "noun":
            continue
        lemma = w["lemma"]
        low = lemma.lower()
        if len(lemma) < 3 or w.get("article") not in ("de", "het"):
            rej["shape"] += 1
            continue
        if low in stop:
            rej["stoplist"] += 1
            continue
        if low in vforms:
            rej["homograph"] += 1
            continue
        gw = gloss_words(w.get("translation_en") or "")
        if not gw:
            rej["shape"] += 1
            continue
        if len(gw) > 3:
            rej["long_gloss"] += 1
            continue
        if _ABSTRACT_RE.search(w.get("translation_en") or ""):
            rej["abstract"] += 1
            continue
        scores = [conc[g] for g in gw[:2] if g in conc]
        if not scores:
            rej["no_conc"] += 1
            continue
        best = max(scores)
        if best < args.min:
            rej["low_conc"] += 1
            continue
        picked.append((w.get("frequency_rank") or 10**9, lemma, best,
                       " ".join(gw[:2])))

    picked.sort()
    if args.max:
        picked = picked[:args.max]

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("# concrete, picturable corpus nouns — feed to "
                 "fetch_images.py --only-list\n")
        fh.write("# min concreteness %.2f · %d words · regenerate with "
                 "scripts/pick_image_words.py\n" % (args.min, len(picked)))
        for _, lemma, _, _ in picked:
            fh.write(lemma + "\n")

    print("\nrejected: " + ", ".join("%s=%d" % kv for kv in rej.items()))
    print("PICKED %d words -> %s" % (len(picked), os.path.relpath(OUT, ROOT)))
    print("\nfirst 40:", ", ".join(l for _, l, _, _ in picked[:40]))
    print("\nsample with gloss/score:")
    for _, l, s, g in picked[:15]:
        print("  %-14s %.2f  %s" % (l, s, g))


if __name__ == "__main__":
    main()
