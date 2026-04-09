# CODEX Scratchpad

## Active Strategy Name

Floor-fix + anti-clumping + perception optimization.

## Session Summary (2026-04-09 → 2026-04-10)

### Validated Improvement (g64 with --tle-ms 2, 192 games)
| Opponent | Baseline g64 | Current g64 | Improvement |
|----------|-------------|-------------|-------------|
| jon-6 | 56.8% | 70.3% | +13.5 |
| a9bfs-surround | 37.5% | 51.6% | +14.1 |
| leeroy-jonkins | 60.9% | 65.6% | +4.7 |
| **Overall** | **56.8%** | **62.5%** | **+5.7** |

- TLE turns: 0
- TiEq improved from 27640 avg

### g16 variance note
g16 runs with identical code range from 51-79%. The g64 is the reliable
signal. Individual g16 runs should not be used to claim or deny progress.

### Best g16 result
- 79.2% overall (87.5% jon-6, 68.8% surround, 81.2% leeroy)

## 12 Commits Landed

### Economy + offense
1. Assault economy fallback (60 turns)
2. Economy-health gated bonus assault (round >= 80)
3. Assault progress tracking (scout doesn't count)
4. Unit count fix (live `get_unit_count()`) — critical bug fix
5. MAX_BUILDER_COUNT raised to 12
6. Spawn interval 12, threshold 200
7. Economy spawn tries all directions (P1 congestion fix)

### Stall recovery
8. TILING_BACK ping-pong detection
9. Escalating blacklist TTL (60 → 180 → 500)
10. Exploration exhaustion reset (60 turns)
11. Economy stall reset (150 turns)
12. Claimed harvester recheck for broken routes (20 turns)

### Anti-clumping
13. Shared progress stall TTL 6→12
14. Friendly blocker always marked (TTL 8)
15. TILING_BACK friendly-blocker handling (new, highest-impact)
16. Exploration builder-specific tie-break (ID-based perturbation)

### Perception + runtime
17. Enemy sentinel danger zones for economy builders
18. Dead marker scan removal (frontier, offensive_route branches)
19. Inlined cardinal deltas + cached conveyor type set
20. Topology heartbeat 20→30 turns
21. Adaptive BFS ore search (50/80/120 nodes by map size)
22. Perception order swap + TILING_BACK health skip

### Tested and reverted
- Sidestep on friendly block: regression (27K from 32K Ti), reverted
- Marker re-enable (P0): massive regression (42%), markers block construction
- Connected harvester markers: permanent claimed_harvesters issue

## Bug Assessment (GPT findings)

### Fixed
- P0 TILING_BACK missing blocker recovery ✓
- P1 economy spawn congestion ✓
- P1 yield rule incomplete ✓

### Confirmed, deliberately deferred
- P0 Marker self-poisoning: markers block construction. Needs redesign.
- P1 Ore-marker→core architecture: moot while markers disabled.
- P1 Grid pruning + topology scaling: needs conveyor-safe exemption.
- P1 Explore-claim dead code: parsed but never consumed.
- P2 Dead marker surface: maintenance drag only.

## Remaining Gap to 80%

The surround matchup (51.6% g64) is the main blocker. Root cause: the
opponent builds sentinels for defense/offense and destroys our infrastructure
(74 conveyors killed in analyzed game). The bot has no defensive infrastructure.

Options for future work:
1. Defensive sentinels near harvester clusters
2. Route resilience (detect + rebuild broken routes faster)
3. More aggressive counter-assault to disrupt opponent before they attack
4. Marker system redesign to enable real cross-builder coordination

## Compaction-Safe Resume Point

12 commits on `got-any-grapes` branch. 40 tests passing.
g64: 62.5% overall (pre-congestion/explore fixes).
All changes documented. Next iteration should focus on the surround matchup
specifically.
