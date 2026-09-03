import { all, send, audioUrl, AUDIO_ENABLED } from "./_lib.js";

export default async function handler(req, res) {
  // audio joins are skipped until audio hosting is configured (AUDIO_BASE_URL)
  const audioSel = AUDIO_ENABLED
    ? `aw.file_path AS word_audio, asx.file_path AS sentence_audio,`
    : `NULL AS word_audio, NULL AS sentence_audio,`;
  const audioJoin = AUDIO_ENABLED
    ? `LEFT JOIN audio_assets aw  ON aw.scope='word' AND aw.word_id=w.id AND aw.status='done'
       LEFT JOIN audio_assets asx ON asx.scope='sentence' AND asx.sentence_id=s.id AND asx.status='done'`
    : ``;

  const rows = await all(`
    SELECT w.id, w.lemma, w.part_of_speech AS pos, w.article, w.gender,
           w.cefr_level AS cefr, w.frequency_rank AS rank, w.translation_en,
           s.sentence_nl, s.sentence_blanked,
           ${audioSel}
           (w.part_of_speech = 'verb') AS is_verb
    FROM words w
    LEFT JOIN example_sentences s ON s.word_id = w.id AND s.sort_order = 0
    ${audioJoin}
    ORDER BY w.frequency_rank
  `);
  if (AUDIO_ENABLED) {
    for (const r of rows) {
      r.word_audio = audioUrl(r.word_audio);
      r.sentence_audio = audioUrl(r.sentence_audio);
    }
  }
  send(res, rows, { maxAge: 3600 });
}
