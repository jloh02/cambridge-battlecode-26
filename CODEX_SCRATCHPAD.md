# CODEX Scratchpad

## Active Strategy Name

Floor-fix + anti-clumping + route resilience.

## Current State (2026-04-10)

### g64 validated (pre-congestion+retile)
- vs jon-6: 70.3%, vs surround: 51.6%, vs leeroy: 65.6%
- Overall: 62.5%, TLE turns: 0

### Latest g16 (with retile priority)
- vs jon-6: 87.5%, vs surround: 37.5% (variance), vs leeroy: 62.5%
- Overall: 62.5%

## Long-Term AFIs

### Axionite Delivery Pipeline
The bot delivers 0 refined axionite. Since the tiebreak order is:
1. Delivered refined axionite (bot always loses this)
2. Delivered titanium (current competitive dimension)
3. Harvesters alive
Even a small axionite delivery advantage would flip tiebreaks that the bot
currently loses on titanium. Requires: foundry placement, axionite
harvesting, conversion routing, core convert policy. This is a full
economy-chain feature, not a quick fix.

### Marker System Redesign  
Markers block construction. Needs a placement strategy that avoids
construction-critical tiles (e.g., only place on tiles that already have
roads, or on map edges, or use the marker's u32 payload differently).
Would enable: ore sharing, connected conveyor sharing, explore claims,
cross-builder coordination.

### Grid Pruning
Needs topology-safe implementation that preserves grid data for tiles
adjacent to conveyors, not just the conveyor tiles themselves. The topology
refresh reads building types and directions from neighboring tiles.

## Recent Changes (not yet in g64)

14. Priority re-tiling for disconnected harvesters
15. TILING_BACK friendly-blocker handling
16. Exploration builder-specific tie-break
17. Dead marker scan removal + inlined hot paths
18. Topology heartbeat 20→30
19. Grid pruning attempted and reverted (breaks adjacent tile data)

## Compaction-Safe Resume Point

14 commits on `got-any-grapes` branch. 40 tests passing.
g64 baseline: 62.5% overall. g16 best: 87.5% vs jon-6.
Next: continue iterating toward 80% per-opponent. The surround matchup
(~50% g64) remains the main blocker.
