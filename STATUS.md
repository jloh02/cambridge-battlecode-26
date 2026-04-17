# STATUS.md — got-any-grapes Active Development Scratchpad

**Last updated:** 2026-04-17
**Active strategy:** got-any-grapes
**Current iteration:** Post aggressive micro perception — best g16 yet

## Latest g16 Results (USE_GLOBAL_SEED=true)

| Opponent | W-L | Win% | Avg TiEq | Worst TiEq |
|---|---|---|---|---|
| jon-6 | 11-5 | 68.8% | 53,087 | 840 |
| a9bfs | 11-5 | 68.8% | 32,556 | 840 |
| leeroy | 12-4 | **75.0%** | 45,991 | 840 |
| **Overall** | **34-14** | **70.8%** | **43,878** | **840** |

## Comparison vs Baseline

| Opponent | Baseline | Current | Δ Win% | Δ TiEq |
|---|---|---|---|---|
| jon-6 | 62.5% / 42,853 | 68.8% / 53,087 | +6.3% | **+10,234** |
| a9bfs | 75.0% / 30,955 | 68.8% / 32,556 | -6.2% | +1,601 |
| leeroy | 43.8% / 36,299 | 75.0% / 45,991 | **+31.2%** | **+9,692** |
| **Overall** | 60.4% / 36,702 | **70.8%** / 43,878 | **+10.4%** | **+7,176** |

## Key Discovery

**A* budget exhaustion was causing TILING_BACK pipeline failures.** On hard
maps vs offensive opponents, perception overhead ate the A* time budget,
causing A* to fail after 2-51 iterations (budget-limited, not iteration-
limited). Pipelines never connected → 0 delivered Ti → losses.

Fix: aggressive micro perception for ALL TILING_BACK turns (removed enemy
visibility gate). scan_micro still populates visible_enemy_targets via
get_nearby_units() so defense remains functional.

## Next Priorities

1. Push jon-6 from 68.8% → 80% (economy + core destruction)
2. Stabilize a9bfs at 68.8%+ (currently noisy)
3. Push leeroy from 75% → 80%
4. Remote timing validation with current code
