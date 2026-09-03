import { all, send, audioUrl, TENSE_ORDER, PERSON_ORDER } from "../_lib.js";

export default async function handler(req, res) {
  const id = Number(req.query.id);
  const [w] = await all("SELECT * FROM words WHERE id = ?", [id]);
  if (!w) return send(res, { error: "not found" }, { status: 404, maxAge: 0 });

  const out = { ...w };
  out.sentences = await all(
    "SELECT * FROM example_sentences WHERE word_id = ? ORDER BY sort_order", [id]);

  if (w.part_of_speech === "verb") {
    const conj = Object.fromEntries(TENSE_ORDER.map((t) => [t, {}]));
    const cids = Object.fromEntries(TENSE_ORDER.map((t) => [t, {}]));
    for (const r of await all(
        "SELECT id, tense, person, form FROM verb_conjugations WHERE word_id = ?", [id])) {
      conj[r.tense][r.person] = r.form;
      cids[r.tense][r.person] = r.id;
    }
    out.conjugations = conj;
    out.conj_ids = cids;
    out.persons = PERSON_ORDER;
  }

  out.audio = {};
  for (const r of await all(
      `SELECT scope, sentence_id, conjugation_id, file_path
       FROM audio_assets WHERE word_id = ? AND status='done'`, [id])) {
    const key = r.scope === "sentence" ? `sentence:${r.sentence_id}`
      : r.scope === "conjugation" ? `conj:${r.conjugation_id}` : r.scope;
    out.audio[key] = audioUrl(r.file_path);
  }

  send(res, out, { maxAge: 86400 });
}
