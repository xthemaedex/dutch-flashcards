import { all, send, audioUrl } from "./_lib.js";

// Search / list endpoint: /api/words?q=&set=&pos=&limit=&offset=
export default async function handler(req, res) {
  const { q, set, pos, limit = "500", offset = "0" } = req.query;
  const where = ["1=1"];
  const args = [];
  if (set) { where.push("w.id IN (SELECT word_id FROM word_set_members WHERE set_id = ?)"); args.push(set); }
  if (pos) { where.push("w.part_of_speech = ?"); args.push(pos); }
  if (q) { where.push("(w.lemma LIKE ? OR w.translation_en LIKE ?)"); args.push(`%${q}%`, `%${q}%`); }
  const clause = where.join(" AND ");

  const rows = await all(`
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
    WHERE ${clause}
    ORDER BY w.frequency_rank
    LIMIT ? OFFSET ?`, [...args, Number(limit), Number(offset)]);
  for (const r of rows) {
    r.word_audio = audioUrl(r.word_audio);
    r.sentence_audio = audioUrl(r.sentence_audio);
  }
  const [{ n }] = await all(
    `SELECT COUNT(*) AS n FROM words w WHERE ${clause}`, args);
  send(res, { total: Number(n), words: rows });
}
