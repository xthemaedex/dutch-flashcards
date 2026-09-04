#!/usr/bin/env python3
"""
fetch_images.py — one-time per-word image sourcing for the flashcard DB.

Looks up a Creative-Commons photo for each picturable word via the Openverse API
(https://api.openverse.org — no account required), downloads it, downscales it,
and writes it to  images/<lemma>.jpg . The chosen image + its attribution are
written back into the content JSON (data/seed_words.json by default) so a plain
`seed_db.py --reset` reproduces everything. The finished app only ever serves the
saved file — no API calls at runtime.

Words that get no acceptable match (abstract nouns, particles, most verbs/
adjectives) are simply left without an image; the card renders text-only.

Usage
-----
  python3 scripts/fetch_images.py                     # nouns in data/seed_words.json
  python3 scripts/fetch_images.py --pos noun,verb     # widen the candidate set
  python3 scripts/fetch_images.py --limit 5 --dry-run # preview picks, download nothing
  python3 scripts/fetch_images.py --redo huis,hond    # re-fetch specific lemmas
  python3 scripts/fetch_images.py --json data/corpus_words.json   # full set (scale-up)

Scale-up note: anonymous Openverse access is rate-limited (20/min, 200/day). For
thousands of words, register a free client once (no approval needed) and export
OPENVERSE_CLIENT_ID / OPENVERSE_CLIENT_SECRET — this script will use them for a
much higher quota. See: https://api.openverse.org/v1/#tag/auth
"""

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_JSON = os.path.join(ROOT, "data", "seed_words.json")
IMG_DIR = os.path.join(ROOT, "images")
STOPLIST = os.path.join(ROOT, "data", "image_stoplist.txt")
MISSES = os.path.join(ROOT, "data", "image_misses.txt")   # words that returned nothing usable

API = "https://api.openverse.org/v1/images/"
TOKEN_URL = "https://api.openverse.org/v1/auth_tokens/token/"
UA = ("Mozilla/5.0 (compatible; dutch-flashcards/1.0; "
      "+https://github.com/xthemaedex/dutch-flashcards)")

# Openverse licence codes we accept, best first. 'all' via --licenses overrides.
DEFAULT_LICENSES = ["cc0", "pdm", "by", "by-sa", "by-nc", "by-nc-sa"]
MIN_W, MIN_H = 500, 375          # reject tiny / icon-sized results
MAX_W = 1000                     # downscale target (keeps the CDN branch lean)
JPEG_Q = 82
PER_REQUEST_SLEEP = 3.5          # stay comfortably under 20 req/min anonymous

try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: Pillow is required (pip install Pillow)")


def log(m):
    print(m, flush=True)


# --------------------------------------------------------------------------
# Openverse
# --------------------------------------------------------------------------
def get_token():
    cid = os.environ.get("OPENVERSE_CLIENT_ID")
    secret = os.environ.get("OPENVERSE_CLIENT_SECRET")
    if not (cid and secret):
        return None
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret,
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        tok = json.load(r)["access_token"]
    log("  using authenticated Openverse client (higher rate limit)")
    return tok


def api_get(url, token=None, tries=4):
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = "Bearer " + token
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 15 * (attempt + 1)
                log("  rate-limited; sleeping %ds" % wait)
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt < tries - 1:
                time.sleep(5)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(5)
                continue
            raise
    return None


def search(query, token, licenses):
    params = {
        "q": query,
        "page_size": 12,
        "mature": "false",
        "aspect_ratio": "wide,square",
        "extension": "jpg,jpeg,png",
    }
    if licenses:
        params["license"] = ",".join(licenses)
    data = api_get(API + "?" + urllib.parse.urlencode(params), token)
    return (data or {}).get("results", []) or []


def pick(results, licenses, query, strict_title=False):
    """Best usable result, or None. Ranking, best first:
      1. a query word appears in the image title (cheap relevance signal)
      2. licence preference order
      3. a card-friendly aspect ratio (landscape ~3:2, then square)
      4. larger is better
    Extreme panoramas / very tall crops are rejected outright. With
    strict_title, a result whose title shares no word with the query is
    rejected entirely — many fewer images, but far less nonsense."""
    order = {c: i for i, c in enumerate(licenses or DEFAULT_LICENSES)}
    qwords = {w for w in re.findall(r"[a-z]+", (query or "").lower()) if len(w) > 2}
    scored = []
    for r in results:
        w, h = r.get("width") or 0, r.get("height") or 0
        if w < MIN_W or h < MIN_H or not r.get("url"):
            continue
        ar = w / h if h else 0
        if ar < 0.7 or ar > 2.2:
            continue
        title = (r.get("title") or "").lower()
        title_hit = 0 if (qwords and any(qw in title for qw in qwords)) else 1
        if strict_title and title_hit:
            continue
        lic = (r.get("license") or "").lower()
        ar_score = 0 if 1.15 <= ar <= 1.9 else 1        # landscape preferred, else ok
        scored.append((title_hit, order.get(lic, 99), ar_score, -(w * h), r))
    scored.sort(key=lambda t: t[:4])
    return scored[0][4] if scored else None


# --------------------------------------------------------------------------
# download + process
# --------------------------------------------------------------------------
def fetch_bytes(url, token=None):
    headers = {"User-Agent": UA, "Accept": "image/*"}
    if token and url.startswith("https://api.openverse.org/"):
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def save_image(raw, dest):
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGB")
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    im.save(dest, "JPEG", quality=JPEG_Q, optimize=True)
    return im.size


def download_image(result, lemma, token):
    """Try the original, fall back to Openverse's thumbnail proxy."""
    dest = os.path.join(IMG_DIR, lemma + ".jpg")
    candidates = [result.get("url")]
    if result.get("id"):
        candidates.append("https://api.openverse.org/v1/images/%s/thumb/" % result["id"])
    for src in filter(None, candidates):
        try:
            size = save_image(fetch_bytes(src, token), dest)
            return dest, size
        except Exception as e:  # noqa: BLE001
            log("    (%s failed: %s)" % (src.split("/")[2], e))
    return None, None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
_STOPWORDS = {"a", "an", "the", "to", "of", "for", "or", "and", "with", "in",
              "on", "at", "that", "which", "used", "esp", "e.g", "i.e", "usually",
              "something", "someone", "act", "state", "person", "piece"}


def query_for(word):
    """Search query for a word. An explicit "image_query" in the JSON wins;
    otherwise derive a short, concrete query from the English gloss:
      'city, town'                     -> 'city'
      'to work'                        -> 'work'
      'a set of intended actions'      -> 'set intended actions' -> 'intended'
      'a police officer'               -> 'police officer'
    Verbose Wiktionary definitions are trimmed to the first 2 content words."""
    q = (word.get("image_query") or "").strip()
    if q:
        return q
    t = word.get("translation_en", "") or word.get("lemma", "")
    t = re.split(r"[;,/(]", t)[0].strip().lower()
    words = [w for w in re.findall(r"[a-z][a-z'.-]*", t) if w not in _STOPWORDS]
    return " ".join(words[:2]) if words else t


def licence_label(result):
    lic = (result.get("license") or "").upper()
    ver = result.get("license_version") or ""
    if lic in ("CC0", "PDM"):
        return "CC0" if lic == "CC0" else "Public Domain Mark"
    return ("CC " + lic + (" " + ver if ver else "")).strip()


def _read_lemma_file(path):
    if not os.path.isfile(path):
        return set()
    out = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#")[0].strip().lower()
            if line:
                out.add(line)
    return out


def load_stoplist():
    return _read_lemma_file(STOPLIST)


def record_miss(lemma):
    with open(MISSES, "a", encoding="utf-8") as fh:
        fh.write(lemma.lower() + "\n")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--pos", default="noun",
                    help="comma list of parts of speech to try (default: noun)")
    ap.add_argument("--redo", default="",
                    help="comma list of lemmas to re-fetch even if they have an image / a miss")
    ap.add_argument("--top", type=int, default=0,
                    help="only the N most frequent candidates (by frequency_rank)")
    ap.add_argument("--only-list", default="",
                    help="path to a lemma list (one per line, '#' comments) — "
                         "restrict fetching to exactly those words. Use the output "
                         "of scripts/pick_image_words.py for the curated set.")
    ap.add_argument("--requests", type=int, default=0,
                    help="stop after N Openverse searches this run (resumable; "
                         "use ~180 to stay under the anonymous 200/day limit)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N successful downloads")
    ap.add_argument("--min-len", type=int, default=3,
                    help="skip lemmas shorter than this (default 3 — kills 'ja' etc.)")
    ap.add_argument("--require-article", action="store_true", default=True,
                    help="nouns only: require de/het (filters mislabelled verb forms)")
    ap.add_argument("--no-require-article", dest="require_article", action="store_false")
    ap.add_argument("--strict-title", action="store_true",
                    help="only accept an image whose title shares a word with the "
                         "query — much higher precision, ~half as many images")
    ap.add_argument("--licenses", default=",".join(DEFAULT_LICENSES),
                    help="Openverse licence codes to accept, best first ('all' = any)")
    ap.add_argument("--dry-run", action="store_true",
                    help="search + choose, but download nothing and don't touch the JSON")
    args = ap.parse_args()

    if not os.path.isfile(args.json):
        sys.exit("JSON not found: " + args.json)
    with open(args.json, encoding="utf-8") as fh:
        data = json.load(fh)

    os.makedirs(IMG_DIR, exist_ok=True)
    pos_ok = {p.strip().lower() for p in args.pos.split(",") if p.strip()}
    redo = {s.strip().lower() for s in args.redo.split(",") if s.strip()}
    licenses = None if args.licenses.strip().lower() == "all" \
        else [c.strip().lower() for c in args.licenses.split(",") if c.strip()]
    stop = load_stoplist()
    misses = _read_lemma_file(MISSES) - redo
    only = None
    if args.only_list:
        if not os.path.isfile(args.only_list):
            sys.exit("--only-list file not found: " + args.only_list)
        only = _read_lemma_file(args.only_list)
        log("Restricting to %d lemma(s) from %s" % (len(only), args.only_list))
    token = get_token()

    words = data.get("words", [])
    have_now = sum(1 for w in words if (w.get("image") or {}).get("path"))

    # rank candidates by frequency so --top keeps the useful head of the list
    ranked = sorted(words, key=lambda w: (w.get("frequency_rank") or 10**9))
    todo = []
    seen_candidates = 0
    pruned = 0
    for w in ranked:
        lemma = (w.get("lemma") or "").lower()
        if lemma in stop:
            if (w.get("image") or {}).get("path"):
                fp = os.path.join(ROOT, w["image"]["path"])
                if not args.dry_run:
                    w.pop("image", None)
                    if os.path.isfile(fp):
                        os.remove(fp)
                log("  %-16s in stoplist -> image removed" % lemma)
                pruned += 1
            continue
        if only is not None and lemma not in only:
            continue
        if w.get("part_of_speech", "").lower() not in pos_ok:
            continue
        if len(w.get("lemma", "")) < args.min_len:
            continue
        if (args.require_article and w.get("part_of_speech") == "noun"
                and w.get("article") not in ("de", "het")):
            continue
        # this word counts as an in-scope candidate for --top
        if args.top and seen_candidates >= args.top:
            break
        seen_candidates += 1
        if (w.get("image") or {}).get("path") and lemma not in redo:
            continue
        if lemma in misses:
            continue
        todo.append(w)

    log("In scope: %d candidate noun(s)%s | already have %d, misses %d, to try %d"
        % (seen_candidates, (" (capped at --top %d)" % args.top) if args.top else "",
           have_now, len(misses), len(todo)))
    if not todo:
        log("Nothing to do — coverage complete for this scope.")
        return

    got = skipped = reqs = 0
    skipped_lemmas = []

    def flush():
        if args.dry_run:
            return
        tmp = args.json + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            # match build_corpus.py's formatting so the diff stays minimal
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, args.json)

    for i, w in enumerate(todo):
        if args.limit and got >= args.limit:
            log("--limit (%d downloads) reached." % args.limit)
            break
        if args.requests and reqs >= args.requests:
            log("--requests (%d searches) reached — resume with the same command."
                % args.requests)
            break
        lemma = w["lemma"]
        q = query_for(w)
        reqs += 1
        try:
            results = search(q, token, licenses)
        except Exception as e:  # noqa: BLE001
            log("  %-16s search error: %s" % (lemma, e))
            skipped += 1
            skipped_lemmas.append(lemma)
            time.sleep(PER_REQUEST_SLEEP)
            continue

        best = pick(results, licenses, q, strict_title=args.strict_title)
        if not best:
            log("  %-16s (q=%r) -> no acceptable image, recording miss" % (lemma, q))
            skipped += 1
            skipped_lemmas.append(lemma)
            if not args.dry_run:
                record_miss(lemma)
            time.sleep(PER_REQUEST_SLEEP)
            continue

        cred = best.get("attribution") or (
            '"%s" by %s (%s)' % (best.get("title") or lemma,
                                 best.get("creator") or "unknown",
                                 licence_label(best)))
        cred = re.sub(r"\s+", " ", cred).strip().rstrip(".") + "."

        if args.dry_run:
            log("  %-16s (q=%r) -> %s  [%s]  %sx%s" % (
                lemma, q, best.get("creator") or "?", licence_label(best),
                best.get("width"), best.get("height")))
            got += 1
            time.sleep(PER_REQUEST_SLEEP)
            continue

        dest, size = download_image(best, lemma, token)
        if not dest:
            log("  %-16s download failed, skipping" % lemma)
            skipped += 1
            skipped_lemmas.append(lemma)
            time.sleep(PER_REQUEST_SLEEP)
            continue

        w["image"] = {
            "path": "images/%s.jpg" % lemma,
            "source": best.get("source") or "openverse",
            "attribution": cred,
            "source_url": best.get("foreign_landing_url") or "",
            "license": licence_label(best),
        }
        got += 1
        log("  %-16s (q=%r) -> images/%s.jpg  %sx%s  [%s]" % (
            lemma, q, lemma, size[0], size[1], licence_label(best)))
        if got % 20 == 0:
            flush()   # checkpoint so a crash mid-run keeps progress
        time.sleep(PER_REQUEST_SLEEP)

    if (got or pruned) and not args.dry_run:
        flush()
        log("\nUpdated %s" % args.json)

    total_have = have_now + got - pruned
    log("\nThis run: %d fetched, %d misses, %d pruned, %d searches."
        % (got, skipped, pruned, reqs))
    log("Coverage: %d word(s) now have an image; %d recorded as misses."
        % (total_have, len(_read_lemma_file(MISSES))))
    if todo and (got + skipped) >= len(todo):
        log("Scope complete. Next: rebuild the DB + deploy (see README 'Media hosting').")
    elif args.requests and reqs >= args.requests:
        log("Daily cap hit — run the same command again tomorrow to continue.")


if __name__ == "__main__":
    main()
