from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cambc import Direction, EntityType, Environment, Position


JON_6_A7_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a7bfs"
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
if str(JON_6_A7_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A7_BFS_ROOT))
importlib.invalidate_caches()

import assault as a7_assault  # noqa: E402
import mode_assaulting as a7_mode_assaulting  # noqa: E402
import perception as a7_perception  # noqa: E402
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
    def __init__(
        self,
        *,
        position,
        current_round=20,
        entity_id=7,
        map_width=30,
        map_height=30,
        movable_dirs=None,
    ):
        self._position = position
        self._current_round = current_round
        self._entity_id = entity_id
        self._map_width = map_width
        self._map_height = map_height
        self._movable_dirs = None if movable_dirs is None else set(movable_dirs)

    def get_position(self, _id=None): return self._position
    def get_current_round(self): return self._current_round
    def get_id(self): return self._entity_id
    def get_team(self, _id=None): return 1
    def get_map_width(self): return self._map_width
    def get_map_height(self): return self._map_height
    def get_tile_building_id(self, _pos): return None
    def can_build_road(self, _pos): return False
    def build_road(self, _pos): pass
    def can_move(self, direction):
        return self._movable_dirs is None or direction in self._movable_dirs
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
        assault_subrole="scout",
        assault_last_progress_round=-9999,
        builder_mode=BuilderMode.ASSAULTING,
        is_assault_role=True,
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
        symmetry_tile_cache=None,
        symmetry_tile_cache_count=-1,
        enemy_core_exact=False,
        enemy_core_anchor=None,
        last_enemy_core_position=None,
        core_pos=Position(2, 2),
        last_symmetry_update_round=-9999,
        discovery_turns_without_new_ore=0,
        assault_known_ore_count=0,
        claimed_assault_anchor_keys=set(claimed_assault_anchor_keys or set()),
        claimed_explore_chunks=set(),
        assault_scout_state={"target": None, "chunk": None, "anchor": None, "expires_round": -1},
        assault_claim_state={"anchor": None, "last_round": -9999},
        assault_bootstrap_state={"target": None, "expires_round": -1, "blocked_turns": 0},
        assault_opening_escape_complete=True,
        assault_execute_state={"subplan": None, "anchor": None, "ring": None, "direction": None, "wait_turns": 0, "fire_wait_turns": 0},
        assault_committed_site=None,
        assault_committed_site_round=-9999,
        assault_nav_failure_count=0,
        assault_progress_stall_count=0,
        assault_best_dist_to_ring=9999,
        assault_nav_progress_target=None,
        explored_chunk_last_seen={},
        titanium_locations=set(),
        claimed_harvesters=set(),
        spawn_pos=Position(1, 1),
        turn_profile={},
        last_assault_profile_ring_key=None,
    )


# --- Change 1: sentinel_attack_tiles ---

def test_sentinel_attack_tiles_returns_frozenset_of_int_tuples():
    result = a7_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert isinstance(result, frozenset)
    assert all(isinstance(t, tuple) and len(t) == 2 for t in result)
    assert all(isinstance(t[0], int) and isinstance(t[1], int) for t in result)


def test_sentinel_attack_tiles_north_includes_tile_directly_north():
    result = a7_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 9) in result


def test_sentinel_attack_tiles_north_excludes_tile_directly_south():
    result = a7_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 11) not in result


def test_sentinel_attack_tiles_is_cached_same_object_on_second_call():
    a7_assault._SENTINEL_ATTACK_CACHE.clear()
    r1 = a7_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    r2 = a7_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    assert r1 is r2


def test_visible_threat_score_detects_turret_targeting_ring():
    ring_pos = Position(10, 9)
    enemies = [_enemy(10, 10, EntityType.SENTINEL, Direction.NORTH)]
    score = a7_assault.visible_threat_score(ring_position=ring_pos, enemies=enemies)
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
    sites = a7_assault.rank_assault_sites_for_harvester(
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

    with patch.object(a7_perception, "_update_exploration_chunks"):
        with patch.object(a7_perception, "_update_master_grid"):
            with patch.object(a7_perception, "_scan_nearby_markers"):
                with patch.object(a7_perception, "_infer_state_from_grid") as mock_infer:
                    a7_perception.scan_around(bot, ct, assault_mode=True)

    _args, kwargs = mock_infer.call_args
    assert kwargs.get("refresh_connected") is False


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

    result1 = a7_mode_assaulting._anchor_assessment(bot, ct, harvester, cache=cache)
    result2 = a7_mode_assaulting._anchor_assessment(bot, ct, harvester, cache=cache)

    assert result1 is result2  # same object — cache hit


def test_choose_best_site_for_harvester_does_not_call_legal_fire_fn():
    harvester = Position(15, 15)
    grid = _empty_grid(
        Position(15, 14),
        Position(16, 15),
        Position(15, 16),
        Position(14, 15),
    )
    grid[(16, 15)]["building"] = EntityType.CONVEYOR
    grid[(16, 15)]["building_team"] = 2
    enemies = [
        _enemy(15, 15, EntityType.HARVESTER),
        _enemy(16, 15, EntityType.CONVEYOR, Direction.EAST),
        _enemy(17, 15, EntityType.SENTINEL, Direction.WEST),
    ]

    def _raise_if_called(*_args, **_kwargs):
        raise AssertionError("legal_fire_fn should not be called by the builder planner")

    site = a7_assault.choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(12, 15),
        enemies=enemies,
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        legal_fire_fn=_raise_if_called,
    )

    assert site is not None
    assert site.harvester_position == harvester


def test_publish_assault_claim_uses_assault_marker_helper():
    bot = _mode_bot({})
    ct = _StubController(position=Position(5, 5), current_round=20)
    anchor = Position(12, 12)

    with patch.object(a7_mode_assaulting.utils, "place_marker_around", side_effect=AssertionError("wrong helper")):
        with patch.object(a7_mode_assaulting.utils, "place_assault_marker_around", return_value=True) as mock_place:
            a7_mode_assaulting._publish_assault_claim(bot, ct, anchor)

    mock_place.assert_called_once()
    assert bot.assault_claim_state["anchor"] == (12, 12)


def test_assault_claim_ttl_matches_v2_refresh_contract():
    assert a7_mode_assaulting.ASSAULT_CLAIM_TTL == (
        a7_mode_assaulting.ASSAULT_CLAIM_REFRESH_INTERVAL * 3
    )
    assert a7_perception.ASSAULT_CLAIM_TTL == a7_mode_assaulting.ASSAULT_CLAIM_TTL


def test_candidate_ore_sources_uses_only_titanium_memory():
    bot = _mode_bot({})
    bot.core_pos = Position(0, 0)
    bot.titanium_locations = {
        Position(7, 7),
        Position(1, 0),
        Position(2, 0),
        Position(3, 0),
        Position(4, 0),
        Position(5, 0),
        Position(6, 0),
    }

    result = a7_mode_assaulting._candidate_ore_sources(bot)

    assert Position(1, 0) in result
    assert Position(6, 0) in result
    assert Position(7, 7) not in result
    assert len(result) == 6


def test_assault_module_drops_removed_v2_helpers():
    assert not hasattr(a7_assault, "connected_friendly_harvesters")
    assert not hasattr(a7_assault, "choose_support_harassment_target")
    assert not hasattr(a7_assault, "spread_sweep_target")


def test_force_enemy_half_frontier_does_not_fall_back_to_our_half():
    bot = _mode_bot({})
    bot.core_pos = Position(2, 2)
    bot.enemy_core_anchor = Position(9, 9)
    ct = _StubController(position=Position(2, 2), map_width=12, map_height=12)

    with patch.object(a7_mode_assaulting, "_enemy_half_metrics", return_value=(0, 0)):
        with patch.object(
            a7_mode_assaulting,
            "_normalize_scout_target",
            side_effect=lambda _bot, _ct, pos: pos,
        ):
            target = a7_mode_assaulting._select_enemy_half_frontier_target(
                bot,
                ct,
                anchor_hint=bot.enemy_core_anchor,
            )

    assert target is None


def test_execute_keeps_live_anchor_when_no_site_is_available():
    anchor = Position(10, 10)
    scout_target = Position(14, 14)
    bot = _mode_bot(_empty_grid(Position(5, 5)))
    bot.harvester_anchor = anchor
    bot.harvester_anchor_last_seen_round = 20
    ct = _StubController(position=Position(5, 5), current_round=20)
    live_assessment = SimpleNamespace(status=a7_assault.ANCHOR_LIVE)

    with patch.object(a7_mode_assaulting, "_update_enemy_inference", return_value=None):
        with patch.object(a7_mode_assaulting, "_live_anchor", return_value=anchor):
            with patch.object(a7_mode_assaulting, "_anchor_assessment", return_value=live_assessment):
                with patch.object(
                    a7_mode_assaulting,
                    "_reusable_committed_site",
                    return_value=(None, live_assessment),
                ):
                    with patch.object(a7_mode_assaulting, "_best_site_for_anchor", return_value=None):
                        with patch.object(a7_mode_assaulting, "_best_visible_site", return_value=None):
                            with patch.object(
                                a7_mode_assaulting,
                                "_choose_scout_target",
                                return_value=scout_target,
                            ) as mock_choose:
                                with patch.object(
                                    a7_mode_assaulting.navigation,
                                    "assault_navigate",
                                    return_value=(False, None),
                                ):
                                    with patch.object(
                                        a7_mode_assaulting,
                                        "_retire_anchor",
                                        side_effect=AssertionError(
                                            "live anchor should not be retired as ring_blocked when no site exists"
                                        ),
                                    ):
                                        a7_mode_assaulting.execute(bot, ct)

    assert bot.harvester_anchor == anchor
    assert mock_choose.call_args.kwargs["live_anchor"] == anchor


def test_execute_uses_escape_before_inference():
    start = Position(5, 5)
    bot = _mode_bot(_empty_grid(start))
    bot.core_pos = Position(6, 6)
    bot.spawn_pos = start
    bot.spawn_slot = 1
    bot.assault_opening_escape_complete = False
    ct = _StubController(
        position=start,
        current_round=7,
        movable_dirs={Direction.NORTHWEST},
    )

    with patch.object(
        a7_mode_assaulting,
        "_update_enemy_inference",
        side_effect=AssertionError("escape should skip inference"),
    ):
        a7_mode_assaulting.execute(bot, ct)

    assert ct.get_position() == Position(4, 4)
    assert bot.assault_subrole == "escape"


def test_shell_exit_target_for_corner_spawn_is_outside_shell():
    start = Position(0, 0)
    bot = _mode_bot(_empty_grid(start))
    bot.core_pos = Position(1, 1)
    bot.spawn_pos = start
    bot.spawn_slot = 1
    bot.assault_opening_escape_complete = False
    ct = _StubController(position=start, current_round=7)

    target = a7_mode_assaulting._shell_exit_target(bot, ct)

    assert target is not None
    assert target != start
    assert a7_mode_assaulting._in_spawn_shell(bot, ct, position=target) is False
