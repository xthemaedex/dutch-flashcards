/* push_images_to_turso.mjs — add per-word image data to the deployed Turso DB
 * WITHOUT touching any other table.
 *
 *   node --env-file=.env scripts/push_images_to_turso.mjs [--json data/corpus_words.json] [--dry-run]
 *
 * Why a dedicated script (not migrate_to_turso.mjs --only words): `--only words`
 * does DELETE FROM words, which cascade-deletes example_sentences,
 * verb_conjugations AND audio_assets in Turso. This script only ALTERs in the
 * new columns and UPDATEs the matching rows, keyed by (lemma, part_of_speech) —
 * the table's UNIQUE key — so nothing else is disturbed.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createClient } from "@libsql/client";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const DRY = args.includes("--dry-run");
const jsonIdx = args.indexOf("--json");
const JSON_PATH = join(ROOT, jsonIdx !== -1 ? args[jsonIdx + 1] : "data/corpus_words.json");

const url = process.env.TURSO_DATABASE_URL;
const authToken = process.env.TURSO_AUTH_TOKEN;
if (!url || !authToken) {
  console.error("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN (e.g. node --env-file=.env ...).");
  process.exit(1);
}
const turso = createClient({ url, authToken });

const IMAGE_COLS = [
  ["image_path", "TEXT"],
  ["image_source", "TEXT"],
  ["image_attribution", "TEXT"],
  ["image_source_url", "TEXT"],
  ["image_license", "TEXT"],
];

async function ensureColumns() {
  const info = (await turso.execute("PRAGMA table_info(words)")).rows.map((r) => r.name);
  for (const [col, type] of IMAGE_COLS) {
    if (info.includes(col)) { console.log(`  column ${col} already present`); continue; }
    if (DRY) { console.log(`  would ADD COLUMN ${col} ${type}`); continue; }
    await turso.execute(`ALTER TABLE words ADD COLUMN ${col} ${type}`);
    console.log(`  added column ${col}`);
  }
}

const data = JSON.parse(readFileSync(JSON_PATH, "utf8"));
const withImg = data.words.filter((w) => (w.image || {}).path);
console.log(`Source : ${JSON_PATH}`);
console.log(`Turso  : ${url}`);
console.log(`Words with an image: ${withImg.length}\n`);

console.log("Ensuring columns...");
await ensureColumns();

if (DRY) {
  console.log(`\n[dry-run] would UPDATE ${withImg.length} rows. Sample:`);
  for (const w of withImg.slice(0, 5)) console.log(`  ${w.lemma} (${w.part_of_speech}) -> ${w.image.path}`);
  process.exit(0);
}

const sql = `UPDATE words SET image_path=?, image_source=?, image_attribution=?,
             image_source_url=?, image_license=?
             WHERE lemma=? AND part_of_speech=?`;
const CHUNK = 400;
let done = 0;
for (let i = 0; i < withImg.length; i += CHUNK) {
  const batch = withImg.slice(i, i + CHUNK).map((w) => ({
    sql,
    args: [
      w.image.path, w.image.source || "openverse", w.image.attribution || null,
      w.image.source_url || null, w.image.license || null,
      w.lemma, w.part_of_speech,
    ],
  }));
  await turso.batch(batch, "write");
  done += batch.length;
  process.stdout.write(`\r  updated ${done}/${withImg.length}`);
}
process.stdout.write("\n");

const n = (await turso.execute(
  "SELECT COUNT(*) n FROM words WHERE image_path IS NOT NULL")).rows[0].n;
console.log(`\nTurso now has ${n} words with image_path set. Done.`);
console.log("Next: set IMAGE_BASE_URL on Vercel + redeploy so /api/details serves them.");
