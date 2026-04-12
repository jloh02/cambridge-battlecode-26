# CODEX Scratchpad

## Active Long-Form Task

- Current active batch, 2026-04-12: enemy-builder blocked-edge reroute for
  a9 resilience. User priority is improving resilience against
  `jon-6-a9bfs-surround` while avoiding TiEq regressions against `jon-6`
  and `leeroy-jonkins`; win-rate movement is noisy and secondary. Highest-ROI
  narrow primitive: when an economy or tiling builder's ACTUAL next step is
  blocked by a visible enemy builder, mark only that blocked tile as a
  short-lived temporary obstacle so the existing pathfinder reroutes around
  the blocker. This differs from rejected hard threat reroutes because it does
  not react to merely seeing an enemy and does not abandon direct-core routing;
  it only handles a concrete blocked movement edge.
- Planned implementation surface: `navigation.try_pathfinding_move()` for
  FINDING_ORE/EXPLORING/HIJACKING movement, `mode_tiling_back._navigate_and_build()`
  for return-lane builders, and runtime-substrate tests proving enemy-builder
  blockers get TTL obstacles while no broad enemy-visible behavior is added.
  Acceptance guardrail for local validation: a9 avg/worst TiEq should improve
  or at least the low-output tail should shrink, while `jon-6` and
  `leeroy-jonkins` average TiEq should not materially regress versus
  `.dist/reports/got-any-grapes_ax_splice_g16.json` (`jon-6` 36,979 avg,
  `leeroy` 36,856 avg).

- Direction update from user, 2026-04-12: restore the broad blocked-edge
  reroute that produced `.dist/reports/got-any-grapes_enemy_builder_blocked_edge_g16.json`
  (`jon-6-a9bfs-surround` **12-4**, avg TiEq **32,997**) and address the
  leeroy regression separately by mirroring leeroy's rush: opening assault
  builders should seek the enemy core and build multiple sentinels that can
  fire on the core. New active batch is broad enemy-builder reroute +
  opening RUSH mode + core-first sentinel targeting. No remote testing until
  focused tests, compileall, deterministic smokes, and g16 are complete.
- Revision during cheap smoke: blind opening RUSH caused a deterministic
  `default_small1` seed 1 a9 collapse (**21 delivered Ti** vs the broad
  reroute smoke's **29,730 delivered Ti**), so RUSH is now reserved for
  later bonus assault after the existing economy proxy can fire. Opening
  assault remains on the previous bounded assault path; core-first sentinel
  targeting stays.
- User decision after local g16: accept the core-first sentinel candidate
  despite lower a9 avg TiEq because it produced higher local win rate:
  `.dist/reports/got-any-grapes_broad_blocker_corefirst_g16.json`, **33-15 /
  68.8%** overall; `jon-6` **13-3**, avg TiEq **35,361**;
  `jon-6-a9bfs-surround` **10-6**, avg TiEq **19,122**; `leeroy-jonkins`
  **10-6**, avg TiEq **23,864**. Automatic RUSH assignment remains disabled
  (`RUSH_ASSIGNMENT_MIN_ROUND = 10000`) because both blind opening and bonus
  RUSH auto-assignment failed the a9 smoke. Commit this state, then run 2
  remote match tests per opponent per seat order.
- Commit: `35c9e2c` (`Improve grapes pressure resilience`).
- Remote r4-per-opponent validation on `35c9e2c` (12 match tests / 60 games):
  **28-32 overall**, avg TiEq **24,840**, worst **0**. Remote timing remains
  severe: builder turns **89.0% >0.5ms / 65.8% >1ms / 57.3% >1.5ms /
  50.8% >2ms**, `tled_turns` **580,938** across analyzed team-games.
  Every game flagged `small_loop`, `high_tle_pressure`, and
  `low_builder_progress`; `travel_without_build` appeared in **44/60**.
  By opponent:
  - `jon-6`: **8-12**, avg TiEq **24,419**, worst **1,030**.
  - `jon-6-a9bfs-surround`: **10-10**, avg TiEq **24,272**, worst **470**.
  - `leeroy-jonkins`: **10-10**, avg TiEq **25,828**, worst **0**.
  Decision: do not promote. Keep commit as user-requested snapshot and next
  target should be runtime/perception, especially stale conveyor/building
  caching, because remote TLE pressure still contaminates strategy results.

- Current active batch, 2026-04-12: narrow axionite splice executor.
  Live code already has `axionite_planner.plan_axionite_foundry_placement`
  and per-builder `pending_axionite_plan`, but axionite remains disabled
  in `utils.get_eligible_ore_locations()` because the tiling-back executor
  cannot build the foundry/support conveyors. Highest-ROI batch is to finish
  only the cheap, local, already-planned splice case: require the raw-ax
  conveyor to be the builder's current harvester access tile, require the
  refined-output conveyor to be buildable from that same local action radius,
  execute raw conveyor / foundry / refined output before normal return routing,
  then resume normal tiling-back from the refined output tile toward the core.
  This uses only private builder state plus visible grid data and existing
  controller `can_build_*` checks; it does not add shared globals or marker
  coordination.
- Immediate action: implement the executor surface in `states.py`,
  `axionite_planner.py`, `utils.py`, `mode_finding_ore.py`, and
  `mode_tiling_back.py`; add focused runtime-substrate tests for the planner
  current-position constraint, foundry pending action, ordered executor, and
  ax eligibility gate. Cheap validation first: targeted pytest, compileall,
  tiling regression subset, then deterministic local smoke before any g16.
- Compaction-safe resume point: if interrupted, inspect these functions first:
  `utils.get_eligible_ore_locations`,
  `mode_finding_ore._build_harvester_and_switch_mode`,
  `axionite_planner.plan_axionite_foundry_placement`,
  `mode_tiling_back._execute_pending_build`, and
  `mode_tiling_back.execute`.
- Batch result, 2026-04-12: implementation and cheap validation passed, but
  the batch is not remote-ready and should not be committed yet. Targeted
  runtime-substrate tests passed **105**, `test_analyze_replay.py` passed
  **3**, tiling regression subset passed **6**, and `compileall` passed.
  `git diff --check` still fails only on pre-existing trailing whitespace in
  dirty `FIRST_LONGFORM_PROMPT.md`, not on touched files. Deterministic
  `default_small1` seed 1 vs `jon-6-a9bfs-surround` under `--tle 2` won by
  titanium tiebreak with **9,970 delivered Ti** for got-any-grapes; local
  replay timing stayed all-zero and is not timing evidence.
- Local g16 no-TLE for the axionite splice executor:
  `.dist/reports/got-any-grapes_ax_splice_g16.json`, **30-18 / 62.5%**
  overall, avg TiEq **29,668**, worst TiEq **0**, local TLE turns **0**
  with all local timing buckets zero/unusable. By opponent:
  `jon-6` **13-3 / 81.2%**, avg TiEq **36,979**, worst **0**;
  `jon-6-a9bfs-surround` **6-10 / 37.5%**, avg TiEq **15,169**, worst
  **570**; `leeroy-jonkins` **11-5 / 68.8%**, avg TiEq **36,856**, worst
  **0**. Seat split was balanced; a9 was 3-5 in each seat.
- Axionite activation evidence: across all 48 g16 games, got-any-grapes mined
  **0 axionite**, delivered **0 refined axionite**, and no replay-analysis
  output contained the axionite plan/executor log lines. Interpretation: the
  executor is mechanically covered but dormant under current target-selection
  and readiness gates. Forcing it to activate would require a deliberate
  ore-target priority tradeoff and should be treated as the next separate
  behavior batch, not a bug fix. Decision: revise/no remote validation and no
  commit from this batch as-is.
- MAE from this batch:
  Mechanistic: pending foundry/conveyor executor is bounded to local visible
  tiles and existing `can_build_*` checks; no shared state or broad scans.
  Algorithmic: current ore selection still overwhelmingly pursues titanium;
  axionite remains inert unless target selection explicitly values viable
  foundry splices. Emergent: the main a9 losses remain first-lane/productivity
  failures with `small_loop`, `low_builder_progress`, and
  `travel_without_build`, not missing axionite.
- Stop/next target: do not remote-test this batch. The next plausible ROI is
  tradeoff-aware target selection or first-lane recovery under pressure; either
  can materially affect win rate and execution safety, so it needs an explicit
  acceptance criterion before benchmarking.

- 2026-04-12 — **remote r2 batch 15** (post cinnamon_roll bridge fix
  + TILING_BACK A* budget bump + port spread_offset). 30 games,
  15-15 / **50%** overall:
  - `jon-6`: 6-4 / 60%
  - `jon-6-a9bfs-surround`: 4-6 / 40%
  - `leeroy-jonkins`: 5-5 / 50%

  Match IDs: e7d4d6cc, 7c689f9f, 9a08e9d7, e81bbf77, 459aff45,
  815e7375. The last two (leeroy) were packaged at HEAD with the
  port-spread + ax planner scaffolding since the rate limit forced
  a retry, the other four shipped at the pre-spread state.

  No more 0-delivery cinnamon_roll games — that validation is good.
  But overall win rate is stuck in the 50-57% range across b12-b15.
  Batch 10's 70% was the outlier; we need structural improvements
  (axionite routing, splitter-aware parallel lanes on single-line
  ore maps) beyond navigation fixes to push higher.

- 2026-04-12 — **axionite pipeline scaffolding landed (half-wired)**.
  New `axionite_planner` module with `plan_axionite_foundry_placement`
  that enforces the geometric constraints a viable foundry needs:
  raw-ax conveyor adjacent to the ax harvester, Ti input from an
  already-connected friendly conveyor pointing INTO the foundry,
  refined-ax output conveyor heading toward the core. Wired into
  `_build_harvester_and_switch_mode` so axionite ore commits only
  go through when the planner approves. Executor side (tiling-back
  walker actually building the foundry + conveyors) is still a
  pending task — enabling `get_eligible_ore_locations` before the
  executor lands regressed default_small2 seed 1 from 42900 → 9880
  mined because raw ax routed directly to the core is destroyed.

- 2026-04-12 — **cinnamon_roll 0-delivery root cause found and fixed**.
  Every local+remote match that landed on cinnamon_roll had resulted
  in 0 Ti delivered across 2000 turns with the same signature: 5
  harvesters + ~50 conveyors alive, `titanium_collected = 0`,
  1500-1700 turn no-progress streaks clustered near the wall edges,
  and `failure_signals = [small_loop, high_tle_pressure,
  low_builder_progress, travel_without_build]`. Two compounding root
  causes:

  1. TILING_BACK A* time budget was 450μs / 220 iterations. On the
     spiral terrain cinnamon_roll/flowers/donut present, the A*
     debug log showed it hitting the TIME limit after ~50 iterations
     with 80-130 nodes still in the open_set — the planner was
     terminating BEFORE any bridge candidate was added to the open
     set (the needs_bridge gate fires only at wall-adjacent tiles,
     which A* could not reach in 50 iterations on a spiral layout).
     Fix in 9b20e30: bump the tiling-back A* budget to 650μs / 260
     iterations.

  2. The bridge_transit planner (which plans a non-bridge walk from
     bridge_start to bridge_end after A* returned a BRIDGE action)
     failed indefinitely on spiral maps because the wall was the
     ONLY crossing — there was no non-bridge path to plan. The bot
     sat in `pending_bridge_plan` cooldown loops forever. Fix in
     74c2766: when the transit A* fails, call `ct.build_bridge`
     directly from bridge_start and drop the transit requirement.
     The bridge handles resource transport across the wall; the
     builder does NOT need to physically cross.

  Local smoke vs jon-6 seed 1: **13570 Ti mined** on cinnamon_roll
  (previously 0), seed 2: **30810 Ti mined**. default_small2 seed 1
  still wins 54440 Ti mined.

- 2026-04-12 — **remote r2 batch 11 REGRESSED** (commits ac60bc9 +
  358c8ba + 5439bea + 694f8cf). 30 games, 16-14 / **53.3%** overall,
  down 17pp from batch 10. Per-opponent:
  - `jon-6`: 7-3 / 70% (-20pp), >2ms 62.4% (vs 41.0% in batch 10)
  - `a9bfs-surround`: 5-5 / 50% (-20pp), >2ms 52.8%
  - `leeroy-jonkins`: 4-6 / 40% (-10pp), >2ms 47.7%
  - Small-loop events up 44% (920 → 1324 across 30 games)

  Root cause pinned to 5439bea's behavioral changes: the small-loop
  killer recovery was tearing down assault-mode `committed_site` /
  `execute_state` / `bootstrap_state` on stationary assault bots that
  were correctly camping+attacking an enemy, and the forced
  random-move escape escalation was then displacing them away from
  the target. That combo produced a worse loop pattern than the one
  it was designed to fix, which is why small-loop events went UP.

  Fix: commit 1853e13 surgically reverts ONLY the 5439bea behavioral
  bits (assault state reset + forced escape) while keeping the
  batch 11 bugfixes that also shipped: ac60bc9 + 358c8ba + 694f8cf
  (hot-path dict cleanup) + 306d68f (navigation None-grid-entry crash
  in the blocker branch) + 90370ac (perception SNAPSHOT_CHECK_INTERVAL
  16→4 + wall-tile get_tile_building_id skip).

  Match IDs: 81adc0d2, a1563035, 3cf2aeae, bb06bcb2, 47c29c09,
  778ca09e.

- 2026-04-12 — **remote r2 batch 10 (post hot-path dict cleanup 7a12194 +
  core-bridge hoist e1924d4)**. 30 games, 6 matches:
  - `jon-6`: 9-1 / **90%** (A: 5-0, B: 4-1), 351k us / 246k opp, >2ms 41.0%
  - `jon-6-a9bfs-surround`: 7-3 / **70%** (A: 4-1, B: 3-2), 388k / 320k, >2ms 56.7%
  - `leeroy-jonkins`: 5-5 / **50%** (A: 3-2, B: 2-3), 300k / 314k, >2ms 55.4%
  - **Overall 21-9 / 70%**, aggregate >2ms 51.1% / >1.5ms 59.0% / >1ms 72.0%.

  Compared to remote r2 batch 1 (47% overall, jon-6 50%, a9 30%, leeroy
  60%): **+23pp overall**, jon-6 +40pp, a9 +40pp, leeroy -10pp. Biggest
  remaining weakness is leeroy — we are underwater on delivery (300k vs
  314k) which exactly matches the 5-5 tie. jon-6 and a9 delivery margins
  are both firmly positive. Timing pressure is roughly unchanged from
  batch 1 but win rates improved significantly, which validates the
  anytime-resumable pipeline: we are winning despite >50% of turns
  taking >2ms remotely.

  Match IDs: a4609f28, e7cf8c6d, 25ba1636, 13b6a8b8, 955be45c, 5f441ea1.

- 2026-04-12 — **analyzer port-count fix**. The original
  `pipeline_graph.core_port_occupancy` was wrong: it counted only the
  END-OF-GAME transport buildings sitting on the 12 cardinal approach
  slots. That under-counted real deliveries because (1) buildings
  destroyed mid-game stopped showing, (2) bridges that delivered into
  the core were not counted as "ports", and (3) the snapshot disagreed
  with `delivered_titanium > 0` whenever the bot had successfully
  delivered earlier in the game. The user flagged this directly. Fixed
  by adding a per-team `core_delivery_sources` Counter that the
  `distributeResources` handler increments by SOURCE position whenever
  the destination is a core tile, then exposing it in
  `core_delivery_port_summary` as `active_source_ports` /
  `source_top1_share` / `source_top3_share` / `source_top_ports`. Use
  these new fields for the "how many ports actually fed the core" view
  going forward; the old `pipeline_graph.core_port_occupancy` is still
  there but only as the end-of-game snapshot.

- 2026-04-12 — **per-map delivery audit (n=83 games across all known
  replay-analysis files)**. Aggregated `delivered_titanium`, port count,
  small_loop_max per map per side using the known TEAM_A/TEAM_B mapping
  for batches 1/3/7/8. Ranked by `(avg_ours - avg_opps)` to surface the
  maps where got-any-grapes throughput is lowest relative to opponent.

  **NOTE**: the table below uses the OLD destination-side port count
  (active_ports), because old replay-analysis files predate the new
  source-side metric. After the analyzer fix above, future audits
  should use `active_source_ports` and `source_top1_share` instead;
  re-running analyze_replay against the cached replays would refresh
  these for the existing files.

  **Worst maps (terrain-heavy + 0-1 ports + small_loop_max ~1900-2000)**:

  | map                | n | diff   | avg ports | win% | sloop_max |
  |--------------------|---|--------|-----------|------|-----------|
  | castle_keep        | 2 | -39865 | 0.0       | 0%   | 1970      |
  | donut              | 2 | -34240 | 1.5       | 0%   | 1917      |
  | battlebot          | 1 | -29710 | 0.0       | 0%   | 1970      |
  | default_medium1    | 1 | -27830 | 0.0       | 0%   | 1903      |
  | cubes              | 1 | -20370 | 0.0       | 0%   | 1926      |
  | cinnamon_roll      | 4 | -18460 | 0.8       | 0%   | 1621      |
  | arena              | 4 | -18335 | 0.5       | 0%   | 1076      |
  | settlement         | 1 | -17280 | 7.0       | 0%   | 1951      |
  | tree_of_life       | 1 | -15840 | 0.0       | 0%   | 1974      |
  | sierpinski_evil    | 3 | -13029 | 2.3       | 0%   | 1804      |
  | flowers            | 3 | -12326 | 1.0       | 0%   | 1949      |

  **Best maps (open terrain + win 100%)**:

  | map                  | n | diff   | avg ports | win% |
  |----------------------|---|--------|-----------|------|
  | thread_of_connection | 2 | +33835 | 2.5       | 100% |
  | pls_buy_cucats_merch | 1 | +25430 | 0.0       | 100% |
  | shish_kebab          | 1 | +19750 | 6.0       | 100% |
  | first_sound          | 2 | +16370 | 0.0       | 100% |
  | the_great_divide     | 2 | +14365 | 5.5       | 100% |
  | minimaze             | 5 | +13760 | 0.6       | 100% |
  | tiles                | 1 | +12480 | 1.0       | 100% |

  **Diagnosis (MAE)**:
  - **Mechanistic**: bridge expansion was gated to fire only when an
    immediate cardinal neighbour was a wall/non-passable building. On
    spiral maps the bot walks ALONG the spiral arm with free neighbours
    in front and behind, so the gate stayed closed and bridges never
    got enqueued. The candidate filter then rejected perpendicular
    bridges (zero progress_dot, zero raw_h delta) — exactly the
    perpendicular escapes that spiral terrain demands. **Fixed in
    commit 57e251b**: gate now also fires when target is far away
    (>=10 manhattan), and the filter accepts non-strictly-worsening
    candidates when the wall-escape gate is active.
  - **Algorithmic**: core port slots were committed by hash-spread but
    upstream chains often broke before reaching the slot, leaving
    orphan stub conveyors that wasted real estate. **Fixed in commit
    daf3aa1**: `_assign_core_lane_slot` now penalises slots that hold
    a friendly transport tile NOT in `connected_friendly_conveyors`.
  - **Emergent**: builder_max_small_loop_streak was 1500-2000 on
    almost every losing map — builders cycle for nearly the full
    game in a 1-3 tile pattern. The previous loop killer was
    self-defeating because it reset its streak counter on every mode
    flip. **Fixed in commit daaa166**: history accumulates across
    all modes and recovery does not force a mode change, so the
    streak survives mode flapping and recovery is gentle enough to
    let normal planning re-enter naturally next turn.

  Recent commits since the prior committed batch (7e92424):
  - b8557dc — generic small loop killer (initial version)
  - 0e2b502 — defense early-out when no visible enemies
  - 57e251b — bridge filter relaxed for spiral terrain
  - daf3aa1 — orphan-aware core slot scoring
  - daaa166 — cross-mode small loop tracking with gentler recovery

- 2026-04-12 — **anytime-return pipeline + perception SDK reduction + jon-6
  port batch landed locally**. Changes: (1) `timing.TimingGovernor.has_budget_for`
  helper plus `PERCEPTION_OPTIONAL_NS` / `MODE_ENTRY_NS` / `LOOKAHEAD_BUILD_NS`
  / `SNAPSHOT_RESERVE_NS` constants; (2) in-snapshot time gate inside
  `_collect_visible_snapshot` that truncates the tile loop when the hard
  budget runs low; (3) env caching for WALL/EMPTY tiles, skipping per-tile
  `get_tile_env` on already-known static terrain; (4) skip per-tile
  `get_tile_builder_bot_id` — builders now come from `get_nearby_units()`
  only, saving ~55 SDK calls per full scan; (5) building-id reuse cache:
  when the building_id at a tile matches the previously stored
  `tile_data["building_id"]`, hydrate type/team/direction/bridge_target from
  cached grid data without SDK calls (only HP is re-queried); (6) post-
  perception + pre-defense time gate in `builder_bot.run()` that bails
  before mode execution if the remaining hard budget is below
  `MODE_ENTRY_NS`; (7) time-gated lookahead build in
  `mode_tiling_back._navigate_and_build`; (8) A* time guard widened from
  80μs → 200μs; (9) road-destroy-before-conveyor bug fixed — roads are
  paved over directly, never destroyed first; (10) jon-6 friendly-blocker
  yield policy ported to `navigation.try_pathfinding_move` and
  `mode_tiling_back._navigate_and_build` — only mark a blocked friendly
  builder as a temp obstacle when we should actually route around them
  (higher-priority id or attached to a harvester route); (11)
  `_visible_matching_friendly_conveyor` now matches SPLITTER and
  ARMOURED_CONVEYOR in addition to CONVEYOR, so we do not treat a correctly-
  aimed friendly splitter/armoured conveyor as a rebuild target; (12) SDK
  upgraded to `cambc 1.6.3`, `BATTLECODE_EXPLAINER.md` updated with 1.6.3
  constants (SENTINEL_STUN_DURATION=5 etc.).
- Cheap validation for the batch: runtime substrate suite is **96 passed**
  (added 6 new tests covering the anytime gates, env caching, skip-per-tile-
  builder-bot-id, snapshot truncation, building-id cache, road-preservation,
  and the jon-6 blocker yield policy), `compileall` passed, and
  `git diff --check` passed.
- Local g16 no-TLE vs `got_any_grapes_anytime_g16.json`: **22-26 overall /
  45.8%**, avg TiEq 22,342, worst TiEq 0, local TLE turns 0. By opponent:
  jon-6 **11-5 / 68.8%**, a9 **8-8 / 50.0%** (up from 4-12 baseline),
  leeroy **3-13 / 18.8%** (down from 9-7 baseline). Local execTimeUs is
  still all-zero on cambc 1.6.2, so local bucket timing is unreliable. The
  local dip vs the 24-24 baseline is within noise; the remote matches below
  are the authoritative signal for this batch.
- Remote r2 batch 1 (BEFORE the jon-6 blocker port and `_visible_matching_*`
  fix): **14-16 / 47% overall** across 30 games. By opponent:
  jon-6 **5-5 / 50%** (+10 vs 4-6 baseline),
  a9 **3-7 / 30%** (+10 vs 2-8 baseline),
  leeroy **6-4 / 60%** (+30 vs 3-7 baseline). Timing pressure vs the prompt's
  74.7-83.6% >1ms / 59.7-80.1% >1.5ms / 51.8-75.8% >2ms baseline:
  jon-6 **62.1% >1ms / 41.4% >1.5ms / 34.5% >2ms**,
  a9 **72.2% / 63.3% / 55.9%**,
  leeroy **74.7% / 67.9% / 64.7%**. jon-6 >2ms rate dropped dramatically
  (≈-20 to -30 points); a9 and leeroy improved modestly.
- Remote timing is **bimodal**, not uniform. Per-game analysis shows some
  games at 0.0-2.5% >2ms (gates catching TLE cleanly) while others are at
  80-97% >2ms — the latter are lategame situations with many visible
  buildings that make each full perception explode on SDK calls. The
  building-id reuse cache and in-snapshot time gate added after r2 batch 1
  are the targeted fixes for that lategame disaster mode.
- Remote r2 batch 2 (post jon-6 blocker port + post matching-conveyor fix
  + post building-id cache + post in-snapshot gate): queued with match IDs
  654061f4, 543c9fbf, 6ea33a9f, cd5235a1, f705e257, 99ccd742. Waiting for
  completion to confirm additional improvement; analysis will aggregate the
  same per-opponent + timing-pressure metrics as batch 1.
- Remaining known hygiene gap: `_visible_protected_pipeline_at` can protect
  a friendly pipeline that is not in our own `tiled_back_positions`, which
  is the action-level conveyor ownership bugfix and should stay, but it may
  also be over-protecting in edge cases where an orphan wrong-direction
  conveyor is left on our path. No evidence yet that this is net harmful —
  defer until replay review shows a concrete failure mode.
- Current active batch, 2026-04-12 (historical, superseded): non-semantic
  hot-path allocation cleanup.
  After rejecting the in-place navigation-state patch, keep state semantics
  untouched and target only local temporary allocations: replace
  `mode_tiling_back._future_path_keys()` path copying with bounded iteration,
  and replace full sorting in `mode_assaulting._candidate_ore_sources()` with
  top-6 selection. Full scope: two helper edits plus focused tests proving the
  selected ore-source set remains identical to sorted top-6 and future path
  reservation only consumes the requested prefix. No benchmark until cheap
  validation and bug audit pass.
- Pre-benchmark audit for non-semantic allocation cleanup: touched call paths
  are `_future_path_keys()` used only for pipeline-claim reserved marker tiles
  and `_candidate_ore_sources()` used in assault predicted-harvester inference.
  Invariants checked: returned reserved positions are identical for the first
  `PIPELINE_CLAIM_PATH_RESERVE_STEPS`, path iterables are not mutated, marker
  placement safety filters are unchanged, the ore candidate set matches sorted
  top-6 by the existing `(distance-to-core, x, y)` key, no marker protocol or
  shared-state model changes are introduced, and no unbounded scan is added.
  Edge cases checked: generator paths, short paths, bridge path entries,
  fewer-than-six ore sources, and `core_pos is None` fallback key behavior.
  Cheap validation: runtime-substrate 87 passed, py_compile passed, compileall
  passed, and `git diff --check` passed.
- Rejected non-semantic hot-path allocation cleanup: same-schedule g16 was
  21-27 overall / 43.8%, avg TiEq 20,198, worst 0; by opponent `jon-6` 11-5,
  a9 6-10, `leeroy` 4-12. This is better than the rejected in-place state
  patch but still below the current-live local baseline in the prompt and not
  a meaningful timing validation because local `execTimeUs` remains all zero.
  Decision: reverted the two helper edits and tests. Remaining obvious
  allocation-only changes are likely below benchmark noise; further meaningful
  improvement now requires behavior-coupled pipeline, defense, or perception
  time-gating tradeoffs.
- Current 2026-04-12 stop reason: no new bot-code changes from this session
  are retained. Two mechanistic/runtime-only batches were tried, validated, and
  rejected on same-schedule g16; both were reverted. Post-revert cheap
  validation passes: runtime-substrate 85 tests, compileall, and
  `git diff --check`. The remaining plausible ROIs require meaningful
  tradeoffs in win rate, TiEq, or execution safety: e.g. perception time
  deferral can stale topology/ore knowledge, pipeline recovery changes can
  alter first-lane completion, and defense/sabotage changes have already shown
  matchup-coupled regressions. Next session should choose one explicit
  behavior-coupled batch with acceptance criteria before benchmarking, rather
  than another allocation-only micro-patch.
- Current active batch, 2026-04-12: navigation-state allocation hardening.
  Highest-ROI first change is mechanistic, not strategic: the live
  `navigation.compute_pathfinding_step()` still defensively copies the
  per-builder pathfinding state and cached path list on every movement/planning
  turn. Each builder owns its private `pathfinding_state`, and callers
  immediately replace it with the returned state, so mutation-in-place is legal
  under the execution model and should preserve behavior while reducing hot-path
  allocation pressure. Scope: update `navigation.compute_pathfinding_step()` to
  keep the same state object/path list, expire temporary obstacles in place,
  preserve planner invalidation semantics, and add focused runtime-substrate
  tests that prove cached movement no longer clones state while stale temporary
  obstacles still expire. Benchmarking is deferred until tests, compile, diff
  check, and a bug audit pass.
- Pre-benchmark audit for navigation-state allocation hardening: inspected the
  only live callers (`mode_tiling_back._navigate_and_build()` and
  `navigation.try_pathfinding_move()`), both of which immediately assign the
  returned state back to `bot.pathfinding_state`; no shared/global coordination
  is introduced. Invariants checked: target-change invalidation still clears
  path and planner state, cached path validation still trims/clears stale
  paths, exact-target early return still clears path, temporary obstacle expiry
  preserves the same dict object, and movement still consumes the first path
  step only after an actual move. Edge cases checked: missing path key,
  non-list path coercion, expired temporary obstacles, planner object identity,
  and assault BFS callers of `_expire_temporary_obstacles()`. Cheap validation:
  runtime-substrate 87 passed, benchmark/tool tests 10 passed, replay analyzer
  tests 3 passed, compileall passed, py_compile passed, and `git diff --check`
  passed after removing pre-existing trailing whitespace from
  `FIRST_LONGFORM_PROMPT.md`. Deterministic local `--tle 2` smokes completed
  without crashes: jon-6/default_small2 won with 23,208 delivered Ti;
  a9/pls_buy_cucats_merch won but only 187 delivered Ti; leeroy/bar_chart
  remained a low-output loss with 11 delivered Ti. Local replay timing buckets
  remain unusable because `execTimeUs` is still all zero.
- Rejected navigation-state allocation hardening: local g16 on schedule seed 1
  was a clear validation failure, 18-30 overall / 37.5%, avg TiEq 17,341,
  worst 0; by opponent `jon-6` 11-5, a9 3-13, `leeroy` 4-12. Seat split:
  jon-6 Team A 4-4 / Team B 7-1; a9 Team A 2-6 / Team B 1-7; leeroy Team A
  2-6 / Team B 2-6. Timing buckets were locally all zero, so no local timing
  conclusion is available. Decision: revert the in-place navigation-state and
  test additions. Even though the patch was intended as behavior-preserving,
  same-schedule validation was materially worse than the live baseline and not
  acceptable as a standalone mechanistic trade.
- Current active batch, 2026-04-12: re-opened long-form work on
  `bots/got-any-grapes/` against `jon-6`, `jon-6-a9bfs-surround`, and
  `leeroy-jonkins`. Precedence for this task is live code > user prompt >
  `AGENTS.md` > `BATTLECODE_EXPLAINER.md` > this scratchpad. The worktree is
  already dirty in `mode_tiling_back.py` and
  `tests/test_got_any_grapes_runtime_substrate.py`; treat those edits as live
  state, preserve them unless direct evidence shows a real detriment, and do
  not revert unrelated dirty files or maps.
- Immediate 2026-04-12 action: inspect live perception/navigation/pipeline hot
  paths, choose the highest-ROI complete batch, implement it end-to-end with
  unit coverage, run cheap validation, then benchmark only after the bug audit
  is complete. Remote testing is explicitly deferred until local cheap tests
  and local matrix evidence justify validation.
- Compaction-safe resume point, 2026-04-12: docs have been re-read; current
  leading hypothesis is a strict runtime/pipeline safety batch, not a new
  offense, axionite, marker, or broad defense branch. Start from live code and
  verify behavior in `builder_bot.py`, `perception.py`, `navigation.py`, and
  `mode_tiling_back.py` before editing.
- Rejected 2026-04-12 navigation batch: tried making `TILING_BACK` empty-route
  replans use a bounded resumable A* slice before any full A* recompute. Cheap
  tests passed and focused `--tle 2` smokes won, but g16 no-TLE was a genuine
  detriment: 20-28 overall / 41.7%, avg TiEq 24,145.6, worst 0; `jon-6` 9-7,
  a9 6-10, `leeroy` 5-11. A safer revision keeping only the anytime slice cap
  plus bridge-pruning parity also failed: 21-27 overall / 43.8%, avg TiEq
  24,013.8, worst 0; `jon-6` 10-6, a9 6-10, `leeroy` 5-11. Both versions kept
  local TLE turns at 0 but local replay `execTimeUs` remained zero, so local
  `% >1ms` timing could not be read. Decision: reverted all `navigation.py`
  changes and the added navigation tests. Do not reintroduce anytime-first
  return routing without a stronger route-quality/progress invariant; it is
  not safe as a standalone timing fix.
- Rejected 2026-04-12 marker-dispatch batch: tried direct payload decoding in
  `_scan_nearby_markers` after raw marker-type dispatch to avoid repeated enum
  conversion and parser calls. Cheap tests passed and direct payload checks
  matched the legacy parsers for ore, connected conveyor, pipeline claim,
  assault claim, and explore claim markers. Local g16 still failed acceptable
  validation: 24-24 overall / 50.0%, avg TiEq 19,508.1, worst 0; `jon-6`
  12-4, a9 7-9, `leeroy` 5-11. This was not promotion-grade and lowered TiEq
  / `leeroy` robustness relative to the current live candidate. Decision:
  reverted all `perception.py` marker-dispatch changes and added tests.
- Current 2026-04-12 stop reason: no bot-code changes from this session are
  retained. Cheap validation after reverts still passes (`runtime_substrate`,
  `test_analyze_replay`, compileall, and `git diff --check`). Remaining likely
  ROIs are not quick behavior-preserving patches: broad SDK-call caching
  touches many modules, and pipeline/defense fixes are behavior-coupled with
  known win-rate tradeoffs. Next task should start by choosing one of those
  tradeoff-aware batches rather than resurrecting anytime-first routing or
  marker parser rewrites.

- Strategy name: got-any-grapes remote timing first-lane hardening
- Task: Improve `bots/got-any-grapes/` against `jon-6`,
  `jon-6-a9bfs-surround`, and `leeroy-jonkins` under the legal Cambridge
  Battlecode execution model.
- Criteria: prioritize remote safety before new strategy; reduce builder turns
  over 1 ms / 1.5 ms / 2 ms, preserve or improve first titanium lane
  reliability, and track win rate, TiEq, worst TiEq, small loops,
  no-progress/travel-without-build signals, and TLE turns.
- Throughput priority: maximize delivered titanium throughput into the core,
  not just ore discovery, mining, or total conveyor count. Current observed
  failure: many ore lanes converge into only 2-3 final pipelines near the core,
  causing massive pipeline stall even when upstream harvesters and conveyors
  exist. Future batches should prefer fixes that spread returns across more
  core-adjacent ports, reduce last-mile saturation, and diagnose idle/stalled
  delivered-resource lanes.
- Latest evidence: 2026-04-11 remote baseline is 9-21 overall across the
  requested 30 games. By opponent: 4-6 vs `jon-6`, 2-8 vs
  `jon-6-a9bfs-surround`, 3-7 vs `leeroy-jonkins`. Weighted remote builder
  timing pressure is extreme: 74.7%-83.6% over 1 ms, 59.7%-80.1% over 1.5 ms,
  and 51.8%-75.8% over 2 ms depending on matchup. All 30 games flagged
  `high_tle_pressure`, `low_builder_progress`, and `small_loop`; 15 games
  flagged `travel_without_build`; delivered refined axionite was 0.
- Immediate next action: use the failed threat-aware direct-core fallback
  experiment to define practical AFIs that preserve the direct-core economic
  upside while adding local robustness against offensive pressure. Do not add a
  hard "enemy visible means reroute" rule; it collapsed the economic matchup.
- Current active batch, 2026-04-11: strictly mechanistic assault-inference
  runtime cleanup. Maintain an incremental count of known terrain/env tiles
  during perception and use it for assault symmetry cache invalidation instead
  of repeatedly scanning `bot.grid.values()`. This preserves direct-core
  economics and assault target semantics while removing a recurring broad
  whole-grid pass from assault builders.
- Compaction-safe resume point: live code is authoritative and already dirty.
  Current batch surface is `builder_bot.py` for the new private counter default,
  `perception.py` for incrementing that counter on full and fast visible-tile
  writes, `mode_assaulting.py` for reading the counter instead of scanning
  grid values, and `tests/test_got_any_grapes_runtime_substrate.py` for focused
  invariants. Do not benchmark until the implementation, bug audit, targeted
  pytest, and compile checks are complete.
- Current defense-targeting batch, 2026-04-11: user correctly pointed out that
  defensive sentinels should remove the assaulting builder bots before shooting
  guns. Replayed evidence showed the old sentinel priority targeted turrets and
  logistics before enemy builders. A global builder-first patch was rejected by
  smoke (`default_small1` seed 1 vs a9 collapsed to 640 delivered Ti), and a
  friendly-logistics-near-builder patch was also rejected by smoke (11
  delivered Ti). Retained local candidate scopes builder-first only to enemy
  builders near a visible friendly core, preserving forward hijack/logistics
  pressure. Cheap validation passed: 83 runtime-substrate tests, compileall,
  and `git diff --check`. Seed-1 smokes under `--tle 2` won all three by core
  kill: vs `jon-6` turn 784 / 6,880 delivered Ti; vs
  `jon-6-a9bfs-surround` turn 1460 / 10,070 delivered Ti; vs
  `leeroy-jonkins` turn 1074 / 3,860 delivered Ti.
- Current defense-targeting g16 result: local no-TLE matrix was 24-24 overall,
  avg TiEq 27,039, worst TiEq 0, local TLE turns 0. By opponent: `jon-6` 12-4,
  avg TiEq 32,918, worst 0; `jon-6-a9bfs-surround` 4-12, avg TiEq 21,004,
  worst 90; `leeroy-jonkins` 8-8, avg TiEq 27,195, worst 0. Seat split:
  jon-6 Team A 7-1 / Team B 5-3; a9 Team A 1-7 / Team B 3-5; leeroy Team A
  3-5 / Team B 5-3. Analyzer signals persisted in every matchup:
  `small_loop`, `low_builder_progress`, and `travel_without_build` in all 48
  games; `core_port_concentration` in 38/48. Local replay `execTimeUs` fields
  remained zero, so local `% >1ms` timing is unavailable. Decision: commit as
  a promising local candidate at user request, but do not remote-validate yet;
  the result is a real `leeroy` improvement and a mechanistically correct
  core-defense primitive, but it remains below gate and does not solve a9.
- Replay-diagnosis clarification, 2026-04-11: the g16 is not bad evidence even
  though it misses the formal gate. Compared with the previous connected-
  pipeline local candidate (22-26 overall, `jon-6` 13-3, a9 5-11, leeroy
  4-12), this batch is 24-24 overall, gives up one game each to `jon-6` and
  a9, but improves `leeroy` from 4-12 to 8-8. Treat the scoped core-defense
  sentinel target policy as useful, not promotion-ready.
- `core_port_concentration` meaning: this analyzer flag is not counting how
  many core slots have built pipeline adjacent to them. It counts actual
  resource transfers into the 3x3 core footprint. `active_ports` is the number
  of distinct core tiles that received delivered resources; `top1_share` and
  `top3_share` measure how much delivered titanium entered through the busiest
  one or three core tiles. The flag fires after at least 1,000 delivered
  resource-equivalent when delivery uses three or fewer active ports or the top
  three ports carry at least 85% of delivery. More active ports would be good;
  the flag means delivery is concentrated, not spread. It is diagnostic only:
  concentrated ports in high-output wins can simply mean one lane is working,
  while concentrated ports in low-output losses indicate final-mile bottleneck
  or failure to build parallel durable lanes.
- Replay-diagnosis by opponent: `jon-6` losses are mostly plain economic
  execution failures, not defense failures. Worst `pls_buy_cucats_merch` game
  delivered 0 Ti after only 1 harvester and 44 conveyors while `jon-6` placed
  35 harvesters and 362 conveyors. Other `jon-6` losses delivered 10k-15k Ti
  but had huge conveyor churn and no-progress streaks. The fix is first-lane
  completion and builder productivity, not more sentinels.
- Replay-diagnosis by opponent: a9 losses are suppression and survivability
  failures. Worst losses still place harvesters and sentinels but lose builders,
  harvesters, and conveyors faster than they convert to delivered Ti: e.g.
  `wasteland_oasis` delivered 90 Ti with 7 harvesters, 7 sentinels, 9 builders
  removed; `mandelbrot` delivered 920 Ti with 5 harvesters removed; `pixel_forest`
  spawned 29 builders and lost 21. The failure is not "no defense"; it is that
  defense/rebuild/harvest/return do not compose into a durable controlled
  logistics area under suppression.
- Replay-diagnosis by opponent: `leeroy` improved because its rush profile is
  closer to the scoped core-defense primitive. Remaining worst losses are still
  zero/near-zero opening-economy failures: `starry_night` delivered 0 Ti with
  0 harvesters and 3 conveyors, `cold` delivered 0 Ti with 2 harvesters and 32
  conveyors, and `bar_chart` delivered 140 Ti with 2 harvesters and 26
  conveyors. The remaining failure is minimum-viable economy under rush
  pressure, not just target order.
- MAE next target: the repeated `small_loop`, `low_builder_progress`, and
  `travel_without_build` flags are three views of unresolved builder intent.
  Builders spend too many turns moving, waiting, or re-evaluating without
  completing a useful local construction/combat step. Next batch should target
  progress recovery under contested construction: when a builder loops or
  travels without building near a lane, force a bounded local action
  (repair/defend/clear/abandon) rather than reattempting the same plan. For a9,
  prefer a local controlled-area primitive around harvester/outlet regions over
  global defense or core-port spreading.
- Rejected follow-up, 2026-04-11: tried two local controlled-area primitives.
  First, a stalled `TILING_BACK` builder under visible nearby enemy pressure
  could build a local sentinel after a route stall; this regressed the a9
  `default_small1` seed-1 smoke from the committed core-kill win to a tiebreak
  loss with 2,560 delivered Ti, even after tightening the trigger from 8 to 16
  stationary turns and removing ping-pong triggers. Second, non-tiling economy
  builders were allowed to defend visibly damaged far harvesters under enemy
  builder pressure while still ignoring far damaged conveyors; seed-1 smokes
  passed, but g16 was a clear detriment: 15-33 overall / 31.2%, `jon-6` 9-7,
  a9 2-14, `leeroy` 4-12, avg TiEq 22,663, worst 0, TLE turns 0. Reverted both.
  Interpretation: simply expanding where/when sentinels are built destroys
  role timing and economy composition. The next improvement should not be
  "more defense radius"; inspect spawn/role distribution and minimum viable
  economy instead.
- Rejected follow-up, 2026-04-11: tried gating non-assault opportunistic
  hijack on private evidence of a safe titanium lane (`last_harvester_pos`,
  connected friendly conveyors, or connected-harvester markers), leaving
  assault-role pressure untouched. Cheap tests passed, but the a9
  `default_small1` seed-1 smoke collapsed to 16 delivered Ti. Reverted. This
  conflicts with the intuitive "no hijack before first safe lane" rule:
  against a9, early opportunism is currently carrying essential pressure. Do
  not add a blunt hijack gate; any safety gate must preserve early a9-facing
  sabotage, perhaps by distinguishing map/opponent profile through local
  pressure evidence rather than economy evidence alone.
- Active batch result: implementation and cheap validation passed
  (`tests/test_got_any_grapes_runtime_substrate.py`, `tests/test_analyze_replay.py`,
  and compileall on `bots/got-any-grapes`). Local g16 no-TLE failed the
  win-rate gate and should not go remote: 20-28 overall / 41.7%, avg TiEq
  19,719, worst TiEq 0, local TLE turns 0; by opponent `jon-6` 11-5,
  `jon-6-a9bfs-surround` 2-14, `leeroy-jonkins` 7-9. Local replay
  `execTimeUs` was still zero, so no local `% >1ms` timing conclusion is
  available. Deterministic `default_small1` seed 1 vs a9 still won under
  `--tle 2` with 5,928 delivered titanium. Decision: revise locally, no
  commit and no remote validation. The next target is the a9/zero-output
  collapse in live code, using same-schedule local evidence before any remote.
- Rejected marker-disable batch: worst a9 losses showed hundreds of assault
  claim markers and marker removals, so disabling assault claim publishing was
  tested as a construction-safety fix. Targeted tests and compileall passed,
  but the deterministic `default_small1` seed 1 a9 smoke regressed immediately
  from a win with 5,928 delivered titanium to a loss with 204 delivered
  titanium. The change was reverted. Interpretation: assault claim markers are
  ugly and probably expensive, but they are currently carrying enough
  coordination/pressure value that a blunt no-op is a genuine detriment. Any
  marker work must make placement safer without removing the claim signal.
- Rejected marker-cadence batch: tried preserving assault claim markers while
  reducing refresh frequency from 4 to 8 rounds. Cheap validation passed and
  deterministic `default_small1` seed 1 a9 still won with 9,890 delivered
  titanium in replay analysis, but same-schedule g16 collapsed further:
  14-34 overall / 29.2%, `jon-6` 10-6, `jon-6-a9bfs-surround` 1-15,
  `leeroy-jonkins` 3-13, avg TiEq 18,276, worst TiEq 0, local TLE turns 0.
  Reverted. Interpretation: assault claims are not merely cosmetic; their
  cadence affects coordination enough that even reducing marker volume is a
  real tradeoff. Do not revisit marker cadence without a safer claim placement
  or a replacement coordination primitive.
- Current active batch: early local core defense. User correctly identified
  that the bot had no defensive override against offensive strategies. Added
  a bounded `defense.py` primitive: non-assault economy/explorer builders near
  the own core interrupt greed only when a visible enemy builder/turret is
  inside the core-defense radius, then build a local sentinel aimed at the
  assailant. The helper skips assault roles and `TILING_BACK` so it does not
  peel builders off an active first lane. Cheap validation passed. Smoke
  evidence: `default_small1` seed 1 vs a9 under `--tle 2` won with 22,210
  delivered titanium, up from 5,928 before this patch; `default_small1` seed 1
  vs leeroy also won with 22,290 delivered titanium. Next action: run local
  g16 no-TLE against all three studied opponents before any remote validation.
- Rejected core-halo hygiene batch, 2026-04-11: implemented a tiny
  `core_halo.py` helper called from `BuilderBot.run()` after perception and
  before hijack/economy. It only used current visible grid data, current tile,
  and the 12 own-core approach slots; tests covered quiet no-op, no legality
  calls without visible hostile pressure, underfoot hostile logistics fire,
  hostile approach barriers, own-lane preservation, and no whole-grid scan.
  Cheap tests passed and one smoke won, but the repeat smoke lost and the g16
  no-TLE matrix was a clear detriment: 18-30 overall / 37.5%, avg TiEq
  22,186.5, worst TiEq 0, TLE turns 0; by opponent `jon-6` 10-6,
  `jon-6-a9bfs-surround` 5-11, `leeroy-jonkins` 3-13. The batch was removed.
  Interpretation: even tiny action-priority/barrier changes near core can
  disrupt the current direct-core/economy/assault coupling. Do not reintroduce
  generic core-halo barriers without replay proof that a specific approach
  tile is actively harming the first titanium lane.
- Latest post-revert cheap validation: `python -m pytest
  tests/test_got_any_grapes_runtime_substrate.py tests/test_analyze_replay.py`
  passed 60 tests; the tiling regression subset passed 6 tests; compileall on
  `bots/got-any-grapes` and `tools/analyze_replay.py` passed. Running the
  runtime substrate and tiling tests in one combined pytest process still
  exposes an existing cross-file module contamination issue, so keep using the
  repo's separated validation shape unless that test harness is cleaned up.
- Rejected ore-target cache batch, 2026-04-11: tried a private per-builder
  `FINDING_ORE` cache for the current ore/access pair with a 3-turn TTL and
  validity checks for ore still present, not claimed, not blacklisted, no
  adjacent friendly conveyor, passable access tile, and friend deconfliction.
  Cheap tests and smoke passed, but g16 no-TLE was a clear detriment:
  17-31 overall / 35.4%, avg TiEq 18,463.5, worst TiEq 0, TLE turns 0; by
  opponent `jon-6` 7-9, `jon-6-a9bfs-surround` 6-10, `leeroy-jonkins` 4-12.
  Removed the batch. Interpretation: target freshness and deconfliction are
  more important than the saved BFS work; do not cache the ore target across
  movement turns unless the cache is tied to a stronger progress invariant or
  same-turn/full-perception signature.
- Current immediate next action: avoid more behavior-coupled "cheap" caches or
  barriers. If continuing, focus on strictly behavior-preserving hot-path
  reductions inside existing functions, such as reducing allocation and SDK
  calls in perception/navigation without changing selected ore targets,
  return targets, or action priority.
- Iteration 1 batch: bounded opening escape plus tiling-back fast perception.
  Edited `builder_bot.py` to use local fast perception for non-assault
  `TILING_BACK` turns between 10-round full-perception heartbeats. Edited
  `mode_assaulting.py` to defer repeated shell-escape BFS to a 4-round cadence
  and yield an assault builder to `FINDING_ORE` after 8 blocked opening-escape
  attempts. Added tests in `tests/test_got_any_grapes_runtime_substrate.py`.
- Iteration 1 cheap validation: `~/.pyenv/versions/cambc/bin/python -m pytest
  tests/test_got_any_grapes_runtime_substrate.py` passed 42 tests; compileall
  on `bots/got-any-grapes` passed. One deterministic smoke with
  `cambc run got-any-grapes jon-6-a9bfs-surround maps/default_small1.map26
  --seed 1 --tle 2 --replay replay.replay26` completed and won for
  `got-any-grapes`, with no local TLE reported; replay `execTimeUs` fields were
  zero, so this is not timing evidence. Smoke still showed weak delivered
  titanium (76), `small_loop`, `low_builder_progress`, and
  `travel_without_build`.
- Iteration 1 remote validation: 6 seat-paired remote matches completed on
  2026-04-11: `8739a5b4-0bf1-47d8-a3e1-d98625e92f54`,
  `07d9d800-54f7-41e2-a9f6-88f5a2b40e0a`,
  `c6f0dfd2-1197-49b6-a067-4380206017c3`,
  `417fe110-81c5-4b3c-b8c1-61af0ec3a59a`,
  `47b536be-1dcd-4deb-b22c-e14cf77b26d5`, and
  `b584a810-5dac-4cf3-ac95-894c50d64f39`. Overall candidate score was 10-20
  vs the prompt baseline 9-21. By opponent: `jon-6` 3-7, avg TiEq 19,474,
  worst 0, builder timing 76.2% >1ms / 62.4% >1.5ms / 54.9% >2ms;
  `jon-6-a9bfs-surround` 4-6, avg TiEq 26,907, worst 4,920, timing
  83.6% / 74.4% / 68.8%; `leeroy-jonkins` 3-7, avg TiEq 21,490, worst 0,
  timing 72.3% / 59.4% / 53.6%. All games still had `small_loop`,
  `high_tle_pressure`, and `low_builder_progress`; 16/30 had
  `travel_without_build`. Decision: revise, not revert yet. Mechanistic
  changes helped a9 and some jon timing, but remote safety target was not met.
- Iteration 2 immediate target: identify and cheaply disable/reduce expensive
  per-turn work for stationary or no-progress builders while preserving first
  titanium-lane construction, then address last-mile delivery saturation near
  the core by spreading return lanes across more core-adjacent ports.
- Iteration 2 batch: broadened fast perception from assault/tiling-only to
  non-assault `FINDING_ORE` and `EXPLORING` on a heartbeat cadence: full scan
  every 4 rounds while no titanium is known and every 8 rounds once titanium is
  known. Fast inference now records locally visible titanium/axionite so the
  first lane can still be discovered between full scans. Targeted tests passed
  (44 tests) and compileall passed. Deterministic `default_small1` smoke vs
  `jon-6-a9bfs-surround` won with 11,260 delivered/mined titanium in replay
  analysis, up from 76 delivered in the prior smoke; local `execTimeUs` remained
  zero, so local timing is unavailable.
- Iteration 2 g16 local no-TLE matrix: 30-18 overall, avg TiEq 29,667, worst
  0, local reported TLE 0. By opponent: `jon-6` 15-1, avg TiEq 41,656, worst
  4,940; `jon-6-a9bfs-surround` 8-8, avg TiEq 24,314, worst 1,220;
  `leeroy-jonkins` 7-9, avg TiEq 23,031, worst 0. Seat split: jon-6 Team A
  7-1 / Team B 8-0; a9 Team A 3-5 / Team B 5-3; leeroy Team A 4-4 / Team B
  3-5. Decision: keep revising locally before another remote run because
  g16 remains below the 80% per-opponent bar and leeroy/worst-TiEq failures
  remain.
- Rejected follow-up: tried a core-port spreading helper plus stronger
  connected-conveyor load penalties to address final-pipeline saturation.
  Cheapest smoke on the same `default_small1` seed immediately regressed from
  a win with 11,260 delivered titanium to a loss with only 64 scored titanium
  and 1,210 mined, so that change was reverted. Delivery-throughput remains a
  priority, but the next version must preserve the existing first return target
  on early lanes and should probably diagnose port saturation before changing
  core-port selection.
- Rejected follow-up 2: tried a narrower return-target-only load penalty that
  left A* step costs and core-port geometry unchanged, then tried an even more
  conservative version that only rose at load 4+. Both failed the same smoke
  (`default_small1`, seed 1 vs a9), losing with 1,407 and then 2,773 scored
  titanium. Conclusion: the current private connected-load estimate is too
  blunt for direct routing changes; penalizing merges breaks working first-lane
  construction before it fixes final-pipeline stall. Next pipeline work should
  start with replay/diagnostic evidence of core-port saturation and only then
  introduce a construction-safe spread primitive.
- Pipeline investigation update: added replay-analysis diagnostics for
  core-delivery port concentration. A saved castle replay delivered 78,860
  titanium through exactly 3 core tiles, with top-3 share 100%, confirming the
  user's last-mile glut observation. A first implementation that used private
  inferred harvester-count load to trigger secondary lanes regressed local g16
  (56.2% overall, jon-6 10-6, a9 6-10, leeroy 11-5), so it was revised away
  from inferred global load. Current local approach uses direct visible
  backpressure instead: when a builder is about to claim a harvester because it
  touches existing friendly transport, it only starts a secondary core return
  if that adjacent transport visibly stores a resource. Forced secondary
  returns choose a deterministic alternate core tile from the harvester
  position, without shared Python state or marker dependence. Targeted tests
  pass and the deterministic a9 smoke still wins with 11,260 delivered
  titanium.
- Splitter research update: official rules say splitters accept input only from
  the back and alternate among the primary output plus the two adjacent output
  directions, prioritizing least-recently-used directions. They can relieve a
  final-port delivery glut only when placed before the saturated last-mile
  fan-out and paired with valid downstream branches; they do not multiply the
  capacity of a single upstream trunk by themselves.
- Pipeline heuristic iteration: verified bridges are not infinite-capacity
  pipes. A replay scan over 250 local replays found no bridge emitting more
  than one stack in a distribution phase, so long bridges should be treated as
  long-hop construction tools, not throughput multipliers. A hard no-merge
  direct-core-return heuristic was rejected: broad threshold g16 fell to 12.5%
  overall, while a narrow threshold failed the deterministic a9 smoke. The
  direct-core idea itself remains live: close harvesters prefer direct core,
  visible backpressure can trigger forced secondary returns, visibly full core
  approaches can fall back to a connected pipeline, splitters are handled as
  passable transport, and core-port diagnostics are retained. A clean local
  g16 on the safer backpressure-only candidate was 60.4% overall, with 14-2 vs
  `jon-6`, 8-8 vs `jon-6-a9bfs-surround`, and 7-9 vs `leeroy-jonkins`; no
  local TLE turns. Decision: do not commit yet; next target is a softer
  construction-safe robustness primitive that preserves first-lane construction
  and the `jon-6` direct-core gains.
- Failed adaptive-threat experiment: tried keeping direct-core as the default
  while deferring to a known connected lane when a builder saw local pressure
  near the harvester/route/core. Even after tightening fallback to "nearby
  viable lane only", local g16 collapsed to 19-29 overall: 7-9 vs `jon-6`,
  6-10 vs `jon-6-a9bfs-surround`, and 6-10 vs `leeroy-jonkins`, avg TiEq
  20,061, worst TiEq 10, TLE turns 0. Decision: this was genuine detriment, not
  noise. The implementation was removed. Lesson: offense and logistics are
  delicately coupled; visible threat must not hard-override direct-core routing
  because the direct-core economy is itself the main advantage against pure
  economy and a necessary resource base against offense.
- Offensive scenario musings:
  - Rusher / core leech: a fast enemy builder reaches the core halo or a
    friendly lane and tries to turn friendly logistics into an attack rail.
    Robust response should be local core-halo hygiene: clear enemy logistics,
    block hostile approach tiles, and avoid building final-port infrastructure
    that points into an active enemy builder. Do not globally stop farming.
  - Disruptor / route cutter: enemy builders, sentinels, gunners, or barriers
    contest ore veins and sever pipelines. Robust response should preserve
    independent direct-core lanes in quiet areas, repair or retile broken
    nearby harvesters, and only shorten/merge when the backup is already close
    and construction-safe. The failed fallback shows that "pressure seen,
    reroute" is too blunt.
  - Terminator / tech timing: opponent looks economic, then uses refined
    axionite/foundries to power stronger weapons and late core pressure. Robust
    response should not panic early; it should keep titanium throughput high,
    watch for visible foundry/axionite-chain evidence, then prioritize attacks
    or disruption on foundries, axionite harvesters, and ammo routes rather
    than fighting upgraded weapons head-on.
  - Port blocker / congestion attacker: opponent or friendly overbuilding
    reduces available core-adjacent delivery slots. Robust response should use
    core-port diagnostics and visible ring fullness to fall back to existing
    pipelines only when direct core slots are truly unavailable, not merely
    because an enemy is nearby.
  - Spawn clog / builder trap: pressure or friendly overproduction pins
    builders near the 3x3 core shell. Robust response should be cheap local
    unclogging, road placement, and temporary obstacle memory; broad combat
    planning from every stuck builder is too expensive under the 2 ms budget.
- Practical robust AFIs to consider next:
  - AFI 1, Core-halo hygiene: a very small local routine for builders near
    own core that clears hostile conveyors/markers/roads underfoot or adjacent
    when they form a route into the core shell, and optionally drops a barrier
    on a clearly hostile approach tile. This is practical because it uses only
    current visible grid data and builder `fire`/barrier actions; it should
    not affect quiet distant harvesters.
  - AFI 2, Direct-core route safety as a cost bias, not a hard switch: add a
    small temporary obstacle or path-cost penalty around visible hostile combat
    tiles during direct-core A*, while keeping the same direct target. This
    preserves the economic intent but nudges routes around danger when a safe
    detour is cheap.
  - AFI 3, Broken-lane first aid: strengthen existing disconnected-harvester
    retile logic with a short TTL priority for recently seen own harvesters
    that lost all adjacent transport. This attacks disruptor damage without
    changing quiet direct-core behavior.
  - AFI 4, Core-port saturation fallback: keep the direct-core idea, but when
    the 12 approach slots are visibly full or final-port concentration is
    locally obvious, allow pipeline merge or alternate core tile selection.
    This is practical because it is already partially implemented and tested;
    it does not require global capacity estimates.
  - AFI 5, Offensive flip after first safe lane: keep opportunistic hijack or
    enemy logistics cutting gated behind first safe titanium delivery. The
    target should be enemy harvesters/foundries/ammo routes, not generic core
    assault, because those are higher-leverage and cheaper to recognize.
  - AFI 6, Axionite-chain scouting marker later: after titanium is stable,
    mark visible enemy foundries or axionite harvesters with a sparse event
    marker. This is not first-priority because marker placement can poison
    routes and axionite work is explicitly deferred until titanium is reliable.
  - Combat component notes from SDK `cambc 1.6.2`: barriers are cheap
    3-titanium / 30-HP blockers and are the most practical immediate defensive
    tool beyond builder `fire`; gunners cost 10 titanium, fire every turn for
    10 damage with 2-ammo cost, can rotate for 10 titanium, and line-of-sight
    rules make them useful only when direction and logistics are deliberate;
    breaches cost 15 titanium + 10 axionite, have 60 HP, fire every turn for
    40 direct / 20 splash with 5-ammo cost, but require axionite and therefore
    belong after a real foundry/ammo plan; launchers cost 20 titanium, ignore
    facing, and throw builder bots (`can_launch`/`launch`) rather than firing
    like gunners, so they are a mobility/tactical-delivery tool, not a simple
    defensive turret. Practical implication: near-term robust combat should
    prefer builder fire, barriers, route denial, and selective sentinel/gunner
    geometry only where logistics already exist; breach/launcher plans are
    later AFIs because they need ammo, positioning, and more tests.
  - Non-AFIs for now: broad global threat classification, per-turn combat
    scans from every builder, hard reroute on visible enemy, default gunner or
    breach production without an ammo/refined-axionite plan, and splitter or
    bridge assumptions that pretend to multiply throughput.
- Current-code strategic reflection:
  - Can this bot cheese early-game / econ-focused enemies? Partly yes. Live
    code has forced opening assault spawns on rounds 5 and 6, assault builders
    use symmetry/frontier inference, navigate with road support, publish sparse
    assault claims, and try to capture enemy harvester rings with sentinels.
    Non-assault builders can also opportunistically hijack visible enemy
    harvesters by standing on active outlets, firing underfoot, sealing open
    sides with barriers, and then tiling back from the captured outlet. These
    are real pressure tools. But they are fragile cheese: they depend on
    visible enemy harvesters or successful symmetry navigation, mostly attack
    economy rather than the core, and can waste early builder slots if no good
    target materializes. Against pure economic opponents, the more reliable
    "cheese" is actually direct-core titanium throughput, not combat.
  - Can this bot endure sustained pressure? Not yet at promotion level. It has
    strong navigation primitives (bounded A*, cached/anytime pathing, local
    escape, temporary obstacles, disconnected-harvester retiling, stall
    blacklists, fast perception cadence), and it has some local combat actions
    (builder `fire`, sentinel assault sites, hijack barriers). The missing
    durability layer is a cheap defensive routine around own core/own routes.
    Sustained pressure still causes low builder progress, small loops, and
    travel-without-build; remote builder timing pressure is also high, so
    "superior navigation" is contaminated by runtime cost. Most importantly,
    titanium supply is inconsistent: the bot can create high-output games, but
    worst TiEq remains catastrophic and core-port concentration shows that
    delivered throughput, not mined ore, is the binding constraint.
  - How does this bot exert pressure? It pressures through three channels:
    direct economic pressure by delivering titanium faster than pure farmers;
    assault pressure by building sentinels around enemy harvesters; and hijack
    pressure by stealing/sealing enemy harvester outlets. These tactics work
    best against slow economic opponents and exposed harvester layouts. They
    work worse against offensive opponents because those opponents contest the
    same logistics surface: builders get delayed, routes are cut, and assault
    units that do not quickly find value become deadweight. The failed
    threat-reroute experiment reinforces that pressure must be layered on top
    of a stable titanium engine, not substituted for it.
- MAE framework reflection:
  - Mechanistic: the bot has useful runtime work already (fast perception,
    bounded searches, cached pathing), but remote evidence says it is still too
    expensive. Any AFI that adds broad scans, per-turn global classification,
    or extra A* work is suspect. Practical AFIs must be tiny local checks,
    cadence-gated, and reuse current perception/grid data.
  - Algorithmic: the direct-core route heuristic is valuable but brittle when
    converted into hard rules. Better algorithmic AFIs should bias or repair
    existing behavior instead of flipping modes: core-halo hygiene, temporary
    obstacle costs around danger, local retile priority, and visibly-full
    core-port fallback. These preserve the same strategic goals while reducing
    known failure modes.
  - Emergent: the current bot's cooperation is mostly implicit: markers share
    ore/connected conveyors/assault claims, but every builder still has private
    state. Emergent failures are congestion, duplicate routes, too many
    builders entering pressure work, and assault slots stealing economy before
    the first lane is safe. Robustness should come from evidence-gated role
    changes and sparse markers only after construction safety is proven.
  - Strategic conclusion: do not chase a single "anti-offense mode." Use the
    economic direct-core engine as the baseline, add narrow local defensive
    primitives for core/route hygiene, and only flip the script offensively
    after delivered titanium proves the first lane is alive.
- Challenged-fundamentals reassessment:
  - Planning/runtime: assume the bot is not yet remote-safe on AWS Graviton3.
    The current remote baseline has extreme builder timing pressure across all
    studied opponents, with more than half of builder turns over 2 ms in every
    matchup. Local `execTimeUs` may be zero in smoke replays, so remote remains
    timing truth, but remote must not be used as bug-finding. Any next AFI must
    be compatible with fewer scans, fewer broad path searches, and fewer
    repeated SDK calls.
  - Navigation: do not call navigation deployment-ready. The code has strong
    primitives, but replay signals still show `small_loop`,
    `travel_without_build`, poor progress under obstacles, and occasional
    catastrophic TiEq. Treat navigation as adequate for some direct-lane
    construction, not as a solved substrate for combat or large detours.
  - Combat tactics: incomplete because they are not integrated with supply,
    timing, route protection, and role gating. Sentinels can capture enemy
    harvester rings, hijack can steal outlets, and barriers can deny space, but
    these actions can be counter-synergistic with economy when they consume
    early builder turns, titanium, pathfinding budget, or core-halo space before
    a safe lane is delivering. Synergy exists only when combat protects or
    amplifies delivered-resource throughput: clearing a core leech, sealing an
    enemy harvester outlet, defending a live route, or cutting an enemy foundry
    chain after our first lane is safe.
  - SDK/resource use: the bot uses useful SDK pieces (nearby scans, marker
    values, build legality, builder fire, movement, pathing helpers), but it is
    not yet making robust algorithmic/emergent use of the full resource model.
    Delivered titanium is the KPI, yet behaviors still overvalue building,
    traveling, scouting, or assaulting relative to actual delivery. Bridges and
    splitters were initially easy to overinterpret; current evidence says use
    them only with exact construction semantics, not imagined throughput.
  - Emergent path forward: under 2 ms/unit and private state, prefer implicit
    pack-like swarm behavior over central-planner coordination. The right
    analogy is not isolated workers and not telepathic global planning; it is
    wolves taking compatible local roles during a hunt. Practical examples:
    if one friendly occupies an enemy outlet, another seals a side; if a ring
    site is occupied, another builder takes a neighboring useful pressure tile;
    if a hostile route reaches the core halo, nearby builders clear or block it
    while quiet builders keep farming. Complex shared-state plans need
    consensus, broad sensing, and durable shared memory; those are expensive
    and illegal unless encoded through sparse markers. The team should become
    bigger than the sum of its parts through robust local invariants and cheap
    role-compatible spatial rules.
- Roadmap / big direction:
  - Current outlook: `got-any-grapes` has a real strategic kernel but is not
    deployable yet. The kernel is direct-core titanium throughput plus
    opportunistic pressure. It can beat or threaten pure economy when the first
    lanes survive, but remote TLE pressure, small loops, catastrophic worst TiEq,
    and weak robustness against offensive disruption mean it is not
    promotion-close.
  - First deployable target: a boringly reliable titanium bot. It should get at
    least one safe harvester-plus-return lane in almost every game, keep local
    builder turns over 1 ms below the repo safety target, avoid zero/near-zero
    TiEq games, and preserve direct-core gains against `jon-6` while not
    collapsing under `a9bfs-surround` or `leeroy-jonkins`.
  - Mechanistic work required: remove or cadence-gate hot-path broad work in
    perception/navigation/assault, reduce repeated SDK calls, keep pathfinding
    bounded and resumable, avoid per-turn whole-map/topology rebuilding, and
    measure builder timing pressure after every runtime-sensitive batch.
  - Algorithmic work required: make first-lane construction more deterministic
    and recoverable; improve small-loop and travel-without-build escape; keep
    direct-core as the default for close harvesters; use core-port fallback only
    when visibly necessary; improve route repair and local obstacle handling
    before adding heavier combat or axionite.
  - Emergent work required: build implicit pack behavior from cheap local rules:
    core-halo hygiene, outlet sealing/contesting, alternate local pressure tiles,
    local retile priority, and sparse markers only where they cannot poison
    construction. Avoid central-planner fantasies and avoid role changes that
    steal early economy before delivered titanium proves a lane is alive.
  - Final product for this roadmap: not a sophisticated combined-arms bot yet,
    but a remote-safe economy-pressure bot. It should establish direct-core
    titanium lanes quickly, repair or defend them locally, opportunistically
    punish exposed enemy harvesters/logistics, and only escalate into heavier
    offense or axionite/foundry tactics after the titanium engine is stable.
- Compaction-safe resume point: continue from live code, not older notes. User
  precedence is live code > prompt > `AGENTS.md` > `BATTLECODE_EXPLAINER.md` >
  scratchpads. Hard constraints: no shared Python globals for coordination;
  markers are the only cross-unit communication; no hijack peeling before a
  safe titanium lane exists; remote tests are validation only after cheap
  bug-finding and local validation. Current code state: failed visible-threat
  direct-core reroute was removed after g16 collapse; retained code includes
  runtime fast-perception changes, assault opening escape bounding, visible
  backpressure secondary returns, direct-core preference for close harvesters,
  core-approach-full fallback, splitter/passability correctness, bridge
  capacity realism, and core-delivery-port replay diagnostics. Latest cheap
  validation after cleanup: `python -m pytest tests/test_got_any_grapes_runtime_substrate.py
  tests/test_analyze_replay.py` passed 59 tests; `python -m compileall
  bots/got-any-grapes tools/analyze_replay.py` passed. No final commit yet; the
  next practical target is a small core-halo hygiene / local pack-behavior AFI,
  with no remote testing until implementation and cheap validation are complete.

## 2026-04-11 got-any-grapes defense/opportunism iteration

- User correction: offensive opponents need proactive defense, not just greed.
  Important split: `leeroy-jonkins` rushes the core and incidentally saps the
  economy; `jon-6-a9bfs-surround` actively suppresses lanes long-term.
- Implemented and retained for now:
  - new `defense.py`
  - core-rush sentinel response for non-assault FINDING_ORE / EXPLORING
    builders near the core
  - near-core lane sentinel response only when a visible friendly economy asset
    is already visibly damaged by nearby pressure
  - `TILING_BACK` builders are not peeled off lane construction
  - defense uses private unit state and visible perception only; no globals or
    illegal shared coordination
  - README rewritten to document current strategy, implementation map, and MAE
- Tried and rejected:
  - broad lane defense away from core: deterministic a9/leeroy smokes collapsed
  - movement-only shadowing/trailing of local enemies near undamaged lanes:
    deterministic a9 smoke collapsed to 176 delivered Ti and a loss
  - connected-lane gating for hijack and bonus assault: g16 collapsed to 31.2%
    overall, including 7-9 vs `jon-6`; reverted
- Latest cheap tests after reverting failed subideas:
  - `python -m pytest tests/test_got_any_grapes_runtime_substrate.py`: 69 passed
  - `python -m compileall bots/got-any-grapes`: passed
- Best defense-batch g16 evidence before reverting failed subideas:
  - 43.8% overall, avg TiEq 21,729, worst TiEq 0, local TLE turns 0
  - vs `jon-6`: 12-4, avg TiEq 33,429
  - vs `jon-6-a9bfs-surround`: 3-13, avg TiEq 15,934
  - vs `leeroy-jonkins`: 6-10, avg TiEq 15,823
  - local replay execTime fields were zero, so timing-pressure rates read 0.0
    and are not decision-grade for remote safety
- Decision: do not remote. The batch is not promotion- or validation-worthy.
  Keep the narrow defense primitives only as a revised local substrate, and use
  the next iteration for a separate front-patrol/proactive-border concept.
- Next target:
  - design a single bounded front patroller after first-lane evidence, operating
    at the outer logistics/frontier edge rather than chasing enemies inside the
    lane
  - must avoid broad scans, avoid stealing `TILING_BACK`, and must not suppress
    direct-core throughput vs `jon-6`
- Rejected reactionary lane-delay update, 2026-04-11: user suggested allowing
  a lone assault builder to cause a little damage before committing to defense.
  Tested a single-scratch tolerance plus immediate response to multiple nearby
  builders while keeping harvester/outlet hijack active. Smokes were mixed, but
  g16 failed hard at 16-32 overall / 33.3%: `jon-6` 10-6,
  `jon-6-a9bfs-surround` 3-13, `leeroy-jonkins` 3-13, avg TiEq 19,513.5,
  worst 0. Reverted to the prior visible-damage lane-defense gate.
- Rejected generic supply-line hijack, 2026-04-11: added direct sabotage of
  visible enemy conveyor-family tiles, first ungated and then gated to builders
  with no known titanium target. Deterministic smokes looked good, but g16
  exposed real emergent harm: ungated scored 18-30 overall / 37.5%, and the
  budgeted version scored 15-33 overall / 31.2%, including a collapse to 50%
  vs `jon-6`. Interpretation: generic supply sabotage over-peels the flex pool
  and hurts own economy more than it suppresses offensive opponents. Future
  hijack expansion needs legal pressure claims / stronger role budgeting before
  targeting non-harvester supply tiles.
- Rejected fed-sentinel hijack variant, 2026-04-11: tried the user's more
  modest sabotage framing where a builder already at a hijack outlet builds one
  fed sentinel around the enemy harvester only if the gun immediately covers a
  visible enemy builder or conveyor-family target. Focused tests passed, but
  deterministic smokes showed immediate harm: a9 collapsed to 10 scored
  titanium and lost badly, while jon/leery throughput also fell. Interpretation:
  the concept may still be strategically plausible, but this placement/timing
  poisons the hijack site or starves the lane. Reverted before g16.

## Medium-Term Emergent Strategy Notes

- Current emergent shape: the bot is still mostly a collection of strong local
  reflexes rather than a clean implicit team policy. Coordination comes through
  spawn-slot roles, action priority, visible local evidence, and assault claim
  markers, not through shared Python state.
- Current division of labor:
  - core creates early diagonal assault roles and economy roles by spawn slot
  - `TILING_BACK` builders are protected as lane constructors and should remain
    hard to steal because they are the units converting mined ore into TiEq
  - FINDING/EXPLORING builders are the flex pool for ore search, healing,
    hijack, and lane defense
  - assault builders coordinate mostly through claim markers and local anchor
    retirement
  - defense/hijack coordinate implicitly by priority order and visible evidence
- Current emergent weakness: the flex pool is overloaded. The same non-assault
  builder can become explorer, defender, healer, or hijacker based on one
  visible frame, which creates mode churn and inconsistent labor. Hijack also
  lacks a team-level budget, so aggressive sabotage can starve own lane
  construction if too many flex builders see enemy logistics.
- Current strongest implicit coordination rule: `TILING_BACK` is not stolen.
  Preserve that until a stronger legal marker-based construction-safety scheme
  exists.
- Medium-term AFI: role budgeting by local eligibility, not global managers.
  Keep lane constructors sacred; let only unattached FINDING/EXPLORING builders
  with no fresh titanium target take hijack/sabotage; let nearby multi-enemy
  pressure override that; eventually use safe markers as pressure claims so two
  builders do not chase the same enemy supply tile.
- Opponent mapping:
  - vs `jon-6`, avoid over-peeling flex builders so the direct-core economy
    remains intact
  - vs `leeroy-jonkins`, immediate core defense absorbs the rush while nearby
    flex builders punish exposed supply lines only when visible
  - vs `jon-6-a9bfs-surround`, spare/flex builders should apply economic
    sabotage to prevent long-term suppression from standing up

## 2026-04-11 Pipeline Integrity Batch

- User report: builders appear to overwrite each other's pipelines. Highest-ROI
  fix is construction safety in `TILING_BACK`, because that mode owns the live
  route from harvester to delivered TiEq.
- Implemented current candidate:
  - connected friendly transport is protected from pending conveyor builds
  - connected friendly transport is protected from bridge starts/targets
  - obstacle clearing refuses to destroy connected friendly conveyors/bridges
  - a builder standing on connected friendly transport skips retargeting that
    tile and keeps moving instead of freezing
  - lookahead construction skips connected friendly transport
  - unconnected partial conveyors remain repairable/retargetable so incomplete
    lanes are not frozen forever
- Cheap validation so far:
  - `python -m pytest tests/test_got_any_grapes_runtime_substrate.py -q`:
    73 passed
  - `python -m compileall bots/got-any-grapes`: passed
  - deterministic `default_small1` seed 1 smokes under `--tle 2`: wins vs
    `jon-6` (13,870 delivered Ti), `jon-6-a9bfs-surround` (11,470 delivered
    Ti), and `leeroy-jonkins` (28,320 delivered Ti)
- Current action: run local g16 no-TLE matrix before any remote validation.
- Rejected stronger "never destroy any friendly conveyor" variant: user asked
  for this if possible, but the current construction system still creates
  unconnected partial conveyors that must be repairable. Protecting every
  visible friendly conveyor caused the deterministic a9 smoke to collapse to
  10 scored titanium / 360 mined. Keep the connected-pipeline invariant for now
  and revisit all-friendly preservation only with a cleaner ownership/claim
  mechanism for partial lanes.
- Local g16 result for connected-pipeline preservation: 22-26 overall / 45.8%,
  avg TiEq 20,479, worst 0, TLE turns 0. By opponent: `jon-6` 13-3, avg TiEq
  35,006; `jon-6-a9bfs-surround` 5-11, avg TiEq 13,002; `leeroy-jonkins`
  4-12, avg TiEq 13,429. Decision: no remote; keep only as a locally coherent
  construction-safety candidate if the user values pipeline integrity, but it
  does not solve offensive matchups.
- Medium-term lane ownership idea from user: roughly 12 builders, one per
  pipeline, each maintaining its own lane while treating others' pipes as
  protected. Legal implementation would need per-builder private lane identity
  plus marker claims for partial routes; there is no shared manager. Other
  builders should treat claimed/connected lane tiles as protected except at
  explicit merge endpoints.
- Follow-up lane-ownership probe:
  - Added tested scaffolding for `PIPELINE_CLAIM` markers and 12-slot core
    lane assignment, but both production knobs are currently disabled.
  - Rejected hard external-slot routing: deterministic a9 seed 1 collapsed to
    70 delivered Ti, then 1,120 mined after viable-slot filtering; the target
    change delayed/broke first-lane delivery under pressure.
  - Rejected sparse claim-marker publication for now: with slot targeting
    disabled but claim publication/self-claim active, the same a9 smoke lost
    with 2,210 delivered Ti versus the connected-only candidate's 9,830-11,470
    delivered Ti on comparable smokes.
  - Restored production behavior to connected-pipeline preservation only:
    `ENABLE_CORE_LANE_SLOT_TARGETING = False` and
    `ENABLE_PIPELINE_CLAIM_MARKERS = False`.
  - Restored deterministic `default_small1` seed 1 smokes under `--tle 2`:
    win vs `jon-6` by core kill on turn 1192 with 10,260 delivered Ti, win vs
    `jon-6-a9bfs-surround` with 9,830 delivered Ti, and win vs
    `leeroy-jonkins` with 33,040 delivered Ti.

## 2026-04-11 Mechanistic Offensive-Matchup Audit

- Current g16 pipeline-preservation report analyzed:
  `.dist/reports/got-any-grapes_vs_jon-6-jon-6-a9bfs-surround-leeroy-jonkins_matrix.json`.
- Answers to user questions:
  - We lose primarily in delivered Ti and harvester/conveyor count, not because
    conveyor direction overrides are the main failure. Same-tile/different-dir
    pipeline replacements are higher in winning games because active economies
    rebuild and retile more.
  - Offensive low-output games correlate with early pressure. In a9 losses,
    early damage before turn 400 averaged roughly 1,090 versus 287 in a9 wins,
    and harvesters placed averaged 11.6 in losses versus 14.6 in wins.
  - Worst offensive maps in the current g16: `pixel_forest`, `face`,
    `minimaze`, and `mandelbrot`; `wasteland`, `gaussian`, and some large maps
    also show pressure failures.
  - Low a9 maps often show both early damage and harvester removals; leeroy
    losses are more often early core kill / rush pressure with low delivered Ti.
- Rejected defense-throttle patch:
  - Hypothesis: a9 losses build more sentinels, so over-defense might starve
    economy.
  - Change tried: one defensive sentinel per builder, total visible cap, and
    lane defense only for harvesters/connected conveyors.
  - Result: deterministic a9 smoke collapsed to 1,630 delivered Ti. Decision:
    revert; extra sentinels are mostly a symptom of pressure, not the root cause.
- Rejected healing-priority patch:
  - Hypothesis: damaged harvesters should be healed before damaged conveyors
    under pressure.
  - Unconditional harvester-first healing improved one a9 smoke but regressed
    jon-6 badly; threat-gated harvester-first healing still dropped a9
    throughput to 2,370 delivered Ti on the same smoke.
  - Decision: revert; preserving conveyor repair priority is part of first-lane
    throughput.
- Rejected builder-first defense target-order patch:
  - Hypothesis: defensive sentinels should prioritize enemy builders mounting
    the assault before shooting turrets/guns/logistics.
  - Scoped code changed only visible core/lane threat target priority and added
    focused tests.
  - Cheap validation passed, but local g16 regressed to 20-28 overall / 41.7%,
    avg TiEq 20,533, worst 0: `jon-6` 9-7, a9 4-12, `leeroy` 7-9.
  - Decision: reverted. Builder-first targeting is intuitively plausible but
    not sufficient as a standalone local heuristic.
- Rejected broad bridge-transit patch:
  - Inspected `jon-6` bridge handling and tried avoiding duplicate bridge
    queueing when a matching bridge already exists, plus consuming lookahead
    bridge builds into transit state.
  - Cheap tests and a jon-6 focused smoke improved, but g16 regressed to 18-30
    overall / 37.5%, avg TiEq 20,323, worst 0: `jon-6` 11-5, a9 3-13,
    `leeroy` 4-12.
  - Decision: do not keep as a net patch. Bridge code still needs work, but
    this version improved one economic case while harming offensive robustness.
- Current conveyor ownership patch:
  - User asked specifically about conveyors after the bridge review.
  - Revised protection rule: connected/claimed friendly transport is protected;
    visible friendly transport not in this builder's private
    `tiled_back_positions` is also protected; this builder may still repair a
    private unconnected segment it previously laid.
  - Matching protected conveyors are accepted as already-built progress without
    destructive legality calls; conflicting protected conveyors become
    temporary obstacles and force replanning.
  - Cheap validation: `tests/test_got_any_grapes_runtime_substrate.py` passes
    85 tests, compileall passes, and `git diff --check` passes.
  - Focused smokes after removing the bridge-transit experiment: jon-6
    `default_small2` seed 517204564 Team A won with 37,029 shown Ti;
    a9 `pls_buy_cucats_merch` seed 1219788632 Team A won but remained
    low-output; leeroy `bar_chart` seed 1238924204 Team B still collapsed.
  - Current action: local g16 no-TLE is running to decide whether the conveyor
    ownership invariant is aggregate-positive or another local-only detriment.
  - Local g16 result: 24-24 overall / 50.0%, avg TiEq 23,329, worst 0,
    local TLE turns 0. By opponent: `jon-6` 11-5, avg TiEq 34,315;
    a9 4-12, avg TiEq 12,595; `leeroy` 9-7, avg TiEq 23,076.
    Compared with the retained candidate (24-24, avg TiEq 27,039), this is
    not a promotion improvement: it trades one jon-6 game for one leeroy game
    and lowers TiEq. Replay analysis still shows every game with `small_loop`,
    `low_builder_progress`, and `travel_without_build`; `core_port_concentration`
    appears in 39/48. Local execTime fields are zero, so no local timing
    pressure conclusion is available. Decision: revise inside pipelining, not
    remote and not commit yet.
  - Pipeline diagnosis from this g16: low-output games are still delivery/port
    failures. Average active core delivery ports are only 2.88 vs jon-6, 2.00
    vs a9, and 1.75 vs leeroy. Losses have fewer harvesters and conveyors, but
    also fewer active ports: jon-6 losses average 1.6 ports and two zero-output
    games have zero active ports. Conveyor removals remain non-trivial
    (20-42 per game average depending on opponent), so partial-lane ownership
    helped mechanistically but did not solve emergent pipeline countersynergy.
  - Next pipelining-only target: terminal core bridges and last-mile port
    expansion. Current code has disabled hard core-lane slot targeting and
    near-core bridge planning mostly treats bridge target as a place the
    builder must move to. That is wrong for bridge-to-core delivery: the
    builder only needs to vacate the bridge start, build the bridge into a core
    tile, and mark the lane complete. Add this terminal-bridge primitive before
    revisiting any defense, hijack, or non-pipeline strategy work.
  - Rejected terminal-core-bridge activation:
    - Tried a bounded terminal bridge primitive plus a conservative activation
      rule: only after a connected lane existed, hash-selected direct-core
      builders could consider a bridge-to-core terminal port.
    - The low-cost bridge preference immediately regressed the a9 focused
      smoke. A conservative no-cost version still produced a worse leeroy
      `bar_chart` smoke and a zero-delivery replay with a bridge placed.
    - Removed the terminal bridge behavior. Bridge/21-port expansion remains
      important, but it needs a safer last-mile design than simply making A*
      prefer bridge-to-core targets.
  - Current pipeline planner batch:
    - Keep the conveyor ownership action rule: connected/claimed/other
      friendly transport is protected; a builder may repair only its private
      unconnected `tiled_back_positions`.
    - Add the same invariant to A*: another builder's visible unconnected
      wrong-way conveyor/bridge is not a route tile; this builder's private
      unconnected wrong-way conveyor remains routeable so execution can repair
      it.
    - Cheap validation: 87 runtime-substrate tests, compileall, and
      `git diff --check` passed.
    - Focused smokes: jon-6 `default_small2` seed 517204564 won with 38,463
      shown Ti; a9 `pls_buy_cucats_merch` seed 1219788632 won with 20,790
      mined; leeroy `bar_chart` seed 1238924204 still lost but improved from
      near-zero mining to 9,210 mined. Current action: g16 no-TLE matrix is
      running; no remote validation.
    - g16 result: clear detriment, 18-30 overall / 37.5%, avg TiEq 20,118,
      worst 0. By opponent: `jon-6` 9-7, a9 6-10, `leeroy` 3-13. It improved
      a9 wins but cratered jon-6 and leeroy. Decision: reverted planner-side
      route skipping; keep only action-level conveyor ownership as the current
      local candidate.
- Tooling timing-pressure batch:
  - User asked for local tools to report builder timing pressure at
    `>0.5ms`, `>1ms`, `>1.5ms`, and `>2ms`.
  - Updated `tools/analyze_replay.py` to add a `0_5ms` exec-pressure bucket
    alongside the existing `1ms`, `1_5ms`, and `2ms` buckets. The shared
    threshold list feeds team summaries, builder summaries, exec-by-kind, and
    hot-unit output fields.
  - Updated `tools/benchmark_matrix.py` to extract builder-turn pressure
    counts from replay analysis, aggregate them by weighted builder turns, and
    print aggregate/per-opponent `builder >0.5/1/1.5/2ms` rates.
  - Updated `tools/report.py` Markdown/CSV output to include the same four
    builder pressure rates.
  - Cheap validation: `~/.pyenv/versions/cambc/bin/python -m pytest
    tests/test_analyze_replay.py tests/test_benchmark_matrix_gate.py
    tests/test_benchmark.py` passed 12 tests,
    `~/.pyenv/versions/cambc/bin/python -m py_compile` for touched tool/test
    files passed, and `git diff --check` passed.
  - TLE-limit answer: `benchmark_matrix --tle-ms` is forwarded through
    `run_local_game()` as `cambc run --tle <ms>`; enforcement is by the cambc
    SDK/CLI runtime, not by `benchmark_matrix` measuring wall-clock itself.
  - Follow-up local timing check:
    - Ran `~/.pyenv/versions/cambc/bin/cambc run bots/got-any-grapes
      bots/jon-6 maps/default_small2.map26 --seed 123456 --replay
      .dist/timing_check_default_small2_seed_123456.replay26` with TLE off.
      Raw protobuf replay contained 35,677 `botOutput` records, all with
      `execTimeUs == 0`; analyzer reported Team A and Team B average/max exec
      time as 0us and all pressure buckets as 0.
    - Re-ran the same command with `--tle 2` to
      `.dist/timing_check_default_small2_seed_123456_tle2.replay26`. Raw
      protobuf replay contained 40,778 `botOutput` records, all with
      `execTimeUs == 0`; analyzer again reported all local pressure buckets
      as 0.
    - Current conclusion: local `cambc run` on cambc 1.6.2 is not populating
      replay `execTimeUs`, even when `--tle 2` is supplied. Replay-analysis
      timing from local runs is therefore unusable until we add another local
      timing source or rely on remote replay timing truth.
- Prompt/baseline cleanup, 2026-04-12:
  - Audited live code against the scratchpad before updating
    `FIRST_LONGFORM_PROMPT.md`. The dirty bot/test changes are the retained
    action-level conveyor ownership bugfix plus focused tests; failed
    navigation, marker-dispatch, terminal-bridge, bridge-transit, and
    planner-side route-skipping experiments are not present in live code.
  - Removed one unnecessary leftover plumbing change while auditing:
    `_navigate_and_build` no longer accepts or receives an unused
    `target_kind` argument.
  - Cheap validation after the audit: `~/.pyenv/versions/cambc/bin/python -m
    pytest tests/test_got_any_grapes_runtime_substrate.py` passed 85 tests,
    `~/.pyenv/versions/cambc/bin/python -m compileall bots/got-any-grapes`
    passed, and `git diff --check` passed.
  - Replaced the old tiered evidence block in `FIRST_LONGFORM_PROMPT.md` with
    current live-code status, current live local baseline, best local reference
    statistics, and the cambc 1.6.2 all-zero local `execTimeUs` caveat.
- AGENTS/tooling SOP cleanup, 2026-04-12:
  - Updated ignored local `AGENTS.md` to match current analyzer fields:
    flat `teams[*].builder_turns_over_0_5ms_rate`, `>1ms`, `>1.5ms`,
    `>2ms`, `exec_time_by_kind`, `hot_units_by_exec_time`, and TLE turns
    instead of the stale `teams[*].runtime_pressure` shape.
  - Documented the cambc 1.6.2 all-zero local `botOutput.execTimeUs` caveat,
    clarified that remote matches remain timing truth, and clarified
    `benchmark_matrix.py --tournament-backend` schedules
    `opponents * maps * seeds * 2 seat orders`.
  - Updated promotion-rule text to match the live 150k average-TiEq default and
    note that the live benchmark helper disables the worst-TiEq gate unless an
    explicit threshold is passed.
  - Fixed `tools/promotion_gate.py` import by adding
    `MAX_REMEDIATION_ROUNDS = 2` to `tools/benchmark_matrix.py`, and added a
    regression test for remediation-limit deactivation.
  - Cheap validation: `~/.pyenv/versions/cambc/bin/python -m pytest
    tests/test_benchmark_matrix_gate.py tests/test_benchmark.py` passed 10
    tests, `~/.pyenv/versions/cambc/bin/python -m py_compile
    tools/benchmark_matrix.py tools/promotion_gate.py
    tests/test_benchmark_matrix_gate.py` passed, and `git diff --check`
    passed.
