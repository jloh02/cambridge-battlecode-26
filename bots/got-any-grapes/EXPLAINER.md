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
- If the harvester is already connected, the bot marks it claimed and keeps looking.
- If the harvester is not connected, the builder switches into `TILING_BACK` and builds a route toward the best current return target.
- `TILING_BACK` prefers a connected friendly conveyor when that beats a direct core return, otherwise it routes back to the core.
- Exploration remains the fallback when no eligible titanium target is available.

## Navigation

- Routing remains pure A* for macro movement.
- The live substrate keeps resumable anytime A* state for repeated replans instead of cloning planner state every turn.
- Planner reuse now keys on obstacle identity, not just obstacle counts.
- Anytime best-candidate ranking no longer reconstructs full parent paths in the hot loop.
- Both `calculate_astar_path` and `_resume_anytime_astar` use a closed set to prevent re-expanding nodes and reduce heap bloat.
- A* hot loops have inlined walkability checks, step costs, heuristics, and line-deviation scoring to eliminate function call overhead.
- Obstacle sets are merged upfront (one set lookup per neighbor instead of two).
- Shared no-progress recovery is live for economy movement modes:
  - `FINDING_ORE`
  - `EXPLORING`
  - `TILING_BACK`
- That shared recovery now feeds ore-target and exploration-target abandonment instead of letting ping-pong movement count as progress forever.
- The bot does not use a greedy routing fallback.

## Stall Recovery

Two stall-recovery mechanisms cover `TILING_BACK` gaps not addressed by the shared progress system:

1. **Pending-build stall recovery**: When `_execute_pending_build` fails for `PENDING_BUILD_STALL_LIMIT` (6) consecutive turns, the pending build is abandoned, the blocked position becomes a temporary obstacle, and navigation resumes.

2. **Navigation stall recovery**: When the builder's position doesn't change for `NAV_STALL_LIMIT` (40) turns in `TILING_BACK`, the mode is abandoned. For HARVESTER-origin tiling, the harvester position is blacklisted in `ore_target_blacklist` for 30 turns to prevent cycling.

## Exploration

- Explorer ally deconfliction is live: builders skip exploration chunks where a nearby ally is closer.
- Unreachable chunks are blacklisted after repeated stalls.

## Assault Behavior

- Assault-role builders use the assault module from spawn rather than an older dedicated rush path.
- Assault perception still uses the fast/heartbeat refresh split.
- Assault closeouts remain opportunistic rather than consistently decisive; many wins are still titanium tiebreak wins.

## Known Limits

- Remote TLE pressure is still significant in late-game (high unit counts increase per-turn overhead).
- The bonus assault quota is purely titanium-threshold-driven with no economy health check.
- Delivered refined axionite remains 0 — no foundry-convert pipeline exists.
