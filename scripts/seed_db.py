#!/usr/bin/env python3
"""
seed_db.py — build the flashcard SQLite database from a local JSON file.

No network. No external API. Content is authored in data/seed_words.json and
this script just validates it and writes it into the database, plus creates the
'pending' audio_assets rows that scripts/generate_audio.py will later fill.

Usage:
    python3 scripts/seed_db.py                    # create/update db/flashcards.db
    python3 scripts/seed_db.py --reset            # delete the db first, rebuild
    python3 scripts/seed_db.py --json data/seed_words.json --db db/flashcards.db
    python3 scripts/seed_db.py --audio-conjugations   # also queue audio for every conj form
"""

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULT_JSON = os.path.join(ROOT, "data", "seed_words.json")
DEFAULT_DB = os.path.join(ROOT, "db", "flashcards.db")
SCHEMA_SQL = os.path.join(ROOT, "db", "schema.sql")

TENSE_ORDER = [
    "presens", "imperfectum", "perfectum", "plusquamperfectum",
    "futurum", "futurum_exactum", "conditionalis",
]
PERSON_ORDER = ["ik", "jij", "hij", "wij", "jullie", "zij_mv"]

# Pronoun prefixes to strip so we can also store the bare verb form.
_PRONOUN_PREFIXES = ("ik ", "jij ", "hij ", "wij ", "jullie ", "zij ")


def log(msg):
    print(msg, flush=True)


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def verb_form_only(form):
    for p in _PRONOUN_PREFIXES:
        if form.startswith(p):
            return form[len(p):]
    return form


def validate(data):
    """Return (errors, warnings). Errors abort the build; warnings are printed."""
    errors, warnings = [], []
    words = data.get("words", [])
    if not words:
        errors.append("no words in JSON")

    verbs = [w for w in words if w.get("part_of_speech") == "verb"]
    if len(verbs) < 2:
        errors.append("need at least 2 verbs, found %d" % len(verbs))

    seen = set()
    n_no_article = n_no_example = n_no_cloze = 0
    for w in words:
        key = (w.get("lemma"), w.get("part_of_speech"))
        if key in seen:
            errors.append("duplicate word: %s" % (key,))
        seen.add(key)

        if not w.get("lemma") or not w.get("part_of_speech"):
            errors.append("word missing lemma/part_of_speech: %r" % w)
        if not w.get("translation_en"):
            errors.append("%s: missing translation_en" % w.get("lemma"))

        if w.get("part_of_speech") == "noun" and w.get("article") not in ("de", "het"):
            n_no_article += 1
        if not w.get("examples"):
            n_no_example += 1
        for ex in w.get("examples", []):
            if ex.get("blanked") and "___" not in ex["blanked"]:
                errors.append("%s: blanked sentence has no '___'" % w.get("lemma"))
            if not ex.get("blanked"):
                n_no_cloze += 1

        if w.get("part_of_speech") == "verb":
            conj = w.get("conjugations", {})
            for tense in TENSE_ORDER:
                if tense not in conj:
                    errors.append("%s: missing tense '%s'" % (w.get("lemma"), tense))
                    continue
                for person in PERSON_ORDER:
                    if not conj[tense].get(person):
                        errors.append(
                            "%s: missing %s/%s" % (w.get("lemma"), tense, person))

    if n_no_article:
        warnings.append("%d noun(s) without de/het (plurale tantum / loanwords)"
                        % n_no_article)
    if n_no_example:
        warnings.append("%d word(s) with no example sentence" % n_no_example)
    if n_no_cloze:
        warnings.append("%d example(s) with no fill-in-the-blank form" % n_no_cloze)
    return errors, warnings


def build(conn, data, queue_conjugation_audio):
    cur = conn.cursor()

    # --- word sets -------------------------------------------------------
    set_ids = {}
    for s in data.get("word_sets", []):
        cur.execute(
            """INSERT INTO word_sets (name, cefr_level, theme, description, sort_order)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   cefr_level=excluded.cefr_level,
                   theme=excluded.theme,
                   description=excluded.description,
                   sort_order=excluded.sort_order""",
            (s["name"], s.get("cefr_level"), s.get("theme"),
             s.get("description"), s.get("sort_order", 0)),
        )
        row = cur.execute("SELECT id FROM word_sets WHERE name = ?", (s["name"],)).fetchone()
        set_ids[s["name"]] = row[0]

    n_words = n_sent = n_conj = n_audio = 0

    for w in data["words"]:
        # --- word -------------------------------------------------------
        cur.execute(
            """INSERT INTO words
                 (lemma, part_of_speech, translation_en, definition_nl, definition_en,
                  article, gender, plural,
                  infinitive, past_participle, auxiliary, is_separable, is_irregular,
                  cefr_level, frequency_rank, notes)
               VALUES (?,?,?,?,?, ?,?,?, ?,?,?,?,?, ?,?,?)
               ON CONFLICT(lemma, part_of_speech) DO UPDATE SET
                   translation_en=excluded.translation_en,
                   definition_nl=excluded.definition_nl,
                   definition_en=excluded.definition_en,
                   article=excluded.article,
                   gender=excluded.gender,
                   plural=excluded.plural,
                   infinitive=excluded.infinitive,
                   past_participle=excluded.past_participle,
                   auxiliary=excluded.auxiliary,
                   is_separable=excluded.is_separable,
                   is_irregular=excluded.is_irregular,
                   cefr_level=excluded.cefr_level,
                   frequency_rank=excluded.frequency_rank,
                   notes=excluded.notes""",
            (
                w["lemma"], w["part_of_speech"], w["translation_en"],
                w.get("definition_nl"), w.get("definition_en"),
                w.get("article"), w.get("gender"), w.get("plural"),
                w.get("infinitive"), w.get("past_participle"), w.get("auxiliary"),
                1 if w.get("is_separable") else 0,
                1 if w.get("is_irregular") else 0,
                w.get("cefr_level"), w.get("frequency_rank"), w.get("notes"),
            ),
        )
        word_id = cur.execute(
            "SELECT id FROM words WHERE lemma = ? AND part_of_speech = ?",
            (w["lemma"], w["part_of_speech"]),
        ).fetchone()[0]
        n_words += 1

        # --- set membership ------------------------------------------
        for set_name in w.get("sets", []):
            if set_name not in set_ids:
                die("word '%s' references unknown set '%s'" % (w["lemma"], set_name))
            cur.execute(
                "INSERT OR IGNORE INTO word_set_members (word_id, set_id) VALUES (?, ?)",
                (word_id, set_ids[set_name]),
            )

        # --- example sentences -------------------------------------
        # Rebuild sentences for this word so re-runs stay clean.
        cur.execute("DELETE FROM example_sentences WHERE word_id = ?", (word_id,))
        for i, ex in enumerate(w.get("examples", [])):
            cur.execute(
                """INSERT INTO example_sentences
                     (word_id, sentence_nl, sentence_en, sentence_blanked, sort_order)
                   VALUES (?, ?, ?, ?, ?)""",
                (word_id, ex["nl"], ex["en"], ex.get("blanked"), i),
            )
            sentence_id = cur.lastrowid
            n_sent += 1
            n_audio += queue_audio(
                cur, "sentence", "sentence:%d" % sentence_id,
                text=ex["nl"], sentence_id=sentence_id, word_id=word_id,
            )

        # --- word audio -------------------------------------------
        n_audio += queue_audio(
            cur, "word", "word:%d" % word_id, text=w["lemma"], word_id=word_id
        )

        # --- verb conjugations -----------------------------------
        if w.get("part_of_speech") == "verb":
            cur.execute("DELETE FROM verb_conjugations WHERE word_id = ?", (word_id,))
            conj = w.get("conjugations", {})
            for t_sort, tense in enumerate(TENSE_ORDER):
                for p_sort, person in enumerate(PERSON_ORDER):
                    form = conj[tense][person]
                    cur.execute(
                        """INSERT INTO verb_conjugations
                             (word_id, tense, person, form, verb_form_only,
                              tense_sort, person_sort)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (word_id, tense, person, form, verb_form_only(form),
                         t_sort, p_sort),
                    )
                    conj_id = cur.lastrowid
                    n_conj += 1
                    if queue_conjugation_audio:
                        n_audio += queue_audio(
                            cur, "conjugation", "conj:%d" % conj_id,
                            text=form, conjugation_id=conj_id, word_id=word_id,
                        )

    conn.commit()
    return {
        "words": n_words, "sentences": n_sent,
        "conjugations": n_conj, "audio_rows": n_audio,
    }


def queue_audio(cur, scope, dedup_key, text, word_id=None,
                sentence_id=None, conjugation_id=None):
    """Insert a 'pending' audio_assets row if it doesn't already exist. Returns 0/1."""
    cur.execute(
        """INSERT INTO audio_assets
             (scope, dedup_key, word_id, sentence_id, conjugation_id, text, char_count)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(dedup_key) DO UPDATE SET
               text=excluded.text,
               char_count=excluded.char_count""",
        (scope, dedup_key, word_id, sentence_id, conjugation_id, text, len(text)),
    )
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--reset", action="store_true",
                    help="delete the database file before building")
    ap.add_argument("--audio-conjugations", dest="audio_conj", action="store_true",
                    help="also queue an audio row for every single conjugated form")
    args = ap.parse_args()

    if not os.path.exists(args.json):
        die("JSON not found: %s" % args.json)
    if not os.path.exists(SCHEMA_SQL):
        die("schema not found: %s" % SCHEMA_SQL)

    with open(args.json, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    errors, warnings = validate(data)
    for wmsg in warnings:
        log("  warning: " + wmsg)
    if errors:
        for p in errors[:50]:
            print("  - " + p, file=sys.stderr)
        die("%d validation error(s); nothing written." % len(errors))
    log("Validation OK: %d words (%d verbs)." % (
        len(data["words"]),
        sum(1 for w in data["words"] if w["part_of_speech"] == "verb"),
    ))

    if args.reset and os.path.exists(args.db):
        os.remove(args.db)
        for ext in ("-wal", "-shm"):
            if os.path.exists(args.db + ext):
                os.remove(args.db + ext)
        log("Removed existing %s" % args.db)

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA_SQL, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())

    stats = build(conn, data, args.audio_conj)

    # Report
    total_chars = conn.execute(
        "SELECT COALESCE(SUM(char_count),0) FROM audio_assets WHERE status='pending'"
    ).fetchone()[0]
    by_scope = conn.execute(
        "SELECT scope, COUNT(*), COALESCE(SUM(char_count),0) "
        "FROM audio_assets GROUP BY scope ORDER BY scope"
    ).fetchall()
    conn.close()

    log("")
    log("Inserted: %(words)d words, %(sentences)d sentences, "
        "%(conjugations)d conjugation forms, %(audio_rows)d audio rows." % stats)
    log("Pending audio characters by scope:")
    for scope, cnt, chars in by_scope:
        log("  %-12s %4d rows   %6d chars" % (scope, cnt, chars))
    log("  %-12s %19d chars  <- send this many to a TTS engine" % ("TOTAL", total_chars))
    log("")
    log("Database ready: %s" % args.db)
    log("Next: python3 scripts/generate_audio.py --report   (then --provider ...)")


if __name__ == "__main__":
    main()
