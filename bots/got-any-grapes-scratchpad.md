# got-any-grapes scratchpad

## Promotion ladder

Checkpoint baseline for the refinement loop:

- `f2e958e` `Simplify anytime planner draft in got-any-grapes`
- keep the bot on the anytime-only planner by default:
  - `1.9 ms` soft planner deadline
  - `2.0 ms` hard turn cap
  - full A* first on healthy turns
  - resumable anytime-return A* as the bounded fallback
  - no speculative live planning
  - no greedy live fallback

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

Refinement loop after checkpoint:

1. optimize primitives for time complexity first
2. debug primitives for contract violations and aberrant behavior
3. debug strategy against:
   - `jon-6-a9bfs-surround`
   - `jon-6`
   - `leeroy-jonkins`
4. once a candidate clears the `60%` surround smoke, run `64` local games against each opponent
5. require per opponent:
   - at least `80%` win rate
   - at least `150k` average `TiEq`
6. if a 64-game gate fails, drop back to `16`-game smoke with the stricter per-opponent bar:
   - at least `80%` win rate
   - at least `150k` average `TiEq`
7. only after the local `64`-game gates pass for all three opponents should remote validation begin

Tooling defaults for the refinement loop:

- local benchmark promotion gate now defaults to:
  - `80%` win rate
  - `150k` average `TiEq`
  - no worst-`TiEq` requirement unless explicitly enabled
- reports should surface per opponent:
  - win rate
  - average `TiEq`
  - worst `TiEq`
  - TLE turns
  - win-condition mix

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
  - initial integrated version cleared smoke, but the simpler anytime-only variant was cleaner and safer
  - kept version:
    - full A* remains primary on healthy turns
    - anytime planning resumes only after an interrupted/empty expensive search or when a prior anytime search is already in flight
    - greedy fallback removed from live pathfinding
    - speculative planning removed from the live pathfinding loop for now
    - decision timing updated to `1.9 ms` soft / `2.0 ms` hard
  - focused tests:
    - `test_anytime_astar_resumes_after_partial_slice`
    - `test_repeated_replan_uses_anytime_partial_instead_of_greedy`
  - broader speculative versions missed smoke (`9-7`, `9-7`)
  - final anytime-only smoke: `10-6` vs `jon-6-a9bfs-surround` (`62.5%`)
  - final smoke report: `.dist/reports/got-any-grapes_anytime_only_smoke.json`

## Replay review checklist

When a smoke or 64-game gate fails, inspect failed opponents and classify the loss into one or more of:

- econ stall
  - slow harvester conversion
  - delivery lane never completed
  - builders alive but not converting into resource flow
- frontier collapse
  - assault anchor dies too easily
  - trench/frontline control evaporates after one stall
  - forward pressure never stabilizes
- no-closeout resource wins
  - winning by tiebreak only
  - frontier pressure not turning into core kills
- congestion or loop behavior
  - repeated local oscillation
  - spawn shell or lane self-blocking
  - blocked-step recovery failing repeatedly
- TLE pressure
  - high turns-over-2ms rate
  - recurring `tled_turns`
  - planner or perception spikes under clutter

For every retained strategic change, record:

- what failure mode it fixes
- which opponent class it helps
- which opponent class it may weaken against
- what exploit or bait pattern it introduces if overused

## Refinement results after checkpoint `f2e958e`

- tooling aligned to the real local gate:
  - default promotion gate is now `80%` win rate and `150k` average `TiEq` per opponent
  - no worst-`TiEq` requirement by default
  - reports now surface per-opponent `TLE` turns and win-condition mix
- checkpoint smoke remained above the base bar:
  - `.dist/reports/got-any-grapes_anytime_only_smoke.json`
  - `10-6` vs `jon-6-a9bfs-surround`
- first full `64`-game local gate on the checkpoint:
  - report: `.dist/reports/got-any-grapes_refinement64_v1.json`
  - aggregate: `64.1%`, avg `TiEq 30596.0`, `0` TLE turns
  - `jon-6`: `48-16`, `75.0%`, avg `TiEq 39447.0`
  - `jon-6-a9bfs-surround`: `40-24`, `62.5%`, avg `TiEq 25770.3`
  - `leeroy-jonkins`: `35-29`, `54.7%`, avg `TiEq 26570.8`
  - failed opponents:
    - `jon-6`: `win_rate`, `tieq_avg`
    - `jon-6-a9bfs-surround`: `win_rate`, `tieq_avg`
    - `leeroy-jonkins`: `win_rate`, `tieq_avg`
- immediate diagnosis from the gate:
  - the bot is stable and TLE-clean
  - the main weakness is not legality or timeout pressure
  - the main weakness is strategic throughput and closeout:
    - too many wins are still tiebreak/resource wins
    - `leeroy-jonkins` is the weakest current matchup
    - `jon-6-a9bfs-surround` is still the main frontier-pressure check
