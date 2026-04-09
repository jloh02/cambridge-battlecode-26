# CODEX Scratchpad

## Active Strategy Name

Floor-fix iteration: adaptive offense, stall recovery, spawning fixes.

## Task Description

Improve `got-any-grapes` from low-floor tiebreak-heavy state into a stable
promotion candidate.

## Criteria

Per `CODEX_INSTRUCTIONS.md` — 80% per-opponent gate over g16/g64.

## Current State (2026-04-10)

### Latest g16 (clean committed code)
- **Overall: 68.8%**
- vs jon-6: 68.8%
- vs a9bfs-surround: 62.5%
- vs leeroy-jonkins: 75.0%
- TLE turns: 0, worst TiEq: 0

### Progress from baseline
| Opponent | Baseline | Current | Delta |
|----------|----------|---------|-------|
| jon-6 | 56.2% | 68.8% | +12.6 |
| a9bfs-surround | 43.8% | 62.5% | +18.7 |
| leeroy-jonkins | 56.2% | 75.0% | +18.8 |

## Validated Bug Assessment (GPT findings)

### Fixed
- P1 economy spawn congestion: now tries all directions (committed)

### Confirmed but deliberately kept disabled
- P0 marker self-poisoning: `place_marker_around` places markers on tiles
  needed for conveyor construction. Re-enabling caused 41.7% regression.
  Needs tile-avoidance redesign before enabling.

### Confirmed for medium-term
- P1 ore-marker → core architecture broken (moot while markers disabled)
- P1 late-game perception scaling (grid never pruned, topology refresh O(n))
- P1 explore-claim dead code (parsed but never consumed)
- P2 dead marker surface (CONNECTED_HARVESTER disabled, ASSAULT_SPAWN unused)

## Medium-Term Plans

1. Marker redesign: place markers only on tiles that won't need buildings
2. Grid pruning with conveyor-safe exemption (M2 from scratchpad)
3. Explore-claim cleanup (remove dead parsing/state)
4. Ore BFS expansion for sparse maps

## All Landed Changes

1. Assault economy fallback (60 turns)
2. Economy-health gated bonus assault (round >= 80)
3. TILING_BACK ping-pong detection
4. Escalating blacklist TTL (60 → 180 → 500)
5. Exploration exhaustion reset (60 turns)
6. Economy stall reset (150 turns)
7. Assault progress tracking
8. Harvester place tracking
9. Unit count fix (live `get_unit_count()`)
10. Spawn interval 12, threshold 200
11. MAX_BUILDER_COUNT 12
12. Enemy sentinel danger zones
13. Claimed harvester recheck (20 turns)
14. Economy spawn tries all directions
15. Perception order swap + TILING_BACK health skip

## Compaction-Safe Resume Point

All changes committed across 4 commits on `got-any-grapes` branch.
40 unit tests passing. g16: 68.8% overall.
Next: continue iterating toward 80% per-opponent gate.
