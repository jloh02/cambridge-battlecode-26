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
- Preserve the current `jon-5o` opening until the team has `2` completed connected friendly harvester lanes.
- After that gate, assign the next `2` diagonal-spawn builders to permanent assault duty.
- Unlock a `3rd` assault builder only when all are true:
  - at least `3` completed connected friendly harvester lanes,
  - at least `7` friendly builders alive,
  - titanium reserve is at least `harvester_cost + sentinel_cost + 2 * conveyor_cost`.
- Assault builders do not return to ore-finding or tiling-back.

## State

### Core State
- `completed_connected_harvesters`
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

## Phase 2: Execute On A Visible Harvester
This part should stay decentralized and visible-state based.

### Terms
- `ring site`: one cardinal-adjacent tile to the harvester.
- `BUILT`: friendly sentinel already on that ring tile.
- `OCCUPIED`: any unit body is standing on that ring tile now.
- `CLEARABLE`: enemy conveyor or armoured conveyor is on that ring tile.
- `OPEN`: immediately buildable now.
- `BLOCKED`: not usable now.

### Routine 3: `CHOOSE_VISIBLE_ASSAULT_SITE()`
1. Enumerate visible enemy harvesters.
2. For each harvester:
   - enumerate its `4` ring sites,
   - classify each site from visible tile state only,
   - enumerate legal sentinel facings,
   - reject inward or non-feeding facings,
   - reject facings with no useful denial value,
   - reject threatened sites unless an immediate build produces an immediately useful sentinel.
3. Score the best site by:
   - current `harvester_anchor` first,
   - non-threatened before threatened,
   - fewer turns to first useful shot,
   - shorter path to ring tile,
   - larger local logistics cluster,
   - more usable ring sides,
   - deterministic tie-break.
4. Return the best visible site or `None`.

### Routine 4: `EXECUTE_ASSAULT_SITE(site)`
1. Set `harvester_anchor = site.harvester_position`.
2. Refresh `harvester_anchor_last_seen_round`.
3. If standing on the target ring tile:
   - if the tile is `CLEARABLE`, destroy it immediately,
   - else sidestep off the tile without stepping onto the harvester.
4. Else if adjacent to the ring tile:
   - if the tile is `CLEARABLE`, move/clear toward it,
   - else if the tile is `OPEN` and `can_build_sentinel`, build immediately.
5. Else move toward the ring tile.

### Routine 5: `SUPPORT_HARASSMENT(anchor)`
1. If no legal ring build exists right now:
   - harass enemy builders first,
   - then conveyors / bridges / foundries in the same local cluster,
   - then defenders blocking the ring.
2. Recompute visible ring sites next turn.
3. Switch back to `EXECUTE_ASSAULT_SITE` as soon as a useful `OPEN` or `CLEARABLE` site appears.

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

## What We Explicitly Do Not Keep From `jon-5a1`
- Spawn-slot deciding the one true symmetry mode forever.
- The exact old anchor heuristic as policy gospel.
- Any hidden-state teammate election.

## What Is Deferred
- Sophisticated same-lane crawl after semi-lock.
- Deep multi-anchor lane planning.
- Marker-based assault coordination.
- More advanced support subroles.

These are deferred until the bot can reliably:
- reach enemy-side economy,
- build one sentinel,
- and avoid scout collapse.

## Tests
- Verify assault mode does not activate before `2` completed connected harvester lanes.
- Verify visible enemy core overrides inference immediately.
- Verify visible enemy harvester overrides prediction immediately.
- Verify scout objectives are slot-dispersed before first contact.
- Verify raiders do not all choose the same top predicted harvester when multiple sector candidates exist.
- Verify scout rotation occurs after stall.
- Verify visible `BUILT` and `OCCUPIED` ring tiles are treated as hard state.
- Verify an adjacent friendly builder does not suppress an immediate legal build.
- Verify a `CLEARABLE` ring tile is destroyed immediately when already occupied by the raider.
- Verify a legal `OPEN` ring tile is built immediately.
- Verify a visible built sentinel suppresses duplicate same-site builds on later turns.
- Verify support harassment takes over when no useful ring build exists.

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
