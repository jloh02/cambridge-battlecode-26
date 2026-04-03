# `jon-5` AFIs

AFI here means "Area for Improvement".

This file separates:

- AFIs that are already implicit in `jon-5` or its README
- AFIs found from the current code review

The point is not to rewrite `jon-5` immediately. The point is to make the
current weakness list explicit so future work can be targeted.

## Communication And Deconfliction

### Already present in the bot / README

- reduce duplicate work using markers
- reduce conveyor congestion by limiting how many builders tag onto the same
  conveyor

### Additional AFIs from review

- marker-sharing intent exists, but marker placement is currently stubbed out in
  `utils.place_marker_around()`, so several coordination ideas never actually
  reach other bots
- ore deconfliction is still mostly local and proximity-based; it does not yet
  have a durable claim lifecycle
- exploration deconfliction is lightweight and purely local; it is good enough
  to spread builders a bit, but not good enough to coordinate whole sectors
- connected-conveyor hints exist, but the protocol is still ad hoc and brittle
  compared with a versioned typed marker schema

## Economy And Logistics

### Already present in the bot / README

- axionite collection
- reduce conveyor congestion near the core
- consider a splitter near the core when lanes get crowded
- surveyor / repair mode for idle builders

### Additional AFIs from review

- `jon-5` is still effectively titanium-only; it does not yet have a true
  foundry-plus-convert plan
- the core's builder spawning policy is intentionally simple, but it is still a
  coarse heuristic rather than a lane-aware economic policy
- tiling-back is strong at building a route, but weak at auditing whether an
  existing route should be repaired, widened, or replaced
- bridge use is tactical rather than policy-driven; there is no explicit notion
  of when bridge spend is economically worth the scaling cost
- route quality is still judged more by immediate geometry than by downstream
  delivery congestion

## Defense And Combat

### Already present in the bot / README

- build defense around harvesters
- heal core to defend rush strategies
- use barriers to cover ores

### Additional AFIs from review

- the bot has no convincing defensive posture once the opponent contests a lane
- healing exists in the game but is not yet integrated into a deliberate
  defensive routine
- logistics-critical tiles and harvesters are not explicitly prioritized for
  protection
- the bot can clear obstacles, but it does not yet have a real combat or
  anti-rush doctrine

## Pathing And Exploration Robustness

### Already present in the bot / README

- compare turn timing across maps
- tune mode budgets by map size and congestion
- improve obstacle epoching for smarter cache reuse

### Additional AFIs from review

- pathfinding is bounded and pragmatic, which is good, but the budgets are still
  static heuristics rather than map- or phase-aware policies
- exploration chunking is coarse and can still send builders into low-value fog
  without strong economic justification
- the bot remembers a lot of local geometry, but the memory model is not yet
  explicitly structured around stale-information handling
- congestion recovery still relies on short-lived temporary obstacles rather
  than a more deliberate lane arbitration policy

## Architecture And Testability

### Already present in the bot / README

- add benchmark coverage for timing behavior
- add regression checks alongside timeout checks

### Additional AFIs from review

- `jon-5` mixes controller mutation directly into the same mode logic that makes
  strategic decisions, which makes targeted testing harder than it needs to be
- the remembered grid is powerful, but it is still a dict-of-dicts rather than
  a typed state layer with explicit invariants
- marker encoding, sensing, pathing, and execution are all effective enough to
  compete, but they are tightly coupled and hard to reuse cleanly
- future work should preserve the current strong tiling-back behavior while
  extracting cleaner primitives around it, rather than replacing it wholesale
