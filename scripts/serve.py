#!/usr/bin/env python3
"""
serve.py — local read-only viewer for the flashcard database.

No dependencies (Python stdlib only). Reads db/flashcards.db, serves a small
JSON API + the cached audio files + the viewer page. This is a CONTENT CHECKER
for Phase 1, not the Phase 2 app (no spaced repetition, no rating, no state).

    python3 scripts/serve.py
    open http://localhost:8000
"""

import argparse
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "db", "flashcards.db")
VIEWER = os.path.join(ROOT, "public", "index.html")
AUDIO_DIR = os.path.join(ROOT, "audio")
IMG_DIR = os.path.join(ROOT, "images")
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
IMG_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".gif": "image/gif"}

TENSE_ORDER = ["presens", "imperfectum", "perfectum", "plusquamperfectum",
               "futurum", "futurum_exactum", "conditionalis"]
PERSON_ORDER = ["ik", "jij", "hij", "wij", "jullie", "zij_mv"]


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def api_sets():
    conn = db()
    rows = conn.execute("""
        SELECT ws.id, ws.name, ws.cefr_level, ws.description,
               COUNT(m.word_id) AS word_count
        FROM word_sets ws
        LEFT JOIN word_set_members m ON m.set_id = ws.id
        GROUP BY ws.id ORDER BY ws.sort_order, ws.name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def api_cards():
    """Lean projection of every card — enough to build the SRS queue and render
    a card FRONT. Full detail (definition, conjugations) comes from /api/word/id."""
    conn = db()
    rows = conn.execute("""
        SELECT w.id, w.lemma, w.part_of_speech AS pos, w.article, w.gender,
               w.cefr_level AS cefr, w.frequency_rank AS rank, w.translation_en,
               s.sentence_nl, s.sentence_blanked,
               aw.file_path AS word_audio, asx.file_path AS sentence_audio,
               (w.part_of_speech = 'verb') AS is_verb
        FROM words w
        LEFT JOIN example_sentences s ON s.word_id = w.id AND s.sort_order = 0
        LEFT JOIN audio_assets aw  ON aw.scope='word' AND aw.word_id=w.id AND aw.status='done'
        LEFT JOIN audio_assets asx ON asx.scope='sentence' AND asx.sentence_id=s.id AND asx.status='done'
        ORDER BY w.frequency_rank
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def api_words(set_id=None, pos=None, q=None, limit=500, offset=0):
    conn = db()
    where, params = ["1=1"], []
    if set_id:
        where.append("w.id IN (SELECT word_id FROM word_set_members WHERE set_id = ?)")
        params.append(set_id)
    if pos:
        where.append("w.part_of_speech = ?")
        params.append(pos)
    if q:
        where.append("(w.lemma LIKE ? OR w.translation_en LIKE ?)")
        params += ["%" + q + "%", "%" + q + "%"]
    sql = """
        SELECT w.id, w.lemma, w.part_of_speech, w.translation_en, w.definition_nl,
               w.definition_en, w.article, w.gender, w.plural, w.infinitive,
               w.past_participle, w.auxiliary, w.is_separable, w.is_irregular,
               w.cefr_level, w.frequency_rank,
               s.sentence_nl, s.sentence_en, s.sentence_blanked,
               aw.file_path AS word_audio, asx.file_path AS sentence_audio
        FROM words w
        LEFT JOIN example_sentences s ON s.word_id = w.id AND s.sort_order = 0
        LEFT JOIN audio_assets aw  ON aw.scope='word' AND aw.word_id=w.id AND aw.status='done'
        LEFT JOIN audio_assets asx ON asx.scope='sentence' AND asx.sentence_id=s.id AND asx.status='done'
        WHERE %s
        ORDER BY w.frequency_rank
        LIMIT ? OFFSET ?
    """ % " AND ".join(where)
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM words w WHERE " + " AND ".join(where), params
    ).fetchone()[0]
    conn.close()
    return {"total": total, "words": [dict(r) for r in rows]}


def api_word(word_id):
    conn = db()
    w = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
    if not w:
        conn.close()
        return None
    out = dict(w)
    out["sentences"] = [dict(r) for r in conn.execute(
        "SELECT * FROM example_sentences WHERE word_id=? ORDER BY sort_order", (word_id,))]
    if w["part_of_speech"] == "verb":
        conj, cids = {}, {}
        for r in conn.execute(
                "SELECT id, tense, person, form FROM verb_conjugations WHERE word_id=?",
                (word_id,)):
            conj.setdefault(r["tense"], {})[r["person"]] = r["form"]
            cids.setdefault(r["tense"], {})[r["person"]] = r["id"]
        out["conjugations"] = {t: conj.get(t, {}) for t in TENSE_ORDER}
        out["conj_ids"] = {t: cids.get(t, {}) for t in TENSE_ORDER}
        out["persons"] = PERSON_ORDER
    out["audio"] = {}
    for r in conn.execute(
            "SELECT scope, sentence_id, conjugation_id, file_path FROM audio_assets "
            "WHERE word_id=? AND status='done'", (word_id,)):
        if r["scope"] == "sentence":
            key = "sentence:%s" % r["sentence_id"]
        elif r["scope"] == "conjugation":
            key = "conj:%s" % r["conjugation_id"]
        else:
            key = r["scope"]
        out["audio"][key] = r["file_path"]
    conn.close()
    return out


def api_details():
    """Every word's card-back detail (definitions, sentences, conjugations, audio)
    in one payload — the app precaches this so the whole review flow works
    offline, not just card fronts. ~5 MB uncompressed for 8k words."""
    conn = db()
    out = {}
    for w in conn.execute("SELECT * FROM words"):
        out[w["id"]] = {
            "translation_en": w["translation_en"],
            "definition_nl": w["definition_nl"],
            "definition_en": w["definition_en"],
            "article": w["article"], "gender": w["gender"], "plural": w["plural"],
            "auxiliary": w["auxiliary"], "past_participle": w["past_participle"],
            "is_separable": w["is_separable"], "is_irregular": w["is_irregular"],
            "part_of_speech": w["part_of_speech"],
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
    for r in conn.execute(
            "SELECT word_id, scope, sentence_id, conjugation_id, file_path "
            "FROM audio_assets WHERE status='done'"):
        d = out.get(r["word_id"])
        if d is None:
            continue
        if r["scope"] == "sentence":
            key = "sentence:%s" % r["sentence_id"]
        elif r["scope"] == "conjugation":
            key = "conj:%s" % r["conjugation_id"]
        else:
            key = r["scope"]
        d["audio"][key] = r["file_path"]
    conn.close()
    return out


def api_stats():
    conn = db()
    s = {
        "words": conn.execute("SELECT COUNT(*) FROM words").fetchone()[0],
        "by_pos": {r[0]: r[1] for r in conn.execute(
            "SELECT part_of_speech, COUNT(*) FROM words GROUP BY part_of_speech")},
        "sentences": conn.execute("SELECT COUNT(*) FROM example_sentences").fetchone()[0],
        "conjugations": conn.execute("SELECT COUNT(*) FROM verb_conjugations").fetchone()[0],
        "audio_done": conn.execute(
            "SELECT COUNT(*) FROM audio_assets WHERE status='done'").fetchone()[0],
        "audio_total": conn.execute("SELECT COUNT(*) FROM audio_assets").fetchone()[0],
    }
    conn.close()
    return s


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        qs = parse_qs(u.query)

        def one(k, d=None):
            return qs.get(k, [d])[0]

        STATIC = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
                  ".css": "text/css", ".json": "application/json",
                  ".webmanifest": "application/manifest+json",
                  ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
        try:
            if p == "/":
                p = "/index.html"
            ext = os.path.splitext(p)[1]
            if ext in STATIC and "/" not in p.strip("/"):
                fp = os.path.join(os.path.dirname(VIEWER), p.lstrip("/"))
                if os.path.isfile(fp):
                    extra = None
                    if p == "/sw.js":
                        # always revalidate the worker so a new version is picked up
                        extra = {"Service-Worker-Allowed": "/",
                                 "Cache-Control": "no-cache"}
                    with open(fp, "rb") as fh:
                        return self._send(200, fh.read(), STATIC[ext], extra)
                return self._send(404, {"error": "not found"})
            if p == "/api/stats":
                return self._send(200, api_stats())
            if p == "/api/sets":
                return self._send(200, api_sets())
            if p == "/api/cards":
                return self._send(200, api_cards())
            if p == "/api/details":
                return self._send(200, api_details())
            if p == "/api/images":
                # lemmas that have an image file — frontend only renders <img> for these
                have = []
                if os.path.isdir(IMG_DIR):
                    for fn in os.listdir(IMG_DIR):
                        stem, ext = os.path.splitext(fn.lower())
                        if ext in IMG_EXTS:
                            have.append(stem)
                return self._send(200, have)
            if p == "/api/words":
                return self._send(200, api_words(
                    set_id=one("set"), pos=one("pos"), q=one("q"),
                    limit=int(one("limit", 500)), offset=int(one("offset", 0))))
            if p.startswith("/api/word/"):
                w = api_word(int(p.rsplit("/", 1)[1]))
                return self._send(200, w) if w else self._send(404, {"error": "not found"})
            if p.startswith("/audio/"):
                rel = p.lstrip("/")
                fp = os.path.normpath(os.path.join(ROOT, rel))
                if not fp.startswith(AUDIO_DIR) or not os.path.isfile(fp):
                    return self._send(404, {"error": "no audio"})
                with open(fp, "rb") as fh:
                    return self._send(200, fh.read(), "audio/mpeg")
            if p.startswith("/img/"):
                # /img/<lemma> -> images/<lemma>.<ext>  (optional, drop files in there)
                stem = os.path.basename(p[len("/img/"):]).lower()
                for ext in IMG_EXTS:
                    fp = os.path.join(IMG_DIR, stem + ext)
                    if os.path.isfile(fp):
                        with open(fp, "rb") as fh:
                            return self._send(200, fh.read(), IMG_MIME[ext])
                return self._send(404, {"error": "no image"})
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if not os.path.exists(DB):
        raise SystemExit("db/flashcards.db not found — run seed_db.py first")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("Dutch Flashcards:  http://localhost:%d" % args.port)
    print("(local API + static app — Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
