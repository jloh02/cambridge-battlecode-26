# got-any-grapes

`got-any-grapes` is the live source bot in this directory.

The detailed behavior reference is in `EXPLAINER.md`. The short version:

- no active rush mode
- titanium-first economy
- diagonal spawn-slot builders open in assault mode, transition to economy after 60 turns without targets
- non-assault builders prioritize ore, tile-back logistics, exploration, and opportunistic hijacks
- routing stays pure A* with resumable planner state and shared no-progress recovery
- bonus assault spawning gated on round progression (>= round 80)
- adaptive BFS ore search scales with map size (50/80/120 nodes)

## Session Changes (2026-04-09 → 2026-04-10)

### Added
- Assault economy fallback: yields to economy after 60 turns idle
- Bonus assault gated on economy establishment (round >= 80)
- TILING_BACK ping-pong detection + escalating blacklist
- Exploration exhaustion reset + economy stall reset
- Unit count fix: live `get_unit_count()` for spawn cap
- MAX_BUILDER_COUNT raised to 12
- Economy spawn tries all directions (P1 congestion fix)
- Claimed harvester recheck for broken routes
- Enemy sentinel danger zones for economy builders
- Adaptive BFS ore search (map-size scaled)

### Known Issues
- Marker system disabled (self-poisons logistics, needs redesign)
- Remote TLE pressure in late-game
- Grid pruning disabled (conveyor topology dependency)

This file is intentionally brief so it does not drift separately from the bot explainer.
