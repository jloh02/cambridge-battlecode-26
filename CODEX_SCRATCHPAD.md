# CODEX Scratchpad

## Active Strategy Name

Floor-fix + anti-clumping + perception optimization.

## Current State (2026-04-10)

### Latest g16 (mixed code, includes some pre-fix games)
- **Overall: 70.8%**
- vs jon-6: 75.0%
- vs a9bfs-surround: 75.0% (best ever, was 37.5% g64 baseline)
- vs leeroy-jonkins: 62.5%
- avg TiEq: 33310.8 (highest ever)
- TLE turns: 0

### Clean g16 in progress.

## GPT Congestion Claims Assessment

### Fixed
- **P0 TILING_BACK bypass**: TILING_BACK had NO friendly-blocker handling.
  `can_move()` failure was silently ignored. Now adds temp obstacle (TTL 8).
  **Committed.**
- **P1 Yield rule incomplete**: Already fixed earlier — simplified to always
  mark friendly blockers (TTL 8).

### Correct but not worth fixing now
- **P0 Passable builders**: Correct observation but intentional design. Making
  builders non-passable would break A* pathfinding in corridors with any traffic.
  The real fix is collision handling at execution time (which we're doing).
- **P1 Lane convergence**: Load penalty already discourages convergence. Making it
  stronger risks under-utilizing good routes. Monitor but don't change.
- **P1 Build before move**: Intentional — building a conveyor under yourself + moving
  in one turn is the efficient pattern. The pending-build stall (6 turns) already
  handles the freeze case.

### Not worth pursuing
- **P1 Intent-based deconfliction**: Would require reservation semantics via markers.
  But markers are disabled (P0 self-poisoning). This is a marker-system redesign
  blocker, not a quick fix.
- **P2 Healing clumps**: Very minor. Healing is conditional on damaged buildings
  being visible and doesn't fire often.
- **P2 Hijack contention**: Also minor. Hijack is opportunistic and rare.
- **Sidestep on block**: Tested and reverted — caused regression (27K from 32K Ti).
  Moving perpendicular invalidates the A* path and costs a replan turn.

## All Committed Changes (10 commits)

### Economy + offense
1. Assault economy fallback (60 turns)
2. Economy-health gated bonus assault (round >= 80)
3. Assault progress tracking (scout doesn't count)
4. Unit count fix (live `get_unit_count()`)
5. MAX_BUILDER_COUNT 12
6. Spawn interval 12, threshold 200
7. Economy spawn tries all directions

### Stall recovery
8. TILING_BACK ping-pong detection
9. Escalating blacklist TTL (60 → 180 → 500)
10. Exploration exhaustion reset (60 turns)
11. Economy stall reset (150 turns)
12. Claimed harvester recheck (20 turns)

### Anti-clumping
13. Shared progress stall TTL 6→12
14. Friendly blocker always marked (TTL 8)
15. **TILING_BACK friendly-blocker handling** (new)

### Perception + runtime
16. Enemy sentinel danger zones
17. Dead marker scan removal
18. Inlined cardinal deltas + cached conveyor set
19. Topology heartbeat 20→30 turns
20. Adaptive BFS ore search (map-size scaled)
21. Perception order swap + TILING_BACK health skip

## Compaction-Safe Resume Point

10 commits on `got-any-grapes` branch. 40 tests passing.
g16 best: 70.8% overall. g64 baseline: 62.5%.
Clean g16 running to validate latest committed state.
