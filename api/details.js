import { all, send, audioUrl, AUDIO_ENABLED, TENSE_ORDER, PERSON_ORDER } from "./_lib.js";

// Every card's back-of-card detail in one payload — the service worker precaches
// this so the whole review flow works offline, not just card fronts.
export default async function handler(req, res) {
  const out = {};

  for (const w of await all(`
      SELECT id, translation_en, definition_nl, definition_en, article, gender,
             plural, auxiliary, past_participle, is_separable, is_irregular,
             part_of_speech
      FROM words`)) {
    out[w.id] = {
      translation_en: w.translation_en,
      definition_nl: w.definition_nl,
      definition_en: w.definition_en,
      article: w.article, gender: w.gender, plural: w.plural,
      auxiliary: w.auxiliary, past_participle: w.past_participle,
      is_separable: w.is_separable, is_irregular: w.is_irregular,
      part_of_speech: w.part_of_speech,
      sentences: [], audio: {},
    };
  }

  for (const r of await all(
      "SELECT * FROM example_sentences ORDER BY word_id, sort_order")) {
    const d = out[r.word_id];
    if (d) d.sentences.push(r);
  }

  for (const r of await all(
      "SELECT word_id, id, tense, person, form FROM verb_conjugations")) {
    const d = out[r.word_id];
    if (!d) continue;
    if (!d.conjugations) {
      d.conjugations = Object.fromEntries(TENSE_ORDER.map((t) => [t, {}]));
      d.conj_ids = Object.fromEntries(TENSE_ORDER.map((t) => [t, {}]));
      d.persons = PERSON_ORDER;
    }
    d.conjugations[r.tense][r.person] = r.form;
    d.conj_ids[r.tense][r.person] = r.id;
  }

  if (AUDIO_ENABLED) {
    for (const r of await all(
        `SELECT word_id, scope, sentence_id, conjugation_id, file_path
         FROM audio_assets WHERE status='done'`)) {
      const d = out[r.word_id];
      if (!d) continue;
      const key = r.scope === "sentence" ? `sentence:${r.sentence_id}`
        : r.scope === "conjugation" ? `conj:${r.conjugation_id}` : r.scope;
      d.audio[key] = audioUrl(r.file_path);
    }
  }

  send(res, out, { maxAge: 120 });
}
