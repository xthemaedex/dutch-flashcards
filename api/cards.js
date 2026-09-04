import { all, send } from "./_lib.js";

// Lean list for building the SRS queue + rendering a card FRONT. Deliberately NO
// audio joins (they're slow at 8k rows) — the front's word-audio comes from the
// /api/details payload the app already loads. maxAge keeps this edge-cached.
export default async function handler(req, res) {
  const rows = await all(`
    SELECT w.id, w.lemma, w.part_of_speech AS pos, w.article, w.gender,
           w.cefr_level AS cefr, w.frequency_rank AS rank, w.translation_en,
           s.sentence_nl, s.sentence_blanked,
           NULL AS word_audio, NULL AS sentence_audio,
           (w.part_of_speech = 'verb') AS is_verb
    FROM words w
    LEFT JOIN example_sentences s ON s.word_id = w.id AND s.sort_order = 0
    ORDER BY w.frequency_rank
  `);
  send(res, rows, { maxAge: 3600 });
}
