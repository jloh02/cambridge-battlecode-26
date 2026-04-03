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

## Iteration protocol

1. Investigate `jon-5o` regressions vs `jon-5` over 32 games before adding AFI changes.
2. Verify whether each confirmed regression bug exists in `duck-1`.
3. Patch regression bugs in `duck-1` first.
4. Prioritize AFIs in order: **7, 9, 10, 11**.
5. Use at least `g16` (`--games-per-opponent 16`) with `--jobs 8` for all
   decision-making runs (no `g4` decisions).
6. Before any keep decision, run `g32` (`--games-per-opponent 32`) with
   `--jobs 8` as the final validation gate.
7. Commit every net improvement immediately with metrics in commit message.

## Run log

| Step | Change set | Command | Outcome |
| --- | --- | --- | --- |
| 24 | Combined traceback+annotation fix | g4 (legacy, invalid now) | Folded (regressed vs AFI-16 baseline) |
| 24a | Debug annotation only | g4 (legacy, invalid now) | Folded (regressed vs AFI-16 baseline) |

| 30 | R1 re-land (bridge pruning relax + direct transit A*) | g16 (`step30_r1_reland`, `step30c_r1plusdebug`) | Kept by strategic directive despite regression risk and high variance (`53.1%` to `65.6%` WR across separate g16 schedules), because broader-opponent hypothesis favors less over-pruned bridge routing and direct transit continuity under pressure. |
| 30b | Restore unconditional traceback debug annotations | code parity with `jon-5` | Kept: `draw_indicator_dot` on A* failure and `draw_indicator_line` on move target now always render (not debug-flag gated). |
