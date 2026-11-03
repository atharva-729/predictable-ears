// Written findings for docs/index.html. Numbers come from D (aggregates); the words
// were written after reading the results (reports/RUN_LOG.md).
const P = D.pop, H = P.headline, S = D.smarter, C = D.clean, F = D.funnel;
const R = Object.fromEntries(P.rules.rules.map((r) => [r.rule, r]));
const T = Object.fromEntries(P.clusters.table.map((c) => [c.cluster, c]));
const t = (name) => T[name] || {};
const TP = P.time_patterns, LB = P.loop_breakout;
const hrs = (a) => a.filter((v) => v != null);
const rng = (a) => [Math.min(...hrs(a)), Math.max(...hrs(a))];
const pts = (x) => (100 * x).toFixed(1);
const gain = S.mixture_median - S.best_single_median;

fill("ans-main", `A one-line rule, <strong>“same artist as last time”</strong>, guesses the typical listener's next artist <span class="hl">${pct(H.predictability_top1.median)}</span> of the time. For about ${H.share_top1_over_50 > .3 && H.share_top1_over_50 < .37 ? "a third" : pct(H.share_top1_over_50)} of listeners it is right more than half the time.`);
fill("ans-but", `It is runs, not repeats: the same <em>track</em> comes back only ${pct(H.track_level_top1_median.repeat_last, 0)} of the time, and once a run ends the next artist is hard to call even with five guesses (${pct(H.predictability_top5.median)}).`);

fill("data-bul", lis([
  `<strong>What:</strong> the public ListenBrainz listens export of 1 November 2026 (CC0). The last 12 full months, Nov 2025 – Oct 2026: ${n0(F.window_users)} users with at least one listen.`,
  `<strong>Why ListenBrainz:</strong> it is the only large, public, listen-by-listen history with timestamps. People scrobble from Spotify, Last.fm and local players.`,
  `<strong>Who:</strong> ${n0(F.sampled)} listeners drawn at random (fixed seed) from the ${n0(F.eligible)} who were active all year and did not look like bots. Random, so not hand-picked. <a class="down" href="#method">Filters ↓</a>`,
  `<strong>How:</strong> the dump is one 250 GB file; only the 38 GB holding these months was downloaded, by byte range. User names were hashed on arrival and never stored.`,
]));

fill("res-h2", `“Same artist as last time” is the rule that works, best for ${pct(R.repeat_last.wins_share)} of listeners`);
fill("nob-results", lis([
  `<strong>People listen in runs of an artist, not on repeat.</strong> “Same artist” is right ${pct(R.repeat_last.top1_median)} of the time; “same track” only ${pct(H.track_level_top1_median.repeat_last, 0)}. Albums and artist sessions, not one song looping.`,
  `<strong>Your favourite artist is a bad guess.</strong> “Most played” is right only ${pct(R.most_frequent.top1_median)} of the time: the typical listener's top 10 artists take just ${pct(H.concentration_top10.median)} of their plays, spread over about ${n0(H.effective_artists.median)} effective artists.`,
  `<strong>Five guesses barely help.</strong> ${pct(H.predictability_top1.median)} with one guess, ${pct(H.predictability_top5.median)} with five. When a run breaks, what comes next is genuinely open.`,
  `<strong>How much you listen does not matter.</strong> The lighter, middle and heavier thirds of listeners are all near ${pct(R.repeat_last.by_volume.middle)} on “same as last”.`,
  `<strong>The clock is useless as a guide.</strong> “This hour” is right ${pct(R.time_of_day.top1_median, 1)} of the time and is the best rule for almost nobody (${pct(R.time_of_day.wins_share, 1)}). <a class="down" href="#time">Time of day ↓</a>`,
]));

const hab = t("Creatures of habit"), dev = t("Devotees"), exp = t("Explorers"), loo = t("Loopers"), ste = t("Steady rotation");
fill("types-h2", `Five kinds of listener. Being predictable is not the same as having narrow taste.`);
fill("nob-types", lis([
  `<strong>There are two ways to be predictable.</strong> Creatures of habit (${pct(hab.share)}) are ${pct(hab.predictability_top1)} predictable with a normal spread of about ${n0(hab.effective_artists)} artists: they play in long runs. Devotees (${pct(dev.share)}) are ${pct(dev.predictability_top1)} predictable because their world is small: about ${n0(dev.effective_artists)} artists, ${pct(dev.concentration_top10)} of plays on their top 10.`,
  `<strong>Explorers really are different.</strong> About ${n0(exp.effective_artists)} effective artists, ${pct(exp.exploration_rate)} of plays are a first-time artist, and the rules get only ${pct(exp.predictability_top1)} right.`,
  `<strong>The trade-off is real but loose.</strong> More exploring means less predictable (rank correlation ${P.relationships.spearman_exploration_predictability.toFixed(2)}), but it flattens out: the most exploring tenth is still ${pct(P.relationships.predictability_by_exploration_decile.at(-1).predictability_median)} predictable.`,
  `<strong>Loopers are rare but extreme.</strong> Only ${pct(loo.share, 1)} of listeners, with about ${(loo.loop_days_per_month || 0).toFixed(0)} loop days a month, against ${H.loop_days_per_month.median.toFixed(2)} for the typical listener.`,
]));

fill("smart-h2", gain <= 0.005
  ? `No. A learned mix of the rules does no better than “same artist as last time”`
  : gain < 0.03
    ? `Barely. Mixing the rules adds ${pts(gain)} points; the dumb rule captures most of it`
    : `Somewhat. Mixing the rules adds ${pts(gain)} points over the best single rule`);
fill("nob-smart", lis([
  `<strong>The mix is not better.</strong> Typical listener: ${pct(S.mixture_median, 1)} for the mix against ${pct(S.best_single_median, 1)} for the best single rule (mean change ${S.gain_mean_pts.toFixed(1)} points). It gains 5+ points for only ${pct(S.share_users_gain_over_5pts, 2)} of listeners and does worse for ${pct(S.share_users_mixture_worse)}.`,
  `<strong>The comparison flatters the single rule a little:</strong> each listener's best rule is picked with hindsight on the test listens, while the mix had to choose its weights beforehand. That does not change the answer, because…`,
  `<strong>…the ceiling is only ${pct(S.oracle_median)}.</strong> Even a perfect judge of which rule to trust on each listen gets at most ${pts(S.oracle_median - S.best_single_median)} points more. What is left needs a different kind of model, or is not predictable from listening history at all.`,
  `<strong>The mix ends up as “same as last”.</strong> It was the heaviest-weighted rule for ${pct(S.heaviest_weight_share.repeat_last || 0)} of listeners.`,
]));

fill("loops-h2", LB.lift > 1.15
  ? `Loop-heavy months are followed by a breakout a little more often`
  : `Loop-heavy months do not lead to breakouts`);
fill("nob-loops", lis([
  `<strong>Loops are rare for most people.</strong> The typical listener has ${H.loop_days_per_month.median.toFixed(2)} loop days a month, about one a year, and at least a quarter of listeners have none.`,
  `<strong>After a loop-heavy month, a breakout follows ${pct(LB.breakout_rate_after_high_loop, 1)} of the time, against ${pct(LB.breakout_rate_after_other, 1)} after other months</strong> (×${LB.lift.toFixed(1)}). A small, real tilt toward “stuck, then break out”. It shows timing, not cause.`,
  `<strong>Breakouts happen to ${pct(H.share_with_breakout)} of listeners</strong> at least once in the year. These are the moments a recommender could matter most.`,
]));

const [ul, uh] = rng(TP.utc.predictability_by_hour), [ll, lh] = rng(TP.local.predictability_by_hour);
const offs = Object.entries(TP.inferred_offset_counts).map(([k, v]) => [+k, v]);
const eu = offs.filter(([k]) => k >= 0 && k <= 4).reduce((a, [, v]) => a + v, 0), am = offs.filter(([k]) => k >= -8 && k <= -2).reduce((a, [, v]) => a + v, 0);
fill("time-h2", `The hour of day barely matters`);
fill("nob-time", lis([
  `<strong>Predictability moves only ${(100 * (uh - ul)).toFixed(0)} points across the day in UTC (${pct(ul)}–${pct(uh)}) and ${(100 * (lh - ll)).toFixed(0)} in estimated local time.</strong> Weekdays and weekends are the same (${pct(TP.utc.predictability_weekday)} vs ${pct(TP.utc.predictability_weekend)}).`,
  `<strong>Treating everyone as UTC does not hide a pattern.</strong> The estimated timezones look real (${pct(eu / F.sampled)} of listeners land on European offsets, ${pct(am / F.sampled)} on the Americas), and shifting to local time leaves the line just as flat.`,
  `<strong>These per-listen figures (${pct(ul)}+) are above the headline ${pct(H.predictability_top1.median)}</strong> because here every listen counts, so heavy, predictable listeners weigh more.`,
]));

fill("method-bul", lis([
  `<strong>Window:</strong> 1 Nov 2025 – 31 Oct 2026, the 12 full months before the dump. All times UTC.`,
  `<strong>Eligibility:</strong> ≥ 3,000 listens and active in ≥ 10 of 12 months. Bots and bulk imports out: any day over 1,500 listens; over 20% identical timestamps; or more than 2 “fast days” (≥ 50 listens with most gaps under 30 s). Users with 1–2 fast days stay, minus those days.`,
  `<strong>Cleaning:</strong> the same track by the same user within 30 s counts once (${n0(C.dedupe_removed)} removed). A new session starts after 30 minutes of silence.`,
  `<strong>Scoring:</strong> per listener, train on the first 80% of their listens, test on every listen in the last 20%. Predictability = the best rule's hit rate. Ties broken alphabetically. Exact definitions: <code>METRICS.md</code>.`,
  `<strong>Exploration:</strong> share of plays that are a first-time artist for that listener, from month 3 on (months 1–2 build history). It falls through the year, from ${pct(P.drift.by_month[0].mean)} to ${pct(P.drift.by_month.at(-1).mean)}, mostly because later months are judged against more history. Weak evidence, not a trend.`,
  `<strong>Listener types:</strong> k-means on five standardised measures (predictability, entropy, exploration, top-10 concentration, loop days); k = ${P.clusters.k} chosen by silhouette from 3–5. Names come from the cluster centres. Cards are composites built from cluster medians, not real people.`,
  `<strong>Smarter model:</strong> per listener, a weighted vote of the four rules' top-5 lists, weights (0–3 each) chosen on the last 20% of their training data, then scored on the same test listens.`,
]));
fill("identity-bul", lis([
  `<strong>Every credited artist counts.</strong> “BTS, Halsey” is one collaboration track, credited to both; each gets half the listen, and guessing either is right. ${pct(C.multi_artist_share, 1)} of listens credit more than one artist.`,
  `<strong>Same artist, different spellings, one key.</strong> MusicBrainz IDs where present; otherwise the cleaned name, matched to an ID seen with that name elsewhere. “ADAMS AVENUE” and “Adams Avenue” are one artist.`,
  `<strong>Placeholders are not artists.</strong> “Unknown Artist”, “Various Artists” and similar: ${n0(C.unknown_recovered_rows)} of ${n0(C.unknown_rows)} such listens were recovered from the same recording elsewhere; the rest were dropped.`,
  `<strong>Import tags removed.</strong> Text after “ • ” (e.g. “Recommended for you”, “From Smart Shuffle”, songwriter lists) is dropped.`,
]));
fill("cost-bul", lis([
  `<strong>$0 and no AI model.</strong> Plain counting rules, Python, DuckDB. Everything ran on an 8 GB laptop.`,
  `<strong>Time:</strong> about 1.5 h to download 38 GB (the server's speed), then minutes per step: ingest 7 min, cleaning 5 min, metrics 8 min, smarter model about 15 min, population seconds.`,
  `<strong>Privacy:</strong> user names hashed with a secret salt on arrival; per-listener results stay on the machine; this page is built from aggregates only.`,
]));
