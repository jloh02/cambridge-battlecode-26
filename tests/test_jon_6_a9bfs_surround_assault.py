from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


JON_6_A9_BFS_SURROUND_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a9bfs-surround"
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
if str(JON_6_A9_BFS_SURROUND_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A9_BFS_SURROUND_ROOT))
importlib.invalidate_caches()

import assault as surround_assault  # noqa: E402
import mode_assaulting as surround_mode_assaulting  # noqa: E402


def _enemy(x, y, entity_type, direction=None):
    return surround_assault.VisibleEnemy(
        position=Position(x, y),
        entity_type=entity_type,
        direction=direction,
    )


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
        map_width=30,
        map_height=30,
    ):
        self._position = position
        self._current_round = current_round
        self._map_width = map_width
        self._map_height = map_height
        self.fired: list[Position] = []

    def get_position(self, _id=None): return self._position

    def get_current_round(self): return self._current_round

    def get_team(self, _id=None): return 1

    def get_id(self): return 7

    def get_map_width(self): return self._map_width

    def get_map_height(self): return self._map_height

    def can_fire(self, _position): return True

    def fire(self, position): self.fired.append(position)

    def can_move(self, _direction): return False

    def move(self, _direction): raise AssertionError("move should not be called")


def _mode_bot(grid, *, position, predicted_enemy_harvesters=None, visible_positions=None):
    return SimpleNamespace(
        grid=grid,
        logger=_StubLogger(),
        harvester_anchor=Position(10, 10),
        harvester_anchor_last_seen_round=20,
        assault_anchor_status=None,
        assault_last_site_signature=None,
        assault_subrole="execute",
        assault_last_progress_round=-9999,
        assault_anchor_blacklist={},
        assault_exhausted_regions=[],
        assault_exhausted_sectors={},
        visible_enemy_targets=[],
        visible_positions=set(visible_positions or set(grid)),
        visible_friendly_builders=[],
        confirmed_enemy_harvesters={},
        predicted_enemy_harvesters=list(predicted_enemy_harvesters or []),
        recent_assault_waypoints={},
        spawn_slot=0,
        connected_friendly_conveyors={},
        claimed_assault_anchor_keys=set(),
        core_pos=Position(2, 2),
        assault_scout_state={
            "target": None,
            "chunk": None,
            "anchor": None,
            "expires_round": -1,
        },
        assault_claim_state={"anchor": None, "last_round": -9999},
        assault_bootstrap_state={
            "target": None,
            "path": [],
            "expires_round": -1,
            "blocked_turns": 0,
        },
        assault_opening_escape_complete=True,
        assault_execute_state={
            "subplan": "CLEAR_THEN_BUILD",
            "anchor": (10, 10),
            "ring": (position.x, position.y),
            "direction": Direction.EAST.name,
            "wait_turns": 0,
            "fire_wait_turns": 0,
            "clear_attempts": 0,
        },
        assault_committed_site=None,
        assault_committed_site_round=-9999,
        assault_nav_failure_count=0,
        assault_progress_stall_count=0,
        assault_best_dist_to_ring=9999,
        assault_nav_progress_target=None,
        turn_profile={},
    )


def test_classify_ring_site_keeps_bridge_clearable_and_blocks_armoured_and_friendly_conveyors():
    ring_position = Position(11, 10)
    grid = _empty_grid(ring_position)
    grid[(11, 10)]["building"] = EntityType.BRIDGE
    grid[(11, 10)]["building_team"] = 2

    assert surround_assault.classify_ring_site(
        grid=grid,
        ring_position=ring_position,
        map_width=30,
        map_height=30,
        my_team=1,
    ) == surround_assault.RING_CLEARABLE

    grid[(11, 10)]["building"] = EntityType.ARMOURED_CONVEYOR
    assert surround_assault.classify_ring_site(
        grid=grid,
        ring_position=ring_position,
        map_width=30,
        map_height=30,
        my_team=1,
    ) == surround_assault.RING_BLOCKED

    grid[(11, 10)]["building"] = EntityType.CONVEYOR
    grid[(11, 10)]["building_team"] = 1
    assert surround_assault.classify_ring_site(
        grid=grid,
        ring_position=ring_position,
        map_width=30,
        map_height=30,
        my_team=1,
    ) == surround_assault.RING_BLOCKED


def test_harassable_enemy_buildings_keep_bridges_and_skip_armoured_conveyors():
    position = Position(11, 10)
    grid = _empty_grid(position)
    ct = _StubController(position=position)
    bot = _mode_bot(grid, position=position)

    grid[(11, 10)]["building"] = EntityType.BRIDGE
    grid[(11, 10)]["building_team"] = 2
    assert surround_mode_assaulting._is_harassable_enemy_building(bot, ct, position)

    grid[(11, 10)]["building"] = EntityType.ARMOURED_CONVEYOR
    assert not surround_mode_assaulting._is_harassable_enemy_building(bot, ct, position)


def test_choose_best_site_for_harvester_uses_forward_direction_for_surround():
    harvester = Position(15, 15)
    grid = _empty_grid(
        Position(15, 14),
        Position(16, 15),
        Position(15, 16),
        Position(14, 15),
    )
    site = surround_assault.choose_best_site_for_harvester(
        harvester_position=harvester,
        current_position=Position(12, 15),
        enemies=[_enemy(15, 15, EntityType.HARVESTER)],
        map_width=30,
        map_height=30,
        grid=grid,
        my_team=1,
        enemy_core_center=Position(24, 15),
    )

    assert site is not None
    assert site.target.position == harvester
    assert site.target.entity_type == EntityType.HARVESTER
    assert site.ring_position == Position(16, 15)
    assert site.sentinel_direction in {
        Direction.EAST,
        Direction.NORTHEAST,
        Direction.SOUTHEAST,
    }


def test_clear_then_build_retargets_to_offscreen_anchor_after_repeated_clear_attempts():
    current_ring = Position(11, 10)
    alternate_anchor = Position(22, 22)
    grid = _empty_grid(current_ring)
    grid[(11, 10)]["building"] = EntityType.CONVEYOR
    grid[(11, 10)]["building_team"] = 2
    predicted = [
        surround_assault.PredictedHarvester(
            position=alternate_anchor,
            source="MIRRORED_ORE",
            source_rank=surround_assault.SOURCE_RANK["MIRRORED_ORE"],
            usable_sides=4,
            immediate_open_sides=0,
            clearable_sides=0,
            unseen_sides=4,
            travel_distance=24,
            distance_to_core_anchor=20,
            same_lane=False,
            mode="ROT180",
        )
    ]
    bot = _mode_bot(
        grid,
        position=current_ring,
        predicted_enemy_harvesters=predicted,
        visible_positions={(10, 10), (11, 10), (12, 10), (10, 11)},
    )
    ct = _StubController(position=current_ring)
    site = surround_assault.AssaultSite(
        harvester_position=Position(10, 10),
        ring_position=current_ring,
        sentinel_direction=Direction.EAST,
        target=surround_assault.SiteTarget(Position(10, 10), EntityType.HARVESTER, 0),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=1,
        usable_sides=3,
        immediate_open_sides=2,
        turns_to_useful_shot=1,
        threatened=False,
        ring_classification=surround_assault.RING_CLEARABLE,
        marginal_value=1,
        uncovered_logistics_gain=0,
        uncovered_target_count=1,
        total_target_value=1,
    )

    assert surround_mode_assaulting._execute_clear_then_build_subplan(bot, ct, site) is True
    assert bot.assault_execute_state["clear_attempts"] == 1
    assert bot.assault_scout_state["target"] is None

    assert surround_mode_assaulting._execute_clear_then_build_subplan(bot, ct, site) is True

    assert ct.fired == [current_ring, current_ring]
    assert (10, 10) in bot.assault_anchor_blacklist
    assert bot.assault_scout_state["anchor"] == (alternate_anchor.x, alternate_anchor.y)
    assert bot.assault_scout_state["target"] == (alternate_anchor.x, alternate_anchor.y)
    assert bot.harvester_anchor is None
