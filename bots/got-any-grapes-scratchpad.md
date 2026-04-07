# got-any-grapes scratchpad

## Promotion ladder

Each meaningful feature follows this sequence:

1. implement the feature
2. run unit or scenario tests for that feature
3. run a 16-game smoke set against `jon-6-a9bfs-surround`
4. require at least 60% win rate in the smoke set
5. if the smoke passes, create a preliminary draft commit
6. do not run 64-game tournaments yet
7. move to the next feature

After all trusted-feature work is complete:

1. selectively import `duck-1` optimizations one at a time
2. after each imported optimization, rerun unit tests and the same 16-game smoke
3. if the smoke passes, create another preliminary draft commit
4. if the smoke fails or the engine behavior regresses, remove the optimization

After all planned trusted features and accepted `duck-1` optimizations are in:

1. run 64-game local tournaments against each of:
   - `jon-6-a9bfs-surround`
   - `leeroy-jonkins`
   - `jon-6`
2. require at least 80% win rate against each opponent
3. require at least 150k average TiEq
4. use those tournaments to bug-hunt, tune, optimize, and refine
5. only after local results are favorable, run 15 remote games against each opponent
6. require at least a 9-6 remote match score against each opponent before closing

## Feature sequencing

Trusted-feature wave:

1. marker-system unification and timing-governor substrate
2. perception boundary and cached marker views
3. anytime-resume navigation
4. speculative navigation
5. hijack consolidation
6. combat consolidation:
   - assault posture
   - trench posture
   - zerg posture
   - offensive logistics
   - smart aiming

`duck-1` wave:

1. inspect one optimization primitive at a time
2. re-derive it against trusted behavior
3. validate it in unit tests and local engine smoke before keeping it

## Trusted-wave results

- `marker-system unification and timing-governor substrate`
  - smoke: `14-2` vs `jon-6-a9bfs-surround` (`87.5%`)
  - report: `.dist/reports/got-any-grapes_trusted1800_smoke.json`
  - commit: `642149e`
- `world-orientation marker sharing`
  - smoke: `11-5` vs `jon-6-a9bfs-surround` (`68.8%`)
  - report: `.dist/reports/got-any-grapes_orientation_smoke.json`
  - commit: `7c5a7a7`
- `opportunistic hijack mode`
  - smoke: `13-3` vs `jon-6-a9bfs-surround` (`81.2%`)
  - report: `.dist/reports/got-any-grapes_hijack_smoke.json`
  - commit: `bdedac1`
- `frontier recovery on single-builder stall`
  - smoke: `10-6` vs `jon-6-a9bfs-surround` (`62.5%`)
  - report: `.dist/reports/got-any-grapes_frontier_recovery_smoke.json`
  - commit: `d9442a7`
- `economy opening unclog`
  - smoke: `12-4` vs `jon-6-a9bfs-surround` (`75.0%`)
  - report: `.dist/reports/got-any-grapes_opening_unclog_smoke.json`
  - commit: `df15e7f`
- `ore-route temporary blacklist`
  - smoke: `13-3` vs `jon-6-a9bfs-surround` (`81.2%`)
  - report: `.dist/reports/got-any-grapes_ore_blacklist_v2_smoke.json`
  - commit: `479c86b`
- `faster opening-shell ore retarget`
  - smoke: `10-6` vs `jon-6-a9bfs-surround` (`62.5%`)
  - report: `.dist/reports/got-any-grapes_early_ore_retry_smoke.json`
  - probe: `12-4` vs `jon-6`
  - probe report: `.dist/reports/got-any-grapes_early_ore_retry_probe_jon6_16.json`
  - commit: `3ef772e`
- `assault arc target selection for live closeout`
  - proved bug: same-ring sentinel arc selection could ignore a legal core-hitting firing arc
  - focused test: `test_assault_site_prefers_core_hitting_arc_on_same_ring`
  - smoke: `11-5` vs `jon-6-a9bfs-surround` (`68.8%`)
  - smoke report: `.dist/reports/got-any-grapes_assault_arc_fix_smoke.json`
  - probe: `10-6` vs `jon-6`
  - probe report: `.dist/reports/got-any-grapes_assault_arc_fix_probe_jon6_16.json`
  - win-condition shift vs `jon-6`: `3` core-destruction wins, `7` tiebreak wins
- `hijack loss recovery at secured outlet`
  - proved bug: a hijack bot that lost vision while already standing on the hijack entry tile would forget the hijack and drop to `EXPLORING`
  - focused test: `test_hijack_mode_tiles_back_when_target_is_lost_on_secured_entry`
  - smoke: `12-4` vs `jon-6-a9bfs-surround` (`75.0%`)
  - smoke report: `.dist/reports/got-any-grapes_hijack_loss_recovery_smoke.json`
  - probe: `13-3` vs `jon-6`
  - probe report: `.dist/reports/got-any-grapes_hijack_loss_recovery_probe_jon6_16.json`
  - secondary probe: `13-3` vs `leeroy-jonkins`
  - secondary probe report: `.dist/reports/got-any-grapes_hijack_loss_recovery_probe_leeroy16.json`
  - note: this improved floor and matchup stability, but `jon-6` wins in the 16-game probe were still all tiebreak wins
- `duck-1 nav low-risk imports`
  - imported mechanical-only changes:
    - greedy fallback now uses `_heuristic(...)` instead of ad hoc Manhattan distance
    - default bridge branching is suppressed while a tiling-back bridge plan is already pending
  - focused tests:
    - `test_greedy_fallback_uses_navigation_heuristic`
    - `test_astar_default_bridge_gating_skips_bridge_when_plan_is_pending`
  - smoke: `11-5` vs `jon-6-a9bfs-surround` (`68.8%`)
  - smoke report: `.dist/reports/got-any-grapes_duck_nav_lowrisk_smoke.json`
- `duck-1 marker/perception constant-factor imports`
  - imported mechanical-only changes:
    - nearby marker scanning now dispatches by encoded marker type instead of walking unrelated parsers first
    - building HP reads are skipped for enemy buildings even during healing-capable scans
  - focused tests:
    - `test_perception_marker_dispatch_skips_unrelated_parsers`
    - `test_perception_only_reads_building_health_for_friendly_buildings`
  - smoke: `10-6` vs `jon-6-a9bfs-surround` (`62.5%`)
  - smoke report: `.dist/reports/got-any-grapes_duck_marker_perception_smoke.json`
- `duck-1 assault local-escape import`
  - imported mechanical-only change:
    - when assault BFS picks a live step but execution is blocked by a builder bot, try one local wall-follow sidestep before turning the turn into a failed replan
  - focused test:
    - `test_assault_navigation_uses_local_escape_when_direct_step_is_blocked`
  - first attempt was too eager and missed smoke (`9-7`); narrowed to builder-congestion-only trigger
  - final smoke: `12-4` vs `jon-6-a9bfs-surround` (`75.0%`)
  - smoke report: `.dist/reports/got-any-grapes_duck_assault_escape_v2_smoke.json`
- `anytime-return and speculative A*`
  - added a resumable anytime A* planner state for non-assault pathfinding
  - planner is deliberately conservative:
    - full A* remains primary on healthy turns
    - anytime planning resumes only after an interrupted/empty expensive search
    - speculative suffix extension only runs for short tiling-back paths and only appends exact suffixes
  - focused tests:
    - `test_anytime_astar_resumes_after_partial_slice`
    - `test_speculative_extension_appends_suffix_to_cached_path`
  - first two versions were too broad and missed smoke (`9-7`, `9-7`)
  - final smoke: `13-3` vs `jon-6-a9bfs-surround` (`81.2%`)
  - smoke report: `.dist/reports/got-any-grapes_anytime_speculative_v3_smoke.json`
