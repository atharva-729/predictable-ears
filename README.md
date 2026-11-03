# Predictable Ears

**How predictable is what we listen to?**

If a dumb rule ("same artist as last time") can guess your next listen 40% of the time, how much of your listening is *choice*? This project measures **predictability, exploration and loops** in real listening histories. It has two parts:

1. **The study (for Anand, publishable):** run on the public **ListenBrainz** listens dumps. About 2,000 active listeners over 12 months gives population-level results: how predictable listeners are, explorers vs loopers, when people break out of loops, and how this shifts by time of day.
2. **The personal app (for Atharva only, never published with data):** a **local-first browser page**. You drop in your own Spotify Extended Streaming History, and it computes the same metrics in the browser and shows where you sit against the ListenBrainz population. Nothing is uploaded, and the page makes no network requests.

Context: an innovation-team study with a Spotify hook. The framing is philosophical ("how free is your taste?"), but the claims stay measurable: **predictability, not free will.**

---

## How to use this README (for Claude Code)

- Work **one phase at a time**. At each **CHECKPOINT**, stop, show what it asks for, and wait for a go-ahead.
- Don't start later phases early. Don't add dependencies that aren't listed here without asking.
- Keep it simple: Python, **DuckDB** + Parquet for data, numpy/pandas for metrics, plotly for charts. The app is plain HTML + JS in one file. No backend, no frameworks, no build step.
- If a sanity check fails, stop and report.

## Ground rules

**Do**
- Check the **ListenBrainz data licence** (listenbrainz.org/data and the MetaBrainz pages) before downloading, and record it in `data/LICENCE_NOTES.md`. If it doesn't allow this use, stop.
- Check dump **file sizes** before downloading anything. Download only the months needed.
- **Hash user names** (salted, salt in `.env`) immediately on ingest. Raw user names never get written to Parquet.
- Use the **same metric code definitions** for the study and the app. Write them once, in a spec (`METRICS.md`), and test both implementations against the same synthetic users.
- Write tests for every metric using synthetic listeners with known answers (see Phase 3).

**Don't**
- Don't publish anything about an individual ListenBrainz user: no real-user profiles, no per-user tables. Use aggregates only. "Example listeners" on the page are **synthetic composites** built from cluster averages, labelled as such.
- **Never commit Atharva's personal data.** `personal/` is gitignored, and a pre-commit hook (or a test) fails if any `Streaming_History*.json` file or `personal/` path is tracked.
- Don't call the result "free will". The data shows what played, not *why* it played (see Limits).
- No LLM is needed. Don't add one.

---

## Data

### ListenBrainz (study)
- **Source:** ListenBrainz full listens dump (`listenbrainz-listens-dump-*-full`, monthly `.listens` files, JSON lines). Full dumps come out twice a month. Use the latest full dump.
- **Fields used:** `listened_at` (unix time), `user_name` (hash it on ingest), and `track_metadata.artist_name`, `track_name`, `release_name`, plus `additional_info` when present (artist MBIDs, recording MBID, `music_service`, `submission_client`, duration).
- **Window:** the **most recent 12 complete months** in the dump. Record which months in config.
- **User sample:**
  - eligible: ≥ 3,000 listens in the window **and** active (≥ 1 listen) in ≥ 10 of the 12 months;
  - exclude likely bots or bulk imports: median gap between listens < 30 s for a whole day, more than 1,500 listens in one day, or more than 20% of listens with identical timestamps;
  - draw a **random 2,000** from the eligible users (seeded). If fewer than 2,000 are eligible, take all of them and report it.
- Expected size: roughly 10–30M listens after sampling. Confirm in Phase 1.

### Personal (app only)
- Spotify **Extended Streaming History** (`Streaming_History_Audio_*.json`). Fields typically include `ts`, `ms_played`, `master_metadata_track_name`, `master_metadata_album_artist_name`, `spotify_track_uri`, `reason_start`, `reason_end`, `shuffle`, `skipped`. **Check the actual values in the export.** Don't assume the `reason_*` vocabulary.
- These files stay in `personal/` (gitignored) and are only ever read by the browser app or local tests.

## Metric definitions (write these into `METRICS.md` in Phase 3)

Everything is at **artist level** unless noted. Artist identity = artist MBID if present, otherwise the normalised artist name (lower-case, trimmed, primary artist only: split off "feat.", "ft.", "&", ","; document the rule).

| Metric | Definition |
|---|---|
| **Sessions** | A new session starts after a gap > 30 min |
| **Predictability (headline)** | Chronological split: first 80% of a user's listens to train, last 20% to test. Run the baselines below. **Predictability = best baseline top-1 hit rate on test** (also report top-5) |
| Baseline `repeat_last` | Predict the same artist as the previous listen |
| Baseline `most_frequent` | Predict the user's most-played artists from training |
| Baseline `markov1` | Predict the most common next artist after the current artist in training (fall back to `most_frequent`) |
| Baseline `time_of_day` | Predict the most-played artists in this hour-of-week bucket in training |
| **Entropy** | Shannon entropy of the artist distribution; also the **effective number of artists** = exp(H) |
| **Exploration rate** | Share of listens to artists **never heard before by this user**. The first 2 months are warm-up history, measured from month 3, per month |
| **Loop episode** | A day where one track is ≥ 30% of that day's listens and ≥ 5 plays |
| **Repeat streak** | Run length of the same artist (and the same track) in consecutive listens |
| **Breakout month** | A month whose exploration rate is > 2 SD above the user's own mean |
| **Concentration** | Share of listens going to the user's top 10 artists |

Also report **track-level** `repeat_last` and `most_frequent` as a secondary view.

---

## Repo layout

```
predictable-ears/
  README.md  METRICS.md  config.yaml
  data/LICENCE_NOTES.md  data/raw/ (gitignored)  data/listens.parquet  data/users.parquet
  personal/ (gitignored)
  src/pears/
    download.py   # list dump files, sizes, fetch selected months
    ingest.py     # .listens → Parquet via DuckDB, hash users
    sample.py     # eligibility, bot filter, random sample
    clean.py      # dedupe, artist normalisation, sessions
    metrics.py    # all metrics per user
    population.py # aggregates, clusters, time patterns
    composites.py # synthetic example listeners from clusters
    cli.py
  app/index.html  # local-first personal app (single file)
  app/population.json  # aggregate percentiles only
  reports/  docs/  tests/
```

CLI shape: `pears <step>`, for example `pears sizes`, `pears download`, `pears ingest`, `pears sample`, `pears metrics`, `pears population`, `pears site`.

---

## Phase 0: Licence, sizes, and the download plan

1. Read the licence terms and write `data/LICENCE_NOTES.md`: licence name, attribution text, any limits. **If the use isn't allowed, stop.**
2. Find the latest full listens dump and list the monthly files for the last 12 complete months **with their sizes**. Estimate total disk use, compressed and extracted.
3. Propose a download plan. If the total is too big for the machine, propose a smaller window (for example 6 months) **before** downloading.

**Don't:** download anything until the checkpoint is approved.

### CHECKPOINT 0
Show:
- The licence summary.
- The file list with sizes.
- Total disk estimate.
- Free disk space on the machine.
- The proposed window.

---

## Phase 1: Ingest and sample

1. Download the approved months, verifying checksums if they're provided.
2. Stream the `.listens` files into Parquet with DuckDB (don't load everything into memory). Hash `user_name` during the stream, and keep only the needed fields.
3. Compute per-user stats over the window: listens, active months, max listens per day, median gap, and the share with identical timestamps.
4. Apply eligibility and bot filters, then draw the seeded random sample of 2,000.
5. Write `data/listens.parquet` (sampled users only) and `data/users.parquet` (per-user stats, with a flag showing why excluded users were excluded).
6. Delete the raw downloads if disk is tight; the Parquet is the working copy.

### CHECKPOINT 1
Show:
- Total users in the window, how many are eligible, how many were excluded by each filter, and the final sample size.
- Total sampled listens.
- Listens-per-user distribution.
- Share of listens with artist MBIDs.
- Share with a `music_service` field, and its top values.
- Disk used.

---

## Phase 2: Cleaning and sessions

1. Dedupe: the same recording or artist-track listened by the same user within 30 s counts once. Report how many rows were removed.
2. Artist normalisation as specified in `METRICS.md`. Report the 20 most common normalisation merges, so Atharva can glance at them.
3. Sessions (> 30 min gap). Add hour-of-week (in the user's timezone if available; otherwise UTC, which is noted as a limit).
4. Mark warm-up months (the first 2) per user.

### CHECKPOINT 2
Show:
- Dedupe counts.
- The normalisation examples.
- Session length distribution.
- Listens per session.
- Whether timezone is available (if not, how that affects time-of-day results).

---

## Phase 3: Metrics

1. Write `METRICS.md` with the exact definitions from the table above, including edge cases (users with fewer than X test listens, ties, unknown artist).
2. Implement `metrics.py`, producing one row per user in `reports/user_metrics.parquet`.
3. **Synthetic test listeners** (in `tests/`), each with a known answer:
   - **Parrot:** the same artist every time. `repeat_last` top-1 = 100%, entropy = 0, exploration = 0 after warm-up.
   - **Uniform random over N artists:** top-1 ≈ 1/N, entropy ≈ log N.
   - **Strict cycle A→B→C→A:** `markov1` ≈ 100%, `repeat_last` = 0.
   - **Explorer:** every listen a new artist. Exploration rate = 100%, predictability ≈ 0.
   - **Night owl:** different artists by hour. `time_of_day` beats `most_frequent`.

   All tests must pass.

**Don't:** add a learned model here (see Phase 5, optional).

### CHECKPOINT 3
Show:
- Tests passing.
- Distribution plots for predictability (top-1, top-5), entropy, effective number of artists, exploration rate, concentration and loop days per month.
- Which baseline wins for what share of users.

---

## Phase 4: Population results

1. **Headline numbers:** median and IQR of predictability (top-1 and top-5); the share of users whose next artist is predictable more than 50% of the time by a trivial rule.
2. **Listener types:** cluster users on standardised [predictability, entropy, exploration rate, concentration, loop days] using k-means. Pick k from 3–5 by silhouette score. Name the clusters descriptively (for example "loopers", "steady rotation", "explorers") based on their centroids, with no LLM involved.
3. **Relationships:** exploration vs predictability (is it a straight trade-off?); does loop behaviour predict a breakout month afterwards (rate of breakout in the 1–2 months after a high-loop month vs baseline)?
4. **Time patterns:** predictability and exploration by hour-of-week, and weekday vs weekend. Only report this if timezone handling is good enough (Checkpoint 2).
5. **Within-year drift:** does exploration rise or fall over the 12 months on average? Report it, but label it weak (one year, seasonality).
6. **Synthetic composite listeners:** for each cluster, generate one example "listener card" from the centroid values, labelled *"composite, not a real person"*.
7. **Population percentiles** for each metric, saved to `app/population.json` (aggregates only, no per-user rows). The app uses this.

### CHECKPOINT 4
Show:
- Headline numbers.
- The cluster table plus a scatter (predictability vs exploration, coloured by cluster).
- The loop → breakout result.
- Time-of-day charts (if valid).
- The composite cards.
- `population.json` size and contents, checked to contain no per-user data.

---

## Phase 5 (optional): Is a smarter model much better?

Quick check of how much of listening is predictable beyond trivial rules: a simple learned next-artist model (for example a per-user mixture of the baselines with learned weights, or a small item2vec + nearest-neighbour model) on the same splits. Report the gain over the best baseline. If the gain is small, that's a finding: "most predictability is captured by dumb rules". Cap it at 1 day.

---

## Phase 6: Demo page for Anand (GitHub Pages)

`docs/index.html`, single file, data from `reports/*.json` (aggregates only):
1. **The hook:** "A one-line rule guesses the typical listener's next artist X% of the time."
2. **Distributions:** predictability and exploration histograms, with the median marked.
3. **Listener types:** a cluster scatter plus composite cards.
4. **Loops and breakouts:** what happens after a loop month.
5. **When we're most predictable:** time-of-day heatmap (if valid).
6. **Why it matters:** recommenders and discovery. If most listening is routine, the interesting product moments are the breakouts.
7. **Limits** (prominent):
   - The data shows **what played, not why**: own picks, autoplay and algorithmic playlists all look the same.
   - No skips.
   - ListenBrainz users are a self-selected, music-nerdy group.
   - It mixes streaming services.
   - Timezone caveat.
   - One year.
8. Credits and licence attribution for ListenBrainz/MetaBrainz.

**Don't:** show any real user, user hash, or per-user row.

### CHECKPOINT 6
Page renders offline, every number comes from `reports/`, the limits are visible, and a grep of `docs/` finds no hashes or user identifiers.

---

## Phase 7: Personal local-first app (Atharva only)

`app/index.html`, single file, plain JS:
- **Input:** drag-and-drop one or more `Streaming_History_Audio_*.json` files, read with `FileReader`. **Nothing leaves the browser.**
- **Hard privacy guarantees:**
  - a Content-Security-Policy meta tag with `connect-src 'none'`;
  - no external scripts, fonts or analytics; everything inline;
  - `population.json` is inlined at build time, not fetched.
- **Processing:** the same definitions as `METRICS.md`, ported to JS. Spotify-specific rules:
  - a listen counts if `ms_played ≥ 30,000`, to roughly match scrobble rules;
  - track nulls (podcasts, local files) are excluded and counted.
- **Extra views only possible with personal data** (clearly marked as not comparable with ListenBrainz):
  - **Chosen vs flowed:** split listens by `reason_start` into ones you actively started vs ones that just continued (map the categories after checking your export's actual values), and compare predictability for each. This is the closest the project gets to the "free will" question.
  - **Skips:** skip rate, and do skips cluster after long loops?
  - **Shuffle on vs off** predictability.
- **Output:**
  - your scores against population percentiles ("more predictable than 72% of listeners");
  - your loop days and breakout months on a timeline;
  - your top loop tracks.
- **JS–Python parity test:** run the same synthetic listeners from Phase 3 through the JS implementation (Node, headless) and require matching outputs within tolerance.

**Don't:** add upload, sharing, export-to-server, or storage beyond the page session. Don't commit any personal output screenshots or JSON.

### CHECKPOINT 7
Parity tests pass. The app works offline with the network disabled (verified in the browser devtools: zero requests after load). The pre-commit check blocks personal files.

---

## Rough timeline

| Phase | Time |
|---|---|
| 0 Licence + sizes | ½ day |
| 1 Ingest + sample | 1 day (mostly download + DuckDB) |
| 2 Cleaning + sessions | ½ day |
| 3 Metrics + tests | 1 day |
| 4 Population results | 1 day |
| 5 Smarter model (optional) | 1 day |
| 6 Demo page | 1 day |
| 7 Personal app | 1–1½ days |

About **5–6 working days** to the Anand demo (Phases 0–4 + 6), plus about 1½ days for the personal app. No LLM spend.

## Out of scope (v1)
- Age or life-stage analysis (no demographics in ListenBrainz; LFM-2b is no longer downloadable).
- Audio features or genre analysis.
- Recommender building.
- Any hosted version of the personal app.