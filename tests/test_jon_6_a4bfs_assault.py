from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


JON_6_A4_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-6-a4bfs"
)
for module_name in (
    "assault",
    "marker",
    "mode_assaulting",
    "navigation",
    "perception",
    "utils",
):
    sys.modules.pop(module_name, None)
if str(JON_6_A4_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_6_A4_BFS_ROOT))
importlib.invalidate_caches()

import mode_assaulting as a4_mode_assaulting  # noqa: E402
import perception as a4_perception  # noqa: E402
from assault import AssaultSite, SiteTarget, VisibleEnemy  # noqa: E402
from states import BuilderMode  # noqa: E402


def _enemy(
    x: int,
    y: int,
    entity_type: EntityType,
    direction: Direction | None = None,
) -> VisibleEnemy:
    return VisibleEnemy(
        position=Position(x, y),
        entity_type=entity_type,
        direction=direction,
    )


def _empty_grid(*positions: Position) -> dict[tuple[int, int], dict]:
    return {
        (position.x, position.y): {"env": Environment.EMPTY, "last_seen": 50}
        for position in positions
    }


class _StubLogger:
    def log(self, _message: str) -> None:
        return


class _StubController:
    def __init__(
        self,
        *,
        position: Position,
        current_round: int = 20,
        entity_id: int = 7,
        map_width: int = 30,
        map_height: int = 30,
    ) -> None:
        self._position = position
        self._current_round = current_round
        self._entity_id = entity_id
        self._map_width = map_width
        self._map_height = map_height

    def get_position(self) -> Position:
        return self._position

    def get_current_round(self) -> int:
        return self._current_round

    def get_id(self) -> int:
        return self._entity_id

    def get_team(self) -> int:
        return 1

    def get_map_width(self) -> int:
        return self._map_width

    def get_map_height(self) -> int:
        return self._map_height

    def get_tile_building_id(self, _pos: Position):
        return None

    def can_build_road(self, _pos: Position) -> bool:
        return False

    def build_road(self, _pos: Position) -> None:
        return

    def can_move(self, _direction: Direction) -> bool:
        return True

    def move(self, direction: Direction) -> None:
        self._position = self._position.add(direction)


def _mode_bot(
    grid: dict[tuple[int, int], dict],
    *,
    visible_enemy_targets=None,
    visible_positions=None,
    confirmed_enemy_harvesters=None,
    predicted_enemy_harvesters=None,
    connected_friendly_conveyors=None,
    claimed_assault_anchor_keys=None,
):
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
        assault_wait_state={
            "site_signature": None,
            "staging_position": None,
            "expires_round": -1,
        },
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
        assault_scout_state={
            "target": None,
            "chunk": None,
            "anchor": None,
            "expires_round": -1,
        },
        assault_claim_state={
            "anchor": None,
            "last_round": -9999,
        },
        explored_chunk_last_seen={},
        titanium_locations=set(),
        known_connected_harvesters=set(),
        claimed_harvesters=set(),
    )


def test_best_visible_site_ignores_blacklisted_visible_anchor():
    harvester_a = Position(10, 10)
    harvester_b = Position(20, 20)
    grid = _empty_grid(
        Position(10, 9),
        Position(11, 10),
        Position(10, 11),
        Position(9, 10),
        Position(20, 19),
        Position(21, 20),
        Position(20, 21),
        Position(19, 20),
    )
    grid[(11, 10)]["building"] = EntityType.CONVEYOR
    grid[(11, 10)]["building_team"] = 2
    grid[(21, 20)]["building"] = EntityType.CONVEYOR
    grid[(21, 20)]["building_team"] = 2
    enemies = [
        _enemy(10, 10, EntityType.HARVESTER),
        _enemy(11, 10, EntityType.CONVEYOR, Direction.EAST),
        _enemy(20, 20, EntityType.HARVESTER),
        _enemy(21, 20, EntityType.CONVEYOR, Direction.EAST),
    ]
    bot = _mode_bot(grid, visible_enemy_targets=enemies)
    bot.assault_anchor_blacklist[(harvester_a.x, harvester_a.y)] = 60
    controller = _StubController(position=Position(11, 12), current_round=20)

    site = a4_mode_assaulting._best_visible_site(bot, controller, live_anchor=None)

    assert site is not None
    assert site.harvester_position == harvester_b


def test_cached_scout_target_stays_committed_until_reached_exact_tile():
    target = Position(10, 10)
    grid = _empty_grid(target)
    bot = _mode_bot(grid)
    bot.assault_scout_state = {
        "target": (target.x, target.y),
        "chunk": a4_mode_assaulting._chunk_key(target),
        "anchor": None,
        "expires_round": 40,
    }
    bot.explored_chunk_last_seen[a4_mode_assaulting._chunk_key(target)] = 20
    controller = _StubController(position=Position(9, 9), current_round=20)

    refreshed = a4_mode_assaulting._cached_scout_target(bot, controller)

    assert refreshed == target
    assert bot.assault_scout_state["target"] == (target.x, target.y)


def test_select_global_enemy_frontier_target_prefers_chunk_closer_to_enemy_core():
    controller = _StubController(
        position=Position(14, 15),
        current_round=20,
        map_width=30,
        map_height=30,
    )
    bot = _mode_bot({})
    bot.core_pos = Position(5, 15)
    bot.enemy_core_anchor = Position(25, 15)

    chunk_cols = (
        controller.get_map_width() + a4_perception.CHUNK_SIZE - 1
    ) // a4_perception.CHUNK_SIZE
    chunk_rows = (
        controller.get_map_height() + a4_perception.CHUNK_SIZE - 1
    ) // a4_perception.CHUNK_SIZE

    home_candidate = None
    enemy_candidate = None
    for chunk_x in range(chunk_cols):
        for chunk_y in range(chunk_rows):
            candidate = a4_mode_assaulting._chunk_center(
                (chunk_x, chunk_y),
                map_width=controller.get_map_width(),
                map_height=controller.get_map_height(),
            )
            if candidate.distance_squared(controller.get_position()) <= (
                a4_perception.CHUNK_SIZE * a4_perception.CHUNK_SIZE
            ):
                continue
            if (
                home_candidate is None
                and candidate.distance_squared(bot.core_pos)
                < candidate.distance_squared(bot.enemy_core_anchor)
                and candidate.x > bot.core_pos.x
            ):
                home_candidate = candidate
            if (
                enemy_candidate is None
                and candidate.distance_squared(bot.enemy_core_anchor)
                < candidate.distance_squared(bot.core_pos)
            ):
                enemy_candidate = candidate
        if home_candidate is not None and enemy_candidate is not None:
            break

    assert home_candidate is not None
    assert enemy_candidate is not None

    blocked = set()
    for chunk_x in range(chunk_cols):
        for chunk_y in range(chunk_rows):
            candidate = a4_mode_assaulting._chunk_center(
                (chunk_x, chunk_y),
                map_width=controller.get_map_width(),
                map_height=controller.get_map_height(),
            )
            key = (candidate.x, candidate.y)
            if key not in {
                (home_candidate.x, home_candidate.y),
                (enemy_candidate.x, enemy_candidate.y),
            }:
                blocked.add(key)
    bot.pathfinding_state["known_obstacles"] = blocked

    target = a4_mode_assaulting._select_global_enemy_frontier_target(
        bot,
        controller,
        anchor_hint=None,
    )

    assert target == enemy_candidate


def test_clearable_ring_engagement_blocks_local_stall():
    anchor = Position(24, 23)
    ring = Position(23, 23)
    grid = _empty_grid(anchor, ring)
    grid[(ring.x, ring.y)]["building"] = EntityType.CONVEYOR
    grid[(ring.x, ring.y)]["building_team"] = 2
    bot = _mode_bot(grid)
    bot.assault_last_progress_round = 0
    controller = _StubController(position=ring, current_round=20)
    site = AssaultSite(
        harvester_position=anchor,
        ring_position=ring,
        sentinel_direction=Direction.WEST,
        target=SiteTarget(anchor, EntityType.HARVESTER, 0),
        hits_core_center=False,
        has_high_value_target=False,
        cluster_size=1,
        usable_sides=1,
        immediate_open_sides=1,
        turns_to_useful_shot=0,
        threatened=False,
        ring_classification="CLEARABLE",
        marginal_value=1,
        uncovered_logistics_gain=1,
        uncovered_target_count=1,
        total_target_value=1,
    )

    assert a4_mode_assaulting._is_locally_stalled(bot, controller, anchor) is True
    assert (
        a4_mode_assaulting._is_locally_stalled_for_site(
            bot,
            controller,
            anchor,
            site=site,
        )
        is False
    )


def test_assault_builder_stays_assault_after_blind_scout_timeout():
    bot = _mode_bot({}, visible_enemy_targets=[])
    bot.titanium_locations = {Position(8, 8)}
    bot.claimed_harvesters = {(8, 8), (9, 8)}
    bot.assault_last_progress_round = 0
    controller = _StubController(position=Position(4, 4), current_round=60)

    a4_mode_assaulting.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.ASSAULTING
    assert bot.is_assault_role is True
    assert bot.spawn_slot == 0
