# CODEX Scratchpad

## Active Strategy Name

Lane-role separation: harden home-lane economy completion, preserve productive front-side disruption, and only then retune offense commitment.

## Task Description

Improve `got-any-grapes` from its current low-floor, tiebreak-heavy state into a stable promotion candidate by:
- reconciling stale bot docs with live behavior
- removing stale/inactive rush doctrine
- fixing the main builder stall / loop / no-progress failures first
- keeping routing purely A*-driven with persistent resumable search state
- making offense less permanently overcommitted after the floor is stabilized
- validating changes with the staged workflow in `CODEX_INSTRUCTIONS.md`

## Criteria

- Follow the repository workflow and promotion criteria from `CODEX_INSTRUCTIONS.md`
- Keep the substrate TLE-clean
- No greedy fallback
- No broad pathfinding rewrite beyond persistent pure-A* continuation and hot-loop optimization
- Keep macro routing policy, costs, heuristics, tie-break order, and bridge policy unchanged unless a concrete regression forces adjustment
- Add focused pytest coverage for new local contracts
- Use replay-backed diagnosis for failures
- Keep this scratchpad current at the end of each iteration

## Latest Evidence

### Current Retained Baseline

- Retained candidate: `.dist/reports/got-any-grapes_nav_floor_smoke_g16_v2.json`
- Aggregate: `66.7%`, avg `TiEq 36465.0`, `0` TLE turns
- Per opponent:
  - `jon-6`: `12-4`, `75.0%`
  - `jon-6-a9bfs-surround`: `11-5`, `68.8%`
  - `leeroy-jonkins`: `9-7`, `56.2%`
- The baseline is still tiebreak-heavy rather than conversion-heavy:
  - most sampled game endings are titanium-tiebreaks
  - delivered refined axionite remains `0`
- Interpretation: the bot is surviving and disrupting enough to compete, but it is not converting pressure into a reliable, deep economy.

### Landed Changes Worth Keeping

- Persistent A* substrate cleanup is retained:
  - planner state persists across turns
  - planner reuse keys on obstacle identity
  - anytime hot-loop ranking no longer reconstructs full paths
- Shared no-progress recovery is retained for ore/explore paths.
- Docs/repo cleanup is retained:
  - `bots/got-any-grapes/EXPLAINER.md` rebuilt from live behavior
  - `bots/got-any-grapes/README.md` corrected
  - dead rush-only files removed: `mode_rush.py`, `rush_gunner_bot.py`

### Replay-Backed Diagnosis That Still Matters

- The remaining floor failures are concentrated in `TILING_BACK`, not in the core A* substrate.
- Key retained replays:
  - `cold`: `.dist/replays/gag_debug_cold_leeroy_seed1019237068.replay26`
  - `starry_night`: `.dist/replays/gag_debug_starry_retained_rerun_seed2065478786.replay26`
  - `default_large2`: `.dist/replays/gag_debug_default_large2_retained_rerun_seed1025035697.replay26`
- `cold` and `starry_night` show home-lane economy collapse behavior:
  - builders stay in `TILING_BACK`
  - `_execute_pending_build` can return every turn before navigation
  - late builders show tiny `mode_us` and missing `nav_*` counters
  - hostile passable tiles can stay blocked through attack/heal or rebuild cycles
- `default_large2` shows something meaningfully different:
  - superficially similar contested hostile-tile waits can be productive
  - short hostile-clearing windows on advancing coordinates are preserving disruption value rather than causing the collapse
- Working interpretation:
  - there is not one “pending build bug”
  - there are at least two families of behavior that we keep conflating:
  - dead home-lane economy churn near return targets
  - productive front-side contested-lane disruption

### What Recent Rollbacks Actually Proved

- Broad offense pullback is not the current highest-leverage fix:
  - `assault_quota_smoke_g16`
  - `assault_fallback_smoke_g16`
  - both regressed the retained candidate
- Generic escape or retry logic is too blunt:
  - `pending_build_retry_smoke_g16`
  - `hostile_wait_escape_smoke_g16`
  - multiple local-only `recontest` / `serial` / `static` replay branches
  - these helped some collapse slices but repeatedly damaged strong maps by suppressing productive disruption
- Heal-aware hostile clearing is directionally interesting but not yet safe:
  - `healwatch_smoke_g16`
  - it improved some preserve-closeout lanes and some `jon-6-a9bfs-surround` cases, but regressed too many strong maps
- Shared-recovery integration for pending-build loops was also too blunt:
  - the `progress_contract` branches showed that progress accounting alone still cannot separate home-lane deadlocks from productive contested lanes
- `CORE` versus `CONVEYOR` return target is a useful clue, but not a sufficient classifier:
  - the `CORE`-return-only gate improved `starry_night`
  - it still failed `cold`
  - it still damaged `default_large2`

### What I Am Probably Still Missing

- Lane role is not formalized enough.
  - I have replay anecdotes, but not a crisp classifier for home-side economy lane versus front-side disruption lane.
- Opportunity cost is under-measured.
  - I know some contested waits are productive, but I have not quantified when enemy delay outweighs our own delayed delivery.
- Timing is under-measured.
  - Aggregate `TiEq` and final tiebreak outcomes hide whether the bot is missing critical early and midgame delivery windows.
- Spatial context is under-measured.
  - “returning to `CORE`” is too coarse; I likely need home-shell distance, lane direction, and whether the builder is on the front side or inside the return network.
- Opponent response patterns are under-measured.
  - `leeroy-jonkins`, `jon-6`, and `jon-6-a9bfs-surround` may punish the same stall state differently because rebuild/heal cadence differs.

## Immediate Next Action

Use the retained baseline as the control and improve classification before editing behavior again:
- instrument or inspect retained replays for lane role and spatial context on `cold`, `starry_night`, and `default_large2`
- identify the narrowest `TILING_BACK` completion/control point where home-lane versus front-side context can safely change behavior
- prefer home-lane completion logic over another generic pending-build escape or routing-level intervention
- keep disruption-preserving behavior as the default unless the lane-role evidence says the builder is starving the economy

## Compaction-Safe Resume Point

Resume from the retained `nav_floor_smoke_g16_v2` candidate.

Keep:
- persistent A* planner state
- obstacle-identity planner reuse
- anytime hot-loop optimization
- shared stall recovery in ore/explore
- docs cleanup and rush-code removal

Do not resume:
- broad offense pullback
- generic pending-build escape / retry branches
- generic shared-recovery hooks for all pending-build waits

Current best framing:
- the main remaining weakness is an economy-completion problem, not a broad pathfinding problem
- the key mistake in recent failed branches was suppressing productive disruption while trying to clear true home-lane deadlocks
- the next real unlock is a stronger lane-role discriminator, then a narrow `TILING_BACK` completion intervention

Most relevant artifacts to reopen first:
- baseline report: `.dist/reports/got-any-grapes_nav_floor_smoke_g16_v2.json`
- `cold`: `.dist/replays/gag_debug_cold_leeroy_seed1019237068.replay26`
- `starry_night`: `.dist/replays/gag_debug_starry_retained_rerun_seed2065478786.replay26`
- `default_large2`: `.dist/replays/gag_debug_default_large2_retained_rerun_seed1025035697.replay26`

## Iteration Log

### Summary Of Kept Work

- Iteration group A:
  - landed persistent A* cleanup and hot-loop optimization
  - landed shared no-progress recovery for ore/explore
  - improved the local smoke baseline to the retained `nav_floor_smoke_g16_v2` result
- Iteration group B:
  - updated `bots/got-any-grapes/EXPLAINER.md`
  - corrected stale bot docs
  - removed dead rush-only codepaths

### Summary Of Rejected Work

- Offense pullback family:
  - removing or softening bonus assault commitment regressed the retained candidate
- Generic navigation/retry family:
  - bridge retry, pending-build retry, and generic hostile-tile escape branches all proved too broad
- Shared-recovery extension family:
  - feeding `TILING_BACK` pending-build loops into shared no-progress recovery did not separate dead economy waits from productive disruption
- Narrow hostile-wait classifiers:
  - same-coordinate, same-id, heal-aware, and `CORE`-return-only variants each explained part of the split, but none were safe enough to keep

### Latest Reflection

- No bot behavior change was kept in the latest reflection pass.
- The scratchpad was rewritten to keep only current strategy, retained evidence, missing blind spots, and the next medium-term priorities.
- Exact next action:
  - inspect or instrument retained replays for lane role and home-side versus front-side context before making another behavior change.
