from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cambc import Direction, EntityType, Environment, Position


JON_6_A6_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a6bfs"
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
if str(JON_6_A6_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A6_BFS_ROOT))
importlib.invalidate_caches()

import assault as a6_assault  # noqa: E402
import mode_assaulting as a6_mode_assaulting  # noqa: E402
import perception as a6_perception  # noqa: E402
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
        assault_subrole="seek_anchor",
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
        assault_bootstrap_state={"target": None, "expires_round": -1, "blocked_turns": 0},
        assault_opening_escape_complete=True,
        assault_committed_site=None,
        assault_committed_site_round=-9999,
        explored_chunk_last_seen={},
        titanium_locations=set(),
        known_connected_harvesters=set(),
        claimed_harvesters=set(),
        spawn_pos=Position(1, 1),
        turn_profile={},
        last_assault_profile_ring_key=None,
        assault_failed_ring_anchor=None,
        assault_failed_ring_positions=set(),
    )


# --- Change 1: sentinel_attack_tiles ---

def test_sentinel_attack_tiles_returns_frozenset_of_int_tuples():
    result = a6_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert isinstance(result, frozenset)
    assert all(isinstance(t, tuple) and len(t) == 2 for t in result)
    assert all(isinstance(t[0], int) and isinstance(t[1], int) for t in result)


def test_sentinel_attack_tiles_north_includes_tile_directly_north():
    result = a6_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 9) in result


def test_sentinel_attack_tiles_north_excludes_tile_directly_south():
    result = a6_assault.sentinel_attack_tiles(Position(10, 10), Direction.NORTH)
    assert (10, 11) not in result


def test_sentinel_attack_tiles_is_cached_same_object_on_second_call():
    a6_assault._SENTINEL_ATTACK_CACHE.clear()
    r1 = a6_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    r2 = a6_assault.sentinel_attack_tiles(Position(5, 5), Direction.EAST)
    assert r1 is r2


def test_visible_threat_score_detects_turret_targeting_ring():
    ring_pos = Position(10, 9)
    enemies = [_enemy(10, 10, EntityType.SENTINEL, Direction.NORTH)]
    score = a6_assault.visible_threat_score(ring_position=ring_pos, enemies=enemies)
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
    sites = a6_assault.rank_assault_sites_for_harvester(
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

    with patch.object(a6_perception, "_update_exploration_chunks"):
        with patch.object(a6_perception, "_update_master_grid"):
            with patch.object(a6_perception, "_scan_nearby_markers"):
                with patch.object(a6_perception, "_infer_state_from_grid") as mock_infer:
                    a6_perception.scan_around(bot, ct, assault_mode=True)

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

    result1 = a6_mode_assaulting._anchor_assessment(bot, ct, harvester, cache=cache)
    result2 = a6_mode_assaulting._anchor_assessment(bot, ct, harvester, cache=cache)

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

    site = a6_assault.choose_best_site_for_harvester(
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


def test_execute_reuses_committed_site_before_reranking():
    harvester = Position(12, 12)
    ring = Position(12, 11)
    site = a6_assault.AssaultSite(
        harvester_position=harvester,
        ring_position=ring,
        sentinel_direction=Direction.NORTHWEST,
        target=a6_assault.SiteTarget(Position(12, 13), EntityType.CONVEYOR, 1),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=1,
        usable_sides=2,
        immediate_open_sides=2,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification=a6_assault.RING_IMMEDIATE,
        marginal_value=4,
        uncovered_logistics_gain=1,
        uncovered_target_count=1,
        total_target_value=4,
    )
    grid = _empty_grid(ring, Position(13, 12), Position(12, 13), Position(11, 12))
    bot = _mode_bot(grid, visible_enemy_targets=[_enemy(12, 12, EntityType.HARVESTER)])
    bot.assault_committed_site = site
    bot.assault_committed_site_round = 20
    ct = _StubController(position=Position(5, 5), current_round=20)

    with patch.object(a6_mode_assaulting, "_update_enemy_inference"):
        with patch.object(a6_mode_assaulting, "_committed_anchor", return_value=harvester):
            with patch.object(a6_mode_assaulting, "_best_site_for_anchor", side_effect=AssertionError("rerank should not run")):
                with patch.object(a6_mode_assaulting, "_best_visible_claimable_site", side_effect=AssertionError("rerank should not run")):
                    with patch.object(a6_mode_assaulting, "_publish_assault_claim"):
                        with patch.object(a6_mode_assaulting, "_execute_site", return_value=True) as mock_execute:
                            a6_mode_assaulting.execute(bot, ct)

    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[2] == site


def test_execute_uses_opening_escape_before_inference():
    start = Position(5, 5)
    bot = _mode_bot(_empty_grid(start))
    bot.core_pos = Position(6, 6)
    bot.spawn_pos = start
    bot.spawn_slot = 1
    bot.assault_opening_escape_complete = False
    ct = _StubController(position=start, current_round=7)

    with patch.object(
        a6_mode_assaulting,
        "_update_enemy_inference",
        side_effect=AssertionError("opening escape should skip inference"),
    ):
        with patch.object(
            a6_mode_assaulting,
            "_choose_scout_target",
            side_effect=AssertionError("opening escape should skip scout targeting"),
        ):
            a6_mode_assaulting.execute(bot, ct)

    assert ct.get_position() != start
    assert ct.get_position().x <= start.x
    assert ct.get_position().y <= start.y
    assert bot.assault_subrole == "opening_escape"
    target = Position(*bot.assault_bootstrap_state["target"])
    assert target != start
    assert a6_mode_assaulting._in_spawn_shell(bot, ct, position=target) is False


def test_bootstrap_target_for_corner_spawn_is_outside_spawn_shell():
    start = Position(0, 0)
    bot = _mode_bot(_empty_grid(start))
    bot.core_pos = Position(1, 1)
    bot.spawn_pos = start
    bot.spawn_slot = 1
    bot.assault_opening_escape_complete = False
    ct = _StubController(position=start, current_round=7)

    target = a6_mode_assaulting._bootstrap_target(bot, ct)

    assert target is not None
    assert target != start
    assert a6_mode_assaulting._in_spawn_shell(bot, ct, position=target) is False


def test_publish_assault_claim_places_marker_when_anchor_taken():
    bot = _mode_bot(_empty_grid(Position(5, 5)))
    calls = []

    class _MarkerController(_StubController):
        def can_place_marker(self, _pos):
            return True

        def place_marker(self, pos, value):
            calls.append((pos, value))

    ct = _MarkerController(position=Position(5, 5), current_round=20)
    anchor = Position(10, 10)

    a6_mode_assaulting._publish_assault_claim(bot, ct, anchor)

    assert calls
    assert bot.assault_claim_state["anchor"] == (10, 10)


def test_move_toward_does_not_random_fallback_when_navigation_fails():
    bot = _mode_bot(_empty_grid(Position(5, 5)))
    ct = _StubController(position=Position(5, 5), current_round=20)

    with patch.object(a6_mode_assaulting.navigation, "move_towards", return_value=False):
        with patch.object(a6_mode_assaulting.utils, "move_random", side_effect=AssertionError("random fallback should not run")):
            moved = a6_mode_assaulting._move_toward(bot, ct, Position(9, 9))

    assert moved is False


def test_move_toward_uses_assault_navigation_for_ring_clear_targets():
    bot = _mode_bot(_empty_grid(Position(5, 5)))
    ct = _StubController(position=Position(5, 5), current_round=20)

    with patch.object(
        a6_mode_assaulting.navigation,
        "assault_move_towards",
        return_value=True,
    ) as mock_assault_move:
        moved = a6_mode_assaulting._move_toward(
            bot,
            ct,
            Position(9, 9),
            allow_enemy_builder_at_target=True,
        )

    assert moved is True
    mock_assault_move.assert_called_once()


def test_choose_scout_target_prefers_stable_enemy_anchor_over_rotating_predictions():
    anchor_a = Position(24, 6)
    anchor_b = Position(22, 8)
    predicted = [
        a6_assault.PredictedHarvester(
            position=anchor_a,
            source="CONFIRMED",
            source_rank=0,
            usable_sides=3,
            immediate_open_sides=2,
            clearable_sides=1,
            unseen_sides=0,
            travel_distance=18,
            distance_to_core_anchor=2,
            same_lane=True,
            mode="ROT180",
        ),
        a6_assault.PredictedHarvester(
            position=anchor_b,
            source="MIRRORED_ORE",
            source_rank=2,
            usable_sides=2,
            immediate_open_sides=1,
            clearable_sides=1,
            unseen_sides=0,
            travel_distance=20,
            distance_to_core_anchor=4,
            same_lane=False,
            mode="ROT180",
        ),
    ]
    grid = _empty_grid(anchor_a, anchor_b)
    bot = _mode_bot(
        grid,
        predicted_enemy_harvesters=predicted,
    )
    bot.core_pos = Position(2, 2)
    bot.enemy_core_anchor = Position(24, 4)
    ct = _StubController(position=Position(4, 4), current_round=120)

    target_a = a6_mode_assaulting._choose_scout_target(bot, ct, live_anchor=None)
    chosen_anchor_a = bot.assault_scout_state["anchor"]

    a6_mode_assaulting._clear_scout_state(bot)
    ct_later = _StubController(position=Position(4, 4), current_round=132)
    target_b = a6_mode_assaulting._choose_scout_target(bot, ct_later, live_anchor=None)
    chosen_anchor_b = bot.assault_scout_state["anchor"]

    assert target_a is not None
    assert target_b is not None
    assert target_a.x > bot.core_pos.x
    assert target_b.x > bot.core_pos.x
    assert chosen_anchor_a == chosen_anchor_b
