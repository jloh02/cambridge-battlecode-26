# jon-5o-a1bfs

`jon-5o-a1bfs` is the `jon-5o-a1` assault bot with one deliberate routing
change:

- economy modes keep the old `jon-5o` navigation stack
- assault bots do **not** use the generic A* stack
- assault bots use **BFS first**, then **Bug 2** as the fallback when the BFS
  route is blocked or temporarily disappears

The point of this fork is narrow and explicit: remove assault-mode dependence on
the old heuristic pathing, which was repeatedly preferring the same bad lane or
stalling against body walls.

## Current Strategy

Macro and assault policy are the same as `jon-5o-a1`:

- normal `jon-5o` economy opening for the first `4` builders
- first `2` diagonal builders are permanent assault bots and are now forced as
  the turn `5` and turn `6` spawns in the standard opening
- `3rd` assault bot unlocks at `90` titanium
- visible or recently confirmed harvesters are hard-committed locally
- anchors are retired once they are `CAPTURED_BY_US`, `DRIED_OUT`, or
  `SATURATED`
- placed sentinels have a local controller and avoid mixed-tile friendly fire

The main fork-specific difference is the assault movement layer.

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
- Do not add hidden coordination or multi-bot reservations here.
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
- improve cluster-completion logic so good follow-up sentinel sites get filled
  more aggressively after the first successful breach
- benchmark whether the assault-only BFS + Bug 2 swap materially improves the
  medium / large replay failures that motivated this fork
