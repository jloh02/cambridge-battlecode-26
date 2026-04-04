from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cambc import Direction, EntityType, Environment, Position


DUCK_1_ROOT = Path(__file__).resolve().parent.parent / "bots" / "duck-1"
if str(DUCK_1_ROOT) not in sys.path:
    sys.path.insert(0, str(DUCK_1_ROOT))

import builder_bot  # noqa: E402
import marker  # noqa: E402
import mode_exploring  # noqa: E402
import mode_hijacking  # noqa: E402
import mode_tiling_back  # noqa: E402
import perception  # noqa: E402
from states import BuilderMode, TargetKind  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _cleanup_duck1_modules():
    yield
    for module_name in (
        "builder_bot",
        "logger",
        "marker",
        "mode_exploring",
        "mode_finding_ore",
        "mode_hijacking",
        "mode_tiling_back",
        "navigation",
        "perception",
        "states",
        "utils",
    ):
        sys.modules.pop(module_name, None)
    while str(DUCK_1_ROOT) in sys.path:
        sys.path.remove(str(DUCK_1_ROOT))


class _StubLogger:
    def log(self, _message: str) -> None:
        return

    def print(self, _message: str) -> None:
        return


class _StubController:
    def __init__(self, *, position: Position, round_num: int = 50) -> None:
        self._position = position
        self._round = round_num
        self.placed_markers: list[tuple[Position, int]] = []

    def get_position(self, _entity_id=None) -> Position:
        return self._position

    def get_current_round(self) -> int:
        return self._round

    def get_team(self):
        return 1

    def get_map_width(self) -> int:
        return 20

    def get_map_height(self) -> int:
        return 20

    def get_nearby_entities(self):
        return []

    def get_entity_type(self, _entity_id=None):
        return EntityType.BUILDER_BOT

    def get_tile_env(self, position: Position):
        return Environment.EMPTY

    def can_place_marker(self, _position: Position) -> bool:
        return True

    def place_marker(self, position: Position, marker_value: int) -> None:
        self.placed_markers.append((position, marker_value))


def _new_builder(mode: BuilderMode = BuilderMode.EXPLORING) -> builder_bot.BuilderBot:
    bot = builder_bot.BuilderBot()
    bot.logger = _StubLogger()
    bot.core_pos = Position(2, 2)
    bot.spawn_pos = Position(3, 3)
    bot.builder_mode = mode
    bot.visible_positions = set()
    return bot


def _mark_visible_empty(bot, position: Position, *, round_num: int = 50):
    bot.visible_positions.add((position.x, position.y))
    bot.grid[(position.x, position.y)] = {
        "env": Environment.EMPTY,
        "last_seen": round_num,
        "entity": None,
        "entity_team": None,
        "building": None,
        "building_team": None,
        "building_dir": None,
    }


def _mark_visible_enemy_conveyor(
    bot,
    position: Position,
    *,
    direction: Direction,
    round_num: int = 50,
):
    bot.visible_positions.add((position.x, position.y))
    bot.grid[(position.x, position.y)] = {
        "env": Environment.EMPTY,
        "last_seen": round_num,
        "entity": None,
        "entity_team": None,
        "building": EntityType.CONVEYOR,
        "building_team": 2,
        "building_dir": direction,
    }


def test_friendly_shared_conveyors_do_not_trigger_hijack(monkeypatch):
    bot = _new_builder()
    bot.shared_connected_conveyor_positions.add((7, 7))
    controller = _StubController(position=Position(5, 5))
    explore_calls: list[BuilderMode] = []

    monkeypatch.setattr(perception, "scan_around", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mode_exploring,
        "execute",
        lambda b, _ct: explore_calls.append(b.builder_mode),
    )
    monkeypatch.setattr(mode_hijacking, "execute", lambda *_args, **_kwargs: None)

    bot.run(controller)

    assert bot.builder_mode == BuilderMode.EXPLORING
    assert explore_calls == [BuilderMode.EXPLORING]


def test_visible_enemy_conveyor_transitions_explorer_to_hijacking(monkeypatch):
    bot = _new_builder()
    controller = _StubController(position=Position(5, 5))
    _mark_visible_enemy_conveyor(bot, Position(7, 5), direction=Direction.EAST)
    _mark_visible_empty(bot, Position(8, 5))
    hijack_modes: list[BuilderMode] = []

    monkeypatch.setattr(perception, "scan_around", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mode_hijacking,
        "execute",
        lambda b, _ct: hijack_modes.append(b.builder_mode),
    )

    bot.run(controller)

    assert bot.builder_mode == BuilderMode.HIJACKING
    assert bot.hijack_source_pos == Position(7, 5)
    assert bot.hijack_entry_pos == Position(8, 5)
    assert hijack_modes == [BuilderMode.HIJACKING]


def test_hijack_target_ignores_blocked_enemy_output_tile():
    bot = _new_builder()
    controller = _StubController(position=Position(5, 5))
    _mark_visible_enemy_conveyor(bot, Position(7, 5), direction=Direction.EAST)
    bot.visible_positions.add((8, 5))
    bot.grid[(8, 5)] = {
        "env": Environment.EMPTY,
        "last_seen": controller.get_current_round(),
        "entity": None,
        "entity_team": None,
        "building": EntityType.CONVEYOR,
        "building_team": 2,
        "building_dir": Direction.NORTH,
    }

    assert mode_hijacking.find_visible_hijack_target(bot, controller) is None


def test_hijacking_only_hands_off_after_reaching_entry_tile(monkeypatch):
    bot = _new_builder(BuilderMode.HIJACKING)
    controller = _StubController(position=Position(5, 5))
    _mark_visible_enemy_conveyor(bot, Position(7, 5), direction=Direction.EAST)
    _mark_visible_empty(bot, Position(8, 5))
    moves: list[Position] = []

    monkeypatch.setattr(
        mode_hijacking.navigation,
        "move_towards",
        lambda _bot, _ct, target: moves.append(target) or True,
    )

    mode_hijacking.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.HIJACKING
    assert moves == [Position(8, 5)]

    controller._position = Position(8, 5)
    mode_hijacking.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.TILING_BACK
    assert bot.tiling_back_origin_kind == "HIJACK"
    assert bot.hijack_source_pos is None
    assert bot.hijack_entry_pos is None


def test_hijack_origin_tiling_back_skips_connected_harvester_marker(monkeypatch):
    bot = _new_builder(BuilderMode.TILING_BACK)
    controller = _StubController(position=Position(2, 2))
    bot.tiling_back_origin_kind = "HIJACK"
    bot.last_harvester_pos = Position(9, 9)
    bot.pending_build = None
    bot.return_target_pos = Position(2, 2)
    bot.return_target_kind = TargetKind.CORE
    bot.return_target_dist_manhatten = 0
    bot.last_return_target_refresh_round = controller.get_current_round()
    bot.connected_friendly_conveyors = {}
    bot.shared_connected_harvester_positions = set()
    harvester_marker_calls: list[Position] = []

    monkeypatch.setattr(
        marker,
        "create_connected_harvester_marker",
        lambda harvester_pos, *_args, **_kwargs: harvester_marker_calls.append(harvester_pos) or 1,
    )

    mode_tiling_back.execute(bot, controller)

    assert bot.builder_mode == BuilderMode.FINDING_ORE
    assert harvester_marker_calls == []
    assert bot.last_harvester_pos == Position(9, 9)
    assert bot.shared_connected_harvester_positions == set()
