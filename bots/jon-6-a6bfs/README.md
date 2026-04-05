# jon-6-a6bfs

`jon-6-a6bfs` branches from `jon-6-a5bfs` and is the first implementation pass of the assault-state-machine overhaul based on bots/jon-6-a5bfs/ASSAULT_STATE_MACHINE_REVIEW.md.

## Starting Point
- starts from `jon-6-a4bfs` baseline (bridge/tiling-back bug already fixed)
- all assault bots TLE on every turn in `jon-6-a4bfs`

## A6 Overhaul Status
- re-enabled nearby marker placement so assault claim markers can actually be published and seen by teammates
- replaced the main assault execution loop with a narrower mission:
  claim anchor, plan sentinel ring/direction, clear the ring if needed, build the sentinel, otherwise scout
- removed the normal `build_now -> harass -> support` fallback cascade from the main `execute()` path
- removed the normal random movement fallback from assault travel
- added per-anchor failed-ring tracking so the bot can replan a different ring before abandoning the anchor
- added new focused `a6` tests for claim placement and no-random-fallback behavior
- fixed the main `a6` navigation regression:
  scout travel now still uses the generic mover, but it can build roads again;
  committed ring/clear/build travel is back on the assault-specific mover so it can legally target clearable enemy ring tiles
- tightened scout targeting so assault bots keep a stable enemy-side anchor instead of rotating across predicted harvesters or falling back to home-side frontier drift
- cut the friendly-conveyor blocker hot path:
  `_is_connected_to_harvester()` now has a constant-time fast path from `connected_friendly_conveyors` / `known_connected_harvesters` and caches fallback DFS results per turn
- current focused validation:
  `pytest -q tests/test_jon_6_a6bfs_assault.py tests/test_jon_6_a6bfs_core.py tests/test_jon_6_a6bfs_navigation.py`
  `27 passed`
- first representative benchmark result:
  `.rep_bench/20260405_151017_jon-6-a6bfs_vs_jon-6.json`
  result `3-7` vs `jon-6`
- latest representative benchmark result after the scout/movement fix set:
  `.rep_bench/20260405_152525_jon-6-a6bfs_vs_jon-6.json`
  result `9-1` vs `jon-6`
- conclusion:
  the structural simplification now has a working movement/targeting interface again and is back to benchmark-competitive, but large-map live TLE behavior still needs server confirmation

## Performance Changes vs jon-6-a4bfs

### 1. Memoize `sentinel_attack_tiles` (`assault.py`)
- Added module-level `_SENTINEL_ATTACK_CACHE` keyed by `(origin.x, origin.y, direction.name, max_range_sq)`
- Returns `frozenset[tuple[int,int]]` instead of `set[Position]`
- All 4 membership-test call sites updated to use `(pos.x, pos.y)` tuple form
- Expected saving: eliminates repeated computation for the same (ring, direction) pair across 32+ calls per visible harvester per turn

### 2. Skip conveyor topology refresh for assault bots (`perception.py`, `builder_bot.py`)
- Added `assault_mode: bool = False` parameter to `scan_around`
- When `True`, passes `refresh_connected=False` to `_infer_state_from_grid`
- `builder_bot.py` passes `assault_mode=bool(self.is_assault_role)`
- Expected saving: skips the conveyor-connected BFS that assault bots never need (they never build conveyors)

### 3. Sort BFS direction order once per path (`navigation.py`)
- In `calculate_assault_bfs_path`, `preferred_dirs = _ordered_assault_directions(start, target)` computed once before the BFS loop
- Inner loop uses `preferred_dirs` instead of re-sorting on every node expansion
- Expected saving: eliminates `sorted(8 dirs)` call on every BFS node (50–200 nodes per path)

### 4. Cache `_anchor_assessment` within a turn (`mode_assaulting.py`)
- Added `cache: dict | None = None` kwarg to `_anchor_assessment`, `_best_visible_site`, `_execute_support`
- `execute()` creates `_aa_cache = {}` at the top and threads it through all 7 call sites
- Expected saving: `rank_assault_sites_for_harvester` (32 site evaluations) is called once per harvester position per turn instead of 3–5 times

### 5. Reuse assault BFS paths across turns (`navigation.py`)
- `assault_move_towards()` now validates and consumes `assault_nav_state["bfs_path"]` instead of recomputing BFS every move
- Successful assault moves pop the cached prefix, so a 10-step approach now pays for one BFS rather than ten
- Added `assault_bfs_cache_hits` stat to confirm reuse during debug runs

### 6. Make Bug 2 exit checks cheap (`navigation.py`)
- `_assault_should_leave_bug()` no longer runs BFS just to decide whether wall-following can stop
- Bug exit now uses the existing Bug 2 conditions plus a cheap “is there a goal-progressing walkable step?” test
- Expected saving: removes repeated BFS calls while bugging around large walls or logistics clutter

### 7. Cut assault navigation hot-loop overhead (`navigation.py`)
- `calculate_assault_bfs_path()` now expands raw `(x, y)` tuples instead of `Position` objects
- Replaced repeated temporary-obstacle `set(...)` materialization with direct dict-key membership checks
- Bug follow/side selection now reuses the same temporary-obstacle snapshot for the whole move

### 8. Add assault fast-perception cadence (`builder_bot.py`, `perception.py`)
- Assault builders now use local fast perception only on travel turns where they are already replaying a cached BFS path or active bug route
- Fast scans now still update exploration chunks and nearby marker claims, so scouting/claim logic stays warm
- Full and fast assault scans both skip building HP reads that only the non-assault healing logic consumes
- `_infer_state_from_grid()` now derives visible enemy cores from the remembered visible tiles instead of doing a second nearby-entity controller sweep

### 9. Add per-turn assault TLE instrumentation (`builder_bot.py`, `mode_assaulting.py`, `assault.py`, `navigation.py`, `utils.py`)
- Added opt-in slow-turn profiling with `DEBUG_TURN_PROFILE=true` and backward-compatible `DEBUG_ASSAULT_PROFILE=true`
- Logs now include candidate-site counts, cluster BFS counts/sizes, `can_fire_from` volume, `can_build_sentinel` volume, local ring-occupancy probes, selected ring changes, and `_is_connected_to_harvester` traversal size
- Default slow-turn threshold is `900000` ns and can be overridden with `TURN_PROFILE_THRESHOLD_NS` or legacy `ASSAULT_PROFILE_THRESHOLD_NS`

### 10. Extend slow-turn profiling into navigation and perception (`builder_bot.py`, `navigation.py`, `perception.py`, `utils.py`)
- Slow-turn logs are now generic `turn_profile` lines instead of assault-only logs, so scout/pathfinding spikes are visible too
- Added navigation counters for A* iterations/open-set peaks, micro-plan usage, cache hits, greedy fallbacks, lookahead invalidations, and blocked-move causes
- Added perception counters and subphase timings for snapshot collection, grid update, marker scan, inference, conveyor-topology refresh, harvester tracking, and remembered-grid scan volume
- Profiling state is now only allocated when `DEBUG_TURN_PROFILE` is enabled, so these counters do not add production-turn overhead

### 11. Simplify assault planning into a committed-site, constant-width search (`assault.py`, `mode_assaulting.py`, `builder_bot.py`)
- Builder bots now keep a committed assault site across turns (`anchor`, `ring`, `direction`) and try to reuse it before reranking
- The committed site is invalidated only on concrete failures: dead/retired anchor, unusable ring, stale commitment age, or adjacent/on-ring execution failure
- Travel turns now stay on the committed ring instead of recomputing a fresh site every turn
- Builder-side assault ranking no longer calls `ct.can_fire_from`; planning is now geometry-only with precomputed attack masks
- Ring evaluation is now constant-width:
  score the 4 ring tiles first, compute threat once per ring, and only inspect a small outward-facing direction set for each ring instead of all 8 directions
- Ring scoring now uses cheap stable signals:
  ring usability, front-side alignment, distance, visible uncovered pressure, visible threat, and stickiness to the committed ring/direction
- Adjacent/on-ring execution failures now bail out early instead of falling through into extra support/site work on the same hot turn
- Added focused tests to lock this in:
  `choose_best_site_for_harvester` must not call `legal_fire_fn`
  assault execution must reuse a committed site before reranking

## Current State
- all eleven TLE/perf optimisations above are applied
- assault movement/perception hot-path pass applied
- committed-site assault planner simplification applied
- focused assault + navigation/core tests pass locally (`21 passed`)
- local timing repros on `default_small1` and `default_large1` against `jon-6` show the builder planner at `assault_can_fire_from_calls=0` with hot-turn direction-candidate counts cut down into single-digit / low-teen ranges instead of the previous `28-56`
- smoke benchmark rerun against `jon-6-a4bfs`: `3-3` on the default small/medium/large maps with seed `1`
- benchmark file: `.rep_bench/20260405_021018_jon-6-a5bfs_vs_jon-6-a4bfs.json`
- full representative benchmark rerun against `jon-6`: `9-1` with seed `1`
- benchmark file: `.rep_bench/20260405_115811_jon-6-a5bfs_vs_jon-6.json`
- latest full representative benchmark after the opening bootstrap pass: `9-1` with seed `1`
- benchmark file: `.rep_bench/20260405_133852_jon-6-a5bfs_vs_jon-6.json`
- turn profiler now covers assault, navigation, and perception hot paths
- local timing repro flow now writes logs to `logs/timing/`
- opening assault bootstrap pass now uses a cheap `opening_escape` phase with a no-perception shell escape turn, constant-time bootstrap target selection, deterministic local exit steps, delayed first full refresh, and no core-written assault spawn markers
- assault architecture review document added: `bots/jon-6-a6bfs/ASSAULT_STATE_MACHINE_REVIEW.md`
- assault overhaul proposal added: `bots/jon-6-a6bfs/ASSAULT_OVERHAUL_PROPOSAL.md`
- `v3` replay review now points to a deeper structural problem:
  assault bots can survive the spawn escape, then later enter wall-side or logistics-side 2/3-tile loops that drive repeated `~2100 us` turns on the server

## Implemented Assault Planner Simplification

This section records the simplification pass that landed for the assault planner.

### Profiling Summary
- Assault `mode_us` is the dominant cost on the worst assault turns; perception matters on some turns, but the main repeated burn is site selection
- `approach`, `adjacent`, and `on_ring` turns are all still re-running expensive site ranking
- The hot loop is `choose_best_site_for_harvester` / `rank_assault_sites_for_harvester`, especially repeated `_target_summary_for_site`, `visible_threat_score`, `connected_enemy_logistics_cluster`, and `ct.can_fire_from`
- Navigation itself is not the primary measured bottleneck; assault targeting is causing target churn and preventing navigation from staying cheap

### A. Commit To One Site Across Turns
- Added a persistent assault plan state:
  anchor, ring tile, sentinel direction, and commit round
- Once a bot has selected a site, keep that site for several turns while traveling
- Recompute only when one of these happens:
  anchor dies, ring tile becomes unusable, adjacent build/fire fails, local stall timer trips, or a much better visible anchor appears right now
- Result:
  removes full site ranking from most `approach` turns and many `adjacent` turns

### B. Replace Full Ranking With Two-Stage Selection
- Stage 1: cheap ring shortlist
  only score the 4 ring tiles around the anchor
  use cheap data only: ring classification, distance, enemy core alignment, visible logistics adjacency, blocked status, threat, existing friendly ring coverage, and simple tie-breaks
- Stage 2: constant-width finalize
  evaluate only a tiny outward-facing direction set per ring using precomputed attack masks and visible target summaries
- Result:
  the hot-turn planner now stays in a constant-width search instead of opening up all ring x direction combinations

### Proposed Cheap Ring Heuristic
- For each of the 4 ring tiles, reject immediately if the tile is blocked, permanently unusable, or occupied by a friendly sentinel
- Build one cheap "front" vector for the anchor:
  visible enemy core if known, else weighted visible enemy logistics/turret centroid, else away from our own core
- Score ring tiles with only cheap integer terms:
  `immediate > clearable > unusable`
  `frontness`
  `distance from current builder`
  `visible threat on the ring tile`
  `stickiness to the currently committed ring`
  `visible uncovered pressure reachable from this side`
- `visible uncovered pressure reachable from this side` should be derived from a tiny constant set of outward-facing directions for that side, not all 8 directions
- The ring heuristic should not run `can_fire_from`

### Target Weighting Rules For The Cheap Heuristic
- Core pressure is highest priority
- Enemy turrets are next highest priority
- Connected logistics pressure matters, especially uncovered logistics tiles
- The anchor harvester itself should never be rewarded as a target
- Other enemy harvesters should not get a large flat reward; at most they should contribute as part of visible logistics pressure
- Existing friendly ring sentinel coverage should subtract value:
  if a target is already covered by a friendly ring sentinel, the builder should treat it as low or zero marginal value
- This is deconflict, not a global "do not fire if a friendly sentinel exists" rule:
  we still want sentinels to fire, but we do not want builders to spend time planning duplicate coverage

### C. Remove `can_fire_from` From Planning Entirely
- Do not call `ct.can_fire_from` while ranking candidates
- Do not call `ct.can_fire_from` for finalist selection either
- Use geometry-only heuristics and precomputed attack masks for the full builder-side planner
- Keep only execution-time legality checks that are already required for building or firing actions, such as `can_build_sentinel`
- If geometry ever proves too optimistic in live games, add a rare post-selection fallback outside the hot planning loop, not back into per-candidate scoring
- Result:
  removes one of the most server-suspicious SDK calls from the planner and keeps site selection `O(visible tiles + visible enemies)`

### D. Precompute Per-Anchor Enemy Summaries Once
- For each anchor under consideration, build one per-turn summary:
  cluster membership, threat by ring tile, directional target counts/values, and geometry-based core pressure for each ring/direction bucket
- Reuse that summary for all ring/direction checks
- Avoid rescanning the visible enemy list inside every candidate evaluation
- Result:
  threat is now computed once per ring and direction evaluation is limited to the tiny outward-facing shortlist

### E. Simplify Assault Navigation Around A Locked Plan
- If a committed site exists and the bot is farther than 1 tile from the ring:
  do pure movement only
  no full rerank while traveling
- Use one persistent movement target:
  the ring tile if clearable, otherwise a staging tile adjacent to the ring
- Keep current cached BFS plus bug/wall-follow, but make it subordinate to the locked site
- If bugging or path replay is already active, do not reconsider the assault target unless invalidation fires
- Result:
  reduces retarget churn and makes the existing BFS cache actually matter

### F. Add Hard Budget Bailouts
- If the bot has already done one expensive ranking this turn, do not do another
- If the turn is already hot, reuse the last site and skip expensive reassessment
- If a bot is `on_ring` or `adjacent`, skip support/secondary-site exploration entirely
- If no cached site exists and the bot is over budget, use a cheap fallback:
  closest usable ring toward core/logistics front
- Result:
  adjacent/on-ring execution now bails early on failure instead of doing more site/support work on the same hot turn

### Timing Result
- The builder-side planner no longer emits `assault_can_fire_from_calls`
- Hot assault turns in the local profiler now show drastically fewer direction candidates and enemy rescans than the old `28-56`-candidate planner
- The representative benchmark result against `jon-6` improved to a `9-1` match record on the default representative suite with seed `1`

### Success Criteria
- Cut average assault `mode_us` for `approach` and `adjacent` turns by at least 50%
- Reduce expensive direction finalists from `28-56` to single digits
- Reduce `assault_target_summary_enemy_scans` by at least 70% on hot assault turns
- Eliminate `assault_can_fire_from_calls` from the builder-side planner
- Keep assault behavior broadly intact:
  still commit to live anchors, still prefer core/logistics pressure, still build/fight from ring tiles

## Review Plan: Opening Assault Bootstrap

This section records the next planned simplification pass for the spawn-time
assault TLE seen in the server replays. The main issue is no longer late
assault-site scoring; it is that newly spawned assault bots can get stuck on
their diagonal spawn tiles while still paying full bootstrap cost every turn.

### Server Replay Diagnosis
- The first long stalls happen on the opening diagonal assault spawn tiles around the core, not near enemy anchors
- When a spawned assault bot does not leave its tile, its server `execTimeUs` stays near the TLE threshold for many consecutive turns
- The current state machine couples perception width to active movement replay:
  if the bot is not already bugging or replaying a cached assault BFS path, it falls back to a full scan
- That means a blocked spawn bot keeps re-running expensive bootstrap work from the densest tile on the map

### A. Replace Motion-Gated Full Scan With Refresh-Gated Full Scan
- Keep full scan as a refresh primitive, but stop using it as the default steady-state mode for stationary assault bots
- Make cheap local scan the default assault perception path
- On the first few assault turns, while the bot is still on or adjacent to its spawn/core shell, do not force a full refresh
- Run full refresh only on explicit invalidation events:
  scout/anchor target invalidated
  enemy contact changed materially
  coarse frontier chunk changed
  bot has escaped the spawn/core shell and has no valid bootstrap target
  periodic heartbeat every few turns
- Do not let "move failed this turn" force a full scan next turn

### B. Add Opening Bootstrap Cache And Stationary Reuse
- Separate "bootstrap target selection" from "movement success"
- Add an `opening_escape` bootstrap phase for newly spawned assault bots
- Once a spawn-time scout target or anchor hypothesis is chosen, keep reusing it across stationary turns until an explicit invalidation fires
- If the bot stays on the same tile and the cached target is still valid, skip symmetry refresh, skip predicted-harvester rebuild, and skip global scout retargeting
- The stationary assault turn should become:
  cheap local perception
  validate cached target
  retry movement
- This keeps "find an assault target" logically stable whether or not the move succeeded

### C. Remove Unused Assault Spawn Markers
- The core currently places `ASSAULT_SPAWN` markers when assault bots spawn
- Those markers are not consumed by builder perception and are not part of symmetry inference
- Remove their creation and placement entirely
- This cuts a small amount of nearby-marker noise and removes dead coordination state

### D. Keep One Cheap Opening Escape Layer
- Opening assault bots should still spawn on diagonals
- The simplification is not to change the spawn geometry; it is to cheapen the first few turns
- While the bot is still on or adjacent to its spawn tile, use a very small local exit policy:
  keep one cached outward bootstrap target derived from `spawn_slot` and `core_pos`
  only search for the next local escape step toward that target
  delay the first full global scout/bootstrap refresh until after leaving the spawn/core shell
- Random movement should remain only as a last-resort unblocker, not as the primary opening policy
- This makes the opening turn cost closer to ordinary travel instead of ordinary global planning

### Algorithmic Conciseness Check
- Cheap local scan is bounded by local vision and should be the default `O(local visible tiles)` path
- Full refresh becomes amortized work instead of repeated every blocked turn
- Cached bootstrap target reuse prevents repeated symmetry / frontier / prediction recomputation on unchanged state
- Removing spawn markers is strictly simpler because it deletes write-only coordination logic
- The planned opening escape layer does not introduce a second planner; it only adds a tiny pre-planner that picks an outward bootstrap target once, then reuses it until normal assault logic can take over

### Algorithmic Validity Check
- Full scan still exists, so the bot does not become blind; it is just delayed until the bot has escaped the densest spawn pocket or an invalidation demands it
- Periodic heartbeat refresh preserves correction against stale remembered state
- Cached target reuse is safe because it is guarded by invalidation:
  visible enemy updates, target expiry, chunk refresh, or contact change can force recomputation
- Removing spawn markers is safe because they are not used by the current builder logic
- Keeping diagonal assault spawns is compatible with this plan because the issue is the repeated bootstrap cost while stuck, not the spawn role itself

## Implemented Opening Assault Bootstrap Simplification

### What Landed
- Assault builders now treat the opening core shell as a dedicated `opening_escape` phase instead of entering the full global assault bootstrap immediately
- While `opening_escape` is active, assault builders now take a dedicated no-perception turn path before any normal scan work runs
- The opening phase keeps one cached outward bootstrap target derived from `spawn_pos` / `spawn_slot` and `core_pos`
- Bootstrap target selection is now constant-time over the shell perimeter instead of scanning the entire map for an outside-shell target
- Movement during `opening_escape` is now a deterministic local step chooser over the 8 adjacent moves:
  prefer leaving the core shell, then reduce distance to the outward bootstrap target, then preserve outward progress
- The first full global refresh is delayed until the bot has actually left the core shell
- If the builder is locally blocked for several opening turns in a row, only then does it allow a random fallback move
- The core no longer writes `ASSAULT_SPAWN` markers when spawning assault builders

### Intended Effect
- Spawn-time assault turns should stay on an `O(local moves + local visible tiles)` path instead of repeating symmetry, scout-target selection, and global movement bootstrap from the densest tile on the map
- A blocked opening builder should now stay cheap while retrying the same outward escape plan instead of re-running the entire assault bootstrap each turn
- Removing the unused spawn markers deletes dead coordination work and reduces nearby-marker noise in the spawn pocket

### V2 Replay Diagnosis
- The second server replay bundle showed that some diagonal assault spawns on large maps were still TLEing from their very first executable turn and then staying pinned near `2005 us` for almost the entire game
- The strongest offenders were large-map diagonal assaults such as:
  `game_2` bots spawned at `(15,34)` and `(13,34)` around core `(14,35)`
  `game_5` bots spawned at `(11,15)` and `(9,15)` around core `(10,16)`
- Those bots were not reaching late assault logic first; they were already over budget on the opening bootstrap path
- The updated hypothesis from those replays was:
  even fast local perception was still too expensive for the opening shell on the server
  the earlier corner-safe bootstrap target fix accidentally introduced an `O(map area)` search on the first opening turn
- The corrective simplification therefore became:
  skip perception entirely on opening-escape turns
  replace the map-area bootstrap target search with a constant-size shell-perimeter search

### Validation Snapshot
- Focused regression tests now cover:
  committed-site reuse
  opening-escape short-circuit before inference
  opening-escape turn skips perception entirely
  no core-written assault spawn markers
  fast perception during the opening diagonal assault phase
  corner-spawn bootstrap targets that must leave the core shell
- Latest focused test run:
  `pytest -q tests/test_jon_6_a5bfs_assault.py tests/test_jon_6_a5bfs_core.py tests/test_jon_6_a5bfs_navigation.py`
  `21 passed`
- Targeted large-map benchmark after the v2 opening fixes:
  `.rep_bench/20260405_133801_jon-6-a5bfs_vs_jon-6.json`
  result `3-1` on `binary_tree.map26` and `cubes.map26`
- Latest representative benchmark after this opening-bootstrap pass:
  `.rep_bench/20260405_133852_jon-6-a5bfs_vs_jon-6.json`
  result `9-1` vs `jon-6`
- The opening TLE-oriented simplification is now backed by the focused regression suite and a benchmark result in line with the earlier committed-site planner branch

## TODO
- [ ] tune the new `jon-6-a6bfs` anchor/ring scoring so the simplified state machine is competitive again
- [ ] read through `bots/jon-6-a6bfs/ASSAULT_STATE_MACHINE_REVIEW.md` while iterating on the rewrite
- [ ] review `bots/jon-6-a6bfs/ASSAULT_OVERHAUL_PROPOSAL.md` while refining the implementation
- [ ] verify TLE is resolved via camb match API submission
- [ ] inspect server match traces to confirm the assault-bot TLE is actually gone
- [ ] run local replay with `DEBUG=true DEBUG_TURN_PROFILE=true` and inspect the new slow-turn `turn_profile` lines on the offending rounds
- [ ] re-check the server replay opening stalls on the diagonal spawn tiles after the opening bootstrap simplification
- [ ] if server TLE persists after these cuts, consider replacing Bug 2 with a fully local greedy/wall-follow controller that never rebuilds global assault paths mid-approach
