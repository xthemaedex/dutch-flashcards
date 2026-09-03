#!/usr/bin/env python3
"""
conjugator.py — rule-based Dutch verb conjugation engine (no API, deterministic).

Produces the 7 tenses x 6 persons used by the flashcard app:
    presens, imperfectum, perfectum, plusquamperfectum,
    futurum, futurum_exactum, conditionalis
    persons: ik, jij, hij, wij, jullie, zij_mv

Approach:
  * Weak (regular) verbs: derived from spelling rules
      - stem: strip -en, undo v/z devoicing, reduce doubled consonants,
        lengthen open-syllable vowels ('maken' -> 'maak')
      - imperfectum + past participle: 't kofschip (voiceless -> -te/-t, else -de/-d)
  * Strong / irregular verbs: STRONG table below gives
        (imperfectum_sing, imperfectum_plur, past_participle, auxiliary)
  * A handful of verbs are also irregular in the present tense -> PRESENT_IRREGULAR
  * Separable verbs ('opbellen'): detected via SEPARABLE_PREFIXES, the prefix
    detaches in main-clause finite forms and attaches in 'ge-' participle.
  * Auxiliary defaults to 'hebben'; STRONG table or an explicit arg can set 'zijn'.

CLI:
    python3 scripts/conjugator.py werken hebben zijn opbellen studeren gaan
    python3 scripts/conjugator.py --json werken
    python3 scripts/conjugator.py --selftest
"""

import argparse
import json
import re
import sys

PERSONS = ["ik", "jij", "hij", "wij", "jullie", "zij_mv"]
PRONOUN = {"ik": "ik", "jij": "jij", "hij": "hij",
           "wij": "wij", "jullie": "jullie", "zij_mv": "zij"}
TENSES = ["presens", "imperfectum", "perfectum", "plusquamperfectum",
          "futurum", "futurum_exactum", "conditionalis"]

VOWELS = "aeiou"
# 't kofschip (+ x): infinitive-minus-en ending in one of these -> voiceless -> -t/-te
KOFSCHIP = {"t", "k", "f", "s", "p", "x", "c", "ch", "sh"}

# Prefixes taken as separable. over-/onder-/door-/voor-/om-/achter- can also be
# inseparable for some verbs (voorkómen 'prevent' vs voorkomen 'occur'); the
# separable reading is the common one for frequent verbs, so we default to it and
# let Wiktionary's participle / the STRONG table correct the exceptions.
SEPARABLE_PREFIXES = [
    "aan", "achter", "af", "bij", "binnen", "boven", "buiten", "deel", "door",
    "in", "langs", "mede", "mee", "na", "neer", "om", "onder", "op", "over",
    "rond", "samen", "terug", "tegen", "toe", "tussen", "uit", "vast", "voor",
    "voort", "vooruit", "weg",
]
# Truly inseparable unstressed prefixes -> no 'ge-' in the participle
INSEP_PREFIXES = ["be", "er", "ge", "her", "ont", "ver", "mis", "weer", "vol"]

# infinitive -> (imperfectum_sing, imperfectum_plur, past_participle, auxiliary)
STRONG = {
    "bakken": ("bakte", "bakten", "gebakken", "hebben"),
    "bederven": ("bedierf", "bedierven", "bedorven", "zijn"),
    "beginnen": ("begon", "begonnen", "begonnen", "zijn"),
    "begrijpen": ("begreep", "begrepen", "begrepen", "hebben"),
    "bevelen": ("beval", "bevalen", "bevolen", "hebben"),
    "bewegen": ("bewoog", "bewogen", "bewogen", "hebben"),
    "bidden": ("bad", "baden", "gebeden", "hebben"),
    "bieden": ("bood", "boden", "geboden", "hebben"),
    "bijten": ("beet", "beten", "gebeten", "hebben"),
    "binden": ("bond", "bonden", "gebonden", "hebben"),
    "blazen": ("blies", "bliezen", "geblazen", "hebben"),
    "blijken": ("bleek", "bleken", "gebleken", "zijn"),
    "blijven": ("bleef", "bleven", "gebleven", "zijn"),
    "blinken": ("blonk", "blonken", "geblonken", "hebben"),
    "braden": ("braadde", "braadden", "gebraden", "hebben"),
    "breken": ("brak", "braken", "gebroken", "hebben"),
    "brengen": ("bracht", "brachten", "gebracht", "hebben"),
    "denken": ("dacht", "dachten", "gedacht", "hebben"),
    "doen": ("deed", "deden", "gedaan", "hebben"),
    "dragen": ("droeg", "droegen", "gedragen", "hebben"),
    "drijven": ("dreef", "dreven", "gedreven", "hebben"),
    "dringen": ("drong", "drongen", "gedrongen", "hebben"),
    "drinken": ("dronk", "dronken", "gedronken", "hebben"),
    "duiken": ("dook", "doken", "gedoken", "hebben"),
    "dwingen": ("dwong", "dwongen", "gedwongen", "hebben"),
    "eten": ("at", "aten", "gegeten", "hebben"),
    "fluiten": ("floot", "floten", "gefloten", "hebben"),
    "gaan": ("ging", "gingen", "gegaan", "zijn"),
    "gelden": ("gold", "golden", "gegolden", "hebben"),
    "genezen": ("genas", "genazen", "genezen", "zijn"),
    "genieten": ("genoot", "genoten", "genoten", "hebben"),
    "geven": ("gaf", "gaven", "gegeven", "hebben"),
    "gieten": ("goot", "goten", "gegoten", "hebben"),
    "glijden": ("gleed", "gleden", "gegleden", "hebben"),
    "graven": ("groef", "groeven", "gegraven", "hebben"),
    "grijpen": ("greep", "grepen", "gegrepen", "hebben"),
    "hangen": ("hing", "hingen", "gehangen", "hebben"),
    "hebben": ("had", "hadden", "gehad", "hebben"),
    "heffen": ("hief", "hieven", "geheven", "hebben"),
    "helpen": ("hielp", "hielpen", "geholpen", "hebben"),
    "heten": ("heette", "heetten", "geheten", "hebben"),
    "houden": ("hield", "hielden", "gehouden", "hebben"),
    "kiezen": ("koos", "kozen", "gekozen", "hebben"),
    "kijken": ("keek", "keken", "gekeken", "hebben"),
    "klimmen": ("klom", "klommen", "geklommen", "zijn"),
    "klinken": ("klonk", "klonken", "geklonken", "hebben"),
    "komen": ("kwam", "kwamen", "gekomen", "zijn"),
    "kopen": ("kocht", "kochten", "gekocht", "hebben"),
    "krijgen": ("kreeg", "kregen", "gekregen", "hebben"),
    "krimpen": ("kromp", "krompen", "gekrompen", "zijn"),
    "kruipen": ("kroop", "kropen", "gekropen", "hebben"),
    "kunnen": ("kon", "konden", "gekund", "hebben"),
    "laten": ("liet", "lieten", "gelaten", "hebben"),
    "lezen": ("las", "lazen", "gelezen", "hebben"),
    "liegen": ("loog", "logen", "gelogen", "hebben"),
    "liggen": ("lag", "lagen", "gelegen", "hebben"),
    "lijden": ("leed", "leden", "geleden", "hebben"),
    "lijken": ("leek", "leken", "geleken", "hebben"),
    "lopen": ("liep", "liepen", "gelopen", "hebben"),
    "moeten": ("moest", "moesten", "gemoeten", "hebben"),
    "mogen": ("mocht", "mochten", "gemogen", "hebben"),
    "nemen": ("nam", "namen", "genomen", "hebben"),
    "prijzen": ("prees", "prezen", "geprezen", "hebben"),
    "raden": ("raadde", "raadden", "geraden", "hebben"),
    "rijden": ("reed", "reden", "gereden", "hebben"),
    "rijzen": ("rees", "rezen", "gerezen", "zijn"),
    "roepen": ("riep", "riepen", "geroepen", "hebben"),
    "ruiken": ("rook", "roken", "geroken", "hebben"),
    "schenken": ("schonk", "schonken", "geschonken", "hebben"),
    "scheppen": ("schiep", "schiepen", "geschapen", "hebben"),
    "scheren": ("schoor", "schoren", "geschoren", "hebben"),
    "schieten": ("schoot", "schoten", "geschoten", "hebben"),
    "schijnen": ("scheen", "schenen", "geschenen", "hebben"),
    "schrijven": ("schreef", "schreven", "geschreven", "hebben"),
    "schrikken": ("schrok", "schrokken", "geschrokken", "zijn"),
    "slaan": ("sloeg", "sloegen", "geslagen", "hebben"),
    "slapen": ("sliep", "sliepen", "geslapen", "hebben"),
    "slijten": ("sleet", "sleten", "gesleten", "zijn"),
    "sluiten": ("sloot", "sloten", "gesloten", "hebben"),
    "smelten": ("smolt", "smolten", "gesmolten", "zijn"),
    "snijden": ("sneed", "sneden", "gesneden", "hebben"),
    "spreken": ("sprak", "spraken", "gesproken", "hebben"),
    "springen": ("sprong", "sprongen", "gesprongen", "hebben"),
    "spuiten": ("spoot", "spoten", "gespoten", "hebben"),
    "staan": ("stond", "stonden", "gestaan", "hebben"),
    "steken": ("stak", "staken", "gestoken", "hebben"),
    "stelen": ("stal", "stalen", "gestolen", "hebben"),
    "sterven": ("stierf", "stierven", "gestorven", "zijn"),
    "stijgen": ("steeg", "stegen", "gestegen", "zijn"),
    "stinken": ("stonk", "stonken", "gestonken", "hebben"),
    "strijden": ("streed", "streden", "gestreden", "hebben"),
    "treden": ("trad", "traden", "getreden", "zijn"),
    "treffen": ("trof", "troffen", "getroffen", "hebben"),
    "trekken": ("trok", "trokken", "getrokken", "hebben"),
    "ontstaan": ("ontstond", "ontstonden", "ontstaan", "zijn"),
    "verstaan": ("verstond", "verstonden", "verstaan", "hebben"),
    "bevallen": ("beviel", "bevielen", "bevallen", "zijn"),
    "verdwijnen": ("verdween", "verdwenen", "verdwenen", "zijn"),
    "vallen": ("viel", "vielen", "gevallen", "zijn"),
    "vangen": ("ving", "vingen", "gevangen", "hebben"),
    "varen": ("voer", "voeren", "gevaren", "hebben"),
    "vechten": ("vocht", "vochten", "gevochten", "hebben"),
    "verdwijnen": ("verdween", "verdwenen", "verdwenen", "zijn"),
    "vergeten": ("vergat", "vergaten", "vergeten", "zijn"),
    "verliezen": ("verloor", "verloren", "verloren", "hebben"),
    "vinden": ("vond", "vonden", "gevonden", "hebben"),
    "vliegen": ("vloog", "vlogen", "gevlogen", "hebben"),
    "vragen": ("vroeg", "vroegen", "gevraagd", "hebben"),
    "vriezen": ("vroor", "vroren", "gevroren", "hebben"),
    "wassen": ("waste", "wasten", "gewassen", "hebben"),
    "wegen": ("woog", "wogen", "gewogen", "hebben"),
    "werpen": ("wierp", "wierpen", "geworpen", "hebben"),
    "weten": ("wist", "wisten", "geweten", "hebben"),
    "wijken": ("week", "weken", "geweken", "zijn"),
    "wijzen": ("wees", "wezen", "gewezen", "hebben"),
    "willen": ("wilde", "wilden", "gewild", "hebben"),
    "winnen": ("won", "wonnen", "gewonnen", "hebben"),
    "worden": ("werd", "werden", "geworden", "zijn"),
    "wrijven": ("wreef", "wreven", "gewreven", "hebben"),
    "zeggen": ("zei", "zeiden", "gezegd", "hebben"),
    "zenden": ("zond", "zonden", "gezonden", "hebben"),
    "zien": ("zag", "zagen", "gezien", "hebben"),
    "zijn": ("was", "waren", "geweest", "zijn"),
    "zingen": ("zong", "zongen", "gezongen", "hebben"),
    "zinken": ("zonk", "zonken", "gezonken", "zijn"),
    "zitten": ("zat", "zaten", "gezeten", "hebben"),
    "zoeken": ("zocht", "zochten", "gezocht", "hebben"),
    "zuipen": ("zoop", "zopen", "gezopen", "hebben"),
    "zullen": ("zou", "zouden", None, "hebben"),
    "zwemmen": ("zwom", "zwommen", "gezwommen", "hebben"),
    "zwijgen": ("zweeg", "zwegen", "gezwegen", "hebben"),
}

# infinitive -> present tense forms (ik, jij, hij, wij, jullie, zij_mv)
PRESENT_IRREGULAR = {
    "zijn":    ["ben", "bent", "is", "zijn", "zijn", "zijn"],
    "hebben":  ["heb", "hebt", "heeft", "hebben", "hebben", "hebben"],
    "kunnen":  ["kan", "kunt", "kan", "kunnen", "kunnen", "kunnen"],
    "zullen":  ["zal", "zult", "zal", "zullen", "zullen", "zullen"],
    "willen":  ["wil", "wilt", "wil", "willen", "willen", "willen"],
    "mogen":   ["mag", "mag", "mag", "mogen", "mogen", "mogen"],
    "gaan":    ["ga", "gaat", "gaat", "gaan", "gaan", "gaan"],
    "staan":   ["sta", "staat", "staat", "staan", "staan", "staan"],
    "slaan":   ["sla", "slaat", "slaat", "slaan", "slaan", "slaan"],
    "doen":    ["doe", "doet", "doet", "doen", "doen", "doen"],
    "zien":    ["zie", "ziet", "ziet", "zien", "zien", "zien"],
    "komen":   ["kom", "komt", "komt", "komen", "komen", "komen"],
}

AUX_PRESENT = {
    "hebben": ["heb", "hebt", "heeft", "hebben", "hebben", "hebben"],
    "zijn":   ["ben", "bent", "is", "zijn", "zijn", "zijn"],
}
AUX_IMPERF = {
    "hebben": ["had", "had", "had", "hadden", "hadden", "hadden"],
    "zijn":   ["was", "was", "was", "waren", "waren", "waren"],
}
ZULLEN_PRESENT = ["zal", "zult", "zal", "zullen", "zullen", "zullen"]
ZULLEN_COND    = ["zou", "zou", "zou", "zouden", "zouden", "zouden"]

DIGRAPH_VOWELS = ("aa", "ee", "oo", "uu", "ie", "ei", "ij", "ou",
                  "au", "eu", "oe", "ui", "ai", "oi")


class ConjugationError(ValueError):
    pass


def split_separable(infinitive):
    """Return (prefix, rest) for separable verbs, else ('', infinitive)."""
    for p in sorted(SEPARABLE_PREFIXES, key=len, reverse=True):
        if not infinitive.startswith(p) or len(infinitive) <= len(p) + 3:
            continue
        rest = infinitive[len(p):]
        if rest[0] in VOWELS and rest not in STRONG and rest not in PRESENT_IRREGULAR:
            continue                      # 'openen' is not 'op'+'enen'
        if rest in STRONG or rest in PRESENT_IRREGULAR:
            return p, rest
        if rest.endswith("en") and len(rest) >= 4:
            return p, rest
    return "", infinitive


def weak_stem(infinitive):
    """Spelling-rule present-tense stem of a weak verb ('maken' -> 'maak')."""
    if infinitive.endswith("en"):
        base = infinitive[:-2]
    elif infinitive.endswith("n"):
        base = infinitive[:-1]
    else:
        base = infinitive
    if not base:
        raise ConjugationError("cannot derive stem from %r" % infinitive)

    # v/z devoicing at end of stem
    if base.endswith("v"):
        base = base[:-1] + "f"
    elif base.endswith("z"):
        base = base[:-1] + "s"

    # reduce doubled final consonant: 'pakk' -> 'pak'
    if len(base) >= 2 and base[-1] == base[-2] and base[-1] not in VOWELS:
        return base[:-1]

    # schwa final syllable (-elen/-enen in a polysyllabic verb): no vowel change
    # 'openen' -> 'open', 'wandelen' -> 'wandel'
    if (len(base) >= 4 and base[-2:] in ("el", "en") and base[-3] not in VOWELS):
        return base
    # -eren verbs: lengthen only when a *single* consonant precedes '-er'
    # (loan verbs: studeren -> studeer, regeren -> regeer); a consonant cluster
    # means a schwa syllable (veranderen -> verander, luisteren -> luister).
    if len(base) >= 4 and base.endswith("er"):
        vgroups = len(re.findall(r"[aeiouy]+", base))
        if base[-3] not in VOWELS and base[-4] in VOWELS:
            # single consonant before '-er', vowel before that -> loan verb;
            # the '-er' syllable carries a long vowel: studer -> studeer
            return base[:-2] + "eer"
        if vgroups >= 2:
            # polysyllabic with a consonant cluster -> schwa: verander, luister
            return base

    # open-syllable vowel lengthening: single vowel + single final consonant
    if (len(base) >= 2 and base[-1] not in VOWELS and base[-1] != ""
            and base[-2] in "aeou"
            and (len(base) == 2 or base[-3] not in VOWELS)):
        # not already a digraph
        if not base[-3:-1] in DIGRAPH_VOWELS:
            return base[:-1] + base[-2] + base[-1]
    return base


def _kofschip_voiceless(infinitive):
    core = infinitive[:-2] if infinitive.endswith("en") else infinitive
    if core.endswith("ch"):
        return True
    return core[-1:] in {"t", "k", "f", "s", "p", "x", "c"}


def weak_forms(infinitive):
    stem = weak_stem(infinitive)
    voiceless = _kofschip_voiceless(infinitive)

    present = [
        stem,                                    # ik
        stem if stem.endswith("t") else stem + "t",   # jij
        stem if stem.endswith("t") else stem + "t",   # hij
        infinitive, infinitive, infinitive,      # wij, jullie, zij
    ]
    suf_sg = "te" if voiceless else "de"
    suf_pl = "ten" if voiceless else "den"
    imp_sg = stem + suf_sg
    imp_pl = stem + suf_pl
    imperf = [imp_sg, imp_sg, imp_sg, imp_pl, imp_pl, imp_pl]

    # past participle: ge + stem + t/d, but a stem already ending in t or d
    # takes no extra letter ('praten' -> 'gepraat', 'antwoorden' -> 'geantwoord')
    if stem.endswith(("t", "d")):
        participle = "ge" + stem
    else:
        participle = "ge" + stem + ("t" if voiceless else "d")
    return present, imperf, participle, "hebben"


def _present_from_strong(infinitive):
    """Strong verbs are usually regular in the present; derive via weak_stem."""
    if infinitive in PRESENT_IRREGULAR:
        return list(PRESENT_IRREGULAR[infinitive])
    stem = weak_stem(infinitive)
    return [
        stem,
        stem if stem.endswith("t") else stem + "t",
        stem if stem.endswith("t") else stem + "t",
        infinitive, infinitive, infinitive,
    ]


def base_parts(infinitive):
    """Return (present[6], imperf[6], participle, auxiliary) for the bare verb."""
    if infinitive in STRONG:
        imp_sg, imp_pl, participle, aux = STRONG[infinitive]
        present = _present_from_strong(infinitive)
        imperf = [imp_sg, imp_sg, imp_sg, imp_pl, imp_pl, imp_pl]
        return present, imperf, participle, aux
    return weak_forms(infinitive)


def conjugate(infinitive, auxiliary=None, core=None):
    """Conjugate `infinitive` into the 7-tense x 6-person table.

    `core` (optional) is a dict of trusted forms (e.g. pulled from Wiktionary)
    that overrides the rule engine for simple, non-separable verbs. Keys:
        present_1sg, present_2sg, present_3sg, present_pl,
        imperf_sg, imperf_pl, participle, auxiliary
    The 4 compound tenses are always assembled here — they are fully regular
    given participle + infinitive + auxiliary.
    """
    infinitive = infinitive.strip().lower()
    prefix, stem_core = split_separable(infinitive)

    present, imperf, participle, aux = base_parts(stem_core)
    is_irreg = stem_core in STRONG or stem_core in PRESENT_IRREGULAR

    if prefix:
        present = [f + " " + prefix for f in present]
        imperf = [f + " " + prefix for f in imperf]
        participle = prefix + participle
        full_inf = prefix + stem_core
    else:
        full_inf = infinitive
        if (participle and participle.startswith("ge")
                and any(stem_core.startswith(p) for p in INSEP_PREFIXES)):
            participle = participle[2:]

    # Trusted-source overrides (skip for separable verbs; the rule engine already
    # places the particle correctly and source forms are inconsistent there).
    if core and not prefix:
        if core.get("present_1sg"):
            present = [
                core.get("present_1sg") or present[0],
                core.get("present_2sg") or present[1],
                core.get("present_3sg") or present[2],
                core.get("present_pl") or present[3],
                core.get("present_pl") or present[4],
                core.get("present_pl") or present[5],
            ]
        if core.get("imperf_sg") or core.get("imperf_pl"):
            isg = core.get("imperf_sg") or imperf[0]
            ipl = core.get("imperf_pl") or imperf[3]
            imperf = [isg, isg, isg, ipl, ipl, ipl]

    # participle + auxiliary from a trusted source are complete forms; accept
    # them even for separable verbs (the compound tenses depend on them).
    if core and core.get("participle"):
        participle = core["participle"]
    if core and core.get("auxiliary") in ("hebben", "zijn"):
        aux = core["auxiliary"]

    if auxiliary in ("hebben", "zijn"):
        aux = auxiliary
    if not participle:
        raise ConjugationError("no participle for %r (defective verb)" % infinitive)

    is_strong = not participle.endswith(("t", "d"))

    out = {}
    out["presens"] = {p: _join(PRONOUN[p], present[i]) for i, p in enumerate(PERSONS)}
    out["imperfectum"] = {p: _join(PRONOUN[p], imperf[i]) for i, p in enumerate(PERSONS)}

    aux_pres = AUX_PRESENT[aux]
    aux_imp = AUX_IMPERF[aux]
    aux_inf = aux

    out["perfectum"] = {
        p: _join(PRONOUN[p], aux_pres[i], participle) for i, p in enumerate(PERSONS)
    }
    out["plusquamperfectum"] = {
        p: _join(PRONOUN[p], aux_imp[i], participle) for i, p in enumerate(PERSONS)
    }
    out["futurum"] = {
        p: _join(PRONOUN[p], ZULLEN_PRESENT[i], full_inf) for i, p in enumerate(PERSONS)
    }
    out["futurum_exactum"] = {
        p: _join(PRONOUN[p], ZULLEN_PRESENT[i], participle, aux_inf)
        for i, p in enumerate(PERSONS)
    }
    out["conditionalis"] = {
        p: _join(PRONOUN[p], ZULLEN_COND[i], full_inf) for i, p in enumerate(PERSONS)
    }
    return {
        "infinitive": full_inf,
        "past_participle": participle,
        "auxiliary": aux,
        "is_separable": bool(prefix),
        "is_irregular": bool(is_irreg or is_strong),
        "conjugations": out,
    }


def _join(*parts):
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------
SELFTEST = {
    "werken": {
        "presens": ["ik werk", "jij werkt", "hij werkt", "wij werken",
                    "jullie werken", "zij werken"],
        "imperfectum": ["ik werkte", "jij werkte", "hij werkte", "wij werkten",
                        "jullie werkten", "zij werkten"],
        "perfectum": ["ik heb gewerkt", "jij hebt gewerkt", "hij heeft gewerkt",
                      "wij hebben gewerkt", "jullie hebben gewerkt",
                      "zij hebben gewerkt"],
        "futurum_exactum": ["ik zal gewerkt hebben", "jij zult gewerkt hebben",
                            "hij zal gewerkt hebben", "wij zullen gewerkt hebben",
                            "jullie zullen gewerkt hebben", "zij zullen gewerkt hebben"],
        "conditionalis": ["ik zou werken", "jij zou werken", "hij zou werken",
                          "wij zouden werken", "jullie zouden werken",
                          "zij zouden werken"],
    },
    "hebben": {
        "presens": ["ik heb", "jij hebt", "hij heeft", "wij hebben",
                    "jullie hebben", "zij hebben"],
        "plusquamperfectum": ["ik had gehad", "jij had gehad", "hij had gehad",
                              "wij hadden gehad", "jullie hadden gehad",
                              "zij hadden gehad"],
    },
    "zijn": {
        "presens": ["ik ben", "jij bent", "hij is", "wij zijn", "jullie zijn",
                    "zij zijn"],
        "perfectum": ["ik ben geweest", "jij bent geweest", "hij is geweest",
                      "wij zijn geweest", "jullie zijn geweest", "zij zijn geweest"],
        "futurum": ["ik zal zijn", "jij zult zijn", "hij zal zijn", "wij zullen zijn",
                    "jullie zullen zijn", "zij zullen zijn"],
    },
}
# spot checks for the stemmer / weak rules
STEM_CHECKS = {
    "maken": "maak", "werken": "werk", "pakken": "pak",
    "horen": "hoor", "reizen": "reis", "leven": "leef", "bellen": "bel",
    "praten": "praat", "wonen": "woon", "fietsen": "fiets", "zetten": "zet",
    "openen": "open", "veranderen": "verander", "wandelen": "wandel",
    "leren": "leer", "tekenen": "teken",
}
PARTICIPLE_CHECKS = {
    "werken": "gewerkt", "praten": "gepraat", "antwoorden": "geantwoord",
    "zetten": "gezet", "leven": "geleefd", "reizen": "gereisd",
    "openen": "geopend", "veranderen": "veranderd", "betalen": "betaald",
    "studeren": "gestudeerd", "bestellen": "besteld",
}


def selftest():
    ok = True
    for verb, checks in SELFTEST.items():
        res = conjugate(verb)["conjugations"]
        for tense, expected in checks.items():
            got = [res[tense][p] for p in PERSONS]
            if got != expected:
                ok = False
                print("FAIL %s/%s\n  expected %s\n  got      %s"
                      % (verb, tense, expected, got))
    for inf, want in STEM_CHECKS.items():
        got = weak_stem(inf)
        if got != want:
            ok = False
            print("FAIL stem(%s): want %s got %s" % (inf, want, got))
    for inf, want in PARTICIPLE_CHECKS.items():
        got = conjugate(inf)["past_participle"]
        if got != want:
            ok = False
            print("FAIL participle(%s): want %s got %s" % (inf, want, got))
    # weak imperfectum kofschip
    for inf, want in {"werken": "ik werkte", "leven": "ik leefde",
                      "reizen": "ik reisde", "fietsen": "ik fietste",
                      "bellen": "ik belde"}.items():
        got = conjugate(inf)["conjugations"]["imperfectum"]["ik"]
        if got != want:
            ok = False
            print("FAIL imperf(%s): want %s got %s" % (inf, want, got))
    print("SELFTEST %s" % ("PASSED" if ok else "FAILED"))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("verbs", nargs="*")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--aux", choices=["hebben", "zijn"], default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if not args.verbs:
        ap.error("give one or more infinitives, or --selftest")

    results = {}
    for v in args.verbs:
        try:
            results[v] = conjugate(v, args.aux)
        except ConjugationError as e:
            results[v] = {"error": str(e)}

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for v, r in results.items():
        if "error" in r:
            print("%s: ERROR %s" % (v, r["error"]))
            continue
        print("\n=== %s === (aux %s, participle %s%s%s)" % (
            r["infinitive"], r["auxiliary"], r["past_participle"],
            ", separable" if r["is_separable"] else "",
            ", irregular" if r["is_irregular"] else ""))
        for tense in TENSES:
            forms = r["conjugations"][tense]
            print("  %-18s %s" % (tense, " | ".join(forms[p] for p in PERSONS)))


if __name__ == "__main__":
    main()
