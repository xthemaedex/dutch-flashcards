import { all, send } from "./_lib.js";

export default async function handler(req, res) {
  const rows = await all(`
    SELECT ws.id, ws.name, ws.cefr_level, ws.description,
           COUNT(m.word_id) AS word_count
    FROM word_sets ws
    LEFT JOIN word_set_members m ON m.set_id = ws.id
    GROUP BY ws.id ORDER BY ws.sort_order, ws.name
  `);
  send(res, rows, { maxAge: 3600 });
}
