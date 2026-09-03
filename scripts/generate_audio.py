#!/usr/bin/env python3
"""
generate_audio.py — one-time pronunciation audio generation for the flashcard DB.

Reads 'pending' rows from audio_assets, synthesizes each with the chosen TTS
provider, writes an audio file under audio/<scope>/, and marks the row 'done'.
The finished app then plays these cached files only — no runtime TTS calls.

Providers
---------
  report  (default)  no synthesis; print character totals + free-tier / scale analysis
  espeak             eSpeak NG (local, free, robotic) — good offline fallback
  piper              Piper (local, free, open-source neural) — recommended for full scale
  edge               Microsoft Edge TTS via `edge-tts` (free, no API key, neural)
  google             Google Cloud TTS (free tier: see --report), needs credentials

Examples
--------
  python3 scripts/generate_audio.py --report
  python3 scripts/generate_audio.py --provider edge   --voice nl-NL-MaartenNeural
  python3 scripts/generate_audio.py --provider piper  --piper-model ./voices/nl_NL-mls-medium.onnx
  python3 scripts/generate_audio.py --provider google --voice nl-NL-Standard-D
  python3 scripts/generate_audio.py --provider espeak --limit 5      # smoke test
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DB = os.path.join(ROOT, "db", "flashcards.db")
AUDIO_DIR = os.path.join(ROOT, "audio")

# ---- Google Cloud TTS free tier (verify at cloud.google.com/text-to-speech/pricing) ----
# Figures below are the long-standing published monthly free allowances (reset monthly).
GOOGLE_FREE_TIER = {
    "Standard": 4_000_000,
    "WaveNet":  1_000_000,
    "Neural2":  1_000_000,
    "Studio":     100_000,
}
GOOGLE_PAID_PER_M = {  # USD per 1,000,000 chars after the free tier
    "Standard": 4.0,
    "WaveNet": 4.0,
    "Neural2": 16.0,
    "Studio": 30.0,
}

# Rough per-word cost model for scale projection (words + one example sentence).
SCALE_CHARS_PER_WORD = 63          # ~8 (lemma) + ~55 (sentence)
SCALE_CONJ_CHARS_PER_VERB = 7 * 6 * 18   # 7 tenses x 6 persons x ~18 chars


def connect(db_path):
    if not os.path.exists(db_path):
        sys.exit("ERROR: database not found: %s  (run seed_db.py first)" % db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


# --------------------------------------------------------------------------
# Reporting / analysis
# --------------------------------------------------------------------------
def cmd_report(conn):
    rows = conn.execute(
        "SELECT scope, status, COUNT(*) c, COALESCE(SUM(char_count),0) chars "
        "FROM audio_assets GROUP BY scope, status ORDER BY scope, status"
    ).fetchall()
    total = conn.execute(
        "SELECT COALESCE(SUM(char_count),0) FROM audio_assets"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COALESCE(SUM(char_count),0) FROM audio_assets WHERE status='pending'"
    ).fetchone()[0]
    n_words = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    n_verbs = conn.execute(
        "SELECT COUNT(*) FROM words WHERE part_of_speech='verb'"
    ).fetchone()[0]

    print("=" * 68)
    print("AUDIO CHARACTER REPORT")
    print("=" * 68)
    print("%-12s %-9s %6s %12s" % ("scope", "status", "rows", "chars"))
    for r in rows:
        print("%-12s %-9s %6d %12d" % (r["scope"], r["status"], r["c"], r["chars"]))
    print("-" * 68)
    print("%-22s %6s %12d" % ("TOTAL (all rows)", "", total))
    print("%-22s %6s %12d" % ("PENDING (to synthesize)", "", pending))
    print()

    print("THIS TEST BATCH vs GOOGLE CLOUD TTS FREE TIER (per month, resets monthly)")
    print("-" * 68)
    for tier, limit in GOOGLE_FREE_TIER.items():
        pct = 100.0 * pending / limit if limit else 0.0
        verdict = "OK, well within free tier" if pct < 100 else "EXCEEDS free tier"
        print("  %-9s free=%9d   this batch=%6d  (%5.2f%%)  %s"
              % (tier, limit, pending, pct, verdict))
    print()
    print("  => This %d-word batch is trivially free on every Google tier," % n_words)
    print("     and on edge-tts / Piper (both unmetered).")
    print()

    _scale_projection(n_verbs)


def _scale_projection(n_verbs_now):
    print("PROJECTION TO A FULL B2 WORD SET (~5,000-10,000 words)")
    print("-" * 68)
    scenarios = [
        ("words + 1 sentence each, NO conjugation audio", 5_000, 0),
        ("words + 1 sentence each, NO conjugation audio", 10_000, 0),
        ("+ full conj. audio for ~600 core verbs",        10_000, 600),
        ("+ full conj. audio for ~1500 verbs",            10_000, 1_500),
    ]
    print("%-46s %9s %14s" % ("scenario", "chars", "vs free tier"))
    for label, n_words, n_verbs in scenarios:
        chars = n_words * SCALE_CHARS_PER_WORD + n_verbs * SCALE_CONJ_CHARS_PER_VERB
        flags = []
        for tier in ("Standard", "WaveNet"):
            lim = GOOGLE_FREE_TIER[tier]
            if chars > lim:
                over = chars - lim
                cost = over / 1_000_000 * GOOGLE_PAID_PER_M[tier]
                flags.append("%s: OVER by %d (~$%.2f one-time)" % (tier, over, cost))
            else:
                flags.append("%s: fits" % tier)
        print("%-46s %9d" % (label, chars))
        for f in flags:
            print("%-46s %9s   %s" % ("", "", f))
    print()
    print("READ-OUT")
    print("-" * 68)
    print(textwrap_fill(
        "Audio is a ONE-TIME job, so the monthly free tier is the real ceiling. "
        "Words + one sentence each stays under ~0.7M chars even at 10k words: free "
        "on Google Standard (4M/mo) AND WaveNet (1M/mo). Adding full 7-tense x "
        "6-person conjugation audio for many verbs pushes past ~1M: still free on "
        "Google Standard, but it breaks the WaveNet/Neural2 monthly free tier "
        "(Neural2 overage is $16/1M). Studio's 100k/mo free tier is blown "
        "immediately at any real scale."))
    print()
    print(textwrap_fill(
        "RECOMMENDATION: generate the whole set with Piper (local, open-source, "
        "neural, zero cost, no quota, reproducible) or edge-tts (free, no key, "
        "neural nl-NL voices). Keep the Google path for a quality pass on just the "
        "~card-front words if desired. If you do use Google at scale, pick "
        "Standard voices and/or split the run across two calendar months to stay "
        "inside the free tier. Amazon Polly (5M chars/mo free for 12 months) is "
        "another comfortably-free option."))
    print()
    print("Alternatives if you outgrow every free tier:")
    print("  - Piper      https://github.com/rhasspy/piper        (offline, MIT-ish, nl_NL/nl_BE voices)")
    print("  - edge-tts   pip install edge-tts                    (neural, free, unofficial MS API)")
    print("  - Coqui TTS  https://github.com/coqui-ai/TTS         (heavier, GPU helps)")
    print("  - eSpeak NG  apt/brew install espeak-ng              (tiny, robotic, instant fallback)")
    print("  - Amazon Polly free tier: 5M chars/month for first 12 months")


def textwrap_fill(s, width=68):
    import textwrap
    return textwrap.fill(s, width=width)


# --------------------------------------------------------------------------
# Synthesis backends. Each returns the bytes/produces a file at out_path.
# --------------------------------------------------------------------------
def synth_espeak(text, out_path, voice):
    if not shutil.which("espeak-ng") and not shutil.which("espeak"):
        raise RuntimeError("espeak-ng not installed (brew install espeak-ng)")
    exe = "espeak-ng" if shutil.which("espeak-ng") else "espeak"
    wav = out_path.rsplit(".", 1)[0] + ".wav"
    subprocess.run([exe, "-v", voice or "nl", "-w", wav, text], check=True)
    return wav


def synth_piper(text, out_path, model):
    if not shutil.which("piper"):
        raise RuntimeError("piper not on PATH (see github.com/rhasspy/piper)")
    if not model or not os.path.exists(model):
        raise RuntimeError("--piper-model must point to a downloaded .onnx voice")
    wav = out_path.rsplit(".", 1)[0] + ".wav"
    proc = subprocess.run(
        ["piper", "--model", model, "--output_file", wav],
        input=text.encode("utf-8"), check=True,
    )
    return wav


def synth_edge(text, out_path, voice):
    try:
        import asyncio
        import edge_tts
    except ImportError:
        raise RuntimeError("pip install edge-tts")

    async def _run():
        communicate = edge_tts.Communicate(text, voice or "nl-NL-MaartenNeural")
        await communicate.save(out_path)

    asyncio.get_event_loop().run_until_complete(_run())
    return out_path


def synth_google(text, out_path, voice):
    try:
        from google.cloud import texttospeech
    except ImportError:
        raise RuntimeError("pip install google-cloud-texttospeech and set "
                           "GOOGLE_APPLICATION_CREDENTIALS")
    client = texttospeech.TextToSpeechClient()
    resp = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code="nl-NL", name=voice or "nl-NL-Standard-D"),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3),
    )
    with open(out_path, "wb") as fh:
        fh.write(resp.audio_content)
    return out_path


BACKENDS = {
    "espeak": synth_espeak,
    "piper": synth_piper,
    "edge": synth_edge,
    "google": synth_google,
}
DEFAULT_VOICE = {
    "espeak": "nl",
    "piper": None,
    "edge": "nl-NL-MaartenNeural",
    "google": "nl-NL-Standard-D",
}


def cmd_generate(conn, provider, voice, piper_model, limit, redo_errors, set_name):
    backend = BACKENDS[provider]
    voice = voice or DEFAULT_VOICE[provider]

    statuses = "('pending','error')" if redo_errors else "('pending')"
    q = "SELECT a.* FROM audio_assets a WHERE a.status IN %s" % statuses
    params = []
    if set_name:
        q += (" AND a.word_id IN (SELECT m.word_id FROM word_set_members m "
              "JOIN word_sets s ON s.id = m.set_id WHERE s.name = ?)")
        params.append(set_name)
    q += " ORDER BY a.scope, a.id"
    if limit:
        q += " LIMIT %d" % limit
    rows = conn.execute(q, params).fetchall()
    if not rows:
        print("Nothing pending. (run --report to see totals)")
        return

    print("Provider=%s  voice=%s  items=%d" % (provider, voice, len(rows)))
    done = errors = chars = 0
    for r in rows:
        subdir = os.path.join(AUDIO_DIR, r["scope"])
        os.makedirs(subdir, exist_ok=True)
        ext = "mp3" if provider in ("edge", "google") else "wav"
        out_path = os.path.join(subdir, "%05d.%s" % (r["id"], ext))
        rel_path = os.path.relpath(out_path, ROOT)
        now = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        try:
            if provider == "piper":
                produced = backend(r["text"], out_path, piper_model)
            else:
                produced = backend(r["text"], out_path, voice)
            rel_path = os.path.relpath(produced, ROOT)
            conn.execute(
                "UPDATE audio_assets SET status='done', file_path=?, audio_format=?, "
                "provider=?, voice_name=?, error_message=NULL, updated_at=? WHERE id=?",
                (rel_path, produced.rsplit('.', 1)[1], provider, voice, now, r["id"]),
            )
            done += 1
            chars += r["char_count"]
        except Exception as exc:  # noqa: BLE001 - want to keep going
            conn.execute(
                "UPDATE audio_assets SET status='error', error_message=?, updated_at=? "
                "WHERE id=?", (str(exc), now, r["id"]),
            )
            errors += 1
            print("  ! id=%d (%s): %s" % (r["id"], r["scope"], exc))
        if (done + errors) % 25 == 0:
            conn.commit()
    conn.commit()
    print("Done: %d synthesized (%d chars), %d errors." % (done, chars, errors))
    if errors:
        print("Re-run with --redo-errors after fixing the cause.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--provider", choices=["report"] + list(BACKENDS),
                    default="report")
    ap.add_argument("--report", action="store_true",
                    help="print the character / free-tier analysis and exit")
    ap.add_argument("--voice", default=None, help="provider-specific voice name")
    ap.add_argument("--piper-model", default=None, help="path to a Piper .onnx voice")
    ap.add_argument("--limit", type=int, default=0, help="cap items (smoke test)")
    ap.add_argument("--set", dest="set_name", default=None,
                    help="only this word set, e.g. --set 'A1 (frequency)'")
    ap.add_argument("--redo-errors", action="store_true",
                    help="also retry rows currently marked 'error'")
    args = ap.parse_args()

    if args.report:
        args.provider = "report"

    conn = connect(args.db)
    try:
        if args.provider == "report":
            cmd_report(conn)
        else:
            cmd_generate(conn, args.provider, args.voice, args.piper_model,
                         args.limit, args.redo_errors, args.set_name)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
