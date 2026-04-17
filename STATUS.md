# STATUS.md — got-any-grapes Active Development Scratchpad

**Last updated:** 2026-04-17
**Active strategy:** got-any-grapes
**Current iteration:** Post-tournament analysis

## All-Map Tournament Results (122 games/opponent, 61 maps × 2 seats)

| Opponent | W-L | Win% | Avg TiEq | Core Destructions |
|---|---|---|---|---|
| jon-6 | 82-40 | 67.2% | 48,922 | 28 |
| a9bfs | 69-53 | 56.6% | 38,670 | 31 |
| leeroy | 74-48 | 60.7% | 41,210 | 33 |
| **Overall** | **225-141** | **61.5%** | **42,934** | **92** |

## Comparison vs Baseline (g16)

| Opponent | Baseline g16 | Tournament | Δ TiEq |
|---|---|---|---|
| jon-6 | 62.5% / 42,853 | 67.2% / 48,922 | +6,069 |
| a9bfs | 75.0% / 30,955 | 56.6% / 38,670 | +7,715 |
| leeroy | 43.8% / 36,299 | 60.7% / 41,210 | +4,911 |

**TiEq improved for ALL opponents vs baseline.** Win rates are below 80% target
but tournament uses 61 maps (including hard maps) vs g16's random maps.

## Analysis

- **a9bfs at 56.6%** is the main weakness — BFS surround attacks from
  multiple directions, our single defender can't cover all sides
- **Core destructions high** (25% of games) — rusher is very effective on
  favorable maps (gaussian: turn 147, shish_kebab: turn 188)
- **leeroy improved** from 43.8% baseline to 60.7% — defense hardening works
- **jon-6 improved** TiEq by +6k — economy + core destruction is solid

## Next Priorities

1. Improve a9bfs matchup (56.6% → 80%)
2. Push jon-6 from 67% → 80%
3. Further TLE reduction for remote deployment
4. Commit tournament results
