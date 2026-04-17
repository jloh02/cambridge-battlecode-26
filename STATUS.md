# STATUS.md — got-any-grapes Active Development Scratchpad

**Last updated:** 2026-04-17
**Active strategy:** got-any-grapes
**Current iteration:** Stabilized — noise-bounded at current architecture

## Validated Results

### All-Map Tournament (122 games/opponent, most stable)
| Opponent | W-L | Win% | Avg TiEq |
|---|---|---|---|
| jon-6 | 82-40 | 67.2% | 48,922 |
| a9bfs | 69-53 | 56.6% | 38,670 |
| leeroy | 74-48 | 60.7% | 41,210 |

### Best g16 (USE_GLOBAL_SEED, note ±8% noise)
| Opponent | Win% | Avg TiEq |
|---|---|---|
| jon-6 | 68.8% | 53,087 |
| a9bfs | 68.8% | 32,556 |
| leeroy | **75.0%** | 45,991 |
| Overall | **70.8%** | 43,878 |

### Improvement vs Baseline
| Opponent | Baseline TiEq | Tournament TiEq | Δ |
|---|---|---|---|
| jon-6 | 42,853 | 48,922 | **+6,069** |
| a9bfs | 30,955 | 38,670 | **+7,715** |
| leeroy | 36,299 | 41,210 | **+4,911** |

TiEq improved for ALL opponents vs baseline.

## Changes Applied (Committed)

1. **Defense Hardening**: 2 core sentinels, 6-turn cooldown, wider economy gate
2. **Role Spec**: Rusher hijack, assault completion fallback, defender orphan mgmt
3. **TLE Reduction**: Safety ring 1, micro perception for TILING_BACK, perception intervals
4. **Key Discovery**: A* budget exhaustion → TILING_BACK pipeline failures

## Remaining Gaps

- 80% target: jon-6 needs +13pp, a9bfs +23pp, leeroy +19pp
- Root cause: TILING_BACK pipeline connection failures on hard maps
  (wall, first_sound, default_large1, cold, cinnamon_roll)
- Delivered Ti is the bottleneck (mined but not delivered)
- Remote timing: Graviton3 5x multiplier makes ~55% of turns >1ms

## Reverted Changes (Not Helpful)
- PENDING_BUILD_STALL_LIMIT 6→3: caused more frequent replanning → worse
- Defender patrol to inward position: collapsed a9bfs
- FINDING_ORE micro perception: stale grid data → a9bfs regression
- Aggressive perception intervals (search 4→6, steady 8→12): delayed threat detection
