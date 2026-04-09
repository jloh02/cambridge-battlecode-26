# CODEX Scratchpad

## Active Strategy Name

Floor-fix iteration: adaptive offense, stall recovery, marker/spawn fixes.

## Task Description

Improve `got-any-grapes` from low-floor tiebreak-heavy state into a stable
promotion candidate.

## Criteria

Per `CODEX_INSTRUCTIONS.md` — 80% per-opponent gate over g16/g64.

## Honest Current State (2026-04-09)

### Latest g16 with unit count + claimed harvester recheck (pre-P0 fix)
- vs jon-6: 68.8%
- vs a9bfs-surround: 50.0%
- vs leeroy-jonkins: 75.0%

### Bug Fixes Applied This Cycle
- **P0 FIXED**: `place_marker_around()` was disabled (body commented out, always returned False). All ore/conveyor/orientation markers were dead. Fixed by uncommenting.
- **P1 FIXED (congestion)**: Economy spawning now tries all directions instead of picking one and giving up.
- **P1 (ore marker architecture)**: Ore markers are placed near the ore site, but the core only reads nearby entities. Remote ore discoveries never reach the core's spawn logic. **Noted for medium-term.** The spawn-toward-ore mechanism is architecturally limited.
- **P1 (grid pruning disabled / TLE)**: Grid pruning is disabled because it broke conveyor topology refresh. Connected-lane refresh walks all grid entries, growing unboundedly. **Noted for medium-term.**
- **P2 (BFS cap)**: 50-node BFS cap on ore search causes Euclidean fallback on sparse maps. Known weakness, starry_night pattern. **Noted for medium-term.**

### g16 running with P0+P1+spawn interval changes

## Medium-Term Plans

### Architecture Fixes
1. **Ore marker → core routing**: Need either (a) builders place ore markers near the core instead of near ore, or (b) a dedicated core-visible marker placement strategy
2. **Grid pruning**: Re-enable with conveyor-safe exemption. Caps late-game grid growth.
3. **Ore BFS expansion**: Increase cap from 50 to 100+ on large maps, with timing budget guard

### Strategic Improvements
4. **Defensive sentinels**: Build sentinels near harvester clusters for protection against surround-style opponents
5. **Route resilience**: Detect and rebuild broken conveyor routes proactively
6. **Connected harvester markers**: Enable cross-builder deconfliction (currently disabled due to permanent claimed_harvesters issue — needs TTL)

## All Landed Changes

1. Assault economy fallback (60 turns)
2. Economy-health gated bonus assault
3. TILING_BACK ping-pong detection
4. Escalating blacklist TTL (60 → 180 → 500)
5. Exploration exhaustion reset (60 turns)
6. Economy stall reset (150 turns)
7. Assault progress tracking (scout doesn't count)
8. Harvester place tracking
9. Unit count fix (live `get_unit_count()`)
10. More aggressive spawning (interval 8, threshold 200)
11. MAX_BUILDER_COUNT raised to 12
12. Enemy sentinel danger zones
13. Claimed harvester recheck (20 turns)
14. **P0: `place_marker_around()` re-enabled**
15. **P1: Economy spawn tries all directions**
16. Perception order swap + TILING_BACK health query skip

## Compaction-Safe Resume Point

All changes landed and tested. 40 tests pass. g16 in progress.
