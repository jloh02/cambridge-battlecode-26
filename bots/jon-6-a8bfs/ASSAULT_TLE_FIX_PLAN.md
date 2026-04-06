# Assault TLE and Target Stability Plan

This plan targets the late assault failures seen against `leeroy-jonkins` on
`butterfly`, `dna`, and `chemistry_class`: near-harvester TLEs, bottom-fringe
scout stalls, target flips back toward base, and wall/corridor navigation churn.

## 1. One-pass visible anchor resolution

Visible harvesters should resolve once per turn into both an anchor status and a
best assault site. The old path assessed a visible anchor by ranking its ring
sites, then ranked the same anchor again to select a site. The replacement is a
single `resolve_visible_anchor` pass that:

- enumerates ring tiles once,
- enumerates sentinel directions once,
- derives `AnchorAssessment` and `best_site` from the same ranked site list,
- returns an explicit `NO_ACTIONABLE_SITE`-style result when no visible plan is
  executable.

This is the main fix for near-harvester TLEs caused by repeated target-summary
enemy scans.

## 2. Progress-based anchor commitment

Anchor leases should be based on progress, not only `last_seen`. A bot that is
still getting closer to a committed site or has recently acted on a site should
not abandon its anchor just because the harvester has been unseen for a short
TTL. The lease should track:

- current anchor key,
- last seen round,
- last progress round,
- best distance to the anchor/ring target.

Hard invalidations still clear immediately: visible empty anchor tile, blacklist,
captured/dried/good-enough assessment, or excessive stall with no progress.

## 3. Stable scout targets

Scout targets should be locks, not soft suggestions. A scout lock should track:

- target tile,
- target chunk,
- optional anchor key,
- target kind (`confirmed_anchor`, `predicted_anchor`, or `frontier_chunk`),
- best distance reached,
- last progress round,
- stall count.

Predicted-anchor epoch rotation should not override an active lock. Frontier
chunks that stall should be marked exhausted temporarily so the bot does not keep
reselecting the same bottom fringe.

## 4. Cheaper assault perception

Assault mode should keep local visible state fresh every turn, but full-grid
harvester tracking should be heartbeat-limited. Visible harvesters are still
updated immediately from the local scan; the expensive remembered-grid harvester
sweep runs only on a cadence or when non-assault modes need it.

This preserves tactical correctness near visible harvesters while reducing the
background cost that compounds when assault bots are already stuck near walls or
large logistics clusters.

## 5. Wall-aware assault navigation

Assault BFS should not use a direction order computed only from the start tile.
Near walls and corridors, the preferred direction must be recomputed from each
expanded node. Dynamic connected-harvester checks should also be memoized per
turn so clusters do not get retraced repeatedly while deciding whether friendly
builders are meaningful obstacles.

## Implementation Order

1. Add the plan file and status notes.
2. Implement one-pass visible anchor resolution.
3. Add progress leases and scout locks.
4. Cadence-limit assault harvester tracking.
5. Make assault BFS direction ordering per-node and memoize connected-harvester checks.
6. Add focused regressions where practical.
7. Run unit tests and direct profiled repros for `butterfly` and `chemistry_class`.

## Implementation Status

- Done: one-pass `resolve_visible_anchor` now returns both assessment and ranked
  sites for visible harvester planning.
- Done: assault anchor progress state keeps unseen anchors alive while progress
  is still being made toward the anchor or committed ring.
- Done: scout targets now store kind, best distance, last progress, and stall
  state; predicted scout anchors no longer rotate by epoch.
- Done: assault-mode harvester tracking is cadence-limited while visible
  harvesters still update immediately from local vision.
- Done: assault BFS recomputes direction ordering per expanded node and caches
  connected-harvester dynamic-obstacle checks per turn.
- Residual risk: `chemistry_class` still has assault turns over `2 ms`; the
  remaining hotspot appears to be large-cluster scout/planner churn and
  occasional perception-inference outliers, not the original assess-plus-rerank
  duplication alone.
