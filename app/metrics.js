// JS port of src/pears/metrics.py. Same definitions as METRICS.md.
// Inlined into app/index.html at build time; also loaded by tests/parity.mjs.
// A listen's artists are a credit: a non-empty array of artist keys, first-credited
// first. Each credited artist gets weight 1/credit.length; a guess is a hit if it is
// in the credit.
const PEARS = (() => {
  const MIN_TEST = 100, MIN_MONTH_LISTENS = 20, SESSION_GAP = 1800;
  const BASELINES = ["repeat_last", "most_frequent", "markov1", "time_of_day"];
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

  function ranked(counter, k) {
    return [...counter.entries()]
      .sort((x, y) => y[1] - x[1] || cmp(x[0], y[0]))
      .slice(0, k).map((e) => e[0]);
  }
  function fill(first, fallback, k) {
    const out = first.slice();
    for (const a of fallback) {
      if (out.length >= k) break;
      if (!out.includes(a)) out.push(a);
    }
    return out.slice(0, k);
  }
  const inc = (m, key, by = 1) => m.set(key, (m.get(key) || 0) + by);
  const add = (m, credit, w = 1) => { const s = w / credit.length; for (const a of credit) inc(m, a, s); };
  const asCredits = (xs) => xs.map((x) => (Array.isArray(x) ? x : [x]));
  const ckey = (credit) => credit.join("\u0001");

  function timeParts(ts, utc) {
    const d = new Date(ts * 1000);
    const g = utc
      ? [d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDay(), d.getUTCHours(), d.getUTCDate()]
      : [d.getFullYear(), d.getMonth(), d.getDay(), d.getHours(), d.getDate()];
    const [y, mo, wd, h, day] = g;
    return {
      month: y * 12 + mo,
      how: ((wd + 6) % 7) * 24 + h,
      day: Math.round(Date.UTC(y, mo, day) / 86400000),
    };
  }

  // perListen (optional array): receives {i, hit: {baseline: 0|1}} per test listen.
  function predictability(credits, how, k = 5, perListen = null) {
    const n = credits.length, nTrain = Math.floor(n * 0.8);
    if (n - nTrain < MIN_TEST) return null;
    const freq = new Map();
    for (let i = 0; i < nTrain; i++) add(freq, credits[i]);
    const mf = ranked(freq, k);
    const trans = new Map();
    for (let i = 0; i + 1 < nTrain; i++) {
      for (const x of credits[i]) {
        if (!trans.has(x)) trans.set(x, new Map());
        add(trans.get(x), credits[i + 1], 1 / credits[i].length);
      }
    }
    const tod = new Map();
    for (let i = 0; i < nTrain; i++) {
      if (!tod.has(how[i])) tod.set(how[i], new Map());
      add(tod.get(how[i]), credits[i]);
    }
    const todRank = new Map([...tod].map(([h, c]) => [h, fill(ranked(c, k), mf, k)]));
    const markovRank = new Map();

    const hits = Object.fromEntries(BASELINES.map((b) => [b, [0, 0]]));
    let recent = [];
    const push = (credit) => {
      for (let j = credit.length - 1; j >= 0; j--) recent = [credit[j], ...recent.filter((x) => x !== credit[j])];
      recent = recent.slice(0, k);
    };
    for (let i = 0; i < nTrain; i++) push(credits[i]);
    for (let i = nTrain; i < n; i++) {
      const t = credits[i], prev = credits[i - 1], pk = ckey(prev);
      if (!markovRank.has(pk)) {
        const s = new Map();
        for (const x of prev) if (trans.has(x)) for (const [b, v] of trans.get(x)) inc(s, b, v);
        markovRank.set(pk, fill(ranked(s, k), mf, k));
      }
      const preds = {
        repeat_last: recent,
        most_frequent: mf,
        markov1: markovRank.get(pk),
        time_of_day: todRank.get(how[i]) || mf,
      };
      const hit = {};
      for (const b of BASELINES) {
        const p = preds[b];
        hit[b] = p.length && t.includes(p[0]) ? 1 : 0;
        hits[b][0] += hit[b];
        if (p.slice(0, k).some((a) => t.includes(a))) hits[b][1]++;
      }
      if (perListen) perListen.push({ i, hit });
      push(t);
    }
    const m = n - nTrain;
    return Object.fromEntries(BASELINES.map((b) => [b, [hits[b][0] / m, hits[b][1] / m]]));
  }

  // Run lengths; a run continues while consecutive listens share an artist.
  function runs(credits) {
    const out = [];
    let cur = 1;
    for (let i = 1; i < credits.length; i++) {
      if (credits[i].some((a) => credits[i - 1].includes(a))) cur++;
      else { out.push(cur); cur = 1; }
    }
    out.push(cur);
    return out;
  }
  const mean = (v) => v.reduce((a, b) => a + b, 0) / v.length;

  function userMetrics(ts, artists, tracks, { utc = false, perListen = false } = {}) {
    const credits = asCredits(artists), trackCredits = tracks.map((t) => [t]);
    const n = credits.length;
    const parts = ts.map((t) => timeParts(t, utc));
    const months = parts.map((p) => p.month), how = parts.map((p) => p.how);
    const out = { n_listens: n };

    const pl = perListen ? [] : null;
    const p = predictability(credits, how, 5, pl);
    if (pl) out.per_listen = pl;
    if (!p) {
      for (const b of BASELINES) out[`${b}_top1`] = out[`${b}_top5`] = null;
      Object.assign(out, { predictability_top1: null, predictability_top5: null, best_baseline: null });
    } else {
      let best = BASELINES[0];
      for (const b of BASELINES) {
        out[`${b}_top1`] = p[b][0];
        out[`${b}_top5`] = p[b][1];
        if (p[b][0] > p[best][0]) best = b;
      }
      out.predictability_top1 = p[best][0];
      out.predictability_top5 = Math.max(...BASELINES.map((b) => p[b][1]));
      out.best_baseline = best;
    }
    const tp = predictability(trackCredits, how, 1);
    out.track_repeat_last_top1 = tp ? tp.repeat_last[0] : null;
    out.track_most_frequent_top1 = tp ? tp.most_frequent[0] : null;

    const c = new Map();
    for (const cr of credits) add(c, cr);
    let h = 0;
    for (const v of c.values()) { const q = v / n; h -= q * Math.log(q); }
    out.entropy = h;
    out.effective_artists = Math.exp(h);
    const top = [...c.values()].sort((a, b) => b - a).slice(0, 10);
    out.concentration_top10 = top.reduce((a, b) => a + b, 0) / n;
    out.n_artists = c.size;

    // exploration: a listen is new in proportion to its first-time credited artists
    const first = months[0], seen = new Set(), per = new Map();
    for (let i = 0; i < n; i++) {
      const m = months[i], cr = credits[i];
      if (m - first >= 2) {
        if (!per.has(m)) per.set(m, [0, 0]);
        per.get(m)[1]++;
        per.get(m)[0] += cr.filter((a) => !seen.has(a)).length / cr.length;
      }
      for (const a of cr) seen.add(a);
    }
    const rates = [...per].filter(([, v]) => v[1] >= MIN_MONTH_LISTENS)
      .sort((a, b) => a[0] - b[0]).map(([m, v]) => [m, v[0] / v[1], v]);
    out.exploration_rate = rates.length
      ? rates.reduce((a, r) => a + r[2][0], 0) / rates.reduce((a, r) => a + r[2][1], 0)
      : null;
    out.monthly_exploration = Object.fromEntries(rates.map((r) => [r[0], r[1]]));
    let breakouts = [];
    if (rates.length >= 4) {
      const v = rates.map((r) => r[1]), mu = mean(v);
      const sd = Math.sqrt(mean(v.map((x) => (x - mu) ** 2)));
      breakouts = rates.filter((r) => r[1] > mu + 2 * sd).map((r) => r[0]);
    }
    out.breakout_months = breakouts;
    out.n_breakouts = breakouts.length;

    const byDay = new Map();
    for (let i = 0; i < n; i++) {
      const d = parts[i].day;
      if (!byDay.has(d)) byDay.set(d, new Map());
      inc(byDay.get(d), tracks[i]);
    }
    const loopDays = [];
    for (const [d, cnt] of [...byDay].sort((a, b) => a[0] - b[0])) {
      let topT = null, topK = -1, tot = 0;
      for (const [t, k] of cnt) {
        tot += k;
        if (k > topK || (k === topK && t > topT)) { topT = t; topK = k; }
      }
      if (topK >= 5 && topK / tot >= 0.3) loopDays.push([d, topT, topK]);
    }
    out.loop_days = loopDays.length;
    out.loop_days_per_month = loopDays.length / (months[n - 1] - months[0] + 1);
    out.loop_day_list = loopDays;
    const ar = runs(credits), tr = runs(trackCredits);
    Object.assign(out, {
      artist_streak_mean: mean(ar), artist_streak_max: Math.max(...ar),
      track_streak_mean: mean(tr), track_streak_max: Math.max(...tr),
    });

    let sessions = 1;
    for (let i = 1; i < n; i++) if (ts[i] - ts[i - 1] > SESSION_GAP) sessions++;
    out.n_sessions = sessions;
    out.listens_per_session = n / sessions;
    return out;
  }

  // Artist identity (METRICS.md): every credited artist, normalised; placeholders dropped.
  const SPLIT = / feat\. | feat | ft\. | ft | featuring | & |, | with /;
  const PLACEHOLDERS = new Set(["unknown artist", "unknown", "[unknown]", "<unknown>", "various artists",
    "various", "va", "[no artist]", "no artist", "[anonymous]", "anonymous"]);
  const normText = (s) => (s || "").replace(/\s*•.*$/, "").normalize("NFC").toLowerCase().trim().replace(/\s+/g, " ");
  function splitArtists(name) {
    const out = [];
    for (const p of normText(name).split(SPLIT)) {
      const a = p.trim();
      if (a && !PLACEHOLDERS.has(a) && !out.includes(a)) out.push(a);
    }
    return out;  // empty = unknown artist
  }

  return { userMetrics, splitArtists, normText, BASELINES };
})();
if (typeof module !== "undefined") module.exports = PEARS;
