# got-any-grapes

`got-any-grapes` is the live source bot in this directory.

The detailed behavior reference is in `EXPLAINER.md`. The short version:

- no active rush mode
- titanium-first economy
- diagonal spawn-slot builders open in assault mode, transition to economy after 60 turns without targets
- non-assault builders prioritize ore, tile-back logistics, exploration, and opportunistic hijacks
- routing stays pure A* with resumable planner state and shared no-progress recovery
- bonus assault spawning gated on economy health (requires connected conveyor marker)

## Session Changes (2026-04-09)

### Added
- Assault economy fallback: assault builders yield to economy after 60 turns without offensive engagement
- Economy-health gated bonus assault: core requires connected economy marker before spawning bonus assault
- TILING_BACK ping-pong detection: catches builders oscillating between ≤2 positions
- Escalating blacklist TTL for repeated tiling-back failures (60 → 180 → 500 turns)
- Exploration exhaustion reset: unreachable chunk blacklist clears every 60 turns
- Economy stall reset: all blacklists/fail counts clear every 150 turns when no harvester placed
- Assault progress tracking: scouting doesn't count as offensive progress

### Known Issues
- Remote TLE pressure in late-game remains significant
- starry_night-class maps with scattered ore remain structurally weak
- Delivered refined axionite remains 0 (no foundry-convert pipeline)

This file is intentionally brief so it does not drift separately from the bot explainer.
