# Metric definitions

One spec for both implementations: `src/pears/metrics.py` (study) and the JS port in
`app/metrics.js`, inlined into `app/index.html` (personal app). Both are tested against
the same synthetic listeners (`tests/synthetic.py`, `tests/test_parity.py`).

## Input

One row per listen: `user`, `ts` (unix seconds), `artists` (the listen's **credit**: a
non-empty list of artist keys, first-credited first; below), `track` (normalised key).
Rows are sorted by `ts`; ties keep input order.

## Artist identity

**Every credited artist counts.** "BTS, Halsey" (one collaboration track) is credited to
both BTS and Halsey; Halsey's solo tracks are still just Halsey.

1. Clean the name: strip import junk after " • " (e.g. "BTS, Halsey • From Smart
   Shuffle"), Unicode NFC, lower-case, trim, collapse whitespace.
2. Split it into credited artists at ` feat. `, ` feat `, ` ft. `, ` ft `, ` featuring `,
   ` & `, `, `, ` with ` (" x " is not split: too many real names contain it). Trim each
   part, drop empty parts and duplicates, keep order.
3. If the listen has artist MBIDs (ListenBrainz only), its keys are those MBIDs.
   Otherwise each name part is a key, replaced by the MBID most often paired with that
   name in tagged listens across the sample (study only), so tagged and untagged plays
   of the same artist match.
4. **Placeholders are not artists:** `unknown artist`, `unknown`, `[unknown]`,
   `<unknown>`, `various artists`, `various`, `va`, `[no artist]`, `no artist`,
   `[anonymous]`, `anonymous`, and the MusicBrainz "Various Artists" / "[unknown]" MBIDs
   are removed from credits.
5. A listen left with no artist is **recovered** from the same recording elsewhere in the
   sample (same recording MBID, else same track name + release name), only when every
   such listen points to one credit. Otherwise it is **dropped** and counted.

Track key = `first artist key + "|" + track name` (track name cleaned as in 1).
Name-based on purpose, so tagged and untagged plays of a track match.

Known limit: splitting on " & " also splits names like "You & I" or "Simon & Garfunkel"
into two artists. Rare (well under 0.1% of listens); not special-cased.

## Weights and hits with several artists

- A listen gives each of its `c` credited artists weight `1/c` in every count (artist
  frequencies, transitions, hour-of-week buckets, entropy, concentration).
- A guess is a **hit** if the guessed artist is any of the listen's credited artists.
- With one artist per listen all definitions below reduce to the single-artist ones.

## Time

- **All times are UTC** for ListenBrainz (the dump has no user timezone or location).
  Each user's offset is constant, so the per-user `time_of_day` rule still groups the
  same local hours together; population hour-of-day patterns mix timezones (checked in
  Phase 4 before reporting). The Spotify app uses the browser's local time.
- Month = calendar month of `ts`.
- Hour-of-week = weekday (Mon = 0) × 24 + hour, 0–167.
- **Sessions:** a new session starts after a gap > 30 min (1,800 s).

## Predictability (headline)

- Chronological split: first `floor(0.8 n)` listens train, the rest test.
  Needs ≥ 100 test listens, otherwise predictability is `null`.
- Each baseline produces a ranked list of artists for each test listen `i`.
  **Hit@k** = any of the first k guesses is in the listen's credit. We report k = 1 and 5.
- Ties in (weighted) counts are broken by artist key, ascending (string order).
- `repeat_last`: rank = the most recent distinct artists before `i` (using train + earlier
  test listens), most recent first; a credit's first artist counts as its most recent.
- `most_frequent`: rank = training artists by weighted count, descending.
- `markov1`: training transitions count every artist of listen `j` → every artist of
  listen `j+1`, weight `1/(|credit j| · |credit j+1|)`. For test listen `i`, sum the
  transition counts of every artist in credit `i-1`, rank by that, then fill from
  `most_frequent` (skipping duplicates).
- `time_of_day`: rank = training artists in listen `i`'s hour-of-week bucket, by weighted
  count; then filled from `most_frequent`.
- **Predictability top-1** = max top-1 hit rate over the four baselines;
  **predictability top-5** = max top-5 hit rate. `best_baseline` = the argmax for top-1
  (ties: the order listed above).
- Track level (secondary): `repeat_last` and `most_frequent` top-1 on track keys.

## Diversity

- **Entropy** H = −Σ p ln p over the weighted artist distribution of all listens
  (natural log).
- **Effective number of artists** = exp(H).
- **Concentration** = weighted share of listens going to the user's 10 most-played artists.

## Exploration

- Warm-up = the first 2 calendar months starting at the user's first listen month.
  Earlier listens still count as history.
- A listen's **newness** = the share of its credited artists never heard in any earlier
  listen of the user (1 for a single new artist; ½ for a known artist featuring a new one).
- Monthly exploration rate (month ≥ 3, with ≥ 20 listens) = Σ newness / listens.
- **Exploration rate** = Σ newness / listens over all post-warm-up months.
- **Breakout month** = a post-warm-up month whose rate > mean + 2 SD of the user's own
  monthly rates (population SD, needs ≥ 4 qualifying months).

## Loops and streaks

- **Loop day** = a calendar day where one track has ≥ 5 plays **and** ≥ 30% of that day's
  listens. `loop_days_per_month` = loop days / months spanned (first to last listen month,
  inclusive).
- **Repeat streak**: lengths of runs of consecutive listens that share an artist (and of
  the same track). Report mean and max run length.

## Edge cases

- Users with < 100 test listens: predictability fields are `null`.
- No post-warm-up month with ≥ 20 listens: exploration is `null`, breakouts 0.
- Float outputs compared with tolerance 1e-9 between Python and JS.
