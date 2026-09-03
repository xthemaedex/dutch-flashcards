/* migrate_to_turso.mjs — one-time copy of the local SQLite DB into Turso (libSQL).
 *
 *   TURSO_DATABASE_URL=libsql://...  TURSO_AUTH_TOKEN=...  node scripts/migrate_to_turso.mjs
 *
 * Reads db/flashcards.db, applies db/schema.sql to Turso, then copies every row.
 * Idempotent-ish: pass --reset to DROP the tables in Turso first.
 */
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createClient } from "@libsql/client";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const LOCAL_DB = join(ROOT, "db", "flashcards.db");
const SCHEMA = join(ROOT, "db", "schema.sql");

const url = process.env.TURSO_DATABASE_URL;
const authToken = process.env.TURSO_AUTH_TOKEN;
if (!url || !authToken) {
  console.error("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars.");
  process.exit(1);
}
const RESET = process.argv.includes("--reset");

// tables in FK-safe insert order
const TABLES = [
  "word_sets", "words", "word_set_members",
  "example_sentences", "verb_conjugations", "audio_assets",
];

const local = new DatabaseSync(LOCAL_DB, { readOnly: true });
const turso = createClient({ url, authToken });

async function run(sql) { return turso.execute(sql); }

async function applySchema() {
  const text = readFileSync(SCHEMA, "utf8")
    .split("\n")
    .filter((l) => !/^\s*--/.test(l))          // drop full-line comments
    .filter((l) => !/^\s*PRAGMA/i.test(l))      // libsql manages pragmas
    .join("\n");
  const stmts = text
    .split(/;\s*(?:\n|$)/)
    .map((s) => s.trim())
    .filter(Boolean);
  for (const s of stmts) {
    try { await run(s + ";"); }
    catch (e) {
      console.warn("  schema stmt FAILED:", e.message.slice(0, 120));
      console.warn("    >>", s.slice(0, 80).replace(/\s+/g, " "));
    }
  }
}

async function dropAll() {
  await run("PRAGMA foreign_keys=OFF");
  await run("DROP VIEW IF EXISTS v_word_card");
  for (const t of [...TABLES].reverse()) await run(`DROP TABLE IF EXISTS ${t}`);
}

async function copyTable(name) {
  const rows = local.prepare(`SELECT * FROM ${name}`).all();
  if (!rows.length) { console.log(`  ${name}: 0 rows`); return; }
  const cols = Object.keys(rows[0]);
  const placeholders = "(" + cols.map(() => "?").join(",") + ")";
  const sql = `INSERT INTO ${name} (${cols.join(",")}) VALUES ${placeholders}`;

  const CHUNK = 400;
  let done = 0;
  for (let i = 0; i < rows.length; i += CHUNK) {
    const batch = rows.slice(i, i + CHUNK).map((r) => ({
      sql,
      args: cols.map((c) => (r[c] === undefined ? null : r[c])),
    }));
    await turso.batch(batch, "write");
    done += batch.length;
    process.stdout.write(`\r  ${name}: ${done}/${rows.length}`);
  }
  process.stdout.write("\n");
}

async function verify() {
  console.log("\nrow counts (local -> turso):");
  for (const t of TABLES) {
    const l = local.prepare(`SELECT COUNT(*) n FROM ${t}`).get().n;
    const r = (await run(`SELECT COUNT(*) n FROM ${t}`)).rows[0].n;
    const ok = Number(l) === Number(r) ? "OK" : "MISMATCH";
    console.log(`  ${t.padEnd(20)} ${String(l).padStart(7)} -> ${String(r).padStart(7)}  ${ok}`);
  }
}

console.log("Local :", LOCAL_DB);
console.log("Turso :", url, "\n");

if (RESET) { console.log("Dropping existing Turso tables..."); await dropAll(); }
console.log("Applying schema...");
await applySchema();
await run("PRAGMA foreign_keys=OFF");
for (const t of TABLES) {
  console.log(`Copying ${t}...`);
  await copyTable(t);
}
await verify();
console.log("\nDone.");
