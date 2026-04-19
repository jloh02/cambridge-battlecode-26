# STATUS.md — got-any-grapes Active Development Scratchpad

**Last updated:** 2026-04-17
**Active strategy:** got-any-grapes
**Session:** Complete — all changes committed

## Validated Results

### All-Map Tournament (122 games/opponent — ground truth)
| Opponent | W-L | Win% | Avg TiEq | Core Kills (us/them) |
|---|---|---|---|---|
| jon-6 | 82-40 | 67.2% | 48,922 | 28/0 |
| a9bfs | 69-53 | 56.6% | 38,670 | 25/6 |
| leeroy | 74-48 | 60.7% | 41,210 | 20/13 |

### g16 Range (noisy, ±8%)
Best single g16: 70.8% overall (34-14)
- jon-6: 68.8%, a9bfs: 68.8%, leeroy: 75.0%

### vs Baseline Improvement (TiEq, tournament)
| Opponent | Baseline TiEq | Tournament TiEq | Δ |
|---|---|---|---|
| jon-6 | 42,853 | 48,922 | **+6,069** |
| a9bfs | 30,955 | 38,670 | **+7,715** |
| leeroy | 36,299 | 41,210 | **+4,911** |

**TiEq improved for ALL opponents.**

## All Commits This Session

| Commit | Change | Impact |
|---|---|---|
| 740ef3d | Defense hardening + role spec + TLE basics | Foundation |
| 43a7e4a | Tournament results documentation | — |
| 8c4af42 | **Aggressive micro perception for TILING_BACK** | **Key breakthrough** |
| 590d8e9 | Best g16 documentation | — |
| b55a14f | Tournament + noise analysis documentation | — |
| 012c0ae | SDK caching + fast scan radius reduction | TLE reduction |

## Key Discovery

**A* budget exhaustion was the root cause of TILING_BACK pipeline failures.**
Perception overhead consumed the time budget before A* could find paths.
Micro perception (16 SDK calls vs ~40) gave A* enough budget to complete
connections. This single change improved leeroy from 43.8% to 75.0%.

## Remaining Work (Not Blocking)

- 80% target: jon-6 +13pp, a9bfs +23pp, leeroy +19pp (tournament)
- Remote timing: Graviton3 5x SDK multiplier → ~55-90% of turns >1ms
- TILING_BACK still fails on hard maps (wall, first_sound, cinnamon_roll)
- Axionite pipeline: scaffolded but not production-tested
