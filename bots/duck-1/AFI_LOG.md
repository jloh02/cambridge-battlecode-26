# duck-1 AFI log

This log tracks the fixed AFI scope for `duck-1` and the outcomes of each
iteration.

## Scope lock

- AFI scope is static unless explicitly changed by the user.
- AFI #1 ("splitter-near-core") is intentionally retired as low value.
- Keep numeric IDs stable so priorities like "7, 9, 10, 11" stay unambiguous.

## AFI checklist

| ID | AFI | Status | Priority |
| --- | --- | --- | --- |
| 1 | Splitter-near-core congestion policy | Retired | n/a |
| 2 | Explore/survey/repair mode for idle builders | Partial | Medium |
| 3 | Core-heal defensive trigger under rush pressure | Partial | Low |
| 4 | Lane audit/repair/replace policy for weak return routes | Partial | Medium |
| 5 | Anti-rush doctrine for logistics-critical tiles | Partial | Low |
| 6 | Marker deconfliction lifecycle + schema discipline | Partial | Medium |
| 7 | Axionite economy completion (foundry-plus-convert throughput) | Partial | **High** |
| 8 | Harvester/ore defense hardening | Partial | Low |
| 9 | Trace-back core-first rule before augmentation | Partial | **High** |
| 10 | Bridge policy update (no special throughput assumption; value-based use) | Partial | **High** |
| 11 | Primitive architecture hardening (typed sensing/logistics/navigation boundaries) | Partial | **High** |
| 12 | Restore debugging sight lasers from `jon-5` | Not done | Low |
| 13 | Leverage map symmetry for inference and decision-making on enemy positions | Not done | **High** |

## Iteration protocol

1. Investigate `jon-5o` regressions vs `jon-5` over 32 games before adding AFI changes.
2. Verify whether each confirmed regression bug exists in `duck-1`.
3. Patch regression bugs in `duck-1` first.
4. Prioritize AFIs in order: **7, 9, 10, 11**.
5. Use at least `g64` (`--games-per-opponent 64`) with `--jobs 8` for all
   decision-making runs.
6. Before any keep decision, run a confirming `g64` rerun on a second schedule
   seed (same jobs/opponent set) to reduce one-schedule variance.
7. Commit every net improvement immediately with metrics in commit message.

## Run log

| Step | Change set | Command | Outcome |
| --- | --- | --- | --- |
| 24 | Combined traceback+annotation fix | g4 (legacy, invalid now) | Folded (regressed vs AFI-16 baseline) |
| 24a | Debug annotation only | g4 (legacy, invalid now) | Folded (regressed vs AFI-16 baseline) |

| 30 | R1 re-land (bridge pruning relax + direct transit A*) | g16 (`step30_r1_reland`, `step30c_r1plusdebug`) | Kept by strategic directive despite regression risk and high variance (`53.1%` to `65.6%` WR across separate g16 schedules), because broader-opponent hypothesis favors less over-pruned bridge routing and direct transit continuity under pressure. |
| 30b | Restore unconditional traceback debug annotations | code parity with `jon-5` | Kept: `draw_indicator_dot` on A* failure and `draw_indicator_line` on move target now always render (not debug-flag gated). |
| 31 | R1 baseline recalibration under new protocol | g64 (`seed1`, `seed2`) | Baseline established before next AFIs: seed1 WR 56.2% avg 22.75k worst 0, seed2 WR 43.8% avg 22.20k worst 0. |
| 32 | AFI-7 A1 (foundry anchor + gated axionite eligibility) | g64 (`seed1`, `seed2`) | **Deferred (not kept):** inconsistent and opponent-skewed; seed1 regressed aggregate and seed2 degraded `jon-5o`; worst remained 0 in both. Refined axionite delivery stayed 0, so intended foundry-plus-convert pathway did not activate robustly. |
| 33 | AFI-9 core-first traceback before augmentation | g64 (`seed1`, `seed2`) | **Kept:** win rate was statistically neutral (127/256 vs 128/256 baseline; paired flips 46 up / 47 down), but TiEq improved robustly (+2.04k avg; bootstrap 95% CI +575 to +3416), with fewer catastrophic tails (`<=5k`: 21 vs 27, zeros: 8 vs 11). This improves economic resilience without measurable WR harm. |
| 34 | AFI-10 bridge policy (value-scored bridge expansion; no throughput assumption) | g64 (`seed1`, `seed2`) | **Deferred (not kept):** WR stayed neutral vs AFI-9 (127/256 in both), but economics regressed materially (avg TiEq `-1.45k`, bootstrap 95% CI `-2.90k` to `+0.13k`) and catastrophic tails worsened (`<=5k`: 29 vs 21, zeros: 14 vs 8). Positive seed1 signal did not hold under seed2 confirmation. |
| 35 | AFI-11 primitive architecture hardening (typed sensing snapshot boundary) | g64 (`seed1`, `seed2`) | **Deferred (not kept):** architecture cleanup did not preserve behavior. Versus AFI-9, aggregate WR dropped (`119/256` vs `127/256`), with primary loss on `jon-5o` (`43.8%` vs `50.0%`). TiEq delta was inconclusive to negative (avg `-444.6`, bootstrap 95% CI `-1812.3` to `+995.1`) and low-tail worsened (`<=5k`: 23 vs 21, zeros: 10 vs 8). |
| 36 | AFI-7 A2 (foundry-anchor routing + foundry-near-core placement/priming) | g64 (`seed1`, `seed2`) | **Deferred (not kept):** robustly negative and failed AFI intent. Paired vs AFI-9 over 256 games: WR `127/256 -> 123/256` (not significant), avg TiEq `-2.77k` (bootstrap 95% CI `-4.16k` to `-1.39k`), tails worsened (`<=5k`: `21 -> 34`, zeros: `8 -> 16`). Also delivered/mined refined axionite remained `0.0` across both opponents and seeds, so no foundry-plus-convert activation occurred. |
| 37 | AFI-4 A1 (disconnected-harvester lane-repair retry trigger) | g64 (`seed1`, `seed2`) | **Kept (with caveat):** materially stronger wins than AFI-9 and AFI-4 A2. Against AFI-9 over paired 256 games: WR `127 -> 143` (+6.25 pp), including `jon-5o` `64 -> 74`; TiEq shifted down (`-1.05k`, bootstrap 95% CI `-2.32k` to `+0.25k`) with worse low tails (`<=5k`: `21 -> 27`). Despite quality regression, this version outperformed A2 on head-to-head wins and is retained as the better AFI-4 implementation pending later tail-hardening. |
| 38 | AFI-4 A2 (guarded repair trigger: min-round/topology/distance) | g64 (`seed1`, `seed2`) | **Deferred (not kept):** second pass reduced AFI-4 upside and failed to remove regressions. Versus AFI-9 over paired 256 games: WR only `127 -> 132` (+1.95 pp, non-significant), avg TiEq `-1.11k`, tails still worse (`<=5k`: `21 -> 28`). Directly versus AFI-4 A1, wins dropped (`143 -> 132`, `-4.30 pp`) with no reliable quality gain. |
| 39 | AFI-4 A1 revalidation (restored variant after A2 trial) | g64 (`seed1`, `seed2`) | **Consistency note:** rerun showed schedule variance and role skew (overall WR `125/256`), but decision remains to keep AFI-4 A1 over A2 because A2 reliably underperformed A1 in paired comparison and did not cure tail regressions. AFI-4 remains a win-tilted tradeoff requiring future economic-tail mitigation. |
