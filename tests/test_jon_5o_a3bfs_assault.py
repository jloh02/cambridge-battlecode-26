from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cambc import Direction, EntityType, Environment, Position


JON_5O_A3_BFS_ROOT = (
    Path(__file__).resolve().parent.parent / "bots" / "jon-5o-a3bfs"
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
if str(JON_5O_A3_BFS_ROOT) not in sys.path:
    sys.path.insert(0, str(JON_5O_A3_BFS_ROOT))
importlib.invalidate_caches()

import marker as a3_marker  # noqa: E402
import mode_assaulting as a3_mode_assaulting  # noqa: E402
import perception as a3_perception  # noqa: E402
from assault import VisibleEnemy  # noqa: E402


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
        marker_values: dict[int, int] | None = None,
    ) -> None:
        self._position = position
        self._current_round = current_round
        self._entity_id = entity_id
        self._marker_values = marker_values or {}

    def get_position(self) -> Position:
        return self._position

    def get_current_round(self) -> int:
        return self._current_round

    def get_id(self) -> int:
        return self._entity_id

    def get_team(self) -> int:
        return 1

    def get_map_width(self) -> int:
        return 30

    def get_map_height(self) -> int:
        return 30

    def get_marker_value(self, marker_id: int) -> int:
        return self._marker_values[marker_id]


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
        enemy_core_anchor=None,
        core_pos=Position(2, 2),
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
    )


def test_assault_claim_marker_round_trip():
    anchor = Position(14, 9)
    owner_tag = a3_marker.assault_claim_owner_tag(73)
    marker_value = a3_marker.create_assault_claim_marker(
        anchor,
        owner_tag,
        current_round=123,
        map_width=30,
        map_height=30,
    )

    parsed = a3_marker.parse_assault_claim_marker(marker_value, 30, 30)

    assert parsed is not None
    parsed_anchor, parsed_owner_tag, parsed_round = parsed
    assert parsed_anchor == anchor
    assert parsed_owner_tag == owner_tag
    assert parsed_round == 123


def test_scan_nearby_markers_ignores_self_assault_claim():
    my_id = 42
    self_anchor = Position(10, 10)
    other_anchor = Position(20, 20)
    marker_values = {
        1: a3_marker.create_assault_claim_marker(
            self_anchor,
            a3_marker.assault_claim_owner_tag(my_id),
            current_round=40,
            map_width=30,
            map_height=30,
        ),
        2: a3_marker.create_assault_claim_marker(
            other_anchor,
            a3_marker.assault_claim_owner_tag(7),
            current_round=40,
            map_width=30,
            map_height=30,
        ),
    }
    controller = _StubController(
        position=Position(5, 5),
        current_round=40,
        entity_id=my_id,
        marker_values=marker_values,
    )
    bot = _mode_bot({})
    nearby_buildings = [1, 2]
    nearby_cache = {
        1: {"type": EntityType.MARKER, "team": 1},
        2: {"type": EntityType.MARKER, "team": 1},
    }

    a3_perception._scan_nearby_markers(bot, controller, nearby_buildings, nearby_cache)

    assert bot.claimed_assault_anchor_keys == {(other_anchor.x, other_anchor.y)}


def test_best_visible_site_ignores_locally_claimed_harvester():
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
    bot = _mode_bot(
        grid,
        visible_enemy_targets=enemies,
        claimed_assault_anchor_keys={(harvester_a.x, harvester_a.y)},
    )
    controller = _StubController(position=Position(11, 12))

    site = a3_mode_assaulting._best_visible_site(bot, controller, live_anchor=None)

    assert site is not None
    assert site.harvester_position == harvester_b


def test_cached_scout_target_preserves_anchor_hint_when_normalized():
    target = Position(6, 6)
    normalized_target = Position(6, 7)
    anchor = Position(15, 15)
    surrounding = [
        Position(5, 5),
        Position(5, 6),
        Position(5, 7),
        Position(6, 5),
        Position(6, 7),
        Position(7, 5),
        Position(7, 6),
        Position(7, 7),
    ]
    grid = {
        (target.x, target.y): {
            "env": Environment.EMPTY,
            "entity": EntityType.HARVESTER,
            "last_seen": 50,
        }
    }
    for position in surrounding:
        grid[(position.x, position.y)] = {
            "env": Environment.WALL,
            "last_seen": 50,
        }
    grid[(normalized_target.x, normalized_target.y)] = {
        "env": Environment.EMPTY,
        "last_seen": 50,
    }
    bot = _mode_bot(grid)
    bot.assault_scout_state = {
        "target": (target.x, target.y),
        "chunk": None,
        "anchor": (anchor.x, anchor.y),
        "expires_round": 40,
    }
    controller = _StubController(position=Position(4, 4), current_round=20)

    refreshed = a3_mode_assaulting._cached_scout_target(bot, controller)

    assert refreshed == normalized_target
    assert bot.assault_scout_state["target"] == (
        normalized_target.x,
        normalized_target.y,
    )
    assert bot.assault_scout_state["anchor"] == (anchor.x, anchor.y)


def test_execute_drops_locally_claimed_live_anchor_and_scouts_elsewhere(monkeypatch):
    anchor = Position(10, 10)
    scout_target = Position(18, 18)
    bot = _mode_bot({}, claimed_assault_anchor_keys={(anchor.x, anchor.y)})
    bot.harvester_anchor = anchor
    bot.harvester_anchor_last_seen_round = 18
    controller = _StubController(position=Position(5, 5), current_round=20)
    moved_to: list[Position] = []

    monkeypatch.setattr(
        a3_mode_assaulting,
        "_update_enemy_inference",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        a3_mode_assaulting,
        "_choose_scout_target",
        lambda *_args, **_kwargs: scout_target,
    )
    monkeypatch.setattr(
        a3_mode_assaulting,
        "_move_toward",
        lambda _bot, _ct, target, **_kwargs: moved_to.append(target),
    )

    a3_mode_assaulting.execute(bot, controller)

    assert bot.harvester_anchor is None
    assert moved_to == [scout_target]
