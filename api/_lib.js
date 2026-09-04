// Shared helpers for the Vercel serverless API. Reads from Turso (libSQL).
// build: audio-enabled
import { createClient } from "@libsql/client";
import { gzipSync } from "node:zlib";

export const db = createClient({
  url: process.env.TURSO_DATABASE_URL,
  authToken: process.env.TURSO_AUTH_TOKEN,
});

export const TENSE_ORDER = [
  "presens", "imperfectum", "perfectum", "plusquamperfectum",
  "futurum", "futurum_exactum", "conditionalis",
];
export const PERSON_ORDER = ["ik", "jij", "hij", "wij", "jullie", "zij_mv"];

// Audio isn't deployed yet. When it is (Cloudflare R2 etc.), set AUDIO_BASE_URL
// and every file_path becomes an absolute URL; until then it's null and the app
// shows the muted icon.
const AUDIO_BASE = process.env.AUDIO_BASE_URL || "";
export const AUDIO_ENABLED = !!AUDIO_BASE;
export function audioUrl(filePath) {
  if (!filePath || !AUDIO_BASE) return null;
  return AUDIO_BASE.replace(/\/$/, "") + "/" + filePath;
}

// Per-word images (Phase 4). Same deal as audio: one-time-fetched files served
// from the jsDelivr media branch (images/<lemma>.jpg on the `audio` branch).
// Set IMAGE_BASE_URL once the images are pushed; until then image is null and
// the card is text-only.
const IMAGE_BASE = process.env.IMAGE_BASE_URL || "";
export const IMAGE_ENABLED = !!IMAGE_BASE;
export function imageUrl(filePath) {
  if (!filePath || !IMAGE_BASE) return null;
  return IMAGE_BASE.replace(/\/$/, "") + "/" + filePath;
}

// JSON response. Gzips large payloads in-function so /api/details (~8 MB raw)
// stays well under Vercel's 4.5 MB response-body limit.
//
// The dataset is static between deploys, so lean HARD on the Vercel edge cache:
// `sMaxAge` (defaults to a day) keeps Turso from being hit more than ~once per
// region per day no matter how often clients revalidate. A content change ships
// via a redeploy, which purges the edge — so staleness is never an issue.
// `maxAge` is the browser's own cache window (kept shorter).
export function send(res, body, { status = 200, maxAge = 300, sMaxAge = 86400 } = {}) {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader(
    "Cache-Control",
    sMaxAge > 0
      ? `public, max-age=${maxAge}, s-maxage=${sMaxAge}, stale-while-revalidate=604800`
      : "public, max-age=0, must-revalidate",
  );
  const json = Buffer.from(JSON.stringify(body));
  if (json.length > 128 * 1024) {
    res.setHeader("Content-Encoding", "gzip");
    res.setHeader("Vary", "Accept-Encoding");
    res.status(status).send(gzipSync(json));
  } else {
    res.status(status).send(json);
  }
}

export async function all(sql, args = []) {
  const r = await db.execute({ sql, args });
  return r.rows;
}
