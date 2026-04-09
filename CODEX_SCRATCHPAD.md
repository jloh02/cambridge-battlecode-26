# CODEX Scratchpad

## Active Strategy Name

Floor-fix iteration: adaptive offense, stall recovery, builder replacement.

## Task Description

Improve `got-any-grapes` from low-floor tiebreak-heavy state into a stable
promotion candidate by fixing main floor failures first.

## Criteria

Per `CODEX_INSTRUCTIONS.md` — 80% per-opponent gate over g16/g64.

## Honest Current State (2026-04-09)

### Latest g16 results (with all changes including unit count fix)

- **vs jon-6: 68.8%** (11-5) — approaching 80%
- **vs jon-6-a9bfs-surround: 50.0%** (8-8) — improved from 37.5% g64
- **vs leeroy-jonkins: 56.2%** (9-7)
- **worst TiEq: 100** — NO MORE COMPLETE COLLAPSES (was 0 at baseline)
- **avg TiEq: 31868.5** — highest yet (was 30186 at baseline)
- TLE turns: 0

### Key Finding: Unit Count Fix

The core used `builder_counter` (only incremented, never decremented) instead of
`ct.get_unit_count()` (live count). When builders died in combat, the core
thought it had max builders and stopped spawning. The fix allows replacement
spawning when builders die, dramatically improving resilience against the
surround opponent.

## All Landed Changes

1. Assault economy fallback (60 turns)
2. Economy-health gated bonus assault (connected conveyor marker required)
3. TILING_BACK ping-pong detection
4. Escalating blacklist TTL (60 → 180 → 500)
5. Exploration exhaustion reset (60 turns)
6. Economy stall reset (150 turns — clears blacklists + fail counts)
7. Assault progress tracking (scout doesn't count)
8. Harvester place tracking
9. **Unit count fix: use live `get_unit_count()` instead of historical spawn counter**
10. **Danger zone: economy builders treat tiles near enemy sentinels/gunners as temp obstacles**
11. Perception order swap + TILING_BACK health query skip

## Compaction-Safe Resume Point

All changes landed. 40 tests passing. Latest g16: 58.3% overall with no floor collapses.

Next: continue improving vs surround and leeroy-jonkins matchups.
