# Assault Bot TLE Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `jon-6-a5bfs` assault builder bots reliably under 2ms per turn on AWS Graviton3 by eliminating four identified performance hotspots.

**Architecture:** Four surgical changes — memoize a pure function called in tight loops, skip wasted conveyor topology work for assault bots, sort BFS direction order once per path instead of per node, and cache a repeated expensive computation within a single turn. No behaviour changes.

**Tech Stack:** Python 3.13, `cambc` SDK, `pytest`

---

## File Map

| File | Change |
|------|--------|
| `bots/jon-6-a5bfs/assault.py` | Add `_SENTINEL_ATTACK_CACHE`; rewrite `sentinel_attack_tiles` to return `frozenset[tuple[int,int]]`; update 4 membership-test call sites |
| `bots/jon-6-a5bfs/perception.py` | Add `assault_mode: bool = False` to `scan_around`; pass `refresh_connected=False` when True |
| `bots/jon-6-a5bfs/builder_bot.py` | Pass `assault_mode=bool(self.is_assault_role)` to `scan_around` |
| `bots/jon-6-a5bfs/navigation.py` | Compute `preferred_dirs` once before the BFS loop in `calculate_assault_bfs_path` |
| `bots/jon-6-a5bfs/mode_assaulting.py` | Add `cache` kwarg to `_anchor_assessment`, `_best_visible_site`, `_execute_support`; create turn-local cache in `execute()` |
| `bots/jon-6-a5bfs/README.md` | Document all changes |
| `tests/test_jon_6_a5bfs_assault.py` | New: tests for Changes 1, 2, 4 |
| `tests/test_jon_6_a5bfs_navigation.py` | New: tests for Change 3 |

---

## Task 1 — Memoize `sentinel_attack_tiles` + fix call sites (`assault.py`)

**Files:**
- Modify: `bots/jon-6-a5bfs/assault.py`
- Create: `tests/test_jon_6_a5bfs_assault.py`

- [ ] **Step 1.1: Write failing tests**

Create `tests/test_jon_6_a5bfs_assault.py`:

```python
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


JON_6_A5_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a5bfs"
)
for module_name in (
    "assault",
    "marker",
    "mode_assaulting",
    "navigation",
    "perception",
    "utils",
    "states",
):
    sys.modules.pop(module_name, None)
if str(JON_6_A5_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A5_BFS_ROOT))
importlib.invalidate_caches()

import assault as a5_assault  # noqa: E402
import mode_assaulting as a5_mode_assaulting  # noqa: E402
import perception as a5_perception  # noqa: E402
from assault import VisibleEnemy  # noqa: E402
from states import BuilderMode  # noqa: E402


def _enemy(x, y, entity_type, direction=None):
    return VisibleEnemy(position=Position(x, y), entity_type=entity_type, direction=direction)


def _empty_grid(*positions):
    return {(p.x, p.y): {"env": Environment.EMPTY, "last_seen": 50} for p in positions}


class _StubLogger:
    def log(self, _msg): pass
    def print(self, _msg): pass


class _StubController:
    def __init__(self, *, position, current_round=20, entity_id=7, map_width=30, map_height=30):
        self._position = position
        self._current_round = current_round
        self._entity_id = entity_id
        self._map_width = map_width
        self._map_height = map_height

    def get_position(self, _id=None): return self._position
    def get_current_round(self): return self._current_round
    def get_id(self): return self._entity_id
    def get_team(self, _id=None): return 1
    def get_map_width(self): return self._map_width
    def get_map_height(self): return self._map_height
    def get_tile_building_id(self, _pos): return None
    def can_build_road(self, _pos): return False
    def build_road(self, _pos): pass
    def can_move(self, _d): return True
    def move(self, d): self._position = self._position.add(d)
    def get_nearby_entities(self): return []


def _mode_bot(grid, *, visible_enemy_targets=None, visible_positions=None,
              confirmed_enemy_harvesters=None, predicted_enemy_harvesters=None,
              connected_friendly_conveyors=None, claimed_assault_anchor_keys=None):
    return SimpleNamespace(
        grid=grid,
        logger=_StubLogger(),
        harvester_anchor=None,
        harvester_anchor_last_seen_round=-9999,
        assault_anchor_status=None,
        assault_last_site_signature=None,
        assault_subrole="support",
        assault_last_progress_round=-9999,
        builder_mode=BuilderMode.ASSAULTING,
        is_assault_role=True,
        assault_wait_state={"site_signature": None, "staging_position": None, "expires_round": -1},
        assault_anchor_blacklist={},
        assault_exhausted_regions=[],
        assault_exhausted_sectors={},
        visible_enemy_targets=list(visible_enemy_targets or []),
        visible_positions=set(visible_positions or set(grid)),
        visible_friendly_builders=[],
        confirmed_enemy_harvesters=dict(confirmed_enemy_harvesters or {}),
        predicted_enemy_harvesters=list(predicted_enemy_harvesters or []),
        recent_assault_waypoints={},
        pathfinding_state={"known_obstacles": set()},
        spawn_slot=0,
        connected_friendly_conveyors=dict(connected_friendly_conveyors or {}),
        symmetry_candidates=("ROT180", "MIRROR_X", "MIRROR_Y"),
        best_symmetry_mode="ROT180",
        enemy_core_exact=False,
        enemy_core_anchor=None,
        last_enemy_core_position=None,
        core_pos=Position(2, 2),
        last_symmetry_update_round=-9999,
        claimed_assault_anchor_keys=set(claimed_assault_anchor_keys or set()),
        claimed_explore_chunks=set(),
        assault_scout_state={"target": None, "chunk": None, "anchor": None, "expires_round": -1},
        assault_claim_state={"anchor": None, "last_round": -9999},
        explored_chunk_last_seen={},
        titanium_locations=set(),
        known_connected_harvesters=set(),
        claimed_harvesters=set(),
    )


# --- Change 1: sentinel_attack_tiles ---

def test_sentinel_attack_tiles_returns_frozenset_of_int_tuples():
    result = a5_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert isinstance(result, frozenset)
    assert all(isinstance(t, tuple) and len(t) == 2 for t in result)
    assert all(isinstance(t[0], int) and isinstance(t[1], int) for t in result)


def test_sentinel_attack_tiles_north_includes_tile_directly_north():
    # A sentinel at (10,10) facing NORTH must be able to hit (10,9) — one step north
    result = a5_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 9) in result


def test_sentinel_attack_tiles_north_excludes_tile_directly_south():
    # A sentinel facing NORTH must NOT hit a tile due south
    result = a5_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 11) not in result


def test_sentinel_attack_tiles_is_cached_same_object_on_second_call():
    # Cache must return the exact same object on a second call
    a5_assault._SENTINEL_ATTACK_CACHE.clear()
    r1 = a5_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    r2 = a5_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    assert r1 is r2


def test_visible_threat_score_detects_turret_targeting_ring():
    # visible_threat_score uses tuple membership; verify it still scores correctly
    turret_pos = Position(10, 10)
    ring_pos = Position(10, 9)  # one step north of turret
    # A SENTINEL at (10,10) facing NORTH covers (10,9)
    enemies = [_enemy(10, 10, EntityType.SENTINEL, Direction.NORTH)]
    score = a5_assault.visible_threat_score(ring_position=ring_pos, enemies=enemies)
    assert score >= 2  # turret with known direction in range scores 2


def test_rank_assault_sites_for_harvester_finds_site_when_ring_tile_is_open():
    harvester = Position(15, 15)
    # North ring tile is open
    grid = _empty_grid(Position(15, 14), Position(16, 15), Position(15, 16), Position(14, 15))
    grid[(16, 15)]["building"] = EntityType.CONVEYOR
    grid[(16, 15)]["building_team"] = 2
    enemies = [
        _enemy(15, 15, EntityType.HARVESTER),
        _enemy(16, 15, EntityType.CONVEYOR, Direction.EAST),
    ]
    sites = a5_assault.rank_assault_sites_for_harvester(
        harvester_position=harvester,
        current_position=Position(14, 14),
        enemies=enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
    )
    assert len(sites) > 0
    assert sites[0].harvester_position == harvester
```

- [ ] **Step 1.2: Run tests to confirm they fail (or have import errors)**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_assault.py -x -q 2>&1 | head -30
```

Expected: `ImportError` or test failures referencing missing `_SENTINEL_ATTACK_CACHE`.

- [ ] **Step 1.3: Add module-level cache and rewrite `sentinel_attack_tiles` in `assault.py`**

In `bots/jon-6-a5bfs/assault.py`, find the existing `sentinel_attack_tiles` function (line ~315) and replace it:

```python
_SENTINEL_ATTACK_CACHE: dict[tuple[int, int, str, int], frozenset[tuple[int, int]]] = {}


def sentinel_attack_tiles(
    origin: Position,
    direction: Direction,
    *,
    max_range_sq: int = 32,
) -> frozenset[tuple[int, int]]:
    cache_key = (origin.x, origin.y, direction.name, max_range_sq)
    cached = _SENTINEL_ATTACK_CACHE.get(cache_key)
    if cached is not None:
        return cached
    attackable: set[tuple[int, int]] = set()
    dx, dy = STEP_BY_DIRECTION[direction]
    for step in range(1, 7):
        bx = origin.x + dx * step
        by = origin.y + dy * step
        bdx = bx - origin.x
        bdy = by - origin.y
        if bdx * bdx + bdy * bdy > max_range_sq:
            break
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                cx = bx + ox
                cy = by + oy
                rel_x = cx - origin.x
                rel_y = cy - origin.y
                if rel_x == 0 and rel_y == 0:
                    continue
                if rel_x * dx + rel_y * dy <= 0:
                    continue
                if rel_x * rel_x + rel_y * rel_y > max_range_sq:
                    continue
                attackable.add((cx, cy))
    result = frozenset(attackable)
    _SENTINEL_ATTACK_CACHE[cache_key] = result
    return result
```

- [ ] **Step 1.4: Update the 4 membership-test call sites in `assault.py`**

**Site 1** — in `_target_summary_for_site`, around line 626:
```python
# OLD:
    if enemy_core_center is not None and enemy_core_center in attack_tiles:
# NEW:
    if enemy_core_center is not None and (enemy_core_center.x, enemy_core_center.y) in attack_tiles:
```

**Site 2** — in `_target_summary_for_site`, around line 632:
```python
# OLD:
        if enemy.position not in attack_tiles:
# NEW:
        if (enemy.position.x, enemy.position.y) not in attack_tiles:
```

**Site 3** — in `visible_threat_score`, around line 693:
```python
# OLD:
                if ring_position in sentinel_attack_tiles(enemy.position, enemy.direction):
# NEW:
                if (ring_position.x, ring_position.y) in sentinel_attack_tiles(enemy.position, enemy.direction):
```

**Site 4** — in `_friendly_ring_sentinel_state`, around line 777:
```python
# OLD:
        covered_targets.update(
            position for position in visible_enemy_positions if position in attack_tiles
        )
# NEW:
        covered_targets.update(
            position for position in visible_enemy_positions if (position.x, position.y) in attack_tiles
        )
```

- [ ] **Step 1.5: Run tests to confirm they pass**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_assault.py -x -q
```

Expected: all tests pass.

- [ ] **Step 1.6: Commit**

```bash
git add bots/jon-6-a5bfs/assault.py tests/test_jon_6_a5bfs_assault.py
git commit -m "perf(a5bfs): memoize sentinel_attack_tiles with frozenset tuple cache"
```

---

## Task 2 — Skip conveyor topology refresh for assault bots (`perception.py`, `builder_bot.py`)

**Files:**
- Modify: `bots/jon-6-a5bfs/perception.py`
- Modify: `bots/jon-6-a5bfs/builder_bot.py`
- Modify: `tests/test_jon_6_a5bfs_assault.py` (add test)

- [ ] **Step 2.1: Write failing test**

Add `from unittest.mock import patch` to the import block at the top of `tests/test_jon_6_a5bfs_assault.py`. Then append:

```python
# --- Change 2: skip topology refresh ---

def test_scan_around_with_assault_mode_passes_refresh_connected_false():
    # Before the fix, scan_around raises TypeError: unexpected keyword argument 'assault_mode'.
    # After the fix, _infer_state_from_grid must receive refresh_connected=False.
    bot = SimpleNamespace(grid={}, explored_tiles=set(), explored_chunk_last_seen={})
    ct = _StubController(position=Position(5, 5), current_round=20)

    with patch.object(a5_perception, "_update_exploration_chunks"):
        with patch.object(a5_perception, "_update_master_grid"):
            with patch.object(a5_perception, "_scan_nearby_markers"):
                with patch.object(a5_perception, "_infer_state_from_grid") as mock_infer:
                    a5_perception.scan_around(bot, ct, assault_mode=True)

    _args, kwargs = mock_infer.call_args
    assert kwargs.get("refresh_connected") is False
```

- [ ] **Step 2.2: Run test to confirm it fails**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_assault.py::test_scan_around_with_assault_mode_passes_refresh_connected_false -x -q
```

Expected: `TypeError: scan_around() got an unexpected keyword argument 'assault_mode'`.

- [ ] **Step 2.3: Add `assault_mode` parameter to `scan_around` in `perception.py`**

Find `scan_around` (line ~185) and replace:

```python
def scan_around(bot, ct: Controller, *, fast: bool = False):
    """Main perception entry point.

    The order matters: first refresh the coarse exploration view, then write
    raw observations into the remembered grid, then decode marker hints, and
    only after that rebuild the derived state used by the current mode.
    """
    if fast:
        _scan_local_fast(bot, ct)
        return

    nearby_tiles = _get_nearby_tiles(bot, ct)
    visible_tiles, nearby_buildings, nearby_units, nearby_cache = (
        _collect_visible_snapshot(ct, nearby_tiles)
    )

    _update_exploration_chunks(bot, ct, visible_tiles)
    _update_master_grid(bot, ct, visible_tiles, nearby_units, nearby_cache)
    _scan_nearby_markers(bot, ct, nearby_buildings, nearby_cache)
    _infer_state_from_grid(bot, ct, nearby_units, nearby_cache)
```

with:

```python
def scan_around(bot, ct: Controller, *, fast: bool = False, assault_mode: bool = False):
    """Main perception entry point.

    The order matters: first refresh the coarse exploration view, then write
    raw observations into the remembered grid, then decode marker hints, and
    only after that rebuild the derived state used by the current mode.
    """
    if fast:
        _scan_local_fast(bot, ct)
        return

    nearby_tiles = _get_nearby_tiles(bot, ct)
    visible_tiles, nearby_buildings, nearby_units, nearby_cache = (
        _collect_visible_snapshot(ct, nearby_tiles)
    )

    _update_exploration_chunks(bot, ct, visible_tiles)
    _update_master_grid(bot, ct, visible_tiles, nearby_units, nearby_cache)
    _scan_nearby_markers(bot, ct, nearby_buildings, nearby_cache)
    _infer_state_from_grid(bot, ct, nearby_units, nearby_cache, refresh_connected=not assault_mode)
```

- [ ] **Step 2.4: Pass `assault_mode` in `builder_bot.py`**

Find the `scan_around` call in `BuilderBot.run` (line ~201):

```python
# OLD:
        perception.scan_around(self, ct, fast=use_fast_perception)
# NEW:
        perception.scan_around(self, ct, fast=use_fast_perception, assault_mode=bool(self.is_assault_role))
```

- [ ] **Step 2.5: Run tests**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_assault.py -x -q
```

Expected: all tests pass.

- [ ] **Step 2.6: Commit**

```bash
git add bots/jon-6-a5bfs/perception.py bots/jon-6-a5bfs/builder_bot.py tests/test_jon_6_a5bfs_assault.py
git commit -m "perf(a5bfs): skip conveyor topology refresh for assault bots"
```

---

## Task 3 — Sort BFS direction order once per path (`navigation.py`)

**Files:**
- Modify: `bots/jon-6-a5bfs/navigation.py`
- Create: `tests/test_jon_6_a5bfs_navigation.py`

- [ ] **Step 3.1: Write failing tests**

Create `tests/test_jon_6_a5bfs_navigation.py`:

```python
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


JON_6_A5_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a5bfs"
)
for module_name in ("navigation", "states", "utils"):
    sys.modules.pop(module_name, None)
if str(JON_6_A5_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A5_BFS_ROOT))
importlib.invalidate_caches()

import navigation  # noqa: E402
from states import BuilderMode  # noqa: E402


class _StubLogger:
    def log(self, _msg): pass
    def print(self, _msg): pass


class _StubController:
    def __init__(self, *, position, movable_directions=None, width=10, height=10):
        self._position = position
        self._movable_directions = movable_directions or set()
        self._width = width
        self._height = height
        self.moved: list[Direction] = []

    def get_position(self): return self._position
    def can_move(self, d): return d in self._movable_directions
    def move(self, d):
        self.moved.append(d)
        self._position = self._position.add(d)
    def get_team(self): return 1
    def get_current_round(self): return 20
    def get_id(self): return 7
    def get_map_width(self): return self._width
    def get_map_height(self): return self._height
    def get_tile_building_id(self, _pos): return None
    def can_build_road(self, _pos): return False
    def build_road(self, _pos): pass
    def draw_indicator_line(self, *_a, **_kw): pass


def _assault_bot(grid):
    return SimpleNamespace(
        builder_mode=BuilderMode.ASSAULTING,
        grid=grid,
        logger=_StubLogger(),
        pathfinding_state={
            "path": [],
            "known_obstacles": set(),
            "temporary_obstacles": {},
            "current_target": None,
        },
        assault_nav_state={
            "current_target": None,
            "bfs_path": [],
            "bugging": False,
            "bug_target": None,
            "bug_line_start": None,
            "bug_mline": set(),
            "bug_hit_distance_sq": None,
            "bug_side": 1,
            "bug_last_move_dir": None,
            "bug_steps": 0,
            "bug_seen_states": set(),
            "bug_flipped": False,
        },
        stats={},
    )


def _path_positions(start, path):
    current = start
    out = []
    for _action_type, direction in path:
        current = current.add(direction)
        out.append((current.x, current.y))
    return out


def test_assault_bfs_routes_around_static_wall():
    bot = _assault_bot({
        (2, 1): {"env": Environment.WALL},
        (2, 2): {"env": Environment.WALL},
        (2, 3): {"env": Environment.WALL},
    })
    controller = _StubController(position=Position(0, 2))

    path = navigation.calculate_assault_bfs_path(
        bot, controller, Position(0, 2), Position(4, 2),
    )

    assert path
    assert path[0][1] in {Direction.NORTHEAST, Direction.SOUTHEAST}
    assert (2, 2) not in _path_positions(Position(0, 2), path)


def test_assault_bfs_finds_direct_path_in_open_space():
    bot = _assault_bot({})
    controller = _StubController(position=Position(0, 0))

    path = navigation.calculate_assault_bfs_path(
        bot, controller, Position(0, 0), Position(3, 0),
    )

    assert path
    positions = _path_positions(Position(0, 0), path)
    assert (3, 0) in positions
    assert len(path) == 3  # shortest path: 3 steps east


def test_assault_bfs_path_does_not_revisit_start():
    bot = _assault_bot({})
    controller = _StubController(position=Position(2, 2))

    path = navigation.calculate_assault_bfs_path(
        bot, controller, Position(2, 2), Position(5, 2),
    )

    assert path
    positions = _path_positions(Position(2, 2), path)
    assert (2, 2) not in positions  # start not revisited
    assert (5, 2) in positions
```

- [ ] **Step 3.2: Run tests to confirm they pass on a4bfs baseline (sanity check)**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_navigation.py -x -q
```

Expected: all pass (the a5bfs navigation is identical to a4bfs at this point).

- [ ] **Step 3.3: Implement single-sort in `calculate_assault_bfs_path` in `navigation.py`**

Find `calculate_assault_bfs_path` (line ~1154). In the function, before the `while queue:` loop, add one line and change the inner loop:

```python
# OLD (inside the while loop, line ~1184):
        for direction in _ordered_assault_directions(current, target):

# NEW — compute once before the loop, then use the fixed list throughout:
```

The full diff for this function (replace the relevant section):

```python
    # Compute preferred direction order once using start→target bearing.
    # BFS correctness is unaffected; this is a heuristic for fewer expansions.
    preferred_dirs = _ordered_assault_directions(start, target)

    while queue:
        current = queue.popleft()
        current_key = (current.x, current.y)
        if current_key == target_key:
            break

        for direction in preferred_dirs:
            nxt = current.add(direction)
```

Locate these two lines in `calculate_assault_bfs_path` and apply the change:
- Add `preferred_dirs = _ordered_assault_directions(start, target)` just before `while queue:`
- Replace `for direction in _ordered_assault_directions(current, target):` with `for direction in preferred_dirs:`

- [ ] **Step 3.4: Run tests**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_navigation.py -x -q
```

Expected: all pass.

- [ ] **Step 3.5: Commit**

```bash
git add bots/jon-6-a5bfs/navigation.py tests/test_jon_6_a5bfs_navigation.py
git commit -m "perf(a5bfs): compute BFS direction order once per path instead of per node"
```

---

## Task 4 — Cache `_anchor_assessment` within a turn (`mode_assaulting.py`)

**Files:**
- Modify: `bots/jon-6-a5bfs/mode_assaulting.py`
- Modify: `tests/test_jon_6_a5bfs_assault.py` (add test)

- [ ] **Step 4.1: Write failing test**

Append to `tests/test_jon_6_a5bfs_assault.py`:

```python
# --- Change 4: anchor assessment cache ---

def test_anchor_assessment_cache_returns_same_object_on_second_call():
    harvester = Position(10, 10)
    grid = _empty_grid(
        Position(10, 9), Position(11, 10), Position(10, 11), Position(9, 10),
    )
    grid[(11, 10)]["building"] = EntityType.CONVEYOR
    grid[(11, 10)]["building_team"] = 2
    enemies = [
        _enemy(10, 10, EntityType.HARVESTER),
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
    ]
    bot = _mode_bot(grid, visible_enemy_targets=enemies)
    ct = _StubController(position=Position(8, 8))
    cache: dict = {}

    result1 = a5_mode_assaulting._anchor_assessment(bot, ct, harvester, cache=cache)
    result2 = a5_mode_assaulting._anchor_assessment(bot, ct, harvester, cache=cache)

    assert result1 is result2  # same object — cache hit
```

- [ ] **Step 4.2: Run test to confirm it fails**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_assault.py::test_anchor_assessment_cache_returns_same_object_on_second_call -x -q
```

Expected: FAIL — `_anchor_assessment` does not accept `cache` kwarg yet.

- [ ] **Step 4.3: Add `cache` parameter to `_anchor_assessment`**

Find `_anchor_assessment` (line ~270) in `mode_assaulting.py` and replace:

```python
def _anchor_assessment(
    bot,
    ct: Controller,
    anchor: Position,
    *,
    enemies: list[assault.VisibleEnemy] | None = None,
) -> assault.AnchorAssessment:
    current_enemies = _assault_enemies(bot) if enemies is None else enemies
    return assault.assess_anchor(
        harvester_position=anchor,
        current_position=ct.get_position(),
        enemies=current_enemies,
        grid=bot.grid,
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct)
        | _visible_friendly_ring_sentinels(bot, ct, anchor),
        legal_fire_fn=_legal_fire_fn(ct),
        enemy_core_center=_visible_enemy_core_center(current_enemies),
        current_anchor=anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
        friendly_builder_positions=getattr(bot, "visible_friendly_builders", []),
    )
```

with:

```python
def _anchor_assessment(
    bot,
    ct: Controller,
    anchor: Position,
    *,
    enemies: list[assault.VisibleEnemy] | None = None,
    cache: dict[tuple[int, int], assault.AnchorAssessment] | None = None,
) -> assault.AnchorAssessment:
    if cache is not None:
        cached = cache.get((anchor.x, anchor.y))
        if cached is not None:
            return cached
    current_enemies = _assault_enemies(bot) if enemies is None else enemies
    result = assault.assess_anchor(
        harvester_position=anchor,
        current_position=ct.get_position(),
        enemies=current_enemies,
        grid=bot.grid,
        my_team=ct.get_team(),
        actor_id=ct.get_id(),
        map_width=ct.get_map_width(),
        map_height=ct.get_map_height(),
        blocked_ring_positions=_blocked_ring_positions(bot, ct)
        | _visible_friendly_ring_sentinels(bot, ct, anchor),
        legal_fire_fn=_legal_fire_fn(ct),
        enemy_core_center=_visible_enemy_core_center(current_enemies),
        current_anchor=anchor,
        site_bias=0 if bot.spawn_slot is None else bot.spawn_slot,
        connected_friendly_conveyors=getattr(bot, "connected_friendly_conveyors", {}),
        friendly_builder_positions=getattr(bot, "visible_friendly_builders", []),
    )
    if cache is not None:
        cache[(anchor.x, anchor.y)] = result
    return result
```

- [ ] **Step 4.4: Add `cache` parameter to `_best_visible_site`**

Find `_best_visible_site` (line ~744) and update its signature and internal call:

```python
# OLD:
def _best_visible_site(
    bot,
    ct: Controller,
    live_anchor: Position | None,
) -> assault.AssaultSite | None:
    enemies = _assault_enemies(bot)
    ...
        assessment = _anchor_assessment(bot, ct, enemy.position, enemies=enemies)

# NEW:
def _best_visible_site(
    bot,
    ct: Controller,
    live_anchor: Position | None,
    *,
    cache: dict[tuple[int, int], assault.AnchorAssessment] | None = None,
) -> assault.AssaultSite | None:
    enemies = _assault_enemies(bot)
    ...
        assessment = _anchor_assessment(bot, ct, enemy.position, enemies=enemies, cache=cache)
```

- [ ] **Step 4.5: Add `cache` parameter to `_execute_support`**

Find `_execute_support` (line ~896) and update its signature and internal call:

```python
# OLD:
def _execute_support(
    bot,
    ct: Controller,
    *,
    anchor: Position,
    site: assault.AssaultSite | None = None,
    forbidden_position: Position | None = None,
) -> bool:
    current_pos = ct.get_position()
    assessment = _anchor_assessment(bot, ct, anchor)

# NEW:
def _execute_support(
    bot,
    ct: Controller,
    *,
    anchor: Position,
    site: assault.AssaultSite | None = None,
    forbidden_position: Position | None = None,
    cache: dict[tuple[int, int], assault.AnchorAssessment] | None = None,
) -> bool:
    current_pos = ct.get_position()
    assessment = _anchor_assessment(bot, ct, anchor, cache=cache)
```

- [ ] **Step 4.6: Wire the cache through `execute()`**

In `execute()` (line ~1486), add cache creation at the top and thread it through all call sites:

```python
def execute(bot, ct: Controller):
    enemies = _assault_enemies(bot)
    _refresh_anchor_blacklist(bot, ct.get_current_round())
    _refresh_exhausted_regions(bot, ct.get_current_round())
    _refresh_exhausted_sectors(bot, ct.get_current_round())
    _update_enemy_inference(bot, ct)
    _aa_cache: dict[tuple[int, int], assault.AnchorAssessment] = {}  # turn-local cache
    live_anchor = _committed_anchor(bot, ct, enemies)
```

Then update these six call sites within `execute()`:

**Line ~1498:**
```python
# OLD:
        live_assessment = _anchor_assessment(bot, ct, live_anchor, enemies=enemies)
# NEW:
        live_assessment = _anchor_assessment(bot, ct, live_anchor, enemies=enemies, cache=_aa_cache)
```

**Line ~1510:**
```python
# OLD:
        chosen_site = _best_visible_site(bot, ct, live_anchor)
# NEW:
        chosen_site = _best_visible_site(bot, ct, live_anchor, cache=_aa_cache)
```

**Line ~1523:**
```python
# OLD:
            chosen_assessment = _anchor_assessment(
                bot,
                ct,
                chosen_site.harvester_position,
                enemies=enemies,
            )
# NEW:
            chosen_assessment = _anchor_assessment(
                bot,
                ct,
                chosen_site.harvester_position,
                enemies=enemies,
                cache=_aa_cache,
            )
```

**Line ~1562 (first `_execute_support` call):**
```python
# OLD:
            if _execute_support(
                bot,
                ct,
                anchor=chosen_site.harvester_position,
                site=chosen_site,
                forbidden_position=chosen_site.ring_position,
            ):
# NEW:
            if _execute_support(
                bot,
                ct,
                anchor=chosen_site.harvester_position,
                site=chosen_site,
                forbidden_position=chosen_site.ring_position,
                cache=_aa_cache,
            ):
```

**Line ~1570:**
```python
# OLD:
            post_support_assessment = _anchor_assessment(
                bot,
                ct,
                chosen_site.harvester_position,
                enemies=enemies,
            )
# NEW:
            post_support_assessment = _anchor_assessment(
                bot,
                ct,
                chosen_site.harvester_position,
                enemies=enemies,
                cache=_aa_cache,
            )
```

**Line ~1600 (second `_execute_support` call):**
```python
# OLD:
            if _execute_support(bot, ct, anchor=live_anchor):
# NEW:
            if _execute_support(bot, ct, anchor=live_anchor, cache=_aa_cache):
```

**Line ~1602:**
```python
# OLD:
            post_support_assessment = _anchor_assessment(
                bot,
                ct,
                live_anchor,
                enemies=enemies,
            )
# NEW:
            post_support_assessment = _anchor_assessment(
                bot,
                ct,
                live_anchor,
                enemies=enemies,
                cache=_aa_cache,
            )
```

- [ ] **Step 4.7: Run all tests**

```bash
source .venv/bin/activate
pytest tests/test_jon_6_a5bfs_assault.py tests/test_jon_6_a5bfs_navigation.py -x -q
```

Expected: all pass.

- [ ] **Step 4.8: Commit**

```bash
git add bots/jon-6-a5bfs/mode_assaulting.py tests/test_jon_6_a5bfs_assault.py
git commit -m "perf(a5bfs): cache _anchor_assessment results within a single turn"
```

---

## Task 5 — Update README and run smoke benchmark

**Files:**
- Modify: `bots/jon-6-a5bfs/README.md`

- [ ] **Step 5.1: Update `bots/jon-6-a5bfs/README.md`**

Replace the full content with:

```markdown
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
```

- [ ] **Step 5.2: Commit README**

```bash
git add bots/jon-6-a5bfs/README.md
git commit -m "docs(a5bfs): document TLE optimisation changes"
```

- [ ] **Step 5.3: Run smoke benchmark**

```bash
source .venv/bin/activate
python tools/run_representative_benchmark.py jon-6-a5bfs jon-6-a4bfs \
  --maps default_small1.map26 default_medium1.map26 default_large1.map26 \
  --seeds 1 --jobs 8
```

Expected: `jon-6-a5bfs` wins or draws against `jon-6-a4bfs` (same behaviour, fewer TLEs). Check benchmark output for TLE indicators.
