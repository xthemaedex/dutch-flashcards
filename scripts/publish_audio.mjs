/* publish_audio.mjs — upload locally-generated audio to the Vercel Blob store.
 *
 *   node --env-file=.env.local scripts/publish_audio.mjs
 *
 * Uploads audio/word/*.mp3 and audio/sentence/*.mp3 to blob pathnames that match
 * the DB's file_path ("audio/word/00001.mp3"), so the deployed API just prefixes
 * them with AUDIO_BASE_URL. Idempotent: already-uploaded files are skipped.
 * Re-run any time generate_audio.py has produced more clips.
 */
import { list, put } from "@vercel/blob";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const token = process.env.BLOB_READ_WRITE_TOKEN;
if (!token) { console.error("BLOB_READ_WRITE_TOKEN not set (use --env-file=.env.local)"); process.exit(1); }

const SCOPES = ["word", "sentence", "conjugation"];
const CONCURRENCY = 6;

async function putWithRetry(path, stream, opts, tries = 5) {
  for (let i = 0; ; i++) {
    try { return await put(path, stream, opts); }
    catch (e) {
      const wait = e?.retryAfter ? e.retryAfter * 1000 : 2000 * (i + 1);
      if (i >= tries - 1 || !/rate|Too many/i.test(String(e))) throw e;
      await new Promise((r) => setTimeout(r, wait));
    }
  }
}

async function localFiles() {
  const out = [];
  for (const scope of SCOPES) {
    const dir = join(ROOT, "audio", scope);
    let names;
    try { names = await readdir(dir); } catch { continue; }
    for (const n of names) {
      if (n.endsWith(".mp3")) out.push(`audio/${scope}/${n}`);
    }
  }
  return out;
}

async function alreadyUploaded() {
  const have = new Set();
  let cursor;
  do {
    const res = await list({ token, prefix: "audio/", cursor, limit: 1000 });
    for (const b of res.blobs) have.add(b.pathname);
    cursor = res.cursor;
  } while (cursor);
  return have;
}

async function main() {
  const files = await localFiles();
  const have = await alreadyUploaded();
  const todo = files.filter((f) => !have.has(f));
  console.log(`local: ${files.length}  already in blob: ${have.size}  to upload: ${todo.length}`);
  if (!todo.length) { console.log("nothing to do."); return baseUrlHint(have); }

  let done = 0, base = null;
  const queue = todo.slice();
  async function worker() {
    while (queue.length) {
      const path = queue.shift();
      const body = await readFile(join(ROOT, path));
      const res = await putWithRetry(path, body, {
        access: "public", token, addRandomSuffix: false,
        allowOverwrite: true, contentType: "audio/mpeg",
      });
      if (!base) base = res.url.slice(0, res.url.length - path.length - 1); // strip "/audio/..."
      done++;
      if (done % 100 === 0 || done === todo.length)
        process.stdout.write(`\r  uploaded ${done}/${todo.length}`);
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  process.stdout.write("\n");
  console.log("\nAUDIO_BASE_URL =", base);
  console.log("Set it on Vercel:  vercel env add AUDIO_BASE_URL production");
}

function baseUrlHint(have) {
  const first = [...have][0];
  if (first) console.log("(store already populated — AUDIO_BASE_URL is the blob domain, e.g. https://<id>.public.blob.vercel-storage.com)");
}

main().catch((e) => { console.error(e); process.exit(1); });
