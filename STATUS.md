# STATUS.md — got-any-grapes Active Development Scratchpad

**Last updated:** 2026-04-17
**Active strategy:** got-any-grapes (economy-first + rusher + defender)
**Current iteration:** Commit candidate — defense + role spec + TLE reduction

## Cumulative g16 Results (vs baseline, USE_GLOBAL_SEED=true)

| Opponent | Baseline | Current | Δ Win% | Δ TiEq |
|---|---|---|---|---|
| jon-6 | 62.5% / 42,853 | 75.0% / 62,771 | **+12.5%** | **+19,918** |
| a9bfs | 75.0% / 30,955 | 56.2% / 37,830 | -18.8% (noise) | **+6,875** |
| leeroy | 43.8% / 36,299 | 50.0% / 31,927 | +6.2% | -4,372 |
| **Overall** | **60.4% / 36,702** | **60.4% / 44,176** | **0%** | **+7,474** |

**Note**: Win rate deltas ±4 wins (±25%) are unresolved noise per CLAUDE.md.
TiEq improved for 2/3 opponents. jon-6 consistently improved across all runs.
a9bfs win rate fluctuated widely (37-75%) across runs but TiEq was always above baseline.

## Changes Applied (Commit Candidate)

| File | Change | Status |
|---|---|---|
| defense.py | `MAX_VISIBLE_CORE_DEFENSE_SENTINELS` 1→2 | KEPT |
| defense.py | `DEFENSE_SENTINEL_COOLDOWN` 12→6 | KEPT |
| defense.py | `DEFENSE_ECONOMY_EMERGENCY_CORE_DIST_SQ=18` | KEPT |
| mode_rush.py | Post-turret hijack check | KEPT |
| mode_hijacking.py | Role-aware hijack completion fallback | KEPT |
| builder_bot.py | Defender orphan tracking + port management | KEPT |
| perception.py | Safety ring radius 2→1 | KEPT |
| perception.py | Fixed double `get_position()` in fast scan | KEPT |
| builder_bot.py | Micro perception for TILING_BACK | KEPT |
| builder_bot.py | `ECON_STEADY` 8→10, `ECON_TILING` 10→14 | KEPT |
| defense.py | Barrier cooldown 20→10 | **REVERTED** |
| builder_bot.py | Defender inward patrol | **REVERTED** |

## Profiling (cold map, local)
- 2.3% of builder turns >1ms (meets <5% local target)
- TILING_BACK/micro: 212μs avg (cheapest tier)
- Remote: ~55-93% >1ms (Graviton3 ~5x SDK latency, fundamental constraint)

## Resume Point
Commit current changes, then continue with next priority:
- Improve a9bfs stability (currently noisy 56-75%)
- Push leeroy from 50% toward 80%
- Further TLE reduction for remote deployment
