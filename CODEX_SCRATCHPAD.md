# CODEX Scratchpad

## Active Strategy Name

TILING_BACK stall recovery + runtime optimization pass.

## Task Description

Improve `got-any-grapes` from its current low-floor, tiebreak-heavy state into a stable promotion candidate.

## Criteria

Per `CODEX_INSTRUCTIONS.md`: g16 ≥80% per opponent, g64 with TLE, remote validation.

## Latest Evidence

### g16 Passing (without TLE enforcement)

- **Aggregate: 81.2%** across all opponents
- jon-6: **81.2%** (13-3)
- jon-6-a9bfs-surround: **81.2%** (13-3)
- leeroy-jonkins: **81.2%** (13-3)
- All three opponents pass the 80% gate.

### g64 with TLE: Not Passing (58.3%)

- The g64 with `--tle-ms 2` shows significant degradation from TLE pressure
- jon-6: 65.6%, jon-6-a9bfs-surround: 45.3%, leeroy-jonkins: 64.1%
- Primary blocker: late-game per-turn cost exceeds 2ms on Graviton3

### Remote TLE Analysis

Across 3 remote test runs vs jon-6, remote results are 3-2, 3-2, 3-2 (all wins). The bot wins enough early games before TLE pressure becomes severe. But late-game TLE rates are extreme (up to 83-97% of turns over 2ms).

**Baseline (no optimizations)**: Game 5: 97.1% TLE, avg 2150μs
**With mechanistic optimizations**: Game 5: ~83% TLE, avg ~1990μs
**With fast perception for tiling (rolled back — regressed winrate)**: Game 3: 1.9% TLE, avg 951μs but g16 dropped to 62.5%

### Runtime Optimization Impact

Mechanistic optimizations (A* inlining, closed set, batch-clear, `is` comparisons, etc.) provide ~10-15% reduction in average turn time. Not enough for the user's target of 4x (25% of current).

Extending fast perception to economy builders provides ~50% reduction but regresses winrate (81.2% → 62.5%).

## Landed Changes This Session

### Behavior (improve win rate):
1. Pending-build stall recovery (6-turn limit)
2. Navigation stall recovery (40-turn limit + harvester blacklist)
3. Exploration deconfliction bugfix (tuple-vs-Position, Position[0] → Position.x)
4. Grid KeyError safety in _clear_obstacles_for_conveyor

### Runtime (no algorithm change):
5. A* hot loop inlining (eliminate function call overhead for walkability, step cost, heuristic, line deviation)
6. A* closed set (both calculate_astar_path and anytime)
7. Merged obstacle sets upfront (one set lookup per neighbor)
8. Perception batch-clear with pre-built dict template
9. Perception `ct.get_team()` caching
10. Perception `_infer_state_from_grid` deferred Position creation + `is` comparisons
11. Hijacking and healing inline distance arithmetic

### Rejected:
- Fast perception for TILING_BACK builders (interval 3): regressed g16 from 81.2% to 62.5%

### Tests:
- 7 new unit tests (35 total, all passing)

## Emergent Property Suggestions (not implemented)

1. **Adaptive assault expiry**: Transition idle assault builders to economy after ~80 turns
2. **Economy-health gated bonus assault**: Require at least 1 delivering harvester before bonus assault
3. **Late-game builder spawn cap**: Stop spawning after 6-7 active economy builders past turn ~1200
4. **Cross-builder route sharing**: Share completed TILING_BACK routes via markers
5. **Exploration ore broadcast**: Explorer-discovered ore shared to core's marker pool
6. **Harvester saturation awareness**: Prefer new harvesters on unsaturated logistics branches

## Compaction-Safe Resume Point

Resume from the current code with all behavior fixes and mechanistic optimizations, but NO fast perception for economy builders.

**Where we stand**:
- g16 passes (81.2% per opponent)
- Remote tests pass (3-2 consistently against jon-6)
- g64 with TLE fails (58.3%)
- The TLE blocker requires either: (a) a perception scope reduction that doesn't regress winrate, or (b) a fundamentally different approach to late-game turn cost

**Next steps for TLE**:
- The fast perception approach works technically (massive TLE reduction) but needs to preserve more information — possibly a wider fast-scan radius or selective full-scan for tiles that changed
- Grid pruning (remove entries > N turns old) could reduce dict sizes and thus all dict-dependent operations
- Merging the grid-update and inference passes into one loop eliminates the second iteration over ~100+ positions
- Consider whether reducing A* mode budgets (iteration limits) by ~30% affects path quality measurably

**Key files**:
- `bots/got-any-grapes/mode_tiling_back.py` (stall recovery)
- `bots/got-any-grapes/mode_exploring.py` (bugfix)
- `bots/got-any-grapes/navigation.py` (A* optimization)
- `bots/got-any-grapes/perception.py` (runtime optimization)
- `tests/test_got_any_grapes_runtime_substrate.py` (7 new tests)
