from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    def get_nearby_tiles(self): return []
    def get_nearby_units(self): return []


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
    result = a5_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 9) in result


def test_sentinel_attack_tiles_north_excludes_tile_directly_south():
    result = a5_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 11) not in result


def test_sentinel_attack_tiles_is_cached_same_object_on_second_call():
    a5_assault._SENTINEL_ATTACK_CACHE.clear()
    r1 = a5_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    r2 = a5_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    assert r1 is r2


def test_visible_threat_score_detects_turret_targeting_ring():
    ring_pos = Position(10, 9)
    enemies = [_enemy(10, 10, EntityType.SENTINEL, Direction.NORTH)]
    score = a5_assault.visible_threat_score(ring_position=ring_pos, enemies=enemies)
    assert score >= 2


def test_rank_assault_sites_for_harvester_finds_site_when_ring_tile_is_open():
    harvester = Position(15, 15)
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
