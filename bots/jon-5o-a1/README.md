# jon-5o-a1

`jon-5o-a1` is a `jon-5o` fork that keeps the same economy backbone and adds a
permanent builder-based harvester assault package.

It is not promotion ready. The current representative benchmark is still below
target. On 2026-04-03, the latest debug-on representative run against `jon-5o`
finished at `11/20` wins (`55%`).

## Current Macro Policy

- Keep the normal `jon-5o` economy opening for the first `4` builders.
- After that floor, the first `2` diagonal-spawn builders are permanent assault
  bots.
- Unlock the `3rd` assault bot at `90` titanium.
- `MIN_CONNECTED_LANES_FOR_BONUS_ASSAULT` still exists in code only as a
  potentially unused future-tuning constant.

## What Changed Relative To `jon-5o`

- Added a permanent `ASSAULTING` builder role.
- Added slot-dispersed enemy-side scouting before first contact.
- Added committed visible-harvester execution once a live or recently confirmed
  enemy harvester exists.
- Added local ring-site selection for sentinel placement around enemy
  harvesters.
- Added explicit anchor retirement with blacklist states so captured / dried /
  saturated harvesters get dropped instead of being reacquired immediately.
- Added marginal-value site scoring so follow-up ring sites can beat duplicate-
  value ones.
- Added a local `SentinelBot` controller so placed sentinels actually fire.
- Fixed sentinel friendly fire on mixed tiles by refusing shots at enemy
  building positions currently occupied by a friendly builder.
- Representative benchmark runs now save timestamped JSON/replay artifacts and
  enable debug stdout/indicator lines by default.

## Assault Behavior Right Now

Assault builders currently do this:

1. scout toward slot-dispersed enemy-side anchors when there is no visible
   harvester
2. hard-commit to a visible or recently confirmed harvester anchor
3. assess whether that anchor is still `live`, `captured`, `dried`, or
   `saturated`
4. score ring sites by marginal new denial value, not just raw single-site
   quality
5. move to the ring site, clear it only if that unlocks the chosen build, and
   place a sentinel if legal
6. blacklist the anchor and move on once the local denial job is done

The current implementation is intentionally biased toward "find one anchor and
get one useful sentinel down, then avoid wasting turns on already-dead
anchors." It still does not have a full multi-anchor / wide-route assault plan.

## Sentinel Behavior Right Now

Placed sentinels are controlled locally in
[sentinel_bot.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/sentinel_bot.py).

Current fire priority is:

1. enemy turrets
2. connected enemy logistics near the adjacent anchor harvester while the line
   is still live
3. enemy core once the local line is basically dead
4. any other legal visible enemy

The adjacent anchor harvester itself is intentionally skipped so the sentinel
focuses on drying the line behind it.

The sentinel also refuses to fire at an enemy building tile if one of our
builders is standing on that same tile, because turret shots on mixed
builder/building occupancy hit the builder only.

Important caveat: this is still local visible-state logic. If the sentinel sees
a real live logistics tail, it will still clear that before pivoting to the
core.

## What Is Working

- Assault bots now spawn reliably instead of waiting for connected-lane reports.
- Assault bots do find enemy harvesters on some maps.
- Assault bots do place sentinels in some successful positions.
- Sentinels now fire instead of idling forever.
- Assault bots now retire captured / dried / saturated anchors instead of
  sticking to them forever.
- Representative benchmark replays once again contain debug stdout and green
  path lines.

## Known Failure Modes

### 1. The Bot Still Thinks In Terms Of Marginal Local Sites, Not Full Cluster Planning

The current ring-site code is now better at avoiding duplicate-value sites, but
it is still weak at:

- filling multiple back-side sentinel sites around the same local cluster,
- recognizing "three more good denial sites exist here",
- or switching from one local cluster to a globally better second cluster.

So a replay can show obvious follow-up placements that a human would take, but
the bot can still under-complete the pocket.

### 2. Support Mode Can Still Degrade Into Orbiting

The anchor blacklist removed the worst infinite re-acquire loop, but crowded
local pockets can still produce:

- oscillation,
- repeated pathing toward the same blocked point,
- or wandering near the anchor instead of retiring it and moving on.

### 3. Friendly-Congestion Handling Is Still Too Local

The current congestion fix only adds temporary obstacles after the next step is
blocked. That helps, but it is still reactive and very local.

Observed remaining problem:

- the bot can keep recomputing toward the same corridor or the same top-side
  tile,
- bounce around friendly builders,
- or fail to take a wider alternate route even when one exists.

This is the big A* / local-replan issue seen in the replays where a bot wants
to go around a body wall and simply does not commit to the wider path.

### 4. Enemy-Body Avoidance Is Still Incomplete

Assault bots now replan around some immediate enemy-builder blocks, but the
global path model still behaves as if builder bodies are broadly passable.

That means the bot can still:

- aim for routes that are only theoretically open,
- keep choosing lanes clogged by enemy builders,
- and fail to route around enemy body clusters early enough.

### 5. Clear-Vs-Build Logic Is Still Too Primitive

Right now the assault builder only has a local clear-to-unlock rule. It still
does not have a richer cluster-wide policy that says:

- prefer placing a useful sentinel over manually firing something,
- clear only when it directly unlocks a better sentinel site,
- and otherwise move on when the local denial job is already done.

That is why some replay positions feel obviously solvable by a human but still
lead to indecision.

## Concrete Replay Interpretations

These are the current best explanations for the patterns seen in recent replays:

- "Why did it not place 3 more sentinels behind the harvesters?"
  Because the current site selector is still local and greedy. It now avoids
  duplicate-value follow-ups, but it still does not run a full cluster-
  completion planner.
- "Why does the sentinel not shoot the core?"
  The sentinel code does shoot the core, and it now promotes the core once the
  local line is mostly dead. If it still ignores the core, the bot still thinks
  there is a real live logistics tail worth clearing first.
- "Why does it keep circling a harvester that is already ours in practice?"
  This should be reduced now because captured / dried / saturated anchors are
  retired and blacklisted. If it still happens, the bug is now in local stall
  detection or congestion handling, not in total lack of retirement logic.
- "Why does it keep pathing back to the same place?"
  Because support/orbit fallback and local congestion handling can both keep the
  bot attached to the same anchor and the same blocked lane.

## Files That Matter

- [core_bot.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/core_bot.py):
  assault spawn quota and macro policy
- [mode_assaulting.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/mode_assaulting.py):
  anchor commitment, ring execution, support fallback
- [assault.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/assault.py):
  site scoring, target selection, cluster logic
- [navigation.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/navigation.py):
  A*, replanning, temporary obstacles
- [sentinel_bot.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/bots/jon-5o-a1/sentinel_bot.py):
  placed sentinel targeting

## TODO

### Highest Priority

- [ ] Tune the new anchor-retirement thresholds so live anchors are not dropped
      too early and dead anchors are not kept too long.
- [ ] Tighten local stall detection so near-anchor orbit loops collapse faster.
- [ ] Add cluster-saturation logic so builders can fill multiple good sentinel
      sites around one local harvester pocket.
- [ ] Prefer building a useful sentinel over manual self-clear when both are
      available.
- [ ] Add explicit clear-vs-build policy: clear only when it unlocks a better
      sentinel or immediate high-value denial.

### Pathing / Congestion

- [ ] Fix the A* / local-replan failure where assault bots keep targeting the
      same blocked top-side tile instead of taking the wider route around
      enemy/friendly body walls.
- [ ] Stop repeated re-pathing into the same congested corridor after a failed
      move.
- [ ] Add stronger congestion memory so friendly-builder clumps do not cause
      long orbit loops.
- [ ] Treat enemy body walls as route-quality penalties earlier, not only after
      the next step fails.

### Targeting / Site Value

- [ ] Revisit sentinel targeting so exposed enemy core shots can outrank dead-
      line conveyor cleanup in some positions.
- [ ] Define when a local harvester cluster is "finished enough" to move on
      versus when it is still worth filling out more ring sites.
- [ ] Score follow-up sentinel placements around an already-pressured harvester
      cluster instead of always re-deriving one best single site.

### Bench / Debug

- [ ] Keep representative benchmark debug-on by default.
- [ ] Add replay checks for "circling without new value" so these failures are
      caught automatically instead of only by visual inspection.
