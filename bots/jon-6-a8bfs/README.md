# jon-6-a8bfs

`jon-6-a8bfs` branches from `jon-6-a7bfs` and is currently focused on assault reliability. The visible-anchor planner and passable-ring fixes are still in place; the latest experiment replaced the old assault opening escape with a broader assault-only bootstrap egress phase to cut spawn-time cost.

## Implemented
- Added `ASSAULT_TLE_FIX_PLAN.md` to pin down the five-part late-assault plan: one-pass visible-anchor resolution, progress-based anchor leases, stable scout locks, cadence-limited assault harvester tracking, and wall-aware assault BFS.
- Added one-pass visible-anchor resolution. Visible harvesters now derive both `AnchorAssessment` and the best ring site from one ranked-site pass instead of assessing and then reranking the same anchor.
- Added progress-based anchor lease state so unseen anchors are not dropped purely because the short `last_seen` TTL expires while the bot is still making progress toward the committed anchor or ring.
- Made scout targets more lock-like by tracking target kind, best distance, last progress, and stall count. Predicted scout anchors no longer rotate by epoch; active scout locks survive short TTL expiry while they are still making progress, and stalled frontier chunks can temporarily exhaust their sector.
- Cadence-limited assault-mode full-grid harvester tracking. Assault scans still update visible harvesters immediately, but the expensive remembered-grid harvester sweep now runs on a heartbeat instead of every assault turn.
- Made assault BFS recompute preferred direction order at each expanded node instead of reusing the start-tile ordering for the whole search. Connected-harvester checks for dynamic obstacles are now memoized per turn.
- Moved the forced opening assault wave earlier and widened it: `jon-6-a8bfs` now spawns four diagonal assault bots on rounds `4,5,6,7` (0-indexed) instead of only spawning two on `5,6`. The low-resource assault quota now matches that four-bot opening wave automatically because it is still derived from the configured round set.
- Reordered assault site scoring so a ring with `turns_to_useful_shot = 0` wins before a richer `CLEARABLE` logistics shot when neither option is a core/turret/high-threat exception. This fixes the “fight the conveyor instead of just plonking a sentinel next to the harvester” failure mode.
- Added explicit ring occupancy ordering inside the assault scorer: prefer friendly roads/markers first because they can be cleared with `destroy()`, then empty rings, then enemy roads/markers, then enemy conveyors/armoured conveyors/bridges.
- Added a mild visible-anchor depth tie-breaker toward `enemy_core_anchor` and threaded that same inferred core focus into per-anchor site ranking. This is intentionally a tie-breaker, not a dominant bias, after a stronger version regressed the smoke benchmark.
- Replaced the old shell-BFS-first escape with an assault-only `bootstrap_egress` phase. Assault bots now stay on cheap bootstrap logic from spawn until they clear a coarse outward checkpoint, see a useful local signal, or hit a hard timeout.
- Bootstrap egress now uses a staged local policy instead of the old broad shell reroute: prefer outward progress, then tangential slide, then bounded backstep, then a tiny cached local reroute only after repeated blocks.
- Kept bootstrap cheap after shell exit too: assault bots continue using fast perception while bootstrap is active, instead of immediately paying for a full scout/inference turn on the first frame outside the shell.
- Disabled `CONNECTED_HARVESTER` marker placement in `mode_tiling_back`; replay analysis showed the lone base marker was still coming from that old tiling-back path, not from assault bootstrap or claim markers.
- Updated `build_predicted_enemy_harvesters` to treat unseen ring sides as actionable when ranking mirrored enemy ore sites. This keeps far-side DNA-style targets alive even when the mirrored enemy half is still fogged.
- Split visible-anchor handling away from exploratory anchor scouting. Visible harvesters now resolve through the real ring planner with `allow_exploratory_fallback=False`, and anchors that expose no actionable site are explicitly abandoned with a short blacklist instead of being left in a soft scout loop.
- Stopped visible committed sites from expiring on the short commit TTL while the anchor is still on-screen. This makes visible assault plans sticky until a hard invalidation, instead of reranking every few turns.
- Added bounded execute-side recovery for `BUILD`/`CLEAR_THEN_BUILD`: execute now reclassifies its ring state each turn, and `BUILD` no longer retries a closed `can_build_sentinel()` window forever.
- Fixed ring legality for enemy passable logistics. Enemy `ROAD`, `MARKER`, and `BRIDGE` tiles on assault rings are now classified as `CLEARABLE` instead of `IMMEDIATE`, while friendly roads and markers still stay in the immediate-build path via a pre-build `destroy()`.
- Reworked clear/build execution to match that legality split: `CLEAR_THEN_BUILD` now steps onto enemy roads, markers, and bridges and fires them just like enemy conveyors, instead of falling into a false `can_build_sentinel()` loop.

## Root Cause Notes
- The late `butterfly`/`chemistry_class` TLEs were mostly planner and perception churn. Visible harvesters could trigger anchor assessment and site ranking as two separate ranked-site passes, and assault perception still scanned the whole remembered grid for harvesters even during otherwise cheap local scans.
- Target flips back toward base were partly caused by a seen-only anchor TTL. A bot could still be moving toward a useful anchor or ring, but if the harvester was unseen for long enough the live-anchor path cleared it and let recent-confirmed or predicted target selection pull the bot backward.
- The bottom-fringe scout stalls were made worse by soft scout targets and predicted-anchor epoch rotation. The new scout lock keeps a concrete target until progress stalls or the target is locally exhausted.
- Wall/corridor TLEs were not just path length. The assault BFS used one direction order from the start tile, which biased the entire search into the same wall face. The new per-node ordering is still bounded but adapts as the search moves around obstacles.
- The “attack the conveyor instead of building on open ring space” bug was a scorer-ordering issue, not an execute issue. `pressure_score` could outrank `turns_to_useful_shot`, so a clearable conveyor ring sometimes beat an empty immediate ring around the same harvester.
- Even after fixing immediate-vs-clearable, ring occupancy still mattered. The planner was treating all immediate rings and all clearable rings too similarly, so it could skip over free `destroy()` conversions on friendly roads/markers or pick a higher-HP enemy conveyor instead of an enemy road.
- The DNA “why didn’t it ever make it to the other side?” behavior is mostly a target-selection issue, not pure pathfinding. The current mild depth tie-breaker helps only when visible options are otherwise comparable. A stronger depth-first visible-anchor bias did make bots cross farther, but it also hurt the smoke benchmark enough that it was not kept.
- The stray base marker was a dead write path: `CONNECTED_HARVESTER` markers were still emitted, but `jon-6-a8bfs` was not meaningfully consuming them.
- The DNA and post-sentinel stalls were not primarily caused by the node-capped assault BFS. In the frozen replay states, assault BFS counters stopped at zero for the affected bots, which means they were no longer even reaching the navigation phase.
- Symmetry itself was not the main failure either. The mirrored enemy core/ore inference could still identify the opposite side of the map. The real break was the target heuristic throwing away mirrored ore candidates whenever all ring sides were still unseen.
- The cubes-style “stand on enemy logistics and do nothing” failure split into two layers:
  - visible anchors could fail to produce a concrete site and then fall back into scout, even though the bot was already next to real enemy infrastructure
  - execute-side `BUILD` could keep retrying a false `can_build_sentinel()` forever without reclassifying or timing out
- The large-map “claim marker but no sentinel” stall had an additional concrete cause: ring classification treated every passable ring building as open. That was wrong for enemy roads, enemy markers, and enemy bridges. The planner would commit a `BUILD` plan, but execute could never actually place the sentinel on those occupied enemy tiles.
- The current spawn-time risk is a whole-team budget spike, not just a single assault-pathing spike. The new assault bootstrap reduced some early assault cost, but the econ bots still dominate the tracked time on the worst early rounds.

## Validation
- `pytest -q tests/test_jon_6_a8bfs_core.py tests/test_jon_6_a8bfs_assault.py tests/test_jon_6_a8bfs_tiling.py`
  `20 passed`
- `DEBUG=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=900000 cambc run jon-6-a8bfs leeroy-jonkins maps/butterfly.map26 --seed 1 --replay .dist/replays/jon-6-a8bfs_vs_leeroy-jonkins_butterfly_seed_1.replay26`
  `jon-6-a8bfs` wins on resources at turn `2000`
  Log: `logs/timing/jon-6-a8bfs_vs_leeroy-jonkins_butterfly_seed_1.log`
- `DEBUG=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=900000 cambc run jon-6-a8bfs leeroy-jonkins maps/chemistry_class.map26 --seed 1 --replay .dist/replays/jon-6-a8bfs_vs_leeroy-jonkins_chemistry_class_seed_1.replay26`
  `leeroy-jonkins` wins on resources at turn `2000`
  Log: `logs/timing/jon-6-a8bfs_vs_leeroy-jonkins_chemistry_class_seed_1.log`
- `python tools/run_representative_benchmark.py jon-6-a8bfs jon-6-a7bfs --seeds 1 --jobs 8`
  `5-5`
  Benchmark file: `.rep_bench/20260406_121219_jon-6-a8bfs_vs_jon-6-a7bfs.json`
- `pytest -q tests/test_jon_6_a8bfs_core.py tests/test_jon_6_a8bfs_assault.py tests/test_jon_6_a8bfs_tiling.py`
  `18 passed`
- `python tools/run_representative_benchmark.py jon-6-a8bfs jon-6-a7bfs --maps default_small1.map26 default_medium1.map26 default_large1.map26 --seeds 1 --jobs 8`
  `3-3`
  Benchmark file: `.rep_bench/20260406_022944_jon-6-a8bfs_vs_jon-6-a7bfs.json`
- `pytest -q tests/test_jon_6_a8bfs_assault.py tests/test_jon_6_a8bfs_tiling.py`
  `16 passed`
- `DEBUG=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=900000 cambc run jon-6-a8bfs leeroy-jonkins maps/dna.map26 --seed 1 --replay .dist/replays/jon-6-a8bfs_vs_leeroy-jonkins_dna_seed_1.replay26`
  `leeroy-jonkins` wins on resources at turn `2000`
  Log: `logs/timing/jon-6-a8bfs_vs_leeroy-jonkins_dna_seed_1.log`
- `python tools/run_representative_benchmark.py jon-6-a8bfs jon-6-a7bfs --maps default_small1.map26 default_medium1.map26 default_large1.map26 --seeds 1 --jobs 8`
  `4-2`
  Benchmark files: `.rep_bench/20260406_021533_jon-6-a8bfs_vs_jon-6-a7bfs.json`, `.rep_bench/20260406_022343_jon-6-a8bfs_vs_jon-6-a7bfs.json`
- `DEBUG=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=900000 cambc run jon-6-a8bfs jon-6-a7bfs maps/cubes.map26 --seed 1 --replay .dist/replays/jon-6-a8bfs_vs_jon-6-a7bfs_cubes_seed_1.replay26`
  `jon-6-a7bfs` wins on resources at turn `2000`
  Log: `logs/timing/jon-6-a8bfs_vs_jon-6-a7bfs_cubes_seed_1.log`
- `DEBUG=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=900000 cambc run jon-6-a8bfs jon-6-a7bfs maps/default_large1.map26 --seed 1 --replay .dist/replays/jon-6-a8bfs_vs_jon-6-a7bfs_default_large1_seed_1.replay26`
  `jon-6-a7bfs` wins on resources at turn `2000`
  Log: `logs/timing/jon-6-a8bfs_vs_jon-6-a7bfs_default_large1_seed_1.log`
- `python tools/run_representative_benchmark.py jon-6-a8bfs jon-6-a7bfs --seeds 1 --jobs 8`
  `4-6`
  Benchmark files: `.rep_bench/20260406_003156_jon-6-a8bfs_vs_jon-6-a7bfs.json`, `.rep_bench/20260406_010146_jon-6-a8bfs_vs_jon-6-a7bfs.json`, `.rep_bench/20260406_014835_jon-6-a8bfs_vs_jon-6-a7bfs.json`

## Current Read
- The one-pass visible-anchor planner is wired into the visible-anchor path. In the `chemistry_class` log, visible anchor turns now show `assault_visible_anchor_resolution_calls=1` and `assault_rank_calls=1` for the selected visible harvester instead of the earlier assess-plus-rerank pattern.
- The assault harvester tracking heartbeat is active. Late assault turns now frequently show `perception_harvester_tracking_skips=1`, while visible harvesters still update through the local visible-tile loop.
- `butterfly` improved in the direct `leeroy-jonkins` repro and now wins that seed, but scout-mode outliers still exist on bottom-fringe assault bots. Those outliers have low perception time and high mode time, so the remaining issue is likely scout target/navigation churn rather than harvester-grid tracking.
- `chemistry_class` is still not solved. It still has assault turns over `2 ms`, including one profiler outlier where `perception_infer_ns` dominated despite harvester tracking being skipped. The plan mechanisms are implemented, but this map still needs a deeper fix for large visible enemy clusters and scout/path churn.
- The full representative benchmark against `jon-6-a7bfs` is neutral at `5-5` after this change.
- The earlier four-bot assault opening wave is wired correctly. `jon-6-a8bfs` now forces diagonal assault spawns on rounds `4,5,6,7` (0-indexed), and the new core regression covers both the schedule and the derived low-resource quota.
- The earlier opening wave is smoke-neutral overall so far: it improves one `default_large1` seat enough to get a core kill, but it also gives back both `default_small1` seats, so the net smoke result moved to `3-3`.
- The visible-anchor soft-fallback bug is fixed. In the new profiled `cubes` replay, the long-lived late-game `BUILD` stalls around a single ring are gone; those bots now either replan or abandon instead of pinning themselves forever on `can_build_sentinel() == false`.
- The enemy-passable-ring bug was real and the fix still stands: enemy roads, markers, and bridges no longer get misclassified as immediate-build rings.
- The immediate-ring scorer fix looks good: it addresses the “just build beside the harvester” complaint and still keeps the smoke benchmark healthy.
- The new ring occupancy order also looks healthy. It keeps sentinel planning biased toward the cheapest ring conversion path without hurting the smoke benchmark.
- The mild depth tie-breaker is acceptable, but it does not fully solve the DNA cross-map pursuit issue by itself. The current log still trends back toward the nearer left-side visible anchor once that anchor remains actionable.
- The new bootstrap egress does reduce tracked early assault cost on `default_large1` (the worst summed tracked early round dropped from about `7.1 ms` to about `6.2 ms`), and it fixes the obvious escape oscillation/backstep behavior.
- The single `cubes` repro is still ugly. Late-game assault bots now churn between `approach` and `scout` on upper-map anchors, so the execute deadlock is gone but the follow-through on that map is still poor.
- This is now at least smoke-benchmark positive again, but DNA-side assault target commitment is still unfinished. The next round should probably tackle that with a more explicit frontier/anchor-handoff rule instead of pushing generic visible-site scoring any harder.
