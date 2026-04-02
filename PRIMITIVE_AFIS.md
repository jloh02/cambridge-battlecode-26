# Primitive AFIs From `cambattle`

This file records what `jon-5` should eventually learn from the `cambattle`
primitives.

These are primitive-level AFIs, not instructions to rewrite `jon-5`
immediately. The right direction is incremental borrowing of cleaner building
blocks while preserving the good tactical behavior `jon-5` already has.

## 1. Separate Sensing From Decision And Execution

`cambattle` has a cleaner boundary:

- `sense.py` builds a typed turn snapshot
- solution code decides on a plan
- `executor.py` is the only layer that mutates the controller

Lesson for future bot lines:

- strategy code should spend less time mixing "what should I do?" with "which
  controller call can legally do it right now?"
- this separation makes local reasoning and unit testing much easier

## 2. Use Typed, Versioned Marker Schemas

`cambattle.markers` defines:

- explicit marker kinds
- a schema version
- helper encoders / decoders
- freshness helpers

Lesson for `jon-5`:

- marker traffic should not rely on loose ad hoc payload conventions forever
- a typed schema makes it much easier to evolve claims, route hints, and
  congestion signals without silent decode failures

## 3. Reuse Logistics And Bridge Primitives

`cambattle.logistics` already isolates useful logistics questions:

- what a route tile currently means
- whether a pipeline actually reaches the core
- whether a bridge target is legal
- how to choose a bridge target without open-coded geometry everywhere

Lesson for `jon-5`:

- keep the strong tiling-back behavior, but stop re-encoding every logistics
  legality rule inside the main mode code
- route tracing and bridge legality are good candidates for shared primitives

## 4. Prefer Typed Turn Data Over Raw Dict Bundles

`cambattle.sense` and `cambattle.decision` use dataclasses such as:

- `TurnContext`
- `TileInfo`
- `EntityInfo`
- `TurnPlan`

Lesson for future work:

- typed turn data makes invariants more visible
- plans become auditable data instead of implicit side effects
- replay-oriented debugging gets simpler when the planner contract is small and
  explicit

## 5. Keep Navigation Helpers Reusable

`cambattle.nav` is simpler than `jon-5`'s navigation, but it demonstrates the
right primitive boundary:

- small path and geometry helpers
- visible-goal planning
- reusable distance and adjacency utilities

Lesson for `jon-5`:

- the advanced tactical logic can stay where it is for now
- but low-level geometry, route-scoring, and planner support code should
  gradually move toward reusable helpers rather than staying fused into one bot

## 6. Suggested Adoption Order

The most sensible order to borrow from `cambattle` is:

1. marker schema discipline
2. bridge / logistics legality helpers
3. typed sensing snapshots
4. planner / executor separation where it improves testability

That order keeps the current behavior intact while reducing the amount of
hard-to-audit controller-coupled code over time.
