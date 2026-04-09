# got-any-grapes

This file records the live behavior of `got-any-grapes` as it exists in this directory.

## Current Doctrine

- The bot is titanium-first in live play.
- Mixed-ore collection is not active.
- Diagonal spawn-slot builders are treated as assault-role builders from initialization.
- Non-assault builders cycle among:
  - `FINDING_ORE`
  - `TILING_BACK`
  - `EXPLORING`
  - `HIJACKING`
- Opportunistic hijack remains live and can preempt economy builders when a visible enemy harvester outlet is worth contesting.
- There is no live rush mode in the builder state machine.

## Core Behavior

- The core opens with a forced assault wave on rounds `5` and `6`.
- The core can also spawn additional assault builders up to the current quota when the titanium threshold is met.
- That bonus assault rule is still titanium-threshold-driven in live code and has not yet been tied to a stronger opening validation rule.
- Outside assault spawns, the core continues economy spawning around the core footprint with mild ore-biased direction choice when ore markers are available.

## Economy Behavior

- Economy builders target titanium ore only.
- When a builder reaches ore access, it builds the harvester if possible.
- If the harvester is already connected, the bot marks it claimed and keeps looking for the next job.
- If the harvester is not connected, the builder switches into `TILING_BACK` and builds a route toward the best current return target.
- `TILING_BACK` prefers a connected friendly conveyor when that beats a direct core return, otherwise it routes back to the core.
- Exploration remains the fallback when no eligible titanium target is available.

## Navigation

- Routing remains pure A* for macro movement.
- The live substrate keeps resumable anytime A* state for repeated replans instead of cloning planner state every turn.
- Planner reuse now keys on obstacle identity, not just obstacle counts.
- Anytime best-candidate ranking no longer reconstructs full parent paths in the hot loop.
- Shared no-progress recovery is live for economy movement modes:
  - `FINDING_ORE`
  - `EXPLORING`
  - `TILING_BACK`
- That shared recovery now feeds ore-target and exploration-target abandonment instead of letting ping-pong movement count as progress forever.
- The bot does not use a greedy routing fallback.

## Assault Behavior

- Assault-role builders use the assault module from spawn rather than an older dedicated rush path.
- Assault perception still uses the fast/heartbeat refresh split.
- Assault closeouts remain opportunistic rather than consistently decisive; many wins are still titanium tiebreak wins.

## Known Limits

- The bot is still below the local smoke gate for the studied opponent trio.
- The main remaining floor failures are still low-throughput collapse games with long builder loop streaks on some bad maps.
- The current live offense can still overcommit because bonus assault spawning is not yet conditioned on a stronger real-opening check.
