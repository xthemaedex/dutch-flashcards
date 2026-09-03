import { all, send } from "./_lib.js";

export default async function handler(req, res) {
  const [words] = await all("SELECT COUNT(*) AS n FROM words");
  const pos = await all(
    "SELECT part_of_speech AS p, COUNT(*) AS n FROM words GROUP BY part_of_speech");
  const [sent] = await all("SELECT COUNT(*) AS n FROM example_sentences");
  const [conj] = await all("SELECT COUNT(*) AS n FROM verb_conjugations");
  const [ad] = await all("SELECT COUNT(*) AS n FROM audio_assets WHERE status='done'");
  const [at] = await all("SELECT COUNT(*) AS n FROM audio_assets");
  send(res, {
    words: Number(words.n),
    by_pos: Object.fromEntries(pos.map((r) => [r.p, Number(r.n)])),
    sentences: Number(sent.n),
    conjugations: Number(conj.n),
    audio_done: Number(ad.n),
    audio_total: Number(at.n),
  });
}
