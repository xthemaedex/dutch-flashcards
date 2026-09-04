import { all, send, IMAGE_ENABLED } from "./_lib.js";

// Lemmas that have an image (once IMAGE_BASE_URL is set + images are pushed to
// the media branch). Kept as a lean list the SW precaches; the actual image URL
// + attribution ride along in /api/details.
export default async function handler(req, res) {
  if (!IMAGE_ENABLED) return send(res, [], { maxAge: 3600 });
  const rows = await all(
    "SELECT lemma FROM words WHERE image_path IS NOT NULL");
  send(res, rows.map((r) => String(r.lemma).toLowerCase()), { maxAge: 600 });
}
