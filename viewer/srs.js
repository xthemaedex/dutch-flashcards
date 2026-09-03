/* srs.js — SM-2 spaced repetition + review-queue building + streak/stats.
 *
 * All state is per-device and lives in localStorage — the app makes zero network
 * calls for scheduling, which is what lets it work offline. Card state is keyed
 * by word id; a verb is ONE card (the whole conjugation table), never 42.
 *   dfx-srs-v1     card state   { id: {ef,interval,reps,lapses,due,last,seen,known} }
 *   dfx-streak-v1  activity     { last, current, longest, days:{ "YYYY-MM-DD": n } }
 */
window.SRS = (function () {
  const KEY = "dfx-srs-v1";
  const SKEY = "dfx-streak-v1";
  const DAY = 86400000;
  const LAPSE_MIN = 10 * 60 * 1000; // "Again" resurfaces after ~10 min
  const MATURE_DAYS = 21;           // interval at/above this = "mastered"

  const Q = { again: 0, hard: 3, good: 4, easy: 5 };

  let store = read(KEY, {});
  let streak = normStreak(read(SKEY, {}));

  function read(k, dflt) {
    try { return JSON.parse(localStorage.getItem(k)) || dflt; }
    catch (e) { return dflt; }
  }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function write() { save(KEY, store); }
  function writeStreak() { save(SKEY, streak); }

  function ymd(ts) { return new Date(ts).toLocaleDateString("sv"); } // YYYY-MM-DD, local
  function normStreak(s) {
    return {
      last: s.last || null,
      current: s.current || 0,
      longest: s.longest || 0,
      days: s.days || {},
    };
  }

  function fresh() {
    return { ef: 2.5, interval: 0, reps: 0, lapses: 0, due: 0, last: 0, seen: 0, known: false };
  }
  function get(id) { return store[id] ? Object.assign(fresh(), store[id]) : fresh(); }

  /* ---- streak ---- */
  function recordActivity() {
    const t = ymd(Date.now());
    streak.days[t] = (streak.days[t] || 0) + 1;
    if (streak.last !== t) {
      const yst = ymd(Date.now() - DAY);
      streak.current = streak.last === yst ? streak.current + 1 : 1;
      streak.last = t;
      streak.longest = Math.max(streak.longest, streak.current);
    }
    writeStreak();
  }
  function streakInfo() {
    const t = ymd(Date.now()), yst = ymd(Date.now() - DAY);
    const alive = streak.last === t || streak.last === yst;
    return {
      current: alive ? streak.current : 0,
      longest: streak.longest,
      today: streak.days[t] || 0,
      days: streak.days,
      reviewedToday: streak.last === t,
    };
  }
  /* reviews per day for the last `n` days, oldest first */
  function activity(n) {
    const out = [];
    for (let i = n - 1; i >= 0; i--) {
      const d = ymd(Date.now() - i * DAY);
      out.push({ date: d, count: streak.days[d] || 0 });
    }
    return out;
  }

  /* ---- rating ---- */
  function rate(id, rating) {
    const q = Q[rating];
    const s = get(id);
    const now = Date.now();
    s.seen += 1;
    s.last = now;
    s.known = false;

    if (q < 3) {
      s.reps = 0;
      s.lapses += 1;
      s.interval = 0;
    } else {
      if (s.reps === 0) s.interval = 1;
      else if (s.reps === 1) s.interval = 6;
      else s.interval = Math.round(s.interval * s.ef);
      if (q === Q.hard) s.interval = Math.max(1, Math.round(s.interval * 0.6));
      if (q === Q.easy) s.interval = Math.max(1, Math.round(s.interval * 1.3));
      s.reps += 1;
    }
    s.ef = Math.max(1.3, s.ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)));
    s.due = s.interval === 0 ? now + LAPSE_MIN : now + s.interval * DAY;

    store[id] = s;
    write();
    recordActivity();
    return s;
  }

  /* Skip the grind: mark a card known without reviewing it. */
  function markKnown(id) {
    const s = get(id);
    s.ef = Math.max(s.ef, 2.6);
    s.reps = Math.max(s.reps, 3);
    s.interval = Math.max(s.interval, 60);
    s.seen = Math.max(s.seen, 1);
    s.known = true;
    s.last = Date.now();
    s.due = Date.now() + s.interval * DAY;
    store[id] = s;
    write();
    recordActivity();
    return s;
  }
  function unmarkKnown(id) {
    if (store[id]) { delete store[id]; write(); }
  }

  /* ---- queue ---- */
  function buildQueue(cards, opts) {
    opts = opts || {};
    const newLimit = opts.newLimit == null ? 20 : opts.newLimit;
    const sessionSize = opts.sessionSize == null ? 30 : opts.sessionSize;
    const now = Date.now();
    const due = [], neu = [];
    for (const c of cards) {
      const s = store[c.id];
      if (!s || !s.seen) neu.push(c);
      else if (s.due <= now) due.push(c);
    }
    due.sort(function (a, b) {
      const sa = store[a.id], sb = store[b.id];
      return (sb.lapses - sa.lapses) || (sa.due - sb.due);
    });
    const queue = due.concat(neu.slice(0, newLimit));
    return queue.slice(0, Math.max(sessionSize, 0) || queue.length);
  }

  /* ---- stats ---- */
  function bucket(s, now) {
    if (!s || !s.seen) return "new";
    if (s.known || s.interval >= MATURE_DAYS) return "mastered";
    if (s.interval === 0) return "learning";
    return "progress";                 // young: 1..20 day interval
  }
  function stats(cards) {
    const now = Date.now();
    const b = { new: 0, learning: 0, progress: 0, mastered: 0 };
    let due = 0, seen = 0;
    for (const c of cards) {
      const s = store[c.id];
      b[bucket(s, now)]++;
      if (s && s.seen) { seen++; if (s.due <= now) due++; }
    }
    return {
      total: cards.length, seen: seen, due: due,
      new: b.new, learning: b.learning, progress: b.progress, mastered: b.mastered,
      completion: cards.length ? b.mastered / cards.length : 0,
    };
  }
  /* per-key breakdown, e.g. groupStats(cards, c => c.cefr) */
  function groupStats(cards, keyOf) {
    const out = {};
    for (const c of cards) (out[keyOf(c)] = out[keyOf(c)] || []).push(c);
    const res = {};
    for (const k in out) res[k] = stats(out[k]);
    return res;
  }

  /* difficulty score for the heatmap — higher = weaker (only for seen cards) */
  function difficulty(id) {
    const s = store[id];
    if (!s || !s.seen) return 0;
    return s.lapses * 2 + Math.max(0, 2.5 - s.ef) * 2.5;
  }
  function weakest(cards, n) {
    return cards
      .map((c) => ({ card: c, score: difficulty(c.id) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, n || 40);
  }

  function resetAll() {
    store = {}; streak = normStreak({});
    write(); writeStreak();
  }

  return {
    get: get, rate: rate, markKnown: markKnown, unmarkKnown: unmarkKnown,
    buildQueue: buildQueue, stats: stats, groupStats: groupStats,
    weakest: weakest, difficulty: difficulty,
    streakInfo: streakInfo, activity: activity,
    resetAll: resetAll, LAPSE_MIN: LAPSE_MIN, MATURE_DAYS: MATURE_DAYS,
  };
})();
