/* app.js — Phase 2: core flashcard review flow (SM-2), plus a light browse/search.
 * Reads the Phase 1 database through serve.py's JSON API. Scheduling state is
 * client-side (see srs.js) so the review loop needs no network once cards load. */
"use strict";

const $ = (s) => document.querySelector(s);
const view = $("#view");
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const api = async (p) => {
  const r = await fetch(p);
  if (!r.ok) throw new Error(p + " -> " + r.status);
  return r.json();
};

/* ---------- theme ---------- */
(function () {
  let t; try { t = localStorage.getItem("dfx-theme"); } catch (e) {}
  if (t) document.documentElement.dataset.theme = t;
  $("#themeBtn").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("dfx-theme", next); } catch (e) {}
  };
})();

/* ---------- settings popover (audio + reminders + install) ---------- */
$("#audioBtn").onclick = () => {
  const open = document.querySelector(".audio-sheet");
  if (open) { open.remove(); return; }
  const el = document.createElement("div");
  el.className = "audio-sheet";
  const notif = "Notification" in window ? Notification.permission : "unsupported";
  el.innerHTML = `
    <div class="lab">Audio</div>
    <label><input type="checkbox" id="_aw" ${AudioPrefs.autoWord ? "checked" : ""}> Auto-play word</label>
    <label><input type="checkbox" id="_as" ${AudioPrefs.autoSentence ? "checked" : ""}> Auto-play sentence on flip</label>
    <div class="en">tap 🔊 on a card to replay · key <b>R</b></div>

    <div class="lab" style="margin-top:10px">Daily reminder</div>
    ${notif === "unsupported"
      ? `<div class="en">Not supported in this browser.</div>`
      : notif === "denied"
      ? `<div class="en">Blocked — enable notifications for this site in browser settings.</div>`
      : `<label><input type="checkbox" id="_rem" ${notif === "granted" && Reminders.on ? "checked" : ""}> Notify me when cards are due</label>
         <button class="linkbtn" id="_test" style="padding:2px 0">Send a test notification</button>`}

    ${InstallPrompt.available ? `<button class="bigbtn" id="_install" style="margin-top:10px;padding:10px 16px;font-size:14px">Install app</button>` : ""}
    <div class="en" style="margin-top:6px">Add to Home Screen for full-screen + offline.</div>`;
  document.body.appendChild(el);
  el.querySelector("#_aw").onchange = (e) => AudioPrefs.set("autoWord", e.target.checked);
  el.querySelector("#_as").onchange = (e) => AudioPrefs.set("autoSentence", e.target.checked);
  const rem = el.querySelector("#_rem");
  if (rem) rem.onchange = (e) => {
    if (e.target.checked) Reminders.enable().then((ok) => { if (!ok) e.target.checked = false; });
    else Reminders.disable();
  };
  const test = el.querySelector("#_test");
  if (test) test.onclick = () => Reminders.test();
  const inst = el.querySelector("#_install");
  if (inst) inst.onclick = () => InstallPrompt.show();
  setTimeout(() => document.addEventListener("click", function h(ev) {
    if (!el.contains(ev.target) && ev.target.id !== "audioBtn") {
      el.remove(); document.removeEventListener("click", h);
    }
  }), 0);
};

/* ---------- audio ----------
 * Everything plays from files cached by Phase 1 (scripts/generate_audio.py).
 * No network calls beyond fetching those static .mp3s. */
const AudioPrefs = {
  s: (() => { try { return JSON.parse(localStorage.getItem("dfx-audio")) || {}; }
              catch (e) { return {}; } })(),
  get autoWord() { return this.s.autoWord !== false; },        // default on
  get autoSentence() { return this.s.autoSentence === true; }, // default off
  set(k, v) {
    this.s[k] = v;
    try { localStorage.setItem("dfx-audio", JSON.stringify(this.s)); } catch (e) {}
  },
};

let AUDIO = new Audio();
let lastPath = null;
let playingBtn = null;
function play(path, btn) {
  if (!path) return;
  lastPath = path;
  if (playingBtn) playingBtn.classList.remove("playing");
  playingBtn = btn || null;
  if (btn) btn.classList.add("playing");
  const clear = () => {
    if (btn) btn.classList.remove("playing");
    if (playingBtn === btn) playingBtn = null;
  };
  try {
    AUDIO.pause();
    AUDIO = new Audio("/" + path);
    AUDIO.addEventListener("ended", clear);
    AUDIO.addEventListener("error", clear);
    AUDIO.play().catch(clear);   // autoplay may be blocked until first gesture
  } catch (e) { clear(); }
}
function replay() { if (lastPath) play(lastPath); }

/* one <button> for present audio, a flat muted glyph when the file isn't made yet */
function audioBtn(path, cls) {
  cls = cls ? " " + cls : "";
  return path
    ? `<button class="audio-btn${cls}" data-a="${path}" aria-label="Play audio">🔊</button>`
    : `<span class="audio-btn muted${cls}" title="Audio not generated yet" aria-hidden="true">🔇</span>`;
}
function wireAudio(root) {
  (root || view).querySelectorAll(".audio-btn[data-a], .conjcell[data-a]").forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); play(b.dataset.a, b); };
  });
}

/* optional per-word image: drop images/<lemma>.jpg and it appears; absent -> nothing.
 * We only emit an <img> for lemmas the server says it has, so no 404 noise. */
let IMAGES = new Set();
fetch("/api/images").then((r) => r.json()).then((a) => { IMAGES = new Set(a); }).catch(() => {});
function wordImage(lemma) {
  const s = String(lemma).toLowerCase();
  return IMAGES.has(s)
    ? `<img class="wordimg" alt="" loading="lazy" src="/img/${encodeURIComponent(s)}" onerror="this.remove()">`
    : "";
}

/* ---------- PWA: service worker, install prompt, daily reminder ---------- */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

const InstallPrompt = {
  deferred: null,
  get available() { return !!this.deferred; },
  show() {
    if (!this.deferred) return;
    this.deferred.prompt();
    this.deferred.userChoice.finally(() => { this.deferred = null; });
  },
};
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  InstallPrompt.deferred = e;
});

/* tiny IndexedDB bridge so the service worker can read the due count */
function idbSet(key, val) {
  return new Promise((res) => {
    const r = indexedDB.open("dfx", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("meta");
    r.onsuccess = () => {
      const tx = r.result.transaction("meta", "readwrite");
      tx.objectStore("meta").put(val, key);
      tx.oncomplete = () => res();
      tx.onerror = () => res();
    };
    r.onerror = () => res();
  });
}
/* recompute "cards due today" and hand it to the SW for the reminder */
function updateDueSummary() {
  if (!CARDS) return;
  const st = SRS.stats(CARDS);
  idbSet("reminder", { due: st.due, updated: Date.now() });
}

const Reminders = {
  get on() { try { return localStorage.getItem("dfx-remind") === "1"; } catch (e) { return false; } },
  set on(v) { try { localStorage.setItem("dfx-remind", v ? "1" : "0"); } catch (e) {} },
  async enable() {
    if (!("Notification" in window)) return false;
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return false;
    this.on = true;
    updateDueSummary();
    // periodic background sync: Chrome/Android, installed PWA only
    try {
      const reg = await navigator.serviceWorker.ready;
      if ("periodicSync" in reg) {
        const status = await navigator.permissions.query({ name: "periodic-background-sync" });
        if (status.state === "granted")
          await reg.periodicSync.register("dutch-daily-reminder", { minInterval: 12 * 3600 * 1000 });
      }
    } catch (e) {}
    return true;
  },
  async disable() {
    this.on = false;
    try {
      const reg = await navigator.serviceWorker.ready;
      if (reg.periodicSync) await reg.periodicSync.unregister("dutch-daily-reminder");
    } catch (e) {}
  },
  async test() {
    if (!("Notification" in window)) { alert("Notifications not supported here."); return; }
    const perm = Notification.permission === "granted"
      ? "granted" : await Notification.requestPermission();
    if (perm !== "granted") return;
    updateDueSummary();
    const reg = await navigator.serviceWorker.ready.catch(() => null);
    if (reg) reg.active && reg.active.postMessage("test-notification");
    else new Notification("Dutch Flashcards", { body: "Reminders are on." });
  },
};

/* ---------- data ---------- */
let CARDS = null;              // compact list of every card (cached)
let BYID = {};
let cardsPromise = null;
let DETAILS = null;            // id -> full card-back detail (one bulk payload)
let detailsPromise = null;
const detailCache = {};

/* pull every card's back-of-card detail in one request; the SW precaches it so
 * the whole flow (definitions, conjugations, sentence audio) works offline. */
function loadDetails() {
  if (DETAILS) return Promise.resolve(DETAILS);
  if (!detailsPromise) {
    detailsPromise = api("/api/details")
      .then((map) => { DETAILS = map; return map; })
      .catch((e) => { detailsPromise = null; throw e; });
  }
  return detailsPromise;
}

async function loadCards() {
  if (CARDS) return CARDS;
  if (!cardsPromise) {
    cardsPromise = api("/api/cards").then((rows) => {
      CARDS = rows;
      rows.forEach((c) => (BYID[c.id] = c));
      updateDueSummary();
      loadDetails().catch(() => {});   // warm the bulk payload in the background
      return CARDS;
    }).catch((e) => {
      cardsPromise = null;        // allow a retry when back online
      throw e;
    });
  }
  return cardsPromise;
}
async function detail(id) {
  if (DETAILS && DETAILS[id]) return DETAILS[id];
  if (detailCache[id]) return detailCache[id];
  try {
    const map = await loadDetails();           // bulk payload (SW-cached offline)
    if (map[id]) return map[id];
  } catch (e) { /* fall through to single fetch */ }
  detailCache[id] = await api("/api/word/" + id);
  return detailCache[id];
}

/* ---------- nav ---------- */
const VALID_TABS = ["review", "browse", "stats", "search"];
let TAB = VALID_TABS.includes(new URLSearchParams(location.search).get("tab"))
  ? new URLSearchParams(location.search).get("tab") : "review";
document.querySelectorAll("nav button").forEach((b) =>
  b.classList.toggle("active", b.dataset.tab === TAB));
document.querySelectorAll("nav button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("nav button").forEach((x) => x.classList.toggle("active", x === b));
    TAB = b.dataset.tab;
    if (TAB !== "review") showBar(false);
    render();
  };
});
function goReview() {
  document.querySelectorAll("nav button").forEach((x) =>
    x.classList.toggle("active", x.dataset.tab === "review"));
  TAB = "review";
  render();
}

function showBar(on) { $("#sessionbar").hidden = !on; }
function setBar(frac) { $("#sessionfill").style.width = Math.round(frac * 100) + "%"; }

function refreshStreakChip() {
  const sk = SRS.streakInfo();
  const chip = $("#streakChip");
  if (sk.current > 0) {
    chip.hidden = false;
    chip.textContent = "🔥 " + sk.current;
    chip.classList.toggle("today", sk.reviewedToday);
  } else {
    chip.hidden = true;
  }
  chip.onclick = () => {
    document.querySelectorAll("nav button").forEach((x) =>
      x.classList.toggle("active", x.dataset.tab === "stats"));
    TAB = "stats"; render();
  };
}

async function render() {
  try {
    if (!CARDS) view.innerHTML = `<div class="empty">Loading cards…</div>`;
    if (TAB === "browse") return renderBrowse();
    if (TAB === "search") return renderSearch();
    if (TAB === "stats") return renderStats();
    return renderReview();
  } catch (e) {
    const offline = !navigator.onLine || /Failed to fetch|NetworkError/i.test(String(e));
    view.innerHTML = offline
      ? `<div class="empty"><div class="big">📡</div>
          You're offline and the word list hasn't been saved to this device yet.<br><br>
          Connect once so the app can finish setting up, then it works offline.
          <br><br><button class="bigbtn" id="retry">Try again</button></div>`
      : `<div class="empty">Error: ${esc(String(e))}<br><br>
          Is the server running? <code>python3 scripts/serve.py</code></div>`;
    const rb = document.getElementById("retry");
    if (rb) rb.onclick = () => render();
  }
}

window.addEventListener("online", () => { if (!CARDS) render(); });

/* =====================================================================
 *  REVIEW  (SM-2)
 * ===================================================================== */
const SESSION = {
  active: false, queue: [], pos: 0, total: 0,
  graduated: new Set(), tally: { again: 0, hard: 0, good: 0, easy: 0 },
  flipped: false, scope: "all", scopeName: "All sets",
};

async function renderReview() {
  await loadCards();
  if (SESSION.active) return renderCard();
  return renderStart();
}

function poolForScope() {
  if (SESSION.scope === "all") return CARDS;
  return CARDS.filter((c) => c.cefr === SESSION.scope);
}

function renderStart() {
  showBar(false);
  const levels = ["A1", "A2", "B1", "B2"];
  const st = SRS.stats(poolForScope());
  view.innerHTML = `
    <div class="hero">
      <div class="big">🎯</div>
      <h2>Ready to review</h2>
      <p>${SESSION.scopeName}</p>
      <div class="dueline">
        <span class="pill"><b>${st.due}</b> due</span>
        <span class="pill"><b>${st.new}</b> new</span>
        <span class="pill">${st.mastered} mastered</span>
      </div>
      <button class="bigbtn" id="start">${st.due + st.new === 0 ? "Study ahead" : "Start review"}</button>
      <div style="margin-top:22px">
        <div class="en" style="margin-bottom:8px">Focus a level:</div>
        <div class="dueline">
          <button class="pill" data-scope="all">All</button>
          ${levels.map((l) => `<button class="pill" data-scope="${l}">${l}</button>`).join("")}
        </div>
      </div>
      ${InstallPrompt.available
        ? `<div style="margin-top:18px"><button class="bigbtn" id="installNudge"
             style="padding:11px 20px;font-size:14px">📲 Install app</button></div>` : ""}
      <button class="linkbtn" id="resetSrs">Reset all progress</button>
    </div>`;
  $("#start").onclick = () => startSession();
  if ($("#installNudge")) $("#installNudge").onclick = () => InstallPrompt.show();
  view.querySelectorAll("[data-scope]").forEach((b) => {
    b.onclick = () => {
      SESSION.scope = b.dataset.scope;
      SESSION.scopeName = b.dataset.scope === "all" ? "All sets" : "Level " + b.dataset.scope;
      renderStart();
    };
  });
  $("#resetSrs").onclick = () => {
    if (confirm("Erase all review history on this device?")) { SRS.resetAll(); renderStart(); }
  };
}

function startSession() {
  const pool = poolForScope();
  const queue = SRS.buildQueue(pool, { sessionSize: 30, newLimit: 20 });
  if (!queue.length) { renderCaughtUp(); return; }
  SESSION.active = true;
  SESSION.queue = queue.slice();
  SESSION.pos = 0;
  SESSION.total = queue.length;
  SESSION.graduated = new Set();
  SESSION.tally = { again: 0, hard: 0, good: 0, easy: 0 };
  SESSION.flipped = false;
  showBar(true);
  renderCard();
}

function endSession() {
  SESSION.active = false;
  showBar(false);
}

async function renderCard() {
  // skip anything already graduated (can happen after an "again" re-queue)
  while (SESSION.pos < SESSION.queue.length &&
         SESSION.graduated.has(SESSION.queue[SESSION.pos].id)) SESSION.pos++;
  if (SESSION.pos >= SESSION.queue.length) return renderComplete();

  const card = SESSION.queue[SESSION.pos];
  setBar(SESSION.graduated.size / SESSION.total);

  const tag = card.article
    ? `<span class="tag ${card.article}">${card.article}</span>`
    : `<span class="tag pos">${esc(card.pos)}</span>`;
  const cloze = card.sentence_blanked
    ? esc(card.sentence_blanked).replace("___", "<b>______</b>")
    : (card.sentence_nl ? esc(card.sentence_nl) : `<span class="en">no example sentence</span>`);

  let body;
  if (!SESSION.flipped) {
    body = `
      ${tag}
      <div class="word">${esc(card.lemma)}</div>
      <div class="row" style="margin:2px 0 4px">
        ${audioBtn(card.word_audio)}
        <span class="en">${card.word_audio ? "hear the word" : "audio pending"}</span>
      </div>
      ${wordImage(card.lemma)}
      <div class="cloze">${cloze}</div>
      <div class="hint">tap card, or swipe → knew&nbsp;it / ← didn't</div>`;
  } else {
    const d = await detail(card.id);
    body = tag + cardBack(card, d);
    prefetchNext();
  }

  view.innerHTML = `
    <div class="review-head">
      <span>card <b>${Math.min(SESSION.graduated.size + 1, SESSION.total)}</b> / ${SESSION.total}</span>
      <span>ease ${SRS.get(card.id).ef.toFixed(2)} · seen ${SRS.get(card.id).seen}×</span>
    </div>
    <div class="swipe-area">
      <div class="rcard" id="rcard">
        <div class="swipe-flag know">KNEW IT</div>
        <div class="swipe-flag dont">AGAIN</div>
        ${body}
      </div>
    </div>
    ${SESSION.flipped ? ratingRow() : `<button class="flip-cta" id="flip">Show answer</button>`}
    <div class="cardtools">
      <button class="linkbtn" id="known">✓ I already know this</button>
      <button class="linkbtn" id="quit">End session</button>
    </div>`;

  wireCard(card);
  wireAudio();

  // auto-play (best effort; browsers may block until the first user gesture)
  if (!SESSION.flipped) {
    if (AudioPrefs.autoWord && card.word_audio)
      play(card.word_audio, view.querySelector(".audio-btn[data-a]"));
  } else if (AudioPrefs.autoSentence) {
    const sb = view.querySelector(".sentence-full .audio-btn[data-a]");
    if (sb) play(sb.dataset.a, sb);
  }
}

function cardBack(card, d) {
  const badges = [
    card.cefr && `<span class="badge">${card.cefr}</span>`,
    card.rank && `<span class="badge">#${card.rank}</span>`,
    d.is_irregular ? `<span class="badge irr">irregular</span>` : "",
    d.is_separable ? `<span class="badge sep">separable</span>` : "",
    d.plural ? `<span class="badge">pl. ${esc(d.plural)}</span>` : "",
    d.auxiliary ? `<span class="badge">aux ${d.auxiliary}</span>` : "",
  ].filter(Boolean).join("");

  const s0 = d.sentences && d.sentences[0];
  const sentAudio = s0 && d.audio ? d.audio["sentence:" + s0.id] : null;

  let conj = "";
  if (card.pos === "verb" && d.conjugations) {
    const P = d.persons;
    const lab = { ik: "ik", jij: "jij", hij: "hij/zij/het", wij: "wij", jullie: "jullie", zij_mv: "zij (mv)" };
    const ids = d.conj_ids || {};
    const cell = (t, p, f) => {
      const form = esc(f[p] || "");
      if (!form) return "<td></td>";
      const cid = ids[t] && ids[t][p];
      const ap = cid != null && d.audio ? d.audio["conj:" + cid] : null;
      return ap
        ? `<td><button class="conjcell" data-a="${ap}">${form}<span>🔊</span></button></td>`
        : `<td>${form}</td>`;
    };
    conj = `<div class="conj"><table><thead><tr><th>tense</th>${
      P.map((p) => `<th>${lab[p]}</th>`).join("")}</tr></thead><tbody>${
      Object.entries(d.conjugations).map(([t, f]) =>
        `<tr><td>${t}</td>${P.map((p) => cell(t, p, f)).join("")}</tr>`).join("")
    }</tbody></table></div>`;
  }

  return `
    <div class="translation">${esc(d.translation_en)}</div>
    ${d.definition_nl ? `<div class="defblock"><div class="lab">definitie (NL)</div>${esc(d.definition_nl)}</div>` : ""}
    ${d.definition_en && d.definition_en !== d.translation_en
      ? `<div class="defblock"><div class="lab">definition (EN)</div>${esc(d.definition_en)}</div>` : ""}
    ${s0 ? `<div class="sentence-full"><div class="row">
        ${audioBtn(sentAudio)}
        <div>${esc(s0.sentence_nl)}<div class="en">${esc(s0.sentence_en)}</div></div></div></div>` : ""}
    <div class="badges">${badges}</div>
    ${conj}`;
}

function ratingRow() {
  const g = SRS.get(SESSION.queue[SESSION.pos].id);
  // rough "next due" preview
  return `<div class="ratings">
    <button class="again" data-r="again">Again<small>&lt;10 min</small></button>
    <button class="hard" data-r="hard">Hard<small>soon</small></button>
    <button class="good" data-r="good">Good<small>${g.reps === 0 ? "1 d" : g.reps === 1 ? "6 d" : Math.round(g.interval * g.ef) + " d"}</small></button>
    <button class="easy" data-r="easy">Easy<small>longer</small></button>
  </div>`;
}

function wireCard(card) {
  const rcard = $("#rcard");
  const flip = () => { SESSION.flipped = !SESSION.flipped; renderCard(); };

  if ($("#flip")) $("#flip").onclick = flip;
  if ($("#quit")) $("#quit").onclick = () => { endSession(); renderStart(); };
  if ($("#known")) $("#known").onclick = () => {
    SRS.markKnown(card.id);
    refreshStreakChip();
    updateDueSummary();
    SESSION.graduated.add(card.id);
    SESSION.pos++;
    SESSION.flipped = false;
    renderCard();
  };
  view.querySelectorAll(".ratings button").forEach((b) =>
    (b.onclick = () => applyRating(b.dataset.r)));

  // tap to flip
  rcard.addEventListener("click", (e) => {
    if (e.target.closest(".audio-btn,.conjcell,.ratings,button")) return;
    if (Math.abs(drag.dx) > 6) return;   // was a swipe, not a tap
    flip();
  });

  // swipe
  const drag = { on: false, x0: 0, y0: 0, dx: 0 };
  const flags = {
    know: rcard.querySelector(".swipe-flag.know"),
    dont: rcard.querySelector(".swipe-flag.dont"),
  };
  rcard.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".audio-btn,.conjcell,.ratings")) return;
    drag.on = true; drag.x0 = e.clientX; drag.y0 = e.clientY; drag.dx = 0;
    rcard.classList.remove("anim");
    try { rcard.setPointerCapture(e.pointerId); } catch (x) {}
  });
  rcard.addEventListener("pointermove", (e) => {
    if (!drag.on) return;
    drag.dx = e.clientX - drag.x0;
    const dy = e.clientY - drag.y0;
    if (Math.abs(dy) > Math.abs(drag.dx) && Math.abs(drag.dx) < 12) return;
    rcard.style.transform = `translateX(${drag.dx}px) rotate(${drag.dx / 22}deg)`;
    flags.know.style.opacity = drag.dx > 40 ? Math.min(1, (drag.dx - 40) / 70) : 0;
    flags.dont.style.opacity = drag.dx < -40 ? Math.min(1, (-drag.dx - 40) / 70) : 0;
  });
  const finish = () => {
    if (!drag.on) return;
    drag.on = false;
    const TH = 95;
    if (drag.dx > TH) return swipeAway(1);
    if (drag.dx < -TH) return swipeAway(-1);
    rcard.classList.add("anim");
    rcard.style.transform = "";
    flags.know.style.opacity = flags.dont.style.opacity = 0;
  };
  rcard.addEventListener("pointerup", finish);
  rcard.addEventListener("pointercancel", finish);

  function swipeAway(dir) {
    rcard.classList.add("anim");
    rcard.style.transform = `translateX(${dir * 640}px) rotate(${dir * 18}deg)`;
    rcard.style.opacity = "0";
    setTimeout(() => applyRating(dir > 0 ? "good" : "again"), 180);
  }
}

function applyRating(rating) {
  const card = SESSION.queue[SESSION.pos];
  SRS.rate(card.id, rating);
  refreshStreakChip();
  updateDueSummary();
  SESSION.tally[rating]++;
  if (rating === "again") {
    const at = Math.min(SESSION.pos + 3 + Math.floor(Math.random() * 3), SESSION.queue.length);
    SESSION.queue.splice(at, 0, card);
  } else {
    SESSION.graduated.add(card.id);
  }
  SESSION.pos++;
  SESSION.flipped = false;
  renderCard();
}

function prefetchNext() {
  const nx = SESSION.queue[SESSION.pos + 1];
  if (nx) detail(nx.id).catch(() => {});
}

function renderComplete() {
  endSession();
  const t = SESSION.tally;
  const n = t.again + t.hard + t.good + t.easy;
  const acc = n ? Math.round(((t.good + t.easy + t.hard) / n) * 100) : 0;
  view.innerHTML = `
    <div class="hero">
      <div class="big">✅</div>
      <h2>Session complete</h2>
      <p>${SESSION.graduated.size} cards reviewed · ${acc}% knew it</p>
      <div class="dueline">
        <span class="pill">Again <b>${t.again}</b></span>
        <span class="pill">Hard <b>${t.hard}</b></span>
        <span class="pill">Good <b>${t.good}</b></span>
        <span class="pill">Easy <b>${t.easy}</b></span>
      </div>
      <button class="bigbtn" id="again">Another session</button>
    </div>`;
  $("#again").onclick = () => renderStart();
}

function renderCaughtUp() {
  view.innerHTML = `
    <div class="hero">
      <div class="big">🌤️</div>
      <h2>You're all caught up</h2>
      <p>Nothing due in ${esc(SESSION.scopeName.toLowerCase())} right now.</p>
      <button class="bigbtn" id="ahead">Study ahead anyway</button>
      <button class="linkbtn" id="back2">Back</button>
    </div>`;
  $("#ahead").onclick = () => {
    const pool = poolForScope();
    // force some new cards even if none "due"
    const q = SRS.buildQueue(pool, { sessionSize: 20, newLimit: 20 });
    if (!q.length) { alert("This level has no unseen cards left."); return; }
    SESSION.active = true; SESSION.queue = q; SESSION.pos = 0; SESSION.total = q.length;
    SESSION.graduated = new Set(); SESSION.tally = { again: 0, hard: 0, good: 0, easy: 0 };
    SESSION.flipped = false; showBar(true); renderCard();
  };
  $("#back2").onclick = () => renderStart();
}

/* =====================================================================
 *  BROWSE  (read-only flip-through, no scheduling)
 * ===================================================================== */
const BR = { setId: null, words: [], idx: 0, flipped: false };

async function renderBrowse() {
  if (BR.setId) return renderBrowseCard();
  const sets = await api("/api/sets");
  view.innerHTML = `<div class="setgrid">${sets.map((s) => `
    <button class="setcard" data-set="${s.id}">
      <span class="lvl">${esc(s.cefr_level || "·")}</span>
      <span class="meta"><b>${esc(s.name)}</b><span>${s.word_count} words</span></span>
      <span class="chev">›</span></button>`).join("")}</div>`;
  view.querySelectorAll(".setcard").forEach((el) => {
    el.onclick = async () => {
      BR.setId = el.dataset.set; BR.idx = 0; BR.flipped = false;
      view.innerHTML = `<div class="empty">Loading…</div>`;
      const d = await api("/api/words?limit=8000&set=" + BR.setId);
      BR.words = d.words;
      renderBrowseCard();
    };
  });
}

async function renderBrowseCard() {
  const w = BR.words[BR.idx];
  const d = await detail(w.id);
  const compat = {
    id: w.id, lemma: w.lemma, pos: w.part_of_speech, article: w.article,
    cefr: w.cefr_level, rank: w.frequency_rank,
    sentence_blanked: w.sentence_blanked, sentence_nl: w.sentence_nl,
    word_audio: w.word_audio,
  };
  const tag = w.article ? `<span class="tag ${w.article}">${w.article}</span>`
    : `<span class="tag pos">${esc(w.part_of_speech)}</span>`;
  view.innerHTML = `
    <div class="crumbs"><button id="bBack">Sets</button><span>›</span>
      <span>${BR.idx + 1} / ${BR.words.length}</span></div>
    <div class="rcard">
      ${BR.flipped ? tag + cardBack(compat, d)
        : `${tag}<div class="word">${esc(w.lemma)}</div>
           <div class="row" style="margin:2px 0 4px">
             ${audioBtn(w.word_audio)}
             <span class="en">${w.word_audio ? "hear the word" : "audio pending"}</span></div>
           ${wordImage(w.lemma)}
           <div class="cloze">${w.sentence_blanked
              ? esc(w.sentence_blanked).replace("___", "<b>______</b>")
              : esc(w.sentence_nl || "")}</div>
           <div class="hint">tap to flip</div>`}
    </div>
    <div class="navbtns">
      <button id="bPrev" ${BR.idx === 0 ? "disabled" : ""}>‹ Prev</button>
      <button id="bFlip">${BR.flipped ? "Front" : "Flip"}</button>
      <button id="bNext" ${BR.idx >= BR.words.length - 1 ? "disabled" : ""}>Next ›</button>
    </div>
    <div class="cardtools">
      <button class="linkbtn" id="bKnown">${SRS.get(w.id).known ? "✓ known — undo" : "Mark as known"}</button>
    </div>`;
  wireAudio();
  $(".rcard").onclick = (e) => { if (e.target.closest(".audio-btn,.conjcell")) return; BR.flipped = !BR.flipped; renderBrowseCard(); };
  $("#bFlip").onclick = () => { BR.flipped = !BR.flipped; renderBrowseCard(); };
  $("#bBack").onclick = () => { BR.setId = null; renderBrowse(); };
  $("#bPrev").onclick = () => { if (BR.idx > 0) { BR.idx--; BR.flipped = false; renderBrowseCard(); } };
  $("#bNext").onclick = () => { if (BR.idx < BR.words.length - 1) { BR.idx++; BR.flipped = false; renderBrowseCard(); } };
  $("#bKnown").onclick = () => {
    SRS.get(w.id).known ? SRS.unmarkKnown(w.id) : SRS.markKnown(w.id);
    refreshStreakChip();
    renderBrowseCard();
  };
}

/* =====================================================================
 *  SEARCH
 * ===================================================================== */
let searchT;
function renderSearch() {
  view.innerHTML = `<input class="search-in" id="sIn" placeholder="Search Dutch or English…" autocomplete="off"><div id="hits"></div>`;
  const inp = $("#sIn"); inp.focus();
  inp.oninput = () => {
    clearTimeout(searchT);
    searchT = setTimeout(async () => {
      const q = inp.value.trim();
      if (q.length < 2) { $("#hits").innerHTML = ""; return; }
      const d = await api("/api/words?limit=60&q=" + encodeURIComponent(q));
      $("#hits").innerHTML = d.words.map((w) => `
        <button class="hit" data-id="${w.id}">
          ${w.article ? `<span class="tag ${w.article}">${w.article}</span>`
            : `<span class="tag pos">${esc(w.part_of_speech)}</span>`}
          <b>${esc(w.lemma)}</b><span class="tr">${esc(w.translation_en)}</span>
          <span class="mini">#${w.frequency_rank}</span></button>`).join("")
        || `<div class="empty">no matches</div>`;
      $("#hits").querySelectorAll(".hit").forEach((el) => {
        el.onclick = async () => {
          BR.words = d.words; BR.idx = d.words.findIndex((x) => x.id == el.dataset.id);
          BR.setId = "search"; BR.flipped = false;
          document.querySelectorAll("nav button").forEach((x) =>
            x.classList.toggle("active", x.dataset.tab === "browse"));
          TAB = "browse";
          renderBrowseCard();
        };
      });
    }, 170);
  };
}

/* =====================================================================
 *  STATS  (streak · per-set completion · difficulty heatmap · activity)
 * ===================================================================== */
async function renderStats() {
  await loadCards();
  const st = SRS.stats(CARDS);
  const sk = SRS.streakInfo();
  const bars = (s) => `<div class="cov">
      <div style="flex:${s.mastered};background:var(--feather)"></div>
      <div style="flex:${s.progress};background:var(--mask)"></div>
      <div style="flex:${s.learning};background:var(--bee)"></div>
      <div style="flex:${s.new};background:var(--surface)"></div>
    </div>`;

  // per level (our sets are the 4 CEFR bands)
  const byLvl = SRS.groupStats(CARDS, (c) => c.cefr || "?");
  const levelRows = ["A1", "A2", "B1", "B2"].filter((l) => byLvl[l]).map((l) => {
    const s = byLvl[l];
    return `<div class="lvlrow">
      <span class="lvl sm">${l}</span>
      <div class="lvlbody">
        <div class="lvlnums"><b>${Math.round(s.completion * 100)}%</b>
          <span>${s.mastered}/${s.total} mastered · ${s.due} due</span></div>
        ${bars(s)}
      </div></div>`;
  }).join("");

  // difficulty heatmap — weakest seen cards, terracotta scale
  const weak = SRS.weakest(CARDS, 42);
  const maxScore = weak.length ? weak[0].score : 1;
  const heat = weak.length
    ? `<div class="heat">${weak.map(({ card, score }) => {
        const t = Math.min(1, score / maxScore);            // 0..1
        return `<button class="tile" data-id="${card.id}"
          style="--h:${t}" title="${esc(card.lemma)} — ${esc(card.translation_en || "")}">
          ${esc(card.lemma)}</button>`;
      }).join("")}</div>`
    : `<p class="en">No weak spots yet — they show up here once you've missed a few.</p>`;

  // last 14 days of activity
  const act = SRS.activity(14);
  const actMax = Math.max(1, ...act.map((d) => d.count));
  const spark = `<div class="spark">${act.map((d) => `
    <span title="${d.date}: ${d.count}" style="height:${Math.max(6, (d.count / actMax) * 40)}px;
      background:${d.count ? "var(--feather)" : "var(--surface)"}"></span>`).join("")}</div>`;

  view.innerHTML = `
    <div class="streakrow">
      <div class="flame">🔥<b>${sk.current}</b></div>
      <div>
        <div style="font-weight:800">${sk.current === 1 ? "1 day" : sk.current + " days"} streak</div>
        <div class="en">longest ${sk.longest} · ${sk.today} reviewed today</div>
      </div>
    </div>
    ${spark}

    <div class="statgrid" style="margin-top:18px">
      <div class="statbox"><b>${st.mastered}</b><span>words mastered</span></div>
      <div class="statbox"><b>${st.progress + st.learning}</b><span>in progress</span></div>
      <div class="statbox"><b>${st.due}</b><span>due now</span></div>
      <div class="statbox"><b>${st.new.toLocaleString()}</b><span>not started</span></div>
    </div>

    <h3 class="sec">Completion by level</h3>
    ${levelRows}

    <h3 class="sec">Difficulty heatmap <span class="en">— your weakest words</span></h3>
    ${heat}

    <p class="en" style="margin-top:18px">Tap a tile to open that card.
      Dark mode: the ◐ button, top right.</p>`;

  view.querySelectorAll(".tile").forEach((el) => {
    el.onclick = () => openCardById(+el.dataset.id);
  });
}

/* jump to a single card in Browse mode */
async function openCardById(id) {
  const c = BYID[id];
  if (!c) return;
  const d = await api("/api/words?limit=1&q=" + encodeURIComponent(c.lemma));
  BR.words = d.words.length ? d.words : [{
    id: c.id, lemma: c.lemma, part_of_speech: c.pos, article: c.article,
    cefr_level: c.cefr, frequency_rank: c.rank, translation_en: c.translation_en,
    sentence_nl: c.sentence_nl, sentence_blanked: c.sentence_blanked,
    word_audio: c.word_audio,
  }];
  BR.idx = Math.max(0, BR.words.findIndex((w) => w.id === id));
  BR.setId = "single"; BR.flipped = true;
  document.querySelectorAll("nav button").forEach((x) =>
    x.classList.toggle("active", x.dataset.tab === "browse"));
  TAB = "browse";
  renderBrowseCard();
}

/* ---------- keyboard (desktop convenience) ---------- */
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "r" || e.key === "R") { replay(); return; }
  if (TAB !== "review" || !SESSION.active) return;
  if (e.key === " " || e.key === "Enter") { e.preventDefault();
    if (!SESSION.flipped) { SESSION.flipped = true; renderCard(); } }
  else if (SESSION.flipped && ["1", "2", "3", "4"].includes(e.key))
    applyRating(["again", "hard", "good", "easy"][+e.key - 1]);
});

/* ---------- boot ---------- */
refreshStreakChip();
loadCards().then((c) => {
  $("#hdrStat").textContent = c.length.toLocaleString() + " cards";
}).catch(() => {});
render();
