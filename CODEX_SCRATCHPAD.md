# CODEX Scratchpad

## Active Strategy Name

Floor-fix + congestion reduction + perception optimization.

## Current State (2026-04-10)

### g64 with --tle-ms 2 (pre-congestion-fix code)
- **vs jon-6: 70.3%** (45-19, up from baseline 56.8%)
- **vs a9bfs-surround: 51.6%** (33-31, up from baseline 37.5%)
- **vs leeroy-jonkins: 65.6%** (42-22, up from baseline 60.9%)
- **Overall: 62.5%** (up from 56.8%)
- TLE turns: 0

### Best g16 result (one run)
- 79.2% overall (87.5% jon-6, 68.8% surround, 81.2% leeroy)

### Progress from baseline
| Metric | Baseline g64 | Current g64 | Best g16 |
|--------|-------------|-------------|----------|
| vs jon-6 | 56.8% | 70.3% | 87.5% |
| vs surround | 37.5% | 51.6% | 68.8% |
| vs leeroy | 60.9% | 65.6% | 81.2% |
| Overall | 56.8% | 62.5% | 79.2% |

### Not yet captured in g64:
- Congestion fix (longer obstacle TTL, always mark friendly blockers)
- Perception optimizations (dead code removal, inlined hot paths)
- Adaptive BFS ore search

## All Committed Changes (7 commits on got-any-grapes branch)

1. Assault economy fallback (60 turns)
2. Economy-health gated bonus assault (round >= 80)
3. TILING_BACK ping-pong detection
4. Escalating blacklist TTL (60 → 180 → 500)
5. Exploration exhaustion reset (60 turns)
6. Economy stall reset (150 turns — clears blacklists + fail counts)
7. Assault progress tracking (scout doesn't count)
8. Harvester place tracking
9. Unit count fix (live `get_unit_count()`)
10. Spawn interval 12, threshold 200
11. MAX_BUILDER_COUNT 12
12. Enemy sentinel danger zones
13. Claimed harvester recheck (20 turns)
14. Economy spawn tries all directions
15. Adaptive BFS ore search (map-size scaled)
16. Congestion: shared progress TTL 6→12, friendly blocker TTL 3→8
17. Always mark friendly builder blockers as temp obstacles
18. Dead marker scan removal (frontier, offensive_route)
19. Inlined cardinal deltas + cached conveyor set
20. Topology heartbeat 20→30 turns

## Compaction-Safe Resume Point

7 commits on `got-any-grapes` branch. 40 tests passing.
g64: 62.5% overall. g16 best: 79.2%.

Next: run g16/g64 with latest changes (congestion + perception) to measure impact.
Then continue toward 80% per-opponent gate.
