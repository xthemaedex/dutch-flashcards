/* publish_audio.mjs — push locally-generated audio to the `audio` branch, which
 * is served by the jsDelivr CDN (https://cdn.jsdelivr.net/gh/<user>/<repo>@audio/).
 *
 *   node scripts/publish_audio.mjs
 *
 * Commits everything under audio/ to the orphan `audio` branch (kept separate so
 * the main branch stays lean), pushes it, and pings jsDelivr to refresh its
 * cache. Idempotent — re-run whenever generate_audio.py has produced more clips.
 */
import { execFileSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const sh = (cmd, args) =>
  execFileSync(cmd, args, { cwd: ROOT, encoding: "utf8" }).trim();

// repo slug from the origin remote
const remote = sh("git", ["remote", "get-url", "origin"]);
const slug = remote.replace(/^git@github\.com:|^https:\/\/github\.com\/|\.git$/g, "");
const CDN = `https://cdn.jsdelivr.net/gh/${slug}@audio`;

const branch = sh("git", ["rev-parse", "--abbrev-ref", "HEAD"]);
if (branch !== "main") {
  console.error(`On branch "${branch}" — run this from main.`);
  process.exit(1);
}
if (sh("git", ["status", "--porcelain"])) {
  console.error("Working tree not clean — commit or stash first.");
  process.exit(1);
}

function count(scope) {
  try { return readdirSync(join(ROOT, "audio", scope)).filter((f) => f.endsWith(".mp3")).length; }
  catch { return 0; }
}
const totals = ["word", "sentence", "conjugation"].map((s) => `${s} ${count(s)}`).join(", ");
console.log("local clips:", totals);

// worktree so we never disturb the checkout on main
const wt = join(ROOT, ".git", "audio-worktree");
try { sh("git", ["worktree", "remove", "--force", wt]); } catch {}
sh("git", ["fetch", "-q", "origin", "audio"]);
sh("git", ["worktree", "add", "-q", wt, "audio"]);
try {
  // mirror local audio/ into the worktree
  execFileSync("rsync", ["-a", "--delete", join(ROOT, "audio") + "/", join(wt, "audio") + "/"],
    { stdio: "inherit" });
  execFileSync("git", ["-C", wt, "add", "-A", "audio"], { stdio: "inherit" });
  const changed = execFileSync("git", ["-C", wt, "status", "--porcelain"], { encoding: "utf8" }).trim();
  if (!changed) { console.log("no new clips to publish."); }
  else {
    execFileSync("git", ["-C", wt, "commit", "-q", "-m", "audio: sync clips"], { stdio: "inherit" });
    execFileSync("git", ["-C", wt, "push", "-q", "origin", "audio"], { stdio: "inherit" });
    console.log("pushed to origin/audio");
  }
} finally {
  sh("git", ["worktree", "remove", "--force", wt]);
}

// nudge jsDelivr to re-pull the branch (best effort)
try {
  await fetch(`https://purge.jsdelivr.net/gh/${slug}@audio/`);
  console.log("jsDelivr purge requested");
} catch {}

console.log("\nAUDIO_BASE_URL =", CDN);
console.log("(already set on Vercel; new clips appear within ~12 h, sooner after a purge)");
