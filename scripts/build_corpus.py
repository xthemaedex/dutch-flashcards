#!/usr/bin/env python3
"""
build_corpus.py — assemble the flashcard corpus from OFFLINE open datasets.

No API calls. Inputs (download once with fetch_sources.sh):
  data/sources/nl_50k.txt
      OpenSubtitles Dutch frequency list (hermitdave/FrequencyWords, CC-BY-SA 4.0)
  data/sources/kaikki.org-dictionary-Dutch.jsonl
      Wiktionary (English) Dutch extract from kaikki.org (CC-BY-SA 4.0 / GFDL)

Output:
  data/corpus_words.json     same shape as data/seed_words.json -> feed to seed_db.py
  data/corpus_report.md      counts + rows needing manual review

For each frequency-ranked lemma we take from Wiktionary: part of speech, English
gloss(es), de/het + gender + plural for nouns, and an example sentence (+ its
English translation) which we also turn into a fill-in-the-blank. Verb
conjugations come from scripts/conjugator.py (rule engine); the participle is
cross-checked against Wiktionary and disagreements are flagged, not silently kept.

Usage:
  python3 scripts/build_corpus.py --limit 2000
  python3 scripts/build_corpus.py --limit 8000 --out data/corpus_words.json
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import conjugator  # noqa: E402

SRC = os.path.join(ROOT, "data", "sources")
FREQ = os.path.join(SRC, "nl_50k.txt")
KAIKKI = os.path.join(SRC, "kaikki.org-dictionary-Dutch.jsonl")
TAT_NL = os.path.join(SRC, "nld_sentences.tsv")
TAT_EN = os.path.join(SRC, "eng_sentences.tsv")
TAT_LINKS = os.path.join(SRC, "nld-eng_links.tsv")
OUT_JSON = os.path.join(ROOT, "data", "corpus_words.json")
OUT_REPORT = os.path.join(ROOT, "data", "corpus_report.md")

POS_MAP = {
    "noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb",
    "num": "numeral", "pron": "pronoun", "prep": "preposition",
    "conj": "conjunction", "intj": "interjection", "det": "determiner",
    "article": "determiner", "particle": "particle",
}
# preference when a word has several parts of speech. Closed-class function
# words rank above noun so 'een'/'dat'/'over' aren't mis-tagged as nouns via a
# marginal Wiktionary noun sense.
POS_PRIORITY = ["numeral", "pronoun", "determiner", "conjunction", "preposition",
                "verb", "adjective", "noun", "adverb", "particle", "interjection"]
# hard overrides for a few very common words with messy multi-POS entries
POS_FORCE = {
    "een": "determiner", "de": "determiner", "het": "determiner",
    "dat": "conjunction", "die": "pronoun", "dit": "pronoun", "deze": "pronoun",
    "wat": "pronoun", "als": "conjunction", "of": "conjunction", "en": "conjunction",
    "maar": "conjunction", "want": "conjunction", "dan": "adverb", "er": "adverb",
    "over": "preposition", "door": "preposition", "voor": "preposition",
    "om": "preposition", "af": "adverb", "op": "preposition", "uit": "preposition",
    "niet": "adverb", "niets": "pronoun", "nog": "adverb", "ook": "adverb",
    "wel": "adverb", "heel": "adverb", "erg": "adverb", "zeer": "adverb",
    "me": "pronoun", "mij": "pronoun", "je": "pronoun", "jij": "pronoun",
    "ze": "pronoun", "we": "pronoun", "hem": "pronoun", "haar": "pronoun",
    "zich": "pronoun", "hun": "pronoun", "veel": "determiner", "velen": "pronoun",
    "weinig": "determiner", "geen": "determiner", "alle": "determiner",
    "pas": "adverb", "even": "adverb", "toch": "adverb", "al": "adverb",
    # core verbs that also have a pronoun/determiner reading ('zijn' = his)
    "zijn": "verb", "hebben": "verb", "worden": "verb", "kunnen": "verb",
    "zullen": "verb", "moeten": "verb", "mogen": "verb", "willen": "verb",
}
_RARE_TAGS = {"archaic", "obsolete", "dated", "poetic", "rare", "dialectal",
              "historical", "literary"}
# hand-maintained: frequency tokens that resolve to a misleading Wiktionary entry
# (rare verb homographs of a common noun/quantifier, etc.). Grows with review.
SKIP_LEMMAS = {"bomen", "velen", "malen", "pikken", "aarden",
               "dingen", "wezen", "middelen", "gassen", "dozen"}

CEFR_BANDS = [(750, "A1"), (1500, "A2"), (3000, "B1"), (10 ** 9, "B2")]

_WORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)


def load_tatoeba(max_per_token=25):
    """Build token -> [(nl, en), ...] index from Tatoeba (nl sentences that have
    an English translation). Sentences are length-filtered for flashcard use."""
    if not all(os.path.exists(p) for p in (TAT_NL, TAT_EN, TAT_LINKS)):
        sys.stderr.write("Tatoeba files missing; skipping example sentences.\n")
        return {}

    nl_text = {}
    with open(TAT_NL, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                nl_text[p[0]] = p[2]

    # nl_id -> first eng_id
    pair = {}
    need_en = set()
    with open(TAT_LINKS, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) == 2 and p[0] in nl_text and p[0] not in pair:
                pair[p[0]] = p[1]
                need_en.add(p[1])

    en_text = {}
    with open(TAT_EN, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3 and p[0] in need_en:
                en_text[p[0]] = p[2]

    index = {}
    n = 0
    for nl_id, en_id in pair.items():
        nl = nl_text.get(nl_id, "")
        en = en_text.get(en_id, "")
        if not nl or not en:
            continue
        wc = nl.count(" ") + 1
        if wc < 3 or wc > 14 or len(nl) > 90:
            continue
        if any(c in nl for c in "\"()[]/\\") or nl.count(",") > 1:
            continue
        toks = set(t.lower() for t in _WORD_RE.findall(nl))
        rec = (nl, en, wc)
        for t in toks:
            if len(t) < 2:
                continue
            bucket = index.setdefault(t, [])
            if len(bucket) < max_per_token:
                bucket.append(rec)
        n += 1
    sys.stderr.write("Tatoeba: indexed %d nl/en sentence pairs, %d tokens\n"
                     % (n, len(index)))
    return index


def tatoeba_example(index, forms):
    """Pick the best (nl, en) Tatoeba pair that contains one of `forms`."""
    best = None
    best_key = None
    for f in forms:
        for nl, en, wc in index.get(f.lower(), ()):
            # prefer: contains a blankable form, 5-11 words, then shorter
            blank = make_blank(nl, forms)
            key = (0 if blank else 1, 0 if 5 <= wc <= 11 else 1, wc, len(nl))
            if best_key is None or key < best_key:
                best_key = key
                best = (nl, en)
    return best


def cefr_for_rank(rank):
    for ceiling, level in CEFR_BANDS:
        if rank <= ceiling:
            return level
    return "B2"


def load_frequency(limit):
    """Return list of (lemma, rank) for the first `limit` usable tokens."""
    out = []
    with open(FREQ, encoding="utf-8") as fh:
        rank = 0
        for line in fh:
            parts = line.split()
            if len(parts) != 2:
                continue
            token = parts[0].strip().lower()
            if not token or not _WORD_RE.fullmatch(token) or len(token) < 2:
                continue
            rank += 1
            out.append((token, rank))
            if rank >= limit * 3:   # over-fetch; many will miss in Wiktionary
                break
    return out


def sense_is_form_of(sense):
    if sense.get("form_of") or sense.get("alt_of"):
        return True
    tags = sense.get("tags") or []
    if "form-of" in tags or "alt-of" in tags:
        return True
    gl = " ".join(sense.get("glosses") or []).lower()
    return gl.startswith(("inflection of", "plural of", "singular of",
                          "past tense of", "past participle of", "gerund of",
                          "diminutive of", "alternative form of",
                          "alternative spelling of", "obsolete form of"))


def index_kaikki(wanted):
    """Map lemma -> {pos: entry} for lemmas in `wanted` (a set)."""
    idx = {}
    with open(KAIKKI, encoding="utf-8") as fh:
        for line in fh:
            if '"lang_code": "nl"' not in line and '"lang_code":"nl"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("lang_code") != "nl":
                continue
            w = (o.get("word") or "").lower()
            if w not in wanted:
                continue
            pos = POS_MAP.get(o.get("pos"))
            if not pos:
                continue
            real_senses = [s for s in o.get("senses", []) if not sense_is_form_of(s)]
            if not real_senses:
                continue
            o["_senses"] = real_senses
            slot = idx.setdefault(w, {})
            # keep the entry with the most usable senses for a given pos
            if pos not in slot or len(real_senses) > len(slot[pos].get("_senses", [])):
                slot[pos] = o
    return idx


def _all_senses_rare(entry):
    ss = entry.get("_senses", [])
    return bool(ss) and all(set(s.get("tags") or []) & _RARE_TAGS for s in ss)


def pick_pos(entries, lemma=None):
    if lemma in POS_FORCE and POS_FORCE[lemma] in entries:
        return POS_FORCE[lemma], entries[POS_FORCE[lemma]]
    # if the verb reading is entirely rare/archaic but a noun/adj reading isn't,
    # take the common one ('bomen' the trees, not 'bomen' = to chat)
    if "verb" in entries and _all_senses_rare(entries["verb"]):
        for alt in ("noun", "adjective"):
            if alt in entries and not _all_senses_rare(entries[alt]):
                return alt, entries[alt]
    for p in POS_PRIORITY:
        if p in entries:
            return p, entries[p]
    k = next(iter(entries))
    return k, entries[k]


def verb_entry_is_infinitive(entry, lemma):
    """True unless the kaikki entry has forms and none is 'infinitive' == lemma."""
    forms = entry.get("forms", [])
    inf_forms = [f.get("form") for f in forms if (f.get("tags") or []) == ["infinitive"]]
    if not inf_forms:
        return True   # no conjugation table to judge by
    return lemma in inf_forms


def clean_gloss(g):
    g = re.sub(r"\s+", " ", g or "").strip().rstrip(".")
    return g


def glosses_of(entry, n=3):
    out = []
    for s in entry["_senses"]:
        for g in s.get("glosses") or []:
            g = clean_gloss(g)
            if g and g not in out:
                out.append(g)
        if len(out) >= n:
            break
    return out[:n]


NOUN_GENDER_TAGS = {
    "neuter": ("het", "neuter"),
    "masculine": ("de", "masculine"),
    "feminine": ("de", "feminine"),
    "common-gender": ("de", "common"),
    "common": ("de", "common"),
}


def noun_article_gender(entry):
    for s in entry["_senses"]:
        for t in s.get("tags") or []:
            if t in NOUN_GENDER_TAGS:
                return NOUN_GENDER_TAGS[t]
    exp = " ".join(h.get("expansion", "") for h in entry.get("head_templates", []))
    m = re.search(r"\b%s\s+([nmfc])\b" % re.escape(entry["word"]), exp)
    if m:
        return {"n": ("het", "neuter"), "m": ("de", "masculine"),
                "f": ("de", "feminine"), "c": ("de", "common")}[m.group(1)]
    for t in entry.get("forms", []):
        if "neuter" in (t.get("tags") or []) and t.get("form") == entry["word"]:
            return ("het", "neuter")
    return (None, None)


def noun_plural(entry):
    for t in entry.get("forms", []):
        tags = t.get("tags") or []
        if "plural" in tags and "indefinite" not in tags and t.get("form"):
            if t["form"] not in ("-", entry["word"]):
                return t["form"]
    exp = " ".join(h.get("expansion", "") for h in entry.get("head_templates", []))
    m = re.search(r"plural (\S+?)[,)]", exp)
    return m.group(1) if m else None


def wiktionary_participle(entry):
    for t in entry.get("forms", []):
        tags = set(t.get("tags") or [])
        if "past" in tags and "participle" in tags and t.get("form"):
            return t["form"]
    return None


_FORM_EXCLUDE = {
    "archaic", "subjunctive", "formal", "majestic", "colloquial", "Flanders",
    "dialectal", "obsolete", "alternative", "rare", "informal", "imperative",
    "gerund", "table-tags", "inflection-template", "nonstandard", "dated",
    "poetic", "class", "error-unknown-tag",
}
# verbs that take 'zijn' as perfect auxiliary (beyond the STRONG table)
ZIJN_VERBS = {
    "gebeuren", "groeien", "slagen", "stoppen", "veranderen", "verhuizen",
    "landen", "ontsnappen", "overlijden", "verongelukken", "belanden",
    "arriveren", "emigreren", "immigreren", "promoveren",
}


def kaikki_core_forms(entry):
    """Extract clean core verb forms from a kaikki entry's `forms` list."""
    slots = {}

    def consider(key, form):
        if form and form not in ("-", "") and key not in slots:
            slots[key] = form

    for t in entry.get("forms", []):
        form = (t.get("form") or "").strip()
        tags = set(t.get("tags") or [])
        if not form or tags & _FORM_EXCLUDE:
            continue
        if tags == {"infinitive"}:
            consider("infinitive", form)
        elif tags == {"first-person", "present", "singular"}:
            consider("present_1sg", form)
        elif tags == {"present", "singular", "third-person"}:
            consider("present_3sg", form)
        elif tags == {"present", "second-person", "singular"}:
            # two candidates (werkt / werk) share tags -> keep the -t form
            if "present_2sg" not in slots or form.endswith("t"):
                slots["present_2sg"] = form
        elif tags == {"plural", "present"}:
            consider("present_pl", form)
        elif tags == {"first-person", "past", "singular"} or tags == {"past", "singular", "third-person"}:
            consider("imperf_sg", form)
        elif tags == {"past", "plural"}:
            consider("imperf_pl", form)
        elif tags == {"participle", "past"}:
            consider("participle", form)
    return slots


def word_forms_for_cloze(lemma, pos, conj):
    """Surface forms of the *lexical* word for fill-in-the-blank matching.

    For verbs we deliberately use only the single-verb tenses (presens,
    imperfectum), the participle and the infinitive -- never the compound
    tenses, whose auxiliaries ('heb', 'was', 'zal', ...) would otherwise get
    blanked instead of the target verb.
    """
    forms = {lemma}
    if pos == "verb" and conj:
        for tense_name in ("presens", "imperfectum"):
            for f in conj["conjugations"][tense_name].values():
                parts = f.split()[1:]          # drop the pronoun
                if parts:
                    forms.add(parts[0])        # the finite verb (ignore trailing particle)
        forms.add(conj["past_participle"])
        forms.add(conj["infinitive"])
    return {f for f in forms if len(f) >= 2}


def make_blank(sentence, forms):
    for f in sorted(forms, key=len, reverse=True):
        pat = re.compile(r"\b%s\b" % re.escape(f), re.IGNORECASE)
        if pat.search(sentence):
            return pat.sub("___", sentence, count=1)
    return None


def pick_example(entry, forms):
    best = None
    best_score = -1
    for s in entry["_senses"]:
        for ex in s.get("examples") or []:
            nl = (ex.get("text") or "").strip()
            en = (ex.get("english") or "").strip()
            if not nl or len(nl) < 8 or nl.count(" ") < 2:
                continue
            score = 0
            if make_blank(nl, forms):
                score += 5
            if en:
                score += 3
            wc = nl.count(" ") + 1
            if 4 <= wc <= 16:
                score += 2
            elif wc > 24:
                score -= 2
            if score > best_score:
                best_score = score
                best = (nl, en)
    return best


def build(limit):
    freq = load_frequency(limit)
    wanted = set(w for w, _ in freq)
    sys.stderr.write("Indexing Wiktionary for %d candidate lemmas...\n" % len(wanted))
    idx = index_kaikki(wanted)
    sys.stderr.write("  matched %d lemmas in Wiktionary\n" % len(idx))
    tat = load_tatoeba()

    words = []
    seen = set()
    flags = {"conj_participle_mismatch": [], "no_example": [], "no_translation": [],
             "no_cloze": [], "noun_no_article": [], "verb_unknown_strength": [],
             "verb_rules_only": []}
    counts = {}

    for lemma, rank in freq:
        if len(words) >= limit:
            break
        if lemma in SKIP_LEMMAS:
            seen.add(lemma)
            continue
        if lemma in seen or lemma not in idx:
            continue
        seen.add(lemma)
        pos, entry = pick_pos(idx[lemma], lemma)

        gl = glosses_of(entry)
        if not gl:
            flags["no_translation"].append(lemma)
            continue
        translation_en = "; ".join(gl[:2])
        definition_en = ". ".join(gl)

        rec = {
            "lemma": lemma,
            "part_of_speech": pos,
            "translation_en": translation_en,
            "definition_nl": None,
            "definition_en": definition_en,
            "article": None, "gender": None, "plural": None,
            "cefr_level": cefr_for_rank(rank),
            "frequency_rank": rank,
            "sets": [cefr_for_rank(rank) + " (frequency)"],
            "examples": [],
        }

        conj = None
        if pos == "verb":
            plausible = (lemma.endswith("en")
                         or lemma in ("zijn", "gaan", "doen", "zien", "staan", "slaan"))
            if not plausible or not verb_entry_is_infinitive(entry, lemma):
                flags.setdefault("verb_not_infinitive", []).append(lemma)
                continue
            _GE_VERBS_OK = {"geloven", "gebeuren", "gebruiken", "genezen",
                            "getuigen", "gehoorzamen", "gedogen", "genieten",
                            "geven", "gedragen", "gebieden", "gelden"}
            if (lemma.startswith("ge") and lemma.endswith("en")
                    and lemma not in conjugator.STRONG
                    and lemma not in _GE_VERBS_OK):
                if "noun" in idx[lemma]:
                    pos = "noun"
                    entry = idx[lemma]["noun"]
                    rec["part_of_speech"] = "noun"
                    rec["translation_en"] = "; ".join(glosses_of(entry)[:2])
                else:
                    flags.setdefault("verb_not_infinitive", []).append(
                        lemma + " (ge-...-en, likely past participle)")
                    continue
            wcore = kaikki_core_forms(entry)
            if not wcore.get("participle"):
                wp0 = wiktionary_participle(entry)
                if wp0:
                    wcore["participle"] = wp0   # trust Wiktionary's participle
            if not wcore.get("auxiliary"):
                if lemma in conjugator.STRONG:
                    wcore["auxiliary"] = conjugator.STRONG[lemma][3]
                elif lemma in ZIJN_VERBS:
                    wcore["auxiliary"] = "zijn"
            try:
                conj = conjugator.conjugate(lemma, core=wcore)
            except conjugator.ConjugationError as e:
                flags["verb_unknown_strength"].append("%s (%s)" % (lemma, e))
                continue
            rec["infinitive"] = conj["infinitive"]
            rec["past_participle"] = conj["past_participle"]
            rec["auxiliary"] = conj["auxiliary"]
            rec["is_separable"] = conj["is_separable"]
            rec["is_irregular"] = conj["is_irregular"]
            rec["conjugation_source"] = (
                "wiktionary" if wcore.get("participle") else "rules")
            rec["conjugations"] = conj["conjugations"]
            wp = wiktionary_participle(entry)
            if wp and wp != conj["past_participle"]:
                flags["conj_participle_mismatch"].append(
                    "%s: final=%s wiktionary=%s" % (lemma, conj["past_participle"], wp)
                )
            if not wcore.get("participle"):
                _, base = conjugator.split_separable(lemma)
                known = base in conjugator.STRONG or base in conjugator.PRESENT_IRREGULAR
                if not known and conj["is_irregular"]:
                    flags["verb_unknown_strength"].append(
                        "%s: no Wiktionary forms + not in irregulars table; "
                        "rule engine guessed strong (participle %s) -- VERIFY"
                        % (lemma, conj["past_participle"]))
                elif not known:
                    flags.setdefault("verb_rules_only", []).append(lemma)

        if pos == "noun":
            art, gen = noun_article_gender(entry)
            rec["article"], rec["gender"] = art, gen
            rec["plural"] = noun_plural(entry)
            if not art:
                flags["noun_no_article"].append(lemma)

        forms = word_forms_for_cloze(lemma, pos, conj)
        ex = tatoeba_example(tat, forms) if tat else None
        ex_src = "tatoeba"
        if not ex:
            ex = pick_example(entry, forms)
            ex_src = "wiktionary"
        if not ex:
            flags["no_example"].append(lemma)
        else:
            nl, en = ex
            blank = make_blank(nl, forms)
            if not blank:
                flags["no_cloze"].append(lemma)
            rec["examples"].append({
                "nl": nl,
                "en": en or "(no translation available)",
                "blanked": blank,
                "source": ex_src,
            })

        # a card needs at least a translation; example is strongly preferred
        counts[pos] = counts.get(pos, 0) + 1
        words.append(rec)

    # word sets
    levels = sorted({w["cefr_level"] for w in words})
    word_sets = [
        {"name": lv + " (frequency)", "cefr_level": lv, "theme": "frequency",
         "description": "Auto-built from OpenSubtitles frequency rank + Wiktionary.",
         "sort_order": i + 1}
        for i, lv in enumerate(levels)
    ]

    data = {
        "meta": {
            "batch": "corpus v1 (offline: frequency + Wiktionary + rule conjugator)",
            "generated_at": "2026-09-03",
            "sources": [
                "hermitdave/FrequencyWords 2018 nl_50k (CC-BY-SA 4.0)",
                "kaikki.org Dutch Wiktionary extract (CC-BY-SA 4.0 / GFDL)",
            ],
            "limit": limit,
            "word_count": len(words),
            "notes": "definition_nl is NULL (Wiktionary English has no Dutch defs). "
                     "CEFR level is a frequency-band heuristic, not official CEFR. "
                     "Verb conjugations are rule-generated; review corpus_report.md.",
        },
        "word_sets": word_sets,
        "persons": conjugator.PERSONS,
        "tenses": conjugator.TENSES,
        "words": words,
    }
    return data, flags, counts


def write_report(flags, counts, data):
    lines = ["# Corpus build report\n",
             "Generated %s. %d words.\n" % (data["meta"]["generated_at"],
                                            data["meta"]["word_count"])]
    lines.append("## Part-of-speech counts\n")
    for pos, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append("- %s: %d" % (pos, n))
    lines.append("\n## Rows needing manual review\n")
    titles = {
        "conj_participle_mismatch":
            "Verb: final participle disagrees with Wiktionary's listed participle",
        "verb_unknown_strength":
            "Verb: no data + not in irregulars table, engine guessed -- VERIFY",
        "verb_rules_only":
            "Verb: conjugated by spelling rules only (weak, no Wiktionary table)",
        "verb_not_infinitive":
            "Skipped: frequency token tagged 'verb' but not an infinitive "
            "(inflected form / plural noun homograph)",
        "noun_no_article": "Noun: no de/het determined (plurale tantum / loanword)",
        "no_example": "No usable example sentence (Tatoeba + Wiktionary)",
        "no_cloze": "Example present but headword form not found for fill-in-the-blank",
        "no_translation": "No English gloss (skipped)",
    }
    for key, title in titles.items():
        items = flags.get(key, [])
        lines.append("### %s — %d\n" % (title, len(items)))
        if items:
            lines.append("```")
            lines.extend(items[:200])
            if len(items) > 200:
                lines.append("... (%d more)" % (len(items) - 200))
            lines.append("```")
        lines.append("")
    with open(OUT_REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=2000,
                    help="number of words to emit (default 2000)")
    ap.add_argument("--out", default=OUT_JSON)
    args = ap.parse_args()

    for p in (FREQ, KAIKKI):
        if not os.path.exists(p):
            sys.exit("missing source: %s  (run scripts/fetch_sources.sh)" % p)

    if not conjugator.selftest():
        sys.exit("conjugator selftest failed; aborting")

    data, flags, counts = build(args.limit)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    write_report(flags, counts, data)

    print("\nWrote %s  (%d words)" % (args.out, len(data["words"])))
    print("Wrote %s" % OUT_REPORT)
    print("POS:", ", ".join("%s=%d" % kv for kv in sorted(counts.items())))
    print("Flags:", ", ".join("%s=%d" % (k, len(v)) for k, v in flags.items() if v))
    print("\nNext: python3 scripts/seed_db.py --reset --json %s" % os.path.relpath(args.out, ROOT))


if __name__ == "__main__":
    main()
