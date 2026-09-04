-- Dutch Flashcard App — Phase 1 database schema (SQLite)
-- The finished app queries this database ONLY. No runtime API calls of any kind.
-- All content (definitions, sentences, conjugations) is generated once and inserted
-- by scripts/seed_db.py. Audio files are generated once by scripts/generate_audio.py
-- and referenced here by relative path.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------------
-- Word sets: CEFR levels (A1..B2) and/or thematic groupings.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS word_sets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    cefr_level  TEXT,                       -- 'A1','A2','B1','B2' or NULL for pure themes
    theme       TEXT,                       -- e.g. 'travel', 'work', 'mixed'
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Words: one row per lemma + part of speech.
-- Noun columns (article/gender/plural) and verb columns (infinitive/
-- past_participle/auxiliary/...) are NULL when not applicable.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS words (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma           TEXT    NOT NULL,
    part_of_speech  TEXT    NOT NULL,       -- 'noun','verb','adjective','adverb','pronoun',...
    translation_en  TEXT    NOT NULL,       -- short gloss shown on the card back
    definition_nl   TEXT,
    definition_en   TEXT,

    -- noun-specific
    article         TEXT,                   -- 'de' | 'het' | NULL
    gender          TEXT,                   -- 'common' | 'neuter' | 'masculine' | 'feminine' | NULL
    plural          TEXT,

    -- verb-specific
    infinitive      TEXT,
    past_participle TEXT,
    auxiliary       TEXT,                   -- 'hebben' | 'zijn'
    is_separable    INTEGER NOT NULL DEFAULT 0,
    is_irregular    INTEGER NOT NULL DEFAULT 0,

    -- meta
    cefr_level      TEXT,
    frequency_rank  INTEGER,                -- lower = more frequent; drives review priority

    -- optional per-word image (Phase 4). Fetched once by scripts/fetch_images.py
    -- and self-hosted; never requested at runtime. NULL for abstract words /
    -- particles / anything without a good match -> card falls back to text-only.
    image_path       TEXT,                  -- relative path, e.g. 'images/hond.jpg'
    image_source     TEXT,                  -- 'openverse' | 'wikimedia' | ...
    image_attribution TEXT,                 -- ready-to-show credit line
    image_source_url TEXT,                  -- where the image came from (landing page)
    image_license    TEXT,                  -- e.g. 'CC BY 2.0', 'CC0', 'PDM'

    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),

    CHECK (article IS NULL OR article IN ('de','het')),
    CHECK (auxiliary IS NULL OR auxiliary IN ('hebben','zijn')),
    UNIQUE (lemma, part_of_speech)
);

-- Many-to-many: a word can belong to several sets (e.g. its CEFR level + a theme).
CREATE TABLE IF NOT EXISTS word_set_members (
    word_id INTEGER NOT NULL REFERENCES words(id)     ON DELETE CASCADE,
    set_id  INTEGER NOT NULL REFERENCES word_sets(id) ON DELETE CASCADE,
    PRIMARY KEY (word_id, set_id)
);

-- ---------------------------------------------------------------------------
-- Example sentences: at least one per word. sentence_blanked is the
-- fill-in-the-blank string shown on the front of the card (target word -> ___).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS example_sentences (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id          INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    sentence_nl      TEXT    NOT NULL,
    sentence_en      TEXT    NOT NULL,
    sentence_blanked TEXT,
    sort_order       INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Verb conjugations: 7 tenses x 6 persons per verb.
--   tense  in ('presens','imperfectum','perfectum','plusquamperfectum',
--              'futurum','futurum_exactum','conditionalis')
--   person in ('ik','jij','hij','wij','jullie','zij_mv')
-- form           = full form incl. pronoun, e.g. 'ik heb gewerkt'
-- verb_form_only = form without the pronoun,   e.g. 'heb gewerkt'
-- *_sort columns give a stable display order for the linked-set card view (Phase 2).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verb_conjugations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id        INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    tense          TEXT    NOT NULL,
    person         TEXT    NOT NULL,
    form           TEXT    NOT NULL,
    verb_form_only TEXT,
    tense_sort     INTEGER NOT NULL DEFAULT 0,
    person_sort    INTEGER NOT NULL DEFAULT 0,

    CHECK (tense  IN ('presens','imperfectum','perfectum','plusquamperfectum',
                      'futurum','futurum_exactum','conditionalis')),
    CHECK (person IN ('ik','jij','hij','wij','jullie','zij_mv')),
    UNIQUE (word_id, tense, person)
);

-- ---------------------------------------------------------------------------
-- Audio assets: one row per piece of speakable text. Rows are created (status
-- 'pending') by seed_db.py; generate_audio.py fills file_path / voice / status.
-- Exactly one of word_id / sentence_id / conjugation_id is set; dedup_key makes
-- the intent explicit and unique (SQLite treats multiple NULLs as distinct).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audio_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scope           TEXT    NOT NULL,       -- 'word' | 'sentence' | 'conjugation'
    dedup_key       TEXT    NOT NULL UNIQUE,-- e.g. 'word:12', 'sentence:5', 'conj:88'
    word_id         INTEGER REFERENCES words(id)             ON DELETE CASCADE,
    sentence_id     INTEGER REFERENCES example_sentences(id) ON DELETE CASCADE,
    conjugation_id  INTEGER REFERENCES verb_conjugations(id) ON DELETE CASCADE,

    text            TEXT    NOT NULL,       -- exact string sent to the TTS engine
    char_count      INTEGER NOT NULL,
    file_path       TEXT,                   -- relative path, e.g. 'audio/word/0001.mp3'
    audio_format    TEXT    NOT NULL DEFAULT 'mp3',
    provider        TEXT,                   -- 'google' | 'edge' | 'piper' | 'espeak'
    voice_name      TEXT,                   -- e.g. 'nl-NL-Standard-D', 'nl-NL-MaartenNeural'
    status          TEXT    NOT NULL DEFAULT 'pending',  -- 'pending'|'done'|'error'|'skipped'
    error_message   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT,

    CHECK (scope  IN ('word','sentence','conjugation')),
    CHECK (status IN ('pending','done','error','skipped'))
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_words_pos        ON words(part_of_speech);
CREATE INDEX IF NOT EXISTS idx_words_freq       ON words(frequency_rank);
CREATE INDEX IF NOT EXISTS idx_setmembers_set   ON word_set_members(set_id);
CREATE INDEX IF NOT EXISTS idx_sentences_word   ON example_sentences(word_id);
CREATE INDEX IF NOT EXISTS idx_conj_word        ON verb_conjugations(word_id);
CREATE INDEX IF NOT EXISTS idx_conj_word_tense  ON verb_conjugations(word_id, tense_sort, person_sort);
CREATE INDEX IF NOT EXISTS idx_audio_word       ON audio_assets(word_id);
CREATE INDEX IF NOT EXISTS idx_audio_status     ON audio_assets(status);

-- ---------------------------------------------------------------------------
-- Convenience view: everything needed to render a single word card.
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_word_card AS
SELECT
    w.id                AS word_id,
    w.lemma,
    w.part_of_speech,
    w.translation_en,
    w.definition_nl,
    w.definition_en,
    w.article,
    w.gender,
    w.plural,
    w.infinitive,
    w.past_participle,
    w.auxiliary,
    w.cefr_level,
    w.frequency_rank,
    w.image_path,
    w.image_attribution,
    w.image_source_url,
    w.image_license,
    s.sentence_nl,
    s.sentence_en,
    s.sentence_blanked,
    aw.file_path        AS word_audio_path,
    asx.file_path       AS sentence_audio_path
FROM words w
LEFT JOIN example_sentences s
       ON s.word_id = w.id AND s.sort_order = 0
LEFT JOIN audio_assets aw
       ON aw.scope = 'word' AND aw.word_id = w.id AND aw.status = 'done'
LEFT JOIN audio_assets asx
       ON asx.scope = 'sentence' AND asx.sentence_id = s.id AND asx.status = 'done';

-- NOTE: Phase 2 will add SRS tables (e.g. review_state, review_log) referencing
-- words(id) and verb_conjugations(id). They are intentionally out of scope here.
