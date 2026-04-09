# CODEX Scratchpad

## Active Strategy Name

Floor-fix + anti-clumping + perception optimization + route resilience.

## Current State (2026-04-10)

### Latest g16 (all optimizations)
- **Overall: 75.0%**
- vs jon-6: **93.8%** (15-1)
- vs a9bfs-surround: **68.8%** (11-5)
- vs leeroy-jonkins: **62.5%** (10-6)
- TLE turns: 0

### Progress from baseline
| Opponent | Baseline | Current Best | Improvement |
|----------|----------|-------------|-------------|
| jon-6 | 56.2% | 93.8% | +37.6 |
| surround | 43.8% | 68.8% | +25.0 |
| leeroy | 56.2% | 75.0%* | +18.8 |
| Overall | 52.1% | 75.0% | +22.9 |

*leeroy best was 81.2% in one run, current run 62.5%.

## 18 Commits on `got-any-grapes` Branch

### Economy + offense
1-7. Assault fallback, economy-gated assault, progress tracking, unit count fix,
     builder cap 12, spawn interval 12/threshold 200, spawn all directions

### Stall recovery
8-12. Ping-pong detection, escalating blacklist, explore reset, economy stall
      reset, claimed harvester recheck (8 turns)

### Anti-clumping
13-16. Shared stall TTL 12, friendly blocker TTL 8, TILING_BACK blocker handling,
       explore ID-based tie-break

### Route resilience
17. Priority re-tiling for disconnected harvesters

### Perception + runtime
18-22. Danger zones, dead marker removal, inlined cardinals, topology heartbeat 30,
       adaptive BFS, chunk dedup, orientation precheck, heal simplification

## Long-Term AFIs

1. **Axionite delivery pipeline** — foundry + conversion + routing
2. **Marker system redesign** — avoid construction-critical tiles
3. **Grid pruning** — topology-safe implementation
4. **Intent-based deconfliction** — reservation via markers (blocked by marker redesign)

## Compaction-Safe Resume Point

18 commits. 40 tests passing. g16 best: 75.0% overall (93.8% vs jon-6).
g64 validated: 62.5% overall (pre-recent optimizations).
