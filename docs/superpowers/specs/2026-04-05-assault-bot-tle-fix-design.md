# Assault Bot TLE Fix — Design Spec

**Date:** 2026-04-05  
**Target bot:** `jon-6-a5bfs` (working copy of `jon-6-a4bfs`)  
**Problem:** All assault builder bots consistently TLE (reported 2004–2100ms against ~2000ms budget on AWS Graviton3)  
**Goal:** Bring assault bots reliably under 2ms without changing observable behaviour

---

## Context

Assault bots spawn in diagonal slots (NE/NW/SE/SW of core) and immediately enter `BuilderMode.ASSAULTING`. Unlike economy bots they never build conveyors, never use tiling-back, and their value comes from placing sentinels adjacent to enemy harvesters. The TLE is marginal (~5–10% over budget) and manifests from turn 1.

The four identified hotspots are all in the assault-specific code paths. No economy or tiling-back code is changed.

---

## Change 1 — Memoize `sentinel_attack_tiles` (`assault.py`)

### Problem
`sentinel_attack_tiles(origin, direction)` is a pure function that computes the set of tiles a sentinel at `origin` firing in `direction` can hit. It is called up to 32 times per visible enemy harvester per turn (4 ring positions × 8 sentinel directions in `rank_assault_sites_for_harvester`, plus additional calls in `visible_threat_score`). The result never changes for the same `(origin, direction)` pair.

### Fix
Add a module-level dict `_SENTINEL_ATTACK_CACHE: dict[tuple[int, int, str], frozenset[tuple[int, int]]]` (key: `(origin.x, origin.y, direction.name)`).

Change `sentinel_attack_tiles` to:
1. Check the cache; return the cached frozenset if present.
2. Otherwise compute as before, store as a `frozenset` of `(x, y)` int tuples (not `Position` objects — avoids allocation overhead and frozenset is hashable).

**Call site audit:**
- `_target_summary_for_site`: tests `if enemy.position not in attack_tiles` and `if enemy_core_center in attack_tiles` — these use `Position` objects. Must change membership tests to `(pos.x, pos.y)`.
- `_friendly_ring_sentinel_state`: tests `if position in attack_tiles` where `position` is a `Position`. Same fix.
- `visible_threat_score`: tests `if ring_position in sentinel_attack_tiles(...)` — same fix.

All three call sites need `.x`/`.y` unpacking for the membership test. Return type changes from `set[Position]` to `frozenset[tuple[int, int]]`.

---

## Change 2 — Skip conveyor topology refresh for assault bots (`perception.py`, `builder_bot.py`)

### Problem
`_infer_state_from_grid` with `refresh_connected=True` (the default) runs a BFS over `known_friendly_conveyors` to recompute which conveyors are connected to core. Assault bots never build conveyors, so this BFS is always empty-but-still-entered and the topology-dirty check runs every visible tile. On topology-change or every 15 rounds it also iterates `known_friendly_conveyors` to rebuild `connected_friendly_conveyors`. All wasted for assault bots.

### Fix
Add parameter `assault_mode: bool = False` to `scan_around`. When `True`, pass `refresh_connected=False` to `_infer_state_from_grid`.

In `builder_bot.py`, change the `scan_around` call to:
```python
perception.scan_around(self, ct, fast=use_fast_perception, assault_mode=bool(self.is_assault_role))
```

This preserves full vision range (unlike the existing fast-scan path which restricts to radius 3) while skipping the wasted topology work.

---

## Change 3 — Sort BFS direction order once per path, not per node (`navigation.py`)

### Problem
`_ordered_assault_directions(current, target)` calls `sorted(ASSAULT_CLOCKWISE_DIRECTIONS, key=...)` on **every BFS node expansion**. Sorting 8 elements with a multi-field tuple key involves ~24 comparisons. With 50–200 node expansions per path, this is 1200–4800 comparisons of avoidable work per `calculate_assault_bfs_path` call.

### Fix
Compute the preferred direction order **once per BFS call** using the start→target vector, and pass that fixed list into the BFS loop. Remove `_ordered_assault_directions` from the inner loop entirely.

In `calculate_assault_bfs_path`:
```python
preferred_dirs = _ordered_assault_directions(start, target)
# ... then inside the BFS loop:
for direction in preferred_dirs:
    ...
```

**Correctness note:** BFS guarantees a shortest path regardless of direction order — the sort is purely a heuristic that reduces nodes expanded by preferring directions that head toward the target. Using the start→target order throughout is a slight approximation (the ideal direction subtly shifts as you traverse the map), but in practice path lengths are short enough that the fixed order finds the same or equivalent shortest path. BFS correctness is unaffected.

---

## Change 4 — Cache `_anchor_assessment` within a turn (`mode_assaulting.py`)

### Problem
Within a single `execute()` call, `_anchor_assessment(bot, ct, harvester_position)` is called 3–5 times for the same harvester position. Each call invokes `rank_assault_sites_for_harvester` (up to 32 site evaluations, each calling `sentinel_attack_tiles` and `connected_enemy_logistics_cluster`). The enemies list and grid do not change during a turn.

Call sites within one `execute()`:
1. Live anchor assessment (line ~1498)
2. Chosen site assessment when site differs from live anchor (line ~1523)
3. Inside `_execute_support` → `_anchor_assessment` (line ~905)
4. `post_support_assessment` after support fails (line ~1570)
5. `post_support_assessment` in the live-anchor support branch (line ~1602)

### Fix
Pass a `_assessment_cache: dict[tuple[int, int], AnchorAssessment]` dict into `execute()` as a local variable (created at top of `execute()`). Thread it through to all `_anchor_assessment` call sites within `execute()`. `_anchor_assessment` gains an optional `cache` parameter; if provided, checks `(pos.x, pos.y)` before computing and stores the result after.

The cache is a plain local dict — no invalidation needed since it's created fresh each turn.

---

## Files Changed

| File | Change |
|------|--------|
| `bots/jon-6-a5bfs/assault.py` | Memoize `sentinel_attack_tiles`; update 3 call sites |
| `bots/jon-6-a5bfs/perception.py` | Add `assault_mode` param to `scan_around` |
| `bots/jon-6-a5bfs/builder_bot.py` | Pass `assault_mode=self.is_assault_role` to `scan_around` |
| `bots/jon-6-a5bfs/navigation.py` | Precompute direction order table; update `_ordered_assault_directions` |
| `bots/jon-6-a5bfs/mode_assaulting.py` | Add `_anchor_assessment` cache in `execute()` |
| `bots/jon-6-a5bfs/README.md` | Document changes |

## Out of Scope

- Economy/ore/tiling-back bots (confirmed working, not touched)
- Navigation strategy (BFS + Bug2) — separate future task
- `build_predicted_enemy_harvesters` dedup — impact judged too small (~5–20µs)
