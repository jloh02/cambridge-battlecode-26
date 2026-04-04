# jon-6-a5bfs

`jon-6-a5bfs` branches from `jon-6-a4bfs` and targets the assault-bot TLE.

## Starting Point
- starts from `jon-6-a4bfs` baseline (bridge/tiling-back bug already fixed)
- all assault bots TLE on every turn in `jon-6-a4bfs`

## Performance Changes vs jon-6-a4bfs

### 1. Memoize `sentinel_attack_tiles` (`assault.py`)
- Added module-level `_SENTINEL_ATTACK_CACHE` keyed by `(origin.x, origin.y, direction.name, max_range_sq)`
- Returns `frozenset[tuple[int,int]]` instead of `set[Position]`
- All 4 membership-test call sites updated to use `(pos.x, pos.y)` tuple form
- Expected saving: eliminates repeated computation for the same (ring, direction) pair across 32+ calls per visible harvester per turn

### 2. Skip conveyor topology refresh for assault bots (`perception.py`, `builder_bot.py`)
- Added `assault_mode: bool = False` parameter to `scan_around`
- When `True`, passes `refresh_connected=False` to `_infer_state_from_grid`
- `builder_bot.py` passes `assault_mode=bool(self.is_assault_role)`
- Expected saving: skips the conveyor-connected BFS that assault bots never need (they never build conveyors)

### 3. Sort BFS direction order once per path (`navigation.py`)
- In `calculate_assault_bfs_path`, `preferred_dirs = _ordered_assault_directions(start, target)` computed once before the BFS loop
- Inner loop uses `preferred_dirs` instead of re-sorting on every node expansion
- Expected saving: eliminates `sorted(8 dirs)` call on every BFS node (50–200 nodes per path)

### 4. Cache `_anchor_assessment` within a turn (`mode_assaulting.py`)
- Added `cache: dict | None = None` kwarg to `_anchor_assessment`, `_best_visible_site`, `_execute_support`
- `execute()` creates `_aa_cache = {}` at the top and threads it through all 7 call sites
- Expected saving: `rank_assault_sites_for_harvester` (32 site evaluations) is called once per harvester position per turn instead of 3–5 times

## Current State
- all four TLE optimisations applied
- benchmarked against `jon-6-a4bfs` on smoke maps — see benchmark output

## TODO
- [ ] verify TLE is resolved via camb match API submission
- [ ] if still TLEing, profile with DEBUG_TIME on large maps
- [ ] consider BFS+Bug2 navigation replacement (separate task)
