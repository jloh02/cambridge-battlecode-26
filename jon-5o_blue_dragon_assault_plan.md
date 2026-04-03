# `jon-5o-a1` Living Implementation Plan

This document is the current implementation plan for `jon-5o-a1`.

It replaces earlier mixed versions of the plan. The main cleanup is:
- remove stale hidden-state coordination ideas,
- separate global scouting from local ring execution,
- defer fancy lane-crawl logic until the bot can reliably find one enemy harvester and place one sentinel.

## Goal
- Keep `jon-5o`'s economy and tiling-back backbone.
- Add a small permanent assault package that can:
  - reach the enemy side,
  - find an enemy harvester,
  - place at least one useful sentinel,
  - then convert that foothold into local denial.

## Current Diagnosis

### What Is Actually Going Wrong
- The clustering problem looks more like objective collapse than raw A* failure.
- `jon-5o-a1` currently tends to funnel raiders toward one shared inferred objective:
  - one `best_symmetry_mode`,
  - one `enemy_core_anchor`,
  - often one top predicted harvester,
  - then one small spread pattern around that anchor.
- When several raiders choose the same long-range anchor, the pathfinder naturally sends them through the same corridor or choke.
- The visible result looks like "bad pathing", but the deeper problem is "too many bots chose the same destination."

### Why `jon-5a1` Still Finds Harvesters And Places Guns
- `jon-5a1` is simpler and more decisive before first contact.
- Each assault bot gets a slot-specific symmetry guess and anchor offset.
- Each assault bot scouts a different direction around that slot-specific anchor.
- As soon as a visible harvester exists, `jon-5a1` immediately switches to:
  - choose best visible site,
  - move to ring tile,
  - clear if needed,
  - build if legal.
- It does not spend as much effort ranking mirrored harvester candidates before first contact.

### Concrete Comparison
- `jon-5o-a1` scouting collapse:
  - [bots/jon-5o-a1/mode_assaulting.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/mode_assaulting.py#L415) picks `live_anchor`, else `predicted_enemy_harvesters[0]`, else one `enemy_core_anchor`.
  - [bots/jon-5o-a1/assault.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/assault.py#L992) only spreads a few tiles around that one anchor.
- `jon-5a1` scout dispersion:
  - [bots/jon-5a1/mode_assaulting.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5a1/mode_assaulting.py#L32) predicts the enemy side per slot.
  - [bots/jon-5a1/mode_assaulting.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5a1/mode_assaulting.py#L234) scouts a slot-specific direction immediately.
  - [bots/jon-5a1/mode_assaulting.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5a1/mode_assaulting.py#L248) immediately executes a visible site once found.

## Design Principles
- Use only visible world state for local assault coordination.
- Do not infer teammate intent from hidden local state.
- Separate "how do we find a target?" from "how do we coordinate on a visible target?"
- Before first contact, hard dispersion matters more than clever ranking.
- After first contact, visible local action matters more than long-range prediction.
- First milestone is not "perfect lane crawl." First milestone is "reliably get one gun on one enemy harvester."

## Macro Rules
- Preserve the current `jon-5o` opening floor until the team has the usual first `4` economy builders.
- After that floor, the first `2` diagonal-spawn builders are always permanent assault bots.
- Unlock a `3rd` assault builder only when global titanium is at least `90`.
- Assault builders do not return to ore-finding or tiling-back.
- `MIN_CONNECTED_LANES_FOR_BONUS_ASSAULT` remains in code only as a potentially unused future-tuning constant; it is not part of the current assault quota logic.

## State

### Core State
- `assault_quota`
- `assault_spawned`

### Builder State
- `is_assault_role`
- `spawn_slot`
- `last_enemy_core_position`
- `enemy_core_anchor`
- `enemy_core_exact`
- `symmetry_candidates`
- `best_symmetry_mode`
- `confirmed_enemy_harvesters`
- `predicted_enemy_harvesters`
- `harvester_anchor`
- `harvester_anchor_last_seen_round`
- `assault_anchor_blacklist`
- `assault_anchor_status`
- `assault_last_site_signature`
- `assault_last_progress_round`
- `recent_assault_waypoints`

## Two-Phase Assault Algorithm

### Phase 1: Acquire A Harvester
This is the phase that needs to be simple and hard to deadlock.

#### Routine 1: `UPDATE_ENEMY_INFERENCE()`
1. Refresh visible hostile memory.
2. If enemy core is visible:
   - set `enemy_core_anchor` to the exact core position,
   - set `enemy_core_exact = true`.
3. Else occasionally refresh surviving symmetry modes from remembered terrain.
4. Build predicted enemy harvester candidates from:
   - visible enemy harvesters,
   - mirrored connected friendly harvesters,
   - mirrored ore near active home lanes.
5. Keep prediction as a ranking hint, not a team-global hard assignment.

#### Routine 2: `CHOOSE_SCOUT_OBJECTIVE()`
1. If a visible enemy harvester exists, stop scouting and switch to Phase 2 immediately.
2. Else if `harvester_anchor` is still live, keep moving toward that anchor.
3. Else if enemy core is exact, scout around that enemy side by slot.
4. Else if symmetry is still uncertain:
   - each raider owns a different symmetry / direction hypothesis,
   - do not collapse all raiders onto one global `best_mode` target.
5. Else if predictions exist:
   - each raider uses a slot-specific ordered subset of the candidate list,
   - do not send every raider to `predicted_enemy_harvesters[0]`.
6. If a scout objective stalls or gets crowded, rotate to the next slot-owned candidate.

### Required Scout Dispersion Rule
- Hard dispersion is required before first contact.
- A raider may use prediction to rank targets inside its own sector.
- A raider may not treat the globally best predicted harvester as the only legal destination for the whole team.

### Practical Slot Policy
- Slot `0`: first symmetry candidate, north/east side bias.
- Slot `1`: second symmetry candidate or alternate side bias on the same mode.
- Slot `2`: third symmetry candidate or south/east side bias.
- Slot `3`: fallback / hedge slot.

The exact slot mapping can be adjusted, but the property must hold:
- different slots should explore meaningfully different enemy-side entry regions.

## Phase 2: Execute And Retire Anchors
This part stays decentralized and visible-state based, but now includes an
explicit anchor-lifecycle layer so the bot can move on once a local denial job
is already done.

### Terms
- `ring site`: one cardinal-adjacent tile to the harvester.
- `BUILT`: friendly sentinel already on that ring tile.
- `OCCUPIED`: any unit body is standing on that ring tile now.
- `CLEARABLE`: enemy conveyor or armoured conveyor is on that ring tile.
- `OPEN`: immediately buildable now.
- `BLOCKED`: not usable now.

### Routine 3: `ASSESS_ANCHOR(anchor)`
1. Build the visible enemy logistics cluster rooted at the harvester.
2. Count:
   - enemy logistics still attached to that cluster,
   - adjacent friendly connected conveyors,
   - friendly ring sentinels already built around the anchor,
   - useful remaining ring sites with positive marginal value.
3. Classify the anchor as exactly one of:
   - `LIVE`
   - `CAPTURED_BY_US`
   - `DRIED_OUT`
   - `SATURATED`
4. Competitive-programming invariant:
   - an anchor may only stay live if it still has positive marginal value or no local pressure has been established yet.

### Routine 4: `RANK_ASSAULT_SITES(anchor)`
1. Enumerate all `4` ring sites and all `8` sentinel facings.
2. Reject:
   - inward / non-feeding facings,
   - blocked or occupied ring tiles,
   - threatened sites unless the immediate shot is into a turret,
   - duplicate-value sites that add no new visible denial beyond existing friendly ring sentinels.
3. For each remaining site, compute:
   - `total_target_value`
   - `marginal_value`
   - `uncovered_target_count`
4. Score sites by:
   - current anchor first,
   - non-threatened before threatened,
   - higher marginal value first,
   - more uncovered targets first,
   - higher total target value,
   - faster time to first useful shot,
   - shorter path,
   - bigger local cluster,
   - deterministic tie-break.
5. Only allow the old exploratory fallback site when:
   - there is no friendly ring sentinel yet,
   - the harvester is not already feeding our connected line,
   - and we still want one first-contact probe around a recent/visible anchor.

### Routine 5: `EXECUTE_OR_RETIRE(anchor, ranked_sites)`
1. If `ASSESS_ANCHOR` returns `CAPTURED_BY_US`, `DRIED_OUT`, or `SATURATED`:
   - blacklist the anchor immediately,
   - clear `harvester_anchor`,
   - resume scouting.
2. Else if a ranked site exists:
   - remember its site signature,
   - only refresh `assault_last_progress_round` on:
     - new site selection,
     - building a sentinel,
     - clearing a blocking conveyor,
     - or a local sidestep that changes occupancy.
3. Build-vs-clear order:
   - `BUILD_NOW` if any legal immediate site has positive marginal value.
   - `CLEAR_TO_UNLOCK` only when clearing the chosen ring tile unlocks that positive-value build.
   - `DIRECT_FIRE` only for local harassment when no positive-value build exists.
4. If the bot is locally stalled near the same anchor with no new value:
   - blacklist the anchor,
   - do not reacquire it immediately from confirmed memory,
   - switch back to scouting.

### Routine 6: `SENTINEL_FIRE_POLICY()`
1. If the adjacent anchor still has a live enemy logistics tail:
   - `turrets > connected logistics > core > anything else`
2. If the local line is basically dead:
   - `turrets > core > leftover logistics > anything else`
3. Never prioritize the adjacent anchor harvester body itself.
4. Competitive-programming invariant:
   - once an anchor is strategically dead, both the builder and the sentinel must stop spending turns on dead-line cleanup unless it unlocks new denial.

## Local Coordination Rules

### Hard Shared State
- A friendly sentinel already built on a ring tile.
- A unit body physically occupying a ring tile.
- A conveyor physically blocking a ring tile.

### Non-State That Must Not Become A Hard Claim
- A nearby friendly builder.
- A teammate being closer to the ring tile.
- A guessed teammate role such as "builder" or "support."

### Exact Case Handling

#### Case A: One Good Ring Site, Two Raiders
- Both may converge.
- One may waste one turn.
- Next-turn visible state resolves the duplication.

#### Case B: Multiple Comparable Ring Sites
- Use slot bias only as a tie-break.
- Do not let the bias override a clearly superior site.

#### Case C: Friendly Builder On The Ring Tile
- Treat as `OCCUPIED`.
- Do not try to build through it this turn.

#### Case D: Friendly Builder Adjacent To The Ring Tile
- Not a hard claim.
- Still build if legal.

#### Case E: Enemy Conveyor On The Ring Tile
- If already on the tile, destroy now.
- Else move toward it if it is still the best site.

#### Case F: Friendly Sentinel Already Built
- Treat as `BUILT`.
- Pick another useful site or harass.

#### Case G: No Useful Ring Site Exists
- Harass.
- Recompute next turn.
- Do not idle.

## What We Keep From `jon-5a1`
- Immediate commitment to a visible harvester.
- Simple scout dispersion by slot.
- A direct "find site -> move -> clear -> build" loop.

## Implemented So Far
- Representative benchmark artifacts now save with timestamped matchup names for both JSON and replay directories.
- Representative benchmark runs now force debug replay stdout and indicator lines on by default, with `--no-debug` as an explicit opt-out.
- Pre-contact scouting is slot-dispersed instead of collapsing onto one shared predicted anchor.
- If no visible harvester exists, assault bots optimize for discovery rather than over-committing to stale inference.
- If a visible or recently confirmed harvester exists, assault bots hard-commit locally until the anchor is disproven or stalls.
- Visible-state local ring execution is in place, and assault bots are now placing sentinels.
- The first `2` assault bots now spawn unconditionally after the opening economy floor instead of waiting for connected-lane markers.
- Placed sentinels now have a local controller and fire at legal nearby targets instead of idling forever.
- Assault pathing now replans around non-objective enemy builder bodies instead of repeatedly face-blocking into them.
- Anchors now have explicit retirement states: `LIVE`, `CAPTURED_BY_US`, `DRIED_OUT`, `SATURATED`.
- Retired anchors are now blacklisted so the bot does not immediately reacquire the same dead objective from confirmed memory.
- Site selection now scores marginal new denial instead of only one raw best site, so follow-up ring sites can beat duplicate-value ones.
- Sentinel targeting now promotes the enemy core once the local logistics tail is basically dead.

## What We Explicitly Do Not Keep From `jon-5a1`
- Spawn-slot deciding the one true symmetry mode forever.
- The exact old anchor heuristic as policy gospel.
- Any hidden-state teammate election.

## What Is Deferred
- Sophisticated same-lane crawl after semi-lock.
- Deep multi-anchor lane planning.
- Marker-based assault coordination.
- The broader A* / wide-route congestion fix when the bot should commit to a long detour around body walls instead of repeatedly preferring the same blocked lane.

These are deferred until the bot can reliably:
- reach enemy-side economy,
- build one sentinel,
- and avoid scout collapse.

## Tests
- Verify the first `2` assault bots do not wait for connected-lane markers.
- Verify the `3rd` assault bot unlocks only at `90` titanium.
- Verify visible enemy core overrides inference immediately.
- Verify visible enemy harvester overrides prediction immediately.
- Verify scout objectives are slot-dispersed before first contact.
- Verify raiders do not all choose the same top predicted harvester when multiple sector candidates exist.
- Verify scout rotation occurs after stall.
- Verify sentinels instantiate a local controller and fire the highest-priority legal target while ignoring the adjacent anchor harvester.
- Verify visible `BUILT` and `OCCUPIED` ring tiles are treated as hard state.
- Verify an adjacent friendly builder does not suppress an immediate legal build.
- Verify a `CLEARABLE` ring tile is destroyed immediately when already occupied by the raider.
- Verify a legal `OPEN` ring tile is built immediately.
- Verify a visible built sentinel suppresses duplicate same-site builds on later turns.
- Verify support harassment takes over when no useful ring build exists.
- Verify assault pathing adds a temporary obstacle for non-objective enemy builders but not for an enemy builder standing on the actual objective tile.

## Findings / Improvement Log
- 2026-04-03: initial `jon-5o-a1` implementation landed as a `jon-5o` fork with delayed diagonal assault spawns, symmetry-scored inference, predicted harvester scouting, and visible-state ring execution.
- 2026-04-03: targeted tests in `tests/test_jon_5o_a1_assault.py` passed for helper-level behavior.
- 2026-04-03: first representative benchmark did not clear the target:
  - vs `jon-5o`: `12/20` wins (`60%`)
  - vs `jon-5`: `9/20` wins (`45%`)
- 2026-04-03: after removing hidden `ring_builder` election and using visible-state local execution:
  - vs `jon-5o`: `10/20` wins (`50%`)
  - vs `jon-5`: `9/20` wins (`45%`)
- 2026-04-03: conclusion from replay discussion:
  - the no-turret deadlock issue was real and is fixed in principle,
  - the remaining issue is broader scout collapse and assault acquisition inefficiency.
- 2026-04-03: comparison against `jon-5a1` shows why `jon-5a1` still places guns:
  - it disperses early scouts more aggressively,
  - it commits faster once a visible harvester appears,
  - it does less global pre-contact ranking that can collapse the whole assault team onto one stale target.
- 2026-04-03: representative benchmark artifacts now use timestamped matchup naming in both `.json` output and replay directories.
- 2026-04-03: the first `2` assault bots no longer wait for connected-lane reports; only the `3rd` assault bot is economically gated.
- 2026-04-03: representative benchmark replays now restore debug stdout and indicator lines by default.
- 2026-04-03: follow-up replay fixes landed:
  - placed sentinels now have a local controller and do fire,
  - assault pathing now treats non-objective enemy builders as short-lived obstacles and replans around them.
- 2026-04-03: anchor-lifecycle and marginal-value follow-up logic landed:
  - anchors are now assessed as `LIVE`, `CAPTURED_BY_US`, `DRIED_OUT`, or `SATURATED`,
  - retired anchors are blacklisted to avoid immediate reacquisition,
  - sentinel target priority now promotes the enemy core once the local logistics tail is nearly dead.
- 2026-04-03: latest full representative benchmark after these changes:
  - vs `jon-5o`: `11/20` wins (`55%`)
