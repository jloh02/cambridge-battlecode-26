# CODEX Scratchpad

## Active Long-Form Task

### Current checkpoint (2026-04-16): comprehensive bug fix pass

- Active strategy: delta perception + strategic bug fixes + defense tuning.
- Local g16 (USE_GLOBAL_SEED): **35-13 (72.9%)** session best.
  `jon-6` **12-4 (75.0%)**, `a9` **12-4 (75.0%)**, `leeroy` **11-5 (68.8%)**.
- Remote r2 timing (with all fixes): avg **25.9% >2ms** (down from 53.2%).
  Simple maps show 0.1-1.2% >2ms. Complex maps still 60-90% >2ms (A* + topology
  dominate, not perception).

**Changes committed this session (15+ fixes):**

Mechanistic / timing:
- Delta perception (spatial deferral for full scans): entered + safety ring are
  fresh, persisted tiles reuse cached grid data. ~50% fewer SDK calls per full scan.
- Delta entity clearing order fix: clear stale unit fields BEFORE _update_master_grid
  so fresh get_nearby_units data (including enemy sentinels) is preserved.
- Reduced TILING_BACK fast scan radius (9 → 2).
- Inlined direction deltas in _refresh_local_obstacle_memory.
- Removed depths dict from anytime A*.
- Topology reverse_links built as sets directly.
- Reverted obstacle fingerprint len-only (caused false A* signature matches).
- scan_micro() function (available, not called in current routing).
- FINDING_ORE A* budget increased (180/350μs → 250/500μs).
- SDK-verify conveyor merge to prevent phantom pipeline completion.

Strategic:
- Defender active healing (moves toward damaged buildings within leash).
- Defender demotion after 80 turns (clears stale state on transition).
- Hijack gate strengthened (4+ connected transports, positive load, Ti reserves).
- Removed RESOURCE_MAX_SPAWN_BUILDER cap.
- EXPLORING → FINDING_ORE only when unclaimed ore exists.
- Lane defense fires BEFORE healing (sentinels > heal against sentinels).
- DIRECT_CORE_RETURN_MAX_DIST 18 → 12 (more pipeline merges).
- Port load penalty in core lane slot scoring (4 × load_count).
- ECON_STALL_RESET_INTERVAL 150 → 100.
- LANE_THREAT_RADIUS_SQ 9 → 18 (covers sentinel fire range).
- Assault → economy transition clears stale state.
- Explorer stays in EXPLORING on chunk arrival when no ore known.
- S31 v2: never-connected harvester retile with enemy/distance gates (testing).
- 8 new maps extracted from remote replays.

**Remaining known bugs (not yet fixed):**

Mechanistic / performance:
- Bug 6: `_is_ore_claimed_by_friend` creates fresh access_cache per BFS call
  instead of reusing across candidates. Performance-only, low impact.
  (mode_finding_ore.py:368)
- Bug 13-16: Assault opening escape BFS creates Position objects in the hot loop
  (49 nodes × 8 directions × Position.add). Takes 1-2.4ms locally / 3-12ms
  Graviton. Double BFS (_shell_exit_target + _shell_escape_route) could merge.
  _opening_escape_direction_order calls _in_spawn_shell 8× per node.
  Complex refactor, separate batch. (mode_assaulting.py:401-469)
- Danger zone around enemy sentinels is 3×3 (1 tile each direction) but sentinel
  fire range is ~5.7 tiles along facing direction. Builders approaching along the
  fire line from 4+ tiles aren't in the danger zone. Fix would need directional
  danger zones using sentinel facing info. (perception.py:962-977)

Strategic:
- S27: `_is_ore_claimed_by_friend` doesn't account for friend's MODE. A friend
  in TILING_BACK near ore "claims" it via distance deconfliction even though it's
  heading to the core, not the ore. Needs inter-builder communication (markers)
  or mode-awareness approximation. (mode_finding_ore.py:365-391)
- S31: Never-connected harvester retile: v1 (round 120, no gates) regressed
  leeroy 43.8%; v2 (round 200, enemy+distance gates) under test.
  (mode_finding_ore.py:664-673)
- No pipeline completion verification: after TILING_BACK completes, the builder
  never checks if titanium is actually flowing. A route with a directional error
  at one tile stays broken forever unless the retile system catches it (which
  requires prev_adjacent_conveyors > 0). (mode_tiling_back.py:1892-1904)
- `_recheck_claimed_harvesters` uses stale `_has_adjacent_conveyor` which reads
  `connected_friendly_conveyors` — on delta turns this may be stale, causing
  unnecessary unclaim/retile cycles. (mode_finding_ore.py:701-726)
- `_is_visible_current_round` in mode_hijacking checks `last_seen == current_round`
  — on delta perception turns, persisted tiles have `last_seen` from a previous
  turn. Hijack targets on persisted tiles appear invisible even though they're
  still in view. (mode_hijacking.py:93-100)
- `main.py` line 11: `random.seed(1)` always pins the global random state to
  seed 1 unless USE_GLOBAL_SEED overrides it. This makes the core's spawn
  rotation deterministic across all non-USE_GLOBAL_SEED games. Opponents could
  fingerprint the fixed rotation order. (main.py:11)

**Rejected ideas (with evidence):**
- Pure micro perception (unit-only scan, no grid updates): 8.3% g16 — stale
  obstacles caused permanent A* stalls.
- Obstacle fingerprint len-only: remote 8-22 — false signature matches.
- Three-tile small-loop threshold: collapsed jon-6 locally.
- Target-aware small-loop recovery: collapsed all opponents locally.
- Opening fast-perception grace: collapsed a9 locally.
- S31 v1 retile (round 120, no enemy gate): leeroy 43.8% regression.

**Compaction-safe resume point:** all fixes committed. S31 v2 under benchmark.
Next ROI targets: assault opening escape optimization (Bug 13-16), perception
age threshold to replace fixed full-scan intervals, pipeline completion
verification after TILING_BACK.
