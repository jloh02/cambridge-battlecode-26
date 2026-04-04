# jon-5o-a4bfs

`jon-5o-a4bfs` is the `jon-5o-a1` assault bot with one deliberate routing
change:

- economy modes keep the old `jon-5o` navigation stack
- assault bots do **not** use the generic A* stack
- assault bots use **BFS first**, then **Bug 2** as the fallback when the BFS
  route is blocked or temporarily disappears

The point of this fork is narrow and explicit: remove assault-mode dependence on
the old heuristic pathing, which was repeatedly preferring the same bad lane or
stalling against body walls.

## Replay Diagnosis: 2026-04-04

This variant now tracks the replay-specific regressions seen in:

- `.rep_bench/replays/20260404_123139_jon-5o-a3bfs_vs_jon-5o/jon-5o-a3bfs_vs_jon-5o_corridors_seed_1.replay26`
- `.rep_bench/replays/20260404_123139_jon-5o-a3bfs_vs_jon-5o/jon-5o_vs_jon-5o-a3bfs_wasteland_seed_1.replay26`
- `.rep_bench/replays/20260404_123139_jon-5o-a3bfs_vs_jon-5o/jon-5o-a3bfs_vs_jon-5o_default_medium1_seed_1.replay26`

Confirmed issues from the replay analyzer plus focused replay inspection:

- `corridors`: assault bot `913` does not literally set a return-to-core target,
  but it does reacquire bad cached scout targets on the home-side or near-home
  frontier and later ping-pongs between nearby local assault targets after
  center contact
- `wasteland`: builder `28` repeatedly attacks the ring conveyor at `(23, 23)`
  and then retires the anchor for `local stall` while the clearable target is
  still live
- `wasteland` and `default_medium1`: assault bots can blacklist or exhaust a
  local anchor and then immediately reacquire the same visible harvester again
  through `_best_visible_site`, which creates the observed two-target
  ping-ponging

The `a4` patch set is intentionally narrow:

- visible-site selection now respects anchor blacklist and exhausted-region
  cooldowns, so locally stalled harvesters are not immediately reacquired on
  the next turn just because they are still visible
- local-stall checks are now site-aware, so a bot that is still adjacent to a
  live clearable ring conveyor does not retire that anchor while it is waiting
  to finish the clear
- global frontier fallback now uses a stricter enemy-half test:
  a candidate chunk must actually be closer to the inferred enemy core than to
  our own core to count as enemy-side
- scout-target cache clearing is less eager:
  getting near a cached scout tile no longer forces an immediate retarget until
  the bot actually reaches that staging tile

Current validation after the `a4` replay-fix patch:

- `pytest tests/test_jon_5o_a4bfs_assault.py`: `4/4` passed
- nearby regression guard: `pytest tests/test_jon_5o_a3bfs_assault.py`: `5/5`
  passed
- smoke benchmark attempt vs `jon-5o` on
  `default_small1/default_medium1/default_large1`, seed `1`:
  the runner completed both `default_small1` seats and both `default_large1`
  seats, all won by `jon-5o-a4bfs`, but it did not finish emitting the
  `default_medium1` seat outputs or benchmark JSON before stalling

## Current Strategy

Macro and assault policy are the same as `jon-5o-a1`:

- normal `jon-5o` economy opening for the first `4` builders
- first `2` diagonal builders are permanent assault bots and are now forced as
  the turn `5` and turn `6` spawns in the standard opening
- `3rd` assault bot unlocks at `90` titanium
- visible or recently confirmed harvesters are hard-committed locally
- anchors are retired once they are `CAPTURED_BY_US`, `DRIED_OUT`, or
  `SATURATED`
- anchors can also retire as `GOOD_ENOUGH_MOVE_ON` once a local pressure asset
  already exists, no turret shot or core-center shot remains, and the best
  extra local work would add at most `1` newly uncovered logistics tile
- placed sentinels have a local controller and avoid mixed-tile friendly fire
- when scoring or discussing enemy-core pressure, only the enemy core center
  tile counts as a valid core target; touching the outer tiles of the `3x3`
  core footprint is not enough
- incomplete ring shells are acceptable once the remaining ring tiles have
  already been deleted or no longer add new denial value
- `SATURATED` means “a friendly ring sentinel already exists, at least `3`
  ring sides are resolved, and no unresolved side still offers a turret or
  core-center shot”

The main fork-specific difference is the assault movement layer.

## Implemented Changes

The fork now differs from the original `jon-5o-a1` assault stack in these
concrete ways:

- assault pathing is fork-local:
  builders in economy modes still use the old stack, but assault builders use
  BFS first and Bug 2 fallback only
- the first two assault builders are forced as the turn `5` and turn `6`
  diagonal spawns, instead of waiting on economy-connected-lane confirmation
- enemy-core pressure is normalized to the enemy core center tile only:
  visible outer footprint tiles stay blocked terrain, but they do not count as
  firing targets or assault value
- local shell completion is no longer “fill all four sides”:
  remaining ring sides matter only if they still create turret pressure,
  core-center pressure, or meaningful new logistics denial
- anchor retirement now has two different “done” flavors:
  `SATURATED` is the strict local-shell state, while `GOOD_ENOUGH_MOVE_ON` is
  the aggressive global move-on state once one lasting pressure asset exists
  and the best extra local work is trivial
- the move-on rule is implemented with explicit per-site metadata:
  each candidate site tracks whether it has a high-value target
  (`turret` or `core-center`) and how many newly uncovered connected enemy
  logistics tiles it would add beyond existing friendly ring coverage
- good-enough retirement uses a short exhausted-region cooldown:
  the anchor itself is blacklisted for `12` turns and the current visible local
  cluster is also marked exhausted so the bot does not immediately hop to a
  neighboring harvester in the same drained pocket
- support and orbit behavior respect global move-on:
  before taking a local harassment or orbit action, the bot recomputes the
  anchor assessment and refuses to keep circling a locally exhausted anchor
- assault scouting now tracks chunk recency and exhausted sectors on medium and
  large maps:
  predicted-anchor scouting no longer relies on the old tight five-point local
  sweep alone there, and a drained local enemy pocket can be cooled down at the
  sector level so the same assault bot does not keep snapping back into the
  same three-harvester loop
- post-clear ring behavior is stabilized:
  if a bot clears a ring tile and steps off it, it can hold a short adjacent
  staging state instead of instantly stepping back onto the same ring tile
- that adjacent-wait state is intentionally constrained:
  it expires quickly, is tied to the exact site signature, and is explicitly
  disabled on harvester-adjacent clogging tiles so the bot does not squat next
  to the anchor forever
- progress refresh is stricter on exhausted anchors:
  merely discovering another slightly different low-value site on the same
  pressured anchor is no longer enough to count as meaningful progress
- explored chunk memory is now reused by assault scouting:
  perception records the last round each explored chunk was seen, and scout
  target selection prefers frontier chunks around predicted anchors that are
  either unseen or stale relative to the current round
- small maps keep the old tighter scout sweep:
  the broader frontier-scoring and sector cooldown behavior is intentionally
  gated to medium and large maps so the fork does not throw away fast local
  closes on compact layouts
- replay diagnosis on the medium representative map:
  assault bots can retire a local anchor and then spend dozens of turns logging
  only `mode: ASSAULTING` with no `assault moving toward ...` line, which means
  target generation returned `None` instead of producing a new scout objective
- medium and large maps now keep a persistent scout commitment:
  once an assault bot picks a frontier target, it keeps that target for a short
  TTL instead of recomputing from scratch every turn and potentially idling
- when local predicted-anchor scouting runs dry, assault bots now fall back to
  a global enemy-half chunk frontier:
  this uses chunk recency plus enemy-side bias, so the bot can peel away from a
  saturated local pocket and keep searching for new harvesters such as the
  northern medium-map sites
- direct evidence now outranks coarse sector memory:
  visible enemy harvesters are assessed directly instead of being vetoed by
  sector cooldowns, and recent confirmed harvesters only respect anchor-level
  cooldowns
- sector exhaustion is now only recorded for strong area evidence:
  `CAPTURED_BY_US`, `DRIED_OUT`, and `SATURATED` still cool a sector down, but
  weak retire reasons such as `GOOD_ENOUGH_MOVE_ON`, `local stall`, and
  `support exhausted` no longer blacklist an entire coarse map bucket
- predicted-anchor scouting demotes exhausted sectors to a soft penalty:
  sector history can still break ties against recently drained areas, but it no
  longer removes a predicted harvester from consideration by itself
- global frontier fallback is now staged and sector-agnostic:
  it first looks for unseen or meaningfully stale chunks on the enemy half,
  then unseen or stale chunks anywhere, then enemy-half chunks, then anything
  viable, with the actual score driven by freshness, waypoint recency, forward
  progress, and travel distance rather than sector cooldowns
- local same-harvester ping-pong now has an explicit deconfliction path:
  an assault bot working a harvester drops a short-lived local
  `ASSAULT_CLAIM` marker keyed to that exact harvester, and another assault
  bot that sees the claim will stop treating that harvester as available and
  fall back to another visible/predicted anchor or the existing global
  frontier heuristic
- that coordination is intentionally narrow:
  there are no frontier claims and no generic “nearby friendly builder” score;
  the marker only claims an exact harvester anchor, only matters locally, and
  only refreshes every `4` rounds so the bot does not spam markers every turn
- cached scout-target normalization now preserves its anchor hint:
  if a remembered frontier target has to slide onto a nearby viable staging
  tile, the bot keeps the original anchor association instead of silently
  downgrading that cached scout objective into an anchor-less global target
- assault scouts can now pave roads while traveling to scout objectives:
  the old fork accidentally disabled road building for the assault-specific
  BFS/Bug2 mover, so corridor and home-half breakout attempts could stay
  needlessly slow
- assault movement now paves by default, including harvester-adjacent approach
  tiles:
  if a ring tile gets paved on the way in, site execution explicitly destroys
  the allied road or marker before trying to place the sentinel, which is safe
  because `destroy()` does not cost action cooldown
- validation after the local-claim patch:
  the full representative benchmark vs `jon-5o` at seed `1` is now `8/10`
  wins (`80%`); the remaining losses are one `default_medium1` seat and one
  `wasteland` seat, both by `Resources (tiebreak)` on turn `2000`
- replay-fix follow-up in `a4`:
  `_best_visible_site()` now skips blacklisted and exhausted visible anchors,
  `_is_locally_stalled_for_site()` suppresses false local-stall retires while a
  ring conveyor is still clearable, and `_select_global_enemy_frontier_target()`
  now treats “enemy half” as “closer to the inferred enemy core than to ours”
  instead of the old coarse half-plane test
- scout fallback is also less jittery in `a4`:
  `_cached_scout_target()` keeps a close-but-not-yet-reached scout commitment
  instead of clearing it as soon as the bot enters the near-target radius,
  which was one of the ingredients behind the short-range scout retarget loops

## Assault Targeting Contract

For assault-site selection specifically:

- enemy-core pressure is scored against the visible enemy core center tile only
- visible outer core tiles remain blocked terrain but do not count as combat
  targets
- shell completion is value-driven, not “fill all four sides”
- once most ring sides are already resolved and the remaining unresolved sides
  offer no turret shot or core-center shot, the anchor should retire instead of
  orbiting for cosmetic completion
- `GOOD_ENOUGH_MOVE_ON` is the aggressive global move-on rule:
  the anchor must still be visible, pressure must already be established by a
  ring sentinel or friendly connected line, and any remaining local build must
  be worth at most `1` new logistics tile
- a `GOOD_ENOUGH_MOVE_ON` retirement applies a short `12`-turn exhausted-region
  cooldown so the bot does not immediately reacquire a different harvester in
  the same local enemy cluster
- if a nearby friendly assault bot has already claimed the exact harvester with
  a fresh `ASSAULT_CLAIM` marker, this bot should not keep contesting that same
  harvester locally and should instead peel away into another anchor or scout
  target
- if an assault bot clears a ring tile and steps off it, it now arms a short
  adjacent-wait state so it can hold a safe staging tile instead of stepping
  straight back onto the ring tile on the next turn
- this adjacent-wait state is intentionally narrow: it is only armed after a
  ring-tile sidestep, it expires quickly, and it is never allowed while the bot
  is standing right next to the anchor harvester
- potential issue to watch: the aggressive move-on rule can rotate away too
  early if local visibility misses a still-important follow-up shot, so the
  `<= 1` logistics-gain threshold and `12`-turn cooldown are explicit tuning
  knobs

## Assault Navigation Contract

This README is the implementation guide for assault movement.

### Goal

For assault bots, optimize for:

1. shortest remembered route when one exists
2. deterministic obstacle tracing when the shortest remembered route is blocked
3. fast exit from obstacle-tracing once the direct route becomes good again
4. avoiding the old failure mode of repeatedly recommitting to the same bad A*
   corridor

### Non-goals

- Do not replace economy-mode pathing in this fork.
- Do not add broad frontier reservations or generic nearby-builder heuristics
  here; the only coordination added in this fork is a short-lived local marker
  for exact harvester ownership.
- Do not make assault movement depend on a heuristic open-set ordering.

## Exact Algorithm

### State

Each assault bot keeps a separate assault navigation state:

- `current_target`
- `bfs_path`
- `bugging`
- `bug_target`
- `bug_line_start`
- `bug_mline`
- `bug_hit_distance_sq`
- `bug_side`
- `bug_last_move_dir`
- `bug_steps`
- `bug_seen_states`
- `bug_flipped`

Competitive-programming invariant:

- if `bugging == False`, the next move decision must come from a fresh BFS
- if `bugging == True`, the bot may only leave bug mode after rejoining the
  stored m-line strictly closer to the target than the hit point

### Phase 1: BFS

Run an unweighted `8`-neighbor BFS from the current tile to the target tile on
the remembered grid.

#### BFS passability rules

Treat a tile as blocked if any of these are true:

- out of bounds
- wall or ore
- friendly builder body
- enemy builder body, unless that tile is the exact target and
  `allow_enemy_builder_at_target=True`
- any non-passable building
- remembered hard obstacle
- temporary obstacle from recent live blocking

Target-tile exception:

- if the target tile is the actual assault objective, allow BFS to aim at it
  when it is a clearable enemy conveyor / armoured conveyor tile
- still do **not** allow stepping through a friendly builder on the target tile

#### BFS ordering

Among equal-depth expansions, visit neighbors ordered by:

1. lower Chebyshev distance to the target
2. lower Manhattan distance to the target
3. deterministic compass order

This keeps BFS deterministic without turning it back into a heuristic search.

### Phase 2: Execute BFS Step

If BFS found a route:

1. take the first step
2. if `ct.can_move(step)` succeeds, stay in BFS mode
3. if live execution fails, mark the blocking tile as a temporary obstacle and
   immediately switch to Bug 2

### Phase 3: Enter Bug 2

Bug 2 starts when:

- BFS finds no route, or
- BFS route exists but the first live step is blocked by a body wall or stale
  memory mismatch

On entry, store:

- `bug_line_start = current position`
- `bug_mline = Bresenham(line_start, target)`
- `bug_hit_distance_sq = distance²(current, target)`
- `bug_last_move_dir = blocked heading` or direct heading to target if BFS had
  no route
- `bug_side = left or right`, chosen by whichever first legal wall-follow step
  gets closer to the target

### Phase 4: Bug 2 Wall Following

Bug 2 uses an `8`-direction wall-follow rule.

If following the left wall:

- start scanning from heading rotated `90°` left
- scan clockwise until the first legal move is found

If following the right wall:

- start scanning from heading rotated `90°` right
- scan counterclockwise until the first legal move is found

After each successful bug move:

- update `bug_last_move_dir`
- increment `bug_steps`
- record `(position, heading, side)` in `bug_seen_states`

### Phase 5: Leave Bug 2

Leave bug mode only if:

1. current tile lies on `bug_mline`
2. `distance²(current, target) < bug_hit_distance_sq`
3. a fresh BFS from the current tile to the target now exists

When those are all true:

- clear bug state
- resume BFS immediately

This is the core Bug 2 guarantee: do not leave the obstacle boundary early just
because the bot feels “sort of closer”; leave only when it has truly regained
the original line with provable progress.

### Loop Escape

If Bug 2 repeats the same `(position, heading, side)` state:

- flip the wall-follow side once

If it loops again after flipping, or if:

- `bug_steps > 2 * map_width * map_height`

then:

- drop bug state
- let the caller use its existing emergency fallback

Competitive-programming invariant:

- one side flip is allowed
- repeated looping after the flip means the local obstacle trace is not paying
  off and must be abandoned

## Why This Fork Exists

The old assault A* failure mode was not “pathfinding is impossible”. It was:

- the heuristic repeatedly preferred the same blocked corridor
- local replans were too reactive
- body walls caused recommitment to the same bad lane

BFS fixes the first problem by removing heuristic lane bias.

Bug 2 fixes the second by giving the assault bot a deterministic “walk the
boundary until the straight route is valid again” rule instead of doing another
speculative global heuristic replan.

## Files That Matter

- [builder_bot.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1bfs/builder_bot.py):
  assault navigation state and debug counters
- [navigation.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1bfs/navigation.py):
  assault BFS and Bug 2 implementation
- [mode_assaulting.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1bfs/mode_assaulting.py):
  assault move entry point
- [assault.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1bfs/assault.py):
  anchor selection, site ranking, and harassment logic
- [sentinel_bot.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1bfs/sentinel_bot.py):
  placed sentinel targeting

## Remaining Work

- tune when Bug 2 should give up earlier versus keep tracing
- decide whether target-occupied enemy builders should trigger a special local
  harassment rule instead of plain wait / reapproach
- improve follow-up sentinel-site logic so extra ring tiles get filled only
  when they still add new denial value; incomplete shells are fine once the
  local deletion job is mostly done
- benchmark whether the assault-only BFS + Bug 2 swap materially improves the
  medium / large replay failures that motivated this fork
- watch for adjacent-wait edge cases in crowded assaults: if staging tiles get
  contested by multiple friendlies or the legal-build reason changes from
  cooldown to resource starvation, the short wait may still need a stronger
  abort / retarget rule
